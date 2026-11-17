#  db_models.py
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, DateTime, JSON, Text, Index
from sqlalchemy.orm import relationship
from datetime import datetime

from .database import Base

class License(Base):
    __tablename__ = "licenses"

    license_id = Column(Integer, primary_key=True, index=True)
    license_key = Column(String, unique=True, index=True, nullable=False)
    product_id = Column(Integer, ForeignKey("products.product_id"))
    client_id = Column(Integer, ForeignKey("clients.client_id"))
    status = Column(String, default="active")  # active, expired, revoked
    activation_count = Column(Integer, default=0)
    max_activations = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    features = Column(JSON, nullable=True)
    
    # Relationships
    product = relationship("Product", back_populates="licenses")
    client = relationship("Client", back_populates="licenses")
    activations = relationship("Activation", back_populates="license")


class Activation(Base):
    __tablename__ = "activations"

    activation_id = Column(Integer, primary_key=True, index=True)
    license_id = Column(Integer, ForeignKey("licenses.license_id"))
    hardware_id = Column(String, index=True)
    ip_address = Column(String)
    user_agent = Column(String, nullable=True)
    system_info = Column(JSON, nullable=True)
    first_activated = Column(DateTime, default=datetime.utcnow)
    last_check_in = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    # Relationships
    license = relationship("License", back_populates="activations")


class Product(Base):
    __tablename__ = "products"

    product_id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    version = Column(String)
    features = Column(JSON, nullable=True)
    
    # License settings - new fields
    default_max_activations = Column(Integer, default=1)
    license_key_format = Column(String, default="XXXX-XXXX-XXXX-XXXX")
    heartbeat_interval = Column(Integer, default=24)  # in hours
    auto_deactivate_days = Column(Integer, default=30)
    enforce_hardware_check = Column(Boolean, default=True)
    
    # Relationships
    licenses = relationship("License", back_populates="product")


class Client(Base):
    __tablename__ = "clients"

    client_id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    email = Column(String)
    company = Column(String, nullable=True)
    contact_info = Column(JSON, nullable=True)
    
    # Relationships
    licenses = relationship("License", back_populates="client")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    log_id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    action = Column(String)
    entity_type = Column(String)  # "license", "activation", etc.
    entity_id = Column(Integer)
    user_id = Column(Integer, nullable=True)
    ip_address = Column(String, nullable=True)
    details = Column(JSON, nullable=True)

class SystemSettings(Base):
    __tablename__ = "system_settings"

    setting_id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True)
    value = Column(String)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = {'extend_existing': True}

    key_id = Column(Integer, primary_key=True, index=True)
    api_key = Column(String, unique=True, index=True)
    name = Column(String)
    key_type = Column(String, default="client", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)