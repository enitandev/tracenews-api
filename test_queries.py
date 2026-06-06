from app.db import supabase

res1 = supabase.table("clusters").select("id", count="exact").gte("outlet_count", 2).execute()
print(f"Clusters with outlet_count >= 2: {res1.count}")

res2 = supabase.table("clusters").select("id", count="exact").eq("outlet_count", 1).execute()
print(f"Clusters with outlet_count = 1: {res2.count}")
