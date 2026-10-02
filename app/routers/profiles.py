"""Outlet and politician profiles."""
import logging
from fastapi import APIRouter
from app.db import supabase

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/outlets")
def get_outlets():
    result = supabase.table("outlets").select("*").eq(
        "active", True
    ).order("name").execute()
    return {"outlets": result.data, "count": len(result.data)}


@router.get("/outlets/{slug}")
def get_outlet(slug: str):
    result = supabase.table("outlets").select("*").eq(
        "slug", slug
    ).single().execute()
    
    outlet_id = None
    if result.data:
        outlet_obj = result.data
        if isinstance(outlet_obj, list):
            outlet_id = outlet_obj[0].get("id")
        elif isinstance(outlet_obj, dict):
            outlet_id = outlet_obj.get("id")

    stories_data = []
    if outlet_id:
        stories_res = supabase.table(
            "stories"
        ).select(
            "id, title, url, summary, "
            "published_at, image_url, "
            "source_type, cluster_id, "
            "clusters(slug, outlet_count, "
            "category, coverage_stats)"
        ).eq(
            "outlet_id", outlet_id
        ).order(
            "published_at", desc=True
        ).limit(20).execute()
        stories_data = stories_res.data or []
    
    for s in stories_data:
        cluster_data = s.pop("clusters", {}) or {}
        s["cluster_slug"] = cluster_data.get("slug")
        s["cluster_outlet_count"] = cluster_data.get("outlet_count")
        s["cluster_category"] = cluster_data.get("category")
        s["cluster_coverage_stats"] = cluster_data.get("coverage_stats")

    return {
        "outlet": result.data,
        "recent_stories": stories_data,
    }


@router.get("/politicians/{slug}")
def get_politician(slug: str):
    # Fetch politician by slug
    result = supabase.table(
        "politicians"
    ).select(
        "id, full_name, common_name, "
        "slug, party, state, "
        "geopolitical_region, category, "
        "current_position, active, "
        "wikipedia_image_url, "
        "publication_status"
    ).eq(
        "slug", slug
    ).eq(
        "active", True
    ).single().execute()
    
    if not result.data:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=404,
            detail="Politician not found"
        )
    
    politician = result.data
    pub_status = politician.get(
        "publication_status", "published"
    )

    if pub_status == "excluded":
        from fastapi.responses import Response
        return Response(
            content='{"detail": "Gone — '
            'this page has been permanently '
            'withdrawn."}',
            status_code=410,
            media_type="application/json"
        )

    if pub_status == "pending_review":
        from fastapi.responses import Response
        return Response(
            content='{"detail": '
            '"Not found"}',
            status_code=404,
            media_type="application/json"
        )

    pid = politician["id"]
    
    # Fetch story entities for 
    # this politician
    # Get cluster IDs where this 
    # politician is mentioned
    entities_res = supabase.table(
        "story_entities"
    ).select(
        "story_id"
    ).eq(
        "politician_id", pid
    ).eq(
        "entity_type", "politician"
    ).execute()
    
    story_ids = [
        e["story_id"] 
        for e in (entities_res.data or [])
    ]
    
    total_count = len(story_ids)
    
    # Get recent stories via join
    # instead of .in_() with large list
    recent_res = supabase.table(
        "story_entities"
    ).select(
        "story_id, "
        "stories(id, title, url, "
        "published_at, image_url, "
        "cluster_id, "
        "clusters(slug, outlet_count, "
        "category, coverage_stats))"
    ).eq(
        "politician_id", pid
    ).eq(
        "entity_type", "politician"
    ).order(
        "story_id", desc=False
    ).limit(20).execute()

    recent_stories = []
    for e in (recent_res.data or []):
        s = e.get("stories") or {}
        if not s:
            continue
        cluster_data = \
            s.pop("clusters", {}) or {}
        s["cluster_slug"] = \
            cluster_data.get("slug")
        s["cluster_outlet_count"] = \
            cluster_data.get("outlet_count")
        s["cluster_category"] = \
            cluster_data.get("category")
        s["cluster_coverage_stats"] = \
            cluster_data.get(
                "coverage_stats"
            )
        recent_stories.append(s)

    # Get tier distribution via 
    # story_entities join
    dist_res = supabase.table(
        "story_entities"
    ).select(
        "story_id, "
        "stories(cluster_id, "
        "clusters(coverage_stats))"
    ).eq(
        "politician_id", pid
    ).eq(
        "entity_type", "politician"
    ).execute()
    
    tier_dist = {
        "govt_aligned": 0,
        "mainstream": 0,
        "watchdog": 0
    }
    seen_clusters = set()
    stories_with_dist = 0
    
    for e in (dist_res.data or []):
        s = e.get("stories") or {}
        cid = s.get("cluster_id")
        if not cid or cid in seen_clusters:
            continue
        seen_clusters.add(cid)
        
        cluster_data = \
            s.get("clusters") or {}
        stats = cluster_data.get(
            "coverage_stats", {}
        ) or {}
        dist = stats.get(
            "coverage_tier_distribution",
            {}
        ) or {}
        
        if dist:
            stories_with_dist += 1
            tier_dist["govt_aligned"] += dist.get("pro_establishment", dist.get("govt_aligned", 0))
            tier_dist["mainstream"] += dist.get("institutional", dist.get("mainstream", 0))
            tier_dist["watchdog"] += dist.get("adversarial", dist.get("watchdog", 0))
    
    return {
        "politician": politician,
        "total_story_count": total_count,
        "tier_distribution": tier_dist,
        "stories_with_distribution": 
            stories_with_dist,
        "recent_stories": recent_stories
    }
