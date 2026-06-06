import os
import logging
from dateutil import parser as dateparser
from datetime import timezone
from app.db import supabase
from openai import OpenAI

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.65
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def get_recent_unclustered(hours: int = 48) -> list[dict]:
    """Get stories from the last N hours that haven't been clustered yet and have embeddings."""
    from datetime import datetime, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    response = supabase.table("stories").select("id, title, summary, published_at, fetched_at, embedding").gte(
        "published_at", cutoff
    ).is_("cluster_id", "null").not_.is_("embedding", "null").execute()
    return response.data or []

def is_earlier_story(new_story: dict, existing_first_seen: str, new_story_fetched: str) -> bool:
    try:
        new_time = dateparser.parse(new_story["published_at"]).astimezone(timezone.utc)
        old_time = dateparser.parse(existing_first_seen).astimezone(timezone.utc)
        diff_minutes = abs((new_time - old_time).total_seconds()) / 60.0
        
        if diff_minutes <= 30:
            if new_story_fetched and existing_first_seen:
                pass
        
        return new_time < old_time
    except Exception:
        return False

def cleanup_old_clusters():
    """Delete single-story clusters older than 24 hours."""
    try:
        from datetime import datetime, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        res = supabase.table("clusters").select("id").lt("first_seen_at", cutoff).eq("outlet_count", 1).execute()
        old_clusters = res.data or []
        
        if old_clusters:
            ids = [c["id"] for c in old_clusters]
            
            # Process in batches to avoid URL length limits
            batch_size = 50
            for i in range(0, len(ids), batch_size):
                batch_ids = ids[i:i+batch_size]
                supabase.table("stories").update({"cluster_id": None}).in_("cluster_id", batch_ids).execute()
                supabase.table("cluster_scores").delete().in_("cluster_id", batch_ids).execute()
                supabase.table("clusters").delete().in_("id", batch_ids).execute()
                
            logger.info(f"Cleaned up {len(ids)} old single-story clusters.")
    except Exception as e:
        logger.error(f"Failed to cleanup old clusters: {e}")

def get_embedding(text: str) -> list[float] | None:
    try:
        res = openai_client.embeddings.create(
            input=text,
            model="text-embedding-3-small"
        )
        return res.data[0].embedding
    except Exception as e:
        logger.error(f"Failed to generate single embedding: {e}")
        return None

def run_clustering() -> dict:
    """Main clustering job using pgvector and OpenAI embeddings."""
    logger.info("Starting pgvector clustering run...")
    stories = get_recent_unclustered()
    if not stories:
        logger.info("No unclustered stories with embeddings found.")
        cleanup_old_clusters()
        return {"stories_clustered": 0, "new_clusters": 0, "total_clusters": 0}

    logger.info(f"{len(stories)} unclustered stories to process")

    assigned = 0
    created = 0
    debug_count = 0

    for story in stories:
        cluster_id = None
        story_emb = story.get("embedding")
        if not story_emb:
            continue

        # Query Supabase for the nearest cluster
        try:
            match_res = supabase.rpc("match_clusters", {
                "query_embedding": story_emb,
                "match_threshold": 0.0,
                "match_count": 3  # Get top 3 for debug logging
            }).execute()
            matches = match_res.data or []
            
            # Debug logging for first 20 stories
            if debug_count < 20:
                logger.info(f"\n--- DEBUG: Story '{story['title']}' ---")
                if not matches:
                    logger.info("  No matches found in DB at all.")
                for rank, m in enumerate(matches):
                    status = "MATCH" if m['similarity'] >= SIMILARITY_THRESHOLD else "NO MATCH"
                    logger.info(f"  Rank {rank+1}: score={m['similarity']:.3f} | [{status}] -> '{m['representative_title']}'")
                debug_count += 1

            if matches:
                # Top match is the first one
                best_match = matches[0]
                if best_match["similarity"] >= SIMILARITY_THRESHOLD:
                    cluster_id = best_match["id"]
                    
                    # We need to fetch the existing cluster to check first_seen_at for tiebreakers
                    cluster_res = supabase.table("clusters").select("first_seen_at").eq("id", cluster_id).execute()
                    if cluster_res.data:
                        existing_first_seen = cluster_res.data[0]["first_seen_at"]
                        if is_earlier_story(story, existing_first_seen, story.get("fetched_at")):
                            # Update representative title and its embedding
                            new_cluster_emb = get_embedding(story["title"])
                            update_payload = {
                                "representative_title": story["title"],
                                "first_seen_at": story["published_at"]
                            }
                            if new_cluster_emb:
                                update_payload["embedding"] = new_cluster_emb
                                
                            supabase.table("clusters").update(update_payload).eq("id", cluster_id).execute()

        except Exception as e:
            logger.error(f"Error matching cluster for story {story['id']}: {e}")
            continue

        if not cluster_id:
            # Create new cluster
            cluster_emb = get_embedding(story["title"])
            if not cluster_emb:
                logger.warning(f"Could not generate embedding for new cluster: {story['title']}")
                continue
                
            new_cluster = supabase.table("clusters").insert({
                "representative_title": story["title"],
                "first_seen_at": story["published_at"],
                "outlet_count": 0,
                "embedding": cluster_emb
            }).execute()
            cluster_id = new_cluster.data[0]["id"]
            created += 1

        # Assign story
        supabase.table("stories").update({"cluster_id": cluster_id}).eq("id", story["id"]).execute()
        assigned += 1
        
        # Update outlet count
        count_result = supabase.table("stories").select("id", count="exact").eq("cluster_id", cluster_id).execute()
        supabase.table("clusters").update({"outlet_count": count_result.count or 0}).eq("id", cluster_id).execute()

    # Run cleanup of old single-story clusters
    cleanup_old_clusters()

    # Get total clusters for response
    total_res = supabase.table("clusters").select("id", count="exact").execute()
    total_clusters = total_res.count or 0

    logger.info(f"Clustering complete. {assigned} stories assigned, {created} new clusters.")
    return {
        "stories_clustered": assigned,
        "new_clusters": created,
        "total_clusters": total_clusters,
    }
