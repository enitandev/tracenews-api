"""
Shared live-coverage and verdict helpers used by the story, feed and admin
endpoints: outlet caches, distinct-outlet tier distribution, sourcing info,
and the DARK withholding gate.
"""
import logging
import time
from app.db import supabase
from app.tier_utils import get_outlet_tier, count_outlet_tiers, card_distribution, REPUBLISHER_S2_MAX
from app.monitoring_spirit import DARK_ENABLED

logger = logging.getLogger(__name__)

def render_safe_verdict(verdict_result: dict) -> dict:
    """
    DARK is computed but not shipped. Gate D closed 'not met' — see
    Gate_D_Closure_Record.md. This function is the single point where
    that restriction is enforced. Do not remove without a new Gate D
    passing.

    Returns None for DARK: the verdict is withheld entirely. It must never be
    relabelled as another state — a CLEAR in its place would publish a false
    "covered widely" claim about the story.
    """
    if verdict_result.get("verdict") == "dark" and not DARK_ENABLED:
        return None
    return verdict_result

def get_sourcing_info(
    cluster_stories,
    outlets_map,
    behavioral_map,
    tier_a
):
    """
    Computes sourcing info for 
    the Monitoring Spirit engine.
    Uses same tier-assignment logic
    as compute_live_coverage_tier_distribution.
    """
    loud_tier_outlet_ids = set()
    has_original = False
    
    seen_outlet_ids = set()
    for s in cluster_stories:
        oid = s.get("outlet_id")
        if not oid or oid in seen_outlet_ids:
            continue
        seen_outlet_ids.add(oid)
        
        if oid not in outlets_map:
            continue
        out = outlets_map[oid]
        slug = out.get("slug")
        behav = behavioral_map.get(slug) \
            if slug else None
        
        tier = get_outlet_tier(out.get("government_alignment"), out.get("is_blog"))
        
        if tier == tier_a:
            loud_tier_outlet_ids.add(oid)
            if behav and behav.get(
                "s2_score", 0
            ) and behav["s2_score"] >= 50:
                has_original = True
    
    return {
        "distinct_outlets_in_loud_tier":
            len(loud_tier_outlet_ids),
        "has_original_reporting_outlet":
            has_original
    }





_OUTLETS_CACHE = {}
_BEHAVIORAL_CACHE = {}
_LAST_CACHE_UPDATE = 0
CACHE_TTL = 3600  # 1 hour

def get_outlets_cache():
    global _OUTLETS_CACHE, _BEHAVIORAL_CACHE, _LAST_CACHE_UPDATE
    now = time.time()
    if now - _LAST_CACHE_UPDATE > CACHE_TTL or not _OUTLETS_CACHE:
        out_res = supabase.table("outlets").select("id, slug, government_alignment, name, logo_url, is_blog, headquarters_city, geopolitical_lean").execute()
        _OUTLETS_CACHE = {o["id"]: o for o in (out_res.data or [])}
        
        behav_res = supabase.table("outlet_behavioral_scores").select("*").execute()
        _BEHAVIORAL_CACHE = {b["outlet_slug"]: b for b in (behav_res.data or [])}
        
        _LAST_CACHE_UPDATE = now
    return _OUTLETS_CACHE, _BEHAVIORAL_CACHE

def compute_live_coverage_tier_distribution(cluster_id, stories, outlets_map, behavioral_map):
    """Card-tier distribution over distinct outlets (blog/unscored excluded)."""
    unique_outlet_ids = set()
    for s in stories:
        oid = s.get("outlet_id")
        if oid:
            unique_outlet_ids.add(oid)

    tier_dist = card_distribution(count_outlet_tiers(
        outlets_map[oid] for oid in unique_outlet_ids if oid in outlets_map
    ))
            
    scored_s2 = []
    for oid in unique_outlet_ids:
        if oid not in outlets_map:
            continue
        out = outlets_map[oid]
        slug = out.get('slug')
        behav = behavioral_map.get(slug) \
            if slug else None
        if behav and behav.get(
            's2_score'
        ) is not None:
            scored_s2.append(
                behav['s2_score']
            )

    if len(scored_s2) >= 3:
        republished = sum(
            1 for s in scored_s2 if s < REPUBLISHER_S2_MAX
        )
        churnalism_ratio = round(
            republished / len(scored_s2), 3
        )
    else:
        churnalism_ratio = None

    return tier_dist, churnalism_ratio

STORY_PAGE_SIZE = 1000   # PostgREST's default max rows per request
CLUSTER_ID_BATCH = 50    # also keeps the in_() URL short


def fetch_cluster_story_outlets(cluster_ids):
    """
    (id, cluster_id, outlet_id) for every story in the given clusters. A single
    query is silently capped at STORY_PAGE_SIZE rows, which would undercount
    the clusters at the end of a large pool, so ids are batched and each batch
    is paged until a short page comes back.
    """
    rows = []
    for i in range(0, len(cluster_ids), CLUSTER_ID_BATCH):
        batch = cluster_ids[i:i + CLUSTER_ID_BATCH]
        start = 0
        while True:
            page = (
                supabase.table("stories")
                .select("id, cluster_id, outlet_id")
                .in_("cluster_id", batch)
                .order("id")
                .range(start, start + STORY_PAGE_SIZE - 1)
                .execute()
            ).data or []
            rows.extend(page)
            if len(page) < STORY_PAGE_SIZE:
                break
            start += STORY_PAGE_SIZE
    return rows


def enrich_clusters_with_live_tiers(clusters):
    if not clusters: return clusters
    
    outlets_map, behavioral_map = get_outlets_cache()
    cluster_ids = [c["id"] for c in clusters]
    
    stories = fetch_cluster_story_outlets(cluster_ids)
    
    stories_by_cluster = {}
    for s in stories:
        cid = s.get("cluster_id")
        if cid not in stories_by_cluster:
            stories_by_cluster[cid] = []
        stories_by_cluster[cid].append(s)
        
    for c in clusters:
        cid = c["id"]
        c_stories = stories_by_cluster.get(cid, [])
        live_dist, churnalism_ratio = compute_live_coverage_tier_distribution(cid, c_stories, outlets_map, behavioral_map)
        
        blog_count = live_dist.pop("blog", 0)
        
        if not c.get("coverage_stats"):
            c["coverage_stats"] = {}
        c["coverage_stats"]["coverage_tier_distribution"] = live_dist
        c["coverage_stats"]["total_coverage"] = sum(live_dist.values())
        c["coverage_stats"]["blog_count"] = blog_count
        c["coverage_stats"]["churnalism_ratio"] = churnalism_ratio
        
    return clusters


def strip_embeddings(rows):
    """
    Drop the stored embedding vectors from rows returned to clients (and from
    rows nested one level down, e.g. a cluster's stories). Nothing client-side
    reads them, and they were over 90% of the story-page payload.
    """
    for row in (rows if isinstance(rows, list) else [rows]):
        if not isinstance(row, dict):
            continue
        row.pop("embedding", None)
        for value in row.values():
            if isinstance(value, list):
                for nested in value:
                    if isinstance(nested, dict):
                        nested.pop("embedding", None)
            elif isinstance(value, dict):
                value.pop("embedding", None)
    return rows
