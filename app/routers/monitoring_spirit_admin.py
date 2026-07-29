from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
from app.admin_auth import require_admin
from app.db import supabase
from app.monitoring_spirit import resolve_verdict

router = APIRouter()

def _get_outlets_cache():
    outlets_res = supabase.table("outlets").select("*").execute()
    outlets_map = {o["slug"]: o for o in (outlets_res.data or [])}
    behavioral_res = supabase.table("outlet_behavioral_scores").select("*").execute()
    behavioral_map = {b["outlet_slug"]: b for b in (behavioral_res.data or [])}
    return outlets_map, behavioral_map

@router.get("/api/admin/monitoring-spirit/verdicts")
async def list_current_verdicts(_: bool = Depends(require_admin)):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
    clusters = (
        supabase.table("clusters")
        .select("id, slug, representative_title, created_at, category, coverage_stats")
        .gte("created_at", cutoff)
        .execute()
    ).data or []

    overrides_res = (
        supabase.table("verdict_overrides")
        .select("cluster_id")
        .eq("active", True)
        .execute()
    )
    overridden_ids = {o["cluster_id"] for o in (overrides_res.data or [])}

    outlets_map, behavioral_map = _get_outlets_cache()
    from app.main import compute_live_coverage_tier_distribution, get_sourcing_info

    results = []
    for c in clusters:
        stories_res = supabase.table("stories").select(
            "*, story_bias_tags(bias_category_id, source), outlets(slug, name, government_alignment, independence_score, credibility_tier, logo_url, ownership_name, ownership_type, ownership_transparency, party_proximity, track_record_status, promotional_alignment_count, headquarters_city, geopolitical_lean)"
        ).eq("cluster_id", c["id"]).execute()
        stories = stories_res.data or []
        
        live_dist, churnalism_ratio = compute_live_coverage_tier_distribution(
            c["id"], stories, outlets_map, behavioral_map
        )
        
        loud_tier = "unscored"
        max_count = 0
        for t, cnt in live_dist.items():
            if t != "blog" and cnt > max_count:
                max_count = cnt
                loud_tier = t
                
        sourcing_info = get_sourcing_info(stories, outlets_map, behavioral_map, loud_tier)
        
        has_entity_tag = False
        has_money_figure = False
        for s in stories:
            for t in s.get("story_bias_tags", []):
                cat_id = t.get("bias_category_id")
                if cat_id == "entity_mentions":
                    has_entity_tag = True
                elif cat_id == "money_figures":
                    has_money_figure = True
                    
        snap_res = supabase.table("coverage_snapshots") \
            .select("coverage_tier_distribution, outlet_count, snapshot_at") \
            .eq("cluster_id", c["id"]) \
            .order("snapshot_at", desc=True) \
            .limit(3) \
            .execute()
        snapshot_reads = snap_res.data or []
        
        coverage_stats = c.get("coverage_stats") or {}
        total_outlets = coverage_stats.get("total_coverage", len(stories))
        
        verdict = resolve_verdict(
            tier_distribution=live_dist,
            total_outlets=total_outlets,
            churnalism_ratio=churnalism_ratio,
            category=c.get("category"),
            has_entity_tag=has_entity_tag,
            has_money_figure=has_money_figure,
            snapshot_reads=snapshot_reads,
            sourcing_info=sourcing_info
        )
        
        if verdict["verdict"] in ("mixed", "dark"):
            results.append({
                "cluster_id": c["id"],
                "slug": c["slug"],
                "headline": c["representative_title"],
                "verdict": verdict["verdict"],
                "evidence": verdict.get("evidence"),
                "has_active_override": c["id"] in overridden_ids,
            })
    return results


class OverrideCreate(BaseModel):
    cluster_id: str
    original_verdict: str  # 'mixed' | 'dark'
    reason: str
    actor: str  # named person, required — never "admin"

@router.post("/api/admin/monitoring-spirit/overrides", status_code=201)
async def create_override(payload: OverrideCreate, _: bool = Depends(require_admin)):
    if not payload.reason.strip():
        raise HTTPException(status_code=400, detail="Reason is required")
    if not payload.actor.strip():
        raise HTTPException(status_code=400, detail="Actor is required")

    res = supabase.table("verdict_overrides").insert({
        "cluster_id": payload.cluster_id,
        "original_verdict": payload.original_verdict,
        "reason": payload.reason,
        "actor": payload.actor,
    }).execute()
    row = res.data[0]

    supabase.table("admin_audit_log").insert({
        "actor": payload.actor,
        "action": "verdict.dismiss",
        "target_table": "verdict_overrides",
        "target_id": row["id"],
        "before_state": None,
        "after_state": row,
    }).execute()

    return row


@router.get("/api/admin/monitoring-spirit/overrides")
async def list_overrides(_: bool = Depends(require_admin)):
    res = (
        supabase.table("verdict_overrides")
        .select("*")
        .eq("active", True)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data


class ReinstateRequest(BaseModel):
    actor: str

@router.post("/api/admin/monitoring-spirit/overrides/{override_id}/reinstate")
async def reinstate_override(override_id: str, payload: ReinstateRequest, _: bool = Depends(require_admin)):
    before_res = supabase.table("verdict_overrides").select("*").eq("id", override_id).execute()
    if not before_res.data:
        raise HTTPException(status_code=404, detail="Not found")
    before = before_res.data[0]

    after_res = (
        supabase.table("verdict_overrides")
        .update({
            "active": False,
            "reinstated_at": datetime.now(timezone.utc).isoformat(),
            "reinstated_by": payload.actor,
        })
        .eq("id", override_id)
        .execute()
    )
    after = after_res.data[0]

    supabase.table("admin_audit_log").insert({
        "actor": payload.actor,
        "action": "verdict.reinstate",
        "target_table": "verdict_overrides",
        "target_id": override_id,
        "before_state": before,
        "after_state": after,
    }).execute()

    return after
