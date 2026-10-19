-- upgrade_v1.0.13: qm_feature_definition 补 explanation 列（幂等）
--   背景：explanation 列当初只加在 backend/shared/db_init.sql 第 20 节的
--   CREATE TABLE IF NOT EXISTS 里，而 CREATE TABLE IF NOT EXISTS 不会改动
--   已存在的表——所以「按旧版本建过 qm_feature_definition」的存量库一直缺这
--   一列。随后的 upgrade_v1.0.10.sql（特征字典注册表种子）INSERT 显式引用
--   explanation，deploy/update.sh 用 ON_ERROR_STOP=1 执行该文件，首次升级即中断：
--     ERROR: column "explanation" of relation "qm_feature_definition" does not exist
--     [quantmind-update] 错误: SQL 升级失败: upgrade v1.0.10.sql
--   新库由 db_init.sql 建表时自带该列，本补丁只负责存量库补列。
--
-- 幂等：ADD COLUMN IF NOT EXISTS，可随启动重复重放。
-- 自动执行：
--   1) backend/main_oss.py 的 _ensure_upgrade_scripts 每次启动扫描重放；
--   2) deploy/update.sh 第 4 步按 schema_migrations 去重执行。
-- 覆盖场景：v1.0.10 已被 schema_migrations 记为「已应用」的库（首次启用版本
--   追踪时被批量标记、或曾跳过），update.sh 不会再跑 v1.0.10，靠本补丁补齐列；
--   特征字典数据本身仍由 v1.0.10（已在同一次 update 前修正为自愈式补列）导入。
-- 手工执行（可选）：
--   docker exec -i quantmind-db psql -U quantmind -d quantmind \
--     < data/upgrade_v1.0.13.sql
-- ============================================================

BEGIN;

ALTER TABLE qm_feature_definition
    ADD COLUMN IF NOT EXISTS explanation TEXT DEFAULT '';

COMMIT;
