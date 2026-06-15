import os
import time
import json
import logging
from datetime import datetime, timezone
from app.db import supabase
from app.behavioral_analyzer import analyze_outlet

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("batch_analyzer")

TARGET_OUTLETS = [
    "quartz-africa", "ait", "the-tide", "reuters-africa",
    "daily-independent", "goal-nigeria", "punch-metro",
    "dataphyte", "blueprint-newspaper", "the-nation",
    "vanguard-delta", "sahara-reporters", "pointblank-news",
    "osun-defender", "al-jazeera-africa", "fij-nigeria",
    "voa-hausa", "pulse-nigeria", "sporting-life-nigeria",
    "the-point", "african-arguments", "pm-news",
    "arise-news", "bellanaija"
]

def run_batch():
    logger.info("Starting batch behavioral analysis for top 25 outlets")
    
    results_summary = []
    
    for slug in TARGET_OUTLETS:
        logger.info(f"\n{'='*50}\nProcessing: {slug}\n{'='*50}")
        
        try:
            # 1. Fetch outlet ID
            outlet_res = supabase.table("outlets").select("id, name").eq("slug", slug).execute()
            if not outlet_res.data:
                logger.error(f"Outlet not found for slug: {slug}")
                continue
                
            outlet_id = outlet_res.data[0]["id"]
            
            # 2. Count stories to log sample size
            stories_res = supabase.table("stories").select("id").eq("outlet_id", outlet_id).limit(100).execute()
            sample_size = len(stories_res.data) if stories_res.data else 0
            
            if sample_size == 0:
                logger.warning(f"No stories found for {slug}. Skipping.")
                continue
                
            # 3. Run analyzer (this internally limits to top stories based on the analyze_outlet function)
            analysis = analyze_outlet(outlet_id, limit=100)
            
            if not analysis:
                logger.error(f"Analysis returned None for {slug}")
                continue
                
            # 4. Save to outlet_behavioral_scores
            score_data = {
                "outlet_slug": slug,
                "independence_score": analysis.get("independence_score"),
                "critical_distance_notes": analysis.get("critical_distance_notes", ""),
                "accountability_notes": analysis.get("accountability_notes", ""),
                "story_selection_notes": analysis.get("story_selection_notes", ""),
                "brown_envelope_suspected": analysis.get("brown_envelope_suspected", False),
                "brown_envelope_evidence": analysis.get("brown_envelope_evidence", ""),
                "story_sample_size": sample_size,
                "analyzed_at": datetime.now(timezone.utc).isoformat()
            }
            
            supabase.table("outlet_behavioral_scores").upsert(score_data).execute()
            
            logger.info(f"Successfully processed {slug}. Score: {analysis.get('independence_score')}")
            
            # Add to summary
            results_summary.append({
                "outlet_slug": slug,
                "independence_score": analysis.get("independence_score"),
                "brown_envelope_suspected": analysis.get("brown_envelope_suspected")
            })
            
        except Exception as e:
            logger.error(f"FAILED on {slug}: {str(e)}")
            # Continue to next outlet
            
        # 3 second delay
        time.sleep(3)
        
    # Print final summary
    print("\n\n" + "*"*60)
    print("FINAL BATCH RESULTS SUMMARY")
    print("*"*60)
    print(f"{'OUTLET SLUG':<30} | {'SCORE':<5} | {'BROWN ENVELOPE'}")
    print("-" * 60)
    for res in results_summary:
        print(f"{res['outlet_slug']:<30} | {res['independence_score']:<5} | {res['brown_envelope_suspected']}")
    print("*"*60)

if __name__ == "__main__":
    # Ensure Supabase has the table first (requires user to run the migration)
    run_batch()
