from app.db import supabase
import uuid

# test inserting a dummy story with embedding
test_id = "e7dbd380-0fb1-4d85-883f-48b1fe997320" # known from previous log
updates = [{"id": test_id, "embedding": [0.0]*1536}]
res = supabase.table("stories").upsert(updates).execute()
print(res)
