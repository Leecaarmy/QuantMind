-- upgrade_v1.0.15: 用户因子训练数据集自动发布（generation + active 指针）。
-- 与 backend/shared/db_init.sql 第 67 节同 DDL；幂等可重放，新库走 db_init，
-- 存量库靠本脚本拉齐。写法约束：本文件不得出现百分号字符（psycopg2 fallback
-- 会误解析），故 CHECK 用 IN 枚举，不用正则。

BEGIN;

SET LOCAL lock_timeout = '10s';

CREATE TABLE IF NOT EXISTS public.qm_user_factor_generations (
    generation_id     TEXT PRIMARY KEY,
    dataset_key       TEXT NOT NULL DEFAULT 'l1_factors',
    status            TEXT NOT NULL DEFAULT 'building',
    feature_key       TEXT NOT NULL,
    factor_name       TEXT NOT NULL DEFAULT '',
    expression_sha256 TEXT NOT NULL DEFAULT '',
    manifest_json     TEXT NOT NULL DEFAULT '{}',
    row_count         INTEGER NOT NULL DEFAULT 0,
    byte_count        INTEGER NOT NULL DEFAULT 0,
    error_message     TEXT NOT NULL DEFAULT '',
    created_by        TEXT NOT NULL DEFAULT '',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at      TIMESTAMPTZ,
    CHECK (dataset_key IN ('l1_factors', 'rd_mined')),
    CHECK (status IN ('building', 'published', 'failed', 'archived'))
);

CREATE TABLE IF NOT EXISTS public.qm_user_factor_dataset_active (
    dataset_key     TEXT PRIMARY KEY,
    generation_id   TEXT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (dataset_key IN ('l1_factors', 'rd_mined'))
);

CREATE INDEX IF NOT EXISTS idx_qm_user_factor_generations_ds_status
    ON public.qm_user_factor_generations (dataset_key, status, created_at DESC);

COMMIT;
