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


def test_headline_allegation_term_missing_from_body_leaves_item_out():
    a = assess("Alleged forgery: Court fixes date for motion", ["The court fixed 12 October for the motion.", "Lawyers for both parties appeared."])
    assert a["lane"] == "left_out" and "alleged" in a["reasons"][0]
    ok = assess("Alleged forgery: Court fixes date", ["The court fixed a date in the alleged forgery case.", "Lawyers appeared."])
    assert ok["lane"] != "left_out"


def test_gate_runs_over_headline_and_body():
    # Adverse term only in the headline, no anchor: the cleared gate suppresses.
    assert assess("Minister accused of fraud")["lane"] == "left_out"
    # Adverse term in the headline with a court anchor in the body: review.
    a = assess("Fraud trial: judge adjourns case", ["The judge adjourned the fraud case to November.", "The court sat in Abuja."])
    assert a["lane"] == "review"


# Item 2: political review lane (narrowed by counsel's ruling, 3 Oct)
@pytest.mark.parametrize("title,bullets", [
    ("Governor opens new school", ["The governor opened a new school in Ibadan on Monday.", "Pupils attended."]),
    ("NIPOST launches digital postcode", ["The Minister of Communications launched the postcode system.", "It covers all buildings."]),
    ("Akpabio salutes Nigerians at 66", ["Senate President Godswill Akpabio congratulated Nigerians on the 66th anniversary.", "He urged unity."]),
    ("NECO releases results", ["NECO said 804,948 candidates obtained five credits.", "The minister of education commended the council."]),
])
def test_routine_political_items_publish_automatically(title, bullets):
    a = assess(title, bullets, registry=REG + [{"full_name": "Godswill Akpabio", "common_name": "Godswill Akpabio", "publication_status": "published"}])
    assert a["lane"] == "auto", a["reasons"]


@pytest.mark.parametrize("title,bullets,trigger", [
    ("ADC names campaign council", ["Atiku Abubakar named the ADC campaign council on Thursday.", "The council has 40 members."], "campaign"),
    ("Speaker urges re-election", ["Atiku Abubakar urged members of the ADC to re-elect the party leadership.", "Delegates met in Abuja."], "re-elect"),
    ("Atiku tackles Tinubu", ["Atiku Abubakar criticised Bola Tinubu over the economy.", "He spoke in Yola."], "criticised"),
    ("President returns", ["Bola Tinubu said he was healthy and ready to resume duties.", "He landed in Lagos."], "healthy"),
])
def test_political_items_with_a_trigger_are_held(title, bullets, trigger):
    reg = REG + [{"full_name": "Bola Tinubu", "common_name": "Bola Tinubu", "publication_status": "published"}]
    a = assess(title, bullets, registry=reg)
    assert a["lane"] == "review"
    assert any(r.startswith("political review lane") and trigger in r for r in a["reasons"]), a["reasons"]


def test_ruled_out_and_ruling_party_are_not_court_items():
    a = assess("President rules out subsidy", ["President Bola Tinubu ruled out a return to petrol subsidies.", "The ruling party backed him."])
    assert not any(r.startswith("court or adjudication") for r in a["reasons"])


def test_court_items_about_named_people_or_companies_are_held():
    a = assess("Court fixes hearing date", ["The Federal High Court fixed October 13 for the hearing of Musa Bello's suit.", "Lawyers appeared."])
    assert any(r.startswith("court or adjudication") for r in a["reasons"])
    b = assess("Manchester City appeal", ["Manchester City will appeal the verdict of the independent commission.", "The club issued a statement."])
    assert any(r.startswith("court or adjudication") for r in b["reasons"])


# Item 3: headline checks
@pytest.mark.parametrize("title,bullets,reason", [
    ("Troops kill scores of terrorists in Adamawa",
     ["Troops neutralised 16 terrorists in Adamawa, according to a military statement.", "Weapons were recovered."],
     "headline quantity word not in body: scores"),
    ("Mutfwang pardons 134 prisoners",
     ["Governor Caleb Mutfwang pardoned 130 inmates and commuted four death sentences.", "The governor's office announced it."],
     "headline number not in body: 134"),
    ("Gunmen kill 5 in Benue", ["Gunmen killed 5 villagers in Benue, the police said.", "Residents fled."],
     "unattributed casualty claim in headline"),
])
def test_headline_checks_route_to_review(title, bullets, reason):
    a = assess(title, bullets)
    assert a["lane"] == "review" and reason in a["reasons"], a["reasons"]


def test_attributed_casualty_headline_passes():
    a = assess("Military says troops killed 16 terrorists in Adamawa",
               ["Troops killed 16 terrorists in Adamawa, according to a military statement.", "Weapons were recovered."])
    assert a["lane"] == "auto", a["reasons"]


def test_non_political_neutral_item_is_auto():
    assert assess("Rail line approved")["lane"] == "auto"


# Item 3: automatic checks
def test_surname_alone_without_full_name_goes_to_review():
    a = assess("Party names campaign team", ["The party announced its campaign team.", "Shaibu stated that the team would start work on Monday."])
    assert "named by one name only: Shaibu" in a["reasons"]
    ok = assess("Party names campaign team", ["Simon Bagaiya Shaibu, the party spokesman, announced the team.", "Shaibu said work starts on Monday."])
    assert not any(r.startswith("named by one name only") for r in ok["reasons"])


def test_headline_name_must_appear_in_full_in_the_body():
    a = assess("Atiku names Akobundu campaign DG", ["Senator Augustine Akobundu was named Director-General.", "Akobundu will coordinate the campaign."])
    assert "named by one name only: Atiku" in a["reasons"]


def test_organisations_are_not_treated_as_surnames():
    a = assess("Manchester City appeal ruling", ["Manchester City Football Club filed an appeal.", "City lawyers spoke to the panel."])
    assert not any(r.startswith("named by one name only") for r in a["reasons"])


def test_reported_speech_naming_a_person_goes_to_review():
    a = assess("Rail line approved", ["Atiku Abubakar opposed the plan, according to reports.", "Construction starts in January."])
    assert any(r.startswith("reported speech") for r in a["reasons"])


@pytest.mark.parametrize("bullet", [
    "Atiku Abubakar reportedly opposed the plan.",
    "Guinea-Bissau won 3-0, according to match reports.",
    "Reports from Ondo indicated partial compliance.",
])
def test_bare_reported_phrases_are_caught_by_the_coverage_check(bullet):
    # Counsel, 3 Oct 2026: added to the coverage checks, so the item is left out.
    a = assess("Rail line approved", [bullet, "Construction starts in January."])
    assert a["lane"] == "left_out" and "forbidden_coverage" in a["reasons"][0]


@pytest.mark.parametrize("bullet", [
    "The arraignment marked a significant development.",
    "The decision underscores the government's priorities.",
    "The statement links the minister to the contract.",
])
def test_commentary_goes_to_review(bullet):
    a = assess("Rail line approved", [bullet, "Construction starts in January."])
    assert a["lane"] == "review" and any(r.startswith("commentary") for r in a["reasons"])


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
    db.tables["cluster_summaries"][0]["bullets"] = ["APC officials met in Abuja to choose a presidential candidate.", "The meeting lasted two hours."]
    monkeypatch.setattr(be, "supabase", db)
    monkeypatch.setattr(be, "cluster_articles_text", lambda cid: "APC officials met in Abuja to choose a presidential candidate.")
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


# Owner's direction, 3 Oct: checks follow counsel's wording, not wider.
@pytest.mark.parametrize("bullet", [
    "Governors pardoned inmates, marking the 66th Independence anniversary.",
    "The company recorded receivables largely linked to energy security costs.",
    "Officials marked the day with a parade.",
])
def test_plain_reporting_is_not_commentary(bullet):
    a = assess("Rail line approved", [bullet, "Construction starts in January."])
    assert not any(r.startswith("commentary") for r in a["reasons"])


@pytest.mark.parametrize("bullets", [
    ["NECO released the 2026 SSCE results on Thursday.", "Candidates in Kano led the results."],
    ["Five men were held for wearing 'Tinubu Must Go' T-shirts, the police said.", "They were remanded."],
    ["Nigeria leads the region, according to Prof. Peter A. Okebukola, the committee chairman.", "Rankings rose."],
])
def test_acronyms_initials_and_common_nouns_are_not_surnames(bullets):
    a = assess("Results released", bullets)
    assert not any(r.startswith("named by one name only") for r in a["reasons"])


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
    monkeypatch.setattr(br, "cluster_articles_text", lambda cid: 'Source 1\nSummary: The minister said "work starts in January".')
    with pytest.raises(HTTPException) as e:
        br.rewrite_item("e1", br.Rewrite(sections={"quotes": [{"speaker": "Ada Obi", "role": "Minister", "quote": "work starts soon"}]}),
                        authorization="Bearer t")
    assert e.value.status_code == 422 and "verbatim" in e.value.detail
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
