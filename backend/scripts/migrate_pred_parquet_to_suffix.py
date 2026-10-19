"""存量 pred.parquet 后缀化迁移（幂等，可重跑）。

背景：2026-10-06 全系统股票代码切后缀正典后，推理回写（pred_merge）
  新写入为 600036.SH，但各模型目录存量 pred.parquet / pred_daily 分片仍是
  SH600036 前缀。读者已切后缀正则，存量历史对分数曲线/覆盖统计不可见；
  且 merge 的 drop_duplicates 按 (symbol, trade_date) 去重，前后缀混存会
  造成同一日双行。

动作：扫描模型根目录下全部 pred.parquet 与 pred_daily/dt=*/data.parquet，
  symbol 列统一后缀，同文件内去重（后缀行优先，同格式末行优先）。
  pred.pkl（qlib-bound 小写索引）不在范围。

模型根目录：MODELS_PRODUCTION（默认 /app/models/production）+
  USER_MODELS_ROOT（默认 /app/models/users，即 /app + models/users）。

用法（服务器上，先 dry-run）：
    docker exec quantmind python3 /app/backend/scripts/migrate_pred_parquet_to_suffix.py --dry-run
    docker exec quantmind python3 /app/backend/scripts/migrate_pred_parquet_to_suffix.py
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.shared.prediction_normalization import normalize_prediction_frame


def convert_file(path: Path, *, date_col: str | None, dry_run: bool) -> tuple[int, int]:
    """返回 (影响行数, 原始总行数)。dry-run 同样检查归一化后的重复。"""
    import pandas as pd

    df = pd.read_parquet(path)
    if "symbol" not in df.columns:
        print(f"  跳过 {path}：无 symbol 列")
        return 0, 0
    total = len(df)
    if date_col and date_col not in df.columns:
        raise ValueError(f"{path} 缺少日期列 {date_col}，拒绝按股票全历史去重")
    normalized = normalize_prediction_frame(df, date_column=date_col)
    original = df["symbol"].astype(str)
    from backend.shared.stock_utils import StockCodeUtil

    n = int((original != original.map(StockCodeUtil.normalize)).sum())
    removed = total - len(normalized)
    n = max(n, removed)
    if n == 0:
        return 0, total
    if not dry_run:
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".parquet.tmp")
        os.close(fd)
        try:
            normalized.to_parquet(tmp, index=False)
            os.replace(tmp, path)
        finally:
            Path(tmp).unlink(missing_ok=True)
    print(f"  {'[dry-run] ' if dry_run else ''}{path}: 去重 {removed} 行")
    return n, total


def iter_targets(roots: list[Path]):
    for root in roots:
        if not root.is_dir():
            print(f"根目录不存在，跳过: {root}")
            continue
        yield from sorted(root.rglob("pred.parquet"))
        yield from sorted(root.rglob("pred_daily/dt=*/data.parquet"))


def main() -> int:
    ap = argparse.ArgumentParser(description="存量 pred.parquet 后缀化（幂等）")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写入")
    ap.add_argument("--roots", nargs="*", default=None, help="覆盖模型根目录")
    args = ap.parse_args()

    if args.roots:
        roots = [Path(r) for r in args.roots]
    else:
        roots = [
            Path(os.getenv("MODELS_PRODUCTION", "/app/models/production")),
            Path("/app") / os.getenv("USER_MODELS_ROOT", "models/users"),
        ]
    files = list(iter_targets(roots))
    print(f"扫描到 {len(files)} 个 parquet 文件")
    converted_files = 0
    converted_rows = 0
    failures = 0
    for path in files:
        try:
            date_col = "trade_date" if path.name == "pred.parquet" else None
            n, total = convert_file(path, date_col=date_col, dry_run=args.dry_run)
            if n:
                converted_files += 1
                converted_rows += n
                print(f"  {'[dry-run] ' if args.dry_run else ''}{path}: 影响 {n}/{total} 行")
        except Exception as exc:
            failures += 1
            print(f"  失败 {path}: {exc}", file=sys.stderr)
    print(f"{'dry-run ' if args.dry_run else ''}完成：{converted_files} 文件，{converted_rows} 行")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
