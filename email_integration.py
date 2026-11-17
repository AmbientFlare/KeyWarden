# email_integration.py
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import logging

# Import local modules
from email_sender import EmailSender, send_license_created_notification, send_license_expiring_notification, send_license_status_changed_notification, send_unusual_activity_notification, send_license_usage_report
from db import crud, models

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_email_settings(db: Session) -> Dict[str, Any]:
    """
    Get email settings from database
    """
    # Get system settings
    system_settings_dict = crud.get_system_settings_dict(db)
    
    # Extract email-related settings
    email_settings = {
        'smtp_server': system_settings_dict.get('email_smtp_server', ''),
        'smtp_port': system_settings_dict.get('email_smtp_port', '587'),
        'smtp_username': system_settings_dict.get('email_smtp_username', ''),
        'smtp_password': system_settings_dict.get('email_smtp_password', ''),
        'sender_email': system_settings_dict.get('email_sender_email', ''),
        'use_tls': system_settings_dict.get('email_use_tls', 'true') == 'true',
        'enable_license_notifications': system_settings_dict.get('email_enable_license_notifications', 'false') == 'true',
        'enable_expiration_warnings': system_settings_dict.get('email_enable_expiration_warnings', 'false') == 'true',
        'enable_status_notifications': system_settings_dict.get('email_enable_status_notifications', 'false') == 'true',
        'enable_unusual_activity_alerts': system_settings_dict.get('email_enable_unusual_activity_alerts', 'false') == 'true',
        'admin_email': system_settings_dict.get('email_admin_email', '')
    }
    
    return email_settings

def create_email_sender(db: Session) -> Optional[EmailSender]:
    """
    Create an EmailSender instance with settings from the database
    """
    email_settings = get_email_settings(db)
    
    # Check if essential settings are present
    if not all([
        email_settings.get('smtp_server'),
        email_settings.get('smtp_username'),
        email_settings.get('smtp_password'),
        email_settings.get('sender_email')
    ]):
        logger.warning("Email settings incomplete. Cannot create EmailSender.")
        return None
    
    return EmailSender(email_settings)

def send_license_created_email(db: Session, license_id: int) -> bool:
    """
    Send license creation notification email
    """
    # Get settings
    settings = get_email_settings(db)
    if not settings.get('enable_license_notifications', False):
        logger.info("License notifications disabled. Skipping email.")
        return False
    
    # Get license, client, and product data
    license_data = crud.get_license_by_id(db, license_id)
    if not license_data:
        logger.error(f"License with ID {license_id} not found.")
        return False
    
    client_data = crud.get_client_by_id(db, license_data.client_id)
    if not client_data:
        logger.error(f"Client with ID {license_data.client_id} not found.")
        return False
    
    product_data = crud.get_product_by_id(db, license_data.product_id)
    if not product_data:
        logger.error(f"Product with ID {license_data.product_id} not found.")
        return False
    
    # Create email sender
    email_sender = create_email_sender(db)
    if not email_sender:
        logger.error("Failed to create EmailSender.")
        return False
    
    # Send notification
    success = send_license_created_notification(
        email_sender,
        license_data.__dict__,
        client_data.__dict__,
        product_data.__dict__
    )
    
    if success:
        logger.info(f"License creation notification sent for license ID {license_id}.")
    else:
        logger.error(f"Failed to send license creation notification for license ID {license_id}.")
    
    return success

def send_license_expiring_email(db: Session, license_id: int, days_remaining: int) -> bool:
    """
    Send license expiration warning email
    """
    # Get settings
    settings = get_email_settings(db)
    if not settings.get('enable_expiration_warnings', False):
        logger.info("Expiration warnings disabled. Skipping email.")
        return False
    
    # Get license, client, and product data
    license_data = crud.get_license_by_id(db, license_id)
    if not license_data:
        logger.error(f"License with ID {license_id} not found.")
        return False
    
    client_data = crud.get_client_by_id(db, license_data.client_id)
    if not client_data:
        logger.error(f"Client with ID {license_data.client_id} not found.")
        return False
    
    product_data = crud.get_product_by_id(db, license_data.product_id)
    if not product_data:
        logger.error(f"Product with ID {license_data.product_id} not found.")
        return False
    
    # Create email sender
    email_sender = create_email_sender(db)
    if not email_sender:
        logger.error("Failed to create EmailSender.")
        return False
    
    # Send notification
    success = send_license_expiring_notification(
        email_sender,
        license_data.__dict__,
        client_data.__dict__,
        product_data.__dict__,
        days_remaining
    )
    
    if success:
        logger.info(f"License expiration warning sent for license ID {license_id}.")
    else:
        logger.error(f"Failed to send license expiration warning for license ID {license_id}.")
    
    return success

def send_license_status_changed_email(db: Session, license_id: int, new_status: str, reason: str = "") -> bool:
    """
    Send license status change notification email
    """
    # Get settings
    settings = get_email_settings(db)
    if not settings.get('enable_status_notifications', False):
        logger.info("Status notifications disabled. Skipping email.")
        return False
    
    # Get license, client, and product data
    license_data = crud.get_license_by_id(db, license_id)
    if not license_data:
        logger.error(f"License with ID {license_id} not found.")
        return False
    
    client_data = crud.get_client_by_id(db, license_data.client_id)
    if not client_data:
        logger.error(f"Client with ID {license_data.client_id} not found.")
        return False
    
    product_data = crud.get_product_by_id(db, license_data.product_id)
    if not product_data:
        logger.error(f"Product with ID {license_data.product_id} not found.")
        return False
    
    # Create email sender
    email_sender = create_email_sender(db)
    if not email_sender:
        logger.error("Failed to create EmailSender.")
        return False
    
    # Send notification
    success = send_license_status_changed_notification(
        email_sender,
        license_data.__dict__,
        client_data.__dict__,
        product_data.__dict__,
        new_status,
        reason
    )
    
    if success:
        logger.info(f"License status change notification sent for license ID {license_id}.")
    else:
        logger.error(f"Failed to send license status change notification for license ID {license_id}.")
    
    return success

def send_unusual_activity_email(db: Session, license_id: int, activity_type: str, details: Dict[str, Any]) -> bool:
    """
    Send unusual activity notification email
    """
    # Get settings
    settings = get_email_settings(db)
    if not settings.get('enable_unusual_activity_alerts', False):
        logger.info("Unusual activity alerts disabled. Skipping email.")
        return False
    
    # Get license, client, and product data
    license_data = crud.get_license_by_id(db, license_id)
    if not license_data:
        logger.error(f"License with ID {license_id} not found.")
        return False
    
    client_data = crud.get_client_by_id(db, license_data.client_id)
    if not client_data:
        logger.error(f"Client with ID {license_data.client_id} not found.")
        return False
    
    product_data = crud.get_product_by_id(db, license_data.product_id)
    if not product_data:
        logger.error(f"Product with ID {license_data.product_id} not found.")
        return False
    
    # Create email sender
    email_sender = create_email_sender(db)
    if not email_sender:
        logger.error("Failed to create EmailSender.")
        return False
    
    # Send notification
    success = send_unusual_activity_notification(
        email_sender,
        license_data.__dict__,
        client_data.__dict__,
        product_data.__dict__,
        activity_type,
        details
    )
    
    if success:
        logger.info(f"Unusual activity notification sent for license ID {license_id}.")
    else:
        logger.error(f"Failed to send unusual activity notification for license ID {license_id}.")
    
    return success

def send_admin_usage_report(db: Session, report_type: str = "weekly") -> bool:
    """
    Send license usage report to administrator
    """
    # Get settings
    settings = get_email_settings(db)
    admin_email = settings.get('admin_email')
    if not admin_email:
        logger.error("Admin email not configured. Cannot send usage report.")
        return False
    
    # Create email sender
    email_sender = create_email_sender(db)
    if not email_sender:
        logger.error("Failed to create EmailSender.")
        return False
    
    # Generate report data
    active_licenses = crud.count_licenses_by_status(db, "active")
    expired_licenses = crud.count_licenses_by_status(db, "expired")
    revoked_licenses = crud.count_licenses_by_status(db, "revoked")
    
    total_activations = crud.count_total_activations(db)
    active_activations = crud.count_active_activations(db)
    
    # Get licenses expiring soon
    expiring_soon = crud.get_licenses_expiring_soon(db, days=7)
    expiring_soon_data = []
    
    for license in expiring_soon:
        client = crud.get_client_by_id(db, license.client_id)
        product = crud.get_product_by_id(db, license.product_id)
        
        expiring_soon_data.append({
            'license_key': license.license_key,
            'client_name': client.name if client else "Unknown",
            'product_name': product.name if product else "Unknown",
            'expires_at': license.expires_at.strftime('%Y-%m-%d')
        })
    
    report_data = {
        'total_licenses': active_licenses + expired_licenses + revoked_licenses,
        'active_licenses': active_licenses,
        'expired_licenses': expired_licenses,
        'revoked_licenses': revoked_licenses,
        'total_activations': total_activations,
        'active_activations': active_activations,
        'expiring_soon': expiring_soon_data
    }
    
    # Send report
    success = send_license_usage_report(
        email_sender,
        admin_email,
        report_data,
        report_type
    )
    
    if success:
        logger.info(f"{report_type.capitalize()} usage report sent to admin.")
    else:
        logger.error(f"Failed to send {report_type} usage report to admin.")
    
    return success

def check_and_send_expiration_warnings(db: Session) -> Dict[str, int]:
    """
    Check for licenses that are about to expire and send warning emails
    
    Returns:
        Dict with counts of emails sent for different warning periods
    """
    # Get settings
    settings = get_email_settings(db)
    if not settings.get('enable_expiration_warnings', False):
        logger.info("Expiration warnings disabled. Skipping check.")
        return {}
    
    # Warning periods in days
    warning_days = [30, 14, 7, 3, 1]
    today = datetime.utcnow().date()
    results = {}
    
    for days in warning_days:
        target_date = today + timedelta(days=days)
        
        # Find licenses expiring on target date
        expiring_licenses = db.query(models.License).filter(
            models.License.status == "active",
            func.date(models.License.expires_at) == target_date
        ).all()
        
        sent_count = 0
        for license in expiring_licenses:
            sent = send_license_expiring_email(db, license.license_id, days)
            if sent:
                sent_count += 1
        
        results[f"{days}_days"] = sent_count
    
    return results