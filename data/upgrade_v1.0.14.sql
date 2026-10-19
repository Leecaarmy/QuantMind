-- upgrade_v1.0.14: 修复股票代码后缀化唯一键冲突（幂等）。
-- v1.0.11 可能已被 schema_migrations 标记为已应用；新编号确保 updater
-- 也能运行修复。与 v1.0.11 使用相同事务体，启动重放与版本升级口径一致。
-- 冲突旧行及后缀行完整快照归档于 public.stock_code_migration_conflicts，
-- 保留后缀记录，不对可能重叠的日汇总盲目累加。

BEGIN;

SET LOCAL lock_timeout = '10s';

-- 同日同来源的前/后缀汇总可能分别覆盖不同时间段，也可能相互重叠。
-- 无法从日汇总还原去重后的逐笔行情，因此不盲目累加统计；保留后缀行，
-- 将完整冲突双方快照持久归档，再移除阻塞唯一键的旧别名行。
DO $$
BEGIN
  IF to_regclass('public.quote_daily_summaries') IS NOT NULL THEN
    LOCK TABLE public.quote_daily_summaries IN SHARE ROW EXCLUSIVE MODE;

    CREATE TABLE IF NOT EXISTS public.stock_code_migration_conflicts (
      migration_name TEXT NOT NULL,
      table_name TEXT NOT NULL,
      row_id TEXT NOT NULL,
      old_symbol TEXT NOT NULL,
      new_symbol TEXT NOT NULL,
      legacy_row JSONB NOT NULL,
      canonical_row JSONB NOT NULL,
      archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      PRIMARY KEY (migration_name, table_name, row_id)
    );

    INSERT INTO public.stock_code_migration_conflicts (
      migration_name, table_name, row_id, old_symbol, new_symbol,
      legacy_row, canonical_row
    )
    SELECT 'stock_code_suffix_v1', 'quote_daily_summaries', old.id::text,
           old.symbol, canonical.symbol, to_jsonb(old), to_jsonb(canonical)
    FROM public.quote_daily_summaries old
    JOIN public.quote_daily_summaries canonical
      ON canonical.trade_date = old.trade_date
     AND canonical.data_source IS NOT DISTINCT FROM old.data_source
     AND canonical.symbol = substring(old.symbol FROM 3)
                             || '.' || substring(old.symbol FROM 1 FOR 2)
    WHERE old.symbol ~ '^(SH|SZ|BJ)[0-9]{6}$'
    ON CONFLICT (migration_name, table_name, row_id) DO NOTHING;

    DELETE FROM public.quote_daily_summaries old
    USING public.quote_daily_summaries canonical
    WHERE old.symbol ~ '^(SH|SZ|BJ)[0-9]{6}$'
      AND canonical.trade_date = old.trade_date
      AND canonical.data_source IS NOT DISTINCT FROM old.data_source
      AND canonical.symbol = substring(old.symbol FROM 3)
                              || '.' || substring(old.symbol FROM 1 FOR 2);
  END IF;
END
$$;

DO $$
DECLARE
  r RECORD;
  v RECORD;
  total_rows BIGINT := 0;
  total_values INT := 0;
BEGIN
  FOR r IN
    SELECT c.table_name, c.column_name
    FROM information_schema.columns c
    JOIN information_schema.tables t USING (table_schema, table_name)
    WHERE c.table_schema = 'public'
      AND t.table_type = 'BASE TABLE'
      AND c.column_name IN ('symbol', 'stock_code')
      AND c.data_type IN ('character varying', 'varchar', 'character', 'char', 'text')
      AND c.table_name NOT IN ('alembic_version', 'spatial_ref_sys', 'geography_columns', 'geometry_columns')
    ORDER BY c.table_name, c.column_name
  LOOP
    FOR v IN EXECUTE format(
      'SELECT DISTINCT %I AS old_v FROM public.%I WHERE %I ~ %L',
      r.column_name, r.table_name, r.column_name, '^(SH|SZ|BJ)[0-9]{6}$'
    ) LOOP
      EXECUTE format(
        'UPDATE public.%I SET %I = substring(%I FROM 3) || %L || substring(%I FROM 1 FOR 2) WHERE %I = %L',
        r.table_name, r.column_name, r.column_name, '.', r.column_name, r.column_name, v.old_v
      );
      GET DIAGNOSTICS total_rows = ROW_COUNT;
      total_values := total_values + 1;
      RAISE NOTICE 'upgrade_v1.0.11: %.% % → 后缀 (% 行)',
        r.table_name, r.column_name, v.old_v, total_rows;
    END LOOP;
  END LOOP;
  RAISE NOTICE 'upgrade_v1.0.11: 完成，共 % 个不同值转后缀', total_values;
END
$$;

COMMIT;
