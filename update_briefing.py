content = """import os
import re
import json
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from app.db import supabase
from openai import OpenAI

logger = logging.getLogger(__name__)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def select_daily_briefing_stories():
    lagos_now = datetime.now(timezone.utc) + timedelta(hours=1)
    today = lagos_now.date()

    existing = supabase.table("daily_briefings").select("id").eq("date", today.isoformat()).execute()
    if existing.data:
        return {"status": "already_selected", "date": today.isoformat()}

    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    
    clusters_res = supabase.table("clusters")\\
        .select("id, slug, representative_title, outlet_count, category, stories(image_url)")\\
        .gte("first_seen_at", since)\\
        .gte("outlet_count", 5)\\
        .order("outlet_count", desc=True)\\
        .limit(10)\\
        .execute()

    eligible = []
    for c in (clusters_res.data or []):
        has_image = any(s.get("image_url") for s in (c.get("stories") or []))
        if has_image:
            eligible.append(c)
        if len(eligible) == 5:
            break

    if len(eligible) < 3:
        logger.warning(f"[daily_briefing] Only {len(eligible)} eligible clusters found for {today}, skipping")
        return {"status": "insufficient_data", "date": today.isoformat(), "found": len(eligible)}

    rows = []
    for i, cluster in enumerate(eligible):
        rows.append({
            "date": today.isoformat(),
            "cluster_id": cluster["id"],
            "cluster_slug": cluster["slug"],
            "position": i + 1,
            "generation_status": "pending"
        })
    
    supabase.table("daily_briefings").insert(rows).execute()
    
    logger.info(f"[daily_briefing] Selected {len(rows)} stories for {today}")
    
    return {
        "status": "selected",
        "date": today.isoformat(),
        "count": len(rows),
        "stories": [
            {
                "position": i + 1, 
                "slug": c["slug"],
                "title": c["representative_title"],
                "outlet_count": c["outlet_count"]
            }
            for i, c in enumerate(eligible)
        ]
    }


def scrape_articles_for_cluster(cluster_id, cluster_slug):
    stories_res = supabase.table("stories")\\
        .select("id, url, title, summary, outlet_slug, outlets(name, credibility_tier)")\\
        .eq("cluster_id", cluster_id)\\
        .not_.is_("url", "null")\\
        .limit(20)\\
        .execute()

    articles = []
    full_count = 0
    fallback_count = 0
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    stories_data = stories_res.data or []
    total = len(stories_data)
    
    for s in stories_data:
        url = s.get("url")
        title = s.get("title")
        summary = s.get("summary") or ""
        outlet_name = s.get("outlets", {}).get("name") if s.get("outlets") else s.get("outlet_slug")
        outlet_tier = s.get("outlets", {}).get("credibility_tier") if s.get("outlets") else "unscored"
        
        text_content = ""
        scraped_full = False
        
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Try selectors in order
            selectors = [
                "article",
                ".article-body", ".article-content", ".post-content", ".entry-content", ".story-body", ".article__body",
                "main"
            ]
            
            for sel in selectors:
                el = soup.select_one(sel)
                if el:
                    # Strip tags and get text
                    extracted = el.get_text(separator=" ", strip=True)
                    if len(extracted) > 200:
                        text_content = extracted
                        break
            
            # Fallback 4: all p tags
            if len(text_content) <= 200:
                p_tags = soup.find_all("p")
                extracted = " ".join([p.get_text(strip=True) for p in p_tags])
                if len(extracted) > 200:
                    text_content = extracted
            
            if len(text_content) > 200:
                text_content = text_content[:3000]
                scraped_full = True
                full_count += 1
            else:
                raise ValueError("Could not extract meaningful text (>200 chars)")
                
        except Exception as e:
            logger.warning(f"[scraper] Failed to scrape {url}: {e}")
            text_content = summary
            fallback_count += 1
            scraped_full = False
            
        articles.append({
            "outlet_name": outlet_name,
            "outlet_tier": outlet_tier,
            "title": title,
            "text": text_content,
            "scraped_full": scraped_full,
            "url": url
        })
        
    logger.info(f"[scraper] {cluster_slug}: {full_count} full / {fallback_count} fallback of {total} articles")
    return articles


def generate_briefing_for_story(briefing_row):
    try:
        # STEP 1: Mark as generating
        supabase.table("daily_briefings")\\
            .update({
                "generation_status": "generating",
                "updated_at": datetime.now(timezone.utc).isoformat()
            })\\
            .eq("id", briefing_row["id"])\\
            .execute()

        # STEP 2: Fetch cluster metadata
        cluster_res = supabase.table("clusters")\\
            .select("id, slug, representative_title, outlet_count, category, first_seen_at, coverage_stats")\\
            .eq("id", briefing_row["cluster_id"])\\
            .execute()

        if not cluster_res.data:
            raise ValueError(f"Cluster not found: {briefing_row['cluster_id']}")

        cluster = cluster_res.data[0]

        # STEP 3: Scrape articles
        articles = scrape_articles_for_cluster(
            briefing_row["cluster_id"],
            briefing_row["cluster_slug"]
        )

        # Clean HTML from fallback summaries
        for a in articles:
            if not a["scraped_full"]:
                a["text"] = re.sub(r'<[^>]+>', '', a["text"]).strip()

        # Build article context string grouped by tier
        tier_groups = {}
        for a in articles:
            tier = a.get("outlet_tier") or "unscored"
            if tier not in tier_groups:
                tier_groups[tier] = []
            tier_groups[tier].append(a)

        article_context = ""
        tier_labels = {
            "adversarial": "ADVERSARIAL OUTLETS",
            "institutional": "INSTITUTIONAL OUTLETS", 
            "pro_establishment": "PRO-ESTABLISHMENT OUTLETS",
            "unscored": "OTHER OUTLETS"
        }
        for tier, label in tier_labels.items():
            if tier in tier_groups:
                article_context += f"\\n\\n{label}:\\n"
                for a in tier_groups[tier]:
                    article_context += (
                        f"\\n[{a['outlet_name']}]\\n"
                        f"{a['title']}\\n"
                        f"{a['text'][:500]}\\n"
                    )

        # STEP 4: AI Call 1 — Ground Summary + Common Ground
        PROMPT_CALL_1 = f\"\"\"You are an expert Nigerian media analyst writing for TraceNews, a media intelligence platform.

STORY: {cluster['representative_title']}
CATEGORY: {cluster['category']}
TOTAL SOURCES: {cluster['outlet_count']}

COVERAGE FROM NIGERIAN NEWS OUTLETS:
{article_context}

Generate a structured briefing in valid JSON. Return ONLY the JSON object, no markdown, no explanation.

{{
  "ground_summary": {{
    "whats_happening": "2-3 sentence factual paragraph. What is happening, who is involved, what has been decided or occurred. Stick to confirmed facts only.",
    "why_it_matters": "2-3 sentence paragraph explaining significance. Why does this matter to Nigerians? What are the broader implications?"
  }},
  "common_ground": [
    {{
      "label": "Short 2-4 word label",
      "text": "One sentence of what ALL outlets across tiers agree on, regardless of their editorial stance."
    }},
    {{
      "label": "Short 2-4 word label", 
      "text": "Second point of consensus"
    }},
    {{
      "label": "Short 2-4 word label",
      "text": "Third point of consensus"
    }}
  ],
  "location_context": {{
    "city": "Primary city where this story is happening (e.g. Abuja, Lagos, Ado-Ekiti). Empty string if not location-specific.",
    "country": "Nigeria (or other country if international story)",
    "note": "One short sentence of geographic/contextual note, e.g. 'State capital and venue of today's governorship election'"
  }}
}}\"\"\"

        response1 = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": PROMPT_CALL_1}
            ],
            max_tokens=1000,
            temperature=0.3
        )
        raw1 = response1.choices[0].message.content
        parsed1 = json.loads(
            raw1.replace("```json", "")
                .replace("```", "")
                .strip()
        )

        # STEP 5: AI Call 2 — Perspectives
        PROMPT_CALL_2 = f\"\"\"You are an expert Nigerian media analyst writing for TraceNews.

STORY: {cluster['representative_title']}

COVERAGE GROUPED BY EDITORIAL STANCE:
{article_context}

Analyze how different outlets are framing this story. Identify the TWO SUBSTANTIVE SIDES of the debate or tension in this story.

IMPORTANT: Do NOT name the sides "Pro-Establishment" or "Adversarial". Name them by WHAT THEY ACTUALLY ARGUE. 
Examples of good naming:
- "Security Advocates vs Civil Liberties Defenders"
- "Government Supporters vs Opposition Critics"  
- "Reform Optimists vs Fiscal Hawks"
- "Ekiti APC vs Opposition Challengers"

If there is no genuine two-sided debate (e.g. purely factual event with no controversy), name the sides as different PERSPECTIVES or EMPHASES instead (e.g. "National Security Lens vs Human Impact Lens").

Return ONLY valid JSON, no markdown:

{{
  "perspectives_title": "Side A Name vs Side B Name (max 8 words total, dramatic and specific)",
  "perspectives_sides": {{
    "side_a": "Side A name only (3-4 words)",
    "side_b": "Side B name only (3-4 words)"
  }},
  "perspectives_table": [
    {{
      "dimension": "2-4 word label for this dimension of debate",
      "side_a": "1-2 sentences: what side A says/emphasizes about this dimension",
      "side_b": "1-2 sentences: what side B says/emphasizes about this dimension"
    }},
    {{
      "dimension": "Second dimension",
      "side_a": "Side A position",
      "side_b": "Side B position"
    }},
    {{
      "dimension": "Third dimension",
      "side_a": "Side A position",
      "side_b": "Side B position"
    }}
  ]
}}\"\"\"

        response2 = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": PROMPT_CALL_2}
            ],
            max_tokens=1000,
            temperature=0.4
        )
        raw2 = response2.choices[0].message.content
        parsed2 = json.loads(
            raw2.replace("```json", "")
                .replace("```", "")
                .strip()
        )

        # STEP 6: AI Call 3 — Follow-up Questions
        PROMPT_CALL_3 = f\"\"\"You are writing follow-up questions for a Nigerian news briefing about:

{cluster['representative_title']}

Ground Summary: 
{parsed1.get('ground_summary', {{}}).get('whats_happening', '')}

Generate 4 follow-up questions a curious Nigerian reader would ask after reading the headline, with clear factual answers based on the coverage.

Return ONLY valid JSON, no markdown:

{{
  "followup_questions": [
    {{
      "question": "Specific question about this story",
      "answer": "2-3 sentence factual answer based on the coverage"
    }},
    {{
      "question": "Second question",
      "answer": "Answer"
    }},
    {{
      "question": "Third question", 
      "answer": "Answer"
    }},
    {{
      "question": "Fourth question",
      "answer": "Answer"
    }}
  ]
}}

Base answers ONLY on what the coverage actually says. Do not invent facts.\"\"\"

        response3 = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": f"{PROMPT_CALL_3}\\n\\nCOVERAGE:\\n{article_context[:2000]}"}
            ],
            max_tokens=800,
            temperature=0.3
        )
        raw3 = response3.choices[0].message.content
        parsed3 = json.loads(
            raw3.replace("```json", "")
                .replace("```", "")
                .strip()
        )

        # STEP 7: Save everything to DB
        supabase.table("daily_briefings")\\
            .update({
                "generation_status": "complete",
                "ground_summary": parsed1.get("ground_summary"),
                "common_ground": parsed1.get("common_ground"),
                "location_context": parsed1.get("location_context"),
                "perspectives_title": parsed2.get("perspectives_title"),
                "perspectives_sides": parsed2.get("perspectives_sides"),
                "perspectives_table": parsed2.get("perspectives_table"),
                "followup_questions": parsed3.get("followup_questions"),
                "updated_at": datetime.now(timezone.utc).isoformat()
            })\\
            .eq("id", briefing_row["id"])\\
            .execute()

        logger.info(f"[daily_briefing] Generated: {briefing_row['cluster_slug']}")
        return {"status": "complete", "slug": briefing_row["cluster_slug"]}

    except Exception as e:
        import traceback
        logger.error(
            f"[daily_briefing] Generation failed for {briefing_row.get('cluster_slug')}: {e}\\n{traceback.format_exc()}"
        )
        supabase.table("daily_briefings")\\
            .update({
                "generation_status": "failed",
                "error_log": str(e),
                "updated_at": datetime.now(timezone.utc).isoformat()
            })\\
            .eq("id", briefing_row["id"])\\
            .execute()
        return {"status": "failed", "error": str(e)}

if __name__ == "__main__":
    import json
    
    # Step 1: Try selection (will skip if already done today)
    sel_result = select_daily_briefing_stories()
    print("Selection:", json.dumps(sel_result, indent=2))
    
    # Step 2: Generate for position 1 ONLY
    # (test one story before running all 5)
    test_res = supabase.table("daily_briefings")\\
        .select("*")\\
        .eq("date", (datetime.now(timezone.utc) + timedelta(hours=1)).date().isoformat())\\
        .eq("position", 1)\\
        .execute()
    
    if test_res.data:
        row = test_res.data[0]
        if row["generation_status"] in ("pending", "failed"):
            print(f"\\nGenerating for: {row['cluster_slug']}")
            result = generate_briefing_for_story(row)
            print("Result:", json.dumps(result, indent=2))
            
            # Show what was generated
            check = supabase.table("daily_briefings")\\
                .select("generation_status, perspectives_title, ground_summary")\\
                .eq("id", row["id"])\\
                .execute()
            
            if check.data:
                d = check.data[0]
                print("\\nStatus:", d["generation_status"])
                print("Perspectives title:", d["perspectives_title"])
                print("Ground summary:", json.dumps(d["ground_summary"], indent=2))
        else:
            print(f"\\nAlready generated: {row['cluster_slug']} ({row['generation_status']})")
    else:
        print("No briefing rows found for today")
"""

with open("app/daily_briefing.py", "w") as f:
    f.write(content)

