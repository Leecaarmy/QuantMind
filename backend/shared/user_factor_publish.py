"""用户因子训练数据集自动发布（企业版 generation 语义的 OSS 下放）。

企业版（``alpha_user_factor_generations`` + ``alpha_user_factor_dataset_active``）：
因子物化任务完成时在同一事务内把 generation 置为 ``published``、登记特征映射、
切换 active 指针并归档旧版；失败任务不切换指针，训练/推理只读 active 指向的
``published`` 版本。

OSS 为单容器部署，无租户隔离与因子任务队列，故做如下简化（语义不变）：

- 按 ``dataset_key`` 单流推进版本，不分 tenant/user；
- generation 是逻辑版本标记（parquet 仍累积写
  ``quantcustom/6_ml_datasets/l1_factors``，见 ``merge_factor_into_source``），
  不做物理目录拷贝；指针即训练可用的版本真相；
- 校验门禁与企业版 ``factor_jobs.py`` 同口径：非法结果抛 ``ValueError``，
  指针不动；显式失败记 ``failed``，指针不动。

调用方（``admin/alpha_factor_pipeline.py``）流程：
``create_building_generation`` → 离线计算 + parquet 合并 →
``publish_completed_generation``（内含字段注册表 upsert）；
任一步失败 → ``mark_generation_failed``。
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

DATASET_KEYS = ("l1_factors", "rd_mined")
DEFAULT_DATASET_KEY = "l1_factors"
GENERATION_STATUSES = ("building", "published", "failed", "archived")

_FEATURE_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")
_GENERATION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def new_generation_id() -> str:
    """生成 16 位 hex 代次 ID（满足库约束，可直接作目录名）。"""
    return uuid.uuid4().hex[:16]


def expression_sha256(expression: str) -> str:
    return hashlib.sha256(str(expression or "").encode("utf-8")).hexdigest()


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_dataset_key(value: object) -> str:
    dataset = str(value or "").strip()
    if dataset not in DATASET_KEYS:
        raise ValueError(f"非法 dataset_key：{dataset!r}，仅支持 {list(DATASET_KEYS)}")
    return dataset


def validate_feature_key(value: object) -> str:
    feature = str(value or "").strip()
    if not _FEATURE_KEY_RE.match(feature):
        raise ValueError(f"非法 feature_key：{feature!r}")
    return feature


def validate_generation_id(value: object) -> str:
    generation_id = str(value or "").strip()
    if not _GENERATION_ID_RE.match(generation_id):
        raise ValueError(f"非法 generation_id：{generation_id!r}")
    return generation_id


async def ensure_user_factor_schema(session: Any) -> None:
    """幂等建表（PG 与 sqlite 通用；时间戳一律由调用方显式传入）。"""
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS qm_user_factor_generations (
                generation_id TEXT PRIMARY KEY,
                dataset_key TEXT NOT NULL DEFAULT 'l1_factors',
                status TEXT NOT NULL DEFAULT 'building',
                feature_key TEXT NOT NULL,
                factor_name TEXT NOT NULL DEFAULT '',
                expression_sha256 TEXT NOT NULL DEFAULT '',
                manifest_json TEXT NOT NULL DEFAULT '{}',
                row_count INTEGER NOT NULL DEFAULT 0,
                byte_count INTEGER NOT NULL DEFAULT 0,
                error_message TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL,
                published_at TIMESTAMPTZ,
                CHECK (dataset_key IN ('l1_factors', 'rd_mined')),
                CHECK (status IN ('building', 'published', 'failed', 'archived'))
            );
            """
        )
    )
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS qm_user_factor_dataset_active (
                dataset_key TEXT PRIMARY KEY,
                generation_id TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                CHECK (dataset_key IN ('l1_factors', 'rd_mined'))
            );
            """
        )
    )
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_qm_user_factor_generations_ds_status "
            "ON qm_user_factor_generations (dataset_key, status, created_at DESC)"
        )
    )


async def create_building_generation(
    session: Any,
    *,
    generation_id: str,
    dataset_key: str = DEFAULT_DATASET_KEY,
    feature_key: str,
    factor_name: str = "",
    expression: str = "",
    created_by: str = "",
) -> dict[str, Any]:
    """登记一个 ``building`` 代次（物化开始前调用）。"""
    generation_id = validate_generation_id(generation_id)
    dataset = validate_dataset_key(dataset_key)
    feature = validate_feature_key(feature_key)
    now = utcnow_iso()
    await session.execute(
        text(
            """
            INSERT INTO qm_user_factor_generations
              (generation_id, dataset_key, status, feature_key, factor_name,
               expression_sha256, created_by, created_at)
            VALUES (:gid, :dataset, 'building', :feature, :name, :sha, :by, :now)
            """
        ),
        {
            "gid": generation_id,
            "dataset": dataset,
            "feature": feature,
            "name": str(factor_name or "")[:256],
            "sha": expression_sha256(expression),
            "by": str(created_by or "")[:128],
            "now": now,
        },
    )
    return {
        "generation_id": generation_id,
        "dataset_key": dataset,
        "status": "building",
        "feature_key": feature,
        "created_at": now,
    }


def _validate_completed_payload(
    *, row_count: object, byte_count: object, expression_sha: str
) -> tuple[int, int]:
    """企业版 finish() 门禁的 OSS 等价：非法结果直接拒收（抛错，不落库）。"""
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count <= 0:
        raise ValueError(f"发布结果非法：row_count 必须为正整数，实得 {row_count!r}")
    if (
        isinstance(byte_count, bool)
        or not isinstance(byte_count, int)
        or byte_count <= 0
    ):
        raise ValueError(f"发布结果非法：byte_count 必须为正整数，实得 {byte_count!r}")
    if expression_sha and not _SHA256_RE.match(str(expression_sha)):
        raise ValueError("发布结果非法：expression_sha256 不是 64 位 hex")
    return int(row_count), int(byte_count)


async def publish_completed_generation(
    session: Any,
    *,
    generation_id: str,
    dataset_key: str = DEFAULT_DATASET_KEY,
    row_count: int,
    byte_count: int,
    manifest_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把 ``building`` 代次原子发布：置 published → 切换指针 → 归档旧版。

    三条写语句与调用方会话同事务；任一失败整体回滚，指针不动。
    ``manifest_extra`` 只收 JSON 可序列化字段。
    """
    generation_id = validate_generation_id(generation_id)
    dataset = validate_dataset_key(dataset_key)
    row = (
        (
            await session.execute(
                text(
                    "SELECT feature_key, factor_name, expression_sha256 "
                    "FROM qm_user_factor_generations "
                    "WHERE generation_id = :gid AND dataset_key = :dataset"
                ),
                {"gid": generation_id, "dataset": dataset},
            )
        )
        .mappings()
        .first()
    )
    if not row:
        raise ValueError(f"代次不存在：{generation_id!r} / {dataset!r}")
    rows, byte_count = _validate_completed_payload(
        row_count=row_count,
        byte_count=byte_count,
        expression_sha=str(row["expression_sha256"] or ""),
    )
    manifest = {
        "dataset_key": dataset,
        "feature_key": str(row["feature_key"]),
        "factor_name": str(row["factor_name"] or ""),
        "expression_sha256": str(row["expression_sha256"] or ""),
        "row_count": rows,
        "byte_count": byte_count,
    }
    for key, value in dict(manifest_extra or {}).items():
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", str(key)):
            manifest[str(key)] = value
    manifest_json = json.dumps(
        manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    now = utcnow_iso()
    updated = await session.execute(
        text(
            """
            UPDATE qm_user_factor_generations
               SET status = 'published', manifest_json = :manifest,
                   row_count = :rows, byte_count = :bytes, published_at = :now
             WHERE generation_id = :gid AND dataset_key = :dataset
               AND status = 'building'
            """
        ),
        {
            "manifest": manifest_json,
            "rows": rows,
            "bytes": byte_count,
            "now": now,
            "gid": generation_id,
            "dataset": dataset,
        },
    )
    if updated.rowcount != 1:
        raise RuntimeError(f"代次已不在 building 状态，拒绝发布：{generation_id!r}")
    await session.execute(
        text(
            """
            INSERT INTO qm_user_factor_dataset_active
              (dataset_key, generation_id, updated_at)
            VALUES (:dataset, :gid, :now)
            ON CONFLICT (dataset_key) DO UPDATE SET
              generation_id = EXCLUDED.generation_id,
              updated_at = EXCLUDED.updated_at
            """
        ),
        {"dataset": dataset, "gid": generation_id, "now": now},
    )
    await session.execute(
        text(
            """
            UPDATE qm_user_factor_generations SET status = 'archived'
             WHERE dataset_key = :dataset AND status = 'published'
               AND generation_id <> :gid
            """
        ),
        {"dataset": dataset, "gid": generation_id},
    )
    return {
        "generation_id": generation_id,
        "dataset_key": dataset,
        "status": "published",
        "manifest": manifest,
        "published_at": now,
    }


async def mark_generation_failed(
    session: Any, generation_id: str, error: str = ""
) -> bool:
    """把 ``building`` 代次记为失败；指针不动。返回是否实际标记成功。"""
    generation_id = validate_generation_id(generation_id)
    updated = await session.execute(
        text(
            """
            UPDATE qm_user_factor_generations
               SET status = 'failed', error_message = :error
             WHERE generation_id = :gid AND status = 'building'
            """
        ),
        {"gid": generation_id, "error": str(error or "")[:2000]},
    )
    return (updated.rowcount or 0) == 1


async def get_active_generation(
    session: Any, dataset_key: str = DEFAULT_DATASET_KEY
) -> dict[str, Any] | None:
    """读 active 指针指向的 ``published`` 代次（训练侧唯一可信版本）。"""
    dataset = validate_dataset_key(dataset_key)
    row = (
        (
            await session.execute(
                text(
                    """
            SELECT active.generation_id, generation.status,
                   generation.feature_key, generation.factor_name,
                   generation.expression_sha256, generation.manifest_json,
                   generation.row_count, generation.byte_count,
                   generation.published_at
              FROM qm_user_factor_dataset_active AS active
              JOIN qm_user_factor_generations AS generation
                ON generation.generation_id = active.generation_id
               AND generation.dataset_key = active.dataset_key
             WHERE active.dataset_key = :dataset
               AND generation.status = 'published'
            """
                ),
                {"dataset": dataset},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def list_generations(
    session: Any,
    dataset_key: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """按创建时间倒序列出代次（含 building/failed/archived，便于排障）。"""
    dataset = validate_dataset_key(dataset_key) if dataset_key else None
    rows = (
        (
            await session.execute(
                text(
                    "SELECT generation_id, dataset_key, status, feature_key, factor_name,"
                    " row_count, byte_count, created_by, created_at, published_at"
                    " FROM qm_user_factor_generations"
                    + (" WHERE dataset_key = :dataset" if dataset else "")
                    + " ORDER BY created_at DESC LIMIT :limit"
                ),
                {"dataset": dataset, "limit": max(1, min(int(limit or 50), 200))},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


async def upsert_discovered_field(
    session: Any,
    *,
    column: str,
    market: str = "CUSTOM",
    dataset_id: str = DEFAULT_DATASET_KEY,
    min_date: str | None = None,
    max_date: str | None = None,
) -> None:
    """发布成功后自动登记字段发现表，省掉一次手动 ``/sources/refresh``。

    只做单列 upsert（``is_present=TRUE``），不碰其它列；训练特征目录的
    草稿/发布仍由管理员在 ``quantdb_factor_catalog`` 侧决策。
    """
    feature = validate_feature_key(column)
    await session.execute(
        text(
            """
            INSERT INTO qm_quantdb_factor_field
              (market, dataset_id, column_name, data_type, schema_hash,
               min_date, max_date, is_present, discovered_at)
            VALUES (:market, :dataset, :column, 'double', '', :min_date,
                    :max_date, TRUE, :now)
            ON CONFLICT (market, dataset_id, column_name) DO UPDATE SET
              is_present = TRUE, discovered_at = EXCLUDED.discovered_at,
              min_date = COALESCE(EXCLUDED.min_date, qm_quantdb_factor_field.min_date),
              max_date = COALESCE(EXCLUDED.max_date, qm_quantdb_factor_field.max_date)
            """
        ),
        {
            "market": str(market or "CUSTOM").upper(),
            "dataset": str(dataset_id or DEFAULT_DATASET_KEY),
            "column": feature,
            "min_date": min_date,
            "max_date": max_date,
            "now": utcnow_iso(),
        },
    )
