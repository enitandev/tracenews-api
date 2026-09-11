import os
import requests
from dotenv import load_dotenv

load_dotenv()
url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]

r = requests.get(f"{url}/rest/v1/", headers={"apikey": key, "Authorization": f"Bearer {key}"})
data = r.json()
print("reader_tier_counters:", list(data["definitions"]["reader_tier_counters"]["properties"].keys()))
print("reader_analytics_consent:", list(data["definitions"]["reader_analytics_consent"]["properties"].keys()))
