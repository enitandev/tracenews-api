import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from app.db import supabase

res = supabase.table("clusters").select("id, framing_cache").execute()
print([c for c in res.data if c.get('framing_cache')])
