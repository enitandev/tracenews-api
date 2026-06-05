-- Stories table
create table stories (
  id              uuid primary key default gen_random_uuid(),
  outlet_id       integer references outlets(id),
  outlet_name     text,
  outlet_slug     text,
  geopolitical_lean text,
  party_proximity text,
  ownership_type  text,
  title           text not null,
  url             text unique not null,
  summary         text,
  published_at    timestamptz,
  fetched_at      timestamptz default now(),
  cluster_id      uuid references clusters(id),
  created_at      timestamptz default now()
);

-- Clusters table
create table clusters (
  id                    uuid primary key default gen_random_uuid(),
  representative_title  text not null,
  first_seen_at         timestamptz,
  outlet_count          integer default 1,
  created_at            timestamptz default now()
);

-- Add cluster_id FK after both tables exist
alter table stories
  add constraint fk_cluster
  foreign key (cluster_id)
  references clusters(id);

-- Indexes
create index stories_published_at_idx on stories(published_at desc);
create index stories_cluster_id_idx on stories(cluster_id);
create index stories_outlet_slug_idx on stories(outlet_slug);
create index clusters_outlet_count_idx on clusters(outlet_count desc);

-- RLS
alter table stories enable row level security;
alter table clusters enable row level security;

create policy "Public can read stories"
  on stories for select using (true);

create policy "Public can read clusters"
  on clusters for select using (true);

-- Add image_url to stories table
ALTER TABLE stories ADD COLUMN IF NOT EXISTS image_url text;

-- Bias categories table
CREATE TABLE IF NOT EXISTS bias_categories (
  id          serial primary key,
  slug        text unique not null,
  name        text not null,
  color       text not null,
  description text,
  created_at  timestamptz default now()
);

-- Seed bias categories
INSERT INTO bias_categories (slug, name, color, description) VALUES
  ('balanced',          'Balanced',          '#FFFFFF', 'Multiple perspectives represented, sources cited across divides, no dominant narrative'),
  ('government',        'Government',        '#008751', 'Pro-administration framing, amplifies official positions, downplays criticism'),
  ('opposition',        'Opposition',        '#C0392B', 'Anti-administration framing, amplifies failures, platforms dissent'),
  ('tribal-ethnic',     'Tribal / Ethnic',   '#E67E22', 'Framing driven by ethnic interest over national interest'),
  ('agenda',            'Agenda',            '#6C3483', 'Coverage serves documented owner, sponsor or affiliated political interest'),
  ('sensationalism',    'Sensationalism',    '#F39C12', 'Inflammatory headlines disproportionate to facts, prioritises outrage over accuracy'),
  ('misinformation',    'Misinformation',    '#1A1A1A', 'Contains factually false claims contradicted by verified sources or fact-checkers'),
  ('foreign-influence', 'Foreign Influence', '#2471A3', 'Content advances documented external political or commercial agenda')
ON CONFLICT (slug) DO NOTHING;

-- Outlet bias tags junction table
CREATE TABLE IF NOT EXISTS outlet_bias_tags (
  id               serial primary key,
  outlet_id        integer references outlets(id) on delete cascade,
  bias_category_id integer references bias_categories(id) on delete cascade,
  confidence       text check (confidence in ('confirmed', 'likely', 'possible')) default 'possible',
  evidence         text,
  reviewed_at      timestamptz default now(),
  unique(outlet_id, bias_category_id)
);

-- Story bias tags table
CREATE TABLE IF NOT EXISTS story_bias_tags (
  id               serial primary key,
  story_id         uuid references stories(id) on delete cascade,
  bias_category_id integer references bias_categories(id) on delete cascade,
  source           text check (source in ('automated', 'editorial', 'factchecker')) default 'automated',
  created_at       timestamptz default now(),
  unique(story_id, bias_category_id)
);

-- RLS
ALTER TABLE bias_categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE outlet_bias_tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE story_bias_tags ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public can read bias_categories"
  ON bias_categories FOR SELECT USING (true);

CREATE POLICY "Public can read outlet_bias_tags"
  ON outlet_bias_tags FOR SELECT USING (true);

CREATE POLICY "Public can read story_bias_tags"
  ON story_bias_tags FOR SELECT USING (true);

-- Indexes
CREATE INDEX IF NOT EXISTS outlet_bias_tags_outlet_id_idx ON outlet_bias_tags(outlet_id);
CREATE INDEX IF NOT EXISTS story_bias_tags_story_id_idx ON story_bias_tags(story_id);
CREATE INDEX IF NOT EXISTS stories_image_url_idx ON stories(image_url) WHERE image_url IS NOT NULL;
