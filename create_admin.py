import os
from supabase import create_client

url = os.environ.get("SUPABASE_URL", "https://yqqysehsnwicppejgfky.supabase.co")
key = os.environ.get("SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InlxcXlzZWhzbndpY3BwZWpnZmt5Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MDYwMTA3NSwiZXhwIjoyMDk2MTc3MDc1fQ.S9tdHJE962ox5tq1EwFKm3pINbSYmK1EMVdyONQC0_g")
supabase = create_client(url, key)

try:
    res = supabase.auth.admin.create_user({
        "email": "testadmin99@tracenews.ng",
        "password": "password123!",
        "email_confirm": True
    })
    user_id = res.user.id
    print("Created user:", user_id)
    
    # Wait for trigger to create profile
    import time
    time.sleep(2)
    
    supabase.table("profiles").update({"is_staff": True}).eq("id", user_id).execute()
    print("Marked as staff!")
except Exception as e:
    print(e)
