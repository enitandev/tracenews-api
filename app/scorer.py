import logging
import json
import os
import time
import httpx
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from app.db import supabase
from app.classifier import classify_cluster_hybrid

logger = logging.getLogger(__name__)

def safe_execute(query_builder, retries=3, delay=3):
    for attempt in range(retries):
        try:
            return query_builder.execute()
        except (httpx.HTTPError, httpx.TransportError) as e:
            logger.warning(f"Network error (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise


def run_scoring(all_time: bool = False):
    logger.info("Starting Monitoring Spirit Scoring Engine...")
    
    query = supabase.table("clusters").select("id, outlet_count, category, representative_title")
    if not all_time:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        query = query.gte("first_seen_at", cutoff)
    else:
        query = query.or_("coverage_stats.is.null,coverage_stats.eq.{}")
        
    clusters_res = safe_execute(query)
    clusters = clusters_res.data or []
    
    total = len(clusters)
    scored_count = 0
    processed = 0
    
    for cluster in clusters:
        processed += 1
        if processed % 100 == 0:
            print(f"Backfill progress: {processed}/{total} clusters")
        try:

            # Fetch all stories for this cluster
            stories_res = safe_execute(supabase.table("stories").select("*").eq("cluster_id", cluster["id"]))
            stories = stories_res.data or []

            if len(stories) == 0:
                continue

            total_stories = len(stories)

            # 1. Categorize if needed
            category = cluster.get("category")
            if not category:
                combined_summary = " ".join([s.get("summary", "") for s in stories])
                category = classify_cluster_hybrid(cluster.get("representative_title", ""), combined_summary)
                # Update the cluster with the new category
                safe_execute(supabase.table("clusters").update({"category": category}).eq("id", cluster["id"]))

            # 2. Fetch Master Outlet data dynamically for these stories
            outlet_ids = list(set(s["outlet_id"] for s in stories if s.get("outlet_id")))
            outlets_res = safe_execute(supabase.table("outlets").select("*").in_("id", outlet_ids))
            outlets_map = {o["id"]: o for o in (outlets_res.data or [])}

            # Fetch behavioral scores using slugs
            outlet_slugs = list(set(o.get("slug") for o in outlets_map.values() if o.get("slug")))
            behavioral_map = {}
            if outlet_slugs:
                behav_res = safe_execute(supabase.table("outlet_behavioral_scores").select("*").in_("outlet_slug", outlet_slugs))
                behavioral_map = {b["outlet_slug"]: b for b in (behav_res.data or [])}

            # 3. Calculate Coverage Math Variables
            regions = defaultdict(int)
            credibility = defaultdict(int)
            ownership = defaultdict(int)
            gov_alignment = defaultdict(int)
            coverage_tier = defaultdict(int)
            total_independence = 0
            valid_independence_count = 0

            for s in stories:
                oid = s.get("outlet_id")
                if not oid or oid not in outlets_map:
                    continue

                outlet = outlets_map[oid]
                slug = outlet.get("slug")

                # Map region, ownership, credibility, gov_alignment
                regions[outlet.get("geopolitical_lean") or "National"] += 1
                ownership[outlet.get("ownership_type", "Independent")] += 1
                credibility[outlet.get("credibility_tier", "Institutional")] += 1
                gov_alignment[outlet.get("government_alignment", "neutral")] += 1

                # Calculate Coverage Tier
                behav = behavioral_map.get(slug) if slug else None
                tier = "unscored"

                if behav and behav.get("independence_score") is not None:
                    if behav.get("brown_envelope_suspected"):
                        tier = "captured"
                    else:
                        score = behav.get("independence_score")
                        if score >= 70: tier = "independent"
                        elif score >= 35: tier = "deferential"
                        else: tier = "captured"
                else:
                    g_align = outlet.get("government_alignment")
                    if g_align == "pro_government":
                        tier = "captured"
                    elif g_align == "opposition":
                        tier = "independent"
                    elif g_align == "neutral":
                        tier = "deferential"

                if tier != "unscored":
                    coverage_tier[tier] += 1

                # Aggregate independence score (legacy)
                ind_score = outlet.get("independence_score")
                if ind_score is not None:
                    total_independence += ind_score
                    valid_independence_count += 1

            avg_independence = round(total_independence / valid_independence_count) if valid_independence_count > 0 else 50

            # Construct Coverage Stats JSON
            coverage_stats = {
                "geopolitical_distribution": dict(regions),
                "ownership_distribution": dict(ownership),
                "credibility_distribution": dict(credibility),
                "government_alignment_distribution": dict(gov_alignment),
                "coverage_tier_distribution": dict(coverage_tier),
                "average_independence_score": avg_independence,
                "total_coverage": total_stories
            }

            # 4. Monitoring Spirit Rules Engine
            monitoring_flags = []

            # Rule 1: The Coverage Gap (Dead Angle)
            if total_stories >= 5:
                major_regions = ["North", "Southwest", "Southeast", "South-South"]
                covered_regions = [r for r in major_regions if regions.get(r, 0) > 0]
                missing_regions = [r for r in major_regions if regions.get(r, 0) == 0]

                if covered_regions and missing_regions:
                    monitoring_flags.append({
                        "type": "COVERAGE_GAP",
                        "severity": "high",
                        "message": "This story is only being covered by national outlets. No regional publications from the North, Southwest, Southeast or South-South have picked it up.",
                        "icon": "eye-off"
                    })

            # Rule 2: Unverified Viral (Gistlover Effect)
            # If multiple stories exist but ALL are from 'Sensational/Gist' tier
            if total_stories >= 3 and credibility.get("Institutional", 0) == 0:
                monitoring_flags.append({
                    "type": "UNVERIFIED_VIRAL",
                    "severity": "critical",
                    "message": "Trending exclusively on unregulated/sensational blogs. No institutional verification.",
                    "icon": "alert-triangle"
                })

            # Rule 3: Fast Brown Envelope Detection (Identical Text Overlap)
            # We do a rapid text similarity check across summaries
            has_identical_pr = False
            if total_stories >= 3:
                summaries = [s.get("summary", "").strip() for s in stories if len(s.get("summary", "")) > 50]
                if len(summaries) >= 2:
                    # Compare first 100 chars of summaries
                    prefixes = [s[:100].lower() for s in summaries]
                    # If any prefix appears 3 or more times exactly, it's a copy-paste PR
                    counts = {p: prefixes.count(p) for p in set(prefixes)}
                    if any(c >= 3 for c in counts.values()):
                        has_identical_pr = True

            if has_identical_pr:
                monitoring_flags.append({
                    "type": "BROWN_ENVELOPE",
                    "severity": "medium",
                    "message": "High textual overlap detected. Coverage likely driven by synchronized Press Releases.",
                    "icon": "copy"
                })

            # 5. Update the Clusters table
            safe_execute(supabase.table("clusters").update({"coverage_stats": coverage_stats, "monitoring_flags": monitoring_flags}).eq("id", cluster["id"]))

            scored_count += 1



        except Exception as e:
            logger.error(f"Skipping cluster {cluster['id']} due to error: {e}")
            continue
    print(f"Backfill complete: {total} clusters updated")
    logger.info(f"Coverage Math complete. {scored_count} clusters calculated.")
    return {"clusters_scored": scored_count}
