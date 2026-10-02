"""A single story: cluster detail with live verdict, deep dive, summary, framing feedback."""
import logging
from fastapi import APIRouter
from pydantic import BaseModel
from app.db import supabase
from app.tier_utils import get_outlet_tier, is_republisher, normalize_tier_distribution
from app.monitoring_spirit import resolve_verdict
from app.summarizer import is_generation_failure
from app.coverage import render_safe_verdict, get_sourcing_info, get_outlets_cache, compute_live_coverage_tier_distribution

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/clusters/by-slug/{slug}")
def get_cluster_by_slug(slug: str):
    """Get full detailed analytics for a cluster and its stories by slug."""
    cluster_res = supabase.table("clusters").select("*, cluster_scores(*)").eq("slug", slug).execute()
    
    if not cluster_res.data:
        return {"error": "Cluster not found"}
        
    cluster = cluster_res.data[0]
        
    stories_res = supabase.table("stories").select(
        "*, story_bias_tags(bias_category_id, source), outlets(slug, name, government_alignment, independence_score, is_blog, logo_url, ownership_name, ownership_type, ownership_transparency, party_proximity, track_record_status, promotional_alignment_count, headquarters_city, geopolitical_lean)"
    ).eq("cluster_id", cluster["id"]).order("published_at", desc=False).execute()
    
    stories = stories_res.data or []
    
    outlets_map, behavioral_map = get_outlets_cache()
    
    cluster["coverage_stats"] = cluster.get("coverage_stats") or {}
    live_dist, churnalism_ratio = compute_live_coverage_tier_distribution(
        cluster["id"], 
        stories, 
        outlets_map, 
        behavioral_map
    )
    blog_count = live_dist.pop("blog", 0)
    
    cluster["coverage_stats"]["coverage_tier_distribution"] = live_dist
    cluster["coverage_stats"]["total_coverage"] = sum(live_dist.values())
    cluster["coverage_stats"]["blog_count"] = blog_count
    cluster["coverage_stats"]["churnalism_ratio"] = churnalism_ratio
    
    # Flatten the outlet metadata directly onto the story object
    for s in stories:
        if s.get("outlets"):
            out = s["outlets"]
            s["outlet_alignment"] = out.get("government_alignment")
            s["outlet_independence"] = out.get("independence_score")
            tier = get_outlet_tier(out.get("government_alignment"), out.get("is_blog"))
            s["outlet_tier"] = tier
            s["outlet_coverage_tier"] = tier
            s["outlet_logo_url"] = out.get("logo_url")
            if out.get("name"):
                s["outlet_name"] = out.get("name")
            
            behav = behavioral_map.get(out.get("slug"))
            s["outlet_s2_score"] = behav.get("s2_score") if behav else None
            s["outlet_republishes"] = is_republisher(s["outlet_s2_score"])

    # --- MONITORING SPIRIT VERDICT (LIVE ATOMIC COMPUTATION) ---
    try:
        # Determine the "loudest" tier for sourcing check
        loud_tier = "unscored"
        max_count = 0
        for t, c in live_dist.items():
            if t != "blog" and c > max_count:
                max_count = c
                loud_tier = t
        
        # 1. Synthesize sourcing info using the ported logic
        sourcing_info = get_sourcing_info(
            stories,
            outlets_map,
            behavioral_map,
            loud_tier
        )
        
        # 2. Extract entity and money figure tags
        has_entity_tag = False
        has_money_figure = False
        for s in stories:
            for t in s.get("story_bias_tags", []):
                cat_id = t.get("bias_category_id")
                if cat_id == "entity_mentions":
                    has_entity_tag = True
                elif cat_id == "money_figures":
                    has_money_figure = True
        
        # 3. Query the 3 most recent snapshots for persistence
        snap_res = supabase.table("coverage_snapshots") \
            .select("coverage_tier_distribution, outlet_count, snapshot_at") \
            .eq("cluster_id", cluster["id"]) \
            .order("snapshot_at", desc=True) \
            .limit(3) \
            .execute()
            
        snapshot_reads = snap_res.data or []
        
        # 4. Resolve verdict live
        verdict_res = resolve_verdict(
            tier_distribution=live_dist,
            total_outlets=cluster["coverage_stats"]["total_coverage"],
            churnalism_ratio=churnalism_ratio,
            category=cluster.get("category"),
            has_entity_tag=has_entity_tag,
            has_money_figure=has_money_figure,
            snapshot_reads=snapshot_reads,
            sourcing_info=sourcing_info
        )
        
        # Attach to the response. If anything above failed, this won't execute,
        # guaranteeing Invariant 1 (withhold rather than render stale).
        safe_verdict = render_safe_verdict(verdict_res)
        if safe_verdict is not None:
            # Snapshot distributions are normalised to the canonical tier keys
            # for display; unusable rows are dropped, never shown as zero.
            display_snapshots = []
            for snap in snapshot_reads:
                dist = normalize_tier_distribution(snap.get("coverage_tier_distribution"))
                if dist is None:
                    logger.error(f"Dropping unusable coverage snapshot for cluster {cluster['id']} at {snap.get('snapshot_at')}")
                    continue
                display_snapshots.append({**snap, "coverage_tier_distribution": dist})
            safe_verdict["snapshots"] = display_snapshots
            cluster["monitoring_spirit_live"] = safe_verdict
        
    except Exception:
        # Invariant 1: do not set monitoring_spirit_live
        logger.exception(f"Live verdict computation failed for cluster {cluster['id']}")
        
    return {"cluster": cluster, "stories": stories}



@router.get("/clusters/{id}/deep-dive")
def get_cluster_deep_dive(id: str):
    """Get full detailed analytics for a cluster and its stories."""
    cluster_res = supabase.table("clusters").select("*, cluster_scores(*)").eq("id", id).single().execute()
    cluster = cluster_res.data
    
    stories_res = supabase.table("stories").select(
        "*, story_bias_tags(bias_category_id, source), outlets(slug, name, government_alignment, independence_score, is_blog, logo_url, ownership_name, ownership_type, ownership_transparency, party_proximity, track_record_status, promotional_alignment_count, headquarters_city, geopolitical_lean)"
    ).eq("cluster_id", id).order("published_at", desc=False).execute()
    
    stories = stories_res.data or []
    
    outlets_map, behavioral_map = get_outlets_cache()
    
    cluster["coverage_stats"] = cluster.get("coverage_stats") or {}
    live_dist, churnalism_ratio = compute_live_coverage_tier_distribution(
        cluster["id"], 
        stories, 
        outlets_map, 
        behavioral_map
    )
    blog_count = live_dist.pop("blog", 0)
    
    cluster["coverage_stats"]["coverage_tier_distribution"] = live_dist
    cluster["coverage_stats"]["total_coverage"] = sum(live_dist.values())
    cluster["coverage_stats"]["blog_count"] = blog_count
    cluster["coverage_stats"]["churnalism_ratio"] = churnalism_ratio
    
    # Flatten the outlet metadata directly onto the story object
    for s in stories:
        if s.get("outlets"):
            out = s["outlets"]
            slug = out.get("slug")
            s["outlet_alignment"] = out.get("government_alignment")
            s["outlet_independence"] = out.get("independence_score")
            tier = get_outlet_tier(out.get("government_alignment"), out.get("is_blog"))
            s["outlet_tier"] = tier
            s["outlet_logo_url"] = out.get("logo_url")
            if out.get("name"):
                s["outlet_name"] = out.get("name")
            
            behav = behavioral_map.get(slug) if slug else None
            s["outlet_s2_score"] = behav.get("s2_score") if behav else None
            s["outlet_republishes"] = is_republisher(s["outlet_s2_score"])
            s["outlet_coverage_tier"] = tier
            
            # Carry forward all required outlet fields before deleting
            s["outlets_full"] = out
            del s["outlets"]

    if stories:
        stories[0]["broke_story_first"] = True
    
    return {
        "cluster": cluster,
        "stories": stories
    }


class FeedbackRequest(BaseModel):
    cluster_id: str
    tier: str
    comment: str

@router.post("/framing/feedback")
def submit_framing_feedback(req: FeedbackRequest):
    """Submit user feedback for AI framing."""
    supabase.table("framing_feedback").insert({
        "cluster_id": req.cluster_id,
        "tier": req.tier,
        "comment": req.comment
    }).execute()
    return {"status": "success"}



@router.get("/api/clusters/{id}/summary")
def get_cluster_summary(id: str):
    try:
        from app.storySummaryStrings import UI
        res = supabase.table("cluster_summaries").select("*").eq("cluster_id", id).order("generated_at", desc=True).limit(1).execute()
        if not res.data:
            return {"status": "pending", "bullets": [], "message": UI["pending"]}
        
        summary = res.data[0]
        # A correction supersedes the summary; never serve it while the
        # replacement is generated.
        if summary.get("superseded") is True:
            return {"status": "pending", "bullets": [], "message": UI["pending"]}
        if is_generation_failure(summary):
            return {"status": "error", "bullets": [], "message": UI["error"]}
        if summary.get("published"):
            return {"status": "published", "bullets": summary.get("bullets", [])}
        
        if summary.get("gate") in ["review", "suppress"] or summary.get("flags"):
            return {"status": "withheld", "bullets": [], "message": UI["withheld"]}
            
        return {"status": "error", "bullets": [], "message": UI["error"]}
    except Exception as e:
        logger.error(f"Error fetching summary for {id}: {e}")
        from app.storySummaryStrings import UI
        return {"status": "error", "bullets": [], "message": UI["error"]}
