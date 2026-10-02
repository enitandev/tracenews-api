from app.daily_briefing import select_eligible_briefing_clusters


def cluster(cid, dist, image=True, article_rows=50):
    return {"id": cid, "outlet_count": article_rows,
            "coverage_stats": {"coverage_tier_distribution": dist} if dist is not None else None,
            "stories": [{"image_url": "https://img/x.jpg" if image else None}]}


def ids(clusters):
    return [c["id"] for c in select_eligible_briefing_clusters(clusters)]


def test_floor_is_distinct_outlets_not_article_rows():
    # 50 articles from 2 outlets: passed the old article-row floor, fails now.
    assert ids([cluster("a", {"govt_aligned": 1, "mainstream": 1, "watchdog": 0})]) == []
    assert ids([cluster("b", {"govt_aligned": 2, "mainstream": 2, "watchdog": 1})]) == ["b"]


def test_blogs_do_not_count_toward_the_floor():
    assert ids([cluster("a", {"mainstream": 3, "watchdog": 1, "blog": 5})]) == []


def test_unknown_distinct_count_is_not_eligible():
    assert ids([cluster("a", None), cluster("b", {"Institutional": 9})]) == []


def test_needs_an_image():
    assert ids([cluster("a", {"mainstream": 5}, image=False)]) == []


def test_ranked_by_distinct_count_and_capped_at_nine():
    clusters = [cluster(f"c{n}", {"mainstream": n}) for n in range(5, 17)]
    picked = ids(clusters)
    assert picked == [f"c{n}" for n in range(16, 7, -1)]
