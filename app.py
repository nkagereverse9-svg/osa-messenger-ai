import os
import json
import time
import hashlib
from typing import Dict, Any, Optional, List

import requests
from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse

app = FastAPI()

# =========================
# ENV
# =========================
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "").strip()
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "").strip()

AI_PROVIDER = os.getenv("AI_PROVIDER", "groq").strip().lower()
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "llama3-8b-8192").strip()

PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip()

NK_OFFICIAL_PRODUCTS = "https://nkarofficial.com/our-products/skincare/"
NK_OFFICIAL_DOMAIN = "nkarofficial.com"

# =========================
# SIMPLE IN-MEMORY "STATE"
# (Render Free instance may sleep => memory resets sometimes)
# =========================
USER_STATE: Dict[str, Dict[str, Any]] = {}

def now_ts() -> int:
    return int(time.time())

def get_state(psid: str) -> Dict[str, Any]:
    if psid not in USER_STATE:
        USER_STATE[psid] = {
            "stage": "start",
            "skin_type": None,
            "concern": None,
            "budget": None,
            "last_seen": now_ts(),
            "history": []  # short history for context
        }
    USER_STATE[psid]["last_seen"] = now_ts()
    return USER_STATE[psid]

def add_history(psid: str, role: str, content: str):
    st = get_state(psid)
    st["history"].append({"role": role, "content": content})
    # keep last 8 msgs only
    st["history"] = st["history"][-8:]


# =========================
# META MESSENGER SEND API
# =========================
def send_text_message(psid: str, text: str):
    if not PAGE_ACCESS_TOKEN:
        print("❌ PAGE_ACCESS_TOKEN missing")
        return

    url = "https://graph.facebook.com/v20.0/me/messages"
    payload = {
        "recipient": {"id": psid},
        "message": {"text": text},
        "messaging_type": "RESPONSE",
    }
    params = {"access_token": PAGE_ACCESS_TOKEN}

    try:
        r = requests.post(url, params=params, json=payload, timeout=20)
        if r.status_code != 200:
            print("❌ Send API error:", r.status_code, r.text)
    except Exception as e:
        print("❌ Send API exception:", str(e))


# =========================
# AI (Groq OpenAI-Compatible)
# =========================
SYSTEM_PROMPT = f"""
Anda adalah NK Age-Reverse AI (Malaysia). Tugas: bantu pelanggan memilih skincare NK dan convert kepada order.

RULES (WAJIB):
1) Gaya bahasa: BM santai + mesra + ringkas tapi convincing. Jangan terlalu panjang meleret.
2) Fokus sales: tanya soalan susulan yang tepat untuk qualify lead (jenis kulit, masalah utama, rutin sekarang, bajet, dan target result).
3) Bila pelanggan tanya produk NK apa-apa, jawab dan bagi link rasmi dari domain {NK_OFFICIAL_DOMAIN} jika sesuai.
4) Jangan claim benda pelik/medical. Jika isu serius (ruam teruk/alergi) sarankan patch test & jumpa doktor.
5) Sentiasa akhiri dengan CTA yang jelas:
   - “Nak saya cadangkan routine lengkap + link order?”
   - atau “Nak order sekarang? Saya bagi link rasmi.”
6) Jika pelanggan tanya produk lain selain Age-Reverse, jawab secara umum, dan arahkan ke link rasmi:
   {NK_OFFICIAL_PRODUCTS}

Maklumat penting:
- Link order rasmi: {NK_OFFICIAL_PRODUCTS}

Output format:
- Jangan guna markdown.
- Gunakan emoji minimal (1-2) bila sesuai.
"""

def call_ai(messages: List[Dict[str, str]]) -> Optional[str]:
    """
    Uses Groq OpenAI-compatible endpoint by default.
    Returns assistant content or None on error.
    """
    if AI_PROVIDER != "groq":
        print(f"⚠️ AI_PROVIDER not supported in this code: {AI_PROVIDER}")
        return None

    if not AI_API_KEY:
        print("❌ AI_API_KEY missing")
        return None

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json"
    }

    body = {
        "model": AI_MODEL or "llama3-8b-8192",
        "messages": messages,
        "temperature": 0.6
    }

    try:
        r = requests.post(url, headers=headers, json=body, timeout=30)

        # DEBUG LOGS (Render will show these)
        print("AI STATUS:", r.status_code)
        if r.status_code != 200:
            print("AI ERROR BODY:", r.text[:2000])
            return None

        data = r.json()
        return data["choices"][0]["message"]["content"]

    except Exception as e:
        print("AI EXCEPTION:", str(e))
        return None


# =========================
# SALES / LEAD LOGIC (Hybrid)
# - If message short, we guide with flow.
# - Otherwise we let AI handle with context.
# =========================
def normalize_text(s: str) -> str:
    return (s or "").strip().lower()

def quick_flow_reply(psid: str, user_text: str) -> Optional[str]:
    """
    Returns a direct scripted reply if matches simple flow.
    Otherwise None (then AI handles).
    """
    st = get_state(psid)
    t = normalize_text(user_text)

    # greetings
    if t in {"hi", "hai", "hello", "helo", "hey", "assalamualaikum", "salam"}:
        st["stage"] = "ask_skin"
        return ("Hai 😊 Saya NK Age-Reverse AI. "
                "Kulit awak lebih kepada kering, berminyak, sensitif atau mudah jerawat?")

    # detect skin types
    skin_map = {
        "kering": ["kering", "dry", "kulit kering"],
        "berminyak": ["berminyak", "oily", "kulit berminyak"],
        "sensitif": ["sensitif", "sensitive"],
        "kombinasi": ["kombinasi", "combination", "campur", "mix"],
        "jerawat": ["jerawat", "acne", "berjerawat", "breakout"]
    }

    def match_any(words: List[str]) -> bool:
        return any(w in t for w in words)

    if st["stage"] in {"ask_skin", "start"}:
        for skin, words in skin_map.items():
            if match_any(words):
                st["skin_type"] = skin
                st["stage"] = "ask_concern"
                return (f"Okay noted: {skin} 👍 "
                        "Masalah utama awak sekarang apa ya—garis halus, pori besar, kusam, jerawat, atau kulit mudah kering/tegang?")

    # user states concern
    if st["stage"] == "ask_concern":
        # quick detect
        if any(k in t for k in ["garis", "fine line", "kedut", "wrinkle"]):
            st["concern"] = "garis halus"
        elif any(k in t for k in ["jerawat", "acne", "breakout", "parut"]):
            st["concern"] = "jerawat"
        elif any(k in t for k in ["kusam", "dull", "glow", "cerah"]):
            st["concern"] = "kusam"
        elif any(k in t for k in ["pori", "pore"]):
            st["concern"] = "pori"
        elif any(k in t for k in ["kering", "tegang", "menggelupas"]):
            st["concern"] = "kering/tegang"
        else:
            # if too vague, let AI
            return None

        st["stage"] = "pitch_cleanser"
        return (f"Faham 😊 Untuk {st['skin_type']} + isu {st['concern']}, "
                "NK Age-Reverse Cleanser memang sesuai sebab bantu bersih tanpa keringkan kulit & support anti-aging.\n\n"
                "Awak nak routine paling ringkas (cleanser sahaja) atau nak saya cadangkan set 2-3 step sekali?")

    # user wants cleanser
    if "cleanser" in t or "pencuci" in t or "cuci muka" in t:
        st["stage"] = "close"
        return ("Baik 😊 NK Age-Reverse Cleanser memang best untuk start.\n"
                "Nak saya bagi cara pakai ikut kulit awak + link order rasmi?")

    # If user asks "link" or "order"
    if any(k in t for k in ["link", "order", "beli", "checkout", "buy"]):
        st["stage"] = "close"
        return (f"Ini link rasmi NK (produk skincare): {NK_OFFICIAL_PRODUCTS}\n"
                "Awak nak saya suggest produk paling sesuai dulu ikut kulit awak? 😊")

    return None


def build_ai_messages(psid: str, user_text: str) -> List[Dict[str, str]]:
    st = get_state(psid)
    history = st.get("history", [])

    # Add a small context summary (state)
    state_summary = f"STATE: skin_type={st.get('skin_type')}, concern={st.get('concern')}, stage={st.get('stage')}."

    msgs = [{"role": "system", "content": SYSTEM_PROMPT + "\n\n" + state_summary}]
    # include last history
    for h in history:
        msgs.append({"role": h["role"], "content": h["content"]})
    msgs.append({"role": "user", "content": user_text})
    return msgs


# =========================
# ROUTES
# =========================
@app.get("/")
def root():
    return {"status": "ok", "service": "osa-messenger-ai", "public_url": PUBLIC_URL or "not_set"}

@app.get("/health")
def health():
    return {"ok": True, "ts": now_ts()}

@app.get("/webhook")
def verify_webhook(
    hub_mode: Optional[str] = None,
    hub_verify_token: Optional[str] = None,
    hub_challenge: Optional[str] = None,
    **kwargs
):
    """
    Facebook webhook verification:
    GET /webhook?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...
    """
    # FastAPI gives query params differently; support both ways
    # Sometimes params are passed as "hub.mode" keys
    if hub_mode is None:
        # fallback to kwargs
        hub_mode = kwargs.get("hub.mode")
        hub_verify_token = kwargs.get("hub.verify_token")
        hub_challenge = kwargs.get("hub.challenge")

    print("VERIFY REQ:", hub_mode, hub_verify_token, hub_challenge)

    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(content=str(hub_challenge or ""), status_code=200)

    return PlainTextResponse(content="Verification token mismatch", status_code=403)


@app.post("/webhook")
async def webhook(request: Request):
    """
    Receive events from Facebook Messenger.
    """
    body = await request.json()
    print("WEBHOOK IN:", json.dumps(body)[:2000])

    # Acknowledge quickly
    # Then process
    if body.get("object") == "page":
        for entry in body.get("entry", []):
            messaging_events = entry.get("messaging", [])
            for event in messaging_events:
                # Ignore delivery/read echoes
                if event.get("message") and event["message"].get("is_echo"):
                    continue

                sender = event.get("sender", {}).get("id")
                if not sender:
                    continue

                # Text message
                msg = event.get("message", {})
                text = msg.get("text", "").strip()
                if not text:
                    # if attachments etc
                    send_text_message(sender, "Saya boleh bantu 😊 Boleh taip soalan atau tulis masalah kulit awak ya.")
                    continue

                # Save user text
                add_history(sender, "user", text)

                # 1) Try quick flow
                scripted = quick_flow_reply(sender, text)
                if scripted:
                    send_text_message(sender, scripted)
                    add_history(sender, "assistant", scripted)
                    continue

                # 2) Else AI handles
                msgs = build_ai_messages(sender, text)
                ai_reply = call_ai(msgs)

                if not ai_reply:
                    fallback = ("Maaf, AI tengah sibuk sekejap. "
                                "Boleh ulang soalan anda sekali lagi? 🙂\n\n"
                                f"Link order rasmi: {NK_OFFICIAL_PRODUCTS}")
                    send_text_message(sender, fallback)
                    add_history(sender, "assistant", fallback)
                    continue

                # Ensure CTA + link if user shows buying intent
                low = normalize_text(text)
                if any(k in low for k in ["order", "beli", "link", "harga", "price", "checkout"]):
                    if NK_OFFICIAL_PRODUCTS not in ai_reply:
                        ai_reply = ai_reply.strip() + f"\n\nLink order rasmi: {NK_OFFICIAL_PRODUCTS}"

                send_text_message(sender, ai_reply)
                add_history(sender, "assistant", ai_reply)

    return Response(status_code=200)
