DROP INDEX IF EXISTS idx_verification_symbol_asof;
DROP INDEX IF EXISTS idx_quality_run_blocking;
DROP INDEX IF EXISTS idx_quality_run_symbol_group;
DROP TABLE IF EXISTS source_verification_reports;
DROP TABLE IF EXISTS data_quality_assessments;

-- data_quality_summary_json随001回滚时删除screening_runs；为兼容旧SQLite，
-- 此处不单独执行DROP COLUMN。
