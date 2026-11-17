import os
import tempfile
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# Set secret before any app/db import
os.environ["SECRET_KEY"] = "c7f4a2b6e1d9f0b8c3d6a1e9b2f7c8d4"

# Use a unique temp DB file per test session
TEST_DB_FD, TEST_DB_PATH = tempfile.mkstemp(suffix=".db")
TEST_DB_URL = f"sqlite:///{TEST_DB_PATH}"
os.environ["DATABASE_URL"] = TEST_DB_URL

from api_server import app
from db.database import Base, SessionLocal
from db import models

def pytest_sessionfinish(session, exitstatus):
    # Ensure temp file is deleted at end
    try:
        os.close(TEST_DB_FD)
        os.remove(TEST_DB_PATH)
    except Exception:
        pass

@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    import db.database
    db.database.SessionLocal = TestingSessionLocal
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()

@pytest.fixture(scope="session")
def seeded_data(setup_test_db):
    from db.database import SessionLocal
    db = SessionLocal()
    data = seed_minimal_data(db)
    db.close()
    return data

@pytest.fixture(scope="function")
def db_session():
    from db.database import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture(scope="module")
def api_client(setup_test_db):
    client = TestClient(app)
    yield client
    client.__exit__()

def seed_minimal_data(db):
    product = models.Product(name="TestProd", version="1.0")
    db.add(product)
    db.commit()
    db.refresh(product)

    client = models.Client(name="TestClient", email="client@example.com")
    db.add(client)
    db.commit()
    db.refresh(client)

    from security import create_license_key, hash_license_key
    license_key = create_license_key()
    hashed_key = hash_license_key(license_key)
    license = models.License(
        license_key=hashed_key,
        product_id=product.product_id,
        client_id=client.client_id,
        status="active",
        max_activations=1
    )
    db.add(license)
    db.commit()
    db.refresh(license)

    api_key = models.ApiKey(api_key="test-api-key", name="test", key_type="client", is_active=True)
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    return {
        "product": product,
        "client": client,
        "license": license,
        "license_key": license_key,
        "api_key": api_key.api_key
    }
