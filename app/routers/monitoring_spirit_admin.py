from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
from app.admin_auth import require_permission, get_actor_name
from app.db import supabase
from app.monitoring_spirit import resolve_verdict

router = APIRouter()

def _get_outlets_cache():
    """Outlets keyed by id (the stories' outlet_id), as the tier counting
    expects, and behavioural scores keyed by slug; cached for an hour. This
    used to key outlets by slug, so no story matched an outlet and every
    cluster counted as unscored."""
    from app.coverage import get_outlets_cache
    return get_outlets_cache()

@router.get("/api/admin/monitoring-spirit/verdicts")
def list_current_verdicts(_: str = Depends(require_permission('monitoring_spirit', 'view'))):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
    clusters = (
        supabase.table("clusters")
        .select("id, slug, representative_title, created_at, category, coverage_stats")
        .gte("created_at", cutoff)
        .execute()
    ).data or []

    if not clusters:
        return []

    cluster_ids = [c["id"] for c in clusters]

    overrides_data = []
    stories_data = []
    snaps_data = []

    def fetch(batch):
        overrides = supabase.table("verdict_overrides").select("cluster_id").eq("active", True) \
            .in_("cluster_id", batch).execute().data or []
        # Only what the verdict uses: the outlet (tiers come from the cached
        # outlet map) and the bias tags. Selecting "*" pulled every article's
        # text and embedding vector for nothing.
        stories = supabase.table("stories").select("cluster_id, outlet_id, story_bias_tags(bias_category_id, source)") \
            .in_("cluster_id", batch).execute().data or []
        snaps = supabase.table("coverage_snapshots").select(
            "cluster_id, coverage_tier_distribution, outlet_count, snapshot_at"
        ).in_("cluster_id", batch).order("snapshot_at", desc=True).execute().data or []
        return overrides, stories, snaps

    batches = [cluster_ids[i:i + 50] for i in range(0, len(cluster_ids), 50)]
    with ThreadPoolExecutor(max_workers=min(len(batches), 8)) as pool:
        for overrides, stories, snaps in pool.map(fetch, batches):
            overrides_data.extend(overrides)
            stories_data.extend(stories)
            snaps_data.extend(snaps)

    overridden_ids = {o["cluster_id"] for o in overrides_data}

    outlets_map, behavioral_map = _get_outlets_cache()
    from app.coverage import compute_live_coverage_tier_distribution, get_sourcing_info
    
    from collections import defaultdict
    stories_by_cluster = defaultdict(list)
    for s in stories_data:
        stories_by_cluster[s["cluster_id"]].append(s)
        
    snaps_by_cluster = defaultdict(list)
    for snap in snaps_data:
        if len(snaps_by_cluster[snap["cluster_id"]]) < 3:
            snaps_by_cluster[snap["cluster_id"]].append(snap)

    results = []
    for c in clusters:
        cid = c["id"]
        stories = stories_by_cluster.get(cid, [])
        
        live_dist, churnalism_ratio = compute_live_coverage_tier_distribution(
            cid, stories, outlets_map, behavioral_map
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
                    
        snapshot_reads = snaps_by_cluster.get(cid, [])
        
        # Same basis as the tier counts: distinct outlets in the card tiers.
        total_outlets = sum(live_dist.values())
        
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
                "cluster_id": cid,
                "slug": c["slug"],
                "headline": c["representative_title"],
                "verdict": verdict["verdict"],
                "evidence": verdict.get("evidence"),
                "has_active_override": cid in overridden_ids,
            })
    return results


class OverrideCreate(BaseModel):
    cluster_id: str
    original_verdict: str  # 'mixed' | 'dark'
    reason: str

@router.post("/api/admin/monitoring-spirit/overrides", status_code=201)
def create_override(payload: OverrideCreate, actor: str = Depends(get_actor_name), _: str = Depends(require_permission('monitoring_spirit', 'yes'))):
    if not payload.reason.strip():
        raise HTTPException(status_code=400, detail="Reason is required")

    res = supabase.table("verdict_overrides").insert({
        "cluster_id": payload.cluster_id,
        "original_verdict": payload.original_verdict,
        "reason": payload.reason,
        "actor": actor,
    }).execute()
    row = res.data[0]

    supabase.table("admin_audit_log").insert({
        "actor": actor,
        "action": "verdict.dismiss",
        "target_table": "verdict_overrides",
        "target_id": row["id"],
        "before_state": None,
        "after_state": row,
    }).execute()

    return row


@router.get("/api/admin/monitoring-spirit/overrides")
def list_overrides(_: str = Depends(require_permission('monitoring_spirit', 'view'))):
    res = (
        supabase.table("verdict_overrides")
        .select("*")
        .eq("active", True)
        .order("created_at", desc=True)
        .execute()
    )
    rows = res.data or []
    # The headline of each withdrawn story, so the Desk can say what it was.
    ids = list({r["cluster_id"] for r in rows if r.get("cluster_id")})
    titles = {}
    if ids:
        for c in supabase.table("clusters").select("id, slug, representative_title").in_("id", ids).execute().data or []:
            titles[c["id"]] = c
    for r in rows:
        c = titles.get(r.get("cluster_id")) or {}
        r["headline"] = c.get("representative_title")
        r["slug"] = c.get("slug")
    return rows


@router.post("/api/admin/monitoring-spirit/overrides/{override_id}/reinstate")
def reinstate_override(override_id: str, actor: str = Depends(get_actor_name), _: str = Depends(require_permission('monitoring_spirit', 'yes'))):
    before_res = supabase.table("verdict_overrides").select("*").eq("id", override_id).execute()
    if not before_res.data:
        raise HTTPException(status_code=404, detail="Not found")
    before = before_res.data[0]

    after_res = (
        supabase.table("verdict_overrides")
        .update({
            "active": False,
            "reinstated_at": datetime.now(timezone.utc).isoformat(),
            "reinstated_by": actor,
        })
        .eq("id", override_id)
        .execute()
    )
    after = after_res.data[0]

    supabase.table("admin_audit_log").insert({
        "actor": actor,
        "action": "verdict.reinstate",
        "target_table": "verdict_overrides",
        "target_id": override_id,
        "before_state": before,
        "after_state": after,
    }).execute()

    return after
