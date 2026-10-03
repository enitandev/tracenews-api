"""
Finding people's names in summary text. Shared by the summary gate
(app/summarizer.py) and the Daily Briefing routing (app/briefing_edition.py).
The word lists live in app/briefingStrings.py, with the rules counsel clears.
"""
import re

from app.briefingStrings import SURNAME_CHECK_IGNORE, SURNAME_CHECK_ORG_WORDS

# Capitalised runs; an initial such as "A." stays inside the run ("Peter A. Okebukola").
CAP_RUN = re.compile(r"[A-Z][\w'’\-]*\.?(?:\s+[A-Z][\w'’\-]*\.?)*")
IGNORE = set(SURNAME_CHECK_IGNORE)
ORG = set(SURNAME_CHECK_ORG_WORDS)
ORG_LEADS = ("Operation", "Exercise")


def is_name_word(w):
    """A word that can be part of a person's name: not a title or common
    capitalised word, not an acronym (SSCE, ADC), not an initial, no digits,
    and not a hyphenated common noun ("T-shirts")."""
    if not w or w in IGNORE or len(w) < 2:
        return False
    if w.isupper() or any(ch.isdigit() for ch in w):
        return False
    if "-" in w and any(part[:1].islower() for part in w.split("-")[1:]):
        return False
    return True


def name_runs(text):
    """Capitalised runs of words, each as (position, [name words]) with title
    words dropped and possessives stripped."""
    runs = []
    for m in CAP_RUN.finditer(text or ""):
        raw = m.group(0).split()
        if raw and raw[0] in ORG_LEADS:
            continue
        words = [re.sub(r"(['’]s|['’])$", "", w.rstrip(".")) for w in raw]
        # An organisation word that is not also a title ("Senate President
        # Godswill Akpabio" is a person; "Manchester City" is not).
        if any(w in ORG and w not in IGNORE for w in words):
            continue
        words = [w for w in words if is_name_word(w)]
        if words:
            runs.append((m.start(), words))
    return runs


def person_names(text):
    """Full names of people in the text: runs of two to four name words that
    are not organisations or places."""
    return [" ".join(ws) for _, ws in name_runs(text) if 2 <= len(ws) <= 4]


def organisation_names(text):
    """Named organisations and companies: capitalised runs that contain an
    organisation word ("Manchester City", "Dangote Industries Limited")."""
    out = []
    for m in CAP_RUN.finditer(text or ""):
        words = [re.sub(r"(['’]s|['’])$", "", w.rstrip(".")) for w in m.group(0).split()]
        if len(words) >= 2 and any(w in ORG for w in words):
            out.append(" ".join(words))
    return out
