from fastapi import FastAPI, Request
import requests
import os
import uvicorn

app = FastAPI()

# Environment variables from Render
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")

# -----------------------
# Health check (important)
# -----------------------
@app.get("/health")
def health():
    return {"status": "healthy"}

# -----------------------
# Facebook Webhook Verify
# -----------------------
@app.get("/webhook")
async def verify(request: Request):
    params = request.query_params

    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return int(challenge)

    return {"error": "Verification failed"}

# -----------------------
# Receive Messages
# -----------------------
@app.post("/webhook")
async def receive_message(request: Request):
    body = await request.json()

    if "entry" in body:
        for entry in body["entry"]:
            for messaging_event in entry["messaging"]:
                sender_id = messaging_event["sender"]["id"]

                if "message" in messaging_event:
                    text = messaging_event["message"].get("text", "")

                    reply = f"You said: {text}"

                    send_message(sender_id, reply)

    return {"status": "ok"}


# -----------------------
# Send message back
# -----------------------
def send_message(recipient_id, text):
    url = "https://graph.facebook.com/v18.0/me/messages"

    params = {
        "access_token": PAGE_ACCESS_TOKEN
    }

    headers = {
        "Content-Type": "application/json"
    }

    data = {
        "recipient": {"id": recipient_id},
        "message": {"text": text}
    }

    requests.post(url, params=params, headers=headers, json=data)


# -----------------------
# START SERVER (IMPORTANT)
# -----------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)