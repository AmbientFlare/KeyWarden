# test_webhook.py
import requests
import json
import argparse

def test_webhook(url, webhook_type='debug', payload=None):
    """
    Send a test webhook to the specified URL.
    
    Args:
        url (str): The webhook URL to send the request to
        webhook_type (str): The type of webhook to simulate ('debug', 'stripe', etc.)
        payload (dict, optional): Custom payload to send. If None, a default test payload will be used.
    """
    if not url.startswith('http'):
        url = f"http://{url}"
    
    # Default test payload
    if payload is None:
        if webhook_type == 'stripe':
            payload = {
                "id": "evt_test_123456",
                "type": "checkout.session.completed",
                "created": 1675098765,
                "data": {
                    "object": {
                        "id": "cs_test_123456",
                        "customer": "cus_test_123456",
                        "customer_details": {
                            "email": "test@example.com"
                        },
                        "metadata": {
                            "product_id": "1"
                        },
                        "payment_status": "paid"
                    }
                }
            }
        else:
            # Generic test payload
            payload = {
                "event_id": "test_event_123",
                "event_type": "test_webhook",
                "timestamp": "2023-09-15T12:34:56Z",
                "test_data": "This is a test webhook payload"
            }
    
    # Set headers
    headers = {
        'Content-Type': 'application/json'
    }
    
    if webhook_type == 'stripe':
        # In a real scenario, you'd sign the payload with the Stripe secret
        # For testing, we're just sending a header that our system expects
        headers['stripe-signature'] = 'test_signature'
    
    # Send the request
    print(f"Sending {webhook_type} webhook to {url}...")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        
        print("\nResponse:")
        print(f"Status code: {response.status_code}")
        
        try:
            print(f"Response body: {json.dumps(response.json(), indent=2)}")
        except:
            print(f"Response body: {response.text}")
        
        if response.status_code == 200:
            print("\n✅ Webhook sent successfully!")
        else:
            print("\n❌ Webhook failed to send!")
    
    except Exception as e:
        print(f"\n❌ Error sending webhook: {str(e)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Test webhook endpoints')
    parser.add_argument('url', help='The webhook URL (can be hostname:port/path or full URL)')
    parser.add_argument('--type', choices=['debug', 'stripe'], default='debug',
                      help='Type of webhook to simulate (default: debug)')
    parser.add_argument('--payload', type=json.loads, 
                      help='Custom JSON payload (as string)')
    
    args = parser.parse_args()
    
    test_webhook(args.url, args.type, args.payload)