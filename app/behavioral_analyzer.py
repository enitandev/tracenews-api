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
STATE_GOVT_OUTLETS = ['the-tide', 'kogi-reports', 'lagos-television-ltv']

KNOWN_ALIGNED_OUTLETS = [
  'the-nation',
  'blueprint-newspaper',
  'channels-tv'
]
# Cap at 45 - above Pro-Establishment
# threshold of 35 but below Institutional
# midpoint. These outlets have documented
# ownership/editorial alignment that 
# the 500-char RSS window cannot 
# fully capture.
KNOWN_ALIGNED_CAP = 45

LANGUAGE_SERVICE_OUTLETS = [
    'bbc-hausa',
    'bbc-yoruba', 
    'bbc-pidgin',
    'rfi-hausa',
    'aminiya',
    'voa-hausa'
]

SPECIALIST_OUTLETS = [
  'techpoint-africa',
  'techcabal',
  'technext',
  'investors-king',
  'naijatechguide',
  'the-africa-report',
  'dataphyte',
  'african-arguments',
  'quartz-africa',
  'complete-sports',
  'goal-nigeria',
  'sporting-life-nigeria',
  'brila-fm',
  'bellanaija'
]
# ---------------------------------------------------------
# AI PROMPTS
# ---------------------------------------------------------

PROMPT_COMBINED = """You are analyzing a Nigerian 
news article for the TraceNews Independence Index.

Analyze the headline and summary for ALL of 
the following signals in one pass and return 
a single JSON object.

SIGNAL 1 - Government Framing:
How is government framed in this text?
- "deferential": praises or presents official 
  claims uncritically
- "accountability": critical, exposes wrongdoing, 
  challenges official claims
- "neutral": factual, no clear framing
- "none": no government mentioned

SIGNAL 2 - Churnalism:
Does this read like original journalism or 
a reproduced press release/wire copy?
Strong churnalism indicators: "in a statement", 
"NAN reports", bureaucratic language, reads 
entirely as official announcement.
Original indicators: investigative language, 
fieldwork, critical tone.
Default to "mixed" when in doubt.

SIGNAL 4 - Lexical Deference:
Count deferential terms in EDITORIAL COPY ONLY 
(not in quotes): "His Excellency", "visionary", 
"Renewed Hope Agenda", "landmark achievement", 
"performing governor", "hardworking minister" etc.
Estimate word count.

SIGNAL 6 - Editorial Independence:
Does this article contain corrections, 
retractions, or clarifications of previous 
reporting? Look for: "Correction:", "Retraction:", 
"We earlier reported...", "Editor's Note:"

BROWN ENVELOPE:
Is this likely paid-for content? Only flag if 
ALL THREE apply:
1. Overwhelmingly positive toward a specific 
   official (in editorial voice, NOT in quotes)
2. No clear news hook
3. Single source dependency

Return ONLY a raw JSON object:

{
  "s1": {
    "government_framing": "deferential|accountability|neutral|none",
    "has_non_government_voice": true/false,
    "s1_classification": "independent|captured|neutral",
    "framing_explanation": "one sentence"
  },
  "s2": {
    "reporting_type": "original|press_release|wire_copy|mixed",
    "is_churnalism": true/false,
    "churnalism_evidence": "one sentence or empty string"
  },
  "s4": {
    "deferential_count": integer,
    "approximate_word_count": integer,
    "deference_density_per_1000_words": float
  },
  "s6": {
    "is_correction_or_retraction": true/false,
    "correction_type": "correction|retraction|clarification|follow_up|none"
  },
  "brown_envelope": {
    "overwhelmingly_positive_toward_official": true/false,
    "has_clear_news_hook": true/false,
    "single_source_dependent": true/false,
    "brown_envelope_suspected": true/false,
    "evidence": "one sentence or null"
  }
}

Article headline + summary:
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
                rb = ask_llm(PROMPT_COMBINED, clean_text(text))
                if rb and rb.get('brown_envelope', {}).get('brown_envelope_suspected'):
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
        'story_id': s.get('id'),
        'title': s.get('title', ''),
        'published_at': s.get('published_at', ''),
        's1_prominent': False,
        's2_original': False,
        's4_density': None,
        's6_correction': False,
        'be_layer2_flag': False,
        'elapsed': 0.0
    }
    
    try:
        rc = ask_llm(PROMPT_COMBINED, text)
        if rc:
            s1 = rc.get('s1', {})
            s2 = rc.get('s2', {})
            s4 = rc.get('s4', {})
            s6 = rc.get('s6', {})
            be = rc.get('brown_envelope', {})
            
            if s1.get('s1_classification') == 'independent':
                results['s1_prominent'] = True
            results['government_framing'] = s1.get('government_framing')
            
            if not s2.get('is_churnalism', True):
                results['s2_original'] = True
                
            results['s4_density'] = s4.get('deference_density_per_1000_words')
            
            if s6.get('is_correction_or_retraction'):
                results['s6_correction'] = True
                
            if be.get('brown_envelope_suspected'):
                results['be_layer2_flag'] = True
                
    except Exception as e:
        logger.error(f"Exception processing article {s.get('title')}: {str(e)}", exc_info=True)
        
    results['elapsed'] = time.time() - start_time
    return results

def analyze_outlet(outlet, current, total):
    start_time = time.time()
    outlet_id = outlet['id']
    outlet_slug = outlet['slug']
    outlet_name = outlet['name']
    
    sample, confidence_badge = fetch_sample(outlet_id)
    if not sample:
        logger.warning(f"No stories for {outlet_name}")
        return False
        
    sample_size = len(sample)
    print(f"\n[{current}/{total}] Analyzing: {outlet_name}")
    print(f"  Stories in sample: {sample_size}")
    print(f"  Confidence level: {confidence_badge}")
        
    s1_prominent_count = 0
    s2_original_count = 0
    s4_densities = []
    s6_corrections = 0
    
    be_layer1_flags = 0
    be_layer2_flags = 0
    
    total_articles = len(sample)
    logger.info(f"Starting ThreadPoolExecutor (max_workers=3) for {total_articles} articles...")
    
    completed = 0
    llm_results = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(analyze_article, s) for s in sample]
        for future in as_completed(futures):
            completed += 1
            try:
                res = future.result()
                llm_results.append(res)
                if completed % 10 == 0 or completed == total_articles:
                    print(f"  Progress: {completed}/{total_articles} articles", end="\r")
                if res['s1_prominent']: s1_prominent_count += 1
                if res['s2_original']: s2_original_count += 1
                if res['s4_density'] is not None: s4_densities.append(res['s4_density'])
                if res['s6_correction']: s6_corrections += 1
                if res['be_layer2_flag']: be_layer2_flags += 1
            except Exception as e:
                logger.error(f"Exception retrieving LLM result: {str(e)}", exc_info=True)

    # Brown Envelope Layer 1: Run sequentially to avoid concurrent connection overload
    logger.info(f"Running Brown Envelope Layer 1 sequentially for {total_articles} articles...")
    for result in llm_results:
        try:
            # Only run pgvector RPC if Layer 2 flagged it
            if result.get('be_layer2_flag'):
                embedding = get_story_embedding(result['story_id'])
                if embedding:
                    layer1_flag = run_brown_envelope_layer_1(embedding, result['published_at'])
                    result['brown_envelope_layer1'] = layer1_flag
                    if layer1_flag:
                        be_layer1_flags += 1
                else:
                    result['brown_envelope_layer1'] = False
            else:
                result['brown_envelope_layer1'] = False
        except Exception as e:
            logger.error(f"Exception in Layer 1 sequential check for {result.get('title')}: {e}")

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
    
    # S3 bypass for language services
    # and specialist beat outlets -
    # skip AI cluster classification
    # entirely, no wasted calls
    if outlet_slug in LANGUAGE_SERVICE_OUTLETS or \
        outlet_slug in SPECIALIST_OUTLETS:
        s3_score = 70.0
    else:
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
    if outlet.get('ownership_type', '').lower() == 'government':
        if outlet_slug in FEDERAL_GOVT_OUTLETS:
            final_tii = min(30.0, tii_raw)
        elif outlet_slug in STATE_GOVT_OUTLETS:
            final_tii = min(40.0, tii_raw)
        else:
            final_tii = min(40.0, tii_raw) # Default fallback for unlisted government outlets
            
    if outlet_slug in KNOWN_ALIGNED_OUTLETS:
        final_tii = min(final_tii, KNOWN_ALIGNED_CAP)
            
    # Brown Envelope Override
    layer1_rate = be_layer1_flags / len(sample) if sample else 0
    layer2_rate = be_layer2_flags / len(sample) if sample else 0
    brown_envelope_suspected = layer1_rate >= 0.10 or layer2_rate >= 0.10
    
    if brown_envelope_suspected:
        final_tii = min(final_tii, 34)
    
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
    
    print(f"\n  S1 Source Hierarchy:     {s1_score:.0f}")
    print(f"  S2 Churnalism:           {s2_score:.0f}")
    print(f"  S3 Omission Penalty:     {s3_score:.0f}")
    print(f"  S4 Lexical Deference:    {s4_score:.0f}")
    print(f"  S5 Story Selection:      {s5_score:.0f}")
    print(f"  S6 Editorial Indicators: {s6_score:.0f}")
    print(f"  Brown Envelope:          {brown_envelope_suspected}")

    try:
        # Upsert to behavioral scores (primary key is outlet_slug)
        with_retry(lambda: supabase.table("outlet_behavioral_scores").upsert(payload).execute())
        
        # Update main outlets table
        with_retry(lambda: supabase.table("outlets").update({"independence_score": int(round(final_tii))}).eq("id", outlet_id).execute())
    except Exception as e:
        logger.error(f"Failed to upsert scores for {outlet_name}: {e}")
        return False

    elapsed = time.time() - start_time
    print(f"  FINAL TII SCORE: {final_tii:.0f}")
    tier = 'Pro-Establishment' if final_tii < 35 else 'Institutional' if final_tii < 60 else 'Adversarial'
    print(f"  Tier: {tier}")
    print(f"  Saved. Time taken: {elapsed:.0f}s")
    
    return True

def already_scored_today(outlet_slug):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    res = with_retry(lambda: supabase.table("outlet_behavioral_scores")\
        .select("analyzed_at, s1_score, independence_score")\
        .eq("outlet_slug", outlet_slug)\
        .gte("analyzed_at", cutoff)\
        .not_.is_("s1_score", "null")\
        .execute())
    return res.data[0].get('independence_score', 'N/A') if res.data else None

def main(slugs=None):
    batch_start = time.time()
    scored_count = 0
    skipped_count = 0
    error_count = 0

    try:
        if slugs:
            outlets = []
            for slug in slugs:
                res = with_retry(lambda: supabase.table("outlets")\
                    .select("id, name, slug, ownership_type")\
                    .eq("slug", slug)\
                    .eq("active", True)\
                    .execute())
                if res.data:
                    outlets.extend(res.data)
        else:
            outlets_res = with_retry(lambda: supabase.table("outlets").select("id, name, slug, ownership_type").eq("active", True).execute())
            outlets = outlets_res.data or []
    except Exception as e:
        logger.error(f"Failed to fetch active outlets in main: {e}")
        return
        
    print(f"=== TraceNews TII Analyzer ===")
    print(f"Starting batch run at {datetime.now()}")
    print(f"Outlets to process: {len(outlets)}")
    print(f"==============================")
    
    total = len(outlets)
    for i, o in enumerate(outlets):
        current = i + 1
        existing_score = already_scored_today(o['slug'])
        if existing_score is not None:
            print(f"[{current}/{total}] SKIP: {o['name']} - already scored today (TII: {existing_score})")
            skipped_count += 1
            continue
            
        try:
            story_res = with_retry(lambda: supabase.table("stories")\
                .select("id", count="exact")\
                .eq("outlet_id", o['id'])\
                .neq("source_type", "fact_check")\
                .execute())
                
            if story_res.count < 50:
                print(f"[{current}/{total}] SKIP: {o['name']} - insufficient stories ({story_res.count})")
                skipped_count += 1
                continue
                
            success = analyze_outlet(o, current, total)
            if success:
                scored_count += 1
            else:
                error_count += 1
            time.sleep(3)
        except Exception as e:
            logger.error(f"Error processing {o['name']}: {e}")
            error_count += 1
            
    total_elapsed = time.time() - batch_start
    print(f"\n=== Batch Complete ===")
    print(f"Outlets scored: {scored_count}")
    print(f"Outlets skipped: {skipped_count}")
    print(f"Errors: {error_count}")
    print(f"Total time: {total_elapsed:.0f}s")
    print(f"=====================")

if __name__ == "__main__":
    import sys
    slugs = sys.argv[1:] if len(sys.argv) > 1 else None
    main(slugs)
