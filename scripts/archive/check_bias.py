import sys
from app.db import supabase

res = supabase.table("story_bias_tags").select("*").limit(5).execute()
if not res.data:
    print("Table is empty.")
else:
    for row in res.data:
        print(row)
