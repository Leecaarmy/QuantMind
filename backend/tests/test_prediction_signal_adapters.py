import types

from backend.services.engine.qlib_app.services.backtest_service import (
    QlibBacktestService,
)


def test_vectorized_and_step_alignment_keep_the_same_collision_score(monkeypatch):
    import pandas as pd
    from backend.services.engine.qlib_app.services import (
        backtest_service_runtime as runtime,
    )
    from backend.services.engine.qlib_app.utils.simple_signal import SimpleSignal

    monkeypatch.setattr(
        runtime,
        "D",
        types.SimpleNamespace(
            instruments=lambda universe: universe,
            list_instruments=lambda *a, **k: ["sh600000"],
        ),
    )
    signal = SimpleSignal()
    monkeypatch.setattr(signal, "_get_universe_instruments", lambda: ["sh600000"])
    for codes, scores in [
        (["600000.SH", "SH600000", "sh600000"], [0.9, 0.1, 0.2]),
        (["sh600000", "SH600000", "600000.SH"], [0.2, 0.1, 0.9]),
    ]:
        index = pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2026-09-30"), code) for code in codes],
            names=["datetime", "instrument"],
        )
        pred = pd.DataFrame({"score": scores}, index=index)
        vect = QlibBacktestService()._align_pred_instruments(
            pred, types.SimpleNamespace(universe="all")
        )
        step = signal._align_instrument_case(pred["score"])
        pd.testing.assert_series_equal(vect["score"], step)
        assert vect["score"].tolist() == [0.9]
