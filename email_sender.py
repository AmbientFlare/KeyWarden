# email_sender.py
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union, Any
import logging
from jinja2 import Environment, FileSystemLoader, select_autoescape
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set up Jinja2 for email templates
templates_dir = os.path.join(os.path.dirname(__file__), "email_templates")
os.makedirs(templates_dir, exist_ok=True)

jinja_env = Environment(
    loader=FileSystemLoader(templates_dir),
    autoescape=select_autoescape(['html', 'xml'])
)

class EmailSender:
    def __init__(self, settings: Dict[str, Any]):
        """
        Initialize the EmailSender with provided SMTP settings.
        
        Args:
            settings: Dictionary with SMTP configuration parameters
        """
        self.smtp_server = settings.get('smtp_server')
        self.smtp_port = int(settings.get('smtp_port', 587))
        self.smtp_username = settings.get('smtp_username')
        self.smtp_password = settings.get('smtp_password')
        self.sender_email = settings.get('sender_email')
        self.use_tls = settings.get('use_tls', True)
        
        # Validate essential settings
        if not all([self.smtp_server, self.smtp_username, self.smtp_password, self.sender_email]):
            logger.warning("Email settings incomplete. Email functionality will not work properly.")
    
    def send_email(self, to_email: Union[str, List[str]], subject: str, 
                   text_content: str, html_content: Optional[str] = None) -> bool:
        """
        Send an email with both plain text and HTML versions.
        
        Args:
            to_email: Recipient email address or list of addresses
            subject: Email subject
            text_content: Plain text content
            html_content: HTML content (optional)
            
        Returns:
            bool: True if email was sent successfully, False otherwise
        """
        if not all([self.smtp_server, self.smtp_username, self.smtp_password, self.sender_email]):
            logger.error("Cannot send email: Email settings incomplete")
            return False
        
        # Convert single email to list
        if isinstance(to_email, str):
            to_email = [to_email]
            
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.sender_email
        msg['To'] = ', '.join(to_email)
        
        # Add text part
        part1 = MIMEText(text_content, 'plain')
        msg.attach(part1)
        
        # Add HTML part if provided
        if html_content:
            part2 = MIMEText(html_content, 'html')
            msg.attach(part2)
        
        try:
            # Create secure connection and send email
            context = ssl.create_default_context()
            
            if self.use_tls:
                # For TLS
                with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                    server.starttls(context=context)
                    server.login(self.smtp_username, self.smtp_password)
                    server.sendmail(self.sender_email, to_email, msg.as_string())
            else:
                # For SSL
                with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, context=context) as server:
                    server.login(self.smtp_username, self.smtp_password)
                    server.sendmail(self.sender_email, to_email, msg.as_string())
                    
            logger.info(f"Email sent to {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email: {str(e)}")
            return False

# License notification methods
def send_license_created_notification(email_sender: EmailSender, license_data: Dict[str, Any], 
                                     client_data: Dict[str, Any], product_data: Dict[str, Any]) -> bool:
    """
    Send notification email when a new license is created.
    
    Args:
        email_sender: Configured EmailSender instance
        license_data: License information dictionary
        client_data: Client information dictionary
        product_data: Product information dictionary
        
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    subject = f"Your {product_data['name']} License Key"
    
    # Get templates
    try:
        text_template = jinja_env.get_template('license_created.txt')
        html_template = jinja_env.get_template('license_created.html')
    except Exception as e:
        logger.error(f"Template error: {str(e)}. Using default templates.")
        # Use default templates if files not found
        text_template = None
        html_template = None
    
    # Prepare context data
    context = {
        'client_name': client_data['name'],
        'product_name': product_data['name'],
        'product_version': product_data['version'],
        'license_key': license_data['license_key'],
        'max_activations': license_data['max_activations'],
        'created_date': license_data['created_at'].strftime('%Y-%m-%d'),
        'expires_date': license_data['expires_at'].strftime('%Y-%m-%d') if license_data.get('expires_at') else 'Never',
        'features': license_data.get('features', {})
    }
    
    # Generate content from templates or use defaults
    if text_template:
        text_content = text_template.render(**context)
    else:
        # Default text template
        text_content = f"""
Hello {client_data['name']},

Your license key for {product_data['name']} {product_data['version']} has been created.

License Key: {license_data['license_key']}
Created: {license_data['created_at'].strftime('%Y-%m-%d')}
Expires: {license_data['expires_at'].strftime('%Y-%m-%d') if license_data.get('expires_at') else 'Never'}
Max Activations: {license_data['max_activations']}

Thank you for your business!
"""
    
    if html_template:
        html_content = html_template.render(**context)
    else:
        # Default HTML template
        html_content = f"""
<html>
<body>
    <h2>Your License Key</h2>
    <p>Hello {client_data['name']},</p>
    <p>Your license key for {product_data['name']} {product_data['version']} has been created.</p>
    
    <div style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin: 20px 0;">
        <p><strong>License Key:</strong> {license_data['license_key']}</p>
        <p><strong>Created:</strong> {license_data['created_at'].strftime('%Y-%m-%d')}</p>
        <p><strong>Expires:</strong> {license_data['expires_at'].strftime('%Y-%m-%d') if license_data.get('expires_at') else 'Never'}</p>
        <p><strong>Max Activations:</strong> {license_data['max_activations']}</p>
    </div>
    
    <p>Thank you for your business!</p>
</body>
</html>
"""
    
    # Send the email
    return email_sender.send_email(client_data['email'], subject, text_content, html_content)

def send_license_expiring_notification(email_sender: EmailSender, license_data: Dict[str, Any],
                                      client_data: Dict[str, Any], product_data: Dict[str, Any],
                                      days_remaining: int) -> bool:
    """
    Send notification email when a license is about to expire.
    
    Args:
        email_sender: Configured EmailSender instance
        license_data: License information dictionary
        client_data: Client information dictionary
        product_data: Product information dictionary
        days_remaining: Number of days until expiration
        
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    subject = f"Your {product_data['name']} License Expires in {days_remaining} Days"
    
    # Get templates
    try:
        text_template = jinja_env.get_template('license_expiring.txt')
        html_template = jinja_env.get_template('license_expiring.html')
    except Exception as e:
        logger.error(f"Template error: {str(e)}. Using default templates.")
        text_template = None
        html_template = None
    
    # Prepare context data
    context = {
        'client_name': client_data['name'],
        'product_name': product_data['name'],
        'product_version': product_data['version'],
        'license_key': license_data['license_key'],
        'expires_date': license_data['expires_at'].strftime('%Y-%m-%d'),
        'days_remaining': days_remaining
    }
    
    # Generate content from templates or use defaults
    if text_template:
        text_content = text_template.render(**context)
    else:
        # Default text template
        text_content = f"""
Hello {client_data['name']},

Your license key for {product_data['name']} {product_data['version']} will expire in {days_remaining} days.

License Key: {license_data['license_key']}
Expiration Date: {license_data['expires_at'].strftime('%Y-%m-%d')}

Please contact us to renew your license if you wish to continue using the product.

Thank you!
"""
    
    if html_template:
        html_content = html_template.render(**context)
    else:
        # Default HTML template
        html_content = f"""
<html>
<body>
    <h2>License Expiration Notice</h2>
    <p>Hello {client_data['name']},</p>
    <p>Your license key for {product_data['name']} {product_data['version']} will expire in <strong>{days_remaining} days</strong>.</p>
    
    <div style="background-color: #fff3cd; padding: 15px; border-radius: 5px; margin: 20px 0;">
        <p><strong>License Key:</strong> {license_data['license_key']}</p>
        <p><strong>Expiration Date:</strong> {license_data['expires_at'].strftime('%Y-%m-%d')}</p>
    </div>
    
    <p>Please contact us to renew your license if you wish to continue using the product.</p>
    
    <p>Thank you!</p>
</body>
</html>
"""
    
    # Send the email
    return email_sender.send_email(client_data['email'], subject, text_content, html_content)

def send_license_status_changed_notification(email_sender: EmailSender, license_data: Dict[str, Any],
                                           client_data: Dict[str, Any], product_data: Dict[str, Any],
                                           new_status: str, reason: str = "") -> bool:
    """
    Send notification email when a license status changes.
    
    Args:
        email_sender: Configured EmailSender instance
        license_data: License information dictionary
        client_data: Client information dictionary
        product_data: Product information dictionary
        new_status: New license status
        reason: Reason for status change (optional)
        
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    subject = f"Your {product_data['name']} License Status Changed"
    
    # Get templates
    try:
        text_template = jinja_env.get_template('license_status_changed.txt')
        html_template = jinja_env.get_template('license_status_changed.html')
    except Exception as e:
        logger.error(f"Template error: {str(e)}. Using default templates.")
        text_template = None
        html_template = None
    
    # Prepare context data
    context = {
        'client_name': client_data['name'],
        'product_name': product_data['name'],
        'product_version': product_data['version'],
        'license_key': license_data['license_key'],
        'new_status': new_status,
        'reason': reason
    }
    
    # Generate content from templates or use defaults
    if text_template:
        text_content = text_template.render(**context)
    else:
        # Default text template
        text_content = f"""
Hello {client_data['name']},

Your license key for {product_data['name']} {product_data['version']} has been {new_status}.

License Key: {license_data['license_key']}
New Status: {new_status.capitalize()}
"""
        if reason:
            text_content += f"Reason: {reason}\n"
        
        text_content += "\nIf you have any questions, please contact support.\n\nThank you!"
    
    if html_template:
        html_content = html_template.render(**context)
    else:
        # Default HTML template
        status_color = {
            'active': '#d4edda',
            'expired': '#fff3cd',
            'revoked': '#f8d7da'
        }.get(new_status.lower(), '#f5f5f5')
        
        html_content = f"""
<html>
<body>
    <h2>License Status Change</h2>
    <p>Hello {client_data['name']},</p>
    <p>Your license key for {product_data['name']} {product_data['version']} has been <strong>{new_status}</strong>.</p>
    
    <div style="background-color: {status_color}; padding: 15px; border-radius: 5px; margin: 20px 0;">
        <p><strong>License Key:</strong> {license_data['license_key']}</p>
        <p><strong>New Status:</strong> {new_status.capitalize()}</p>
"""
        if reason:
            html_content += f"        <p><strong>Reason:</strong> {reason}</p>\n"
        
        html_content += """
    </div>
    
    <p>If you have any questions, please contact support.</p>
    
    <p>Thank you!</p>
</body>
</html>
"""
    
    # Send the email
    return email_sender.send_email(client_data['email'], subject, text_content, html_content)

def send_unusual_activity_notification(email_sender: EmailSender, license_data: Dict[str, Any],
                                     client_data: Dict[str, Any], product_data: Dict[str, Any],
                                     activity_type: str, details: Dict[str, Any]) -> bool:
    """
    Send notification email when unusual license activity is detected.
    
    Args:
        email_sender: Configured EmailSender instance
        license_data: License information dictionary
        client_data: Client information dictionary
        product_data: Product information dictionary
        activity_type: Type of unusual activity detected
        details: Details about the unusual activity
        
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    subject = f"Unusual Activity Detected for Your {product_data['name']} License"
    
    # Get templates
    try:
        text_template = jinja_env.get_template('unusual_activity.txt')
        html_template = jinja_env.get_template('unusual_activity.html')
    except Exception as e:
        logger.error(f"Template error: {str(e)}. Using default templates.")
        text_template = None
        html_template = None
    
    # Prepare context data
    context = {
        'client_name': client_data['name'],
        'product_name': product_data['name'],
        'product_version': product_data['version'],
        'license_key': license_data['license_key'],
        'activity_type': activity_type,
        'details': details,
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    # Generate content from templates or use defaults
    if text_template:
        text_content = text_template.render(**context)
    else:
        # Default text template
        text_content = f"""
Hello {client_data['name']},

We've detected unusual activity related to your {product_data['name']} license.

License Key: {license_data['license_key']}
Activity Type: {activity_type}
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Details:
"""
        for key, value in details.items():
            text_content += f"- {key}: {value}\n"
        
        text_content += """
If this activity was not authorized by you, please contact our support team immediately.

Thank you,
License Management Team
"""
    
    if html_template:
        html_content = html_template.render(**context)
    else:
        # Default HTML template
        html_content = f"""
<html>
<body>
    <h2>Unusual License Activity Detected</h2>
    <p>Hello {client_data['name']},</p>
    <p>We've detected unusual activity related to your {product_data['name']} license.</p>
    
    <div style="background-color: #f8d7da; padding: 15px; border-radius: 5px; margin: 20px 0;">
        <p><strong>License Key:</strong> {license_data['license_key']}</p>
        <p><strong>Activity Type:</strong> {activity_type}</p>
        <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        
        <h4>Details:</h4>
        <ul>
"""
        for key, value in details.items():
            html_content += f"            <li><strong>{key}:</strong> {value}</li>\n"
        
        html_content += """
        </ul>
    </div>
    
    <p>If this activity was not authorized by you, please contact our support team immediately.</p>
    
    <p>Thank you,<br>License Management Team</p>
</body>
</html>
"""
    
    # Send the email
    return email_sender.send_email(client_data['email'], subject, text_content, html_content)

def send_license_usage_report(email_sender: EmailSender, admin_email: str, 
                            report_data: Dict[str, Any], report_type: str = "weekly") -> bool:
    """
    Send license usage report to administrator.
    
    Args:
        email_sender: Configured EmailSender instance
        admin_email: Administrator email address
        report_data: Report data dictionary
        report_type: Type of report (weekly, monthly)
        
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    subject = f"{report_type.capitalize()} License Usage Report"
    
    # Get templates
    try:
        text_template = jinja_env.get_template('usage_report.txt')
        html_template = jinja_env.get_template('usage_report.html')
    except Exception as e:
        logger.error(f"Template error: {str(e)}. Using default templates.")
        text_template = None
        html_template = None
    
    # Prepare context data
    context = {
        'report_type': report_type,
        'report_date': datetime.now().strftime('%Y-%m-%d'),
        'report_data': report_data
    }
    
    # Generate content from templates or use defaults
    if text_template:
        text_content = text_template.render(**context)
    else:
        # Default text template
        text_content = f"""
{report_type.capitalize()} License Usage Report
Generated: {datetime.now().strftime('%Y-%m-%d')}

License Summary:
- Total Licenses: {report_data.get('total_licenses', 0)}
- Active Licenses: {report_data.get('active_licenses', 0)}
- Expired Licenses: {report_data.get('expired_licenses', 0)}
- Revoked Licenses: {report_data.get('revoked_licenses', 0)}

Activation Summary:
- Total Activations: {report_data.get('total_activations', 0)}
- Active Activations: {report_data.get('active_activations', 0)}

Licenses Expiring Soon:
"""
        expiring_soon = report_data.get('expiring_soon', [])
        for license in expiring_soon:
            text_content += f"- {license.get('client_name')}: {license.get('license_key')} expires on {license.get('expires_at')}\n"
        
        text_content += "\nFor more details, please check the admin dashboard."
    
    if html_template:
        html_content = html_template.render(**context)
    else:
        # Default HTML template
        html_content = f"""
<html>
<body>
    <h2>{report_type.capitalize()} License Usage Report</h2>
    <p>Generated: {datetime.now().strftime('%Y-%m-%d')}</p>
    
    <div style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin: 20px 0;">
        <h3>License Summary</h3>
        <ul>
            <li>Total Licenses: {report_data.get('total_licenses', 0)}</li>
            <li>Active Licenses: {report_data.get('active_licenses', 0)}</li>
            <li>Expired Licenses: {report_data.get('expired_licenses', 0)}</li>
            <li>Revoked Licenses: {report_data.get('revoked_licenses', 0)}</li>
        </ul>
        
        <h3>Activation Summary</h3>
        <ul>
            <li>Total Activations: {report_data.get('total_activations', 0)}</li>
            <li>Active Activations: {report_data.get('active_activations', 0)}</li>
        </ul>
    </div>
    
    <h3>Licenses Expiring Soon</h3>
    <table style="width: 100%; border-collapse: collapse;">
        <tr style="background-color: #4e73df; color: white;">
            <th style="padding: 8px; text-align: left; border: 1px solid #ddd;">Client</th>
            <th style="padding: 8px; text-align: left; border: 1px solid #ddd;">License Key</th>
            <th style="padding: 8px; text-align: left; border: 1px solid #ddd;">Product</th>
            <th style="padding: 8px; text-align: left; border: 1px solid #ddd;">Expires</th>
        </tr>
"""
        expiring_soon = report_data.get('expiring_soon', [])
        for i, license in enumerate(expiring_soon):
            bg_color = "#ffffff" if i % 2 == 0 else "#f2f2f2"
            html_content += f"""
        <tr style="background-color: {bg_color};">
            <td style="padding: 8px; text-align: left; border: 1px solid #ddd;">{license.get('client_name')}</td>
            <td style="padding: 8px; text-align: left; border: 1px solid #ddd;">{license.get('license_key')}</td>
            <td style="padding: 8px; text-align: left; border: 1px solid #ddd;">{license.get('product_name')}</td>
            <td style="padding: 8px; text-align: left; border: 1px solid #ddd;">{license.get('expires_at')}</td>
        </tr>"""
        
        html_content += """
    </table>
    
    <p>For more details, please check the admin dashboard.</p>
</body>
</html>
"""
    
    # Send the email
    return email_sender.send_email(admin_email, subject, text_content, html_content)