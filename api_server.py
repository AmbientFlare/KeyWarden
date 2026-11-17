# api_server.py - Entry point for the application
from fastapi import FastAPI, Depends, HTTPException, Security, status, Request
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import uvicorn
import logging
import traceback
import os
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import secrets
import hashlib
import jwt
from pydantic import BaseModel



# Local modules
from db import models, crud, schemas
from db.database import engine, SessionLocal
from security import authenticate, create_license_key, verify_license_key, get_hardware_fingerprint

# Create database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="License Server API", version="1.0.0")

# Configure CORS to allow only local access for the admin interface
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency to get the database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Redis client
logger = logging.getLogger(__name__)
redis_client = None
try:
    import redis.asyncio as aioredis
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        redis_client = aioredis.from_url(redis_url)
except ImportError:
    logger.warning("aioredis not available, falling back to database for idempotency")
except Exception as e:
    logger.error(f"Error initializing Redis: {e}")

# Auth middleware
API_KEY_HEADER = APIKeyHeader(name="X-API-Key")

async def get_client_api_key(api_key: str = Security(API_KEY_HEADER), db: Session = Depends(get_db)):
    """Verify API key for client software operations"""
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is missing"
        )
    
    # Verify API key in the database (must be client type or admin type)
    valid_client = crud.validate_api_key(db, api_key, "client")
    valid_admin = crud.validate_api_key(db, api_key, "admin")  # Admin keys can also access client endpoints
    
    if not (valid_client or valid_admin):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key for client operations"
        )
    return api_key

async def get_admin_api_key(api_key: str = Security(API_KEY_HEADER), db: Session = Depends(get_db)):
    """Verify API key for admin operations"""
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is missing"
        )
    
    # Verify API key in the database (must be admin type)
    valid = crud.validate_api_key(db, api_key, "admin")
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key for admin operations"
        )
    return api_key

# Client Software API Endpoints
@app.post("/api/v1/validate", response_model=schemas.LicenseValidation)
async def validate_license(
    request: schemas.LicenseValidationRequest,
    db: Session = Depends(get_db),
    api_key: str = Depends(get_client_api_key)  # Changed here
):
    """Validate a license key without activating it"""
    license_data = crud.get_license_by_key(db, request.license_key)
    
    if not license_data:
        return schemas.LicenseValidation(valid=False, reason="License key not found")
    
    if license_data.status != "active":
        return schemas.LicenseValidation(valid=False, reason=f"License is {license_data.status}")
    
    if license_data.expires_at and license_data.expires_at < datetime.utcnow():
        crud.update_license_status(db, license_data.license_id, "expired")
        return schemas.LicenseValidation(valid=False, reason="License expired")
    
    return schemas.LicenseValidation(
        valid=True,
        product_id=license_data.product_id,
        expires_at=license_data.expires_at,
        features=license_data.features
    )
@app.post("/api/v1/activate", response_model=schemas.ActivationResponse)
async def activate_license(
    request: schemas.ActivationRequest,
    db: Session = Depends(get_db),
    api_key: str = Depends(get_client_api_key)
):
    """Activate a license on a device"""
    license_data = crud.get_license_by_key(db, request.license_key)
    
    if not license_data:
        raise HTTPException(status_code=404, detail="License key not found")
    
    if license_data.status != "active":
        raise HTTPException(status_code=400, detail=f"License is {license_data.status}")
    
    if license_data.expires_at and license_data.expires_at < datetime.utcnow():
        crud.update_license_status(db, license_data.license_id, "expired")
        raise HTTPException(status_code=400, detail="License expired")
    
    # Check activation count
    active_activations = crud.get_active_activations_count(db, license_data.license_id)
    if active_activations >= license_data.max_activations:
        raise HTTPException(status_code=400, detail="Maximum activations reached")
    
    # Generate or use provided hardware ID
    hardware_id = request.hardware_id or get_hardware_fingerprint(request.system_info or {})
    
    # Check for existing activation
    existing_activation = crud.get_activation_by_hardware_id(db, license_data.license_id, hardware_id)
    
    if existing_activation:
        if existing_activation.is_active:
            return schemas.ActivationResponse(
                success=True,
                activation_id=existing_activation.activation_id,
                message="Already activated on this device"
            )
        else:
            # Reactivate existing activation
            crud.reactivate_license(db, existing_activation.activation_id)
            return schemas.ActivationResponse(
                success=True,
                activation_id=existing_activation.activation_id,
                message="License reactivated"
            )
    
    # Create new activation with hardware ID
    activation = crud.create_activation(
        db, 
        license_id=license_data.license_id,
        hardware_id=hardware_id,  # Use the generated/provided hardware ID
        ip_address=request.ip_address,
        user_agent=request.user_agent,
        system_info=request.system_info
    )
    
    # Update license activation count
    crud.increment_activation_count(db, license_data.license_id)
    
    return schemas.ActivationResponse(
        success=True,
        activation_id=activation.activation_id,
        message="License activated successfully"
    )

@app.post("/api/v1/deactivate", response_model=schemas.DeactivationResponse)
async def deactivate_license(
    request: schemas.DeactivationRequest,
    db: Session = Depends(get_db),
    api_key: str = Depends(get_client_api_key)
):
    """Deactivate a license on a device"""
    # Detailed logging
    print("Deactivation Request:")
    print(f"License Key: {request.license_key}")
    print(f"System Info: {request.system_info}")
    print(f"Hardware ID: {request.hardware_id}")

    license_data = crud.get_license_by_key(db, request.license_key)
    
    if not license_data:
        print(f"License not found: {request.license_key}")
        raise HTTPException(status_code=404, detail="License key not found")
    
    # Generate hardware fingerprint if not provided
    hardware_id = request.hardware_id or get_hardware_fingerprint(request.system_info or {})
    print(f"Generated/Received Hardware ID: {hardware_id}")

    # Find active activations for this license
    active_activations = db.query(models.Activation).filter(
        models.Activation.license_id == license_data.license_id,
        models.Activation.is_active == True
    ).all()
    
    if not active_activations:
        print(f"No active activations found for license {license_data.license_id}")
        raise HTTPException(status_code=404, detail="No active license activations found")
    
    # If only one active activation, deactivate it
    if len(active_activations) == 1:
        activation = active_activations[0]
    else:
        # Try to find an activation matching the hardware ID
        activation = next(
            (act for act in active_activations if act.hardware_id == hardware_id), 
            active_activations[0]
        )
    
    # Deactivate
    crud.deactivate_license(db, activation.activation_id)
    
    return schemas.DeactivationResponse(
        success=True,
        message="License deactivated successfully"
    )

@app.post("/api/v1/heartbeat", response_model=schemas.HeartbeatResponse)
async def heartbeat(
    request: schemas.HeartbeatRequest,
    db: Session = Depends(get_db),
    api_key: str = Depends(get_client_api_key)
):
    """Regular check-in from activated software"""
    activation = crud.get_activation_by_id(db, request.activation_id)
    
    if not activation:
        raise HTTPException(status_code=404, detail="Activation not found")
    
    if not activation.is_active:
        return schemas.HeartbeatResponse(
            valid=False,
            message="License is no longer active"
        )
    
    # Get license
    license_data = crud.get_license_by_id(db, activation.license_id)
    if not license_data:
        return schemas.HeartbeatResponse(
            valid=False,
            message="License not found"
        )
    
    # Get product for settings
    product = crud.get_product_by_id(db, license_data.product_id)
    if not product:
        return schemas.HeartbeatResponse(
            valid=False,
            message="Product not found"
        )
    
    if license_data.status != "active":
        return schemas.HeartbeatResponse(
            valid=False,
            message=f"License is {license_data.status}"
        )
    
    if license_data.expires_at and license_data.expires_at < datetime.utcnow():
        crud.update_license_status(db, license_data.license_id, "expired")
        return schemas.HeartbeatResponse(
            valid=False,
            message="License expired"
        )
    
    # Check if auto-deactivation is enabled and if activation has been inactive for too long
    if product.auto_deactivate_days > 0:
        inactive_threshold = datetime.utcnow() - timedelta(days=product.auto_deactivate_days)
        if activation.last_check_in < inactive_threshold:
            crud.deactivate_license(db, activation.activation_id)
            return schemas.HeartbeatResponse(
                valid=False,
                message=f"Activation automatically deactivated after {product.auto_deactivate_days} days of inactivity"
            )
    
    # Verify hardware ID if required and provided
    if product.enforce_hardware_check and request.hardware_id and activation.hardware_id != request.hardware_id:
        # Hardware has changed - potential license transfer attempt
        return schemas.HeartbeatResponse(
            valid=False,
            message="Hardware validation failed"
        )
    
    # Update last_check_in
    crud.update_activation_check_in(db, activation.activation_id)
    
    # Calculate next heartbeat time
    next_heartbeat = datetime.utcnow() + timedelta(hours=product.heartbeat_interval)
    
    return schemas.HeartbeatResponse(
        valid=True,
        message=f"License is valid. Next heartbeat due by {next_heartbeat.strftime('%Y-%m-%d %H:%M:%S')}"
    )

# Admin API Endpoints
@app.get("/api/v1/admin/licenses", response_model=List[schemas.License])
async def get_licenses(
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db),
    api_key: str = Depends(get_admin_api_key)
):
    """Get all licenses with pagination"""
    licenses = crud.get_licenses(db, skip=skip, limit=limit)
    return licenses

@app.post("/api/v1/admin/licenses", response_model=schemas.License)
async def create_license(
    license_data: schemas.LicenseCreate, 
    db: Session = Depends(get_db),
    api_key: str = Depends(get_admin_api_key)
):
    """Create a new license"""
    # Get product to use its license key format
    product = crud.get_product_by_id(db, license_data.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Generate a secure license key with product-specific format
    license_key = create_license_key(product.license_key_format)
    
    # Create license in database
    new_license = crud.create_license(db, license_data, license_key)
    return new_license

@app.get("/api/v1/admin/licenses/{license_id}", response_model=schemas.LicenseDetail)
async def get_license(
    license_id: int, 
    db: Session = Depends(get_db),
    api_key: str = Depends(get_admin_api_key)
):
    """Get detailed information about a license"""
    license_data = crud.get_license_by_id(db, license_id)
    if not license_data:
        raise HTTPException(status_code=404, detail="License not found")
    
    # Get activations
    activations = crud.get_activations_by_license(db, license_id)
    
    return schemas.LicenseDetail(
        **license_data.__dict__,
        activations=activations
    )

@app.put("/api/v1/admin/licenses/{license_id}", response_model=schemas.License)
async def update_license(
    license_id: int, 
    license_data: schemas.LicenseUpdate,
    db: Session = Depends(get_db),
    api_key: str = Depends(get_admin_api_key)
):
    """Update a license"""
    updated_license = crud.update_license(db, license_id, license_data)
    if not updated_license:
        raise HTTPException(status_code=404, detail="License not found")
    return updated_license

@app.delete("/api/v1/admin/licenses/{license_id}", response_model=schemas.DeleteResponse)
async def delete_license(
    license_id: int, 
    db: Session = Depends(get_db),
    api_key: str = Depends(get_admin_api_key)
):
    """Delete a license"""
    success = crud.delete_license(db, license_id)
    if not success:
        raise HTTPException(status_code=404, detail="License not found")
    return {"success": True, "message": "License deleted"}

# Client management
@app.get("/api/v1/admin/clients", response_model=List[schemas.Client])
async def get_clients(
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db),
    api_key: str = Depends(get_admin_api_key)
):
    """Get all clients with pagination"""
    clients = crud.get_clients(db, skip=skip, limit=limit)
    return clients

@app.post("/api/v1/admin/clients", response_model=schemas.Client)
async def create_client(
    client_data: schemas.ClientCreate, 
    db: Session = Depends(get_db),
    api_key: str = Depends(get_admin_api_key)
):
    """Create a new client"""
    client = crud.create_client(db, client_data)
    return client

# Product management
@app.get("/api/v1/admin/products", response_model=List[schemas.Product])
async def get_products(
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db),
    api_key: str = Depends(get_admin_api_key)
):
    """Get all products with pagination"""
    products = crud.get_products(db, skip=skip, limit=limit)
    return products

@app.post("/api/v1/admin/products", response_model=schemas.Product)
async def create_product(
    product_data: schemas.ProductCreate, 
    db: Session = Depends(get_db),
    api_key: str = Depends(get_admin_api_key)
):
    """Create a new product"""
    product = crud.create_product(db, product_data)
    return product

# Report endpoint
@app.get("/api/v1/admin/reports/usage", response_model=schemas.UsageReport)
async def get_usage_report(
    product_id: Optional[int] = None,
    client_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
    api_key: str = Depends(get_admin_api_key)
):
    """Get usage report"""
    report = crud.generate_usage_report(
        db, 
        product_id=product_id,
        client_id=client_id,
        start_date=start_date,
        end_date=end_date
    )
    return report

if __name__ == "__main__":
    # Get host from environment or default to 127.0.0.1 for local development
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=1776)