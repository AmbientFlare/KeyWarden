# db_crud.py
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, Dict, Tuple
from . import models, schemas
from security import hash_license_key, create_license_key, generate_api_key
from datetime import datetime, timedelta
import logging
logger = logging.getLogger(__name__)

# License operations
def get_license_by_id(db: Session, license_id: int):
    """Get license by ID"""
    return db.query(models.License).filter(models.License.license_id == license_id).first()

def get_license_by_key(db: Session, license_key: str):
    """Get license by key"""
    # Hash the key for lookup
    hashed = hash_license_key(license_key)
    return db.query(models.License).filter(models.License.license_key == hashed).first()

def get_licenses(db: Session, skip: int = 0, limit: int = 100):
    """Get all licenses with pagination"""
    return db.query(models.License).offset(skip).limit(limit).all()

def get_licenses_filtered(db: Session, status: Optional[str] = None, skip: int = 0, limit: int = 100):
    """Get licenses filtered by status"""
    query = db.query(models.License)
    
    if status:
        query = query.filter(models.License.status == status)
    
    return query.offset(skip).limit(limit).all()

def count_licenses_filtered(db: Session, status: Optional[str] = None):
    """Count licenses filtered by status"""
    query = db.query(func.count(models.License.license_id))
    
    if status:
        query = query.filter(models.License.status == status)
    
    return query.scalar()

def create_license(db: Session, license_data: schemas.LicenseCreate, license_key: str):
    """Create a new license"""
    # Hash license key before storing
    hashed_key = hash_license_key(license_key)
    db_license = models.License(
        license_key=hashed_key,
        product_id=license_data.product_id,
        client_id=license_data.client_id,
        status=license_data.status,
        max_activations=license_data.max_activations,
        expires_at=license_data.expires_at,
        features=license_data.features
    )
    db.add(db_license)
    db.commit()
    db.refresh(db_license)
    # Attach plain key for response only, do NOT persist plaintext
    db_license.plaintext_license_key = license_key
    
    # Log the action (do NOT log plaintext key)
    log_action(
        db,
        action="create",
        entity_type="license",
        entity_id=db_license.license_id,
        details={"license_key_hashed": hashed_key}
    )
    
    return db_license

def update_license(db: Session, license_id: int, license_data: schemas.LicenseUpdate):
    """Update a license"""
    db_license = get_license_by_id(db, license_id)
    if not db_license:
        return None
    
    # Update fields
    if license_data.product_id is not None:
        db_license.product_id = license_data.product_id
    if license_data.client_id is not None:
        db_license.client_id = license_data.client_id
    if license_data.status is not None:
        db_license.status = license_data.status
    if license_data.max_activations is not None:
        db_license.max_activations = license_data.max_activations
    if license_data.expires_at is not None:
        db_license.expires_at = license_data.expires_at
    if license_data.features is not None:
        db_license.features = license_data.features
    
    db.commit()
    db.refresh(db_license)
    
    # Log the action
    log_action(
        db,
        action="update",
        entity_type="license",
        entity_id=license_id,
        details=license_data.dict(exclude_unset=True)
    )
    
    return db_license

def delete_license(db: Session, license_id: int):
    """Delete a license"""
    db_license = get_license_by_id(db, license_id)
    if not db_license:
        return False
    
    # First delete all activations
    activations = get_activations_by_license(db, license_id)
    for activation in activations:
        db.delete(activation)
    
    # Then delete the license
    db.delete(db_license)
    db.commit()
    
    # Log the action
    log_action(
        db,
        action="delete",
        entity_type="license",
        entity_id=license_id
    )
    
    return True

def count_licenses_by_status(db: Session, status: str):
    """Count licenses by status"""
    return db.query(func.count(models.License.license_id)).filter(
        models.License.status == status
    ).scalar()

def update_license_status(db: Session, license_id: int, status: str):
    """Update license status"""
    db_license = get_license_by_id(db, license_id)
    if not db_license:
        return False
    
    db_license.status = status
    db.commit()
    
    # Log the action
    log_action(
        db,
        action="status_change",
        entity_type="license",
        entity_id=license_id,
        details={"new_status": status}
    )
    
    return True

def increment_activation_count(db: Session, license_id: int):
    """Increment the activation count for a license"""
    db_license = get_license_by_id(db, license_id)
    if not db_license:
        return False
    
    db_license.activation_count += 1
    db.commit()
    return True

def get_licenses_expiring_soon(db: Session, days: int = 7):
    """Get licenses expiring within the specified number of days"""
    now = datetime.utcnow()
    expiry_date = now + timedelta(days=days)
    
    return db.query(models.License).filter(
        models.License.status == "active",
        models.License.expires_at.isnot(None),
        models.License.expires_at <= expiry_date,
        models.License.expires_at >= now
    ).all()

def get_activation_by_hardware_id(db: Session, license_id: int, hardware_id: str):
    """Get activation by hardware ID for a specific license"""
    logger.debug("Searching for activation:")
    logger.debug(f"License ID: {license_id}")
    logger.debug(f"Hardware ID: {hardware_id}")
    
    # Get all activations for this license to see what's stored
    all_activations = db.query(models.Activation).filter(
        models.Activation.license_id == license_id
    ).all()
    
    logger.debug("All Activations for this License:")
    for act in all_activations:
        logger.debug(f"Activation ID: {act.activation_id}")
        logger.debug(f"Hardware ID: {act.hardware_id}")
        logger.debug(f"Is Active: {act.is_active}")
    
    # Try to find an exact match
    activation = db.query(models.Activation).filter(
        models.Activation.license_id == license_id,
        models.Activation.hardware_id == hardware_id
    ).first()
    
    return activation

def get_activations_by_license(db: Session, license_id: int):
    """Get all activations for a license"""
    return db.query(models.Activation).filter(models.Activation.license_id == license_id).all()

def get_active_activations_count(db: Session, license_id: int):
    """Count active activations for a license"""
    return db.query(func.count(models.Activation.activation_id)).filter(
        models.Activation.license_id == license_id,
        models.Activation.is_active == True
    ).scalar()

def create_activation(db: Session, license_id: int, hardware_id: str, ip_address: str, 
                      user_agent: Optional[str] = None, system_info: Optional[Dict] = None):
    """Create a new activation"""
    db_activation = models.Activation(
        license_id=license_id,
        hardware_id=hardware_id,  # Ensure hardware ID is stored
        ip_address=ip_address,
        user_agent=user_agent,
        system_info=system_info,
        is_active=True
    )
    db.add(db_activation)
    db.commit()
    db.refresh(db_activation)
    
    # Log the action
    log_action(
        db,
        action="create",
        entity_type="activation",
        entity_id=db_activation.activation_id,
        details={"license_id": license_id, "hardware_id": hardware_id}
    )
    
    return db_activation

def update_activation_check_in(db: Session, activation_id: int):
    """Update the last check-in time for an activation"""
    db_activation = get_activation_by_id(db, activation_id)
    if not db_activation:
        return False
    
    db_activation.last_check_in = datetime.utcnow()
    db.commit()
    return True

def deactivate_license(db: Session, activation_id: int):
    """Deactivate a license (set is_active to False)"""
    # Use self.get_activation_by_id or the fully qualified method name
    db_activation = get_activation_by_id(db, activation_id)  # Change this line
    
    if not db_activation:
        return False
    
    db_activation.is_active = False
    db.commit()
    
    # Log the action
    log_action(
        db,
        action="deactivate",
        entity_type="activation",
        entity_id=activation_id
    )
    
    return True

# Ensure this method is defined in the same file or imported correctly
def get_activation_by_id(db: Session, activation_id: int):
    """Get activation by ID"""
    return db.query(models.Activation).filter(models.Activation.activation_id == activation_id).first()

def reactivate_license(db: Session, activation_id: int):
    """Reactivate a license (set is_active to True and update last_check_in)"""
    db_activation = get_activation_by_id(db, activation_id)
    if not db_activation:
        return False
    
    db_activation.is_active = True
    db_activation.last_check_in = datetime.utcnow()
    db.commit()
    
    # Log the action
    log_action(
        db,
        action="reactivate",
        entity_type="activation",
        entity_id=activation_id
    )
    
    return True

def count_total_activations(db: Session):
    """Count total activations"""
    return db.query(func.count(models.Activation.activation_id)).scalar()

def count_active_activations(db: Session):
    """Count active activations"""
    return db.query(func.count(models.Activation.activation_id)).filter(
        models.Activation.is_active == True
    ).scalar()

def get_recent_activations(db: Session, limit: int = 10):
    """Get recent activations"""
    return db.query(models.Activation).order_by(
        models.Activation.first_activated.desc()
    ).limit(limit).all()

# Client operations
def get_client_by_id(db: Session, client_id: int):
    """Get client by ID"""
    return db.query(models.Client).filter(models.Client.client_id == client_id).first()

def get_clients(db: Session, skip: int = 0, limit: int = 100):
    """Get all clients with pagination"""
    return db.query(models.Client).offset(skip).limit(limit).all()

def count_clients(db: Session):
    """Count total clients"""
    return db.query(func.count(models.Client.client_id)).scalar()

def create_client(db: Session, client_data: schemas.ClientCreate) -> Dict[str, str]:
    """Create a new client, avoiding duplicates"""
    # Check if client with this email already exists
    existing_client = get_client_by_email(db, client_data.email)
    
    if existing_client:
        # Return a dictionary with all required fields 
        return {
            "name": existing_client.name,
            "email": existing_client.email,  # Add email field
            "client_id": existing_client.client_id,
            "company": existing_client.company,
            "existing": True
        }
    
    # If no existing client, create a new one
    db_client = models.Client(
        name=client_data.name,
        email=client_data.email,
        company=client_data.company,
        contact_info=client_data.contact_info
    )
    db.add(db_client)
    db.commit()
    db.refresh(db_client)
    
    # Log the action
    log_action(
        db,
        action="create",
        entity_type="client",
        entity_id=db_client.client_id
    )
    
    return {
        "name": db_client.name,
        "email": db_client.email,  # Add email field
        "client_id": db_client.client_id,
        "company": db_client.company,
        "existing": False
    }

def update_client(db: Session, client_id: int, client_data: schemas.ClientCreate):
    """Update a client"""
    db_client = get_client_by_id(db, client_id)
    if not db_client:
        return None
    
    # Update fields
    db_client.name = client_data.name
    db_client.email = client_data.email
    db_client.company = client_data.company
    db_client.contact_info = client_data.contact_info
    
    db.commit()
    db.refresh(db_client)
    
    # Log the action
    log_action(
        db,
        action="update",
        entity_type="client",
        entity_id=client_id
    )
    
    return db_client

def delete_client(db: Session, client_id: int):
    """Delete a client"""
    db_client = get_client_by_id(db, client_id)
    if not db_client:
        return False
    
    # First check if there are any licenses for this client
    licenses = db.query(models.License).filter(models.License.client_id == client_id).all()
    
    # Delete all licenses and their activations
    for license in licenses:
        delete_license(db, license.license_id)
    
    # Then delete the client
    db.delete(db_client)
    db.commit()
    
    # Log the action
    log_action(
        db,
        action="delete",
        entity_type="client",
        entity_id=client_id
    )
    
    return True

# Product operations
def get_product_by_id(db: Session, product_id: int):
    """Get product by ID"""
    return db.query(models.Product).filter(models.Product.product_id == product_id).first()

def get_products(db: Session, skip: int = 0, limit: int = 100):
    """Get all products with pagination"""
    return db.query(models.Product).offset(skip).limit(limit).all()

def count_products(db: Session):
    """Count total products"""
    return db.query(func.count(models.Product.product_id)).scalar()

def create_product(db: Session, product_data: schemas.ProductCreate):
    """Create a new product with license settings"""
    db_product = models.Product(
        name=product_data.name,
        version=product_data.version,
        features=product_data.features,
        default_max_activations=product_data.default_max_activations,
        license_key_format=product_data.license_key_format,
        heartbeat_interval=product_data.heartbeat_interval,
        auto_deactivate_days=product_data.auto_deactivate_days,
        enforce_hardware_check=product_data.enforce_hardware_check
    )
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    
    # Log the action
    log_action(
        db,
        action="create",
        entity_type="product",
        entity_id=db_product.product_id
    )
    
    return db_product

def update_product(db: Session, product_id: int, product_data: schemas.ProductCreate):
    """Update a product including license settings"""
    db_product = get_product_by_id(db, product_id)
    if not db_product:
        return None
    
    # Update basic fields
    db_product.name = product_data.name
    db_product.version = product_data.version
    db_product.features = product_data.features
    
    # Update license settings
    db_product.default_max_activations = product_data.default_max_activations
    db_product.license_key_format = product_data.license_key_format
    db_product.heartbeat_interval = product_data.heartbeat_interval
    db_product.auto_deactivate_days = product_data.auto_deactivate_days
    db_product.enforce_hardware_check = product_data.enforce_hardware_check
    
    db.commit()
    db.refresh(db_product)
    
    # Log the action
    log_action(
        db,
        action="update",
        entity_type="product",
        entity_id=product_id
    )
    
    return db_product

def delete_product(db: Session, product_id: int):
    """Delete a product"""
    db_product = get_product_by_id(db, product_id)
    if not db_product:
        return False
    
    # First check if there are any licenses for this product
    licenses = db.query(models.License).filter(models.License.product_id == product_id).all()
    
    # Delete all licenses and their activations
    for license in licenses:
        delete_license(db, license.license_id)
    
    # Then delete the product
    db.delete(db_product)
    db.commit()
    
    # Log the action
    log_action(
        db,
        action="delete",
        entity_type="product",
        entity_id=product_id
    )
    
    return True

# API Key operations
def create_api_key(db: Session, name: str, key_type: str = "client", expires_at: Optional[datetime] = None):
    """Generate and store a new API key and return the raw key with its record"""
    key_value = generate_api_key(key_type)
    db_api_key = models.ApiKey(api_key=key_value, name=name, key_type=key_type, expires_at=expires_at)
    db.add(db_api_key)
    db.commit()
    db.refresh(db_api_key)
    # Return raw key (won't be retrievable later) and the DB record
    return key_value, db_api_key

def validate_api_key(db: Session, api_key_value: str, key_type: str) -> bool:
    """Check if API key is valid and active for the given type"""
    api_key_record = db.query(models.ApiKey).filter(
        models.ApiKey.api_key == api_key_value,
        models.ApiKey.key_type == key_type,
        models.ApiKey.is_active == True
    ).first()
    return api_key_record is not None

def revoke_api_key(db: Session, api_key_value: str) -> bool:
    """Revoke (deactivate) an API key"""
    api_key_record = db.query(models.ApiKey).filter(
        models.ApiKey.api_key == api_key_value,
        models.ApiKey.is_active == True
    ).first()
    if not api_key_record:
        return False
    api_key_record.is_active = False
    db.commit()
    return True

def get_api_keys(db: Session, skip: int = 0, limit: int = 100):
    """Get all API keys with pagination"""
    return db.query(models.ApiKey).offset(skip).limit(limit).all()

# Audit log operations
def log_action(db: Session, action: str, entity_type: str, entity_id: int, user_id: Optional[int] = None, 
               ip_address: Optional[str] = None, details: Optional[Dict[str, str]] = None):
    """Add an entry to the audit log"""
    db_log = models.AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        ip_address=ip_address,
        details=details
    )
    db.add(db_log)
    db.commit()
    
    return db_log

def get_audit_logs(
    db: Session, 
    skip: int = 0, 
    limit: int = 100, 
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    start_date: Optional[datetime] = None
):
    """Get audit logs with filtering and pagination"""
    query = db.query(models.AuditLog)
    
    # Apply filters
    if action:
        query = query.filter(models.AuditLog.action == action)
    
    if entity_type:
        query = query.filter(models.AuditLog.entity_type == entity_type)
    
    if start_date:
        query = query.filter(models.AuditLog.timestamp >= start_date)
    
    # Always order by timestamp, descending
    query = query.order_by(models.AuditLog.timestamp.desc())
    
    return query.offset(skip).limit(limit).all()

def count_audit_logs(
    db: Session,
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    start_date: Optional[datetime] = None
):
    """Count total audit logs with filtering"""
    query = db.query(func.count(models.AuditLog.log_id))
    
    # Apply filters
    if action:
        query = query.filter(models.AuditLog.action == action)
    
    if entity_type:
        query = query.filter(models.AuditLog.entity_type == entity_type)
    
    if start_date:
        query = query.filter(models.AuditLog.timestamp >= start_date)
    
    return query.scalar()

# Report operations
def get_license_stats(db: Session):
    """Get license statistics"""
    total = db.query(func.count(models.License.license_id)).scalar()
    active = count_licenses_by_status(db, "active")
    expired = count_licenses_by_status(db, "expired")
    revoked = count_licenses_by_status(db, "revoked")
    
    # Licenses by product
    by_product = db.query(
        models.Product.name,
        func.count(models.License.license_id)
    ).join(
        models.License, models.License.product_id == models.Product.product_id
    ).group_by(
        models.Product.name
    ).all()
    
    # Licenses by client (top 10)
    by_client = db.query(
        models.Client.name,
        func.count(models.License.license_id)
    ).join(
        models.License, models.License.client_id == models.Client.client_id
    ).group_by(
        models.Client.name
    ).order_by(
        func.count(models.License.license_id).desc()
    ).limit(10).all()
    
    return {
        "total": total,
        "active": active,
        "expired": expired,
        "revoked": revoked,
        "by_product": by_product,
        "by_client": by_client
    }

def get_activation_stats(db: Session):
    """Get activation statistics"""
    total = count_total_activations(db)
    active = count_active_activations(db)
    
    # Activations by product
    by_product = db.query(
        models.Product.name,
        func.count(models.Activation.activation_id)
    ).join(
        models.License, models.License.license_id == models.Activation.license_id
    ).join(
        models.Product, models.Product.product_id == models.License.product_id
    ).group_by(
        models.Product.name
    ).all()
    
    # Recent activations trend (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    daily_activations = db.query(
        func.date(models.Activation.first_activated).label('date'),
        func.count(models.Activation.activation_id).label('count')
    ).filter(
        models.Activation.first_activated >= thirty_days_ago
    ).group_by(
        func.date(models.Activation.first_activated)
    ).order_by(
        func.date(models.Activation.first_activated)
    ).all()
    
    return {
        "total": total,
        "active": active,
        "by_product": by_product,
        "daily_trend": daily_activations
    }

def get_client_by_email(db: Session, email: str):
    """Get client by email address"""
    return db.query(models.Client).filter(models.Client.email == email).first()

def generate_usage_report(db: Session, product_id: Optional[int] = None, client_id: Optional[int] = None,
                          start_date: Optional[datetime] = None, end_date: Optional[datetime] = None):
    """Generate a usage report with optional filters"""
    # Base query
    license_query = db.query(models.License)
    activation_query = db.query(models.Activation)
    
    # Apply filters
    if product_id:
        license_query = license_query.filter(models.License.product_id == product_id)
    
    if client_id:
        license_query = license_query.filter(models.License.client_id == client_id)
    
    licenses = license_query.all()
    license_ids = [lic.license_id for lic in licenses]
    
    activation_query = activation_query.filter(models.Activation.license_id.in_(license_ids))
    
    if start_date:
        activation_query = activation_query.filter(models.Activation.first_activated >= start_date)
        
    if end_date:
        activation_query = activation_query.filter(models.Activation.first_activated <= end_date)
        
    # Get activations
    activations = activation_query.all()
    
    # Build report
    total_licenses = len(licenses)
    active_licenses = sum(1 for lic in licenses if lic.status == "active")
    total_activations = len(activations)
    active_activations = sum(1 for act in activations if act.is_active)
    
    # Group activations by date
    activation_history = db.query(
        func.date(models.Activation.first_activated).label('date'),
        func.count(models.Activation.activation_id).label('count')
    ).filter(
        models.Activation.license_id.in_(license_ids)
    )
    
    if start_date:
        activation_history = activation_history.filter(models.Activation.first_activated >= start_date)
        
    if end_date:
        activation_history = activation_history.filter(models.Activation.first_activated <= end_date)
        
    activation_history = activation_history.group_by(
        func.date(models.Activation.first_activated)
    ).order_by(
        func.date(models.Activation.first_activated)
    ).all()
    
    # Convert to dictionary
    activation_history_dict = [{"date": str(item.date), "count": item.count} for item in activation_history]
    
    return {
        "total_licenses": total_licenses,
        "active_licenses": active_licenses,
        "total_activations": total_activations,
        "active_activations": active_activations,
        "activation_history": activation_history_dict
    }

# System settings operations
def get_system_setting(db: Session, key: str):
    """Get a system setting by key"""
    return db.query(models.SystemSettings).filter(models.SystemSettings.key == key).first()

def get_all_system_settings(db: Session):
    """Get all system settings"""
    return db.query(models.SystemSettings).all()

def update_system_setting(db: Session, key: str, value: str):
    """Update or create a system setting"""
    setting = get_system_setting(db, key)
    if setting:
        setting.value = value
    else:
        setting = models.SystemSettings(key=key, value=value)
        db.add(setting)
    db.commit()
    return setting

def get_system_settings_dict(db: Session) -> Dict[str, str]:
    """Get all system settings as a dictionary with comprehensive logging"""
    try:
        settings = get_all_system_settings(db)
        settings_dict = {setting.key: setting.value for setting in settings}
        
        # Print out settings keys for debugging
        logger.debug("System Settings Keys:")
        for key in settings_dict.keys():
            logger.debug(key)
        
        # Special handling for SMTP password
        if "email_smtp_password" in settings_dict:
            logger.debug("SMTP Password exists in settings")
            logger.debug(f"SMTP Password length: {len(settings_dict['email_smtp_password'])}")
        
        return settings_dict
    except Exception as e:
        logger.debug(f"Error retrieving system settings: {str(e)}")
        return {}