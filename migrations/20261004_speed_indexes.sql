-- Speed indexes (4 Oct 2026). Run once in the Supabase SQL editor; every
-- statement is IF NOT EXISTS, so running it again changes nothing.
--
-- Each index matches a query the site runs on most page views or Desk tabs.
-- Without them Postgres reads the whole table for each request; the category
-- sections took 4-10 s and sometimes failed (HTTP 500) on a cold request.

-- Homepage category sections and most-carried rails:
--   clusters WHERE category = ? ORDER BY first_seen_at DESC
CREATE INDEX IF NOT EXISTS clusters_category_first_seen_idx ON clusters (category, first_seen_at DESC);
-- Homepage landing and feed: clusters ORDER BY first_seen_at DESC LIMIT 200
CREATE INDEX IF NOT EXISTS clusters_first_seen_idx ON clusters (first_seen_at DESC);
-- Desk Monitoring Spirit: clusters WHERE created_at >= now() - 72h
CREATE INDEX IF NOT EXISTS clusters_created_at_idx ON clusters (created_at DESC);

-- Every story page, list and verdict: stories WHERE cluster_id IN (...)
-- (already in 20260605_schema.sql; repeated in case it was never applied)
CREATE INDEX IF NOT EXISTS stories_cluster_id_idx ON stories (cluster_id);

-- Verdict history: coverage_snapshots WHERE cluster_id IN (...) ORDER BY snapshot_at DESC
CREATE INDEX IF NOT EXISTS coverage_snapshots_cluster_time_idx ON coverage_snapshots (cluster_id, snapshot_at DESC);

-- Story summaries and the Briefing: cluster_summaries WHERE cluster_id = ? ORDER BY generated_at DESC
CREATE INDEX IF NOT EXISTS cluster_summaries_cluster_time_idx ON cluster_summaries (cluster_id, generated_at DESC);

-- Desk: open corrections, newest first; overview audit log; active overrides;
-- politicians queue by status
CREATE INDEX IF NOT EXISTS correction_requests_status_created_idx ON correction_requests (status, created_at DESC);
CREATE INDEX IF NOT EXISTS admin_audit_log_created_idx ON admin_audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS verdict_overrides_cluster_active_idx ON verdict_overrides (cluster_id) WHERE active;
CREATE INDEX IF NOT EXISTS politicians_publication_status_idx ON politicians (publication_status);

-- Afterwards, to confirm: the new index names should all be listed.
-- SELECT tablename, indexname FROM pg_indexes
--  WHERE indexname IN ('clusters_category_first_seen_idx', 'clusters_first_seen_idx', 'clusters_created_at_idx',
--    'stories_cluster_id_idx', 'coverage_snapshots_cluster_time_idx', 'cluster_summaries_cluster_time_idx',
--    'correction_requests_status_created_idx', 'admin_audit_log_created_idx',
--    'verdict_overrides_cluster_active_idx', 'politicians_publication_status_idx')
--  ORDER BY tablename;
