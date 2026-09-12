import os
import uuid
import requests
import time
from app.db import supabase

test_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
test_password = "testpass123"
print(f"--- 1 & 2. Creating user {test_email} and getting Session Token ---")
print("Note: Supabase rate limits email signups (3 per hour), so bypassing via admin API...")

user_res = supabase.auth.admin.create_user({
    "email": test_email,
    "password": test_password,
    "email_confirm": True
})
user_id = user_res.user.id

# Create profile manually since we bypassed the signup endpoint
supabase.table("profiles").insert({
    "id": user_id,
    "age_assertion": True
}).execute()

auth_res = supabase.auth.sign_in_with_password({"email": test_email, "password": test_password})
session_token = auth_res.session.access_token
print("Successfully obtained session token for user:", user_id)

print("\n--- 3. Calling REAL DELETE /api/auth/account via Railway endpoint ---")
del_res = requests.delete(
    "https://uvicorn-appmain-production-79c6.up.railway.app/api/auth/account",
    headers={"Authorization": f"Bearer {session_token}"}
)
print("Delete Response Status:", del_res.status_code)
print("Delete Response Body:", del_res.text)

print("\n--- 4. Confirming the profile is gone ---")
prof_res = supabase.table("profiles").select("*").eq("id", user_id).execute()
print("Should be empty:", prof_res.data)
if len(prof_res.data) == 0:
    print("SUCCESS: Profile successfully cascaded from REAL endpoint.")
else:
    print("FAILURE: Profile still exists.")
