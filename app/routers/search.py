"""Cluster search."""
import logging
from fastapi import APIRouter
from app.db import supabase

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/search")
def search_clusters(q: str, limit: int = 20):
    """Search clusters by keyword in representative_title."""
    res = supabase.table("clusters")\
        .select("id, slug, representative_title, outlet_count, category, coverage_stats, first_seen_at")\
        .ilike("representative_title", f"%{q}%")\
        .gte("outlet_count", 2)\
        .order("first_seen_at", desc=True)\
        .limit(limit)\
        .execute()
    return res.data

# ── OUTLETS API ─────────────────────────────────────
