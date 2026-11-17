# handlers/base_handler.py
import abc
import hashlib
import json
import logging
from typing import Dict, Any, Optional, Tuple, Union
from fastapi import Request, Response, status, HTTPException
from sqlalchemy.orm import Session

# Configure logging
logger = logging.getLogger(__name__)

class WebhookHandler(abc.ABC):
    """
    Abstract base class for payment processor webhook handlers.
    
    This class provides the core functionality for validating, processing,
    and responding to webhooks from payment processors.
    """
    
    def __init__(self, db: Session, redis_client=None):
        """
        Initialize the webhook handler.
        
        Args:
            db (Session): SQLAlchemy database session
            redis_client: Redis client for idempotency checks (optional)
        """
        self.db = db
        self.redis_client = redis_client
        
    @property
    @abc.abstractmethod
    def provider_name(self) -> str:
        """Return the name of the payment provider."""
        pass
    
    @abc.abstractmethod
    async def validate_signature(self, request: Request, webhook_secret: str) -> bool:
        """
        Validate the webhook signature to ensure the request is authentic.
        
        Args:
            request: The incoming FastAPI request
            webhook_secret: The webhook secret key for validation
            
        Returns:
            bool: True if signature is valid, False otherwise
        """
        pass
    
    @abc.abstractmethod
    async def parse_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse the webhook event payload into a standardized format.
        
        Args:
            payload: The raw webhook payload
            
        Returns:
            Dict: Standardized event data
        """
        pass
    
    @abc.abstractmethod
    async def process_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process the webhook event and perform appropriate business logic.
        
        Args:
            event_data: The standardized event data
            
        Returns:
            Dict: Processing result
        """
        pass
    
    async def check_idempotency(self, event_id: str) -> bool:
        """
        Check if an event has already been processed to prevent duplicates.
        
        Args:
            event_id: Unique identifier for the event
            
        Returns:
            bool: True if event was already processed, False otherwise
        """
        if self.redis_client:
            # Use Redis for idempotency check
            key = f"webhook:{self.provider_name}:{event_id}"
            exists = await self.redis_client.exists(key)
            return exists
        else:
            # Fallback to database check
            # Here you would check if event_id exists in a WebhookEvent table
            # For now, we'll return False (meaning process the event)
            logger.warning("Redis not available for idempotency check. Falling back to DB check.")
            return False  # Implement DB check here
    
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
        else:
            # Fallback to database storage
            # Here you would insert the event_id into a WebhookEvent table
            logger.warning("Redis not available for idempotency storage. Falling back to DB storage.")
            # Implement DB storage here
    async def check_idempotency(self, event_id: str) -> bool:
        if self.redis_client:
            # Use Redis for idempotency check
            key = f"webhook:{self.provider_name}:{event_id}"
            exists = await self.redis_client.exists(key)
            return exists
        else:
            # Fallback to database check
            from db import crud
            logger.warning("Redis not available for idempotency check. Falling back to DB check.")
            existing_event = crud.get_webhook_event_by_id(self.db, self.provider_name, event_id)
            return existing_event is not None
    async def mark_processed(self, event_id: str, event_data: Dict[str, Any], ttl: int = 86400 * 30) -> None:
        if self.redis_client:
            # Use Redis to store the event ID
            key = f"webhook:{self.provider_name}:{event_id}"
            await self.redis_client.set(key, json.dumps(event_data), ex=ttl)
        else:
            # Fallback to database storage
            from db import crud
            logger.warning("Redis not available for idempotency storage. Falling back to DB storage.")
            crud.create_webhook_event(self.db, self.provider_name, event_id, event_data)
    async def handle_webhook(self, request: Request, webhook_secret: str) -> Response:
        """
        Main webhook handling method that orchestrates the validation,
        idempotency check, and processing.
        
        Args:
            request: The incoming FastAPI request
            webhook_secret: The webhook secret key for validation
            
        Returns:
            Response: HTTP response to return to the caller
        """
        try:
            # Get the raw body for signature validation
            body = await request.body()
            payload = await request.json()
            
            # Validate signature
            valid_signature = await self.validate_signature(request, webhook_secret)
            if not valid_signature:
                logger.warning(f"Invalid signature for {self.provider_name} webhook")
                return Response(
                    content=json.dumps({"error": "Invalid signature"}),
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    media_type="application/json"
                )
            
            # Parse the event
            event_data = await self.parse_event(payload)
            event_id = event_data.get("id")
            
            if not event_id:
                logger.error(f"No event ID found in {self.provider_name} webhook")
                return Response(
                    content=json.dumps({"error": "No event ID found"}),
                    status_code=status.HTTP_400_BAD_REQUEST,
                    media_type="application/json"
                )
            
            # Check idempotency
            already_processed = await self.check_idempotency(event_id)
            if already_processed:
                logger.info(f"Event {event_id} already processed, skipping")
                return Response(
                    content=json.dumps({"status": "already processed"}),
                    status_code=status.HTTP_200_OK,
                    media_type="application/json"
                )
            
            # Process the event
            logger.info(f"Processing {self.provider_name} webhook event: {event_id}")
            result = await self.process_event(event_data)
            
            # Mark as processed
            await self.mark_processed(event_id, event_data)
            
            return Response(
                content=json.dumps({"status": "success", "result": result}),
                status_code=status.HTTP_200_OK,
                media_type="application/json"
            )
            
        except json.JSONDecodeError:
            logger.exception(f"Invalid JSON in {self.provider_name} webhook")
            return Response(
                content=json.dumps({"error": "Invalid JSON payload"}),
                status_code=status.HTTP_400_BAD_REQUEST,
                media_type="application/json"
            )
        except Exception as e:
            logger.exception(f"Error processing {self.provider_name} webhook: {str(e)}")
            return Response(
                content=json.dumps({"error": "Internal server error"}),
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                media_type="application/json"
            )