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
