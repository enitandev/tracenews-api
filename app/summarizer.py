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
    ESCALATION_TERMS,
    FORBIDDEN_COVERAGE_TERMS,
    PRINCIPAL_OFFICEHOLDERS
)

logger = logging.getLogger("summarizer")
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def evaluate_summary(bullets, articles_text: str) -> dict:
    """
    Decide whether generated bullets may publish. This is the legal-risk
    routing for event summaries:

    - escalation: a criminal-process term (charged, convicted, ...) in the
      bullets that no source article used -> flagged
    - forbidden coverage language (outlet, coverage, downplayed, ...) -> flagged
    - fewer than 2 or more than 5 bullets -> flagged
    - an adverse-context term (alleged, fraud, ...) routes the gate:
        with a principal officeholder named -> senior_review
        else with a public-record anchor (court, filed, ...) -> review
        else -> suppress
      no adverse term -> auto

    Publishes only when the gate is auto AND nothing was flagged.
    A bullet that is not text is flagged, never coerced into text.
    """
    if not isinstance(bullets, list):
        bullets = [str(bullets)]

    flags = []
    non_text = [b for b in bullets if not isinstance(b, str)]
    if non_text:
        flags.append(f"bullet_type: {len(non_text)} non-text")
    text_bullets = [b for b in bullets if isinstance(b, str)]

    combined_bullets_lower = " ".join(text_bullets).lower()
    combined_summaries_lower = articles_text.lower()

    def mentions(term, text):
        return re.search(r'\b' + re.escape(term.lower()) + r'\b', text) is not None

    # a) Escalation check
    for term in ESCALATION_TERMS:
        if mentions(term, combined_bullets_lower) and not mentions(term, combined_summaries_lower):
            flags.append(f"escalation: {term}")

    # b) Coverage check
    for term in FORBIDDEN_COVERAGE_TERMS:
        if mentions(term, combined_bullets_lower):
            flags.append(f"forbidden_coverage: {term}")

    # c) Length check
    if len(bullets) < 2 or len(bullets) > 5:
        flags.append(f"bullet_count: {len(bullets)}")

    # Gating
    has_adverse = any(mentions(t, combined_bullets_lower) for t in ADVERSE_CONTEXT_TERMS)
    has_anchor = any(mentions(t, combined_bullets_lower) for t in PUBLIC_RECORD_ANCHORS)
    has_principal = any(mentions(t, combined_bullets_lower) for t in PRINCIPAL_OFFICEHOLDERS)

    if has_adverse:
        if has_principal:
            gate = GATE_SENIOR_REVIEW
        elif has_anchor:
            gate = GATE_HUMAN_REVIEW
        else:
            gate = GATE_SUPPRESS_CLAIM
    else:
        gate = GATE_AUTO_PUBLISH

    return {
        "bullets": bullets,
        "gate": gate,
        "flags": flags,
        "published": gate == GATE_AUTO_PUBLISH and len(flags) == 0,
    }


GENERATION_FAILED_FLAG = "generation_failed"
MAX_GENERATION_ATTEMPTS = 3


def record_generation_failure(cluster_id: str, error: Exception) -> None:
    """
    Store a failed attempt as an unpublished, bullet-less row so the worker
    can count attempts and stop re-calling the paid model after
    MAX_GENERATION_ATTEMPTS (see app.worker.clusters_needing_summary).
    """
    try:
        supabase.table("cluster_summaries").insert({
            "cluster_id": cluster_id,
            "bullets": [],
            "gate": GATE_HUMAN_REVIEW,
            "published": False,
            "flags": [f"{GENERATION_FAILED_FLAG}: {type(error).__name__}"],
            "model": SUMMARY_MODEL,
        }).execute()
    except Exception:
        logger.exception(f"Failed to record summary generation failure for {cluster_id}")


def is_generation_failure(summary_row: dict) -> bool:
    return any(str(f).startswith(GENERATION_FAILED_FLAG) for f in (summary_row.get("flags") or []))


def generate_cluster_summary(cluster_id: str) -> dict:
    """Generate and store an event summary for a given cluster."""
    stories_res = supabase.table("stories").select("title, summary").eq("cluster_id", cluster_id).execute()
    stories = stories_res.data
    
    if len(stories) < 2:
        return None
        
    # The model receives no outlet name, identifier or tier (counsel, 3 Oct 2026, B2).
    articles_text = "\n\n".join([f"Source {i}\nHeadline: {s.get('title')}\nSummary: {s.get('summary')}" for i, s in enumerate(stories, 1)])
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
        logger.exception(f"Failed to generate summary for {cluster_id}")
        record_generation_failure(cluster_id, e)
        return None

    evaluation = evaluate_summary(bullets, articles_text)
    bullets = evaluation["bullets"]
    gate = evaluation["gate"]
    flags = evaluation["flags"]
    is_published = evaluation["published"]

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
