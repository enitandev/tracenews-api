"""
Builds and serves the rebuilt Daily Briefing (counsel, 3 Oct 2026, section B,
amended by counsel's review of the 3 Oct samples). Rules and strings live in
app/briefingStrings.py.

An edition is one row per selected story in briefing_editions. Rows are built
whether or not the Briefing is public, so staff can review them. Each item is
routed (assess_item) when it is read, from its current text: the cleaned
source headline and the cleared summary, or an editor's rewrite of either.
"""
import logging
import re
import time as _time
from datetime import datetime, time, timedelta, timezone

from app.briefingStrings import (
    COMMENTARY_PHRASES, COMMENTARY_STATEMENT_PATTERN, COURT_TERMS, EDITION_CUTOFF_HOUR_LAGOS,
    EXAM_CONTEXT_TERMS, FORBIDDEN_TOKENS, HEADLINE_ATTRIBUTION_PATTERN, HEADLINE_BODY_TERMS,
    HEADLINE_CASUALTY_TERMS, HEADLINE_PREFIXES, HEADLINE_QUANTITY_WORDS, HEADLINE_TRAILING_PHRASES,
    LANE_AUTO, LANE_LEFT_OUT, LANE_REVIEW, LANE_SENIOR_REVIEW, LANES_NEEDING_EDITOR, MAX_STORIES,
    MIN_DISTINCT_OUTLETS, PARTY_NAMES, POLITICAL_ATTACK_TERMS, POLITICAL_CONTEST_TERMS,
    POLITICAL_ENDORSE_TERMS, POLITICAL_HEALTH_TERMS, POLITICAL_OFFICES, POLITICAL_REVIEW_LANE,
    REPORTED_PHRASES, WINDOW_HOURS,
)
from app import names
from app.db import supabase
from app.storySummaryStrings import ADVERSE_CONTEXT_TERMS, GATE_SUPPRESS_CLAIM
from app.summarizer import cluster_articles_text, evaluate_summary, is_generation_failure
from app.tier_utils import card_distribution, count_outlet_tiers, get_distinct_scored_count

logger = logging.getLogger(__name__)
LAGOS = timezone(timedelta(hours=1))
PROTECTED_STATUSES = ("pending_review", "excluded")   # held, private


def lagos_today():
    return datetime.now(LAGOS).date()


def edition_window(day):
    end = datetime.combine(day, time(EDITION_CUTOFF_HOUR_LAGOS, 0), LAGOS)
    return end - timedelta(hours=WINDOW_HOURS), end


# ═══ SELECTION ═══════════════════════════════════════════════════════════════

def select_clusters(clusters):
    """Widest coverage first: distinct outlets, then most recent. Never by tier imbalance."""
    eligible = []
    for c in clusters:
        distinct = get_distinct_scored_count(c.get("coverage_stats"))
        if distinct is None or distinct < MIN_DISTINCT_OUTLETS:
            continue
        if not any(s.get("image_url") for s in (c.get("stories") or [])):
            continue
        eligible.append((distinct, c.get("first_seen_at") or "", c))
    eligible.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [c for _, _, c in eligible[:MAX_STORIES]]


CANDIDATE_POOL = 500
IMAGE_LOOKUP_CHUNK = 100


def candidate_clusters(start, end):
    """Stories first seen in [start, end) with enough rows to qualify, each with
    the image URLs of its articles under "stories" (the shape select_clusters
    reads). Two plain queries: embedding stories in the cluster query times out
    on wider date ranges."""
    clusters = supabase.table("clusters").select(
        "id, slug, representative_title, category, first_seen_at, coverage_stats"
    ).gte("first_seen_at", start.isoformat()).lt("first_seen_at", end.isoformat()) \
        .gte("outlet_count", MIN_DISTINCT_OUTLETS) \
        .order("first_seen_at", desc=True).limit(CANDIDATE_POOL).execute().data or []
    images = {}
    ids = [c["id"] for c in clusters]
    for i in range(0, len(ids), IMAGE_LOOKUP_CHUNK):
        rows = supabase.table("stories").select("cluster_id, image_url") \
            .in_("cluster_id", ids[i:i + IMAGE_LOOKUP_CHUNK]).not_.is_("image_url", "null").execute().data or []
        for r in rows:
            images.setdefault(r["cluster_id"], []).append({"image_url": r["image_url"]})
    for c in clusters:
        c["stories"] = images.get(c["id"], [])
    return clusters


# ═══ TEXT CHECKS ═════════════════════════════════════════════════════════════

def _has(term, text, case_sensitive=False):
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.search(r"(?<![\w-])" + re.escape(term) + r"(?![\w-])", text, flags) is not None


def has_forbidden_token(texts):
    joined = " ".join(t for t in texts if isinstance(t, str))
    return next((tok for tok in FORBIDDEN_TOKENS if _has(tok, joined)), None)


_SEP = r"\s*[:\-–—|!]+\s*"


def clean_headline(title):
    """Source headline without prefix words or trailing virality phrases (item 1a)."""
    t = (title or "").strip()
    changed = True
    while changed:
        changed = False
        for p in HEADLINE_PREFIXES:
            m = re.match(r"^\W*" + re.escape(p) + _SEP, t, re.IGNORECASE)
            if m:
                t, changed = t[m.end():].strip(), True
        for p in HEADLINE_TRAILING_PHRASES:
            m = re.search(r"(?:\s*[:\-–—|!,]+\s*|\s+)" + re.escape(p) + r"\W*$", t, re.IGNORECASE)
            if m:
                t, changed = t[:m.start()].strip(), True
    return t


def headline_body_conflict(title, bullets):
    """A headline allegation/escalation term the body lacks (item 1c)."""
    body = " ".join(b for b in bullets if isinstance(b, str))
    for group in HEADLINE_BODY_TERMS:
        hit = next((t for t in group if _has(t, title)), None)
        if hit and not any(_has(t, body) for t in group):
            return hit
    return None


_registry = {"at": 0, "rows": []}
REGISTRY_TTL_SECONDS = 600


def load_registry():
    """Politician registry names and status, cached for ten minutes."""
    if _time.time() - _registry["at"] < REGISTRY_TTL_SECONDS and _registry["rows"]:
        return _registry["rows"]
    rows, start = [], 0
    while True:
        page = supabase.table("politicians").select("full_name, common_name, publication_status") \
            .range(start, start + 999).execute().data or []
        rows += page
        if len(page) < 1000:
            break
        start += 1000
    _registry.update(at=_time.time(), rows=rows)
    return rows


def registry_matches(text, registry):
    out = []
    for r in registry:
        names = {n.strip() for n in (r.get("full_name"), r.get("common_name")) if n and len(n.strip()) > 3}
        if any(_has(n, text) for n in names):
            out.append(r)
    return out


def parties_in(text):
    return [p for p in PARTY_NAMES if _has(p, text, case_sensitive=p.isupper())]


def offices_in(text):
    return [o for o in POLITICAL_OFFICES if _has(o, text)]


# Capitalised runs; an initial such as "A." stays inside the run ("Peter A. Okebukola").
_IGNORE = names.IGNORE
_ORG = names.ORG
_name_runs = names.name_runs
_is_name_word = names.is_name_word


def _registry_words(registry):
    """First and last names from the registry (not middle words), so a
    one-name reference to a registry person is recognised."""
    words = set()
    for r in registry:
        for n in (r.get("full_name"), r.get("common_name")):
            parts = [w for w in (n or "").split() if len(w) > 2 and _is_name_word(w)]
            if parts:
                words |= {parts[0], parts[-1]}
    return words


def surname_issues(title, bullets, registry):
    """Names of people used alone with no earlier full name containing them
    (item 3i). Body in order; a headline name must appear in full in the body."""
    body = " ".join(b for b in bullets if isinstance(b, str))
    runs = _name_runs(body)
    known = _registry_words(registry)
    known |= {ws[-1] for _, ws in runs if 2 <= len(ws) <= 4 and ws[-1] not in _ORG}
    introduced, issues = set(), []
    for _, words in runs:
        if len(words) >= 2:
            introduced |= set(words)
        elif words[0] in known and words[0] not in introduced and words[0] not in issues:
            issues.append(words[0])
    for _, words in _name_runs(title or ""):
        if len(words) == 1 and words[0] in known and words[0] not in introduced and words[0] not in issues:
            issues.append(words[0])
    return issues


def names_a_person_or_party(text, registry):
    if registry_matches(text, registry) or parties_in(text):
        return True
    return any(len(ws) >= 2 and ws[-1] not in _ORG for _, ws in _name_runs(text))


def commentary_in(bullets):
    text = " ".join(b for b in bullets if isinstance(b, str))
    found = [p for p in COMMENTARY_PHRASES if _has(p, text)]
    found += [m.group(0) for m in re.finditer(COMMENTARY_STATEMENT_PATTERN, text, re.IGNORECASE)]
    return found


_GATE_ORDER = {LANE_AUTO: 0, LANE_REVIEW: 1, LANE_SENIOR_REVIEW: 2, GATE_SUPPRESS_CLAIM: 3}


def political_trigger(full, matches):
    """Counsel's ruling of 3 Oct, item 2: a political figure or party together
    with a trigger. Returns a reason, or None for a routine item."""
    people = [m.get("common_name") or m.get("full_name") for m in matches]
    parties = parties_in(full)
    offices = offices_in(full)
    if not (people or parties or offices):
        return None
    exam = any(_has(t, full, case_sensitive=t.isupper()) for t in EXAM_CONTEXT_TERMS)
    found = [t for t in POLITICAL_CONTEST_TERMS
             if _has(t, full) and not (exam and t in ("candidate", "candidates"))]
    found += [t for t in POLITICAL_ENDORSE_TERMS if _has(t, full)]
    party_count = len({p for p in parties if p.isupper()}) or (1 if parties else 0)
    if len(set(people)) + party_count >= 2:
        found += [t for t in POLITICAL_ATTACK_TERMS if _has(t, full)]
    if people or any(_has(o, full) for o in ("president", "vice president", "governor", "senate president", "speaker")):
        found += [t for t in POLITICAL_HEALTH_TERMS if _has(t, full)]
    if not found:
        return None
    actors = list(dict.fromkeys(people + parties + offices))
    return "political review lane: " + ", ".join(actors) + " — " + ", ".join(dict.fromkeys(found))


def headline_issues(title, body):
    """Counsel's ruling of 3 Oct, item 3: headline numbers or quantity words
    the body does not support, and unattributed casualty claims."""
    issues = []
    num = re.compile(r"\d+(?:[.,]\d+)*")
    body_nums = {n.replace(",", "") for n in num.findall(body)}
    missing = [n for n in num.findall(title) if n.replace(",", "") not in body_nums]
    if missing:
        issues.append("headline number not in body: " + ", ".join(missing))
    words = [w for w in HEADLINE_QUANTITY_WORDS if _has(w, title) and not _has(w, body)]
    if words:
        issues.append("headline quantity word not in body: " + ", ".join(words))
    if any(_has(t, title) for t in HEADLINE_CASUALTY_TERMS) and not re.search(HEADLINE_ATTRIBUTION_PATTERN, title, re.IGNORECASE):
        issues.append("unattributed casualty claim in headline")
    return issues


def assess_item(raw_title, bullets, articles_text, registry, extra_texts=()):
    """Route one item from its current text (headline, What happened bullets,
    and the fuller sections as extra_texts). Returns the cleaned title, the
    lane (auto / review / senior_review / left_out) and every reason."""
    bullets = bullets if isinstance(bullets, list) else [bullets]
    title = clean_headline(raw_title)
    text_bullets = [b for b in bullets if isinstance(b, str)]
    extras = [t for t in extra_texts if isinstance(t, str) and t.strip()]
    body_parts = text_bullets + extras
    body = " ".join(body_parts)
    full = " ".join([title] + body_parts)

    def left_out(reason):
        return {"title": title, "lane": LANE_LEFT_OUT, "reasons": [reason]}

    if not title:
        return left_out("headline empty after cleaning")
    token = has_forbidden_token([title] + body_parts)
    if token:
        return left_out(f"forbidden word: {token}")
    conflict = headline_body_conflict(title, body_parts)
    if conflict:
        return left_out(f"headline term not in body: {conflict}")
    ev = evaluate_summary(bullets, articles_text, title=title)
    flags, gate = list(ev["flags"]), ev["gate"]
    if extras:
        # Adverse quotes and the other sections follow the same gate.
        ev2 = evaluate_summary(extras, articles_text)
        flags += [f for f in ev2["flags"] if not f.startswith("bullet_count")]
        gate = max(gate, ev2["gate"], key=_GATE_ORDER.get)
    if flags:
        return left_out("cleared check flagged: " + "; ".join(flags))
    if gate == GATE_SUPPRESS_CLAIM:
        return left_out("cleared gate: suppress (adverse conduct claim with no public-record anchor)")

    lane, reasons = gate, []
    if lane != LANE_AUTO:
        reasons.append(f"cleared gate: {lane}")
    matches = registry_matches(full, registry)
    if POLITICAL_REVIEW_LANE:
        political = political_trigger(full, matches)
        if political:
            reasons.append(political)
        if any(_has(t, full) for t in COURT_TERMS) and (matches or names.person_names(full) or names.organisation_names(full)):
            reasons.append("court or adjudication item naming a person or company")
    reasons += headline_issues(title, body)
    surnames = surname_issues(title, body_parts, registry)
    if surnames:
        reasons.append("named by one name only: " + ", ".join(surnames))
    reported = [p for p in REPORTED_PHRASES if _has(p, full)]
    if reported and names_a_person_or_party(full, registry):
        reasons.append("reported speech without origin: " + ", ".join(reported))
    commentary = commentary_in(body_parts)
    if commentary:
        reasons.append("commentary: " + ", ".join(commentary))
    if any(_has(t, full) for t in ADVERSE_CONTEXT_TERMS):
        protected = [m.get("common_name") or m.get("full_name") for m in matches
                     if m.get("publication_status") in PROTECTED_STATUSES]
        if protected:
            reasons.append("adverse item naming a held or private person: " + ", ".join(protected))
    if lane == LANE_AUTO and reasons:
        lane = LANE_REVIEW
    return {"title": title, "lane": lane, "reasons": reasons}


# ═══ SUMMARIES AND COUNTS ════════════════════════════════════════════════════

def summary_usable(summary):
    """A cleared summary exists that may be considered at all."""
    if not summary or summary.get("superseded") or is_generation_failure(summary):
        return False
    if summary.get("flags"):
        return False
    return summary.get("gate") in (LANE_AUTO,) + LANES_NEEDING_EDITOR


def latest_summary(cluster_id):
    """The summary the story page serves (app.summarizer.serving_summary): the
    newest one that passed, unless a correction superseded the newest."""
    from app.summarizer import serving_summary
    res = supabase.table("cluster_summaries").select("*").eq("cluster_id", cluster_id) \
        .order("generated_at", desc=True).limit(20).execute()
    return serving_summary(res.data or [])


def coverage_counts(cluster_id):
    """Distinct outlets per tier for the story, counted now."""
    from app.coverage import get_outlets_cache
    outlets_map, _ = get_outlets_cache()
    stories = supabase.table("stories").select("outlet_id").eq("cluster_id", cluster_id).execute().data or []
    outlets = [outlets_map[s["outlet_id"]] for s in stories if s.get("outlet_id") in outlets_map]
    return card_distribution(count_outlet_tiers(outlets))


def named_people(cluster_id):
    """Registry people tagged in the source articles. Reviewer-only (item 7)."""
    stories = supabase.table("stories").select("id").eq("cluster_id", cluster_id).execute().data or []
    ids = [s["id"] for s in stories][:100]
    if not ids:
        return []
    ents = supabase.table("story_entities").select("politician_id").in_("story_id", ids) \
        .eq("entity_type", "politician").execute().data or []
    pids = sorted({e["politician_id"] for e in ents if e.get("politician_id")})
    if not pids:
        return []
    rows = supabase.table("politicians").select("common_name").in_("id", pids).execute().data or []
    return sorted(r["common_name"] for r in rows if r.get("common_name"))


def source_articles(cluster_id):
    """The story's source articles, for the editor to check and rewrite against. Reviewer-only."""
    return supabase.table("stories").select("title, summary, url, published_at") \
        .eq("cluster_id", cluster_id).order("published_at").limit(40).execute().data or []


# ═══ EDITIONS ════════════════════════════════════════════════════════════════

def make_extras(cluster_id):
    """Generate and check the fuller sections for one story. A failure is
    logged and recorded on the row; the item still runs with What happened."""
    from app.briefing_extras import generate_extras
    try:
        kept, dropped = generate_extras(cluster_articles_text(cluster_id))
        return {"extras": kept, "extras_dropped": dropped, "extras_error": None}
    except Exception as e:
        logger.exception(f"[briefing] fuller sections failed for {cluster_id}")
        return {"extras": None, "extras_dropped": None, "extras_error": f"{type(e).__name__}: {e}"[:300]}


def build_edition(day=None, sample=False, with_extras=True):
    """Select a day's stories and record them. Idempotent per day.
    sample=True builds a staff-only sample edition for counsel.
    with_extras generates the fuller sections (one model call per story)."""
    day = day or lagos_today()
    if supabase.table("briefing_editions").select("id").eq("date", day.isoformat()).limit(1).execute().data:
        # One edition per date, real or sample (unique date + story).
        return {"status": "already_built", "date": day.isoformat()}

    start, end = edition_window(day)
    rows, skipped = [], {}
    for cluster in select_clusters(candidate_clusters(start, end)):
        summary = latest_summary(cluster["id"])
        if not summary_usable(summary):
            skipped[cluster["slug"]] = "no usable summary (missing, flagged, suppressed or failed)"
            continue
        row = {
            "date": day.isoformat(),
            "position": len(rows) + 1,
            "cluster_id": cluster["id"],
            "summary_id": str(summary["id"]),
            "gate": summary.get("gate"),
            "coverage_counts": coverage_counts(cluster["id"]),
            "counts_as_of": datetime.now(timezone.utc).isoformat(),
            "is_sample": sample,
        }
        if with_extras:
            row.update(make_extras(cluster["id"]))
            row["extras_generated_at"] = datetime.now(timezone.utc).isoformat()
        rows.append(row)
    if rows:
        supabase.table("briefing_editions").insert(rows).execute()
    for slug, why in skipped.items():
        logger.info(f"[briefing] left out {slug}: {why}")
    return {"status": "built", "date": day.isoformat(), "items": len(rows), "left_out": len(skipped)}


def current_text(row, cluster, summary):
    edited = row.get("edited_bullets")
    return (row.get("edited_title") or cluster.get("representative_title") or "",
            edited if edited else (summary or {}).get("bullets") or [])


def current_extras(row):
    return row.get("edited_extras") or row.get("extras") or {"quotes": [], "next": [], "background": []}


def reader_sections(extras):
    from app.briefing_extras import quote_line
    return {
        "quotes": [{**q, "line": quote_line(q)} for q in extras.get("quotes") or []],
        "next": list(extras.get("next") or []),
        "background": list(extras.get("background") or []),
    }


def first_approval_valid(row, summary):
    """An approval covers the exact text approved (summary id + edit time)."""
    if not row.get("approved_by"):
        return False
    if str(row.get("approved_summary_id") or "") != str((summary or {}).get("id") or ""):
        return False
    return (row.get("approved_edit_at") or None) == (row.get("edited_at") or None)


def approval_valid(row, summary, lane=None):
    """Review needs one named editor. Senior review needs a second, different
    approver of the same text (counsel's ruling, 3 Oct, item 5)."""
    if not first_approval_valid(row, summary):
        return False
    if lane == LANE_SENIOR_REVIEW:
        return bool(row.get("second_approved_by")) and row.get("second_approved_by") != row.get("approved_by")
    return True


def route_row(row, cluster, summary, registry):
    raw_title, bullets = current_text(row, cluster, summary)
    extras = current_extras(row)
    if row.get("left_out_by"):
        a = {"title": raw_title, "lane": LANE_LEFT_OUT,
             "reasons": [f"left out by {row['left_out_by']}: {row.get('left_out_reason') or ''}".strip()]}
    elif not summary_usable(summary):
        a = {"title": raw_title, "lane": LANE_LEFT_OUT, "reasons": ["no usable cleared summary"]}
    else:
        from app.briefing_extras import section_texts
        a = assess_item(raw_title, bullets, cluster_articles_text(row["cluster_id"]), registry, section_texts(extras))
    return a, bullets, extras


def edition_items(day, publishable_only=True):
    """Items for a day. Readers get publishable items of the real edition only;
    staff get every item, with routing, reasons and reviewer-only fields."""
    q = supabase.table("briefing_editions").select("*").eq("date", day.isoformat())
    if publishable_only:
        q = q.eq("is_sample", False)
    rows = q.order("position").execute().data or []
    registry = load_registry() if rows else []
    items = []
    for row in rows:
        # The current summary is used: if a correction replaced the one the
        # edition was built with, the replacement is routed afresh.
        summary = latest_summary(row["cluster_id"])
        cluster = (supabase.table("clusters").select("slug, representative_title, category")
                   .eq("id", row["cluster_id"]).limit(1).execute().data or [{}])[0]
        a, bullets, extras = route_row(row, cluster, summary, registry)
        approved = approval_valid(row, summary, a["lane"])
        publishable = a["lane"] == LANE_AUTO or (a["lane"] in LANES_NEEDING_EDITOR and approved)
        if publishable_only and not publishable:
            continue
        image = (supabase.table("stories").select("image_url").eq("cluster_id", row["cluster_id"])
                 .not_.is_("image_url", "null").limit(1).execute().data or [{}])[0].get("image_url")
        item = {
            "id": row["id"],
            "position": row["position"],
            "slug": cluster.get("slug"),
            "title": a["title"],
            "category": cluster.get("category"),
            "image_url": image,
            "bullets": bullets,
            "sections": reader_sections(extras),
            "coverage_counts": row.get("coverage_counts"),
            "counts_as_of": row.get("counts_as_of"),
        }
        if not publishable_only:
            first_ok = first_approval_valid(row, summary)
            item.update({
                "lane": a["lane"],
                "reasons": a["reasons"],
                "publishable": publishable,
                "is_sample": row.get("is_sample"),
                "source_headline": cluster.get("representative_title"),
                "summary_bullets": (summary or {}).get("bullets") or [],
                "summary_gate": (summary or {}).get("gate"),
                "edited_by": row.get("edited_by"),
                "edited_at": row.get("edited_at"),
                "approved_by": row.get("approved_by") if first_ok else None,
                "approved_at": row.get("approved_at") if first_ok else None,
                "second_approved_by": row.get("second_approved_by") if first_ok else None,
                "second_approved_at": row.get("second_approved_at") if first_ok else None,
                "needs_second_approver": a["lane"] == LANE_SENIOR_REVIEW and first_ok and not approved,
                "approval_checklist": row.get("approval_checklist") if first_ok else None,
                "stale_approval_by": row.get("approved_by") if row.get("approved_by") and not first_ok else None,
                "left_out_by": row.get("left_out_by"),
                "extras_dropped": row.get("extras_dropped") or [],
                "extras_error": row.get("extras_error"),
                "named_in_sources": named_people(row["cluster_id"]),
                "sources": source_articles(row["cluster_id"]),
            })
        items.append(item)
    return items


def item_lane(row):
    """Routing for one stored row (used by the approve endpoint)."""
    summary = latest_summary(row["cluster_id"])
    cluster = (supabase.table("clusters").select("representative_title")
               .eq("id", row["cluster_id"]).limit(1).execute().data or [{}])[0]
    a, _, _ = route_row(row, cluster, summary, load_registry())
    return a["lane"], summary
