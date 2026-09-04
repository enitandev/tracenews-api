import os
import requests
from dotenv import load_dotenv

load_dotenv()
url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]

r = requests.get(f"{url}/rest/v1/", headers={"apikey": key, "Authorization": f"Bearer {key}"})
data = r.json()
tables = data.get("definitions", {}).keys()
print("Tables in DB:", list(tables))
