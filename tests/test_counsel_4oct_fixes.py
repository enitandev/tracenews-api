"""Counsel's clearance of 4 Oct 2026: fixes 1-6, tested on the named sample items.

The items are the reader text of the 4 Oct sample editions
(tests/fixtures/counsel_4oct_items.json). Each test feeds the item through the
build-time corrections and the read-time routing with the current code.
"""
import json
from pathlib import Path

import app.briefing_edition as be
from app.briefingStrings import PARTY_ALIASES, PARTY_NAMES

ITEMS = json.loads((Path(__file__).parent / "fixtures" / "counsel_4oct_items.json").read_text())
OUTLETS = ("News Agency of Nigeria", "NAN", "Punch", "Vanguard", "Channels Television", "CNN", "Politico")


def correct(key, headlines=None, bullets=None):
    it = ITEMS[key]
    bullets = bullets or it["bullets"]
    src = "\n".join([it["title"]] + bullets + it["background"] + it["next"])
    title, kept, extras, notes, out = be.auto_correct(
        headlines or [it["title"]], bullets, {"next": it["next"], "background": it["background"], "quotes": []},
        src, [], OUTLETS)
    lane = be.assess_item(title, kept, src, [], extras["next"] + extras["background"]) if title else None
    return title, kept, extras, notes, out, lane


# Fix 1: headlines
def test_fix1_adamawa_headlines_stating_killings_as_fact_are_rejected():
    it = ITEMS["adamawa"]
    body = " ".join(it["bullets"])
    assert "unattributed casualty claim" in be.headline_issues(it["title"], body)        # "neutralizes", "success"
    assert be.headline_problems(be.clean_headline(it["source_headline"]), it["bullets"])  # "kill scores"
    title, *_, out, _ = correct("adamawa", [it["source_headline"], it["title"]])
    assert title is None and out == "no source headline passes the headline checks"


def test_fix1_ndlea_offender_label_needs_conviction_or_suspected():
    it = ITEMS["ndlea"]
    issues = be.headline_issues(it["title"], " ".join(it["bullets"]))
    assert any(i.startswith("offender label") for i in issues)                            # "docks kingpins"
    assert be.headline_issues("NDLEA arraigns suspected kingpins over Enugu meth lab", " ".join(it["bullets"])) == []
    assert be.headline_issues("Four kidnappers sentenced to death in Edo", "Four kidnappers were sentenced to death.") == []


def test_fix1_new_casualty_terms():
    for h in ("Troops eliminate bandits in Zamfara", "Gunmen gun down farmers in Benue", "Army wipes out camp",
              "Operation recorded major success"):
        assert "unattributed casualty claim" in be.headline_issues(h, h), h
    assert be.headline_issues("Army says troops eliminated 12 bandits in Zamfara", "12 bandits") == []


# Fix 2: criticism with a collective origin
def test_fix2_house_of_reps_civil_society_concerns_removed():
    title, kept, _, notes, out, lane = correct("reps")
    assert out is None and not any("civil society" in b for b in kept)
    assert any("collective origin" in n for n in notes) and lane["lane"] == "auto"


def test_fix2_dodged_collective_criticism_removed_everywhere():
    title, kept, extras, notes, out, _ = correct("dodged")
    text = " ".join(kept + extras["background"])
    for phrase in ("commentators", "some voices", "colonised", "mixed feelings", "bad governance"):
        assert phrase not in text, phrase
    # Counsel expected the item to fall below three points; five remain (see the change note).
    assert len(kept) == 5 and out is None


def test_fix2_fewer_than_three_points_leaves_the_item_out():
    _, _, _, _, out = be.auto_correct(["Nigeria at 66"], [
        "Critics described the celebrations as a failure.", "Some voices condemned the speech.",
        "Nigeria marked 66 years of independence.", "The President addressed the nation."], {}, "x", [])
    assert out == "fewer than 3 points left after corrections"


# Fix 3: a removed claim is removed from every section
def test_fix3_customs_fire_cause_does_not_return_in_background():
    it = ITEMS["customs"]
    bullets = it["bullets"][:1] + [it["removed_original"]] + it["bullets"][1:]
    title, kept, extras, notes, out, _ = correct("customs", bullets=bullets)
    assert out is None
    assert not any("electrical surge" in t for t in kept + extras["background"] + extras["next"])
    assert any("repeats a removed claim" in n for n in notes)


# Fix 4: outlet names and source numbers
def test_fix4_adamawa_news_agency_of_nigeria_removed():
    _, kept, _, notes, _, _ = correct("adamawa", [ITEMS["adamawa"]["title"]])
    assert not any("News Agency of Nigeria" in b for b in kept)
    assert any("outlet named: News Agency of Nigeria" in n for n in notes)


def test_fix4_dodged_source_numbers_stripped_and_build_guard():
    title, kept, extras, notes, out, _ = correct("dodged")
    assert not any("(Sources" in t for t in kept + extras["background"])
    be.assert_no_source_numbers(title, kept, extras)
    try:
        be.assert_no_source_numbers("t", ["A point. (Sources 2, 3)"], {})
        raise AssertionError("the build guard did not fire")
    except RuntimeError:
        pass


def test_fix4_outlet_allowed_as_subject_or_venue_only():
    assert be.outlet_problem("CNN was banned from the White House.", "US judge blocks White House ban on CNN", OUTLETS) is None
    assert be.outlet_problem("The governor told Channels Television he would run.", "Governor to run", OUTLETS) is None
    assert be.outlet_problem("The report was made available to NAN.", "Troops repel attack", OUTLETS)
    assert be.outlet_problem("The leadership of the Assembly met.", "Assembly meets", OUTLETS + ("Leadership",)) is None


# Fix 5: lane triggers
def test_fix5_dangote_legal_challenge_goes_to_the_lane():
    *_, lane = correct("dangote")
    assert lane["lane"] == "review" and "legal challenge" in lane["reasons"][0]


def test_fix5_us_judge_suspension_of_a_ban_does_not_trigger():
    *_, lane = correct("usjudge")
    assert not any("suspend" in r for r in lane["reasons"])


def test_fix5_suspend_triggers_when_a_person_is_suspended():
    a = be.assess_item("Council suspends chairman", ["The council suspended Musa Bello over the audit.",
                                                       "The council met on Monday.", "A report is due in May."], "x", [])
    assert a["lane"] == "review"
    b = be.assess_item("Governor suspends executions", ["Governor Bill Lee suspended all executions in the state.",
                                                          "The state reviewed its protocol.", "A report is due in May."], "x", [])
    assert not any("suspend" in r for r in b["reasons"])


# Fix 6: party name
def test_fix6_ndc_is_nigeria_democratic_congress():
    assert "Nigeria Democratic Congress" in PARTY_NAMES and "National Democratic Congress" not in PARTY_NAMES
    assert PARTY_ALIASES["Nigeria Democratic Congress"] == "NDC"
