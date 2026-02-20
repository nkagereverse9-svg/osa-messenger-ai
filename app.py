import os
import re
import time
import json
import requests
from typing import Dict, Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse

app = FastAPI()

# =========================
# ENV VARS (Render -> Environment)
# =========================
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "nkverify123")  # sama macam Meta verify token
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "")   # Page Access Token (Meta)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")             # Groq API key

# Groq endpoint (OpenAI-compatible)
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")

# Optional: safety / style
MAX_REPLY_CHARS = 800  # elak reply terlalu panjang (Messenger boleh potong)

# =========================
# Simple in-memory user state (stateless -> stateful)
# NOTE: akan reset bila Render restart. Untuk permanent, nanti upgrade SQLite.
# =========================
user_memory: Dict[str, Dict[str, Any]] = {}

# =========================
# Product knowledge (based on your official site)
# You can extend this list anytime.
# =========================
BASE_SITE = "https://nkarofficial.com"

PRODUCTS = {
    "cleanser": {
        "name": "NK Age-Reverse Cleanser",
        "url": f"{BASE_SITE}/our-products/skincare/",
        "key_benefits": [
            "Membersih tanpa mengeringkan kulit",
            "Membantu kurangkan garis halus",
            "Kulit rasa lebih lembut & glowing"
        ],
        "who": "Sesuai untuk kebanyakan jenis kulit (kering/berminyak/normal) — pilih cara guna ikut concern.",
    },
    "serum": {
        "name": "NK Age-Reverse Serum 30ML",
        "url": f"{BASE_SITE}/our-products/skincare/age-reverse-serum-30ml/",
        "key_benefits": [
            "Membantu tingkatkan elastisiti kulit",
            "Mengurangkan garis halus",
            "Bantu kulit nampak lebih cerah & segar",
            "Menyokong penghasilan kolagen"
        ],
        "who": "Sesuai untuk yang fokus anti-aging/tekstur/lebih anjal."
    }
}

ORDER_LINK = f"{BASE_SITE}/our-products/skincare/"  # fallback order/catalog link


# =========================
# Helpers: detect intent / skin type / product query
# =========================
def normalize_text(s: str) -> str:
    return (s or "").strip()

def detect_skin_type(text: str) -> Optional[str]:
    t = text.lower()
    # common BM keywords
    if "kering" in t:
        return "kering"
    if "berminyak" in t or "minyak" in t:
        return "berminyak"
    if "sensitif" in t:
        return "sensitif"
    if "jerawat" in t or "acne" in t:
        return "jerawat"
    if "normal" in t:
        return "normal"
    return None

def detect_concern(text: str) -> Optional[str]:
    t = text.lower()
    concerns = [
        ("garis halus", ["garis halus", "fine line", "wrinkle", "kedut"]),
        ("jerawat", ["jerawat", "acne", "breakout", "panau", "bintik"]),
        ("parut", ["parut", "scar", "bekas"]),
        ("kusam", ["kusam", "dull", "cerah", "glow", "glowing"]),
        ("pori", ["pori", "pori besar", "blackhead", "whitehead"]),
        ("kering", ["kering", "flaky", "menggelupas"]),
        ("berminyak", ["berminyak", "minyak", "oily"]),
        ("sensitif", ["sensitif", "pedih", "merah", "iritasi"]),
    ]
    for label, kws in concerns:
        if any(k in t for k in kws):
            return label
    return None

def detect_product_keyword(text: str) -> Optional[str]:
    t = text.lower()
    # detect user ask product
    if "cleanser" in t or "pencuci" in t or "facial wash" in t or "cuci muka" in t:
        return "cleanser"
    if "serum" in t:
        return "serum"
    # generic: "produk lain"
    if "produk lain" in t or "product lain" in t or "apa lagi" in t:
        return "catalog"
    return None

def is_buy_intent(text: str) -> bool:
    t = text.lower()
    buy_words = [
        "nak beli", "beli", "order", "checkout", "harga", "rm", "payment",
        "cod", "pos", "delivery", "stock", "available", "link", "cart", "promo"
    ]
    return any(w in t for w in buy_words)

def is_greeting(text: str) -> bool:
    t = text.lower().strip()
    return t in ["hi", "hello", "hai", "assalamualaikum", "salam", "hey"]

def get_user_state(sender_id: str) -> Dict[str, Any]:
    if sender_id not in user_memory:
        user_memory[sender_id] = {
            "skin_type": None,
            "concern": None,
            "stage": "intro",       # intro -> qualify -> recommend -> close
            "last_product": None,
            "last_seen": time.time()
        }
    user_memory[sender_id]["last_seen"] = time.time()
    return user_memory[sender_id]

def clamp_reply(text: str) -> str:
    text = text.strip()
    if len(text) <= MAX_REPLY_CHARS:
        return text
    return text[:MAX_REPLY_CHARS].rstrip() + "…"


# =========================
# Messenger Send API
# =========================
def send_message(psid: str, message_text: str) -> None:
    if not PAGE_ACCESS_TOKEN:
        print("❌ Missing PAGE_ACCESS_TOKEN")
        return

    url = f"https://graph.facebook.com/v20.0/me/messages"
    params = {"access_token": PAGE_ACCESS_TOKEN}
    payload = {
        "recipient": {"id": psid},
        "message": {"text": clamp_reply(message_text)}
    }

    r = requests.post(url, params=params, json=payload, timeout=30)
    if r.status_code != 200:
        print("❌ Send API error:", r.status_code, r.text)


# =========================
# Groq Chat call
# =========================
def groq_chat(system_prompt: str, user_prompt: str) -> str:
    if not GROQ_API_KEY:
        return "Maaf ya, sistem AI belum disambungkan (GROQ_API_KEY belum set)."

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    body = {
        "model": GROQ_MODEL,
        "temperature": 0.6,
        "max_tokens": 350,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    }

    try:
        resp = requests.post(GROQ_CHAT_URL, headers=headers, json=body, timeout=40)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print("❌ Groq error:", str(e))
        return "Maaf, AI tengah sibuk sekejap. Boleh ulang soalan anda sekali lagi? 🙂"


# =========================
# Prompt Builder (Agency-level)
# =========================
def build_system_prompt(state: Dict[str, Any]) -> str:
    skin_type = state.get("skin_type")
    concern = state.get("concern")
    stage = state.get("stage")
    last_product = state.get("last_product")

    # compact product facts
    cleanser = PRODUCTS["cleanser"]
    serum = PRODUCTS["serum"]

    return f"""
You are "NK Age-Reverse AI" — a friendly, persuasive, helpful Malaysian skincare sales consultant (Bahasa Melayu + casual English mix if needed).
Goal: convert chat into qualified lead + purchase, ethically and naturally.

IMPORTANT RULES:
1) If user skin_type is known, DO NOT ask "jenis kulit" again. Use it.
2) Keep replies short, clear, and sales-focused (2–6 sentences). Use bullet points only when helpful.
3) Ask ONLY ONE question at the end to move to next step (qualify / close).
4) Always include official product/order link when user shows buying intent or asks "nak beli / harga / link / order".
5) If user asks other product: guide them to official catalog and suggest best match, do not hallucinate.
6) Avoid medical claims; advise patch test & stop if irritation. Recommend consult professional if serious condition.

User context:
- skin_type: {skin_type}
- concern: {concern}
- stage: {stage}
- last_product: {last_product}

Official links:
- Catalog/order: {ORDER_LINK}
- Serum page: {serum['url']}
- Cleanser catalog: {cleanser['url']}

Core product facts (use them, do not invent new info):
CLEANSE: {cleanser['name']}
Benefits: {", ".join(cleanser['key_benefits'])}
For: {cleanser['who']}

SERUM: {serum['name']}
Benefits: {", ".join(serum['key_benefits'])}
For: {serum['who']}

Conversation strategy:
- If stage=intro: greet + ask 1 quick qualifier (skin_type OR concern).
- If stage=qualify: confirm skin_type/concern + suggest product (usually Cleanser first), ask if they want link/harga.
- If stage=recommend: give tailored routine steps + soft close + ask if they want order link.
- If stage=close: give link + ask shipping area / payment preference / quantity.
""".strip()


def build_user_prompt(user_text: str, state: Dict[str, Any]) -> str:
    # We can also nudge the model with structured data:
    return f"""
User message: {user_text}

Respond as NK Age-Reverse AI.
Remember the rules: if skin_type already known, do not ask again.
End with ONE question to progress toward purchase.
""".strip()


# =========================
# Webhook endpoints
# =========================

@app.get("/webhook")
def webhook_verify(request: Request):
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(content=str(challenge), status_code=200)

    return PlainTextResponse(content="Verification failed", status_code=403)


@app.post("/webhook")
async def webhook_receive(request: Request):
    body = await request.json()

    # Messenger events
    if body.get("object") != "page":
        return JSONResponse({"status": "ignored"}, status_code=200)

    entries = body.get("entry", [])
    for entry in entries:
        messaging_events = entry.get("messaging", [])
        for event in messaging_events:
            sender = event.get("sender", {})
            sender_id = sender.get("id")

            # Ignore delivery/read echoes
            if event.get("message", {}).get("is_echo"):
                continue

            # Text message
            if "message" in event and "text" in event["message"]:
                user_text = normalize_text(event["message"]["text"])
                if not user_text:
                    continue

                state = get_user_state(sender_id)

                # Update memory from user message
                skin = detect_skin_type(user_text)
                if skin:
                    state["skin_type"] = skin
                    # move stage if needed
                    if state["stage"] in ["intro", "qualify"]:
                        state["stage"] = "recommend"

                concern = detect_concern(user_text)
                if concern:
                    state["concern"] = concern
                    if state["stage"] == "intro":
                        state["stage"] = "qualify"

                prod_key = detect_product_keyword(user_text)
                if prod_key in ["cleanser", "serum"]:
                    state["last_product"] = prod_key
                    if state["stage"] == "intro":
                        state["stage"] = "qualify"

                # Simple deterministic shortcuts (reduce AI cost, more stable)
                if is_greeting(user_text) and state.get("stage") == "intro":
                    reply = (
                        "Hai 😊 Saya NK Age-Reverse AI. "
                        "Nak saya cadangkan routine yang sesuai—kulit awak lebih kepada kering, berminyak, sensitif atau mudah jerawat?"
                    )
                    send_message(sender_id, reply)
                    continue

                # If user asks "produk lain"
                if prod_key == "catalog":
                    reply = (
                        f"Boleh 😊 Untuk produk lain, awak boleh tengok katalog rasmi sini: {ORDER_LINK}\n"
                        "Awak nak fokus masalah apa dulu—kulit berminyak/jerawat, kering, atau garis halus?"
                    )
                    send_message(sender_id, reply)
                    continue

                # If strong buy intent: push close + link
                if is_buy_intent(user_text):
                    state["stage"] = "close"

                # Build prompts + call Groq
                system_prompt = build_system_prompt(state)
                user_prompt = build_user_prompt(user_text, state)
                ai_reply = groq_chat(system_prompt, user_prompt)

                # Optional: enforce link in close stage
                if state["stage"] == "close" and ORDER_LINK not in ai_reply:
                    ai_reply += f"\n\nLink order rasmi: {ORDER_LINK}"

                send_message(sender_id, ai_reply)
                continue

            # Postback (button)
            if "postback" in event:
                payload = event["postback"].get("payload", "")
                state = get_user_state(sender_id)
                state["stage"] = "qualify"
                send_message(sender_id, "Baik 😊 Boleh share jenis kulit awak (kering/berminyak/sensitif/jerawat) supaya saya cadangkan yang tepat?")
                continue

    return JSONResponse({"status": "ok"}, status_code=200)


@app.get("/")
def health():
    return {"status": "ok"}
