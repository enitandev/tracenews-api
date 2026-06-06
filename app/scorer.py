import logging
import re
from datetime import datetime, timezone, timedelta
from app.db import supabase

logger = logging.getLogger(__name__)

# Basic bias colors mapped to slugs
BIAS_COLORS = {
    'misinformation': '#1A1A1A',
    'foreign-influence': '#2471A3',
    'government': '#008751',
    'opposition': '#C0392B',
    'tribal-ethnic': '#E67E22',
    'sensationalism': '#F39C12',
    'agenda': '#6C3483',
    'balanced': '#1a1a1a', # White background badge with black border on frontend
}

SENSATIONAL_WORDS = ["shocking", "bombshell", "unbelievable", "outrage", "exposed", "scandal", "panic", "destroyed"]
ATTRIBUTION_MARKERS = ["said", "stated", "according to", "documents show", "reported", "confirmed"]

def score_sensationalism(stories):
    if not stories: return 0.0
    total_score = 0
    for s in stories:
        title = s.get("title", "")
        # Check all caps (ignoring short words)
        words = title.split()
        caps_count = sum(1 for w in words if w.isupper() and len(w) > 3)
        if len(words) > 0 and caps_count / len(words) > 0.3:
            total_score += 1
        # Check exclamation marks
        if "!" in title:
            total_score += 1
        # Check trigger words
        if any(w in title.lower() for w in SENSATIONAL_WORDS):
            total_score += 1
    return total_score / len(stories)

def score_verification_quality(stories):
    if not stories: return "insufficient_data"
    
    # Check average length
    total_words = sum(len(s.get("summary", "").split()) for s in stories)
    avg_words = total_words / len(stories)
    if avg_words < 50:
        return "insufficient_data"
    
    markers_found = 0
    for s in stories:
        summary = s.get("summary", "").lower()
        if any(m in summary for m in ATTRIBUTION_MARKERS):
            markers_found += 1
    
    ratio = markers_found / len(stories)
    if ratio >= 0.6: return "High"
    if ratio >= 0.3: return "Moderate"
    return "Low"

def run_scoring(all_time: bool = False):
    logger.info("Starting scoring engine run...")
    
    # Get all clusters that need scoring (we can just score all recent ones to keep them updated as new stories arrive)
    query = supabase.table("clusters").select("id, outlet_count")
    if not all_time:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        query = query.gte("first_seen_at", cutoff)
        
    clusters_res = query.execute()
    clusters = clusters_res.data or []
    
    scored_count = 0
    
    for cluster in clusters:
        # Fetch all stories for this cluster
        stories_res = supabase.table("stories").select("*").eq("cluster_id", cluster["id"]).execute()
        stories = stories_res.data or []
        
        if len(stories) == 0:
            continue
            
        total = len(stories)
        
        # Dimensions setup
        gov_aligned = sum(1 for s in stories if s.get("party_proximity") == "government")
        opp_aligned = sum(1 for s in stories if s.get("party_proximity") == "opposition")
        neutral = total - gov_aligned - opp_aligned
        
        regions = {
            "north": sum(1 for s in stories if s.get("geopolitical_lean") == "North"),
            "southwest": sum(1 for s in stories if s.get("geopolitical_lean") == "Southwest"),
            "southeast": sum(1 for s in stories if s.get("geopolitical_lean") == "Southeast"),
            "niger_delta": sum(1 for s in stories if s.get("geopolitical_lean") == "Niger Delta"),
            "national": sum(1 for s in stories if s.get("geopolitical_lean") == "National"),
        }
        
        ownership = {
            "gov": sum(1 for s in stories if s.get("ownership_type") == "government"),
            "private": sum(1 for s in stories if s.get("ownership_type") == "private"),
            "foreign": sum(1 for s in stories if s.get("ownership_type") == "foreign"),
        }
        
        # Calculate percentages
        gov_pct = gov_aligned / total
        opp_pct = opp_aligned / total
        neutral_pct = neutral / total
        
        reg_pcts = {k: v / total for k, v in regions.items()}
        own_pcts = {k: v / total for k, v in ownership.items()}
        
        sens_score = score_sensationalism(stories)
        verif_qual = score_verification_quality(stories)
        
        # Blindspot check
        max_reg = max(reg_pcts, key=reg_pcts.get)
        max_reg_val = reg_pcts[max_reg]
        is_blindspot = max_reg_val > 0.75 and max_reg != "national" and total >= 3
        
        # Prioritized Dominant Bias Resolution
        dominant_slug = 'balanced'
        # Check misinformation (stub: we'd ideally check against a factcheck table, for now we leave it as a rule placeholder)
        has_misinfo = False # Placeholder
        
        if has_misinfo:
            dominant_slug = 'misinformation'
        elif own_pcts["foreign"] > 0.4:
            dominant_slug = 'foreign-influence'
        elif gov_pct > 0.6:
            dominant_slug = 'government'
        elif opp_pct > 0.6:
            dominant_slug = 'opposition'
        elif is_blindspot:
            dominant_slug = 'tribal-ethnic'
        elif sens_score >= 1.0:
            dominant_slug = 'sensationalism'
        # Agenda check (stub: low transparency + ownership concentration)
        
        scores_data = {
            "cluster_id": cluster["id"],
            "government_pct": gov_pct,
            "opposition_pct": opp_pct,
            "neutral_pct": neutral_pct,
            "north_pct": reg_pcts["north"],
            "southwest_pct": reg_pcts["southwest"],
            "southeast_pct": reg_pcts["southeast"],
            "national_pct": reg_pcts["national"],
            "niger_delta_pct": reg_pcts["niger_delta"],
            "gov_owned_pct": own_pcts["gov"],
            "private_pct": own_pcts["private"],
            "foreign_pct": own_pcts["foreign"],
            "sensationalism_score": sens_score,
            "verification_quality": verif_qual,
            "dominant_bias_slug": dominant_slug,
            "dominant_bias_color": BIAS_COLORS.get(dominant_slug, '#e5e5e5'),
            "is_blindspot": is_blindspot,
            "blindspot_region": max_reg if is_blindspot else None,
            "blindspot_type": "regional" if is_blindspot else None,
            "story_count": total,
            "scored_at": datetime.now(timezone.utc).isoformat()
        }
        
        supabase.table("cluster_scores").upsert(scores_data).execute()
        
        # Apply dominant tag to all stories in cluster for story_bias_tags junction
        bias_cat_res = supabase.table("bias_categories").select("id").eq("slug", dominant_slug).execute()
        if bias_cat_res.data:
            bias_id = bias_cat_res.data[0]["id"]
            for s in stories:
                supabase.table("story_bias_tags").upsert({
                    "story_id": s["id"],
                    "bias_category_id": bias_id,
                    "source": "automated"
                }, on_conflict="story_id, bias_category_id").execute()
                
        scored_count += 1

    logger.info(f"Scoring complete. {scored_count} clusters scored.")
    return {"clusters_scored": scored_count}
