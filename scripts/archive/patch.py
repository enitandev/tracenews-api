import re

# 1 & 2: admin_overview.py
with open("app/routers/admin_overview.py", "r") as f:
    code = f.read()
code = code.replace(
    'supabase.table("politicians").select("id", count="exact").eq("publication_status", "held").execute()',
    'supabase.table("politicians").select("id", count="exact").eq("publication_status", "pending_review").execute()'
)
code = code.replace(
    'supabase.table("correction_requests").select("id, type, outlet_slug, created_at")',
    'supabase.table("correction_requests").select("id, category, subject_id, created_at")'
)
with open("app/routers/admin_overview.py", "w") as f:
    f.write(code)
print("Updated admin_overview.py")
