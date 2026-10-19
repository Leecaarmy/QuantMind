import pandas as pd
import pytest

from backend.shared.prediction_normalization import (
    align_prediction_index,
    normalize_prediction_frame,
)


@pytest.mark.parametrize("reverse", [False, True])
def test_legacy_collision_prefers_suffix_independent_of_order(reverse):
    rows = [
        ("SH600000", 0.1),
        ("sh600000", 0.2),
        ("600000.SH", 0.9),
    ]
    if reverse:
        rows.reverse()
    frame = pd.DataFrame(rows, columns=["symbol", "pred"])
    frame["trade_date"] = "2026-09-30"
    frame.index = [5, 5, 7]  # Physical positions, not labels, select retained rows.
    result = normalize_prediction_frame(frame)
    assert result["symbol"].tolist() == ["600000.SH"]
    assert result["pred"].tolist() == [0.9]
    pred = frame.rename(columns={"trade_date": "datetime", "symbol": "instrument"})
    pred = pred.set_index(["datetime", "instrument"])
    aligned = align_prediction_index(pred, ["sh600000"])
    assert aligned.index.is_unique
    assert aligned.index.get_level_values("instrument").tolist() == ["sh600000"]
    assert aligned["pred"].tolist() == [0.9]


def test_same_format_last_row_wins_without_losing_other_dates():
    frame = pd.DataFrame(
        {
            "symbol": ["600000.SH"] * 3,
            "trade_date": ["2026-09-29", "2026-09-30", "2026-09-30"],
            "pred": [0.1, 0.2, 0.9],
        }
    )
    result = normalize_prediction_frame(frame)
    assert result["pred"].tolist() == [0.1, 0.9]


def test_alignment_handles_half_overlap_empty_universe_and_non_cn():
    index = pd.MultiIndex.from_tuples(
        [("2026-09-30", c) for c in ["sh600000", "600000.SH", "0700.HK", "aapl"]],
        names=["datetime", "instrument"],
    )
    pred = pd.Series([0.1, 0.9, 0.3, 0.4], index=index)
    for instruments in ([], ["sh600000", "0700.HK", "AAPL"]):
        result = align_prediction_index(pred, instruments)
        assert result.index.is_unique
        assert set(result.index.get_level_values("instrument")) == {
            "sh600000",
            "0700.HK",
            "AAPL",
        }
        assert result.loc[(pd.Timestamp("2026-09-30"), "sh600000")] == 0.9


def test_merge_overwrites_legacy_scores_and_refreshes_complete_daily_slice(tmp_path):
    from backend.services.engine.inference.pred_merge import merge_signals_into_pred

    path = tmp_path / "pred.parquet"
    pd.DataFrame(
        {
            "symbol": ["SH600000", "600000.SH", "SZ000001"],
            "trade_date": ["2026-09-30"] * 3,
            "pred": [0.1, 0.2, 0.3],
            "label": [0.0] * 3,
            "split": ["test"] * 3,
        }
    ).to_parquet(path, index=False)
    assert (
        merge_signals_into_pred(
            path,
            [
                (
                    "2026-09-30",
                    [
                        {"symbol": "600000.SH", "score": 0.8},
                        {"symbol": "SH600000", "score": 0.9},
                    ],
                )
            ],
        )
        == 1
    )
    stored = pd.read_parquet(path)
    assert not stored.duplicated(["trade_date", "symbol"]).any()
    assert stored.set_index("symbol")["pred"].to_dict() == {
        "600000.SH": 0.9,
        "000001.SZ": 0.3,
    }
    daily = pd.read_parquet(tmp_path / "pred_daily/dt=20260930/data.parquet")
    assert daily.set_index("symbol")["score"].to_dict() == {
        "600000.SH": 0.9,
        "000001.SZ": 0.3,
    }


def test_template_copy_never_writes_even_when_explicitly_requested(tmp_path):
    from backend.services.engine.inference.gap_backfill import _template_copy_day

    path = tmp_path / "pred.parquet"
    path.write_bytes(b"must stay untouched")
    before = path.read_bytes()
    ok, message = _template_copy_day(path, "2026-09-30")
    assert not ok
    assert "禁止模板复制" in message
    assert path.read_bytes() == before


@pytest.mark.parametrize("allow_copy", [False, True])
def test_failed_backfill_stays_failed_and_preserves_gap(
    tmp_path, monkeypatch, allow_copy
):
    import asyncio
    from backend.services.engine.inference import gap_backfill, script_runner

    class FailedRunner:
        def __init__(self, **kwargs):
            pass

        def execute(self, **kwargs):
            raise RuntimeError("inference unavailable")

    async def no_record(**kwargs):
        pass

    monkeypatch.setattr(script_runner, "InferenceScriptRunner", FailedRunner)
    monkeypatch.setattr(
        gap_backfill,
        "_resolve_backfill_model_lineage",
        lambda **k: ("m", "user_default"),
    )
    monkeypatch.setattr(gap_backfill, "_mark_failed_run", no_record)
    monkeypatch.setattr(gap_backfill, "_mark_success_run", no_record)
    path = tmp_path / "pred.parquet"
    path.write_bytes(b"untouched historical scores")
    result = asyncio.run(
        gap_backfill.backfill_model_gaps(
            tenant_id="test",
            user_id="test",
            model_id="m",
            storage_path=str(tmp_path),
            gaps=["2026-09-30"],
            allow_template_copy=allow_copy,
        )
    )
    assert result["status"] == "failed"
    assert result["failed"] == 1
    assert result["appended"] == 0
    assert path.read_bytes() == b"untouched historical scores"


def test_migration_cleans_suffix_only_duplicates_and_is_idempotent(tmp_path):
    from backend.scripts.migrate_pred_parquet_to_suffix import convert_file

    path = tmp_path / "pred.parquet"
    pd.DataFrame(
        {
            "symbol": ["600000.SH"] * 2,
            "trade_date": ["2026-09-30"] * 2,
            "pred": [0.1, 0.9],
        }
    ).to_parquet(path, index=False)
    before = path.read_bytes()
    assert convert_file(path, date_col="trade_date", dry_run=True)[0] == 1
    assert path.read_bytes() == before
    assert convert_file(path, date_col="trade_date", dry_run=False)[0] == 1
    assert pd.read_parquet(path)["pred"].tolist() == [0.9]
    assert convert_file(path, date_col="trade_date", dry_run=False)[0] == 0
