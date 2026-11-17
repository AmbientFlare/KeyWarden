# db_schemas.py
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

# License schemas
class LicenseBase(BaseModel):
    product_id: int
    client_id: int
    status: str = "active"
    max_activations: int = 1
    expires_at: Optional[datetime] = None
    features: Optional[Dict[str, Any]] = None

class LicenseCreate(LicenseBase):
    pass

class LicenseUpdate(BaseModel):
    product_id: Optional[int] = None
    client_id: Optional[int] = None
    status: Optional[str] = None
    max_activations: Optional[int] = None
    expires_at: Optional[datetime] = None
    features: Optional[Dict[str, Any]] = None

class License(LicenseBase):
    license_id: int
    license_key: str
    activation_count: int
    created_at: datetime

    class Config:
        from_attributes = True

class LicenseDetail(License):
    activations: List['Activation']

    class Config:
        from_attributes = True

# Activation schemas
class ActivationBase(BaseModel):
    hardware_id: str
    ip_address: str
    user_agent: Optional[str] = None
    system_info: Optional[Dict[str, Any]] = None

class ActivationCreate(ActivationBase):
    license_id: int

class Activation(ActivationBase):
    activation_id: int
    license_id: int
    first_activated: datetime
    last_check_in: datetime
    is_active: bool

    class Config:
        from_attributes = True

# Client schemas
class ClientBase(BaseModel):
    name: str
    email: str
    company: Optional[str] = None
    contact_info: Optional[Dict[str, Any]] = None

class ClientCreate(ClientBase):
    pass

class Client(ClientBase):
    client_id: int

    class Config:
        from_attributes = True

# Product schemas
class ProductBase(BaseModel):
    name: str
    version: str
    features: Optional[Dict[str, Any]] = None
    default_max_activations: int = 1
    license_key_format: str = "XXXX-XXXX-XXXX-XXXX"
    heartbeat_interval: int = 24
    auto_deactivate_days: int = 30
    enforce_hardware_check: bool = True

class ProductCreate(ProductBase):
    pass

class Product(ProductBase):
    product_id: int

    class Config:
        from_attributes = True

# API schemas for the license API
class LicenseValidationRequest(BaseModel):
    license_key: str
    hardware_id: Optional[str] = None
    system_info: Optional[Dict[str, Any]] = None

class LicenseValidation(BaseModel):
    valid: bool
    reason: Optional[str] = None
    product_id: Optional[int] = None
    expires_at: Optional[datetime] = None
    features: Optional[Dict[str, Any]] = None

class ActivationRequest(BaseModel):
    license_key: str
    hardware_id: Optional[str] = None
    ip_address: str
    user_agent: Optional[str] = None
    system_info: Optional[Dict[str, Any]] = None

class ActivationResponse(BaseModel):
    success: bool
    activation_id: Optional[int] = None
    message: str

class DeactivationRequest(BaseModel):
    license_key: str
    hardware_id: Optional[str] = None
    system_info: Optional[Dict[str, Any]] = None

class DeactivationResponse(BaseModel):
    success: bool
    message: str

class HeartbeatRequest(BaseModel):
    activation_id: int
    hardware_id: Optional[str] = None
    system_info: Optional[Dict[str, Any]] = None

class HeartbeatResponse(BaseModel):
    valid: bool
    message: str
    
# Report schemas
class UsageReport(BaseModel):
    total_licenses: int
    active_licenses: int
    total_activations: int
    active_activations: int
    activation_history: List[Dict[str, Any]]

# General response schemas
class DeleteResponse(BaseModel):
    success: bool
    message: str

