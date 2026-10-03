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
    CONDUCT_TERMS,
    HARM_EVENT_TERMS,
    PUBLIC_RECORD_ANCHORS,
    SUMMARY_MAX_BULLETS,
    SUMMARY_MIN_BULLETS,
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

def harm_names_a_person(texts) -> bool:
    """A named person in the same sentence as a harm-event term: the person
    may be its subject or alleged cause, so a human reads it."""
    from app.names import person_names
    for text in texts:
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            low = sentence.lower()
            if any(re.search(r"\b" + re.escape(t) + r"\b", low) for t in HARM_EVENT_TERMS) and person_names(sentence):
                return True
    return False


def evaluate_summary(bullets, articles_text: str, title: str = None) -> dict:
    """
    Decide whether generated bullets may publish. This is the legal-risk
    routing for event summaries:

    - escalation: a criminal-process term (charged, convicted, ...) in the
      bullets that no source article used -> flagged
    - forbidden coverage language (outlet, coverage, downplayed, ...) -> flagged
    - fewer than SUMMARY_MIN_BULLETS or more than SUMMARY_MAX_BULLETS -> flagged
    - a CONDUCT term (alleged, fraud, arrested, ...) routes the gate:
        with a principal officeholder named -> senior_review
        else with a public-record anchor (court, filed, ...) -> review
        else -> suppress
    - a HARM_EVENT term (killed, died, injured, ...) with no CONDUCT term
      never suppresses (counsel, 3 Oct 2026): review if a named person is in
      the same sentence as the harm (its subject or alleged cause), else auto
      no adverse term -> auto

    Publishes only when the gate is auto AND nothing was flagged.
    A bullet that is not text is flagged, never coerced into text.

    title: the Briefing runs this over headline + body together (counsel's
    review of the 3 Oct samples, item 1b). The headline joins every check
    except the bullet count. Story pages pass no title.
    """
    if not isinstance(bullets, list):
        bullets = [str(bullets)]

    flags = []
    non_text = [b for b in bullets if not isinstance(b, str)]
    if non_text:
        flags.append(f"bullet_type: {len(non_text)} non-text")
    text_bullets = [b for b in bullets if isinstance(b, str)]

    combined_bullets_lower = " ".join(([title] if isinstance(title, str) else []) + text_bullets).lower()
    combined_summaries_lower = articles_text.lower()

    def mentions(term, text):
        return re.search(r'\b' + re.escape(term.lower()) + r'\b', text) is not None

    # a) Escalation check. A term counts as used by the sources if any form
    # of it is ("charges" / "charged", "confirming" / "confirmed").
    def used_by_sources(term):
        if " " in term:
            return mentions(term, combined_summaries_lower)
        stem = re.sub(r"(ing|ed|es|s|ion|ions|ment)$", "", term.lower())
        return re.search(r"\b" + re.escape(stem) + r"\w*", combined_summaries_lower) is not None

    for term in ESCALATION_TERMS:
        if mentions(term, combined_bullets_lower) and not used_by_sources(term):
            flags.append(f"escalation: {term}")

    # b) Coverage check
    for term in FORBIDDEN_COVERAGE_TERMS:
        if mentions(term, combined_bullets_lower):
            flags.append(f"forbidden_coverage: {term}")

    # c) Length check
    if len(bullets) < SUMMARY_MIN_BULLETS or len(bullets) > SUMMARY_MAX_BULLETS:
        flags.append(f"bullet_count: {len(bullets)}")

    # Gating
    has_conduct = any(mentions(t, combined_bullets_lower) for t in CONDUCT_TERMS)
    has_harm = any(mentions(t, combined_bullets_lower) for t in HARM_EVENT_TERMS)
    has_anchor = any(mentions(t, combined_bullets_lower) for t in PUBLIC_RECORD_ANCHORS)
    has_principal = any(mentions(t, combined_bullets_lower) for t in PRINCIPAL_OFFICEHOLDERS)

    if has_conduct:
        if has_principal:
            gate = GATE_SENIOR_REVIEW
        elif has_anchor:
            gate = GATE_HUMAN_REVIEW
        else:
            gate = GATE_SUPPRESS_CLAIM
    elif has_harm:
        gate = GATE_HUMAN_REVIEW if harm_names_a_person(([title] if isinstance(title, str) else []) + text_bullets) else GATE_AUTO_PUBLISH
    else:
        gate = GATE_AUTO_PUBLISH

    return {
        "bullets": bullets,
        "gate": gate,
        "flags": flags,
        "published": gate == GATE_AUTO_PUBLISH and len(flags) == 0,
    }


def serving_summary(rows):
    """The summary row to serve, from a cluster's rows newest first.

    A correction marks the summary it replaces as superseded; while the newest
    row is superseded nothing is served. Otherwise the newest row that passed
    the checks is served: a later re-run that was flagged, gated or failed does
    not take down a summary that already passed."""
    rows = rows or []
    if not rows:
        return None
    if rows[0].get("superseded") is True:
        return rows[0]
    for row in rows:
        if row.get("superseded") is True:
            return rows[0]
        if row.get("published") and not row.get("flags") and not is_generation_failure(row):
            return row
    return rows[0]


GENERATION_FAILED_FLAG = "generation_failed"
SUMMARY_GENERATION_TRIES = 3
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


def format_articles_text(stories) -> str:
    """The model receives no outlet name, identifier or tier (counsel, 3 Oct 2026, B2)."""
    return "\n\n".join(f"Source {i}\nHeadline: {s.get('title')}\nSummary: {s.get('summary')}" for i, s in enumerate(stories, 1))


def cluster_articles_text(cluster_id: str) -> str:
    stories = supabase.table("stories").select("title, summary").eq("cluster_id", cluster_id).execute().data or []
    return format_articles_text(stories)


def generate_cluster_summary(cluster_id: str) -> dict:
    """Generate and store an event summary for a given cluster."""
    stories = supabase.table("stories").select("title, summary").eq("cluster_id", cluster_id).execute().data or []
    if len(stories) < 2:
        return None
    articles_text = format_articles_text(stories)
    user_prompt = SUMMARY_USER_PROMPT.format(articles_text=articles_text)
    
    # A summary flagged by the checks is drawn again with the same prompt, up
    # to SUMMARY_GENERATION_TRIES times; the rules are never relaxed. The
    # last draw is stored either way, so the record shows what was produced.
    for attempt in range(1, SUMMARY_GENERATION_TRIES + 1):
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
            bullets = json.loads(response.choices[0].message.content).get("bullets", [])
        except Exception as e:
            logger.exception(f"Failed to generate summary for {cluster_id}")
            record_generation_failure(cluster_id, e)
            return None
        evaluation = evaluate_summary(bullets, articles_text)
        if not evaluation["flags"]:
            break
        logger.info(f"[summary] {cluster_id} attempt {attempt} flagged: {evaluation['flags']}")

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
