# handlers/stripe_handler.py
import json
import logging
import stripe # Import the Stripe SDK
from typing import Dict, Any, Optional, Tuple, Union
from datetime import datetime, timedelta
from fastapi import Request, Response, status
from sqlalchemy.orm import Session

from handlers.base_handler import WebhookHandler
from db import crud, models, schemas
from security import create_license_key

# Configure logging
logger = logging.getLogger("stripe_handler")

class StripeWebhookHandler(WebhookHandler):
    """
    Webhook handler for Stripe payment events.
    """
    
    @property
    def provider_name(self) -> str:
        return "stripe"
    
    async def validate_signature(self, request: Request, webhook_secret: str) -> bool:
        """
        Validate the Stripe webhook signature.
        
        Args:
            request: The incoming FastAPI request
            webhook_secret: The Stripe webhook signing secret
            
        Returns:
            bool: True if signature is valid, False otherwise
        """
        try:
            # Get the signature from header
            signature = request.headers.get("stripe-signature")
            if not signature:
                logger.warning("No Stripe signature found in request headers")
                return False
            
            # Get the raw body for verification
            payload = await request.body()
            
            # Construct the event to verify signature
            # This will raise an error if the signature is invalid
            stripe.Webhook.construct_event(
                payload, signature, webhook_secret
            )
            
            return True
        except stripe.error.SignatureVerificationError as e:
            logger.warning(f"Invalid Stripe signature: {str(e)}")
            return False
        except Exception as e:
            logger.exception(f"Error validating Stripe signature: {str(e)}")
            return False
    
    async def parse_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse the Stripe webhook event.
        
        Args:
            payload: The raw webhook payload
            
        Returns:
            Dict: Standardized event data
        """
        event_id = payload.get("id")
        event_type = payload.get("type")
        created = payload.get("created")
        data = payload.get("data", {})
        
        # Standardize the event data
        return {
            "id": event_id,
            "type": event_type,
            "created": created,
            "data": data,
            "raw": payload
        }
    
    def _save_webhook_event(self, event_data):
        """
        Safely save the webhook event to the database with duplicate checking
        
        Args:
            event_data: The parsed event data
            
        Returns:
            models.WebhookEvent: The saved webhook event model
        """
        try:
            event_id = event_data.get("id")
            event_type = event_data.get("type")
            
            if not event_id:
                logger.warning("No event ID found in webhook data")
                event_id = f"generated_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
            
            # First check if this event already exists
            existing_event = self.db.query(models.WebhookEvent).filter(
                models.WebhookEvent.event_id == event_id
            ).first()
            
            if existing_event:
                logger.info(f"Event {event_id} already exists in database, skipping save")
                return existing_event
            
            # Create webhook event entry
            webhook_event = models.WebhookEvent(
                event_id=event_id,
                provider="stripe",
                event_type=event_type or "unknown",
                event_data=event_data.get("raw"),
                processed_at=datetime.utcnow()
            )
            
            self.db.add(webhook_event)
            self.db.commit()
            self.db.refresh(webhook_event)
            
            logger.info(f"Stripe webhook event saved with ID: {event_id}")
            return webhook_event
        
        except Exception as e:
            self.db.rollback()  # Important: rollback on error
            logger.exception(f"Error saving webhook event: {str(e)}")
            return None
    
    async def check_idempotency(self, event_id: str) -> bool:
        """
        Improved idempotency check that first queries the database
        for existing webhook events.
        
        Args:
            event_id: Unique identifier for the event
            
        Returns:
            bool: True if event was already processed, False otherwise
        """
        # First check if the event exists in our WebhookEvent table
        existing_event = self.db.query(models.WebhookEvent).filter(
            models.WebhookEvent.event_id == event_id
        ).first()
        
        if existing_event:
            logger.info(f"Event {event_id} found in database, marked as processed")
            return True
        
        # If not in database, check Redis if available
        if self.redis_client:
            # Use Redis for idempotency check
            key = f"webhook:{self.provider_name}:{event_id}"
            exists = await self.redis_client.exists(key)
            return exists
        
        return False
    
    async def mark_processed(self, event_id: str, event_data: Dict[str, Any], ttl: int = 86400 * 30) -> None:
        """
        Mark an event as processed to prevent duplicate processing.
        
        Args:
            event_id: Unique identifier for the event
            event_data: The event data to store
            ttl: Time to live in seconds (default 30 days)
        """
        if self.redis_client:
            # Use Redis to store the event ID
            key = f"webhook:{self.provider_name}:{event_id}"
            await self.redis_client.set(key, json.dumps(event_data), ex=ttl)
        
        # No need for fallback to database since we're already saving to WebhookEvent table
    
    async def handle_webhook(self, request: Request, webhook_secret: str) -> Response:
        """
        Enhanced webhook handling method with improved error handling and event storage.
        
        Args:
            request: The incoming FastAPI request
            webhook_secret: The webhook secret key for validation
            
        Returns:
            Response: HTTP response to return to the caller
        """
        try:
            # Get the raw body for signature validation
            body = await request.body()
            body_text = body.decode('utf-8')
            
            # Log the received webhook
            logger.info("Received Stripe webhook")
            logger.debug(f"Webhook body preview: {body_text[:200]}...")
            
            try:
                payload = json.loads(body_text)
            except json.JSONDecodeError:
                logger.warning("Request body is not valid JSON")
                return Response(
                    content=json.dumps({"error": "Invalid JSON payload"}),
                    status_code=status.HTTP_400_BAD_REQUEST,
                    media_type="application/json"
                )
            
            # Extract event ID early to check for duplicates
            event_id = payload.get("id")
            if not event_id:
                logger.error("No event ID found in Stripe webhook")
                return Response(
                    content=json.dumps({"error": "No event ID found"}),
                    status_code=status.HTTP_400_BAD_REQUEST,
                    media_type="application/json"
                )
                
            # Check if we've already processed this event - now using DB first
            already_processed = await self.check_idempotency(event_id)
            if already_processed:
                logger.info(f"Event {event_id} already processed, skipping")
                return Response(
                    content=json.dumps({"status": "already processed"}),
                    status_code=status.HTTP_200_OK,
                    media_type="application/json"
                )
            
            # Validate signature
            valid_signature = await self.validate_signature(request, webhook_secret)
            if not valid_signature:
                logger.warning(f"Invalid signature for Stripe webhook")
                return Response(
                    content=json.dumps({"error": "Invalid signature"}),
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    media_type="application/json"
                )
            
            # Parse the event
            event_data = await self.parse_event(payload)
            
            # Save the event to database - this now checks for duplicates internally
            webhook_event = self._save_webhook_event(event_data)
            if not webhook_event:
                logger.error("Failed to save webhook event")
                # Return 200 even if we fail to save, to avoid Stripe retries
                return Response(
                    content=json.dumps({"status": "error saving event"}),
                    status_code=status.HTTP_200_OK,
                    media_type="application/json"
                )
            
            # Process the event
            logger.info(f"Processing Stripe webhook event: {event_id}")
            result = await self.process_event(event_data)
            
            # Mark as processed in Redis if available
            if self.redis_client:
                await self.mark_processed(event_id, event_data)
            
            return Response(
                content=json.dumps({"status": "success", "result": result, "event_id": event_id}),
                status_code=status.HTTP_200_OK,
                media_type="application/json"
            )
            
        except Exception as e:
            logger.exception(f"Error processing Stripe webhook: {str(e)}")
            
            # Try to save the error
            try:
                error_event = {
                    "id": f"error_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                    "type": "error",
                    "error": str(e),
                    "raw": {"error": str(e)}
                }
                self._save_webhook_event(error_event)
            except:
                logger.exception("Failed to save error event")
            
            # Always return 200 for Stripe webhooks to prevent retries
            return Response(
                content=json.dumps({"error": "Internal server error"}),
                status_code=status.HTTP_200_OK,
                media_type="application/json"
            )
    
    async def process_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process the Stripe webhook event with improved handler capabilities.
        
        Currently handles:
        - checkout.session.completed: When a checkout is completed
        - payment_intent.succeeded: When a payment intent succeeds
        - payment_intent.created: When a payment intent is created
        - charge.succeeded: When a charge succeeds
        - charge.updated: When a charge is updated
        
        Args:
            event_data: The standardized event data
            
        Returns:
            Dict: Processing result
        """
        event_type = event_data.get("type")
        data = event_data.get("data", {})
        
        result = {
            "success": False,
            "action": "none",
            "details": {}
        }
        
        try:
            # Core purchase/checkout events
            if event_type == "checkout.session.completed":
                result = await self._handle_checkout_completed(data)
            elif event_type == "payment_intent.succeeded":
                result = await self._handle_payment_intent_succeeded(data)
            elif event_type == "payment_intent.created":
                result = await self._handle_payment_intent_created(data)
            # Charge related events
            elif event_type == "charge.succeeded":
                result = await self._handle_charge_succeeded(data)
            elif event_type == "charge.updated":
                result = await self._handle_charge_updated(data)
            # Subscription related events
            elif event_type == "customer.subscription.deleted":
                result = await self._handle_subscription_deleted(data)
            elif event_type == "customer.subscription.updated":
                result = await self._handle_subscription_updated(data)
            elif event_type == "customer.subscription.created":
                result = await self._handle_subscription_created(data)
            # Invoice related events
            elif event_type == "invoice.payment_succeeded":
                result = await self._handle_invoice_payment_succeeded(data)
            else:
                logger.info(f"Event type '{event_type}' is recognized but not handled")
                result["details"] = {"message": f"Event type '{event_type}' is recognized but not processed"}
            
            return result
        except Exception as e:
            logger.exception(f"Error processing Stripe event {event_type}: {str(e)}")
            result["details"] = {"error": str(e)}
            return result
    
    async def _handle_checkout_completed(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle checkout.session.completed event.
        
        This event occurs when a customer completes the checkout process.
        We'll create a license based on the purchased product.
        
        Args:
            data: The checkout session data
            
        Returns:
            Dict: Processing result
        """
        result = {
            "success": False,
            "action": "checkout_completed",
            "details": {}
        }
        
        try:
            # Extract relevant data
            session = data.get("object", {})
            customer_id = session.get("customer")
            client_email = session.get("customer_details", {}).get("email")
            metadata = session.get("metadata", {})
            
            # Check if we have a product ID in metadata
            product_id_str = metadata.get("product_id")
            if not product_id_str:
                logger.warning("No product_id found in checkout session metadata")
                result["details"] = {"error": "No product_id in metadata"}
                return result
            
            try:
                product_id = int(product_id_str)
            except ValueError:
                logger.warning(f"Invalid product_id format: {product_id_str}")
                result["details"] = {"error": f"Invalid product_id format: {product_id_str}"}
                return result
            
            # Get the product from database
            product = crud.get_product_by_id(self.db, product_id)
            if not product:
                logger.warning(f"Product not found: {product_id}")
                result["details"] = {"error": f"Product not found: {product_id}"}
                return result
            
            # Find or create the client
            client = self._find_or_create_client(client_email, customer_id)
            
            # Create license data
            license_data = schemas.LicenseCreate(
                product_id=product_id,
                client_id=client.client_id,
                status="active",
                max_activations=product.default_max_activations,
                # Set expiration if needed based on your logic
                features={
                    "stripe_customer_id": customer_id,
                    "checkout_session_id": session.get("id"),
                    "payment_status": session.get("payment_status")
                }
            )
            
            # Generate license key
            license_key = create_license_key(product.license_key_format)
            
            # Create the license
            new_license = crud.create_license(self.db, license_data, license_key)
            
            # Update result
            result["success"] = True
            result["details"] = {
                "license_id": new_license.license_id,
                "license_key": license_key,
                "client_id": client.client_id,
                "product_id": product_id
            }
            
            return result
        except Exception as e:
            logger.exception(f"Error handling checkout completed: {str(e)}")
            result["details"] = {"error": str(e)}
            return result
    
    async def _handle_invoice_payment_succeeded(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle invoice.payment_succeeded event.
        
        This event occurs when a subscription payment succeeds.
        We'll either create a new license or extend an existing one.
        
        Args:
            data: The invoice data
            
        Returns:
            Dict: Processing result
        """
        result = {
            "success": False,
            "action": "invoice_payment",
            "details": {}
        }
        
        try:
            # Extract relevant data
            invoice = data.get("object", {})
            customer_id = invoice.get("customer")
            subscription_id = invoice.get("subscription")
            
            if not customer_id or not subscription_id:
                logger.warning("Missing customer_id or subscription_id in invoice")
                result["details"] = {"error": "Missing required data in invoice"}
                return result
            
            # Find client by Stripe customer ID
            client = self._find_client_by_stripe_id(customer_id)
            if not client:
                logger.warning(f"Client not found for Stripe customer: {customer_id}")
                result["details"] = {"error": f"Client not found for customer: {customer_id}"}
                return result
            
            # Find license by subscription ID
            license_data = self._find_license_by_subscription(subscription_id)
            
            if license_data:
                # Extend existing license
                # Calculate new expiration date based on your business logic
                # For example, extend by 30 days, 1 year, etc.
                # license_update = schemas.LicenseUpdate(
                #     expires_at=new_expiration_date
                # )
                # crud.update_license(self.db, license_data.license_id, license_update)
                
                result["success"] = True
                result["action"] = "extend_license"
                result["details"] = {
                    "license_id": license_data.license_id,
                    "client_id": client.client_id,
                    "note": "License extension not implemented yet"
                }
            else:
                # Handle the case where we need to create a new license
                # This would require additional logic to determine which product to assign
                logger.warning(f"No license found for subscription: {subscription_id}")
                result["details"] = {
                    "error": f"No license found for subscription: {subscription_id}",
                    "note": "Automatic license creation from subscription not implemented"
                }
            
            return result
        except Exception as e:
            logger.exception(f"Error handling invoice payment: {str(e)}")
            result["details"] = {"error": str(e)}
            return result
    
    async def _handle_subscription_deleted(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle customer.subscription.deleted event.
        
        This event occurs when a subscription is canceled or expires.
        We'll revoke the associated license.
        
        Args:
            data: The subscription data
            
        Returns:
            Dict: Processing result
        """
        result = {
            "success": False,
            "action": "subscription_deleted",
            "details": {}
        }
        
        try:
            subscription = data.get("object", {})
            subscription_id = subscription.get("id")
            
            if not subscription_id:
                result["details"] = {"error": "Missing subscription ID"}
                return result
            
            # Find license by subscription ID
            license_data = self._find_license_by_subscription(subscription_id)
            
            if license_data:
                # Revoke the license
                crud.update_license_status(self.db, license_data.license_id, "revoked")
                
                result["success"] = True
                result["details"] = {
                    "license_id": license_data.license_id,
                    "status": "revoked"
                }
            else:
                logger.warning(f"No license found for subscription: {subscription_id}")
                result["details"] = {"error": f"No license found for subscription: {subscription_id}"}
            
            return result
        except Exception as e:
            logger.exception(f"Error handling subscription deleted: {str(e)}")
            result["details"] = {"error": str(e)}
            return result
    
    async def _handle_subscription_updated(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle customer.subscription.updated event.
        
        This event occurs when a subscription is updated (plan change, etc.).
        We'll update the associated license if needed.
        
        Args:
            data: The subscription data
            
        Returns:
            Dict: Processing result
        """
        result = {
            "success": False,
            "action": "subscription_updated",
            "details": {}
        }
        
        try:
            subscription = data.get("object", {})
            subscription_id = subscription.get("id")
            status = subscription.get("status")
            
            if not subscription_id:
                result["details"] = {"error": "Missing subscription ID"}
                return result
            
            # Find license by subscription ID
            license_data = self._find_license_by_subscription(subscription_id)
            
            if license_data:
                # Update license based on subscription status
                if status == "active":
                    crud.update_license_status(self.db, license_data.license_id, "active")
                elif status in ["canceled", "unpaid", "past_due"]:
                    crud.update_license_status(self.db, license_data.license_id, "revoked")
                
                result["success"] = True
                result["details"] = {
                    "license_id": license_data.license_id,
                    "status": license_data.status
                }
            else:
                logger.warning(f"No license found for subscription: {subscription_id}")
                result["details"] = {"error": f"No license found for subscription: {subscription_id}"}
            
            return result
        except Exception as e:
            logger.exception(f"Error handling subscription updated: {str(e)}")
            result["details"] = {"error": str(e)}
            return result
    
    async def _handle_payment_intent_succeeded(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle payment_intent.succeeded event.
        
        Args:
            data: The payment intent data
            
        Returns:
            Dict: Processing result
        """
        result = {
            "success": True,
            "action": "payment_intent_succeeded",
            "details": {}
        }
        
        try:
            payment_intent = data.get("object", {})
            payment_intent_id = payment_intent.get("id")
            amount = payment_intent.get("amount", 0)
            currency = payment_intent.get("currency", "usd")
            
            logger.info(f"Payment intent succeeded: {payment_intent_id} for {amount/100} {currency}")
            
            # Add payment details to result
            result["details"] = {
                "payment_intent_id": payment_intent_id,
                "amount": amount,
                "currency": currency,
                "status": payment_intent.get("status")
            }
            
            # Check for metadata that might include product information
            metadata = payment_intent.get("metadata", {})
            if metadata and "product_id" in metadata:
                # This is where you could create a license based on the product_id
                result["details"]["metadata"] = metadata
                
            return result
        except Exception as e:
            logger.exception(f"Error handling payment intent succeeded: {str(e)}")
            result["success"] = False
            result["details"] = {"error": str(e)}
            return result
    
    async def _handle_payment_intent_created(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle payment_intent.created event.
        
        Args:
            data: The payment intent data
            
        Returns:
            Dict: Processing result
        """
        result = {
            "success": True,
            "action": "payment_intent_created",
            "details": {}
        }
        
        try:
            payment_intent = data.get("object", {})
            payment_intent_id = payment_intent.get("id")
            amount = payment_intent.get("amount", 0)
            currency = payment_intent.get("currency", "usd")
            
            logger.info(f"Payment intent created: {payment_intent_id} for {amount/100} {currency}")
            
            # Just log the creation - no specific action needed
            result["details"] = {
                "payment_intent_id": payment_intent_id,
                "amount": amount,
                "currency": currency
            }
            
            return result
        except Exception as e:
            logger.exception(f"Error handling payment intent created: {str(e)}")
            result["success"] = False
            result["details"] = {"error": str(e)}
            return result
    
    async def _handle_charge_succeeded(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle charge.succeeded event.
        
        Args:
            data: The charge data
            
        Returns:
            Dict: Processing result
        """
        result = {
            "success": True,
            "action": "charge_succeeded",
            "details": {}
        }
        
        try:
            charge = data.get("object", {})
            charge_id = charge.get("id")
            amount = charge.get("amount", 0)
            currency = charge.get("currency", "usd")
            payment_intent_id = charge.get("payment_intent")
            
            logger.info(f"Charge succeeded: {charge_id} for {amount/100} {currency}")
            
            # Add charge details to result
            result["details"] = {
                "charge_id": charge_id,
                "amount": amount,
                "currency": currency,
                "payment_intent_id": payment_intent_id,
                "status": charge.get("status")
            }
            
            # No specific action needed for charge success - we handle licenses in the payment_intent handler
            return result
        except Exception as e:
            logger.exception(f"Error handling charge succeeded: {str(e)}")
            result["success"] = False
            result["details"] = {"error": str(e)}
            return result
    
    async def _handle_charge_updated(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle charge.updated event.
        
        Args:
            data: The charge data
            
        Returns:
            Dict: Processing result
        """
        result = {
            "success": True,
            "action": "charge_updated",
            "details": {}
        }
        
        try:
            charge = data.get("object", {})
            charge_id = charge.get("id")
            previous_attributes = data.get("previous_attributes", {})
            
            logger.info(f"Charge updated: {charge_id}")
            logger.debug(f"Changed attributes: {previous_attributes}")
            
            # Just log the update - no specific action needed
            result["details"] = {
                "charge_id": charge_id,
                "status": charge.get("status"),
                "updated_fields": list(previous_attributes.keys())
            }
            
            return result
        except Exception as e:
            logger.exception(f"Error handling charge updated: {str(e)}")
            result["success"] = False
            result["details"] = {"error": str(e)}
            return result
    
    async def _handle_subscription_created(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle customer.subscription.created event.
        
        Args:
            data: The subscription data
            
        Returns:
            Dict: Processing result
        """
        result = {
            "success": True,
            "action": "subscription_created",
            "details": {}
        }
        
        try:
            subscription = data.get("object", {})
            subscription_id = subscription.get("id")
            customer_id = subscription.get("customer")
            status = subscription.get("status")
            
            logger.info(f"Subscription created: {subscription_id} for customer {customer_id}")
            
            # Find client by Stripe customer ID
            client = self._find_client_by_stripe_id(customer_id)
            
            if client:
                # Could create a license here, but typically wait for invoice payment
                result["details"] = {
                    "subscription_id": subscription_id,
                    "customer_id": customer_id,
                    "client_id": client.client_id,
                    "status": status
                }
            else:
                result["details"] = {
                    "subscription_id": subscription_id,
                    "customer_id": customer_id,
                    "status": status,
                    "note": "No matching client found"
                }
            
            return result
        except Exception as e:
            logger.exception(f"Error handling subscription created: {str(e)}")
            result["success"] = False
            result["details"] = {"error": str(e)}
            return result
    
    def _find_or_create_client(self, email: str, stripe_customer_id: str) -> models.Client:
        """
        Find an existing client by email or create a new one.
        
        Args:
            email: Client email
            stripe_customer_id: Stripe customer ID
            
        Returns:
            models.Client: The client record
        """
        # Try to find by email first
        client = self.db.query(models.Client).filter(models.Client.email == email).first()
        
        if client:
            # Update Stripe customer ID if missing
            contact_info = client.contact_info or {}
            if not contact_info.get("stripe_customer_id"):
                contact_info["stripe_customer_id"] = stripe_customer_id
                client.contact_info = contact_info
                self.db.commit()
            return client
        
        # Create new client
        name = email.split('@')[0]  # Simple default name from email
        client_data = schemas.ClientCreate(
            name=name,
            email=email,
            company=None,
            contact_info={"stripe_customer_id": stripe_customer_id}
        )
        
        return crud.create_client(self.db, client_data)
    
    def _find_client_by_stripe_id(self, stripe_customer_id: str) -> Optional[models.Client]:
        """
        Find a client by Stripe customer ID.
        
        Args:
            stripe_customer_id: Stripe customer ID
            
        Returns:
            Optional[models.Client]: The client record if found
        """
        # This is a simple implementation
        # In a real system, you'd want to add a proper index on stripe_customer_id
        clients = self.db.query(models.Client).all()
        for client in clients:
            if client.contact_info and client.contact_info.get("stripe_customer_id") == stripe_customer_id:
                return client
        return None
    
    def _find_license_by_subscription(self, subscription_id: str) -> Optional[models.License]:
        """
        Find a license by Stripe subscription ID.
        
        Args:
            subscription_id: Stripe subscription ID
            
        Returns:
            Optional[models.License]: The license record if found
        """
        # This is a simple implementation
        # In a real system, you'd want to add a proper index on subscription_id
        licenses = self.db.query(models.License).all()
        for license_data in licenses:
            if license_data.features and license_data.features.get("stripe_subscription_id") == subscription_id:
                return license_data
        return None