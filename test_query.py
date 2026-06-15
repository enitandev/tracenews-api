import sys
import os

# Ensure the app module can be found
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.db import supabase

res = supabase.table("clusters").select("id, representative_title, framing_cache").eq("representative_title", "BREAKING: Abducted General dies in captivity").limit(1).execute()
print(res.data)
