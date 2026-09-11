-- Index for filtering stories by published date (essential for the 30-day window)
CREATE INDEX IF NOT EXISTS idx_stories_published_at ON stories(published_at DESC);

-- Index for story bias tags to quickly find tiers for a given cluster/story
CREATE INDEX IF NOT EXISTS idx_story_bias_tags_cluster_id ON story_bias_tags(cluster_id);
CREATE INDEX IF NOT EXISTS idx_story_bias_tags_tier ON story_bias_tags(tier);

-- Composite index for analytics consent (often queried by user_id)
CREATE INDEX IF NOT EXISTS idx_reader_analytics_consent_user_id ON reader_analytics_consent(user_id);

-- If reader history is stored in a separate table (e.g. user_read_events), indexing user_id and created_at
-- CREATE INDEX IF NOT EXISTS idx_user_read_events_user_id ON user_read_events(user_id, created_at DESC);
