# web_gui.py
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
import os
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
import uvicorn
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import json
import logging

# Local modules
from db import models, crud, schemas
from db.database import SessionLocal
from security import create_license_key

from contextlib import asynccontextmanager

# Initialize email scheduler
email_scheduler = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    # Startup code (previously in startup_event)
    global email_scheduler
    
    try:
        # Import scheduler
        from scheduler import EmailScheduler
        
        # Initialize scheduler with session maker
        email_scheduler = EmailScheduler(SessionLocal)
        
        # Start scheduler
        email_scheduler.start()
        
        logger.info("Email scheduler started successfully")
    except Exception as e:
        logger.error(f"Failed to start email scheduler: {str(e)}")
        
    yield  # This is where the app runs
    
    # Shutdown code (previously in shutdown_event)
    if email_scheduler:
        try:
            # Stop scheduler
            email_scheduler.stop()
            logger.info("Email scheduler stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping email scheduler: {str(e)}")

# Create the web app
web_app = FastAPI(title="License Server Admin UI", lifespan=lifespan)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set up authentication
security = HTTPBasic()

# Configure templates and static files
templates = Jinja2Templates(directory="templates")
web_app.mount("/static", StaticFiles(directory="static"), name="static")

# Dependency to get the database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Authentication function
def authenticate(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = os.environ.get("ADMIN_USERNAME", "admin")
    correct_password = os.environ.get("ADMIN_PASSWORD", "admin")
    
    is_correct_username = secrets.compare_digest(credentials.username, correct_username)
    is_correct_password = secrets.compare_digest(credentials.password, correct_password)
    
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# Dashboard route
@web_app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, username: str = Depends(authenticate), db: Session = Depends(get_db)):
    """Main dashboard page"""
    # Get summary data
    active_licenses = crud.count_licenses_by_status(db, "active")
    expired_licenses = crud.count_licenses_by_status(db, "expired")
    revoked_licenses = crud.count_licenses_by_status(db, "revoked")
    
    total_activations = crud.count_total_activations(db)
    active_activations = crud.count_active_activations(db)
    
    # Get recent licenses
    recent_licenses = crud.get_licenses(db, skip=0, limit=5)
    
    # Get recent activations
    recent_activations = crud.get_recent_activations(db, limit=5)
    
    # Get license expiring soon
    expiring_soon = crud.get_licenses_expiring_soon(db, days=7)
    
    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        "username": username,
        "active_licenses": active_licenses,
        "expired_licenses": expired_licenses,
        "revoked_licenses": revoked_licenses,
        "total_activations": total_activations,
        "active_activations": active_activations,
        "recent_licenses": recent_licenses,
        "recent_activations": recent_activations,
        "expiring_soon": expiring_soon,
        "now": datetime.utcnow()
    })

# Licenses routes
@web_app.get("/licenses", response_class=HTMLResponse)
async def list_licenses(
    request: Request,
    page: int = 1,
    status: Optional[str] = None,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """List all licenses with optional filtering"""
    page_size = 20
    skip = (page - 1) * page_size

    licenses = crud.get_licenses_filtered(db, status=status, skip=skip, limit=page_size)
    total_licenses = crud.count_licenses_filtered(db, status=status)

    total_pages = (total_licenses + page_size - 1) // page_size

    # Fetch products and clients for dropdowns
    products = crud.get_products(db)
    clients = crud.get_clients(db)

    return templates.TemplateResponse(request=request, name="licenses.html", context={
        "username": username,
        "licenses": licenses,
        "page": page,
        "total_pages": total_pages,
        "status_filter": status,
        "now": datetime.utcnow(),
        "products": products,  # Pass products to template
        "clients": clients,    # Pass clients to template
        "product_filter": None, # Initialize product filter
        "client_filter": None  # Initialize client filter
    })

# IMPORTANT: Route for creating a new license BEFORE the route with parameter
@web_app.get("/licenses/new", response_class=HTMLResponse)
async def new_license_form(
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Form to create a new license"""
    # Get clients and products for dropdown
    clients = crud.get_clients(db)
    products = crud.get_products(db)
    
    return templates.TemplateResponse(request=request, name="license_form.html", context={
        "username": username,
        "clients": clients,
        "products": products,
        "license": None  # No existing license data
    })

@web_app.post("/licenses/new", response_class=HTMLResponse)
async def create_license(
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Create a new license using product-specific settings"""
    form = await request.form()
    
    # Get product to access its license settings
    product_id = int(form.get("product_id"))
    product = crud.get_product_by_id(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Parse JSON features
    features_json = form.get("features", "{}")
    try:
        features = json.loads(features_json)
    except json.JSONDecodeError:
        features = {}
    
    # Get expiration date
    expires_at = None
    if form.get("expires_at") and form.get("expires_at").strip():
        expires_at = datetime.fromisoformat(form.get("expires_at"))
    
    # Use product's default max activations if not specified
    max_activations = form.get("max_activations")
    if not max_activations or max_activations.strip() == "":
        max_activations = product.default_max_activations
    else:
        max_activations = int(max_activations)
    
    # Create license data object
    license_data = schemas.LicenseCreate(
        product_id=product_id,
        client_id=int(form.get("client_id")),
        status=form.get("status", "active"),
        max_activations=max_activations,
        expires_at=expires_at,
        features=features
    )
    
    # Generate a new license key with product-specific format
    license_key = create_license_key(product.license_key_format)
    
    # Create license
    new_license = crud.create_license(db, license_data, license_key)
    
    # Send email notification if enabled
    try:
        from email_integration import send_license_created_email
        send_license_created_email(db, new_license.license_id)
    except Exception as e:
        # Log the error but don't prevent the license from being created
        logger.error(f"Error sending license creation email: {str(e)}")
    
    # Redirect to license detail page
    return RedirectResponse(f"/licenses/{new_license.license_id}", status_code=303)

@web_app.get("/licenses/{license_id}", response_class=HTMLResponse)
async def view_license(
    license_id: int,
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """View license details"""
    license_data = crud.get_license_by_id(db, license_id)
    if not license_data:
        raise HTTPException(status_code=404, detail="License not found")
    
    activations = crud.get_activations_by_license(db, license_id)
    
    return templates.TemplateResponse(request=request, name="license_detail.html", context={
        "username": username,
        "license": license_data,
        "activations": activations,
        "now": datetime.utcnow()
    })

@web_app.get("/licenses/{license_id}/edit", response_class=HTMLResponse)
async def edit_license_form(
    license_id: int,
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Form to edit an existing license"""
    license_data = crud.get_license_by_id(db, license_id)
    if not license_data:
        raise HTTPException(status_code=404, detail="License not found")
    
    # Get clients and products for dropdown
    clients = crud.get_clients(db)
    products = crud.get_products(db)
    
    return templates.TemplateResponse(request=request, name="license_form.html", context={
        "username": username,
        "license": license_data,
        "clients": clients,
        "products": products
    })

@web_app.post("/licenses/{license_id}/edit", response_class=HTMLResponse)
async def update_license_handler(
    license_id: int,
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Update an existing license"""
    license_data = crud.get_license_by_id(db, license_id)
    if not license_data:
        raise HTTPException(status_code=404, detail="License not found")
    
    form = await request.form()
    
    # Parse JSON features
    features_json = form.get("features", "{}")
    try:
        features = json.loads(features_json)
    except json.JSONDecodeError:
        features = {}
    
    # Get expiration date
    expires_at = None
    if form.get("expires_at") and form.get("expires_at").strip():
        expires_at = datetime.fromisoformat(form.get("expires_at"))
    
    # Create license update data
    license_update = schemas.LicenseUpdate(
        product_id=int(form.get("product_id")),
        client_id=int(form.get("client_id")),
        status=form.get("status", "active"),
        max_activations=int(form.get("max_activations", 1)),
        expires_at=expires_at,
        features=features
    )
    
    # Update license
    updated_license = crud.update_license(db, license_id, license_update)
    
    # Redirect to license detail page
    return RedirectResponse(f"/licenses/{license_id}", status_code=303)

@web_app.post("/licenses/{license_id}/delete", response_class=HTMLResponse)
async def delete_license_handler(
    license_id: int,
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Delete a license"""
    license_data = crud.get_license_by_id(db, license_id)
    if not license_data:
        raise HTTPException(status_code=404, detail="License not found")
    
    # Delete license
    success = crud.delete_license(db, license_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete license")
    
    # Redirect to licenses list
    return RedirectResponse("/licenses", status_code=303)

@web_app.post("/licenses/{license_id}/revoke", response_class=HTMLResponse)
async def revoke_license_handler(
    license_id: int,
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Revoke a license"""
    license_data = crud.get_license_by_id(db, license_id)
    if not license_data:
        raise HTTPException(status_code=404, detail="License not found")
    
    # Update license status
    crud.update_license_status(db, license_id, "revoked")
    
    # Send email notification if enabled
    try:
        from email_integration import send_license_status_changed_email
        send_license_status_changed_email(
            db, 
            license_id, 
            "revoked", 
            "License has been revoked by administrator."
        )
    except Exception as e:
        # Log the error but don't prevent the status change
        logger.error(f"Error sending license status change email: {str(e)}")
    
    # Redirect to license detail page
    return RedirectResponse(f"/licenses/{license_id}", status_code=303)

@web_app.post("/licenses/{license_id}/reactivate", response_class=HTMLResponse)
async def reactivate_license_handler(
    license_id: int,
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Reactivate a license"""
    license_data = crud.get_license_by_id(db, license_id)
    if not license_data:
        raise HTTPException(status_code=404, detail="License not found")
    
    # Update license status
    crud.update_license_status(db, license_id, "active")
    
    # Send email notification if enabled
    try:
        from email_integration import send_license_status_changed_email
        send_license_status_changed_email(
            db, 
            license_id, 
            "reactivated", 
            "License has been reactivated by administrator."
        )
    except Exception as e:
        # Log the error but don't prevent the status change
        logger.error(f"Error sending license status change email: {str(e)}")
    
    # Redirect to license detail page
    return RedirectResponse(f"/licenses/{license_id}", status_code=303)

@web_app.post("/activations/{activation_id}/deactivate", response_class=HTMLResponse)
async def deactivate_activation_handler(
    activation_id: int,
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Deactivate a license activation"""
    activation = crud.get_activation_by_id(db, activation_id)
    if not activation:
        raise HTTPException(status_code=404, detail="Activation not found")
    
    # Deactivate activation
    crud.deactivate_license(db, activation_id)
    
    # Redirect back to license detail
    return RedirectResponse(f"/licenses/{activation.license_id}", status_code=303)

@web_app.post("/activations/{activation_id}/reactivate", response_class=HTMLResponse)
async def reactivate_activation_handler(
    activation_id: int,
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Reactivate a license activation"""
    activation = crud.get_activation_by_id(db, activation_id)
    if not activation:
        raise HTTPException(status_code=404, detail="Activation not found")
    
    # Reactivate activation
    crud.reactivate_license(db, activation_id)
    
    # Redirect back to license detail
    return RedirectResponse(f"/licenses/{activation.license_id}", status_code=303)

# Client routes
# IMPORTANT: Route for creating a new client BEFORE any route with client_id parameter
@web_app.get("/clients/new", response_class=HTMLResponse)
async def new_client_form(
    request: Request,
    username: str = Depends(authenticate)
):
    """Form to create a new client"""
    return templates.TemplateResponse(request=request, name="client_form.html", context={
        "username": username,
        "client": None  # No existing client data
    })

@web_app.post("/clients/new", response_class=HTMLResponse)
async def create_client(
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Create a new client"""
    form = await request.form()
    
    # Parse JSON contact_info
    contact_info_json = form.get("contact_info", "{}")
    try:
        contact_info = json.loads(contact_info_json)
    except json.JSONDecodeError:
        contact_info = {}
    
    # Create client data object
    client_data = schemas.ClientCreate(
        name=form.get("name"),
        email=form.get("email"),
        company=form.get("company"),
        contact_info=contact_info
    )
    
    # Create client with duplicate checking
    client_result = crud.create_client(db, client_data)
    
    # If client already existed, you might want to add a flash message
    if client_result['existing']:
        # You could add a session flash message or pass a query parameter
        return RedirectResponse(
            f"/clients/{client_result['client_id']}?message=existing_client", 
            status_code=303
        )
    
    # Redirect to client details for the new or existing client
    return RedirectResponse(f"/clients/{client_result['client_id']}", status_code=303)

# Update the list_clients route in web_gui.py to handle search functionality
@web_app.get("/clients", response_class=HTMLResponse)
async def list_clients(
    request: Request,
    page: int = 1,
    search: Optional[str] = None,  # Add search parameter
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """List all clients with optional search"""
    page_size = 20
    skip = (page - 1) * page_size
    
    # Base query for clients
    query = db.query(models.Client)
    
    # Apply search filter if provided
    if search and search.strip():
        search_term = f"%{search.strip()}%"
        query = query.filter(
            # Search in name, email, or company columns
            or_(  # Use the imported or_ function here
                models.Client.name.ilike(search_term),
                models.Client.email.ilike(search_term),
                models.Client.company.ilike(search_term)
            )
        )
    
    # Get total count for pagination
    total_clients = query.count()
    
    # Get paginated results
    clients = query.offset(skip).limit(page_size).all()
    
    total_pages = (total_clients + page_size - 1) // page_size
    
    return templates.TemplateResponse(request=request, name="clients.html", context={
        "username": username,
        "clients": clients,
        "page": page,
        "total_pages": total_pages,
        "search": search,  # Pass search term back to template
    })

@web_app.get("/clients/{client_id}", response_class=HTMLResponse)
async def view_client(
    client_id: int,
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """View client details"""
    client = crud.get_client_by_id(db, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    return templates.TemplateResponse(request=request, name="client_detail.html", context={
        "username": username,
        "client": client
    })

@web_app.get("/clients/{client_id}/edit", response_class=HTMLResponse)
async def edit_client_form(
    client_id: int,
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Form to edit an existing client"""
    client = crud.get_client_by_id(db, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    return templates.TemplateResponse(request=request, name="client_form.html", context={
        "username": username,
        "client": client
    })

@web_app.post("/clients/{client_id}/edit", response_class=HTMLResponse)
async def update_client(
    client_id: int,
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Update an existing client"""
    client = crud.get_client_by_id(db, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    form = await request.form()
    
    # Parse JSON contact_info
    contact_info_json = form.get("contact_info", "{}")
    try:
        contact_info = json.loads(contact_info_json)
    except json.JSONDecodeError:
        contact_info = {}
    
    # Create client update data
    client_data = schemas.ClientCreate(
        name=form.get("name"),
        email=form.get("email"),
        company=form.get("company"),
        contact_info=contact_info
    )
    
    # Update client
    crud.update_client(db, client_id, client_data)
    
    # Redirect to clients list
    return RedirectResponse("/clients", status_code=303)

@web_app.post("/clients/{client_id}/delete", response_class=HTMLResponse)
async def delete_client(
    client_id: int,
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Delete a client"""
    client = crud.get_client_by_id(db, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    # Delete client
    crud.delete_client(db, client_id)
    
    # Redirect to clients list
    return RedirectResponse("/clients", status_code=303)

# Products routes - Fixed same routing issue here too
@web_app.get("/products/new", response_class=HTMLResponse)
async def new_product_form(
    request: Request,
    username: str = Depends(authenticate)
):
    """Form to create a new product"""
    return templates.TemplateResponse(request=request, name="product_form.html", context={
        "username": username,
        "product": None  # No existing product data
    })

@web_app.get("/products", response_class=HTMLResponse)
async def list_products(
    request: Request,
    page: int = 1,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """List all products"""
    page_size = 20
    skip = (page - 1) * page_size
    
    products = crud.get_products(db, skip=skip, limit=page_size)
    total_products = crud.count_products(db)
    
    total_pages = (total_products + page_size - 1) // page_size
    
    return templates.TemplateResponse(request=request, name="products.html", context={
        "username": username,
        "products": products,
        "page": page,
        "total_pages": total_pages
    })

@web_app.post("/products/new", response_class=HTMLResponse)
async def create_product(
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Create a new product with license settings"""
    form = await request.form()
    
    # Parse JSON features
    features_json = form.get("features", "{}")
    try:
        features = json.loads(features_json)
    except json.JSONDecodeError:
        features = {}
    
    # Get form data with defaults
    default_max_activations = int(form.get("default_max_activations", 1))
    license_key_format = form.get("license_key_format", "XXXX-XXXX-XXXX-XXXX")
    heartbeat_interval = int(form.get("heartbeat_interval", 24))
    auto_deactivate_days = int(form.get("auto_deactivate_days", 30))
    # Checkbox returns 'on' if checked, None if not checked
    enforce_hardware_check = form.get("enforce_hardware_check") == "on"
    
    # Create product data object
    product_data = schemas.ProductCreate(
        name=form.get("name"),
        version=form.get("version"),
        features=features,
        default_max_activations=default_max_activations,
        license_key_format=license_key_format,
        heartbeat_interval=heartbeat_interval,
        auto_deactivate_days=auto_deactivate_days,
        enforce_hardware_check=enforce_hardware_check
    )
    
    # Create product
    product = crud.create_product(db, product_data)
    
    # Redirect to products list
    return RedirectResponse("/products", status_code=303)

@web_app.get("/products/{product_id}", response_class=HTMLResponse)
async def view_product(
    product_id: int,
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """View product details"""
    product = crud.get_product_by_id(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    return templates.TemplateResponse(request=request, name="product_detail.html", context={
        "username": username,
        "product": product
    })

@web_app.get("/products/{product_id}/edit", response_class=HTMLResponse)
async def edit_product_form(
    product_id: int,
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Form to edit an existing product"""
    product = crud.get_product_by_id(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    return templates.TemplateResponse(request=request, name="product_form.html", context={
        "username": username,
        "product": product
    })

@web_app.post("/products/{product_id}/edit", response_class=HTMLResponse)
async def update_product(
    product_id: int,
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Update an existing product with license settings"""
    product = crud.get_product_by_id(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    form = await request.form()
    
    # Parse JSON features
    features_json = form.get("features", "{}")
    try:
        features = json.loads(features_json)
    except json.JSONDecodeError:
        features = {}
    
    # Get form data with defaults
    default_max_activations = int(form.get("default_max_activations", 1))
    license_key_format = form.get("license_key_format", "XXXX-XXXX-XXXX-XXXX")
    heartbeat_interval = int(form.get("heartbeat_interval", 24))
    auto_deactivate_days = int(form.get("auto_deactivate_days", 30))
    # Checkbox returns 'on' if checked, None if not checked
    enforce_hardware_check = form.get("enforce_hardware_check") == "on"
    
    # Create product update data
    product_data = schemas.ProductCreate(
        name=form.get("name"),
        version=form.get("version"),
        features=features,
        default_max_activations=default_max_activations,
        license_key_format=license_key_format,
        heartbeat_interval=heartbeat_interval,
        auto_deactivate_days=auto_deactivate_days,
        enforce_hardware_check=enforce_hardware_check
    )
    
    # Update product
    crud.update_product(db, product_id, product_data)
    
    # Redirect to product details
    return RedirectResponse(f"/products/{product_id}", status_code=303)

@web_app.post("/products/{product_id}/delete", response_class=HTMLResponse)
async def delete_product(
    product_id: int,
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Delete a product"""
    product = crud.get_product_by_id(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Delete product
    crud.delete_product(db, product_id)
    
    # Redirect to products list
    return RedirectResponse("/products", status_code=303)

# reports route
@web_app.get("/reports", response_class=HTMLResponse)
async def reports_page(
    request: Request,
    product_id: Optional[str] = None,  # Changed from int to str
    client_id: Optional[str] = None,   # Changed from int to str
    date_range: Optional[str] = "30",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Reports dashboard page with filtering capabilities"""
    # Convert string IDs to integers if they're not empty
    product_id_int = None
    if product_id and product_id.strip():
        try:
            product_id_int = int(product_id)
        except ValueError:
            pass
    
    client_id_int = None
    if client_id and client_id.strip():
        try:
            client_id_int = int(client_id)
        except ValueError:
            pass
    
    # Process date range
    start_date_obj = None
    end_date_obj = datetime.utcnow()
    
    if date_range == "custom" and start_date:
        # Parse custom date range
        start_date_obj = datetime.fromisoformat(start_date)
        if end_date:
            end_date_obj = datetime.fromisoformat(end_date)
    elif date_range != "custom":
        # Calculate start date based on selected range (days)
        days = int(date_range)
        start_date_obj = datetime.utcnow() - timedelta(days=days)
    
    # Get filtered license statistics
    license_stats = {
        "active": 0,
        "expired": 0,
        "revoked": 0,
        "total": 0
    }
    
    # Build query for licenses
    license_query = db.query(models.License)
    if product_id_int:
        license_query = license_query.filter(models.License.product_id == product_id_int)
    if client_id_int:
        license_query = license_query.filter(models.License.client_id == client_id_int)
    
    # Count by status
    licenses = license_query.all()
    for license in licenses:
        license_stats["total"] += 1
        if license.status == "active":
            license_stats["active"] += 1
        elif license.status == "expired":
            license_stats["expired"] += 1
        elif license.status == "revoked":
            license_stats["revoked"] += 1
    
    # Get activation history for chart
    activation_history_query = db.query(
        func.date(models.Activation.first_activated).label('date'),
        func.count(models.Activation.activation_id).label('count')
    )
    
    # Filter activations
    if product_id_int or client_id_int:
        activation_history_query = activation_history_query.join(
            models.License, models.License.license_id == models.Activation.license_id
        )
        
        if product_id_int:
            activation_history_query = activation_history_query.filter(
                models.License.product_id == product_id_int
            )
        if client_id_int:
            activation_history_query = activation_history_query.filter(
                models.License.client_id == client_id_int
            )
    
    # Apply date range filter
    if start_date_obj:
        activation_history_query = activation_history_query.filter(
            models.Activation.first_activated >= start_date_obj
        )
    if end_date_obj:
        activation_history_query = activation_history_query.filter(
            models.Activation.first_activated <= end_date_obj
        )
    
    # Group and order
    activation_history = activation_history_query.group_by(
        func.date(models.Activation.first_activated)
    ).order_by(
        func.date(models.Activation.first_activated)
    ).all()
    
    # Convert to list of dictionaries
    activation_history_list = [
        {"date": item.date.strftime('%Y-%m-%d'), "count": item.count}
        for item in activation_history
    ]
    
    # Get product statistics
    product_stats = []
    
    # If a specific product is selected, only include that product
    products_to_include = []
    if product_id_int:
        product = crud.get_product_by_id(db, product_id_int)
        if product:
            products_to_include = [product]
    else:
        products_to_include = crud.get_products(db)
    
    for product in products_to_include:
        if product:  # Ensure product exists
            # Filter licenses for this product
            product_licenses = db.query(models.License).filter(
                models.License.product_id == product.product_id
            )
            
            if client_id_int:
                product_licenses = product_licenses.filter(
                    models.License.client_id == client_id_int
                )
            
            # Get counts
            total_licenses = product_licenses.count()
            active_licenses = product_licenses.filter(
                models.License.status == "active"
            ).count()
            
            # Get activations
            product_activations_query = db.query(models.Activation).join(
                models.License, models.License.license_id == models.Activation.license_id
            ).filter(
                models.License.product_id == product.product_id
            )
            
            if client_id_int:
                product_activations_query = product_activations_query.filter(
                    models.License.client_id == client_id_int
                )
                
            if start_date_obj:
                product_activations_query = product_activations_query.filter(
                    models.Activation.first_activated >= start_date_obj
                )
            if end_date_obj:
                product_activations_query = product_activations_query.filter(
                    models.Activation.first_activated <= end_date_obj
                )
                
            total_activations = product_activations_query.count()
            active_activations = product_activations_query.filter(
                models.Activation.is_active == True
            ).count()
            
            # Add to stats
            product_stats.append({
                "name": product.name,
                "total_licenses": total_licenses,
                "active_licenses": active_licenses,
                "total_activations": total_activations,
                "active_activations": active_activations
            })
    
    # Get all products and clients for filter dropdowns
    all_products = crud.get_products(db)
    all_clients = crud.get_clients(db)
    
    return templates.TemplateResponse(request=request, name="reports.html", context={
        "username": username,
        "license_stats": license_stats,
        "activation_history": activation_history_list,
        "product_stats": product_stats,
        "products": all_products,
        "clients": all_clients,
        "product_id": product_id,
        "client_id": client_id,
        "date_range": date_range,
        "start_date": start_date,
        "end_date": end_date
    })

# API Keys management 
@web_app.get("/api-keys/new", response_class=HTMLResponse)
async def new_api_key_form(
    request: Request,
    username: str = Depends(authenticate)
):
    """Form to create a new API key"""
    # Calculate default expiration date (180 days from today)
    from datetime import datetime, timedelta
    default_expiration = datetime.utcnow() + timedelta(days=180)
    
    return templates.TemplateResponse(request=request, name="api_key_form.html", context={
        "username": username,
        "new_api_key": None,
        "default_expiration": default_expiration  # Ensure this is passed
    })

@web_app.get("/api-keys", response_class=HTMLResponse)
async def list_api_keys(
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """List all API keys"""
    api_keys = crud.get_api_keys(db)
    
    return templates.TemplateResponse(request=request, name="api_keys.html", context={
        "username": username,
        "api_keys": api_keys,
        "now": datetime.utcnow()
    })

@web_app.post("/api-keys/new", response_class=HTMLResponse)
async def create_api_key(
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Create a new API key"""
    form = await request.form()
    
    name = form.get("name")
    key_type = form.get("key_type", "client")
    expires_at_str = form.get("expires_at")
    
    expires_at = None
    if expires_at_str:
        expires_at = datetime.fromisoformat(expires_at_str)
    
    api_key, api_key_obj = crud.create_api_key(db, name=name, key_type=key_type, expires_at=expires_at)
    
    # Calculate default expiration date (180 days from today)
    default_expiration = datetime.utcnow() + timedelta(days=180)
    
    return templates.TemplateResponse(request=request, name="api_key_form.html", context={
        "username": username,
        "new_api_key": api_key,
        "default_expiration": default_expiration  # Ensure this is passed
    })

@web_app.post("/api-keys/{key_id}/deactivate", response_class=HTMLResponse)
async def deactivate_api_key(
    key_id: int,
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Deactivate an API key"""
    success = crud.deactivate_api_key(db, key_id)
    if not success:
        raise HTTPException(status_code=404, detail="API key not found")
    
    return RedirectResponse("/api-keys", status_code=303)

@web_app.post("/api-keys/{key_id}/reactivate", response_class=HTMLResponse)
async def reactivate_api_key(
    key_id: int,
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Reactivate an API key"""
    success = crud.reactivate_api_key(db, key_id)
    if not success:
        raise HTTPException(status_code=404, detail="API key not found")
    
    return RedirectResponse("/api-keys", status_code=303)

@web_app.post("/api-keys/{key_id}/delete", response_class=HTMLResponse)
async def delete_api_key(
    key_id: int,
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Delete an API key"""
    success = crud.delete_api_key(db, key_id)
    if not success:
        raise HTTPException(status_code=404, detail="API key not found")
    
    return RedirectResponse("/api-keys", status_code=303)

#  settings routes
@web_app.post("/settings/admin", response_class=HTMLResponse)
async def update_admin_settings(
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Update admin account settings"""
    form = await request.form()
    
    admin_username = form.get("admin_username")
    new_password = form.get("new_password")
    confirm_password = form.get("confirm_password")
    
    # Validate input
    if new_password and new_password != confirm_password:
        # Return error message
        return templates.TemplateResponse(request=request, name="settings.html", context={
            "username": username,
            "admin_username": admin_username,
            "email_settings": None,
            "license_settings": None,
            "system_settings": None,
            "error_message": "New password and confirmation do not match."
        })
    
    # Update admin credentials in environment variables or config file
    # Note: This is a simplified example. In a real application, you would update a database or config file
    if admin_username:
        os.environ["ADMIN_USERNAME"] = admin_username
    
    if new_password:
        os.environ["ADMIN_PASSWORD"] = new_password
    
    # Redirect back to settings page
    return RedirectResponse("/settings", status_code=303)

@web_app.post("/settings/system", response_class=HTMLResponse)
async def update_system_settings(
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Update system settings"""
    form = await request.form()
    
    # Process system settings form data
    enable_rate_limiting = form.get("enable_rate_limiting") == "on"
    rate_limit = form.get("rate_limit", "60")
    enable_audit_log = form.get("enable_audit_log") == "on"
    log_retention_days = form.get("log_retention_days", "90")
    enable_ip_geolocation = form.get("enable_ip_geolocation") == "on"
    
    # Save settings to database
    crud.update_system_setting(db, "enable_rate_limiting", str(enable_rate_limiting).lower())
    crud.update_system_setting(db, "rate_limit", rate_limit)
    crud.update_system_setting(db, "enable_audit_log", str(enable_audit_log).lower())
    crud.update_system_setting(db, "log_retention_days", log_retention_days)
    crud.update_system_setting(db, "enable_ip_geolocation", str(enable_ip_geolocation).lower())
    
    # Redirect back to settings page
    return RedirectResponse("/settings", status_code=303)

# Audit log
@web_app.get("/audit-log", response_class=HTMLResponse)
async def audit_log(
    request: Request,
    page: int = 1,
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    date_range: Optional[str] = "7",
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """View audit log with filtering"""
    page_size = 50
    skip = (page - 1) * page_size
    
    # Handle date range filtering
    start_date = None
    if date_range and date_range != "all":
        days = int(date_range)
        start_date = datetime.utcnow() - timedelta(days=days)
    
    # Get filtered logs
    logs = crud.get_audit_logs(
        db, 
        skip=skip, 
        limit=page_size, 
        action=action, 
        entity_type=entity_type, 
        start_date=start_date
    )
    
    # Count total filtered logs for pagination
    total_logs = crud.count_audit_logs(
        db,
        action=action,
        entity_type=entity_type,
        start_date=start_date
    )
    
    total_pages = (total_logs + page_size - 1) // page_size
    
    return templates.TemplateResponse(request=request, name="audit_log.html", context={
        "username": username,
        "logs": logs,
        "page": page,
        "total_pages": total_pages,
        "action_filter": action,
        "entity_type_filter": entity_type,
        "date_range_filter": date_range
    })

# Settings page
@web_app.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Settings page with comprehensive settings retrieval"""
    # Get system settings from database
    system_settings_dict = crud.get_system_settings_dict(db)
    
    logger.debug("ALL SYSTEM SETTINGS RETRIEVED:")
    for key, value in system_settings_dict.items():
        if key.startswith("email_"):
            masked_value = (value[:3] + "****") if len(value) > 3 else "****"
            logger.debug(f"{key}: {masked_value}")

    # Explicit password handling for SMTP password
    raw_smtp_password = system_settings_dict.get("email_smtp_password", "")
    logger.debug("Raw SMTP Password Check:")
    logger.debug(f"Raw SMTP Password: {raw_smtp_password}")
    logger.debug(f"Password Length: {len(raw_smtp_password)}")
    logger.debug(f"Password Exists: {bool(raw_smtp_password)}")
    
    if raw_smtp_password:
        masked_smtp_password = "********"
    else:
        masked_smtp_password = ""
    
    # Convert string values to appropriate types
    system_settings = {
        "enable_rate_limiting": system_settings_dict.get("enable_rate_limiting", "false") == "true",
        "rate_limit": int(system_settings_dict.get("rate_limit", "60")),
        "enable_audit_log": system_settings_dict.get("enable_audit_log", "true") == "true",
        "log_retention_days": int(system_settings_dict.get("log_retention_days", "90")),
        "enable_ip_geolocation": system_settings_dict.get("enable_ip_geolocation", "false") == "true"
    }
    
    # Comprehensive email settings parsing
    email_settings = {
        # SMTP Settings
        "smtp_server": system_settings_dict.get("email_smtp_server", ""),
        "smtp_port": system_settings_dict.get("email_smtp_port", "587"),
        "smtp_username": system_settings_dict.get("email_smtp_username", ""),
        "sender_email": system_settings_dict.get("email_sender_email", ""),
        "admin_email": system_settings_dict.get("email_admin_email", ""),
        "smtp_password": masked_smtp_password,
        "use_tls": system_settings_dict.get("email_use_tls", "true") == "true",
        
        # Notification Settings
        "enable_license_notifications": system_settings_dict.get("email_enable_license_notifications", "false") == "true",
        "enable_expiration_warnings": system_settings_dict.get("email_enable_expiration_warnings", "false") == "true",
        "enable_status_notifications": system_settings_dict.get("email_enable_status_notifications", "false") == "true",
        "enable_unusual_activity_alerts": system_settings_dict.get("email_enable_unusual_activity_alerts", "false") == "true",
        "email_report_frequency": system_settings_dict.get("email_report_frequency", "never")
    }
    
    # Additional system information for page
    active_licenses = crud.count_licenses_by_status(db, "active")
    active_activations = crud.count_active_activations(db)
    last_report_run = None  # You might want to track this separately
    email_scheduler_running = email_scheduler is not None and email_scheduler.scheduler_thread is not None
    
    return templates.TemplateResponse(request=request, name="settings.html", context={
        "username": username,
        "admin_username": os.environ.get("ADMIN_USERNAME", "admin"),
        "email_settings": email_settings,
        "system_settings": system_settings,
        "active_licenses": active_licenses,
        "active_activations": active_activations,
        "last_report_run": last_report_run,
        "email_scheduler_running": email_scheduler_running
    })

@web_app.post("/settings/email", response_class=HTMLResponse)
async def update_email_settings(
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Update email notification settings with comprehensive logging and saving"""
    form = await request.form()
    
    logger.debug("FORM DATA RECEIVED:")
    for key, value in form.items():
        logger.debug(f"{key}: {value}")
    
    # Process email settings form data
    # SMTP server settings
    smtp_server = form.get("smtp_server", "")
    smtp_port = form.get("smtp_port", "587")
    smtp_username = form.get("smtp_username", "")
    smtp_password = form.get("smtp_password", "")
    sender_email = form.get("sender_email", "")
    admin_email = form.get("admin_email", "")
    use_tls = form.get("use_tls") == "on"
    
    # Email notification settings
    enable_license_notifications = form.get("enable_license_notifications") == "on"
    enable_expiration_warnings = form.get("enable_expiration_warnings") == "on"
    enable_status_notifications = form.get("enable_status_notifications") == "on"
    enable_unusual_activity_alerts = form.get("enable_unusual_activity_alerts") == "on"
    email_report_frequency = form.get("email_report_frequency", "never")
    
    logger.debug("SETTINGS BEING SAVED:")
    logger.debug(f"SMTP Server: {smtp_server}")
    logger.debug(f"Admin Email: {admin_email}")
    logger.debug(f"License Notifications: {enable_license_notifications}")
    logger.debug(f"Expiration Warnings: {enable_expiration_warnings}")
    logger.debug(f"Report Frequency: {email_report_frequency}")
    
    # COMPREHENSIVE SETTINGS SAVE
    settings_to_save = {
        "email_smtp_server": smtp_server,
        "email_smtp_port": smtp_port,
        "email_smtp_username": smtp_username,
        "email_sender_email": sender_email,
        "email_admin_email": admin_email,
        "email_use_tls": str(use_tls).lower(),
        
        # Notification settings
        "email_enable_license_notifications": str(enable_license_notifications).lower(),
        "email_enable_expiration_warnings": str(enable_expiration_warnings).lower(),
        "email_enable_status_notifications": str(enable_status_notifications).lower(),
        "email_enable_unusual_activity_alerts": str(enable_unusual_activity_alerts).lower(),
        "email_report_frequency": email_report_frequency
    }
    
    # Only update password if provided (don't overwrite with empty string)
    if smtp_password:
        settings_to_save["email_smtp_password"] = smtp_password
    
    # Save ALL settings
    for key, value in settings_to_save.items():
        try:
            crud.update_system_setting(db, key, value)
            logger.info(f"Saved setting: {key} = {value}")
        except Exception as e:
            logger.error(f"Error saving setting {key}: {str(e)}")
    
    # Commit changes
    db.commit()
    
    # Attempt SMTP connection test if all necessary details are present
    try:
        from email_integration import create_email_sender
        email_sender = create_email_sender(db)
        
        if email_sender and admin_email:
            test_success = email_sender.send_email(
                admin_email,
                "License Server - Email Settings Test",
                "Your email settings have been updated successfully.",
                "<html><body><h1>Email Settings Test</h1><p>Your email settings have been updated successfully.</p></body></html>"
            )
            
            if test_success:
                logger.info("Test email sent successfully!")
            else:
                logger.error("Failed to send test email.")
    except Exception as e:
        logger.error(f"Error testing email settings: {str(e)}")
    
    # Redirect back to settings page with a message
    return RedirectResponse("/settings?message=settings_updated", status_code=303)

# Logout route
@web_app.get("/logout", response_class=HTMLResponse)
async def logout():
    """Log out the user"""
    response = RedirectResponse(url="/", status_code=303)
    response.headers["WWW-Authenticate"] = "Basic"
    return response

# Removed import of test_email_route to prevent duplicate /settings/email/test route

@web_app.get("/settings/email/test", response_class=HTMLResponse)
def email_test_route(
    request: Request,
    username: str = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Route for testing email settings"""
    try:
        # Import email integration
        from email_integration import create_email_sender
        
        # Import system settings retrieval
        from db import crud
        
        # Get email settings
        system_settings_dict = crud.get_system_settings_dict(db)
        
        # Extract email settings
        email_settings = {
            'smtp_server': system_settings_dict.get('email_smtp_server', ''),
            'smtp_port': system_settings_dict.get('email_smtp_port', '587'),
            'smtp_username': system_settings_dict.get('email_smtp_username', ''),
            'smtp_password': system_settings_dict.get('email_smtp_password', ''),
            'sender_email': system_settings_dict.get('email_sender_email', ''),
            'use_tls': system_settings_dict.get('email_use_tls', 'true') == 'true',
            'admin_email': system_settings_dict.get('email_admin_email', '')
        }
        
        admin_email = email_settings.get('admin_email')
        
        # Create email sender
        email_sender = create_email_sender(db)
        
        if not email_sender:
            # Return error page
            return templates.TemplateResponse(request=request, name="email_test_result.html", context={
                "username": username,
                "success": False,
                "message": "Failed to create email sender. Please check your SMTP settings."
            })
        
        if not admin_email:
            # Return error page
            return templates.TemplateResponse(request=request, name="email_test_result.html", context={
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
        return templates.TemplateResponse(request=request, name="email_test_result.html", context={
            "username": username,
            "success": success,
            "message": "Test email sent successfully. Please check your inbox." if success else "Failed to send test email. Please check your SMTP settings."
        })
    
    except Exception as e:
        # Return error page
        return templates.TemplateResponse(request=request, name="email_test_result.html", context={
            "username": username,
            "success": False,
            "message": f"Error testing email settings: {str(e)}"
        })

if __name__ == "__main__":
    # Get host from environment or default to 127.0.0.1 for local development
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run(web_app, host=host, port=8080)