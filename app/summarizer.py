import os
import json
import logging
from openai import OpenAI
from app.db import supabase
from app.storySummaryStrings import (
    SUMMARY_MODEL,
    SUMMARY_MAX_TOKENS,
    SUMMARY_TEMPERATURE,
    SUMMARY_SYSTEM_PROMPT,
    SUMMARY_USER_PROMPT,
    ADVERSE_CONTEXT_TERMS,
    PUBLIC_RECORD_ANCHORS,
    GATE_AUTO_PUBLISH,
    GATE_HUMAN_REVIEW,
    GATE_SUPPRESS_CLAIM,
    GATE_DEFAULT,
    ESCALATION_TERMS,
    FORBIDDEN_COVERAGE_TERMS
)

logger = logging.getLogger(__name__)
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def generate_cluster_summary(cluster_id: str) -> dict:
    # 1. Fetch stories
    res = supabase.table("stories").select("summary").eq("cluster_id", cluster_id).execute()
    stories = res.data or []
    
    # Filter out empty summaries
    valid_summaries = [s.get("summary") for s in stories if s.get("summary")]
    if not valid_summaries:
        logger.info(f"No valid summaries found for cluster {cluster_id}")
        return None
        
    articles_text = "\n\n---\n\n".join(valid_summaries)
    
    # 2. Generate
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
    
    import re
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
    
    if has_adverse:
        if has_anchor:
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
