import os
os.environ["ADMIN_API_TOKEN"] = "dummy_token"

import uuid
from app.db import supabase

print("--- SCHEMA VERIFICATION ---")
res = supabase.table('profiles').select('id').limit(1).execute()
print("Profiles table exists:", res is getattr(res, '', res)) # Just printing something if no error

print("\n--- APP IMPORTS CLEANLY ---")
import app.main
print("imports OK")

print("\n--- TESTING CASCADE DELETION ---")
test_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
print(f"Creating user {test_email}...")

# Use admin API to create user so we bypass email confirmation
user_res = supabase.auth.admin.create_user({
    "email": test_email,
    "password": "testpass123",
    "email_confirm": True
})
user_id = user_res.user.id
print("Created user:", user_id)

print("Inserting profile...")
supabase.table("profiles").insert({
    "id": user_id,
    "age_assertion": True
}).execute()

prof_res = supabase.table("profiles").select("*").eq("id", user_id).execute()
print("Profile exists before delete:", len(prof_res.data) > 0)

print("Deleting user via admin API (simulating DELETE /api/auth/account)...")
supabase.auth.admin.delete_user(user_id)

prof_res_after = supabase.table("profiles").select("*").eq("id", user_id).execute()
print("Should be empty:", prof_res_after.data)

if len(prof_res_after.data) == 0:
    print("CASCADE TEST PASSED! The profile was automatically deleted when the auth.users row was deleted.")
else:
    print("CASCADE TEST FAILED! The profile row was left orphaned.")
