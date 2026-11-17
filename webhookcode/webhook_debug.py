# webhook_debug.py
import json
import logging
from datetime import datetime
from fastapi import FastAPI, Request, Response, status
from db import models

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("webhook_debug")

async def debug_webhook_handler(request: Request, db):
    """
    Debug webhook handler that will log incoming webhook events and store them
    without any additional processing or validation.
    
    This is useful for testing webhook functionality without the full processing
    pipeline.
    """
    try:
        # Log request details
        logger.debug(f"Received webhook request: {request.url}")
        logger.debug(f"Headers: {request.headers}")
        
        # Get the raw body
        body = await request.body()
        body_text = body.decode('utf-8')
        logger.debug(f"Body: {body_text}")
        
        # Try to parse as JSON
        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError:
            logger.warning("Request body is not valid JSON")
            payload = {"raw_data": body_text}
        
        # Create a webhook event entry
        event_id = f"debug_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{hash(body_text) % 10000}"
        
        # Save to database
        webhook_event = models.WebhookEvent(
            event_id=event_id,
            provider="debug",
            event_type="debug_webhook",
            event_data=payload,
            processed_at=datetime.utcnow()
        )
        
        db.add(webhook_event)
        db.commit()
        
        logger.info(f"Debug webhook event saved with ID: {event_id}")
        
        return Response(
            content=json.dumps({"status": "success", "event_id": event_id}),
            status_code=status.HTTP_200_OK,
            media_type="application/json"
        )
        
    except Exception as e:
        logger.exception(f"Error processing debug webhook: {str(e)}")
        
        return Response(
            content=json.dumps({"error": f"Internal server error: {str(e)}"}),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            media_type="application/json"
        )

# Function to add to main.py's API router
def add_debug_webhook_route(app, db_dependency):
    @app.post("/api/v1/webhooks/debug")
    async def debug_webhook(request: Request, db=db_dependency):
        """Debugging webhook endpoint that accepts any payload"""
        return await debug_webhook_handler(request, db)