import re
import statistics
from datetime import datetime, timezone
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from app.db import supabase
from app.main import compute_live_coverage_tier_distribution
from app.monitoring_spirit import (
    resolve_verdict,
    is_significant,
    has_persistence,
    has_sourcing,
    TIER_GOVT,
    TIER_MAINSTREAM,
    TIER_WATCHDOG
)
from app.monitoring_spirit_shadow import get_entity_tag_flag, get_sourcing_info, get_snapshot_reads, MONEY_PATTERN

def run_step_b():
    print("=" * 70)
    print("GATE D CAMPAIGN-WINDOW RE-RUN (STEP B)")
    print("=" * 70)

    # 1. Fetch Campaign Window clusters
    all_campaign_clusters = set()
    offset = 0
    while True:
        res = supabase.table("clusters").select("id").gte("first_seen_at", "2026-08-19T00:00:00Z").range(offset, offset + 999).execute()
        data = res.data or []
        for row in data:
            all_campaign_clusters.add(row["id"])
        if len(data) < 1000:
            break
        offset += 1000
    
    # 2. Get snapshot counts
    def fetch_snapshot_page(off):
        try:
            return supabase.table("coverage_snapshots").select("cluster_id").range(off, off + 999).execute().data
        except:
            return []

    snapshot_counts = Counter()
    offsets = range(0, 800000, 1000)
    with ThreadPoolExecutor(max_workers=5) as executor:
        for page_data in executor.map(fetch_snapshot_page, offsets):
            for row in page_data:
                snapshot_counts[row["cluster_id"]] += 1
                
    campaign_counts = {cid: count for cid, count in snapshot_counts.items() if cid in all_campaign_clusters}
    for cid in all_campaign_clusters:
        if cid not in campaign_counts:
            campaign_counts[cid] = 0

    top_500 = sorted(campaign_counts.items(), key=lambda x: x[1], reverse=True)[:500]
    top_500_ids = [cid for cid, count in top_500]

    # Report Sample Composition
    counts_only = [c for cid, c in top_500]
    print(f"Sample Composition:")
    print(f"  Cluster count: {len(top_500)}")
    print(f"  Date range: 2026-08-19 onward")
    print(f"  Snapshot-count distribution: Min {min(counts_only)}, Max {max(counts_only)}, Median {statistics.median(counts_only)}\n")

    # Fetch full data for top 500
    res = supabase.table("clusters").select("id, slug, representative_title, category, outlet_count").in_("id", top_500_ids).execute()
    clusters = res.data or []

    outlets_res = supabase.table("outlets").select("*").execute()
    outlets_map = {o["id"]: o for o in (outlets_res.data or [])}
    
    behav_res = supabase.table("outlet_behavioral_scores").select("*").execute()
    behavioral_map = {b["outlet_slug"]: b for b in (behav_res.data or [])}

    diagnostics = {
        "total_analyzed": 0,
        "excluded_no_stories": 0,
        "excluded_no_tier_assignable": 0,
        "had_silence_pattern": 0,
        "silence_pattern_significant": 0,
        "silence_pattern_persistent": 0,
        "silence_pattern_sourced": 0,
        "dark": 0
    }

    dark_candidates = []
    mixed_results = []
    
    missing_tier_outlets = set()

    for c in clusters:
        cid = c["id"]
        category = c.get("category")
        
        stories_res = supabase.table("stories").select("id, outlet_id, summary, source_type, published_at").eq("cluster_id", cid).execute()
        cluster_stories = stories_res.data or []
        
        if not cluster_stories:
            diagnostics["excluded_no_stories"] += 1
            continue
            
        story_ids = [s["id"] for s in cluster_stories]
        
        live_dist, churn = compute_live_coverage_tier_distribution(cid, cluster_stories, outlets_map, behavioral_map)
        dist = live_dist
        total = sum(live_dist.values())
        
        if total == 0:
            diagnostics["excluded_no_tier_assignable"] += 1
            # Which outlets were responsible?
            for s in cluster_stories:
                oid = s.get("outlet_id")
                out = outlets_map.get(oid)
                if out:
                    missing_tier_outlets.add((out.get("name"), oid))
            continue
        
        has_entity = get_entity_tag_flag(story_ids)
        has_money = bool(MONEY_PATTERN.search(c.get("representative_title", "")))
        snapshot_reads = get_snapshot_reads(cid)
        
        diagnostics["total_analyzed"] += 1
            
        govt_pct = (dist.get(TIER_GOVT, 0) / total if total else 0)
        watch_pct = (dist.get(TIER_WATCHDOG, 0) / total if total else 0)
        
        has_silence_shape = ((watch_pct >= 0.6 and govt_pct <= 0.1) or (govt_pct >= 0.7 and watch_pct <= 0.1))
        
        if has_silence_shape:
            diagnostics["had_silence_pattern"] += 1
            sig = is_significant(category, has_entity, has_money, total)
            if sig:
                diagnostics["silence_pattern_significant"] += 1
            
            ta, tb = (TIER_WATCHDOG, TIER_GOVT) if watch_pct >= 0.6 and govt_pct <= 0.1 else (TIER_GOVT, TIER_WATCHDOG)
            
            pers = has_persistence(snapshot_reads, ta, tb)
            if sig and pers:
                diagnostics["silence_pattern_persistent"] += 1
            
            src_info = get_sourcing_info(cluster_stories, outlets_map, behavioral_map, ta)
            sourced = has_sourcing(src_info)
            if sig and pers and sourced:
                diagnostics["silence_pattern_sourced"] += 1
        
        govt = dist.get(TIER_GOVT, 0)
        watch = dist.get(TIER_WATCHDOG, 0)
        tier_a = TIER_WATCHDOG if watch > govt else TIER_GOVT
        
        sourcing_info = get_sourcing_info(cluster_stories, outlets_map, behavioral_map, tier_a)
        
        result = resolve_verdict(
            tier_distribution=dist,
            total_outlets=total,
            churnalism_ratio=churn,
            category=category,
            has_entity_tag=has_entity,
            has_money_figure=has_money,
            snapshot_reads=snapshot_reads,
            sourcing_info=sourcing_info
        )
        
        if result["verdict"] == "dark":
            diagnostics["dark"] += 1
            dark_candidates.append({
                "cluster": c,
                "tier_a": tier_a,
                "dist": dist,
                "stories": cluster_stories,
                "snapshot_count": len(snapshot_reads),
                "sourcing_info": sourcing_info,
                "evidence": result["evidence"]
            })
        elif result["verdict"] == "mixed":
            mixed_results.append({
                "cluster": c,
                "dist": dist,
                "evidence": result["evidence"]
            })

    print(f"Excluded Clusters: {diagnostics['excluded_no_stories'] + diagnostics['excluded_no_tier_assignable']}")
    print(f"  - No stories mapped: {diagnostics['excluded_no_stories']}")
    print(f"  - No tier assignable outlets: {diagnostics['excluded_no_tier_assignable']}")
    if missing_tier_outlets:
        print("    Outlets missing tiers:")
        for name, oid in list(missing_tier_outlets)[:10]:
            print(f"      - {name} ({oid})")
    print()
    print("=" * 70)
    print("FULL FUNNEL")
    print("=" * 70)
    print(f"Total analyzed (unexcluded): {diagnostics['total_analyzed']}")
    print(f" -> Silence shape: {diagnostics['had_silence_pattern']}")
    print(f" -> Significant: {diagnostics['silence_pattern_significant']}")
    print(f" -> Persistent: {diagnostics['silence_pattern_persistent']}")
    print(f" -> Sourcing-passed: {diagnostics['silence_pattern_sourced']}")
    print(f" -> DARK count: {diagnostics['dark']}")
    print()

    print("=" * 70)
    print("DARK CANDIDATES (FULL DETAIL)")
    print("=" * 70)
    if not dark_candidates:
        print("None.")
    for d in dark_candidates:
        c = d["cluster"]
        print(f"Headline: {c.get('representative_title')}")
        print(f"Category: {c.get('category')}")
        print(f"Total Outlet Count: {sum(d['dist'].values())}")
        print(f"Tier counts: {d['dist']}")
        
        silent_tier = TIER_GOVT if d["tier_a"] == TIER_WATCHDOG else TIER_WATCHDOG
        print(f"Loud Tier: {d['tier_a']} | Silent Tier: {silent_tier}")
        print(f"Snapshot reads checking for persistence: {d['snapshot_count']}")
        
        loud_outlets = []
        silent_outlets = []
        seen_outlets = set()
        for s in d["stories"]:
            oid = s.get("outlet_id")
            if not oid or oid in seen_outlets:
                continue
            seen_outlets.add(oid)
            out = outlets_map.get(oid)
            if not out: continue
            
            slug = out.get("slug")
            behav = behavioral_map.get(slug)
            
            tier = "unscored"
            if out.get("credibility_tier") == "blog":
                tier = "blog"
            elif behav and behav.get("independence_score") is not None:
                score = behav.get("independence_score")
                if behav.get("promotional_alignment_flag") or score < 35:
                    tier = "pro_establishment"
                elif score < 60:
                    tier = "institutional"
                else:
                    tier = "adversarial"
            else:
                g_align = out.get("government_alignment")
                if g_align == "pro_government":
                    tier = "pro_establishment"
                elif g_align == "opposition":
                    tier = "adversarial"
                elif g_align == "neutral":
                    tier = "institutional"
            
            if tier == d["tier_a"]:
                loud_outlets.append(out.get("name"))
            elif tier == silent_tier:
                silent_outlets.append(out.get("name"))
        
        print(f"Outlets on LOUD side ({len(loud_outlets)}): {', '.join(loud_outlets)}")
        print(f"Outlets on SILENT side ({len(silent_outlets)}): {', '.join(silent_outlets) if silent_outlets else 'None'}")
        print("Sourcing details:", d["sourcing_info"])
        print("Verdict Evidence:")
        for e in d["evidence"]:
            print(f"  - [{e['label']}] {e['detail']}")
        print()

    print("=" * 70)
    print("NOTABLE MIXED RESULTS")
    print("=" * 70)
    if not mixed_results:
        print("None.")
    for m in mixed_results:
        c = m["cluster"]
        print(f"- {c.get('representative_title')} ({c.get('category')})")
        print(f"  Tier counts: {m['dist']}")
        print(f"  Evidence: {', '.join([e['detail'] for e in m['evidence']])}")

if __name__ == "__main__":
    run_step_b()
