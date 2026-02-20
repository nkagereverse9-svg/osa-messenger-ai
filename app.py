import os
import time
import json
import asyncio
from typing import Dict, Any, Optional

import requests
from fastapi import FastAPI, Request, Response

app = FastAPI()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "nkverify123")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")

# =========================
# AGENCY SYSTEM PROMPT
# =========================
SYSTEM_PROMPT = """
You are NK Age-Reverse AI Beauty Consultant & Sales Closer.

MISSION:
Solve customer's skin concern and guide them naturally to purchase NK Age-Reverse products.

STYLE:
- Bahasa Melayu santai + professional (macam consultant).
- 3-5 ayat, pendek, jelas.
- Tanya 1 soalan follow-up setiap reply.
- Jangan bunyi robot. Jangan sebut "AI".

SALES FLOW:
1) Greet
2) Identify concern
3) Ask diagnostic questions
4) Educate briefly
5) Recommend suitable NK product
6) Build trust
7) Soft close + link bila nampak intent

PRODUCTS (use these facts):
- NK Age-Reverse Cleanser: gentle cleanse, tidak keringkan kulit, support anti-aging, bantu skin barrier, bee venom.
- NK Age-Reverse Serum 30ml: elasticity, fine lines, collagen support, brightening.

OFFICIAL LINK:
https://nkarofficial.com/

RULES:
- If user says "hi/hello" → terus start consultation (tanya masalah kulit).
- If user ask product lain → jawab secara umum + bawa ke link "our products" / tanya nama produk.
- If user tanya harga/order → bagi link order.
"""

ORDER_LINK = "https://nkarofficial.com/"
PRODUCTS_LINK = "https://nkarofficial.com/our-products/"

# =========================
# Simple lead memory (in RAM)
# NOTE: On free Render, service can restart -> memory reset
# =========================
user_state: Dict[str, Dict[str, Any]] = {}
followup_tasks: Dict[str, asyncio.Task] = {}  # psid -> task


# =========================
# Helpers
# =========================
def detect_buying_intent(text: str) -> bool:
    keywords = [
        "harga", "price", "berapa", "how much",
        "nak beli", "order", "beli", "purchase",
        "link", "checkout", "cod", "pos"
    ]
    t = (text or "").lower()
    return any(k in t for k in keywords)


def stage_from_text(text: str) -> str:
    t = (text or "").lower()
    if detect_buying_intent(t):
        return "hot"
    if any(k in t for k in ["kering", "jerawat", "berminyak", "parut", "sensitif", "garis halus", "wrinkle", "kusam"]):
        return "warm"
    if any(k in t for k in ["hi", "hello", "hai", "assalam", "salam"]):
        return "cold"
    return "warm"


def graph_api_send_message(psid: str, text: str) -> None:
    if not PAGE_ACCESS_TOKEN:
        print("ERROR: PAGE_ACCESS_TOKEN missing")
        return

    url = "https://graph.facebook.com/v19.0/me/messages"
    payload = {
        "recipient": {"id": psid},
        "message": {"text": text}
    }
    params = {"access_token": PAGE_ACCESS_TOKEN}
    r = requests.post(url, params=params, json=payload, timeout=30)
    if r.status_code >= 400:
        print("FB SEND ERROR:", r.status_code, r.text)


def groq_chat(user_text: str, context: Optional[Dict[str, Any]] = None) -> str:
    """
    Call Groq OpenAI-compatible endpoint.
    """
    if not GROQ_API_KEY:
        return "Saya boleh bantu 😊 Boleh share masalah kulit awak dulu—kering, berminyak, jerawat atau garis halus?"

    # Lightweight context injection
    ctx_lines = []
    if context:
        stage = context.get("stage")
        skin = context.get("skin_type")
        if stage:
            ctx_lines.append(f"Lead stage: {stage}")
        if skin:
            ctx_lines.append(f"Skin info: {skin}")

    ctx = "\n".join(ctx_lines).strip()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + (f"\n\nCONTEXT:\n{ctx}" if ctx else "")},
        {"role": "user", "content": user_text}
    ]

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.6,
        "max_tokens": 220
    }

    r = requests.post(url, headers=headers, json=body, timeout=40)
    if r.status_code >= 400:
        print("GROQ ERROR:", r.status_code, r.text)
        return "Maaf ya, sistem tengah sibuk sikit. Awak boleh bagitahu masalah kulit utama awak dulu? 😊"

    data = r.json()
    return data["choices"][0]["message"]["content"].strip()


async def schedule_followups(psid: str):
    """
    Send follow-ups if user becomes inactive.
    Two pings: 15 min and 60 min from last user message.
    Cancelled automatically if user sends new message (we cancel task).
    """
    try:
        # Wait 15 minutes
        await asyncio.sleep(15 * 60)
        st = user_state.get(psid, {})
        last_ts = st.get("last_user_ts", 0)
        if time.time() - last_ts >= 15 * 60:
            # 15-min follow-up (soft)
            msg = "Saya nak pastikan saya bantu betul 😊 Kulit awak lebih cenderung *kering* atau *berminyak* ya?"
            graph_api_send_message(psid, msg)

        # Wait until 60 minutes (another 45 min)
        await asyncio.sleep(45 * 60)
        st = user_state.get(psid, {})
        last_ts = st.get("last_user_ts", 0)
        if time.time() - last_ts >= 60 * 60:
            # 60-min follow-up (CTA)
            msg = (
                "Kalau awak nak saya recommend routine paling simple ikut masalah kulit awak, saya boleh guide step-by-step 😊\n"
                f"Kalau nak tengok semua produk official: {PRODUCTS_LINK}"
            )
            graph_api_send_message(psid, msg)

    except asyncio.CancelledError:
        # normal cancellation
        return
    except Exception as e:
        print("FOLLOWUP ERROR:", str(e))


def reset_followup(psid: str):
    # cancel old followup task
    old = followup_tasks.get(psid)
    if old and not old.done():
        old.cancel()

    # schedule new followups
    followup_tasks[psid] = asyncio.create_task(schedule_followups(psid))


# =========================
# Routes
# =========================
@app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return Response(content=challenge or "", media_type="text/plain")
    return Response(content="Verification token mismatch", status_code=403)


@app.post("/webhook")
async def receive_webhook(request: Request):
    body = await request.json()

    # Facebook sends multiple events
    if body.get("object") != "page":
        return {"status": "ignored"}

    entries = body.get("entry", [])
    for entry in entries:
        messaging_events = entry.get("messaging", [])
        for event in messaging_events:
            sender = event.get("sender", {}).get("id")
            message = event.get("message", {})
            text = message.get("text")

            # Ignore echoes (page messages sent by itself)
            if message.get("is_echo"):
                continue

            if sender and text:
                # Update state
                st = user_state.get(sender, {})
                st["last_user_ts"] = time.time()
                st["stage"] = max(st.get("stage", "cold"), stage_from_text(text), key=lambda x: ["cold","warm","hot"].index(x))
                user_state[sender] = st

                # Schedule follow-ups again
                reset_followup(sender)

                # AI reply
                ai_reply = groq_chat(text, context=st)

                # Add order link if buying intent
                if detect_buying_intent(text):
                    ai_reply += f"\n\nBoleh order terus di sini ya 😊\n{ORDER_LINK}"

                graph_api_send_message(sender, ai_reply)

    return {"status": "ok"}


@app.get("/")
async def health():
    return {"ok": True, "service": "osa-messenger-ai"}

