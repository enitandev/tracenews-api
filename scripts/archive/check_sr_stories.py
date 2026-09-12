import json
from app.db import supabase
res = supabase.table("stories").select("title").eq("outlet_id", (supabase.table("outlets").select("id").eq("slug", "sahara-reporters").execute().data[0]["id"])).limit(10).execute()
print(json.dumps(res.data, indent=2))
