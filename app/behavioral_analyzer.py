import logging
import os
import json
from datetime import datetime, timezone
from app.db import supabase
from openai import OpenAI

logger = logging.getLogger(__name__)

openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

PROMPT_TEMPLATE = """You are the 'Monitoring Spirit' – an uncompromising Nigerian media intelligence engine.
Your task is to analyze a batch of recent articles from a specific Nigerian news outlet and evaluate their editorial independence, critical distance, and structural behavior.

You must evaluate the outlet based on these 4 core journalistic signals, agnostic of the topics (politics, crime, business, etc.) they cover:

1. Critical Distance (Voice & Sourcing): Does the outlet maintain an objective distance from power structures (state, corporate, elite)? Do they simply parrot press releases and official statements as unquestioned facts, or do they seek out affected citizens, independent experts, and alternative voices? 
2. Accountability vs. Sycophancy (Story Selection): Does the outlet actively pursue original, investigative, or accountability journalism (exposing failures, corruption, or public grievances)? Or does their selection systematically avoid controversy to amplify the achievements and PR narratives of those in power?
3. Brown Envelope Detection (Tone & Framing): ONLY flag this as true if there is undeniable, structural evidence of paid PR masquerading as news. Standard journalistic reporting of press releases or verbatim quoting of officials DOES NOT qualify. You must find the author actively injecting subjective praise without attribution (e.g., "the visionary governor", "proactive leadership") or completely uncritical replication of rhetoric in a way that breaks basic journalistic norms. If it is standard reporting or you are in doubt, you MUST default to false.
4. Anchored Independence Score (0-100): Assign a score strictly governed by these behavioral anchors:
   - 90-100 (Fiercely Independent): Consistently holds power to account. Breaks original investigative stories. Demonstrates clear critical distance from all official sources.
   - 70-89 (Strongly Independent): Maintains journalistic integrity and balanced sourcing, though occasionally relies on official narratives for standard reporting.
   - 50-69 (Mixed/Institutional): High reliance on official statements and access journalism. Covers accountability issues but rarely originates them. Tone is overly cautious around power.
   - 30-49 (Highly Deferential): Systematically favors elite/official narratives. Avoids sensitive accountability stories. Frequent evidence of press release replication.
   - 0-29 (Captured/PR Arm): Functions as a mouthpiece for state or corporate interests. Complete absence of critical distance. Overt sycophancy.

Respond in strict JSON format:
{
  "critical_distance_notes": "...",
  "accountability_notes": "...",
  "brown_envelope_suspected": true/false,
  "brown_envelope_evidence": "...",
  "independence_score": <integer 0-100>
}
"""

def analyze_outlet(outlet_id: int, limit: int = 50):
    logger.info(f"Starting behavioral analysis for outlet ID {outlet_id}")
    
    outlet_res = supabase.table("outlets").select("name, slug, ownership_type, geopolitical_lean").eq("id", outlet_id).execute()
    if not outlet_res.data:
        logger.error("Outlet not found.")
        return
    
    outlet = outlet_res.data[0]
    logger.info(f"Analyzing {outlet['name']}...")

    from datetime import timedelta
    from collections import defaultdict
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    
    # Pull stories from last 30 days
    stories_res = supabase.table("stories").select("title, summary, published_at").eq("outlet_id", outlet_id).gte("published_at", cutoff_date).order("published_at", desc=True).limit(1000).execute()
    all_stories = stories_res.data or []
    
    # Fallback to all stories if none found in 30 days
    if not all_stories:
        stories_res = supabase.table("stories").select("title, summary, published_at").eq("outlet_id", outlet_id).order("published_at", desc=True).limit(150).execute()
        all_stories = stories_res.data or []
        
    if not all_stories:
        logger.warning("No stories found for this outlet.")
        return
        
    # Group by day and pick top 5 longest summaries per day
    stories_by_day = defaultdict(list)
    for s in all_stories:
        pub_at = s.get("published_at")
        if pub_at:
            day = pub_at[:10]  # simple YYYY-MM-DD grouping
            stories_by_day[day].append(s)
            
    selected_stories = []
    for day, day_stories in stories_by_day.items():
        # Sort by summary length desc
        day_stories.sort(key=lambda x: len(x.get("summary") or ""), reverse=True)
        selected_stories.extend(day_stories[:5])
        
    # Prepare text batch for LLM
    content_batch = []
    for s in selected_stories:
        content_batch.append(f"Title: {s.get('title')}\nSummary: {s.get('summary')}")
        
    batch_text = "\n\n---\n\n".join(content_batch)
    
    try:
        res = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": PROMPT_TEMPLATE},
                {"role": "user", "content": f"Outlet: {outlet['name']}\nOwnership: {outlet['ownership_type']}\n\nRecent Articles:\n{batch_text}"}
            ],
            response_format={ "type": "json_object" },
            temperature=0.0
        )
        
        analysis = json.loads(res.choices[0].message.content)
        
        logger.info(f"Analysis complete for {outlet['name']}. Score: {analysis.get('independence_score')}")
        
        # Update outlet with new behavioral data
        update_data = {
            "independence_score": analysis.get("independence_score"),
            "last_behavioral_scan": datetime.now(timezone.utc).isoformat(),
        }
        
        # We can also track brown envelope violations by incrementing the tally if suspected
        if analysis.get("brown_envelope_suspected"):
            # Fetch current count
            curr_res = supabase.table("outlets").select("brown_envelope_count").eq("id", outlet_id).execute()
            curr_count = curr_res.data[0].get("brown_envelope_count") or 0
            update_data["brown_envelope_count"] = curr_count + 1
            
            # Change track record status if it gets too high
            if update_data["brown_envelope_count"] >= 3:
                update_data["track_record_status"] = "Problematic"
            elif update_data["brown_envelope_count"] >= 1:
                update_data["track_record_status"] = "Flagged"
                
        supabase.table("outlets").update(update_data).eq("id", outlet_id).execute()
        return analysis
        
    except Exception as e:
        logger.error(f"Failed to analyze outlet: {e}")
        return None

def run_pilot():
    print("Running Pilot Behavioral Analysis...")
    target_slugs = ["punch-ng", "vanguard", "sahara-reporters", "nta"]
    res = supabase.table("outlets").select("id, name, slug").in_("slug", target_slugs).execute()
    
    if not res.data:
        print("No target outlets found in the database.")
        return
        
    for o in res.data:
        print(f"\n--- Analyzing {o['name']} ({o['slug']}) ---")
        result = analyze_outlet(o['id'], limit=20)
        print(json.dumps(result, indent=2))

if __name__ == "__main__":
    run_pilot()
