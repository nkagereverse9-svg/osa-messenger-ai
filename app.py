import os
import time
import requests
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse

app = FastAPI()

# =========================
# ENV (Render)
# =========================
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "nkverify123").strip()
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "").strip()

AI_PROVIDER = os.getenv("AI_PROVIDER", "groq").strip().lower()  # groq
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "llama-3.1-8b-instant").strip()

GRAPH_URL = "https://graph.facebook.com/v20.0/me/messages"

# =========================
# OFFICIAL NKAR FACTS (locked)
# =========================
CATALOG_URL = "https://nkarofficial.com/our-products/"
PRODUCTS = [
    {
        "name": "NK Age-Reverse Cleanser 100ML",
        "price": "RM149.00",
        "url": "https://nkarofficial.com/our-products/skincare/nk-age-reverse-cleanser/",
        "notes": [
            "Gentle cleanse; supports smoother-looking skin",
            "Helps appearance of fine lines & wrinkles (marketing claim on official page)",
            "Suitable for all skin types (official page)",
            "Key ingredients listed: Hyaluronic Acid, Bee Venom, Roselle, Tsubaki, essential oils"
        ],
    },
    {
        "name": "NK Age-Reverse Sunscreen 30ML",
        "price": "RM169.00",
        "url": "https://nkarofficial.com/our-products/skincare/nk-age-reverse-sunscreen/",
        "notes": [
            "Daytime protection; suitable all skin types (official page)",
        ],
    },
    {
        "name": "NK Age-Reverse Serum 30ML",
        "price": "RM229.00",
        "url": "https://nkarofficial.com/our-products/skincare/age-reverse-serum-30ml/",
        "notes": [
            "Serum option in NK Age-Reverse line (official page)",
        ],
    },
    {
        "name": "Energy Water Mist 100ML",
        "price": "RM139.00",
        "url": "https://nkarofficial.com/our-products/skincare/energy-water-mist/",
        "notes": [
            "Mist option in NK line (official page)",
        ],
    },
    {
        "name": "NK Age-Reverse Oil Cleanser",
        "price": "RM129.00 (price may show promo on site)",
        "url": "https://nkarofficial.com/our-products/skincare/nk-age-reverse-oil-cleanser/",
        "notes": [
            "Oil cleanser for double cleansing (official page)",
        ],
    },
    {
        "name": "NK Age-Reverse Travel Set",
        "price": "RM249.00",
        "url": "https://nkarofficial.com/our-products/skincare/nk-age-reverse-travel-set/",
        "notes": [
            "Travel set option (official page)",
        ],
    },
    {
        "name": "NK Age-Reverse Premium Box",
        "price": "RM649.00",
        "url": "https://nkarofficial.com/our-products/skincare/nk-age-reverse-premium-box/",
        "notes": [
            "Full set option (official page)",
        ],
    },
    {
        "name": "[Limited Edition] NK Age-Reverse Raya Gift Set",
        "price": "RM188.00",
        "url": "https://nkarofficial.com/our-products/skincare/limited-edition-nk-age-reverse-raya-gift-set/",
        "notes": [
            "Limited edition set (official page)",
        ],
    },
]

def product_list_text() -> str:
    lines = []
    for p in PRODUCTS:
        lines.append(f"- {p['name']} — {p['price']} — {p['url']}")
    return "\n".join(lines)

NK_SYSTEM = f"""
You are the official NK Age-Reverse Skincare Assistant for Facebook Messenger.

TONE:
- Friendly Malaysian beauty consultant
- Reply in user's language (Malay if Malay, English if English, mixed if mixed)
- Short-to-medium replies, 1–2 emojis max
- Always ask ONE helpful follow-up question
- Soft selling: help first, then guide to order

SAFETY:
- No medical diagnosis, no guaranteed results
- If user reports irritation/rash/burning: advise stop use, rinse, and seek medical advice if severe

OFFICIAL LINKS:
- Catalog: {CATALOG_URL}

OFFICIAL PRODUCTS + PRICES + LINKS (DO NOT INVENT):
{product_list_text()}

RULES:
- If user asks price/order: state the official price and provide the official link.
- If user asks about other products: give brief overview + share catalog link, do not invent extra claims/ingredients.
- If user is new: recommend starting with Cleanser; for daytime suggest Sunscreen; suggest Serum/Mist based on concern.
- End every reply with a gentle question to continue conversation.
""".strip()

# =========================
# Simple in-memory memory (resets if Render restarts)
# =========================
MEM = {}  # psid -> [(role, content, ts)]

def add_mem(psid: str, role: str, content: str):
    MEM.setdefault(psid, []).append((role, content, time.time()))
    MEM[psid] = MEM[psid][-8:]

def get_mem(psid: str):
    return MEM.get(psid, [])

def detect_lang(text: str) -> str:
    t = (text or "").lower()
    bm = sum(w in t for w in ["saya","nak","berapa","harga","macam","cara","guna","kulit","sesuai","promo","beli","pos","negeri","salam","hai"])
    en = sum(w in t for w in ["price","how","use","skin","suitable","order","delivery","hello","hi"])
    if bm > en + 1:
        return "ms"
    if en > bm + 1:
        return "en"
    return "mix"

# =========================
# AI Call (Groq OpenAI-compatible)
# =========================
def call_ai(messages):
    if not AI_API_KEY or AI_PROVIDER != "groq":
        return None
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": AI_MODEL, "messages": messages, "temperature": 0.6}
    r = requests.post(url, headers=headers, json=payload, timeout=25)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

# =========================
# Fallback replies (if AI not available)
# =========================
def fallback_reply(text: str) -> str:
    lang = detect_lang(text)
    t = (text or "").lower()

    if any(k in t for k in ["harga","price","promo","order","beli","checkout"]):
        return (
            "Boleh 😊 Produk mana yang anda maksudkan ya? (Cleanser / Sunscreen / Serum / Mist / Oil Cleanser / Travel Set / Premium Box)\n"
            f"Catalog official: {CATALOG_URL}\n\n"
            "Anda berada di negeri/bandar mana untuk delivery?"
        ) if lang != "en" else (
            "Sure 😊 Which product do you mean? (Cleanser / Sunscreen / Serum / Mist / Oil Cleanser / Travel Set / Premium Box)\n"
            f"Official catalog: {CATALOG_URL}\n\n"
            "Which state/city are you in for delivery?"
        )

    return (
        "Hi 😊 Saya boleh bantu pasal NK Age-Reverse.\n"
        "Boleh share jenis kulit anda (kering/berminyak/sensitif) & fokus masalah apa? ✨"
    ) if lang != "en" else (
        "Hi 😊 I can help with NK Age-Reverse.\n"
        "What’s your skin type (dry/oily/sensitive) and your main concern? ✨"
    )

# =========================
# Smart reply function
# =========================
def smart_reply(psid: str, user_text: str) -> str:
    t = (user_text or "").lower()
    lang = detect_lang(user_text)

    # Safety hard-rule
    if any(k in t for k in ["ruam","gatal","pedih","rash","itch","burn","burning","irritation","merah"]):
        return (
            "Maaf awak alami macam tu 😥\n\n"
            "Untuk keselamatan:\n"
            "✅ Stop guna dulu\n✅ Bilas dengan air bersih\n"
            "✅ Jika teruk/berpanjangan, jumpa doktor\n\n"
            "Boleh share jenis kulit (kering/berminyak/sensitif) & produk NK yang awak guna?"
        ) if lang != "en" else (
            "Sorry you’re experiencing that 😥\n\n"
            "For safety:\n"
            "✅ Stop using it for now\n✅ Rinse with clean water\n"
            "✅ If severe/persistent, see a doctor\n\n"
            "What’s your skin type (dry/oily/sensitive) and which NK product did you use?"
        )

    # Build messages with memory
    msgs = [{"role": "system", "content": NK_SYSTEM}]
    for role, content, _ts in get_mem(psid):
        msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": user_text})

    # Try AI
    try:
        ai = call_ai(msgs)
        if ai and ai.strip():
            return ai.strip()
    except Exception as e:
        print("AI error:", e)

    # Fallback
    return fallback_reply(user_text)

# =========================
# Send message to FB
# =========================
def send_text_message(psid: str, text: str):
    if not PAGE_ACCESS_TOKEN:
        print("ERROR: PAGE_ACCESS_TOKEN missing")
        return

    payload = {"recipient": {"id": psid}, "message": {"text": text}}
    params = {"access_token": PAGE_ACCESS_TOKEN}
    r = requests.post(GRAPH_URL, params=params, json=payload, timeout=15)
    if r.status_code >= 400:
        print("FB SEND ERROR:", r.status_code, r.text)

# =========================
# Routes
# =========================
@app.get("/", response_class=PlainTextResponse)
def home():
    return "OK"

@app.get("/webhook", response_class=PlainTextResponse)
def verify_webhook(request: Request):
    q = request.query_params
    mode = q.get("hub.mode")
    token = q.get("hub.verify_token")
    challenge = q.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
        return challenge

    raise HTTPException(status_code=403, detail="Verification failed")

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()

    if data.get("object") != "page":
        return {"ok": True}

    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            psid = event.get("sender", {}).get("id")
            if not psid:
                continue

            msg = event.get("message", {})
            if msg and "text" in msg:
                user_text = (msg.get("text") or "").strip()
                if not user_text:
                    continue

                add_mem(psid, "user", user_text)
                reply = smart_reply(psid, user_text)
                add_mem(psid, "assistant", reply)
                send_text_message(psid, reply)

    return {"ok": True}
