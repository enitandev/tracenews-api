"""
Builds and serves the rebuilt Daily Briefing (counsel, 3 Oct 2026, section B,
amended by counsel's review of the 3 Oct samples). Rules and strings live in
app/briefingStrings.py.

An edition is one row per selected story in briefing_editions. Rows are built
whether or not the Briefing is public, so staff can review them.

Prompt-first (counsel's ruling of 3 Oct 2026 adopting the owner's decision):
when an edition is built, auto_correct() fixes the headline, removes
offending bullets, quotes and next steps, and corrects party descriptors,
logging every correction with the actor "system". When an item is read,
assess_item() routes it: one editor lane for accusations and proceedings
about named people or organisations; everything else publishes.
"""
import logging
import re
import time as _time
from datetime import datetime, time, timedelta, timezone

from app.briefingStrings import (
    ACTOR_ROLE_WORDS, AUTHORITY_WORDS, CANDIDACY_WORDS, EDITION_CUTOFF_HOUR_LAGOS, EDITOR_LANE_TRIGGERS,
    FORBIDDEN_TOKENS, HEADLINE_ATTRIBUTION_PATTERN, HEADLINE_BODY_TERMS, HEADLINE_CASUALTY_TERMS,
    HEADLINE_PREFIXES, HEADLINE_QUANTITY_WORDS, HEADLINE_TRAILING_PHRASES, LANE_AUTO, LANE_LEFT_OUT,
    LANE_REVIEW, LANE_SENIOR_REVIEW, LANES_NEEDING_EDITOR, MAX_STORIES, MIN_DISTINCT_OUTLETS, SENIOR_SECOND_APPROVERS,
    PARTY_ALIASES, PARTY_NAMES, SUSPENSION_TRIGGERS, WINDOW_HOURS,
)
from app import names
from app.db import supabase
from app.storySummaryStrings import (
    ADVERSE_CONTEXT_TERMS, PRINCIPAL_OFFICEHOLDERS, SUMMARY_MIN_BULLETS,
)
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
        page = supabase.table("politicians").select("full_name, common_name, publication_status, party, current_position") \
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
        names_ = {n.strip() for n in (r.get("full_name"), r.get("common_name")) if n and len(n.strip()) > 3}
        if any(_has(n, text) for n in names_):
            out.append(r)
    return out


def headline_issues(title, body):
    """A number or quantity word in the headline the body does not support, or
    an unattributed casualty claim."""
    issues = []
    num = re.compile(r"\d+(?:[.,]\d+)*")
    body_nums = {n.replace(",", "") for n in num.findall(body)}
    missing = [n for n in num.findall(title) if n.replace(",", "") not in body_nums]
    if missing:
        issues.append("number not in body: " + ", ".join(missing))
    words = [w for w in HEADLINE_QUANTITY_WORDS if _has(w, title) and not _has(w, body)]
    if words:
        issues.append("quantity word not in body: " + ", ".join(words))
    if any(_has(t, title) for t in HEADLINE_CASUALTY_TERMS) and not re.search(HEADLINE_ATTRIBUTION_PATTERN, title, re.IGNORECASE):
        issues.append("unattributed casualty claim")
    return issues


def headline_problems(title, body_parts):
    """Every reason a cleaned headline cannot be used; empty if it can."""
    if not title:
        return ["empty after cleaning"]
    body = " ".join(body_parts)
    problems = []
    token = has_forbidden_token([title])
    if token:
        problems.append(f"forbidden word: {token}")
    conflict = headline_body_conflict(title, body_parts)
    if conflict:
        problems.append(f"term not in body: {conflict}")
    return problems + headline_issues(title, body)


# ═══ AUTOMATIC CORRECTIONS (at build; logged as "system") ════════════════════

def _sentences(text):
    return [x for x in re.split(r"(?<=[.!?])\s+", text or "") if x.strip()]


def bullet_problem(bullet, articles_text):
    """Why a single bullet must be removed, or None."""
    token = has_forbidden_token([bullet])
    if token:
        return f"forbidden word: {token}"
    ev = evaluate_summary([bullet, "-"], articles_text)
    bad = [f for f in ev["flags"] if f.startswith(("forbidden_coverage", "escalation", "bullet_type"))]
    return "; ".join(bad) or None


def _party_key(name):
    name = (name or "").strip()
    for full, short in PARTY_ALIASES.items():
        if name.lower() in (full.lower(), short.lower()):
            return short.lower()
    return name.lower()


def correct_descriptors(text, registry):
    """A party or candidacy descriptor next to a registry person's name is
    checked against the registry's party. Only a party that conflicts with the
    registry is changed: that party name is swapped for the registry's, and
    the rest of the descriptor is kept as the sources wrote it. Nothing from
    the registry's position field is ever inserted. If the registry has no
    party for the person, the descriptor is dropped."""
    notes = []
    for r in registry:
        for name in {n for n in (r.get("full_name"), r.get("common_name")) if n and len(n) > 3}:
            # "Name, <descriptor>," — an appositive that mentions a party or candidacy.
            pattern = re.compile(re.escape(name) + r",\s+([^,;.]{3,120}?)(?=[,;.])")
            m = pattern.search(text)
            if not m:
                continue
            desc = m.group(1)
            # Longest names first, so "Labour Party" is found before "LP" or "Accord Party" before "Accord".
            named = [p for p in sorted(PARTY_NAMES, key=len, reverse=True) if _has(p, desc, case_sensitive=p.isupper())]
            if not (named or any(_has(w, desc) for w in CANDIDACY_WORDS)):
                continue
            party = (r.get("party") or "").strip()
            if not party:
                # Drop ", <descriptor>" and the comma that closed the appositive.
                tail = text[m.end(1):]
                text = text[:m.start(1) - 2] + (tail[1:] if tail.startswith(",") else tail)
                notes.append(f"descriptor for {name} dropped (no party in the registry): '{desc}'")
                continue
            wrong = [p for p in named if _party_key(p) != _party_key(party)]
            if not wrong:
                continue
            fixed = desc
            for p in wrong:
                flags = 0 if p.isupper() else re.IGNORECASE
                fixed = re.sub(r"(?<![\w-])" + re.escape(p) + r"(?![\w-])", party, fixed, flags=flags)
            text = text[:m.start(1)] + fixed + text[m.end(1):]
            notes.append(f"party for {name} corrected from the registry: '{desc}' -> '{fixed}'")
    return text, notes


def auto_correct(headlines, bullets, extras, articles_text, registry):
    """Apply every automatic correction. headlines: the story's source
    headlines, representative one first. Returns (title, bullets, extras,
    corrections, left_out_reason)."""
    corrections = []
    kept = []
    for b in [b for b in bullets if isinstance(b, str)]:
        problem = bullet_problem(b, articles_text)
        if problem:
            corrections.append(f"bullet removed ({problem}): {b[:80]}")
            continue
        b, notes = correct_descriptors(b, registry)
        corrections += notes
        kept.append(b)
    extras = dict(extras or {})
    for key in ("next", "background"):
        fixed = []
        for t in extras.get(key) or []:
            problem = bullet_problem(t, articles_text)
            if problem:
                corrections.append(f"{key} removed ({problem}): {t[:80]}")
                continue
            t, notes = correct_descriptors(t, registry)
            corrections += notes
            fixed.append(t)
        extras[key] = fixed
    quotes = []
    for q in extras.get("quotes") or []:
        problem = bullet_problem(q.get("quote", ""), articles_text)
        if problem:
            corrections.append(f"quote removed ({problem}): {q.get('quote', '')[:80]}")
        else:
            quotes.append(q)
    extras["quotes"] = quotes
    if len(kept) < SUMMARY_MIN_BULLETS:
        return None, kept, extras, corrections, "fewer than two points left after corrections"

    body_parts = kept + [x for k in ("next", "background") for x in extras.get(k) or []]
    title, first_problems = None, None
    for i, raw in enumerate(h for h in headlines if h):
        cleaned = clean_headline(raw)
        problems = headline_problems(cleaned, body_parts)
        if i == 0:
            first_problems = problems
        if not problems:
            title = cleaned
            if i > 0:
                corrections.append(f"headline replaced ({'; '.join(first_problems)}): '{clean_headline(headlines[0])}' -> '{cleaned}'")
            break
    if title is None:
        return None, kept, extras, corrections, "no source headline passes the headline checks"
    return title, kept, extras, corrections, None


# ═══ THE EDITOR LANE (at read) ═══════════════════════════════════════════════

_AUTHORITY = set(AUTHORITY_WORDS)


def _subjects(sentence, registry):
    """Named people and organisations in a sentence that are not themselves
    the authority acting, nor named only as a spokesperson, judge or lawyer."""
    found = []
    for r in registry_matches(sentence, registry):
        found.append(r.get("common_name") or r.get("full_name"))
    for name in names.person_names(sentence):
        at = sentence.find(name.split()[0])
        around = sentence[max(0, at - 45): at + len(name) + 45]
        if any(role in around for role in ACTOR_ROLE_WORDS):
            continue
        found.append(name)
    for org in names.organisation_names(sentence):
        if not any(w in _AUTHORITY for w in org.split()):
            found.append(org)
    return list(dict.fromkeys(found))


# Everyday phrases that contain a trigger word but are not a proceeding.
_BENIGN = re.compile(r"\b(in charge( of)?|free of charge|charge d'affaires|chargé d'affaires|court of public opinion)\b", re.IGNORECASE)


def lane_triggers(texts, registry):
    """(reason, principal_named) for the editor lane, or (None, False)."""
    reasons, principal = [], False
    for text in texts:
        for sentence in _sentences(_BENIGN.sub(" ", text)):
            hits = [k for k, pat in EDITOR_LANE_TRIGGERS.items() if re.search(pat, sentence, re.IGNORECASE)]
            susp = [k for k, pat in SUSPENSION_TRIGGERS.items() if re.search(pat, sentence, re.IGNORECASE)]
            if not (hits or susp):
                continue
            subjects = _subjects(sentence, registry)
            if susp:
                subjects_people = [x for x in subjects if not names.organisation_names(x)]
                if subjects_people:
                    hits += susp
            if hits and subjects:
                reasons.append(f"{', '.join(dict.fromkeys(hits))} — {', '.join(subjects)}")
                if any(_has(p, sentence) for p in PRINCIPAL_OFFICEHOLDERS):
                    principal = True
    return ("editor lane: " + "; ".join(dict.fromkeys(reasons)) if reasons else None), principal


def assess_item(raw_title, bullets, articles_text, registry, extra_texts=()):
    """Route one item from its current text. Returns the title, the lane
    (auto / review / senior_review / left_out) and every reason."""
    bullets = bullets if isinstance(bullets, list) else [bullets]
    title = clean_headline(raw_title)
    text_bullets = [b for b in bullets if isinstance(b, str)]
    extras = [t for t in extra_texts if isinstance(t, str) and t.strip()]
    body_parts = text_bullets + extras

    def left_out(reason):
        return {"title": title, "lane": LANE_LEFT_OUT, "reasons": [reason]}

    if not title:
        return left_out("headline empty after cleaning")
    token = has_forbidden_token([title] + body_parts)
    if token:
        return left_out(f"forbidden word: {token}")
    if len(text_bullets) < SUMMARY_MIN_BULLETS:
        return left_out("fewer than two points")
    remaining = [b for b in body_parts if bullet_problem(b, articles_text)]
    if remaining:
        return left_out("check failed after corrections: " + bullet_problem(remaining[0], articles_text))

    lane, reasons = LANE_AUTO, []
    reason, principal = lane_triggers([title] + body_parts, registry)
    if reason:
        reasons.append(reason)
        lane = LANE_SENIOR_REVIEW if principal else LANE_REVIEW
    full = _BENIGN.sub(" ", " ".join([title] + body_parts))
    if any(_has(t, full) for t in ADVERSE_CONTEXT_TERMS):
        protected = [m.get("common_name") or m.get("full_name") for m in registry_matches(full, registry)
                     if m.get("publication_status") in PROTECTED_STATUSES]
        if protected:
            reasons.append("adverse item naming a held or private person: " + ", ".join(protected))
            lane = lane if lane == LANE_SENIOR_REVIEW else LANE_REVIEW
    return {"title": title, "lane": lane, "reasons": reasons}


# ═══ SUMMARIES AND COUNTS ════════════════════════════════════════════════════

def summary_usable(summary):
    """A summary the Briefing can correct and route: present, not superseded
    by a correction, not a failed generation, with text."""
    if not summary or summary.get("superseded") or is_generation_failure(summary):
        return False
    return bool([b for b in summary.get("bullets") or [] if isinstance(b, str)])


def latest_summary(cluster_id):
    """The newest summary the Briefing works from. The Briefing applies its own
    corrections and editor lane, so the story page's gate does not decide;
    a correction still wins (a superseded newest row is never replaced by an
    older one)."""
    rows = supabase.table("cluster_summaries").select("*").eq("cluster_id", cluster_id) \
        .order("generated_at", desc=True).limit(20).execute().data or []
    if rows and rows[0].get("superseded"):
        return rows[0]
    return next((r for r in rows if not is_generation_failure(r) and r.get("bullets")), rows[0] if rows else None)


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
    """Select a day's stories, apply the automatic corrections and record them.
    Idempotent per day. sample=True builds a staff-only sample edition for
    counsel. with_extras generates the fuller sections (one model call per
    story). Every correction is logged to briefing_edit_log as "system"."""
    day = day or lagos_today()
    if supabase.table("briefing_editions").select("id").eq("date", day.isoformat()).limit(1).execute().data:
        # One edition per date, real or sample (unique date + story).
        return {"status": "already_built", "date": day.isoformat()}

    start, end = edition_window(day)
    registry = load_registry()
    rows, logs, skipped = [], [], {}
    now = datetime.now(timezone.utc).isoformat()
    for cluster in select_clusters(candidate_clusters(start, end)):
        summary = latest_summary(cluster["id"])
        if not summary_usable(summary):
            skipped[cluster["slug"]] = "no usable summary (missing, superseded or failed)"
            continue
        row = {
            "date": day.isoformat(),
            "position": len(rows) + 1,
            "cluster_id": cluster["id"],
            "summary_id": str(summary["id"]),
            "gate": summary.get("gate"),
            "coverage_counts": coverage_counts(cluster["id"]),
            "counts_as_of": now,
            "is_sample": sample,
        }
        if with_extras:
            row.update(make_extras(cluster["id"]))
            row["extras_generated_at"] = now
        headlines = [cluster.get("representative_title")] + [
            a.get("title") for a in source_articles(cluster["id"]) if a.get("title") != cluster.get("representative_title")]
        before = {"title": cluster.get("representative_title"), "bullets": summary.get("bullets"),
                  "sections": row.get("extras")}
        title, bullets, extras, corrections, out_reason = auto_correct(
            headlines, summary.get("bullets") or [], row.get("extras"), cluster_articles_text(cluster["id"]), registry)
        if corrections or out_reason:
            row.update({"edited_title": title, "edited_bullets": bullets, "edited_extras": extras,
                        "edited_by": "system", "edited_at": now})
        if out_reason:
            row.update({"left_out_by": "system", "left_out_reason": out_reason, "left_out_at": now})
        logs.append((len(rows), before, {"title": title, "bullets": bullets, "sections": extras},
                     corrections + ([f"left out: {out_reason}"] if out_reason else [])))
        rows.append(row)
    if rows:
        inserted = supabase.table("briefing_editions").insert(rows).execute().data or []
        entries = [{
            "edition_id": inserted[i]["id"], "date": day.isoformat(), "cluster_id": rows[i]["cluster_id"],
            "is_sample": sample, "editor": "system", "action": "auto_correct",
            "before": before, "after": after, "note": " | ".join(notes),
        } for i, before, after, notes in logs if notes and i < len(inserted)]
        if entries:
            supabase.table("briefing_edit_log").insert(entries).execute()
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
                "waiting_for": waiting_for(row.get("approved_by"))
                if a["lane"] == LANE_SENIOR_REVIEW and first_ok and not approved else None,
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


def is_senior_approver(editor):
    """Editors are recorded as "Name (role)"; the name decides."""
    return bool(editor) and editor.split(" (")[0] in SENIOR_SECOND_APPROVERS


def waiting_for(approved_by):
    """Who can give the missing approval on a senior-review item."""
    if is_senior_approver(approved_by):
        return f"an editor other than {approved_by.split(' (')[0]}"
    return " or ".join(SENIOR_SECOND_APPROVERS)


def item_lane(row):
    """Routing for one stored row (used by the approve endpoint)."""
    summary = latest_summary(row["cluster_id"])
    cluster = (supabase.table("clusters").select("representative_title")
               .eq("id", row["cluster_id"]).limit(1).execute().data or [{}])[0]
    a, _, _ = route_row(row, cluster, summary, load_registry())
    return a["lane"], summary
