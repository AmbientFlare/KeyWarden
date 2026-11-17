# test_email_route.py
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func  # Correctly import func from sqlalchemy
from datetime import datetime

# Import local modules
from web_gui import web_app, authenticate, get_db, templates

# Helper function to get email settings
def get_email_settings(db):
    """Get email settings from database"""
    # Import the CRUD module
    from db import crud
    
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
        'admin_email': system_settings_dict.get('email_admin_email', '')
    }
    
    return email_settings

# Email test route
@web_app.get("/settings/email/test", response_class=HTMLResponse)
async def test_email_settings(
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Test email settings by sending a test email"""
    try:
        # Import email integration
        from email_integration import create_email_sender
        
        # Get email settings
        email_settings = get_email_settings(db)
        admin_email = email_settings.get('admin_email')
        
        # Create email sender
        email_sender = create_email_sender(db)
        
        if not email_sender:
            # Return error page
            return templates.TemplateResponse("email_test_result.html", {
                "request": request,
                "username": username,
                "success": False,
                "message": "Failed to create email sender. Please check your SMTP settings."
            })
        
        if not admin_email:
            # Return error page
            return templates.TemplateResponse("email_test_result.html", {
                "request": request,
                "username": username,
                "success": False,
                "message": "Admin email not configured. Please set an admin email address."
            })
        
        # Send test email
        success = email_sender.send_email(
            admin_email,
            "License Server - Email Test",
            "This is a test email from your License Server.",
            f"""
            <html>
            <body>
                <h1>License Server Email Test</h1>
                <p>This is a test email to verify that your email settings are configured correctly.</p>
                <p>If you're reading this, the test was successful!</p>
                <p>Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </body>
            </html>
            """
        )
        
        # Return result page
        return templates.TemplateResponse("email_test_result.html", {
            "request": request,
            "username": username,
            "success": success,
            "message": "Test email sent successfully. Please check your inbox." if success else "Failed to send test email. Please check your SMTP settings."
        })
    
    except Exception as e:
        # Return error page
        return templates.TemplateResponse("email_test_result.html", {
            "request": request,
            "username": username,
            "success": False,
            "message": f"Error testing email settings: {str(e)}"
        })