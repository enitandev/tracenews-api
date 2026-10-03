"""
The Daily Briefing's fuller sections (counsel's ruling of 3 Oct 2026, item 6):
Who said what, What happens next, Background. Generated from the same source
text as the summary (no outlet names or tiers), then checked in code. Rules
and the prompt live in app/briefingStrings.py.
"""
import json
import logging
import re

from app import names
from app.briefingStrings import (
    BACKGROUND_MAX, EXTRAS_SYSTEM_PROMPT, EXTRAS_USER_PROMPT, NEXT_ATTRIBUTION_PATTERN,
    NEXT_MAX, NEXT_PREDICTION_TERMS, QUOTE_VERB, QUOTES_MAX,
)
from app.storySummaryStrings import CONDUCT_TERMS, PUBLIC_RECORD_ANCHORS, SUMMARY_MODEL, SUMMARY_TEMPERATURE

logger = logging.getLogger(__name__)

PARTY_HISTORY_TERMS = ("defected", "defection", "decamped", "former member", "joined the", "left the", "expelled")


def _norm(text):
    """Compare quotes on the words only: straight quotes, single spaces, lower case."""
    t = (text or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", t).strip().lower()


def _has(term, text):
    return re.search(r"(?<![\w-])" + re.escape(term) + r"(?![\w-])", text, re.IGNORECASE) is not None


def quoted_and_attributed(quote, speaker, articles_text):
    """Counsel's ruling of 3 Oct: a quote counts only if, in one source, the
    words sit inside quotation marks and the named speaker is credited near
    them (same passage). Finding the words alone is not enough: a reporter's
    sentence is not a quote."""
    q = _norm(quote)
    surname = _norm(speaker).split()[-1] if speaker.strip() else ""
    for block in re.split(r"\n\s*\n(?=Source \d+)", articles_text or ""):
        text = _norm(block)
        for m in re.finditer(r'"([^"]{3,})"', text):
            if q and q in m.group(1):
                window = text[max(0, m.start() - 250): m.end() + 250]
                if surname and re.search(r"\b" + re.escape(surname) + r"\b", window):
                    return True
    return False


def quote_line(q):
    """How a quote is shown: named speaker with role, the verb "said" only."""
    return f'{q["speaker"]}, {q["role"]}, {QUOTE_VERB}: "{q["quote"]}"'


def check_extras(raw, articles_text):
    """Keep only what passes counsel's rules. Returns the kept sections and a
    record of what was dropped and why (shown to the editor, never to readers)."""
    raw = raw if isinstance(raw, dict) else {}
    source = _norm(articles_text)
    source_numbers = set(re.findall(r"\d+", articles_text or ""))
    kept = {"quotes": [], "next": [], "background": []}
    dropped = []

    for q in (raw.get("quotes") or []):
        if not isinstance(q, dict):
            dropped.append("quote: not an object")
            continue
        speaker, role, quote = (str(q.get(k) or "").strip() for k in ("speaker", "role", "quote"))
        quote = quote.strip('"“” ')
        if not (speaker and role and quote):
            dropped.append(f"quote without speaker, role or words: {quote[:60]}")
        elif _norm(quote) not in source:
            dropped.append(f"quote not found verbatim in the sources: {quote[:60]}")
        elif not quoted_and_attributed(quote, speaker, articles_text):
            dropped.append(f"quote not inside quotation marks attributed to {speaker} in a source: {quote[:60]}")
        elif len(kept["quotes"]) >= QUOTES_MAX:
            dropped.append(f"quote over the limit of {QUOTES_MAX}")
        else:
            kept["quotes"].append({"speaker": speaker, "role": role, "quote": quote})

    for item in (raw.get("next") or []):
        item = str(item or "").strip()
        attributed = re.search(NEXT_ATTRIBUTION_PATTERN, item, re.IGNORECASE)
        numbers = re.findall(r"\d+", item)
        if not item:
            continue
        if not attributed:
            dropped.append(f"next step not attributed: {item[:60]}")
        elif any(_has(t, item) for t in NEXT_PREDICTION_TERMS) and not _has("said", item) and not _has("according to", item):
            dropped.append(f"next step reads as a prediction: {item[:60]}")
        elif any(n not in source_numbers for n in numbers):
            dropped.append(f"next step has a date or number not in the sources: {item[:60]}")
        elif len(kept["next"]) >= NEXT_MAX:
            dropped.append(f"next step over the limit of {NEXT_MAX}")
        else:
            kept["next"].append(item)

    for item in (raw.get("background") or []):
        item = str(item or "").strip()
        if not item:
            continue
        about_conduct = any(_has(t, item) for t in list(CONDUCT_TERMS) + list(PARTY_HISTORY_TERMS))
        named = names.person_names(item)
        public_record = any(_has(t, item) for t in PUBLIC_RECORD_ANCHORS) and _has("according to", item)
        if about_conduct and named and not public_record:
            dropped.append(f"background about a named person's conduct or party history without an attributed public record: {item[:60]}")
        elif len(kept["background"]) >= BACKGROUND_MAX:
            dropped.append(f"background over the limit of {BACKGROUND_MAX}")
        else:
            kept["background"].append(item)

    return kept, dropped


def section_texts(extras):
    """The sections as plain text, for the routing checks."""
    extras = extras or {}
    return ([quote_line(q) for q in extras.get("quotes") or []]
            + list(extras.get("next") or []) + list(extras.get("background") or []))


def generate_extras(articles_text):
    """One model call. Returns (kept sections, dropped notes); raises on failure."""
    from app.summarizer import openai_client
    response = openai_client.chat.completions.create(
        model=SUMMARY_MODEL,
        temperature=SUMMARY_TEMPERATURE,
        max_tokens=900,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": EXTRAS_SYSTEM_PROMPT},
            {"role": "user", "content": EXTRAS_USER_PROMPT.format(articles_text=articles_text)},
        ],
    )
    return check_extras(json.loads(response.choices[0].message.content), articles_text)
