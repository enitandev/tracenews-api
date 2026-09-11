import urllib.request
import json
import ssl
from collections import defaultdict

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def fetch(url):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, context=ctx) as response:
        return json.loads(response.read().decode())

landing = fetch('https://uvicorn-appmain-production-79c6.up.railway.app/clusters/landing?limit=15')
feed = fetch('https://uvicorn-appmain-production-79c6.up.railway.app/clusters/feed?offset=15&limit=65')

clusters = landing.get('clusters', []) + feed.get('clusters', [])

categories = defaultdict(list)
for c in clusters:
    cat = c.get('category') or 'General'
    categories[cat].append(c)

valid_categories = ["Politics", "Security", "Economy", "Health", "International", "Sports", "Entertainment"]

print("Category | Breadth Cards (>= 3 scored outlets) | Total in Feed")
print("-" * 65)

for cat in valid_categories:
    cat_stories = categories.get(cat, [])
    scored_stories = []
    for c in cat_stories:
        dist = c.get('coverage_stats', {}).get('coverage_tier_distribution', {})
        g = dist.get('govt_aligned', dist.get('pro_establishment', 0))
        m = dist.get('mainstream', dist.get('institutional', 0))
        w = dist.get('watchdog', dist.get('adversarial', 0))
        if g + m + w >= 3:
            scored_stories.append(c)
    print(f"{cat:<12} | {len(scored_stories):<43} | {len(cat_stories)}")

