
from fastapi.testclient import TestClient
from app.main import app
from app.routers.auth import get_current_user

# Mock auth
app.dependency_overrides[get_current_user] = lambda: "test-user-123"

client = TestClient(app)

response = client.post("/api/reader/consent", json={"granted": True})
print(f"Status Code: {response.status_code}")
print(f"Response: {response.json()}")
