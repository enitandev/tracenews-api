import logging
from rapidfuzz import fuzz
from app.db import supabase

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 72  # tune this as needed


def get_recent_unclustered(hours: int = 48) -> list[dict]:
    """Get stories from the last N hours that haven't been clustered yet."""
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    response = supabase.table("stories").select("*").gte(
        "published_at", cutoff
    ).is_("cluster_id", "null").execute()
    return response.data or []


def get_all_clusters() -> list[dict]:
    response = supabase.table("clusters").select("*").execute()
    return response.data or []


def headline_similarity(a: str, b: str) -> float:
    """Compute similarity between two headlines."""
    return fuzz.token_sort_ratio(a.lower(), b.lower())


def find_or_create_cluster(story: dict, clusters: list[dict]) -> str:
    """Find a matching cluster for a story or create a new one."""
    best_match = None
    best_score = 0

    for cluster in clusters:
        score = headline_similarity(story["title"], cluster["representative_title"])
        if score > best_score:
            best_score = score
            best_match = cluster

    if best_score >= SIMILARITY_THRESHOLD and best_match:
        return best_match["id"]

    # Create new cluster
    new_cluster = supabase.table("clusters").insert({
        "representative_title": story["title"],
        "first_seen_at": story["published_at"],
        "outlet_count": 1,
    }).execute()

    new_id = new_cluster.data[0]["id"]
    clusters.append({
        "id": new_id,
        "representative_title": story["title"],
    })
    return new_id


def assign_cluster(story_id: str, cluster_id: str):
    supabase.table("stories").update(
        {"cluster_id": cluster_id}
    ).eq("id", story_id).execute()


def update_cluster_count(cluster_id: str):
    count_result = supabase.table("stories").select(
        "id", count="exact"
    ).eq("cluster_id", cluster_id).execute()
    count = count_result.count or 0
    supabase.table("clusters").update(
        {"outlet_count": count}
    ).eq("id", cluster_id).execute()


def run_clustering() -> dict:
    """Main clustering job."""
    logger.info("Starting clustering run...")
    stories = get_recent_unclustered()
    clusters = get_all_clusters()
    logger.info(f"{len(stories)} unclustered stories, {len(clusters)} existing clusters")

    assigned = 0
    created = 0
    prev_cluster_count = len(clusters)

    for story in stories:
        cluster_id = find_or_create_cluster(story, clusters)
        assign_cluster(story["id"], cluster_id)
        update_cluster_count(cluster_id)
        assigned += 1

    created = len(clusters) - prev_cluster_count
    logger.info(f"Clustering complete. {assigned} stories assigned, {created} new clusters.")
    return {
        "stories_clustered": assigned,
        "new_clusters": created,
        "total_clusters": len(clusters),
    }
