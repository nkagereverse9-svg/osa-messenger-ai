from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

# ---------- VERIFY WEBHOOK ----------
@app.get("/webhook")
async def verify(request: Request):
    params = dict(request.query_params)

    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == VERIFY_TOKEN
    ):
        return params.get("hub.challenge")

    return "Verification failed"


# ---------- RECEIVE MESSAGE ----------
@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()

    try:
        messaging = data["entry"][0]["messaging"][0]
        sender_id = messaging["sender"]["id"]

        if "message" in messaging:
            user_text = messaging["message"].get("text", "")

            reply = ai_reply(user_text)

            send_message(sender_id, reply)

    except Exception as e:
        print("Error:", e)

    return {"status": "ok"}


# ---------- SIMPLE AI (TEMP) ----------
def ai_reply(text):
    text = text.lower()

    if "price" in text or "harga" in text:
        return "✨ NK Age-Reverse cleanser membantu membersihkan kulit secara lembut dan sesuai untuk kulit sensitif. Nak saya sambungkan dengan admin untuk harga & promo terkini?"

    if "hello" in text or "hi" in text:
        return "Hi 👋 Welcome to NK Age-Reverse! How can I help your skin today? ✨"

    return "Terima kasih kerana message NK Age-Reverse 💙 Boleh share jenis kulit anda (oily/kering/sensitif)? Saya bantu cadangkan."


# ---------- SEND MESSAGE ----------
def send_message(recipient_id, message_text):
    url = "https://graph.facebook.com/v19.0/me/messages"

    params = {
        "access_token": PAGE_ACCESS_TOKEN
    }

    headers = {
        "Content-Type": "application/json"
    }

    data = {
        "recipient": {"id": recipient_id},
        "message": {"text": message_text}
    }

    requests.post(url, params=params, headers=headers, json=data)