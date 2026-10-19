"""Canonical prediction keys shared by persistence and Qlib adapters.

Legacy files have no per-row update timestamp. Prefer suffix rows over legacy
aliases on collisions, then the last row within the same format. Writers must
normalize existing rows before appending new inference, so new scores win.
"""

from __future__ import annotations

import re

import pandas as pd

from backend.shared.stock_utils import StockCodeUtil

_CN_SUFFIX = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")


def normalize_prediction_frame(
    frame: pd.DataFrame,
    *,
    date_column: str | None = "trade_date",
    symbol_column: str = "symbol",
) -> pd.DataFrame:
    """Normalize symbols/daily dates and resolve legacy alias collisions."""
    result = frame.copy()
    original = result[symbol_column].astype(str)
    mapping = {code: StockCodeUtil.normalize(code) for code in original.unique()}
    result[symbol_column] = original.map(mapping)
    keys = [symbol_column]
    if date_column is not None:
        result[date_column] = pd.to_datetime(result[date_column]).dt.normalize()
        keys.insert(0, date_column)
    if not result.duplicated(keys).any():
        return result

    # Only sort colliding rows; historical model files can have millions of rows.
    collisions = result.duplicated(keys, keep=False).to_numpy()
    positions = pd.DataFrame(
        {
            "position": range(len(result)),
            "suffix": original.map(
                {
                    code: bool(_CN_SUFFIX.fullmatch(code.strip().upper()))
                    for code in original.unique()
                }
            ).to_numpy(),
        }
    )
    candidates = positions.loc[collisions].sort_values("suffix", kind="stable")
    duplicates = result.iloc[candidates["position"]].duplicated(keys, keep="last")
    keep = pd.Series(True, index=range(len(result)))
    keep.loc[candidates.loc[duplicates.to_numpy(), "position"]] = False
    return result.iloc[keep.to_numpy()]


def align_prediction_index(
    prediction: pd.DataFrame | pd.Series,
    instruments: list[str] | None = None,
) -> pd.DataFrame | pd.Series:
    """Return unique (datetime, instrument) keys in Qlib's universe format.

    CN aliases always cross the boundary through StockCodeUtil.to_qlib().
    Non-CN tickers keep the matching universe spelling, including HK suffixes.
    """
    if not isinstance(prediction.index, pd.MultiIndex):
        return prediction
    if not {"datetime", "instrument"}.issubset(prediction.index.names):
        return prediction
    original = prediction.index.get_level_values("instrument").astype(str)
    keys = pd.DataFrame(
        {
            "datetime": prediction.index.get_level_values("datetime"),
            "instrument": original,
            "position": range(len(prediction)),
        }
    )
    keys = normalize_prediction_frame(
        keys, date_column="datetime", symbol_column="instrument"
    )
    universe = set(map(str, instruments or []))

    def to_instrument(code: str) -> str:
        if _CN_SUFFIX.fullmatch(code):
            return StockCodeUtil.to_qlib(code)
        for candidate in (code, code.lower(), code.upper()):
            if candidate in universe:
                return candidate
        return code

    mapping = {code: to_instrument(code) for code in keys["instrument"].unique()}
    keys["instrument"] = keys["instrument"].map(mapping)
    keys = keys.drop_duplicates(["datetime", "instrument"], keep="last")
    result = prediction.iloc[keys["position"].to_numpy()].copy()
    result.index = pd.MultiIndex.from_frame(keys[["datetime", "instrument"]])
    return result.sort_index()
