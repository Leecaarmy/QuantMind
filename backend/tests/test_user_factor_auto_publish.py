"""用户因子训练数据集自动发布（generation + active 指针）语义测试。

企业版对等行为的 OSS 下放验证：
- 发布成功 → published + 指针切换 + 旧版归档；
- 非法结果（row_count/Byte<=0）→ 抛 ValueError，指针不动；
- 显式失败 → failed，指针不动；
- 字段发现表自动 upsert（is_present=TRUE）。

注：用 ``asyncio.run`` 跑异步体（与仓库其它单测一致，不依赖 pytest-asyncio）。
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.shared import user_factor_publish as ufp

FIELD_REGISTRY_DDL = """
CREATE TABLE IF NOT EXISTS qm_quantdb_factor_field (
    market VARCHAR(16) NOT NULL DEFAULT 'CN',
    dataset_id VARCHAR(64) NOT NULL,
    column_name VARCHAR(128) NOT NULL,
    data_type VARCHAR(64),
    schema_hash VARCHAR(128) NOT NULL DEFAULT '',
    min_date DATE,
    max_date DATE,
    is_present BOOLEAN NOT NULL DEFAULT TRUE,
    discovered_at TIMESTAMPTZ,
    PRIMARY KEY (market, dataset_id, column_name)
)
"""


def _run(body):
    async def _main():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with maker() as sess:
                await ufp.ensure_user_factor_schema(sess)
                await sess.execute(text(FIELD_REGISTRY_DDL))
                await sess.commit()
                result = await body(sess)
                await sess.commit()
                return result
        finally:
            await engine.dispose()

    return asyncio.run(_main())


async def _publish_one(sess, feature="alpha_mom_20", rows=100):
    gid = ufp.new_generation_id()
    await ufp.create_building_generation(
        sess,
        generation_id=gid,
        feature_key=feature,
        factor_name=f"factor {feature}",
        expression="Rank($close)",
    )
    return await ufp.publish_completed_generation(
        sess,
        generation_id=gid,
        row_count=rows,
        byte_count=rows * 8,
        manifest_extra={"min_date": "2024-01-02", "max_date": "2024-03-01"},
    )


def test_publish_moves_active_pointer():
    async def _body(sess):
        record = await _publish_one(sess)
        assert record["status"] == "published"
        active = await ufp.get_active_generation(sess)
        assert active is not None
        assert active["generation_id"] == record["generation_id"]
        assert active["status"] == "published"
        assert "alpha_mom_20" in str(active["manifest_json"])

    _run(_body)


def test_second_publish_archives_first():
    async def _body(sess):
        first = await _publish_one(sess, feature="alpha_a")
        second = await _publish_one(sess, feature="alpha_b")
        active = await ufp.get_active_generation(sess)
        assert active["generation_id"] == second["generation_id"]
        statuses = {
            row["generation_id"]: row["status"]
            for row in await ufp.list_generations(sess)
        }
        assert statuses[first["generation_id"]] == "archived"
        assert statuses[second["generation_id"]] == "published"

    _run(_body)


def test_invalid_result_rejected_pointer_unchanged():
    async def _body(sess):
        first = await _publish_one(sess, feature="alpha_a")
        gid = ufp.new_generation_id()
        await ufp.create_building_generation(
            sess, generation_id=gid, feature_key="alpha_bad"
        )
        try:
            await ufp.publish_completed_generation(
                sess, generation_id=gid, row_count=0, byte_count=10
            )
            raise AssertionError("row_count=0 应当被拒绝")
        except ValueError:
            pass
        active = await ufp.get_active_generation(sess)
        assert active["generation_id"] == first["generation_id"]
        by_id = {row["generation_id"]: row for row in await ufp.list_generations(sess)}
        assert by_id[gid]["status"] == "building"

    _run(_body)


def test_failed_generation_keeps_pointer():
    async def _body(sess):
        first = await _publish_one(sess, feature="alpha_a")
        gid = ufp.new_generation_id()
        await ufp.create_building_generation(
            sess, generation_id=gid, feature_key="alpha_c"
        )
        assert await ufp.mark_generation_failed(sess, gid, error="qlib empty") is True
        # 非 building 代次重复标记返回 False
        assert await ufp.mark_generation_failed(sess, gid) is False
        active = await ufp.get_active_generation(sess)
        assert active["generation_id"] == first["generation_id"]

    _run(_body)


def test_republish_building_generation_rejected():
    async def _body(sess):
        record = await _publish_one(sess, feature="alpha_a")
        try:
            await ufp.publish_completed_generation(
                sess,
                generation_id=record["generation_id"],
                row_count=10,
                byte_count=80,
            )
            raise AssertionError("重复发布应当被拒绝")
        except RuntimeError:
            pass

    _run(_body)


def test_upsert_discovered_field():
    async def _body(sess):
        await ufp.upsert_discovered_field(
            sess,
            column="alpha_mom_20",
            market="CUSTOM",
            dataset_id="l1_factors",
            min_date="2024-01-02",
            max_date="2024-03-01",
        )
        row = (
            (
                await sess.execute(
                    text(
                        "SELECT is_present, min_date, max_date"
                        " FROM qm_quantdb_factor_field "
                        "WHERE market='CUSTOM' AND dataset_id='l1_factors'"
                        " AND column_name='alpha_mom_20'"
                    )
                )
            )
            .mappings()
            .first()
        )
        assert row is not None
        assert row["is_present"] in (1, True)

    _run(_body)


def test_validators_reject_bad_input():
    for bad_call in (
        lambda: ufp.validate_dataset_key("unknown_ds"),
        lambda: ufp.validate_feature_key("select * from x"),
        lambda: ufp.validate_generation_id("../../etc"),
    ):
        try:
            bad_call()
            raise AssertionError("非法输入应当被拒绝")
        except ValueError:
            pass


def _write_custom_partition(root, dt: str, frame) -> None:
    part = root / f"dt={dt}"
    part.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(part / "data.parquet", engine="pyarrow", index=False)


def _patch_custom_root(monkeypatch, tmp_path):
    import backend.shared.feature_source as feature_source

    monkeypatch.setattr(
        feature_source, "user_dataset_dir", lambda dataset="l1_factors": str(tmp_path)
    )


def test_baseline_empty_dir_skipped(monkeypatch, tmp_path):
    import pandas as pd  # noqa: F401  (环境自带，与业务一致)

    _patch_custom_root(monkeypatch, tmp_path)

    async def _body(sess):
        summary = await ufp.publish_data_init_baseline(sess)
        assert summary["action"] == "skipped"
        assert summary["reason"] == "empty"
        assert await ufp.get_active_generation(sess) is None

    _run(_body)


def test_baseline_publishes_then_idempotent(monkeypatch, tmp_path):
    import pandas as pd

    _patch_custom_root(monkeypatch, tmp_path)
    frame = pd.DataFrame(
        {
            "symbol": ["600036.SH", "600000.SH"],
            "date": pd.to_datetime(["2024-01-02", "2024-01-02"]),
            "alpha_a": [0.1, 0.2],
            "alpha_b": [1.0, None],
        }
    )
    _write_custom_partition(tmp_path, "20240102", frame)
    _write_custom_partition(tmp_path, "20240103", frame)

    # 注意：_run 每次建新空库，幂等语义需在同一库内验证，故合并为一次运行
    async def _combined(sess):
        summary = await ufp.publish_data_init_baseline(sess)
        assert summary["action"] == "published"
        first_count = len(await ufp.list_generations(sess))
        again = await ufp.publish_data_init_baseline(sess)
        assert again["action"] == "skipped"
        assert again["reason"] == "up-to-date"
        assert len(await ufp.list_generations(sess)) == first_count
        # 字段发现表已自动登记
        rows = (
            (
                await sess.execute(
                    text(
                        "SELECT column_name FROM qm_quantdb_factor_field "
                        "WHERE market='CUSTOM' AND dataset_id='l1_factors'"
                    )
                )
            )
            .mappings()
            .all()
        )
        assert {r["column_name"] for r in rows} == {"alpha_a", "alpha_b"}

    _run(_combined)


def test_baseline_republishes_on_new_partition(monkeypatch, tmp_path):
    import pandas as pd

    _patch_custom_root(monkeypatch, tmp_path)
    frame = pd.DataFrame(
        {
            "symbol": ["600036.SH", "600000.SH"],
            "date": pd.to_datetime(["2024-01-02", "2024-01-02"]),
            "alpha_a": [0.1, 0.2],
        }
    )
    _write_custom_partition(tmp_path, "20240102", frame)

    async def _body(sess):
        first = await ufp.publish_data_init_baseline(sess)
        assert first["action"] == "published"
        first_active = await ufp.get_active_generation(sess)
        # 新增分区 → 指纹变化 → 再次发布并归档旧代次
        frame2 = frame.copy()
        _write_custom_partition(tmp_path, "20240103", frame2)
        second = await ufp.publish_data_init_baseline(sess)
        assert second["action"] == "published"
        assert second["fingerprint"] != first["fingerprint"]
        active = await ufp.get_active_generation(sess)
        assert active["generation_id"] != first_active["generation_id"]
        statuses = {
            r["generation_id"]: r["status"] for r in await ufp.list_generations(sess)
        }
        assert statuses[first_active["generation_id"]] == "archived"

    _run(_body)


def test_describe_state_none_without_factors(monkeypatch, tmp_path):
    import pandas as pd

    _patch_custom_root(monkeypatch, tmp_path)
    # 只有键列、没有因子列 → 视为无状态
    frame = pd.DataFrame(
        {
            "symbol": ["600036.SH"],
            "date": pd.to_datetime(["2024-01-02"]),
            "close": [10.0],
        }
    )
    _write_custom_partition(tmp_path, "20240102", frame)
    assert ufp.describe_custom_user_dataset_state() is None
