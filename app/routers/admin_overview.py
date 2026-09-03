from fastapi import APIRouter, Depends
from app.admin_auth import require_permission
from app.db import supabase

router = APIRouter(prefix="/api/admin/overview", tags=["admin"])

@router.get("")
async def get_overview(_: str = Depends(require_permission('console_access', 'view'))):
    # 1. Figures
    # Open corrections
    corr_res = supabase.table("correction_requests").select("id", count="exact").eq("status", "open").execute()
    open_corrections_count = corr_res.count if corr_res.count is not None else 0

    from datetime import datetime, timezone, timedelta
    
    from app.routers.monitoring_spirit_admin import list_current_verdicts
    verdicts_data = await list_current_verdicts(_)
    live_verdicts_count = len(verdicts_data)
    
    # Politicians held (needing review)
    pol_res = supabase.table("politicians").select("id", count="exact").eq("publication_status", "held").execute()
    politicians_held_count = pol_res.count if pol_res.count is not None else 0
    
    # Ingestion health (return empty if no real table)
    ingestion_status = "unknown"
    
    figures = {
        "corrections": open_corrections_count,
        "verdicts": live_verdicts_count,
        "politicians_held": politicians_held_count,
        "ingestion": ingestion_status
    }
    
    # 2. Sections
    open_corrections = supabase.table("correction_requests").select("id, type, outlet_slug, created_at").eq("status", "open").order("created_at", desc=True).limit(5).execute().data or []
    live_verdicts = verdicts_data[:5]
    
    # 3. Standing Column
    try:
        wire_res = supabase.table("ingestion_log").select("*").order("created_at", desc=True).limit(5).execute()
        wire_events = wire_res.data or []
    except Exception:
        wire_events = []
    
    # Real platform stats (return empty dictionary as we don't have tables for this yet)
    platform_stats = {}
    
    ledger_res = supabase.table("admin_audit_log").select("*").order("created_at", desc=True).limit(3).execute()
    ledger_entries = ledger_res.data or []
    
    return {
        "figures": figures,
        "sections": {
            "awaiting_action": open_corrections,
            "live_verdicts": live_verdicts
        },
        "standing": {
            "wire": wire_events,
            "platform": platform_stats,
            "ledger": ledger_entries
        }
    }
