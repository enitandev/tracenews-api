import json
import logging
import os
import re
from openai import OpenAI
from app.db import supabase
from app.storySummaryStrings import (
    SUMMARY_MODEL,
    SUMMARY_TEMPERATURE,
    SUMMARY_MAX_TOKENS,
    SUMMARY_SYSTEM_PROMPT,
    SUMMARY_USER_PROMPT,
    ADVERSE_CONTEXT_TERMS,
    PUBLIC_RECORD_ANCHORS,
    GATE_AUTO_PUBLISH,
    GATE_HUMAN_REVIEW,
    GATE_SUPPRESS_CLAIM,
    GATE_SENIOR_REVIEW,
    GATE_DEFAULT,
    ESCALATION_TERMS,
    FORBIDDEN_COVERAGE_TERMS,
    PRINCIPAL_OFFICEHOLDERS
)

logger = logging.getLogger("summarizer")
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def generate_cluster_summary(cluster_id: str) -> dict:
    """Generate and store an event summary for a given cluster."""
    stories_res = supabase.table("stories").select("title, summary, outlet_id").eq("cluster_id", cluster_id).execute()
    stories = stories_res.data
    
    if len(stories) < 2:
        return None
        
    articles_text = "\n\n".join([f"Source: {s.get('outlet_id')}\nHeadline: {s.get('title')}\nSummary: {s.get('summary')}" for s in stories])
    user_prompt = SUMMARY_USER_PROMPT.format(articles_text=articles_text)
    
    try:
        response = openai_client.chat.completions.create(
            model=SUMMARY_MODEL,
            temperature=SUMMARY_TEMPERATURE,
            max_tokens=SUMMARY_MAX_TOKENS,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ]
        )
        content_str = response.choices[0].message.content
        output = json.loads(content_str)
        bullets = output.get("bullets", [])
    except Exception as e:
        logger.error(f"Failed to generate summary for {cluster_id}: {e}")
        return None

    if not isinstance(bullets, list):
        bullets = [str(bullets)]

    combined_bullets_lower = " ".join(bullets).lower()
    combined_summaries_lower = articles_text.lower()
    
    # 3. Eval Check
    flags = []
    
    # a) Escalation check
    for term in ESCALATION_TERMS:
        if re.search(r'\b' + re.escape(term.lower()) + r'\b', combined_bullets_lower) and not re.search(r'\b' + re.escape(term.lower()) + r'\b', combined_summaries_lower):
            flags.append(f"escalation: {term}")
            
    # b) Coverage check
    for term in FORBIDDEN_COVERAGE_TERMS:
        if re.search(r'\b' + re.escape(term.lower()) + r'\b', combined_bullets_lower):
            flags.append(f"forbidden_coverage: {term}")
            
    # c) Length check
    if len(bullets) < 2 or len(bullets) > 5:
        flags.append(f"bullet_count: {len(bullets)}")
        
    # 4. Gating Check
    gate = GATE_DEFAULT
    has_adverse = any(re.search(r'\b' + re.escape(t.lower()) + r'\b', combined_bullets_lower) for t in ADVERSE_CONTEXT_TERMS)
    has_anchor = any(re.search(r'\b' + re.escape(t.lower()) + r'\b', combined_bullets_lower) for t in PUBLIC_RECORD_ANCHORS)
    has_principal = any(re.search(r'\b' + re.escape(t.lower()) + r'\b', combined_bullets_lower) for t in PRINCIPAL_OFFICEHOLDERS)
    
    if has_adverse:
        if has_principal:
            gate = GATE_SENIOR_REVIEW
        elif has_anchor:
            gate = GATE_HUMAN_REVIEW
        else:
            gate = GATE_SUPPRESS_CLAIM
    else:
        gate = GATE_AUTO_PUBLISH

    # 5. Store
    is_published = (gate == GATE_AUTO_PUBLISH and len(flags) == 0)
    
    insert_data = {
        "cluster_id": cluster_id,
        "bullets": bullets,
        "gate": gate,
        "published": is_published,
        "flags": flags if flags else None,
        "model": SUMMARY_MODEL
    }
    
    try:
        supabase.table("cluster_summaries").insert(insert_data).execute()
        return insert_data
    except Exception as e:
        logger.error(f"Failed to store cluster summary for {cluster_id}: {e}")
        return None
