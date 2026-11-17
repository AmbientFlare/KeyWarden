import pytest
from fastapi.testclient import TestClient
from tests.conftest import seeded_data
from api_server import app

client = TestClient(app)

@pytest.fixture(scope="module")
def api_client():
    """Test client for FastAPI app"""
    return client


def test_validate_missing_api_key(api_client):
    """Ensure validation endpoint rejects missing API key"""
    response = api_client.post(
        "/api/v1/validate",
        json={"license_key": "INVALID-KEY"},
    )
    assert response.status_code == 401


def test_activate_missing_api_key(api_client):
    """Ensure activation endpoint rejects missing API key"""
    response = api_client.post(
        "/api/v1/activate",
        json={"license_key": "INVALID-KEY"},
    )
    assert response.status_code == 401


def test_validate_success(seeded_data, api_client):
    """Test successful license validation"""
    headers = {"X-API-Key": seeded_data["api_key"]}
    response = api_client.post(
        "/api/v1/validate",
        json={"license_key": seeded_data["license_key"]},
        headers=headers
    )
    assert response.status_code == 200
    assert response.json().get("valid") is True


def test_activate_success(seeded_data, api_client):
    headers = {"X-API-Key": seeded_data["api_key"]}
    payload = {
        "license_key": seeded_data["license_key"],
        "hardware_id": "HWID-123",
        "ip_address": "127.0.0.1",
        "user_agent": "pytest-client",
        "system_info": {"os": "Windows", "version": "10"}
    }
    response = api_client.post(
        "/api/v1/activate",
        json=payload,
        headers=headers
    )
    assert response.status_code == 200
    assert response.json().get("success") is True
