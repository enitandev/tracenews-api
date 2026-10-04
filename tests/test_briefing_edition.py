"""Rebuilt Daily Briefing rules (counsel, 3 Oct 2026, section B, and counsel's review of the 3 Oct samples)."""
import pytest

import app.briefing_edition as be
from app import briefingStrings


def cluster(cid, distinct, seen="2026-10-03T05:00:00Z", image=True):
    return {"id": cid, "slug": cid, "first_seen_at": seen,
            "coverage_stats": {"coverage_tier_distribution": {"govt_aligned": 0, "mainstream": distinct, "watchdog": 0}},
            "stories": [{"image_url": "https://img/x.jpg" if image else None}]}


def test_selection_is_by_breadth_then_recency_never_tier():
    picked = be.select_clusters([cluster("narrow", 5), cluster("wide", 9), cluster("wide-newer", 9, seen="2026-10-03T06:00:00Z"),
                                 cluster("too-few", 4), cluster("no-image", 12, image=False)])
    assert [c["id"] for c in picked] == ["wide-newer", "wide", "narrow"]


REG = [
    {"full_name": "Atiku Abubakar", "common_name": "Atiku Abubakar", "publication_status": "published"},
    {"full_name": "Simon Bagaiya Shaibu", "common_name": "Simon Shaibu", "publication_status": "pending_review"},
    {"full_name": "Aliko Dangote", "common_name": "Aliko Dangote", "publication_status": "excluded"},
]
NEUTRAL = ["The Federal Executive Council approved a new rail line on Wednesday.",
           "Construction is scheduled to begin in January."]


def assess(title, bullets=NEUTRAL, articles=None, registry=REG):
    return be.assess_item(title, bullets, articles or "\n".join([title] + list(bullets)), registry)


# Item 1: headlines
@pytest.mark.parametrize("raw,clean", [
    ("BREAKING: Senate passes budget", "Senate passes budget"),
    ("JUST IN - Exclusive: CBN cuts rate", "CBN cuts rate"),
    ("FULL LIST: New ministers sworn in", "New ministers sworn in"),
    ("Flood hits Lokoja, see photos", "Flood hits Lokoja"),
    ("Pastor dances at wedding, video trends", "Pastor dances at wedding"),
    ("Watchdog group files suit", "Watchdog group files suit"),
])
def test_headline_cleaning(raw, clean):
    assert be.clean_headline(raw) == clean


# Item 5: forbidden words, whole words only
def test_forbidden_words_are_whole_words_and_percent_is_allowed():
    assert be.has_forbidden_token(["The judge presides over the case."]) is None
    assert be.has_forbidden_token(["Inflation rose to 23.5 percent, or 23.5%."]) is None
    assert be.has_forbidden_token(["Both sides met."]) is None
    assert be.has_forbidden_token(["Observers alleged bias."]) == "bias"
    assert be.has_forbidden_token(["A dramatic turn."]) == "dramatic"
    assert assess("Rail line approved", ["Observers alleged bias in the process.", "x y z."])["lane"] == "left_out"


def test_coverage_panel_is_counts_and_never_percent_or_bias(monkeypatch):
    import app.coverage
    monkeypatch.setattr(app.coverage, "get_outlets_cache", lambda: ({"o1": {"government_alignment": "pro_government"},
                                                                     "o2": {"government_alignment": "neutral"}}, None))

    class Q:
        def select(self, *a): return self
        def eq(self, *a): return self
        def execute(self): return type("R", (), {"data": [{"outlet_id": "o1"}, {"outlet_id": "o2"}, {"outlet_id": "o2"}]})()
    monkeypatch.setattr(be, "supabase", type("DB", (), {"table": lambda self, t: Q()})())
    counts = be.coverage_counts("c1")
    assert all(isinstance(v, int) for v in counts.values())
    panel = " ".join([briefingStrings.UI["coverage_heading"], briefingStrings.UI["coverage_as_of"]]
                     + list(briefingStrings.UI["tier_labels"].values()) + [str(v) for v in counts.values()])
    assert "%" not in panel and "bias" not in panel.lower()


# Item 6: excluded / held / private people
def test_neutral_item_may_name_a_private_person():
    a = assess("Dangote to build refinery in Kenya", ["Aliko Dangote announced a refinery in Kenya.", "Completion is planned for 2030."])
    assert a["lane"] != "left_out"
    assert not any(r.startswith("adverse item naming") for r in a["reasons"])


def test_adverse_item_about_a_private_person_goes_to_review():
    a = assess("Court hears suit against Dangote", ["A court heard a lawsuit filed against Aliko Dangote.", "The judge adjourned the case."])
    assert a["lane"] == "review"
    assert any(r.startswith("adverse item naming a held or private person: Aliko Dangote") for r in a["reasons"])


# Approval covers the exact text approved
def test_approval_is_void_after_a_rewrite_or_a_new_summary():
    row = {"approved_by": "Ada (editorial)", "approved_summary_id": "s1", "approved_edit_at": None, "edited_at": None}
    assert be.approval_valid(row, {"id": "s1"})
    assert not be.approval_valid(row, {"id": "s2"})
    assert not be.approval_valid({**row, "edited_at": "2026-10-04T10:00:00Z"}, {"id": "s1"})
    assert be.approval_valid({**row, "edited_at": "2026-10-04T10:00:00Z", "approved_edit_at": "2026-10-04T10:00:00Z"}, {"id": "s1"})


# Item 7: "Named in the source articles" is reviewer-only; samples never reach readers
class FakeDB:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        db = self

        class Q:
            def __init__(self):
                self.rows = list(db.tables.get(name, []))

            def select(self, *a): return self
            def eq(self, col, val):
                self.rows = [r for r in self.rows if r.get(col) == val]
                return self
            def in_(self, col, vals):
                self.rows = [r for r in self.rows if r.get(col) in vals]
                return self
            def order(self, *a, **k): return self
            def limit(self, *a): return self
            def range(self, *a): return self
            @property
            def not_(self): return self
            def is_(self, *a): return self
            def execute(self): return type("R", (), {"data": self.rows})()
        return Q()


def edition_db():
    row = {"id": "e1", "date": "2026-10-04", "position": 1, "cluster_id": "c1", "is_sample": False,
           "coverage_counts": {"govt_aligned": 1, "mainstream": 4, "watchdog": 0}, "counts_as_of": "2026-10-04T05:00:00Z"}
    return FakeDB({
        "briefing_editions": [row, {**row, "id": "e2", "cluster_id": "c2", "is_sample": True}],
        "cluster_summaries": [{"id": "s1", "cluster_id": "c1", "gate": "auto", "flags": None, "bullets": NEUTRAL},
                              {"id": "s2", "cluster_id": "c2", "gate": "auto", "flags": None, "bullets": NEUTRAL}],
        "clusters": [{"id": "c1", "slug": "rail", "representative_title": "BREAKING: Rail line approved", "category": "Economy"},
                     {"id": "c2", "slug": "rail-2", "representative_title": "Rail line approved", "category": "Economy"}],
        "stories": [{"id": "st1", "cluster_id": "c1", "title": "Rail line approved", "summary": NEUTRAL[0], "image_url": "x.jpg"}],
        "story_entities": [{"story_id": "st1", "politician_id": "p1", "entity_type": "politician"}],
        "politicians": [{"id": "p1", "common_name": "Aliko Dangote", "full_name": "Aliko Dangote", "publication_status": "excluded"}],
    })


def test_reader_items_carry_no_reviewer_fields_and_no_samples(monkeypatch):
    from datetime import date
    monkeypatch.setattr(be, "supabase", edition_db())
    monkeypatch.setattr(be, "cluster_articles_text", lambda cid: "Rail line approved. " + " ".join(NEUTRAL))
    be._registry.update(at=0, rows=[])
    public = be.edition_items(date(2026, 10, 4))
    assert [i["id"] for i in public] == ["e1"]
    assert public[0]["title"] == "Rail line approved"
    for key in ("named_in_sources", "reasons", "lane", "sources", "source_headline", "summary_bullets"):
        assert key not in public[0]
    staff = be.edition_items(date(2026, 10, 4), publishable_only=False)
    assert {i["id"] for i in staff} == {"e1", "e2"}
    assert staff[0]["named_in_sources"] == ["Aliko Dangote"]


def test_held_item_publishes_only_with_a_valid_approval(monkeypatch):
    from datetime import date
    db = edition_db()
    db.tables["cluster_summaries"][0]["bullets"] = ["The police arrested Musa Bello, a contractor, in Abuja on Monday.", "He was released on bail."]
    monkeypatch.setattr(be, "supabase", db)
    monkeypatch.setattr(be, "cluster_articles_text", lambda cid: "The police arrested Musa Bello, a contractor, in Abuja. He was released on bail.")
    be._registry.update(at=0, rows=[])
    assert be.edition_items(date(2026, 10, 4)) == []
    db.tables["briefing_editions"][0].update(approved_by="Ada (editorial)", approved_summary_id="s1")
    assert [i["id"] for i in be.edition_items(date(2026, 10, 4))] == ["e1"]


def test_summary_model_receives_no_outlet_identifier(monkeypatch):
    import app.summarizer as summarizer
    sent = {}

    class Rows:
        data = [{"title": "Headline one", "summary": "Text one"}, {"title": "Headline two", "summary": "Text two"}]

    class Q:
        def __getattr__(self, _):
            return lambda *a, **k: self

        def execute(self):
            return Rows()

    class Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    sent["messages"] = kw["messages"]
                    raise RuntimeError("stop after capturing the prompt")

    monkeypatch.setattr(summarizer, "supabase", type("DB", (), {"table": lambda self, t: Q()})())
    monkeypatch.setattr(summarizer, "openai_client", Client)
    monkeypatch.setattr(summarizer, "record_generation_failure", lambda *a: None)
    summarizer.generate_cluster_summary("c1")
    articles = sent["messages"][1]["content"].split("covering this story:")[1].split("Write ")[0]
    assert articles.strip().splitlines()[0] == "Source 1"
    assert "Source 2" in articles and "Source:" not in articles and "outlet" not in articles.lower()


def test_candidate_clusters_attaches_images_without_embedding_stories(monkeypatch):
    from datetime import datetime, timedelta, timezone
    calls = []

    class Q:
        def __init__(self, table):
            self.table, self.filters = table, {}

        def select(self, cols):
            calls.append((self.table, cols))
            return self

        def in_(self, col, vals):
            self.filters["in"] = list(vals)
            return self

        @property
        def not_(self):
            return self

        def is_(self, *a):
            return self

        def gte(self, *a):
            return self

        def lt(self, *a):
            return self

        def order(self, *a, **k):
            return self

        def limit(self, *a):
            return self

        def execute(self):
            if self.table == "clusters":
                data = [{"id": "c1", "slug": "a"}, {"id": "c2", "slug": "b"}]
            else:
                data = [{"cluster_id": cid, "image_url": "x.jpg"} for cid in self.filters["in"] if cid == "c1"]
            return type("R", (), {"data": data})()

    monkeypatch.setattr(be, "supabase", type("DB", (), {"table": lambda self, t: Q(t)})())
    end = datetime.now(timezone.utc)
    out = {c["id"]: c for c in be.candidate_clusters(end - timedelta(hours=24), end)}
    assert out["c1"]["stories"] == [{"image_url": "x.jpg"}]
    assert out["c2"]["stories"] == []
    assert all("stories(" not in cols for _, cols in calls)


# Item 9: named editor, full checklist, every action logged
def editor_setup(monkeypatch, actor="Ada Obi (editorial)", lane="review"):
    import app.routers.briefing as br
    db = edition_db()
    db.tables["briefing_edit_log"] = []
    updates = []

    real_table = db.table

    def table(name):
        q = real_table(name)
        q.insert = lambda data: (db.tables[name].append(data), q)[1]
        q.update = lambda data: (updates.append(data), q)[1]
        return q
    db.table = table
    monkeypatch.setattr(br, "supabase", db)
    monkeypatch.setattr(br, "get_actor_name", lambda auth: actor)
    monkeypatch.setattr(br, "item_lane", lambda row: (lane, {"id": "s1", "bullets": NEUTRAL}))
    return br, db, updates


ALL_TICKED = {k: True for k, _ in briefingStrings.EDITOR_CHECKLIST}


def test_approval_needs_every_checklist_line(monkeypatch):
    from fastapi import HTTPException
    br, db, updates = editor_setup(monkeypatch)
    with pytest.raises(HTTPException) as e:
        br.approve_item("e1", br.Approval(checklist={**ALL_TICKED, "party_live": False}, no_party_descriptors=True), authorization="Bearer t")
    assert e.value.status_code == 422 and not updates and not db.tables["briefing_edit_log"]
    br.approve_item("e1", br.Approval(checklist=ALL_TICKED, no_party_descriptors=True), authorization="Bearer t")
    assert updates[0]["approved_by"] == "Ada Obi (editorial)" and updates[0]["approved_summary_id"] == "s1"
    assert db.tables["briefing_edit_log"][0]["action"] == "approve"


def test_approval_needs_a_named_editor(monkeypatch):
    from fastapi import HTTPException
    br, _, updates = editor_setup(monkeypatch, actor="3f2b8c1e-1111-2222-3333-444455556666 (editorial)")
    with pytest.raises(HTTPException) as e:
        br.approve_item("e1", br.Approval(checklist=ALL_TICKED, no_party_descriptors=True), authorization="Bearer t")
    assert e.value.status_code == 403 and not updates


def test_auto_or_left_out_items_cannot_be_approved(monkeypatch):
    from fastapi import HTTPException
    br, _, _ = editor_setup(monkeypatch, lane="left_out")
    with pytest.raises(HTTPException) as e:
        br.approve_item("e1", br.Approval(checklist=ALL_TICKED, no_party_descriptors=True), authorization="Bearer t")
    assert e.value.status_code == 409


def test_rewrite_is_logged_with_before_and_after_and_rejects_forbidden_words(monkeypatch):
    from fastapi import HTTPException
    br, db, updates = editor_setup(monkeypatch)
    with pytest.raises(HTTPException):
        br.rewrite_item("e1", br.Rewrite(bullets=["A dramatic turn of events."]), authorization="Bearer t")
    br.rewrite_item("e1", br.Rewrite(title="ADC names campaign council", bullets=["One.", "Two."], note="from sources"),
                    authorization="Bearer t")
    entry = db.tables["briefing_edit_log"][-1]
    assert entry["action"] == "rewrite"
    assert entry["after"] == {"title": "ADC names campaign council", "bullets": ["One.", "Two."], "sections": None}
    assert entry["editor"] == "Ada Obi (editorial)" and updates[-1]["edited_by"] == "Ada Obi (editorial)"


def test_staff_edition_dates_lists_each_date_once_with_counts(monkeypatch):
    import app.routers.briefing as br
    monkeypatch.setattr(br, "supabase", edition_db())
    out = br.staff_edition_dates()
    assert out == {"dates": [{"date": "2026-10-04", "is_sample": False, "items": 2}]}


# Counsel's ruling, 3 Oct, item 5: party checks, second approver, no duplicates
def test_party_live_needs_source_and_time_for_each_descriptor(monkeypatch):
    from fastapi import HTTPException
    br, db, updates = editor_setup(monkeypatch)
    with pytest.raises(HTTPException) as e:
        br.approve_item("e1", br.Approval(checklist=ALL_TICKED), authorization="Bearer t")
    assert e.value.status_code == 422 and not updates
    with pytest.raises(HTTPException):
        br.approve_item("e1", br.Approval(checklist=ALL_TICKED, party_checks=[
            {"descriptor": "Atiku Abubakar, ADC candidate", "source": "", "checked_at": "3 Oct 17:00"}]), authorization="Bearer t")
    br.approve_item("e1", br.Approval(checklist=ALL_TICKED, party_checks=[
        {"descriptor": "Atiku Abubakar, ADC candidate", "source": "inecnigeria.org", "checked_at": "3 Oct 2026 17:00 WAT"}]),
        authorization="Bearer t")
    assert updates[-1]["approval_checklist"]["party_checks"][0]["source"] == "inecnigeria.org"


def approved_row(db):
    db.tables["briefing_editions"][0].update(approved_by="Ada Obi (editorial)", approved_summary_id="s1",
                                             approved_edit_at=None, edited_at=None)


def test_senior_review_needs_a_second_different_approver(monkeypatch):
    from fastapi import HTTPException
    br, db, updates = editor_setup(monkeypatch, lane="senior_review")
    approved_row(db)
    with pytest.raises(HTTPException) as e:
        br.approve_item("e1", br.Approval(checklist=ALL_TICKED, no_party_descriptors=True), authorization="Bearer t")
    assert e.value.status_code == 409 and "second approver" in e.value.detail
    monkeypatch.setattr(br, "get_actor_name", lambda auth: "Enitan Bello (super_admin)")
    br.approve_item("e1", br.Approval(checklist=ALL_TICKED, no_party_descriptors=True), authorization="Bearer t")
    assert updates[-1]["second_approved_by"] == "Enitan Bello (super_admin)"
    assert db.tables["briefing_edit_log"][-1]["action"] == "approve_second"


def test_a_second_approval_click_is_refused_not_logged_twice(monkeypatch):
    from fastapi import HTTPException
    br, db, updates = editor_setup(monkeypatch, lane="review")
    approved_row(db)
    with pytest.raises(HTTPException) as e:
        br.approve_item("e1", br.Approval(checklist=ALL_TICKED, no_party_descriptors=True), authorization="Bearer t")
    assert e.value.status_code == 409 and not db.tables["briefing_edit_log"]


def test_senior_item_publishes_only_with_both_approvals():
    row = {"approved_by": "Ada (editorial)", "approved_summary_id": "s1", "approved_edit_at": None, "edited_at": None}
    assert be.approval_valid(row, {"id": "s1"}, "review")
    assert not be.approval_valid(row, {"id": "s1"}, "senior_review")
    assert not be.approval_valid({**row, "second_approved_by": "Ada (editorial)"}, {"id": "s1"}, "senior_review")
    assert be.approval_valid({**row, "second_approved_by": "Enitan (super_admin)"}, {"id": "s1"}, "senior_review")


def test_section_rewrite_rejects_a_quote_not_in_the_sources(monkeypatch):
    from fastapi import HTTPException
    br, db, updates = editor_setup(monkeypatch)
    monkeypatch.setattr(br, "cluster_articles_text", lambda cid: 'Source 1\nSummary: Minister Ada Obi said "work starts in January".')
    with pytest.raises(HTTPException) as e:
        br.rewrite_item("e1", br.Rewrite(sections={"quotes": [{"speaker": "Ada Obi", "role": "Minister", "quote": "work starts soon"}]}),
                        authorization="Bearer t")
    assert e.value.status_code == 422 and "Not saved" in e.value.detail
    br.rewrite_item("e1", br.Rewrite(sections={"quotes": [{"speaker": "Ada Obi", "role": "Minister", "quote": "work starts in January"}]}),
                    authorization="Bearer t")
    assert updates[-1]["edited_extras"]["quotes"][0]["quote"] == "work starts in January"


# Item 6: the fuller sections
SRC = ('Source 1\nHeadline: Court adjourns case\nSummary: Justice Inyang Ekwo adjourned the case to October 13, 2026. '
       '"We will be ready," lawyer Musa Bello said. The suit was filed in July 2026.')


def test_quotes_must_appear_verbatim_and_render_with_said():
    from app.briefing_extras import check_extras, quote_line
    kept, dropped = check_extras({"quotes": [
        {"speaker": "Musa Bello", "role": "lawyer for the plaintiffs", "quote": "We will be ready,"},
        {"speaker": "Musa Bello", "role": "lawyer", "quote": "We will win"}]}, SRC)
    assert len(kept["quotes"]) == 1 and "verbatim" in dropped[0]
    assert quote_line(kept["quotes"][0]) == 'Musa Bello, lawyer for the plaintiffs, said: "We will be ready,"'


def test_next_steps_must_be_attributed_and_not_predictions():
    from app.briefing_extras import check_extras
    kept, dropped = check_extras({"next": [
        "Justice Inyang Ekwo adjourned the case to October 13, 2026.",
        "The case will likely end in November.",
        "The hearing is on October 20, 2026, the court said."]}, SRC)
    assert kept["next"] == ["Justice Inyang Ekwo adjourned the case to October 13, 2026."]
    assert len(dropped) == 2


def test_background_about_a_named_persons_conduct_needs_an_attributed_public_record():
    from app.briefing_extras import check_extras
    kept, dropped = check_extras({"background": [
        "Musa Bello was accused of fraud in 2019.",
        "The suit was filed in July 2026, according to court records.",
        "The state has 23 local government areas."] + ["Extra point."] * 2}, SRC)
    assert "Musa Bello was accused of fraud in 2019." not in kept["background"]
    assert len(kept["background"]) == 3


def test_sections_follow_the_gate_and_reach_readers_without_reviewer_fields(monkeypatch):
    from datetime import date
    db = edition_db()
    db.tables["briefing_editions"][0]["extras"] = {"quotes": [], "next": ["The council will meet on Monday, the minister said."], "background": []}
    monkeypatch.setattr(be, "supabase", db)
    monkeypatch.setattr(be, "cluster_articles_text", lambda cid: "Rail line approved. " + " ".join(NEUTRAL))
    be._registry.update(at=0, rows=[])
    item = be.edition_items(date(2026, 10, 4))[0]
    assert item["sections"]["next"] == ["The council will meet on Monday, the minister said."]
    assert "extras_dropped" not in item




# ═══ Counsel's ruling adopting the owner's prompt-first decision (3 Oct) ═══

# The single editor lane
@pytest.mark.parametrize("bullets", [
    ["Peter Obi said he would reinstate the subsidy after curbing corruption.", "He spoke in Lagos."],
    ["Gunmen abducted 20 corps members in Imo, the police said.", "The Imo State Police Command said it was investigating the abduction."],
    ["Troops killed 16 terrorists in Adamawa, according to the military.", "Three soldiers died."],
    ["The ADC named Atiku Abubakar its presidential candidate.", "The party's campaign council has 40 members."],
    ["Police spokesperson Henry Okoye said two suspects were arrested.", "Investigations continue."],
])
def test_routine_items_and_unnamed_proceedings_publish(bullets):
    a = assess("Story", bullets)
    assert a["lane"] == "auto", a["reasons"]


@pytest.mark.parametrize("bullets,term", [
    (["The police arrested Musa Bello, a contractor, in Abuja.", "He was released on bail."], "arrest"),
    (["The EFCC charged Musa Bello with fraud before a court in Abuja.", "He pleaded not guilty."], "charge"),
    (["Manchester City Football Club was charged by the Premier League.", "The club denied wrongdoing."], "charge"),
    (["The council suspended Musa Bello, its treasurer, on Monday.", "He has not commented."], "suspend"),
])
def test_accusations_and_proceedings_about_named_subjects_go_to_the_editor(bullets, term):
    a = assess("Story", bullets)
    assert a["lane"] == "review" and term in a["reasons"][0], a["reasons"]


def test_a_principal_office_holder_makes_it_senior_review():
    a = assess("Suit", ["Atiku Abubakar sued President Bola Tinubu at the Federal High Court.", "The hearing is on Monday."],
               registry=REG + [{"full_name": "Bola Tinubu", "common_name": "Bola Tinubu", "publication_status": "published"}])
    assert a["lane"] == "senior_review"


# Automatic corrections at build
def test_a_failing_headline_is_replaced_by_another_outlets_headline():
    title, bullets, extras, notes, out = be.auto_correct(
        ["BREAKING: Troops kill scores of terrorists in Adamawa", "Military says troops killed 16 terrorists in Adamawa"],
        ["Troops killed 16 terrorists in Adamawa, according to a military statement.", "Weapons were recovered."], {}, "x", REG)
    assert title == "Military says troops killed 16 terrorists in Adamawa" and out is None
    assert notes and notes[0].startswith("headline replaced")


def test_no_passing_headline_leaves_the_item_out():
    src = "Governor Caleb Mutfwang pardoned 130 inmates and commuted four death sentences."
    title, _, _, _, out = be.auto_correct(["Mutfwang pardons 134 prisoners"],
                                          ["Governor Caleb Mutfwang pardoned 130 inmates.", "Four death sentences were commuted."], {}, src, REG)
    assert title is None and out == "no source headline passes the headline checks"


def test_a_bullet_with_a_coverage_word_is_removed_not_the_item():
    title, bullets, _, notes, out = be.auto_correct(
        ["Workers begin warning strike"],
        ["Workers began a three-day warning strike on Friday.", "Federal workers reportedly joined in Niger State.",
         "The union cited the minimum wage."], {}, "Workers began a three-day warning strike. The union cited the minimum wage.", REG)
    assert out is None and len(bullets) == 2 and any("reportedly" in n for n in notes)


def test_fewer_than_two_points_after_corrections_leaves_the_item_out():
    _, _, _, _, out = be.auto_correct(["Strike"], ["Workers reportedly joined.", "Reports from Ondo indicated compliance."], {}, "x", REG)
    assert out == "fewer than two points left after corrections"


def test_only_a_conflicting_party_is_corrected_from_the_registry():
    reg = [{"full_name": "Atiku Abubakar", "common_name": "Atiku Abubakar", "publication_status": "published",
            "party": "ADC", "current_position": "Former"},
           {"full_name": "Nyesom Ezenwo Wike", "common_name": "Nyesom Wike", "publication_status": "published",
            "party": "PDP", "current_position": "Minister of FCT"},
           {"full_name": "Peter Obi", "common_name": "Peter Obi", "publication_status": "published", "party": None, "current_position": None}]
    # The party is swapped; the rest of the descriptor stays; the vague position is never inserted.
    text, notes = be.correct_descriptors("Atiku Abubakar, PDP presidential candidate, spoke in Yola.", reg)
    assert text == "Atiku Abubakar, ADC presidential candidate, spoke in Yola." and "corrected" in notes[0]
    text, _ = be.correct_descriptors("Atiku Abubakar, the Peoples Democratic Party flagbearer, spoke.", reg)
    assert text == "Atiku Abubakar, the ADC flagbearer, spoke."
    # Same party (full name or abbreviation): unchanged.
    for s in ("Atiku Abubakar, the ADC presidential candidate, spoke.",
              "Atiku Abubakar, the African Democratic Congress candidate, spoke.",
              "Nyesom Wike, a PDP chieftain, spoke.",
              "Atiku Abubakar, the presidential candidate, spoke.",
              "Atiku Abubakar, a former vice president, spoke in Yola."):
        assert be.correct_descriptors(s, reg) == (s, [])
    # No party in the registry: the descriptor is dropped.
    text, notes = be.correct_descriptors("Peter Obi, the NDC candidate, spoke in Onitsha.", reg)
    assert text == "Peter Obi spoke in Onitsha." and "dropped" in notes[0]


def test_a_reporters_sentence_is_not_a_quote():
    from app.briefing_extras import check_extras
    src = ('Source 1\nSummary: The Special Criminal Court, presided over by Justice Terry Aigbona, handed down the sentence '
           'after a judgment that lasted more than three hours. "Justice has been served," Attorney-General Roland Otaru said.')
    kept, dropped = check_extras({"quotes": [
        {"speaker": "Terry Aigbona", "role": "Judge", "quote": "The Special Criminal Court, presided over by Justice Terry Aigbona, handed down the sentence"},
        {"speaker": "Roland Otaru", "role": "Attorney-General of Edo State", "quote": "Justice has been served,"}]}, src)
    assert [q["speaker"] for q in kept["quotes"]] == ["Roland Otaru"]
    assert "quotation marks" in dropped[0]


def test_only_the_named_second_approver_can_give_the_second_approval(monkeypatch):
    from fastapi import HTTPException
    br, db, updates = editor_setup(monkeypatch, lane="senior_review", actor="Kunle Ade (editorial)")
    approved_row(db)
    with pytest.raises(HTTPException) as e:
        br.approve_item("e1", br.Approval(checklist=ALL_TICKED, no_party_descriptors=True), authorization="Bearer t")
    assert e.value.status_code == 403 and "Enitan Bello" in e.value.detail


def test_an_editor_completes_a_senior_item_the_owner_approved_first(monkeypatch):
    """Order does not matter: the owner signed first, an editor completes the pair."""
    br, db, updates = editor_setup(monkeypatch, lane="senior_review", actor="Toluwalope Ade (editorial)")
    db.tables["briefing_editions"][0].update(approved_by="Enitan Bello (super_admin)", approved_at="2026-10-04T00:00:00Z",
                                             approved_summary_id="s1", approved_edit_at=None, edited_at=None)
    out = br.approve_item("e1", br.Approval(checklist=ALL_TICKED, no_party_descriptors=True), authorization="Bearer t")
    assert out == {"status": "approved", "approved_by": "Toluwalope Ade (editorial)", "second_approved_by": "Enitan Bello (super_admin)"}
    assert updates[-1]["approved_by"] == "Toluwalope Ade (editorial)"
    assert updates[-1]["second_approved_by"] == "Enitan Bello (super_admin)"
    assert db.tables["briefing_edit_log"][-1]["action"] == "approve"


def test_waiting_for_names_who_can_give_the_missing_approval():
    assert be.waiting_for("Enitan Bello (super_admin)") == "an editor other than Enitan Bello"
    assert be.waiting_for("Toluwalope Ade (editorial)") == "Enitan Bello"


def test_everyday_charge_phrases_and_roles_after_a_name_do_not_trigger_the_lane():
    a = assess("Refinery", ["Aliko Dangote, who is in charge of the group, opened the refinery.", "Entry was free of charge."])
    assert a["lane"] == "auto", a["reasons"]
    b = assess("Abduction", ["Henry Okoye, Police Public Relations Officer, said two suspects were arrested.", "Search continues."])
    assert b["lane"] == "auto", b["reasons"]


# Sample review, 4 Oct: corrections that misfired
def test_a_death_sentence_is_not_a_casualty_claim_and_pidgin_headlines_are_skipped():
    assert be.headline_issues("Four kidnappers sentenced to death in Edo", "Four kidnappers were sentenced to death in Edo.") == []
    assert "unattributed casualty claim" in be.headline_issues("Gunmen kill five in Edo", "Gunmen killed five in Edo.")
    assert "not in English" in be.headline_issues(
        "Special court for Edo say make dem kpai convicts by hanging afta Govnor Okpebholo vow - wat next?", "x")


def test_emphasised_is_written_as_said_and_the_bullet_is_kept():
    title, bullets, _, notes, out = be.auto_correct(
        ["Wike vows to resign"], ["Nyesom Wike emphasized his alignment with Bola Tinubu remains unshakable.",
                                 "Nyesom Wike spoke in Port Harcourt."], {}, "Wike spoke in Port Harcourt.", [])
    assert out is None and bullets[0] == "Nyesom Wike said his alignment with Bola Tinubu remains unshakable."
    assert any("said" in n for n in notes)


def test_press_passes_are_not_a_coverage_word():
    assert be.bullet_problem("The order directed the White House to return the press passes of the reporters.", "x") is None
    assert be.bullet_problem("The press focused on the minister's remarks.", "x") is not None


def test_commuted_sentences_and_quoted_slogans_do_not_route_or_raise_to_senior():
    a = assess("Pardons", ["Enugu State Governor Peter Mbah approved the pardon and commutation of sentences of 13 inmates.",
                           "Kogi State Governor Usman Ododo granted clemency to 101 inmates and convicts."])
    assert a["lane"] == "auto", a["reasons"]
    b = assess("Arrests", ["Police in Borno arrested Musa Bello and Ali Kyari for wearing ‘Tinubu Must Go’ T-shirts.",
                           "The two men were remanded."])
    assert b["lane"] == "review", b["reasons"]
    c = assess("Court", ["A court in Abuja heard Atiku Abubakar's suit against Bola Tinubu's election.", "Hearing continues."])
    assert c["lane"] == "senior_review", c["reasons"]
