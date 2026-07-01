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

def compute_snapshot_threshold(
    outlet_count: int) -> int:
  """
  Proportional change threshold for
  triggering an extra snapshot.
  Fire-points by cluster size:
  cluster 3  -> max(2, round(0.45)) = 2
  cluster 5  -> max(2, round(0.75)) = 2
  cluster 15 -> max(2, round(2.25)) = 3
  cluster 40 -> max(2, round(6.0))  = 6
  cluster 80 -> max(2, round(12.0)) = 12
  """
  return max(2, round(outlet_count 
    * 0.15))

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

                if outlet.get("credibility_tier") == "blog":
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
                    g_align = outlet.get("government_alignment")
                    if g_align == "pro_government":
                        tier = "pro_establishment"
                    elif g_align == "opposition":
                        tier = "adversarial"
                    elif g_align == "neutral":
                        tier = "institutional"

                if tier != "unscored":
                    coverage_tier[tier] += 1

                # Aggregate independence score (legacy)
                ind_score = outlet.get("independence_score")
                if ind_score is not None:
                    total_independence += ind_score
                    valid_independence_count += 1

            avg_independence = round(total_independence / valid_independence_count) if valid_independence_count > 0 else 50

            # Construct Coverage Stats JSON
            tier_dist = dict(coverage_tier)
            blog_count = tier_dist.pop("blog", 0)
            coverage_stats = {
                "geopolitical_distribution": dict(regions),
                "ownership_distribution": dict(ownership),
                "credibility_distribution": dict(credibility),
                "government_alignment_distribution": dict(gov_alignment),
                "coverage_tier_distribution": tier_dist,
                "total_coverage": sum(tier_dist.values()),
                "blog_count": blog_count,
                "average_independence_score": avg_independence,
                "primary_region": max(regions.items(), key=lambda x: x[1])[0] if regions else None
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


            # 5. Update the Clusters table
            safe_execute(supabase.table("clusters").update({"coverage_stats": coverage_stats}).eq("id", cluster["id"]))

            # --- coverage snapshot ---
            try:
              now = datetime.now(timezone.utc)
              
              last_snap = supabase.table(
                "coverage_snapshots"
              ).select(
                "snapshot_at, outlet_count, "
                "coverage_tier_distribution"
              ).eq(
                "cluster_id", cluster["id"]
              ).order(
                "snapshot_at", desc=True
              ).limit(1).execute()
              
              should_snapshot = False
              trigger_reason = "hourly"
              
              if not last_snap.data:
                should_snapshot = True
              else:
                prev = last_snap.data[0]
                prev_time = datetime.fromisoformat(
                  prev["snapshot_at"].replace(
                    "Z", "+00:00")
                )
                hours_since = (
                  now - prev_time
                ).total_seconds() / 3600
                
                prev_count = prev.get(
                  "outlet_count") or 0
                curr_count = coverage_stats.get(
                  "total_coverage") or 0
                
                if hours_since >= 1:
                  should_snapshot = True
                
                count_delta = abs(
                  curr_count - prev_count)
                threshold = compute_snapshot_threshold(
                  curr_count)
                
                prev_dist = prev.get(
                  "coverage_tier_distribution"
                ) or {}
                curr_dist = coverage_stats.get(
                  "coverage_tier_distribution"
                ) or {}
                
                tier_delta = 0
                for tier in [
                  "pro_establishment",
                  "institutional",
                  "adversarial"
                ]:
                  prev_share = (
                    prev_dist.get(tier, 0) /
                    max(prev_count, 1)
                  ) * 100
                  curr_share = (
                    curr_dist.get(tier, 0) /
                    max(curr_count, 1)
                  ) * 100
                  tier_delta = max(
                    tier_delta,
                    abs(curr_share - prev_share)
                  )
                
                if (count_delta >= threshold
                    or tier_delta >= 8):
                  should_snapshot = True
                  trigger_reason = "change_threshold"
              
              if should_snapshot:
                stories_res = supabase.table(
                  "stories"
                ).select(
                  "outlet_slug"
                ).eq(
                  "cluster_id", cluster["id"]
                ).execute()
                
                covering_slugs = list(set([
                  s["outlet_slug"]
                  for s in (
                    stories_res.data or []
                  )
                  if s.get("outlet_slug")
                ]))
                
                safe_execute(
                  supabase.table(
                    "coverage_snapshots"
                  ).insert({
                    "cluster_id": cluster["id"],
                    "snapshot_at": 
                      now.isoformat(),
                    "trigger_reason": 
                      trigger_reason,
                    "coverage_tier_distribution":
                      coverage_stats.get(
                        "coverage_tier_distribution"
                      ),
                    "outlet_count": 
                      coverage_stats.get(
                        "total_coverage"),
                    "covering_outlet_slugs":
                      covering_slugs,
                    "absent_expected_slugs": []
                  })
                )
            except Exception as e:
              logger.error(
                f"Snapshot insert failed for "
                f"{cluster['id']}: {e}"
              )
            # --- end coverage snapshot ---

            scored_count += 1



        except Exception as e:
            logger.error(f"Skipping cluster {cluster['id']} due to error: {e}")
            continue
    print(f"Backfill complete: {total} clusters updated")
    logger.info(f"Coverage Math complete. {scored_count} clusters calculated.")
    return {"clusters_scored": scored_count}
