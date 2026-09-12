import re
from datetime import datetime, timezone
from app.db import supabase
from app.main import (
    compute_live_coverage_tier_distribution
)
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from app.tier_utils import get_outlet_tier
from app.monitoring_spirit import (
    resolve_verdict,
    is_significant,
    has_persistence,
    has_sourcing,
    TIER_GOVT,
    TIER_MAINSTREAM,
    TIER_WATCHDOG
)

MONEY_PATTERN = re.compile(
    r'₦|naira|billion|million|\$|'
    r'USD|trn|bn',
    re.IGNORECASE
)


def get_entity_tag_flag(story_ids):
    """
    True if ANY story in this 
    cluster has a story_entities 
    row.
    """
    if not story_ids:
        return False
    res = supabase.table(
        "story_entities"
    ).select("id").in_(
        "story_id", story_ids[:50]
    ).limit(1).execute()
    return bool(res.data)


def get_sourcing_info(
    cluster_stories,
    outlets_map,
    behavioral_map,
    tier_a
):
    """
    Uses the same tier-assignment 
    logic as 
    compute_live_coverage_tier_distribution()
    — behavioral_map first, 
    government_alignment fallback.
    This ensures sourcing check 
    and live distribution agree 
    on which tier each outlet is in.
    """
    loud_tier_outlet_ids = set()
    has_original = False
    
    seen_outlet_ids = set()
    for s in cluster_stories:
        oid = s.get("outlet_id")
        if not oid or oid in seen_outlet_ids:
            continue
        seen_outlet_ids.add(oid)
        
        if oid not in outlets_map:
            continue
        out = outlets_map[oid]
        slug = out.get("slug")
        behav = behavioral_map.get(slug) \
            if slug else None
        
        # Same logic as 
        # compute_live_coverage_tier_distribution
        tier = get_outlet_tier(out.get("government_alignment"), out.get("is_blog"))
        # Map to old names for shadow runner
        if tier == "govt_aligned": tier = "pro_establishment"
        elif tier == "watchdog": tier = "adversarial"
        elif tier == "mainstream": tier = "institutional"
        
        if tier == tier_a:
            loud_tier_outlet_ids.add(oid)
            if behav and behav.get(
                "s2_score", 0
            ) and behav["s2_score"] >= 50:
                has_original = True
    
    return {
        "distinct_outlets_in_loud_tier":
            len(loud_tier_outlet_ids),
        "has_original_reporting_outlet":
            has_original
    }


def get_snapshot_reads(cluster_id):
    res = supabase.table(
        "coverage_snapshots"
    ).select(
        "coverage_tier_distribution, "
        "outlet_count, snapshot_at"
    ).eq(
        "cluster_id", cluster_id
    ).order(
        "snapshot_at", desc=True
    ).limit(3).execute()
    
    reads = []
    for r in (res.data or []):
        reads.append({
            "tier_distribution": 
                r.get(
                    "coverage_tier_distribution", 
                    {}
                ) or {},
            "total": r.get("outlet_count", 0)
        })
    return reads


def run_shadow():
    print("=" * 70)
    print("MONITORING SPIRIT — SHADOW RUN")
    print(
        f"Started: "
        f"{datetime.now(timezone.utc).isoformat()}"
    )
    print("=" * 70)
    
    # Pull a diverse sample: recent 
    # clusters across categories, 
    # not just busy political days.
    # Deliberately include 
    # entertainment/sports to 
    # stress-test the significance 
    # rail with REAL data, not just 
    # our own unit test assumptions.
    print("Fetching snapshot counts to rank top 500 clusters...")
    
    def fetch_snapshot_page(offset):
        try:
            return supabase.table("coverage_snapshots").select("cluster_id").range(offset, offset + 999).execute().data
        except:
            return []

    snapshot_counts = Counter()
    offsets = range(0, 760000, 1000)
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        for page_data in executor.map(fetch_snapshot_page, offsets):
            for row in page_data:
                snapshot_counts[row["cluster_id"]] += 1
                
    top_500_ids = [cid for cid, _ in snapshot_counts.most_common(500)]
    print(f"Counted {sum(snapshot_counts.values())} total snapshots.")

    res = supabase.table(
        "clusters"
    ).select(
        "id, slug, representative_title, "
        "category, outlet_count"
    ).in_("id", top_500_ids).execute()
    
    clusters = res.data or []
    print(f"Sampled {len(clusters)} clusters initially\n")

    osun_count = 0
    borno_count = 0
    for c in clusters:
        text_to_check = ((c.get("category") or "") + " " + (c.get("slug") or "") + " " + (c.get("representative_title") or "")).lower()
        if "osun" in text_to_check or "election" in text_to_check or "vote" in text_to_check:
            osun_count += 1
        if "borno" in text_to_check or "military" in text_to_check or "security" in text_to_check or "army" in text_to_check or "boko" in text_to_check:
            borno_count += 1
            
    print(f"Initial sample Osun/Election matches: {osun_count}")
    print(f"Initial sample Borno/Security matches: {borno_count}")
    
    if osun_count < 10 or borno_count < 10:
        print("Supplementing sample with targeted clusters to meet Gate D spec...")
        supp_res = supabase.table("clusters").select(
            "id, slug, representative_title, category, outlet_count"
        ).gte("outlet_count", 3).or_(
            "slug.ilike.%osun%,slug.ilike.%borno%,slug.ilike.%election%,slug.ilike.%military%,slug.ilike.%security%,representative_title.ilike.%osun%,representative_title.ilike.%borno%"
        ).limit(100).execute()
        
        existing_ids = {c["id"] for c in clusters}
        for sc in (supp_res.data or []):
            if sc["id"] not in existing_ids:
                clusters.append(sc)
                existing_ids.add(sc["id"])
        print(f"Total sampled clusters after supplement: {len(clusters)}\n")
    
    outlets_res = supabase.table(
        "outlets"
    ).select("*").execute()
    outlets_map = {
        o["id"]: o 
        for o in (outlets_res.data or [])
    }
    
    # DEBUG — print first 5 outlet 
    # government_alignment values to 
    # confirm actual casing
    for oid, out in list(
        outlets_map.items()
    )[:5]:
        print(
            f"outlet tier sample: "
            f"{out.get('government_alignment')}"
        )
    
    behav_res = supabase.table(
        "outlet_behavioral_scores"
    ).select("*").execute()
    behavioral_map = {
        b["outlet_slug"]: b 
        for b in (behav_res.data or [])
    }
    
    results = {
        "clear": [],
        "mixed": [],
        "dark": []
    }
    
    diagnostics = {
        "total_analyzed": 0,
        "had_silence_pattern": 0,
        "silence_pattern_significant": 0,
        "silence_pattern_persistent": 0,
        "silence_pattern_sourced": 0,
        "had_2plus_snapshot_reads": 0,
        "had_0_snapshot_reads": 0,
        "had_1_snapshot_read": 0,
        "blocked_by_persistence": 0,
        "blocked_by_sourcing": 0
    }
    
    blocked_persistence_examples = []
    blocked_sourcing_examples = []
    
    for c in clusters:
        cid = c["id"]
        category = c.get("category")
        
        # Get stories for this cluster
        stories_res = supabase.table(
            "stories"
        ).select(
            "id, outlet_id, summary, "
            "source_type, published_at"
        ).eq(
            "cluster_id", cid
        ).execute()
        
        cluster_stories = stories_res.data or []
        
        if not cluster_stories:
            continue
            
        story_ids = [
            s["id"] for s in cluster_stories
        ]
        
        # Compute live tier distribution
        live_dist, churn = \
            compute_live_coverage_tier_distribution(
                cid, 
                cluster_stories, 
                outlets_map, 
                behavioral_map
            )
        
        dist = live_dist
        total = sum(live_dist.values())
        
        if total == 0:
            continue
        
        has_entity = get_entity_tag_flag(
            story_ids
        )
        has_money = bool(
            MONEY_PATTERN.search(
                c.get(
                    "representative_title", 
                    ""
                )
            )
        )
        
        snapshot_reads = get_snapshot_reads(
            cid
        )
        
        diagnostics["total_analyzed"] += 1
        
        if len(snapshot_reads) == 0:
            diagnostics["had_0_snapshot_reads"] += 1
        elif len(snapshot_reads) == 1:
            diagnostics["had_1_snapshot_read"] += 1
        else:
            diagnostics["had_2plus_snapshot_reads"] += 1
            
        govt_pct = (
            dist.get(TIER_GOVT, 0) / total 
            if total else 0
        )
        watch_pct = (
            dist.get(TIER_WATCHDOG, 0) / total 
            if total else 0
        )
        has_silence_shape = (
            (watch_pct >= 0.6 and govt_pct <= 0.1) or
            (govt_pct >= 0.7 and watch_pct <= 0.1)
        )
        if has_silence_shape:
            diagnostics["had_silence_pattern"] += 1
            
            sig = is_significant(
                category, has_entity, has_money, total
            )
            if sig:
                diagnostics[
                    "silence_pattern_significant"
                ] += 1
            
            # Determine actual tier_a/tier_b 
            # for this cluster
            if watch_pct >= 0.6 and govt_pct <= 0.1:
                ta, tb = TIER_WATCHDOG, TIER_GOVT
            else:
                ta, tb = TIER_GOVT, TIER_WATCHDOG
            
            pers = has_persistence(
                snapshot_reads, ta, tb
            )
            if pers:
                diagnostics[
                    "silence_pattern_persistent"
                ] += 1
            
            # Only check sourcing if we got 
            # this far — call the real 
            # get_sourcing_info function 
            # that's already in this file
            src_info = get_sourcing_info(
                cluster_stories,
                outlets_map,
                behavioral_map,
                ta
            )
            sourced = has_sourcing(src_info)
            if sourced:
                diagnostics[
                    "silence_pattern_sourced"
                ] += 1
            
            # NEW: track the actual blocking 
            # reason for each silence-shaped 
            # cluster that didn't reach DARK
            if sig and not pers:
                diagnostics.setdefault(
                    "blocked_by_persistence", 0
                )
                diagnostics["blocked_by_persistence"] += 1
                blocked_persistence_examples.append({
                    "title": c.get("representative_title"),
                    "category": category,
                    "outlet_count": total,
                    "tier_dist": dist,
                    "snapshot_count": len(snapshot_reads)
                })
            elif sig and pers and not sourced:
                diagnostics.setdefault(
                    "blocked_by_sourcing", 0
                )
                diagnostics["blocked_by_sourcing"] += 1
                blocked_sourcing_examples.append({
                    "title": c.get("representative_title"),
                    "category": category,
                    "outlet_count": total,
                    "tier_dist": dist,
                    "sourcing": src_info
                })
        
        # Determine loud tier for 
        # sourcing lookup
        govt = dist.get(TIER_GOVT, 0)
        watch = dist.get(TIER_WATCHDOG, 0)
        tier_a = (
            TIER_WATCHDOG 
            if watch > govt 
            else TIER_GOVT
        )
        
        sourcing_info = get_sourcing_info(
            cluster_stories, outlets_map, 
            behavioral_map, tier_a
        )
        
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
        
        results[result["verdict"]].append({
            "title": c.get(
                "representative_title"
            ),
            "category": category,
            "outlet_count": total,
            "verdict": result["verdict"],
            "evidence": result["evidence"],
            "rails": result["rails"]
        })
    
    print()
    print("=" * 70)
    print("DIAGNOSTIC: WHY DID DARK NOT FIRE?")
    print("=" * 70)
    for k, v in diagnostics.items():
        print(f"{k}: {v}")
    print()
    print(
        f"Clusters with a silence SHAPE "
        f"(loud/silent tier pattern, "
        f"before rails): "
        f"{diagnostics['had_silence_pattern']}"
    )
    print(
        f"Of those, significant: "
        f"{diagnostics['silence_pattern_significant']}"
    )
    print(
        f"Clusters with 2+ snapshot reads "
        f"(persistence rail even possible): "
        f"{diagnostics['had_2plus_snapshot_reads']}"
    )
    print(
        f"Clusters with 0 snapshot reads "
        f"(persistence rail CANNOT pass): "
        f"{diagnostics['had_0_snapshot_reads']}"
    )
    print()
    print(
        f"Of the {diagnostics['silence_pattern_significant']} "
        f"significant silence patterns:"
    )
    print(
        f"  Blocked by PERSISTENCE rail: "
        f"{diagnostics['blocked_by_persistence']}"
    )
    print(
        f"  Blocked by SOURCING rail "
        f"(passed persistence): "
        f"{diagnostics['blocked_by_sourcing']}"
    )
    print(
        f"  Passed all rails "
        f"(should be in DARK count): "
        f"{diagnostics['silence_pattern_significant'] - diagnostics['blocked_by_persistence'] - diagnostics['blocked_by_sourcing']}"
    )
    print()
    
    print()
    print("=" * 70)
    print("BLOCKED BY PERSISTENCE — review each")
    print("=" * 70)
    for ex in blocked_persistence_examples:
        print(f"\n{ex['title']}")
        print(f"  Category: {ex['category']}")
        print(f"  Outlets: {ex['outlet_count']}")
        print(f"  Tier dist: {ex['tier_dist']}")
        print(f"  Snapshot reads available: {ex['snapshot_count']}")

    print()
    print("=" * 70)
    print("BLOCKED BY SOURCING — review each")
    print("=" * 70)
    for ex in blocked_sourcing_examples:
        print(f"\n{ex['title']}")
        print(f"  Category: {ex['category']}")
        print(f"  Outlets: {ex['outlet_count']}")
        print(f"  Tier dist: {ex['tier_dist']}")
        print(f"  Sourcing: {ex['sourcing']}")
    print()

    print(
        f"CLEAR: {len(results['clear'])}"
    )
    print(
        f"MIXED: {len(results['mixed'])}"
    )
    print(
        f"DARK:  {len(results['dark'])}"
    )
    print()
    
    print("=" * 70)
    print(
        "ALL DARK VERDICTS — "
        "MANUAL REVIEW REQUIRED"
    )
    print(
        "Adversarial check: does EVERY "
        "one of these genuinely look "
        "like a coverage gap worth "
        "alarming a reader about? "
        "Any that don't are false "
        "positives the engine needs "
        "fixing for."
    )
    print("=" * 70)
    for d in results["dark"]:
        print(f"\nTitle: {d['title']}")
        print(f"Category: {d['category']}")
        print(
            f"Outlets: {d['outlet_count']}"
        )
        for e in d["evidence"]:
            print(
                f"  [{e['label']}] "
                f"{e['detail']}"
            )
    
    print()
    print("=" * 70)
    print(
        "SPORT/ENTERTAINMENT CHECK — "
        "should be zero DARK or MIXED "
        "from low-stakes categories "
        "unless entity/money tagged"
    )
    print("=" * 70)
    low_stakes_flagged = [
        d for d in 
        results["dark"] + results["mixed"]
        if d["category"] in (
            "Sports", "Entertainment"
        )
    ]
    if low_stakes_flagged:
        print(
            f"⚠ FOUND "
            f"{len(low_stakes_flagged)} "
            f"sport/entertainment "
            f"clusters flagged — "
            f"REVIEW THESE:"
        )
        for f in low_stakes_flagged:
            print(
                f"  - {f['title']} "
                f"({f['verdict']})"
            )
    else:
        print(
            "None found in this sample."
        )
    
    print()
    print("=" * 70)
    print(f"Total clusters analyzed: "
          f"{len(clusters)}")
    print(
        f"Completed: "
        f"{datetime.now(timezone.utc).isoformat()}"
    )
    print("=" * 70)


if __name__ == "__main__":
    run_shadow()
