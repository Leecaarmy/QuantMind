-- upgrade_v1.0.12: 个人策略收藏列（strategies.is_favorite，幂等）
--   个人中心星标收藏 / 回测·模拟盘置顶的状态位（与社区 like_count 无关，
--   后者是公开策略被点赞数）。新库由 backend/shared/db_init.sql 建表时自带；
--   本补丁只负责存量库补列。
--
-- 幂等：ADD COLUMN IF NOT EXISTS，可随启动重复重放。
-- 自动执行：
--   1) backend/main_oss.py 的 _ensure_upgrade_scripts 每次启动扫描重放；
--   2) deploy/update.sh 第 4 步按 schema_migrations 去重执行。
-- 手工执行（可选）：
--   docker exec -i quantmind-db psql -U quantmind -d quantmind \
--     < data/upgrade_v1.0.12.sql
-- ============================================================

BEGIN;

ALTER TABLE strategies
    ADD COLUMN IF NOT EXISTS is_favorite BOOLEAN DEFAULT FALSE;

COMMIT;
