-- schema_clusters_migration.sql

ALTER TABLE clusters ADD COLUMN IF NOT EXISTS coverage_stats JSONB;
ALTER TABLE clusters ADD COLUMN IF NOT EXISTS monitoring_flags JSONB;
