"""The Desk overview: which Briefing items are waiting, and for whom."""
from app.routers.admin_desk import briefing_waiting

TOLU, ENITAN = "Toluwalope Bello (editorial)", "Enitan Bello (super_admin)"


def item(i, lane="review", approved_by=None, needs_second=False, publishable=False, left_out=None):
    return {"id": i, "lane": lane, "approved_by": approved_by, "needs_second_approver": needs_second,
            "publishable": publishable, "left_out_by": left_out}


def test_waiting_items_and_whose_turn_it_is():
    items = [
        item("auto", lane="auto", publishable=True),
        item("review-new"),
        item("review-done", approved_by=TOLU, publishable=True),
        item("senior-new", lane="senior_review"),
        item("senior-half-tolu", lane="senior_review", approved_by=TOLU, needs_second=True),
        item("senior-half-enitan", lane="senior_review", approved_by=ENITAN, needs_second=True),
        item("left-out", left_out="system"),
    ]
    waiting, mine = briefing_waiting(items, ENITAN)
    assert [i["id"] for i in waiting] == ["review-new", "senior-new", "senior-half-tolu", "senior-half-enitan"]
    assert [i["id"] for i in mine] == ["review-new", "senior-new", "senior-half-tolu"]
    _, mine_tolu = briefing_waiting(items, TOLU)
    assert [i["id"] for i in mine_tolu] == ["review-new", "senior-new", "senior-half-enitan"]
