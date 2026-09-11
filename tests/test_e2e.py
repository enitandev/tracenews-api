import os
import uuid
import requests
import time
from app.db import supabase

test_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
test_password = "testpass123"
print(f"1. Signing up {test_email} via production endpoint...")

res = requests.post(
    "https://uvicorn-appmain-production-79c6.up.railway.app/api/auth/signup",
    json={"email": test_email, "password": test_password, "age_assertion": True}
)
print("Signup Response Status:", res.status_code)
data = res.json()
print("Signup Response Body:", data)

user_id = data.get("id")
if not user_id:
    print("FAILED to get user_id from signup!")
    exit(1)

print("\n2. Confirming email via Supabase Admin API...")
admin_res = supabase.auth.admin.update_user_by_id(user_id, email_confirm=True)
print("Email confirmed for:", admin_res.user.id)

print("\n3. Logging in to get session token...")
auth_res = supabase.auth.sign_in_with_password({"email": test_email, "password": test_password})
session_token = auth_res.session.access_token
print("Successfully obtained session token.")

print("\n4. Calling DELETE /api/auth/account via production endpoint...")
del_res = requests.delete(
    "https://uvicorn-appmain-production-79c6.up.railway.app/api/auth/account",
    headers={"Authorization": f"Bearer {session_token}"}
)
print("Delete Response Status:", del_res.status_code)
print("Delete Response Body:", del_res.json())

print("\n5. Verifying cascade deletion...")
prof_res = supabase.table("profiles").select("*").eq("id", user_id).execute()
print("Should be empty:", prof_res.data)
if len(prof_res.data) == 0:
    print("SUCCESS: End-to-end DELETE endpoint successfully cascaded.")
else:
    print("FAILURE: Profile row still exists.")
