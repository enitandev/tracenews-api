import os
from app.db import supabase

res = supabase.table("clusters").select("id, representative_title, category").execute()
print(res.data)
