import os
import json
import time
import random
import logging
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

PROMPT_S1 = """You are analyzing a Nigerian news article for a media intelligence platform.

Your task is to identify ALL sources quoted or referenced in this article.
For each source, identify their category and where they appear.

Source categories:
- "government": Ministers, presidents, governors, government agency spokespeople, military/police spokespersons speaking in official capacity, state-controlled media (NAN, NTA, Voice of Nigeria)
- "opposition": Opposition party politicians, activists running against the government, political critics of the current administration
- "civil_society": NGOs, human rights organizations, labor unions, religious leaders (when commenting on public affairs), professional bodies
- "expert": Academics, independent researchers, lawyers, economists, analysts with no stated political affiliation
- "citizen": Ordinary Nigerians, victims, eyewitnesses, unnamed sources

Position categories:
- "headline_or_first_paragraph": Source appears in the headline or first paragraph
- "early": Source appears in paragraphs 2–5
- "late": Source appears after paragraph 5 or at the end of the article

Count only sources that are actually quoted, paraphrased, or specifically referenced — not sources mentioned in passing.

Return ONLY a raw JSON object with no markdown formatting:

{
  "sources": [
    {
      "category": "government|opposition|civil_society|expert|citizen",
      "position": "headline_or_first_paragraph|early|late",
      "quote_count": integer
    }
  ],
  "non_government_in_prominent_position": true/false,
  "total_sources": integer,
  "government_source_count": integer,
  "non_government_source_count": integer
}

"non_government_in_prominent_position" = true if at least one opposition, civil_society, expert, or citizen source appears in headline_or_first_paragraph OR early position.

Article:
{article_text}"""


PROMPT_S2 = """You are analyzing a Nigerian news article for a media intelligence platform.

Your task is to determine whether this article is original journalism or a reproduction of a press release, government statement, or wire copy.

Nigerian media context: The News Agency of Nigeria (NAN) distributes government press releases that many outlets publish verbatim. Brown envelope journalism involves publishing paid-for content that looks like news. These practices are common and are what you are detecting.

Look for these specific indicators of press release reproduction:
- Phrases like "according to a statement", "in a statement", "the statement read", "signed by", "issued by his office"
- NAN attribution ("NAN reports", "from our correspondent (NAN)")
- Bureaucratic formatting: long official titles before every name
- No evidence of independent reporting, fieldwork, or original interviews
- Generic bylines like "Staff Reporter", "Our Reporter", "Agency Report"
- The entire article reads as a transcription of an official speech or statement

Look for these specific indicators of original reporting:
- Named journalist byline with specific reporting credit
- Direct quotes from interviews clearly conducted by the reporter
- Evidence of fieldwork: "visited the scene", "spoke to residents"
- Multiple independently gathered perspectives
- Reporter's own observations described

IMPORTANT: If an article contains phrases like 'according to documents obtained by [outlet]', 'documents seen by our reporter', 'investigation by [outlet] reveals', or 'exclusive documents' — these are indicators of ORIGINAL reporting, not press releases. Do not classify these as churnalism.

Return ONLY a raw JSON object with no markdown formatting:

{
  "has_statement_language": true/false,
  "has_nan_attribution": true/false,
  "has_named_journalist_byline": true/false,
  "has_original_interview_quotes": true/false,
  "reporting_type": "original|press_release|wire_copy|mixed",
  "is_churnalism": true/false,
  "churnalism_evidence": "brief description of what triggered this classification"
}

"is_churnalism" = true if reporting_type is "press_release" or "wire_copy"
"is_churnalism" = false if reporting_type is "original" or "mixed"

Article:
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

def ask_llm(prompt_template, content):
    try:
        res = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt_template.replace("{article_text}", content).replace("{headlines_list}", content).replace("{headline}", content)}],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        logger.error(f"LLM Error: {e}")
        return None

def get_story_embedding(story_id):
    res = supabase.table("stories")\
        .select("embedding")\
        .eq("id", story_id)\
        .execute()
    if res.data:
        return res.data[0].get("embedding")
    return None

def fetch_sample(outlet_id):
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    res = supabase.table("stories").select("id, title, summary, cluster_id, published_at").eq("outlet_id", outlet_id).neq("source_type", "fact_check").execute()
    all_stories = res.data or []
    
    total = len(all_stories)
    if total < 50:
        return all_stories, "Insufficient Data"
    
    res_30 = supabase.table("stories").select("id, title, summary, cluster_id, published_at").eq("outlet_id", outlet_id).gte("published_at", cutoff_date).neq("source_type", "fact_check").execute()
    stories_30 = res_30.data or []
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
        res = supabase.rpc('match_stories_brown_envelope', {
            'query_embedding': story_embedding,
            'match_threshold': 0.95,
            'pub_time': published_at,
            'time_window_hours': 24
        }).execute()
        
        matches = res.data or []
        unique_outlets = set([m['outlet_id'] for m in matches])
        
        # >= 3 different outlets
        if len(unique_outlets) >= 3:
            matched_ids = [m['id'] for m in matches]
            # Fetch text of matched articles
            stories_res = supabase.table("stories").select("title, summary").in_("id", matched_ids).execute()
            
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
    text = f"{s.get('title', '')}\n\n{s.get('summary', '')}"
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
        if r1 and r1.get('non_government_in_prominent_position'): results['s1_prominent'] = True
            
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
    
    outlet_res = supabase.table("outlets").select("*").eq("id", outlet_id).execute()
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
    active_res = supabase.table("outlets").select("id", count="exact").eq("active", True).execute()
    total_active_outlets = active_res.count if active_res.count else 144
    ecosystem_threshold = int(total_active_outlets * 0.60)
    
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    clusters_res = supabase.table("clusters").select("id, representative_title, outlet_count").gte("created_at", cutoff_date).gte("outlet_count", ecosystem_threshold).execute()
    
    major_clusters = []
    for c in clusters_res.data or []:
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
    
    # Upsert to behavioral scores (primary key is outlet_slug)
    supabase.table("outlet_behavioral_scores").upsert(payload).execute()
    
    # Update main outlets table
    supabase.table("outlets").update({"independence_score": int(round(final_tii))}).eq("id", outlet_id).execute()

def main():
    outlets = supabase.table("outlets").select("id, name").eq("active", True).execute()
    for o in outlets.data:
        analyze_outlet(o['id'])
        time.sleep(3)

if __name__ == "__main__":
    main()
