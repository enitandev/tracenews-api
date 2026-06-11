import os
import json
import time
import random
import logging
import html
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
from app.db import supabase

logger = logging.getLogger(__name__)
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

FEDERAL_GOVT_OUTLETS = ['nta', 'nan', 'voice-of-nigeria', 'radio-nigeria']
STATE_GOVT_OUTLETS = ['the-tide', 'kogi-reports']

# ---------------------------------------------------------
# AI PROMPTS
# ---------------------------------------------------------

PROMPT_S1 = """You are analyzing a Nigerian news article for the TraceNews Independence Index.

You ONLY have access to the headline and the first ~500 characters of the article (a short summary). You must work with this limited text only.

Task: Determine how government officials or their actions are framed in the available text.

Government framing categories:
- "deferential": The text praises, supports, or presents government/official claims uncritically (e.g. "visionary governor", "landmark achievement", "committed leadership", "Renewed Hope Agenda" used positively).
- "accountability": The text is critical, exposes wrongdoing, challenges official claims, or presents government actions negatively (e.g. "minister denies corruption", "EFCC arraigns governor", "leaked documents show...", "residents protest government failure").
- "neutral": Factual reporting with no clear positive or negative framing of government.
- "none": No government official or action is mentioned.

Also check for non-government voices in the available text: opposition, civil society, expert, citizen, activist, etc.

Note: has_non_government_voice = true only counts toward "independent" if the non-government voice presents a perspective DIFFERENT from the official narrative — not if they are also praising the same government action.

Return ONLY a raw JSON object with no markdown, no extra text:

{
  "government_framing": "deferential|accountability|neutral|none",
  "has_non_government_voice": true/false,
  "framing_explanation": "one short sentence explaining the classification",
  "s1_classification": "independent|captured|neutral"
}

Classification rules for s1_classification:
- "independent" if government_framing = "accountability" OR has_non_government_voice = true
- "captured" if government_framing = "deferential" AND has_non_government_voice = false
- "neutral" for everything else

Article headline + summary:
{article_text}"""


PROMPT_S2 = """You are analyzing a Nigerian news article for the TraceNews Independence Index.

You ONLY have access to the headline and the first ~500 characters of the article (a short summary). Work only with this limited text.

Task: Determine whether this looks like original journalism or churnalism (reproduction of government press release, NAN wire copy, or paid statement).

Strong indicators of churnalism even in short summaries:
- Phrases like "in a statement", "according to a statement", "the statement read", "issued by", "signed by", "his office said", "government spokesman said"
- NAN attribution: "NAN reports", "NAN correspondent", "from NAN"
- Bureaucratic or promotional language with no critical context
- Text reads like direct transcription of an official announcement

Indicators of original reporting even in short text:
- Investigative language: "leaked documents show", "our investigation revealed", "citizens allege", "whistleblower claims"
- Citizen-sourced or social media evidence
- Critical or questioning tone toward official claims

Return ONLY a raw JSON object with no markdown, no extra text:

{
  "has_statement_language": true/false,
  "has_nan_attribution": true/false,
  "has_investigative_language": true/false,
  "reporting_type": "original|press_release|wire_copy|mixed",
  "is_churnalism": true/false,
  "churnalism_evidence": "one short sentence describing what triggered this classification"
}

"is_churnalism" = true only if reporting_type is "press_release" or "wire_copy".
"is_churnalism" = false if reporting_type is "original" or "mixed".

Article headline + summary:
{article_text}"""


PROMPT_S4 = """You are analyzing a Nigerian news article for a media intelligence platform.

Your task is to count the use of deferential language applied to government officials, politicians, or government policies in EDITORIAL COPY ONLY.

IMPORTANT: Do NOT count anything inside direct quotation marks. You are only counting language the journalist or editor chose to use themselves — not language attributed to a speaker.

You are looking for:

1. Repeated unnecessary honorifics in editorial text:
   Standard journalism: "Governor Sanwo-Olu said..." (acceptable once)
   Deferential: "His Excellency, the Executive Governor, His Excellency Sanwo-Olu..." (excessive, counts as deferential)
   
   Deferential honorifics to count (when used repeatedly beyond first formal mention):
   "His Excellency", "Her Excellency", "His Royal Highness", "The Executive Governor", "The Distinguished Senator", "The Honourable Minister", "The Rt. Honourable Speaker", "The Visionary Governor", "The Performing Governor"

2. Sanitizing adjectives applied to officials or their actions in editorial voice (NOT in quotes):
   "visionary", "performing", "hardworking", "amiable", "magnanimous", "sagacious", "indefatigable", "diligent", "proactive", "passionate", "tireless", "selfless", "dedicated", "purposeful", "astute", "illustrious", "eminent", "distinguished", "esteemed"

3. Government PR phrases reproduced uncritically as editorial voice:
   "Renewed Hope Agenda", "moving the nation forward", "building a better Nigeria", "transformational leadership", "landmark achievement", "historic initiative", "game-changing policy", "people-oriented governance"

Do NOT count:
- Any of the above when inside direct quotation marks
- Standard formal titles used once at first mention
- Neutral descriptive language

Count the total words in the article (approximate).

Return ONLY a raw JSON object with no markdown formatting:

{
  "deferential_terms_found": ["exact terms found in editorial copy"],
  "deferential_count": integer,
  "approximate_word_count": integer,
  "deference_density_per_1000_words": float,
  "is_high_deference": true/false
}

"deference_density_per_1000_words" = (deferential_count / word_count) * 1000
"is_high_deference" = true if deference_density_per_1000_words > 3.0

Article:
{article_text}"""


PROMPT_S5_HEADLINES = """You are analyzing a sample of Nigerian news headlines for a media intelligence platform.

Classify each headline into exactly one category:

"accountability": The story investigates or reports government failure, corruption, misconduct, policy failure, court rulings against the state, protests against the government, security failures, or holds officials to account for their actions.
  Examples:
  - "EFCC arraigns minister for N4bn fraud"
  - "Court orders government to pay compensation to victims"
  - "Residents protest over abandoned road project"

"government_announcement": The story reports what the government says it is doing, achievements, inaugurations, appointments, policy launches presented from the government's perspective without challenge.
  Examples:
  - "Governor commissions new hospital"
  - "FG launches N50bn youth empowerment scheme"
  - "President swears in new ministers"

"neutral": Crime unrelated to government, international news, sports, entertainment, accidents, business news with no government accountability dimension.

Return ONLY a raw JSON object with no markdown formatting:

{
  "classifications": [
    {
      "index": 0,
      "headline": "headline text",
      "type": "accountability|government_announcement|neutral"
    }
  ],
  "accountability_count": integer,
  "government_announcement_count": integer,
  "neutral_count": integer,
  "total_classified": integer,
  "accountability_ratio": float
}

"accountability_ratio" = accountability_count / (accountability_count + government_announcement_count)
Exclude neutral stories from this ratio.
If both accountability and government_announcement are 0, return 0.5.

Headlines:
{headlines_list}"""


PROMPT_S6 = """You are analyzing a Nigerian news article for a media intelligence platform.

Your task is to determine whether this article is a correction, retraction, clarification, or follow-up that challenges the outlet's own previous reporting.

Look for these indicators:
- Explicit correction language: "Correction:", "Retraction:", "Clarification:", "Editor's Note:", "We earlier reported..."
- Follow-up stories that contradict or update a previous report: "Contrary to our earlier report...", "We have since established...", "New information shows..."
- Acknowledgment of error or inaccuracy in previous coverage

This does NOT include:
- Updates to breaking news (new developments, not corrections)
- Opinion pieces or letters to the editor
- Corrections to quotes attributed to other outlets

Return ONLY a raw JSON object with no markdown formatting:

{
  "is_correction_or_retraction": true/false,
  "correction_type": "correction|retraction|clarification|follow_up|none",
  "evidence": "exact phrase that triggered this classification or null"
}

Article:
{article_text}"""


PROMPT_BROWN_ENVELOPE = """You are analyzing a Nigerian news article for a media intelligence platform.

Detect whether this article is likely "brown envelope journalism" — paid-for or politically sponsored content published as if it were independent journalism.

Brown envelope journalism in Nigeria has a specific textual fingerprint. Check for ALL THREE of these conditions simultaneously:

Condition 1 — OVERWHELMINGLY POSITIVE SENTIMENT toward a specific politician, government official, or government agency:
The article contains extensive praise, positive framing, or celebratory language directed at a specific named individual or agency. The overall tone is promotional, not informational.

Condition 2 — NO CLEAR NEWS HOOK:
There is no recent event (election, policy announcement, crisis, court ruling, inauguration) in the last 48–72 hours that justifies this story being published today. The story is not pegged to anything newsworthy — it just praises the subject.

Condition 3 — SINGLE SOURCE DEPENDENCY:
The article quotes only the subject of the praise or their close allies or spokespersons. No independent, opposing, or unaffiliated voices are present.

IMPORTANT: Do NOT consider language inside direct quotation marks when evaluating Condition 1. Only evaluate editorial framing — the journalist's own words and choices.

Return ONLY a raw JSON object with no markdown formatting:

{
  "overwhelmingly_positive_toward_official": true/false,
  "has_clear_news_hook": true/false,
  "single_source_dependent": true/false,
  "brown_envelope_suspected": true/false,
  "subject_of_praise": "name of politician/official/agency or null",
  "evidence": "one sentence describing what triggered this flag or null"
}

"brown_envelope_suspected" = true ONLY if ALL THREE conditions are met:
overwhelmingly_positive_toward_official = true
AND has_clear_news_hook = false
AND single_source_dependent = true

Article:
{article_text}"""


PROMPT_CLUSTER_CLASS = """You are classifying a Nigerian news story for a media intelligence platform.

Classify this story headline into exactly one of these categories:

"accountability": Stories about government failure, corruption allegations, court rulings against the government or officials, protests, policy failures, budget misuse, security failures, human rights violations, official misconduct, investigations of public officials, mismanagement of public funds

"government_announcement": Routine government press releases, official inaugurations, government achievement reports, policy launches presented positively, official appointments, state visits

"neutral_news": Crime unrelated to government accountability, international news, sports, entertainment, accidents, natural disasters, business news with no government accountability dimension

Return ONLY a raw JSON object:

{
  "classification": "accountability|government_announcement|neutral_news",
  "confidence": "high|medium|low",
  "reasoning": "one sentence explanation"
}

Headline: {headline}"""


# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------

def clean_text(raw):
    # Parse and strip HTML tags
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(separator=" ")
    # Decode HTML entities
    text = html.unescape(text)
    # Collapse whitespace
    text = " ".join(text.split())
    return text[:500]

def with_retry(func, max_retries=5, delay=5):
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed after {max_retries} attempts: {e}")
                raise e
            logger.warning(f"Network error: {e}. Retrying {attempt+1}/{max_retries} in {delay}s...")
            time.sleep(delay)

def ask_llm(prompt_template, content):
    def _call():
        res = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt_template.replace("{article_text}", content).replace("{headlines_list}", content).replace("{headline}", content)}],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        return json.loads(res.choices[0].message.content)
    try:
        return with_retry(_call, max_retries=3, delay=5)
    except Exception as e:
        logger.error(f"LLM Error: {e}")
        return None

def get_story_embedding(story_id):
    try:
        res = with_retry(lambda: supabase.table("stories").select("embedding").eq("id", story_id).execute())
        if res.data:
            return res.data[0].get("embedding")
    except Exception as e:
        logger.error(f"Error fetching embedding: {e}")
    return None

def fetch_sample(outlet_id):
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    
    # Paginated fetch for all stories
    all_stories = []
    page_size = 100
    offset = 0
    while True:
        res = with_retry(lambda: supabase.table("stories")\
            .select("id, title, summary, cluster_id, published_at")\
            .eq("outlet_id", outlet_id)\
            .neq("source_type", "fact_check")\
            .range(offset, offset + page_size - 1)\
            .execute())
        
        batch = res.data or []
        all_stories.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
        
    total = len(all_stories)
    if total < 50:
        return all_stories, "Insufficient Data"
    
    # Paginated fetch for 30-day stories
    stories_30 = []
    offset = 0
    while True:
        res_30 = with_retry(lambda: supabase.table("stories")\
            .select("id, title, summary, cluster_id, published_at")\
            .eq("outlet_id", outlet_id)\
            .gte("published_at", cutoff_date)\
            .neq("source_type", "fact_check")\
            .range(offset, offset + page_size - 1)\
            .execute())
            
        batch = res_30.data or []
        stories_30.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
        
    total_30 = len(stories_30)
    
    if total < 150:
        return stories_30, "Low Confidence"
    elif total < 300:
        return sorted(stories_30, key=lambda x: x.get('published_at', ''), reverse=True)[:150], "Standard"
    else:
        return random.sample(stories_30, min(200, total_30)), "High Confidence"

def run_brown_envelope_layer_1(story_embedding, published_at):
    """Layer 1: Cosine similarity via pgvector RPC."""
    if not story_embedding or not published_at:
        return False
        
    try:
        res = with_retry(lambda: supabase.rpc('match_stories_brown_envelope', {
            'query_embedding': story_embedding,
            'match_threshold': 0.95,
            'pub_time': published_at,
            'time_window_hours': 24
        }).execute())
        
        matches = res.data or []
        unique_outlets = set([m['outlet_id'] for m in matches])
        
        # >= 3 different outlets
        if len(unique_outlets) >= 3:
            matched_ids = [m['id'] for m in matches]
            # Fetch text of matched articles
            stories_res = with_retry(lambda: supabase.table("stories").select("title, summary").in_("id", matched_ids).execute())
            
            # Check if any matched article is flagged as brown envelope
            for matched_story in (stories_res.data or []):
                text = f"{matched_story.get('title', '')}\n\n{matched_story.get('summary', '')}"
                rb = ask_llm(PROMPT_BROWN_ENVELOPE, text)
                if rb and rb.get('brown_envelope_suspected'):
                    return True
            return False
            
        return False
    except Exception as e:
        logger.error(f"Error querying Layer 1 Brown Envelope vector search: {e}")
        return False

def analyze_article(s):
    start_time = time.time()
    text = clean_text(f"{s.get('title', '')}\n\n{s.get('summary', '')}")
    results = {
        's1_prominent': False,
        's2_original': False,
        's4_density': None,
        's6_correction': False,
        'be_layer2_flag': False,
        'elapsed': 0.0
    }
    
    try:
        # Signal 1: Source Hierarchy
        r1 = ask_llm(PROMPT_S1, text)
        if r1:
            if r1.get('s1_classification') == 'independent':
                results['s1_prominent'] = True
            results['government_framing'] = r1.get('government_framing')
            
        # Signal 2: Churnalism
        r2 = ask_llm(PROMPT_S2, text)
        if r2 and not r2.get('is_churnalism'): results['s2_original'] = True
            
        # Signal 4: Lexical Deference
        r4 = ask_llm(PROMPT_S4, text)
        if r4: results['s4_density'] = r4.get('deference_density_per_1000_words', 0.0)
            
        # Signal 6: Editorial Independence
        r6 = ask_llm(PROMPT_S6, text)
        if r6 and r6.get('is_correction_or_retraction'): results['s6_correction'] = True
            
        # Brown Envelope Layer 2: Sentiment Triplet
        rb = ask_llm(PROMPT_BROWN_ENVELOPE, text)
        if rb and rb.get('brown_envelope_suspected'): results['be_layer2_flag'] = True
            
    except Exception as e:
        logger.error(f"Exception processing article {s.get('title')}: {str(e)}", exc_info=True)
        
    results['elapsed'] = time.time() - start_time
    return results

def analyze_outlet(outlet_id: int):
    logger.info(f"Analyzing outlet {outlet_id}")
    
    try:
        outlet_res = with_retry(lambda: supabase.table("outlets").select("*").eq("id", outlet_id).execute())
    except Exception as e:
        logger.error(f"Error fetching outlet {outlet_id}: {e}")
        return
        
    if not outlet_res.data:
        return
    outlet = outlet_res.data[0]
    outlet_slug = outlet['slug']
    
    sample, confidence_badge = fetch_sample(outlet_id)
    if not sample:
        logger.warning(f"No stories for {outlet['name']}")
        return
        
    s1_prominent_count = 0
    s2_original_count = 0
    s4_densities = []
    s6_corrections = 0
    
    be_layer1_flags = 0
    be_layer2_flags = 0
    
    total_articles = len(sample)
    logger.info(f"Starting ThreadPoolExecutor (max_workers=5) for {total_articles} articles...")
    
    completed = 0
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(analyze_article, s): s for s in sample}
        for future in as_completed(futures):
            s = futures[future]
            completed += 1
            try:
                res = future.result()
                logger.info(f"Finished article {completed}/{total_articles}: {s.get('title')} in {res['elapsed']:.2f}s")
                if res['s1_prominent']: s1_prominent_count += 1
                if res['s2_original']: s2_original_count += 1
                if res['s4_density'] is not None: s4_densities.append(res['s4_density'])
                if res['s6_correction']: s6_corrections += 1
                if res['be_layer2_flag']: be_layer2_flags += 1
            except Exception as e:
                logger.error(f"Exception retrieving result for {s.get('title')}: {str(e)}", exc_info=True)

    # Brown Envelope Layer 1: Run sequentially to avoid concurrent connection overload
    logger.info(f"Running Brown Envelope Layer 1 sequentially for {total_articles} articles...")
    for i, s in enumerate(sample):
        try:
            story_embedding = get_story_embedding(s['id'])
            if run_brown_envelope_layer_1(story_embedding, s.get('published_at')):
                be_layer1_flags += 1
        except Exception as e:
            logger.error(f"Exception in Layer 1 sequential check for {s.get('title')}: {e}")

    # Signal Scores
    s1_score = (s1_prominent_count / len(sample)) * 100 if sample else 0
    s2_score = (s2_original_count / len(sample)) * 100 if sample else 0
    avg_density = sum(s4_densities) / len(s4_densities) if s4_densities else 0
    s4_score = max(0, 100 - (avg_density * 10))
    
    if s6_corrections == 0: s6_score = 40
    elif s6_corrections <= 2: s6_score = 60
    elif s6_corrections <= 5: s6_score = 80
    else: s6_score = 100

    # 8. Signal 5 (Batch Story Selection)
    headlines = [s['title'] for s in sample if s.get('title')]
    # Send in chunks of 100 if needed, but per spec "up to 100"
    headlines_text = "\\n".join([f"{i}. {h}" for i, h in enumerate(headlines[:100])])
    r5 = ask_llm(PROMPT_S5_HEADLINES, headlines_text)
    s5_score = (r5.get('accountability_ratio', 0.5) * 100) if r5 else 50.0

    # 9. Signal 3 (Omission Penalty)
    # Calculate Total Active Outlets
    try:
        active_res = with_retry(lambda: supabase.table("outlets").select("id", count="exact").eq("active", True).execute())
        total_active_outlets = active_res.count if active_res.count else 144
    except Exception as e:
        logger.error(f"Error fetching total active outlets: {e}")
        total_active_outlets = 144
        
    ecosystem_threshold = int(total_active_outlets * 0.60)
    
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    try:
        clusters_res = with_retry(lambda: supabase.table("clusters").select("id, representative_title, outlet_count").gte("created_at", cutoff_date).gte("outlet_count", ecosystem_threshold).execute())
        cluster_list = clusters_res.data or []
    except Exception as e:
        logger.error(f"Error fetching major clusters: {e}")
        cluster_list = []
        
    major_clusters = []
    for c in cluster_list:
        r = ask_llm(PROMPT_CLUSTER_CLASS, c['representative_title'])
        if r and r.get('classification') == 'accountability':
            major_clusters.append(c['id'])
            
    if not major_clusters:
        s3_score = 70.0
    else:
        total_major = len(major_clusters)
        outlet_covered = 0
        for s in sample:
            if s.get('cluster_id') in major_clusters:
                outlet_covered += 1
                major_clusters.remove(s.get('cluster_id')) 
                
        s3_score = (outlet_covered / total_major) * 100

    # 10. TII Calculation
    tii_raw = (s1_score * 0.30) + (s2_score * 0.25) + (s3_score * 0.20) + (s4_score * 0.10) + (s5_score * 0.10) + (s6_score * 0.05)
    
    # Apply structural caps based on specific slugs
    final_tii = tii_raw
    if outlet.get('ownership_type') == 'government':
        if outlet_slug in FEDERAL_GOVT_OUTLETS:
            final_tii = min(30.0, tii_raw)
        elif outlet_slug in STATE_GOVT_OUTLETS:
            final_tii = min(40.0, tii_raw)
        else:
            final_tii = min(40.0, tii_raw) # Default fallback for unlisted government outlets
            
    # Brown Envelope Override
    layer1_rate = be_layer1_flags / len(sample) if sample else 0
    layer2_rate = be_layer2_flags / len(sample) if sample else 0
    brown_envelope_suspected = layer1_rate >= 0.10 or layer2_rate >= 0.10
    
    # 13. Upsert
    payload = {
        "outlet_slug": outlet_slug,
        "independence_score": int(round(final_tii)),
        "s1_score": int(round(s1_score)),
        "s2_score": int(round(s2_score)),
        "s3_score": int(round(s3_score)),
        "s4_score": int(round(s4_score)),
        "s5_score": int(round(s5_score)),
        "s6_score": int(round(s6_score)),
        "brown_envelope_suspected": brown_envelope_suspected,
        "confidence_level": confidence_badge,
        "story_sample_size": len(sample),
        "analyzed_at": datetime.now(timezone.utc).isoformat()
    }
    
    logger.info(f"Scored {outlet['name']}: {int(round(final_tii))}")
    
    try:
        # Upsert to behavioral scores (primary key is outlet_slug)
        with_retry(lambda: supabase.table("outlet_behavioral_scores").upsert(payload).execute())
        
        # Update main outlets table
        with_retry(lambda: supabase.table("outlets").update({"independence_score": int(round(final_tii))}).eq("id", outlet_id).execute())
    except Exception as e:
        logger.error(f"Failed to upsert scores for {outlet['name']}: {e}")

def already_scored_today(outlet_slug):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    res = with_retry(lambda: supabase.table("outlet_behavioral_scores")\
        .select("analyzed_at")\
        .eq("outlet_slug", outlet_slug)\
        .gte("analyzed_at", cutoff)\
        .execute())
    return len(res.data) > 0

def main():
    try:
        outlets_res = with_retry(lambda: supabase.table("outlets").select("id, name, slug").eq("active", True).execute())
        outlets = outlets_res.data or []
    except Exception as e:
        logger.error(f"Failed to fetch active outlets in main: {e}")
        return
        
    logger.info(f"Starting behavioral analysis for {len(outlets)} outlets...")
    for o in outlets:
        if already_scored_today(o['slug']):
            logger.info(f"Skipping {o['name']} - already scored today")
            continue
        analyze_outlet(o['id'])
        time.sleep(3)

if __name__ == "__main__":
    main()
