"""Outlet and politician profiles."""
import logging
from fastapi import APIRouter, HTTPException
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


def _published_politician(slug: str):
    """The politician row if the page may be shown, else None. Held
    (pending_review), excluded (private figures) and inactive people are not
    shown anywhere."""
    res = supabase.table("politicians").select(
        "id, full_name, common_name, slug, party, state, geopolitical_region, "
        "category, current_position, active, wikipedia_image_url, publication_status"
    ).eq("slug", slug).eq("active", True).limit(1).execute()
    row = (res.data or [None])[0]
    if not row or (row.get("publication_status") or "published") != "published":
        return None
    return row


def _politician_articles(pid):
    """Every tagged article mentioning the person, with its outlet (paged)."""
    rows, offset = [], 0
    while True:
        page = supabase.table("story_entities").select(
            "story_id, stories(id, outlet_id)"
        ).eq("politician_id", pid).eq("entity_type", "politician").range(offset, offset + 999).execute().data or []
        rows.extend(page)
        if len(page) < 1000:
            return rows
        offset += 1000


@router.get("/politicians/{slug}/visibility")
def politician_visibility(slug: str):
    """Cheap check used by the site middleware: may this page be served?"""
    p = _published_politician(slug)
    if not p:
        return {"visible": False}
    any_article = supabase.table("story_entities").select("story_id").eq(
        "politician_id", p["id"]).eq("entity_type", "politician").limit(1).execute().data
    return {"visible": bool(any_article)}


@router.get("/politicians/{slug}")
def get_politician(slug: str):
    """
    Counts only (counsel, 3 Oct 2026): the number of articles naming the
    person, by the tier of the outlet that published each one, as of today.
    No percentages and no shares. Held, private, inactive and no-data pages
    are 404.
    """
    from datetime import datetime, timezone
    from app.coverage import get_outlets_cache
    from app.tier_utils import get_outlet_tier

    politician = _published_politician(slug)
    if not politician:
        raise HTTPException(status_code=404, detail="Not found")

    outlets_map, _ = get_outlets_cache()
    counts = {"govt_aligned": 0, "mainstream": 0, "watchdog": 0, "untiered": 0}
    seen = set()
    for e in _politician_articles(politician["id"]):
        story = e.get("stories") or {}
        sid = story.get("id")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        outlet = outlets_map.get(story.get("outlet_id"))
        tier = get_outlet_tier(outlet.get("government_alignment"), outlet.get("is_blog")) if outlet else "unscored"
        counts[tier if tier in counts else "untiered"] += 1
    total = len(seen)
    if total == 0:
        raise HTTPException(status_code=404, detail="Not found")

    recent_res = supabase.table("story_entities").select(
        "story_id, stories(id, title, url, published_at, image_url, cluster_id, "
        "clusters(slug, outlet_count, category, coverage_stats))"
    ).eq("politician_id", politician["id"]).eq("entity_type", "politician").order(
        "story_id", desc=False).limit(20).execute()
    recent_stories = []
    for e in (recent_res.data or []):
        st = e.get("stories") or {}
        if not st:
            continue
        cluster_data = st.pop("clusters", {}) or {}
        st["cluster_slug"] = cluster_data.get("slug")
        st["cluster_outlet_count"] = cluster_data.get("outlet_count")
        st["cluster_category"] = cluster_data.get("category")
        st["cluster_coverage_stats"] = cluster_data.get("coverage_stats")
        recent_stories.append(st)

    return {
        "politician": politician,
        "total_articles": total,
        "article_counts": counts,
        "as_of": datetime.now(timezone.utc).date().isoformat(),
        "recent_stories": recent_stories,
    }
