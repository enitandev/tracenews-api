import sys
from app.db import supabase

res = supabase.table("story_bias_tags").select("*").limit(1).execute()
print("Connected successfully. Fetching triggers from pg_class/pg_trigger...")

# Unfortunately supabase client doesn't support raw SQL easily unless there's an RPC.
# Let me just check if there is an RPC that does it.
