import os
import time
import json
import re
from typing import Dict, Any

import requests
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse

# =====================================================
# ENV
# =====================================================
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "")

AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "llama-3.1-8b-instant")

OFFICIAL_DOMAIN = "nkarofficial.com"
OFFICIAL_ORDER_LINK = "https://nkarofficial.com/our-products/skincare/"

# =====================================================
# PRODUCT CATALOG (SOURCE OF TRUTH)
# =====================================================
PRODUCT_CATALOG = [
    {
        "name": "NK Age-Reverse Cleanser",
        "category": "cleanser",
        "for_skin": ["berminyak","kering","kombinasi","sensitif","jerawat"],
        "url": OFFICIAL_ORDER_LINK
    },
    {
        "name": "NK Age-Reverse Serum 30ml",
        "category": "serum",
        "for_skin": ["garis_halus","kusam","kering"],
        "url": OFFICIAL_ORDER_LINK
    }
]

# =====================================================
# USER MEMORY
# =====================================================
USER_STATE: Dict[str, Dict[str, Any]] = {}

def get_state(psid):
    if psid not in USER_STATE:
        USER_STATE[psid] = {
            "stage": "start",
            "skin": "",
            "lead_score": 0,
            "ready_to_buy": False,
            "asked_contact": False,
            "last_seen": time.time()
        }
    return USER_STATE[psid]

# =====================================================
# SALES INTELLIGENCE
# =====================================================
def detect_buying_signal(state, text):
    signals = [
        "harga","price","order","nak beli",
        "link","payment","macam mana beli"
    ]

    if any(s in text.lower() for s in signals):
        state["lead_score"] += 2

    if state["lead_score"] >= 3:
        state["ready_to_buy"] = True

def extract_phone(text):
    m = re.search(r'(\+?6?01[0-9\- ]{7,10})', text)
    return m.group(1) if m else None

# =====================================================
# PROMPT (REVENUE MODE)
# =====================================================
def catalog_text():
    return "\n".join(
        [f"- {p['name']} ({p['category']})" for p in PRODUCT_CATALOG]
    )

SYSTEM_PROMPT = f"""
Anda NK Age-Reverse AI — Professional Skincare Consultant & Sales Closer.

MISI:
- bantu pilih produk
- bina trust
- convert kepada order

RULE WAJIB:
1. Hanya guna produk dalam catalog.
2. Jangan cipta produk/harga/ingredient.
3. Semua link mesti {OFFICIAL_DOMAIN}.
4. Jawapan pendek (max 8 baris).

SALES FLOW:
Empathy → Question → Recommend → Routine → CTA.

CTA contoh:
"Nak saya bagi link order rasmi + cara guna lengkap?"

CATALOG:
{catalog_text()}
"""

# =====================================================
# GROQ API
# =====================================================
def ask_ai(user_text, state):

    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role":"system","content":SYSTEM_PROMPT},
            {"role":"user","content":user_text}
        ],
        "temperature":0.7,
        "max_tokens":250
    }

    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization":f"Bearer {AI_API_KEY}",
            "Content-Type":"application/json"
        },
        json=payload,
        timeout=25
    )

    data = r.json()
    return data["choices"][0]["message"]["content"]

# =====================================================
# RESPONSE ENFORCEMENT
# =====================================================
def enforce_official_link(text):
    urls = re.findall(r"https?://\S+", text)
    for u in urls:
        if OFFICIAL_DOMAIN not in u:
            text = text.replace(u,"")

    if OFFICIAL_DOMAIN not in text:
        text += f"\n\nLink order rasmi:\n{OFFICIAL_ORDER_LINK}"

    return text

def closer_engine(reply, state):

    if state["ready_to_buy"] and not state["asked_contact"]:
        state["asked_contact"] = True
        reply += (
            "\n\n✨ Saya boleh WhatsAppkan routine lengkap "
            "+ cara guna step-by-step.\n"
            "Boleh share nama & nombor WhatsApp? 😊"
        )

    return reply

# =====================================================
# FACEBOOK SEND
# =====================================================
def send_fb(psid, text):

    requests.post(
        "https://graph.facebook.com/v20.0/me/messages",
        params={"access_token":PAGE_ACCESS_TOKEN},
        json={
            "recipient":{"id":psid},
            "message":{"text":text},
            "messaging_type":"RESPONSE"
        },
        timeout=20
    )

# =====================================================
# FASTAPI
# =====================================================
app = FastAPI()

@app.get("/")
def home():
    return {"ok":True}

@app.get("/webhook")
def verify(hub_mode:str="", hub_verify_token:str="", hub_challenge:str=""):
    if hub_mode=="subscribe" and hub_verify_token==VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge)
    return PlainTextResponse("fail",403)

@app.post("/webhook")
async def webhook(req:Request):

    body = await req.json()
    print("IN:", json.dumps(body)[:2000])

    for entry in body.get("entry",[]):
        for event in entry.get("messaging",[]):

            if "message" not in event:
                continue

            sender = event["sender"]["id"]
            text = event["message"].get("text","")

            if not text:
                continue

            state = get_state(sender)
            state["last_seen"] = time.time()

            # detect buying intent
            detect_buying_signal(state, text)

            # detect phone
            phone = extract_phone(text)
            if phone:
                send_fb(sender,
                    "Terima kasih 😊 Team NK akan hubungi anda di WhatsApp sebentar lagi!")
                continue

            # AI reply
            try:
                reply = ask_ai(text, state)
                reply = enforce_official_link(reply)
                reply = closer_engine(reply, state)

            except Exception as e:
                print("AI ERROR:", e)
                reply = f"Boleh ceritakan sedikit masalah kulit anda? 😊\n\n{OFFICIAL_ORDER_LINK}"

            send_fb(sender, reply)

    return JSONResponse({"ok":True})
