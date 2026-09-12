from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

print("\n--- TEST: Signup rejects missing age assertion ---")
resp = client.post("/api/auth/signup", json={
    "email": "test_reject@example.com",
    "password": "testpass123",
    "age_assertion": False
})
print("Expect 400. Got:", resp.status_code)
if resp.status_code == 400:
    print("Test passed.")
else:
    print("Test failed. Response:", resp.json())
