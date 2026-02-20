import os
import time
import json
import re
from typing import Any, Dict, List

import requests
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse

# =========================================================
# ENV
# =========================================================
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "").strip()
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "").strip()

AI_PROVIDER = os.getenv("AI_PROVIDER", "groq").strip().lower()
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "llama-3.1-8b-instant").strip()

# Public URL (optional)
PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip()

# OFFICIAL LINKS (IMPORTANT)
OFFICIAL_DOMAIN = os.getenv("OFFICIAL_DOMAIN", "nkarofficial.com").strip().lower()

# Because your old link sometimes 404, keep this configurable
OFFICIAL_ORDER_LINK = os.getenv("OFFICIAL_ORDER_LINK", "https://nkarofficial.com/").strip()

# WhatsApp (from your screenshot)
WHATSAPP_NUMBER = os.getenv("WHATSAPP_NUMBER", "+60199009677").strip()
WHATSAPP_LINK = os.getenv(
    "WHATSAPP_LINK",
    "https://wa.me/60199009677"
).strip()

BRAND_NAME = os.getenv("BRAND_NAME", "NK Age-Reverse").strip()

# =========================================================
# PRODUCT CATALOG (EDIT this to match your REAL catalog)
# - AI is FORBIDDEN from inventing products outside this list.
# - Add/adjust based on your catalog cards.
# =========================================================
PRODUCT_CATALOG: List[Dict[str, Any]] = [
    {
        "name": "NK Age-Reverse Cleanser",
        "category": "cleanser",
        "price_rm": 149,
        "for_skin": ["berminyak", "kombinasi", "kusam", "garis_halus", "kering", "sensitif"],
        "benefits": [
            "Cuci bersih tanpa rasa ketat",
            "Bantu kurangkan rasa ‘berat’/berminyak di permukaan",
            "Sesuai untuk rutin pagi & malam"
        ],
        "order_hint": "Cleanser",
    },
    {
        "name": "NK Age-Reverse Serum",
        "category": "serum",
        "price_rm": 229,
        "for_skin": ["kusam", "garis_halus", "kering", "kombinasi"],
        "benefits": [
            "Bantu kulit nampak lebih segar & glow (ikut kesesuaian kulit)",
            "Sesuai untuk kulit nampak kusam / tanda awal penuaan",
        ],
        "order_hint": "Serum",
    },
    {
        "name": "NK Age-Reverse Sunscreen",
        "category": "sunscreen",
        "price_rm": 169,
        "for_skin": ["semua", "berminyak", "kombinasi", "kering"],
        "benefits": [
            "Bantu lindungi kulit waktu siang",
            "Step penting kalau nak maintain hasil skincare"
        ],
        "order_hint": "Sunscreen",
    },
    {
        "name": "Energy Water Mist",
        "category": "mist",
        "price_rm": 139,
        "for_skin": ["semua", "kusam", "kering", "dehydrated"],
        "benefits": [
            "Bantu refresh kulit bila rasa kering/tegang",
            "Senang top-up sepanjang hari"
        ],
        "order_hint": "Mist",
    },
    {
        "name": "Travel Set",
        "category": "set",
        "price_rm": 249,
        "for_skin": ["semua"],
        "benefits": [
            "Sesuai untuk cuba dulu / travel",
            "Convenient untuk beginner"
        ],
        "order_hint": "Travel Set",
    },
    {
        "name": "Premium Box",
        "category": "set",
        "price_rm": 649,
        "for_skin": ["semua"],
        "benefits": [
            "Pilihan hadiah / lengkapkan routine",
        ],
        "order_hint": "Premium Box",
    },
    {
        "name": "Two Way Cake",
        "category": "makeup",
        "price_rm": 110,
        "for_skin": ["semua"],
        "benefits": [
            "Makeup finishing (ikut kesesuaian kulit)"
        ],
        "order_hint": "Two Way Cake",
    },
    {
        "name": "NK Rosserie",
        "category": "skincare",
        "price_rm": 189,
        "for_skin": ["semua"],
        "benefits": [
            "Skincare support (ikut kesesuaian kulit)"
        ],
        "order_hint": "NK Rosserie",
    },
]

# =========================================================
# IN-MEMORY STATE (Render free may reset when sleeping)
# =========================================================
USER_STATE: Dict[str, Dict[str, Any]] = {}

def now_ts() -> int:
    return int(time.time())

def get_state(psid: str) -> Dict[str, Any]:
    if psid not in USER_STATE:
        USER_STATE[psid] = {
            "stage": "start",
            "skin": "",
            "concern": "",
            "intent": "",       # e.g. order/price/routine
            "interested": False,
            "last_reco": [],
            "last_user_text": "",
        }
    return USER_STATE[psid]

# =========================================================
# TEXT NORMALIZATION / DETECTION
# =========================================================
def norm(t: str) -> str:
    return (t or "").strip().lower()

def contains_any(t: str, keys: List[str]) -> bool:
    return any(k in t for k in keys)

def detect_intent(t: str) -> str:
    # intent priority
    if contains_any(t, ["harga", "price", "berapa", "rm", "cost"]):
        return "price"
    if contains_any(t, ["cara order", "macam mana order", "how to order", "order", "beli", "purchase", "checkout"]):
        return "order"
    if contains_any(t, ["link", "website", "url"]):
        return "link"
    if contains_any(t, ["routine", "cara guna", "step", "pemakaian", "pakai macam mana"]):
        return "routine"
    return ""

def update_skin_concern(state: Dict[str, Any], t: str) -> None:
    # skin
    if contains_any(t, ["berminyak", "oily", "minyak"]):
        state["skin"] = "berminyak"
    elif contains_any(t, ["kering", "dry"]):
        state["skin"] = "kering"
    elif contains_any(t, ["kombinasi", "combination"]):
        state["skin"] = "kombinasi"
    elif contains_any(t, ["sensitif", "sensitive", "mudah pedih", "merah", "iritasi"]):
        state["skin"] = "sensitif"

    # concerns
    if contains_any(t, ["jerawat", "acne", "breakout", "pimples"]):
        state["concern"] = "jerawat"
    elif contains_any(t, ["kusam", "dull", "tak berseri", "gelap"]):
        state["concern"] = "kusam"
    elif contains_any(t, ["garis halus", "fine line", "wrinkle", "kedut"]):
        state["concern"] = "garis_halus"
    elif contains_any(t, ["menggelupas", "peeling", "flaky", "mengelupas"]):
        state["concern"] = "menggelupas"

def detect_interest(t: str) -> bool:
    return contains_any(t, [
        "nak beli", "nak order", "saya nak", "boleh order", "macam mana beli",
        "bagi link", "send link", "ok saya ambil", "ambil", "deal"
    ])

def interpret_colloquial(t: str) -> str:
    # Normalize common Malaysian chat slang
    # "tak guna dua dua" => user means they don't use both (cleanser & serum)
    if contains_any(t, ["dua dua", "dua-dua", "2 2", "2-2"]):
        if contains_any(t, ["tak", "tidak", "x", "takde"]):
            return "tak_guna_kedua"
    return ""

# =========================================================
# RECOMMENDATION LOGIC (rule-based, to keep answers consistent)
# =========================================================
def pick_products(skin: str, concern: str) -> List[Dict[str, Any]]:
    picks = []

    def add_if(name: str):
        for p in PRODUCT_CATALOG:
            if p["name"].lower() == name.lower():
                picks.append(p)

    # Simple bundle logic
    if concern in ["kusam", "garis_halus"]:
        add_if("NK Age-Reverse Cleanser")
        add_if("NK Age-Reverse Serum")
    elif skin == "berminyak":
        add_if("NK Age-Reverse Cleanser")
        # for oily + daytime protection
        add_if("NK Age-Reverse Sunscreen")
    elif concern == "menggelupas":
        # be gentle: cleanser + mist suggestion
        add_if("NK Age-Reverse Cleanser")
        add_if("Energy Water Mist")
    else:
        add_if("NK Age-Reverse Cleanser")

    # Remove duplicates while preserving order
    seen = set()
    uniq = []
    for p in picks:
        if p["name"] not in seen:
            uniq.append(p)
            seen.add(p["name"])
    return uniq[:2]

def format_price_line(p: Dict[str, Any]) -> str:
    pr = p.get("price_rm")
    if pr:
        return f"• {p['name']} — RM {pr}"
    return f"• {p['name']}"

# =========================================================
# HUMAN SALES PSYCHOLOGY PROMPT (AI)
# =========================================================
def catalog_text() -> str:
    lines = []
    for p in PRODUCT_CATALOG:
        lines.append(
            f"- {p['name']} | kategori: {p['category']} | harga: RM {p.get('price_rm','-')} | sesuai: {', '.join(p['for_skin'])}"
        )
    return "\n".join(lines)

SYSTEM_PROMPT = f"""
Anda ialah “{BRAND_NAME} Human Sales Assistant” — gaya manusia, mesra & santai (macam admin betul) 😄

WAJIB:
1) Hanya sebut produk yang ada dalam PRODUCT_CATALOG.
2) Jangan cipta produk / jangan cipta fakta ingredient / jangan claim berlebihan.
3) Jangan spam link. Link hanya bagi bila user minta “link/cara order/harga” atau user dah menunjukkan minat nak beli.
4) Bila user tanya harga — jawab terus dengan harga (RM) ikut catalog.
5) Bila user tanya cara order — beri 2 pilihan:
   A) Website: {OFFICIAL_ORDER_LINK}
   B) WhatsApp HQ: {WHATSAPP_NUMBER} ({WHATSAPP_LINK})
6) Bahasa BM santai + emoji (1–3 emoji sahaja), ayat pendek, nampak natural.

GAYA “CLOSER MODE” (soft):
- Tanya 1 soalan sahaja kalau info kurang.
- Bila user dah jelas berminat: ajak pilih “Cleanser sahaja” atau “Cleanser + Serum”.
- Guna CTA lembut: “Nak saya bantu pilih set paling ngam?” / “Nak saya bagi step cara pakai?” / “Nak saya tolong orderkan?”

OUTPUT:
- Maks 6–10 baris sahaja.
- Jangan tulis label pelik macam “Empati:” “Question:”.
- Jangan ulang link setiap mesej.

PRODUCT_CATALOG:
{catalog_text()}
""".strip()

def build_user_prompt(user_text: str, state: Dict[str, Any], reco: List[Dict[str, Any]]) -> str:
    reco_names = [p["name"] for p in reco]
    return f"""
STATE:
stage={state.get('stage')}
skin={state.get('skin')}
concern={state.get('concern')}
intent={state.get('intent')}
interested={state.get('interested')}
last_reco={reco_names}

USER:
{user_text}

TASK:
- Balas ikut rules & gaya “human”.
- Jika user tanya harga/cara order, jawab terus + bagi pilihan website/WhatsApp.
- Jika user berminat, bantu close (pilihan set) tanpa memaksa.
""".strip()

def strip_non_official_urls(text: str) -> str:
    urls = re.findall(r"https?://\S+", text)
    for u in urls:
        # allow only official domain + wa.me link
        if (OFFICIAL_DOMAIN not in u) and ("wa.me" not in u):
            text = text.replace(u, "")
    return text.strip()

def safe_fallback_reply(state: Dict[str, Any]) -> str:
    # fallback = still human + ask 1 question only
    if state.get("skin"):
        return f"Okay 😊 Kulit {state['skin']} ya. Awak lebih risau pasal kusam, jerawat, atau nak control minyak je?"
    return "Hi 😊 Awak kulit jenis kering, berminyak, kombinasi atau sensitif ya?"

# =========================================================
# GROQ CALL (OpenAI-compatible endpoint)
# =========================================================
def call_groq_chat(system: str, user: str, model: str) -> str:
    if not AI_API_KEY:
        raise RuntimeError("AI_API_KEY not set")

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.7,
        "max_tokens": 260,
    }

    r = requests.post(url, headers=headers, json=payload, timeout=25)
    if r.status_code >= 400:
        raise RuntimeError(f"AI HTTP {r.status_code}: {r.text}")

    data = r.json()
    return data["choices"][0]["message"]["content"]

# =========================================================
# FB MESSENGER SEND
# =========================================================
def fb_send_text(psid: str, text: str) -> None:
    if not PAGE_ACCESS_TOKEN:
        raise RuntimeError("PAGE_ACCESS_TOKEN not set")

    url = "https://graph.facebook.com/v20.0/me/messages"
    params = {"access_token": PAGE_ACCESS_TOKEN}
    payload = {
        "recipient": {"id": psid},
        "message": {"text": text},
        "messaging_type": "RESPONSE",
    }

    r = requests.post(url, params=params, json=payload, timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"FB SEND ERROR {r.status_code}: {r.text}")

# =========================================================
# RULE-BASED DIRECT ANSWERS (price/order/link) to avoid AI mistakes
# =========================================================
def direct_price_reply(state: Dict[str, Any]) -> str:
    skin = state.get("skin", "")
    concern = state.get("concern", "")
    reco = pick_products(skin, concern)
    if not reco:
        reco = PRODUCT_CATALOG[:2]

    lines = ["Sure 😊 Ini range harga (catalog HQ):"]
    for p in reco:
        lines.append(format_price_line(p))

    lines.append("")
    lines.append("Nak awak prefer ambil *Cleanser sahaja* atau *Cleanser + Serum*? 😉")
    return "\n".join(lines).strip()

def direct_order_reply() -> str:
    return (
        "Boleh 😊 Cara order ada 2 cara:\n"
        f"1) Website rasmi: {OFFICIAL_ORDER_LINK}\n"
        f"2) WhatsApp HQ: {WHATSAPP_NUMBER} ({WHATSAPP_LINK})\n\n"
        "Kalau awak bagitahu nak produk mana, saya susunkan step & confirm total ya 😉"
    ).strip()

def maybe_add_link_only_when_needed(text: str, intent: str, interested: bool) -> str:
    text = strip_non_official_urls(text)

    # Only attach order options if user asks or is clearly interested
    if intent in ["order", "link"] or interested:
        # if AI didn't include any official links, add a short CTA footer
        if (OFFICIAL_DOMAIN not in text) and ("wa.me" not in text):
            text += (
                f"\n\nOrder:\n"
                f"• Website: {OFFICIAL_ORDER_LINK}\n"
                f"• WhatsApp HQ: {WHATSAPP_NUMBER} ({WHATSAPP_LINK})"
            )
    return text.strip()

# =========================================================
# FASTAPI APP
# =========================================================
app = FastAPI()

@app.get("/")
def home():
    return {"ok": True, "service": "osa-messenger-ai", "ts": now_ts()}

@app.get("/webhook")
def verify_webhook(hub_mode: str = "", hub_verify_token: str = "", hub_challenge: str = ""):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge)
    return PlainTextResponse("Verification token mismatch", status_code=403)

@app.post("/webhook")
async def webhook(request: Request):
    body = await request.json()
    print("WEBHOOK IN:", json.dumps(body)[:4000])

    if body.get("object") != "page":
        return JSONResponse({"ok": True})

    for entry in body.get("entry", []):
        for event in entry.get("messaging", []):
            if "message" not in event:
                continue

            sender = event["sender"]["id"]
            message = event["message"]

            if message.get("is_echo"):
                continue

            text = (message.get("text") or "").strip()
            if not text:
                continue

            state = get_state(sender)
            t = norm(text)
            state["last_user_text"] = text

            # detect intent + interest
            state["intent"] = detect_intent(t)
            state["interested"] = detect_interest(t) or state.get("interested", False)

            # interpret colloquial
            slang = interpret_colloquial(t)
            if slang == "tak_guna_kedua":
                # treat as: user doesn't use both cleanser & serum
                # push toward a simple recommendation flow
                if not state.get("skin"):
                    state["skin"] = "berminyak" if "minyak" in t else state.get("skin", "")

            # update skin + concern
            update_skin_concern(state, t)

            # stage shift
            if state["stage"] == "start" and (state.get("skin") or state.get("concern")):
                state["stage"] = "qualify"

            # Direct rule-based replies for price/order to avoid AI hallucination
            try:
                if state["intent"] == "price":
                    reply = direct_price_reply(state)
                elif state["intent"] in ["order", "link"]:
                    reply = direct_order_reply()
                else:
                    # Normal recommendation
                    reco = pick_products(state.get("skin", ""), state.get("concern", ""))
                    state["last_reco"] = [p["name"] for p in reco]

                    user_prompt = build_user_prompt(text, state, reco)

                    if AI_PROVIDER == "groq":
                        reply = call_groq_chat(SYSTEM_PROMPT, user_prompt, AI_MODEL)
                    else:
                        reply = safe_fallback_reply(state)

                reply = maybe_add_link_only_when_needed(reply, state["intent"], state["interested"])

            except Exception as e:
                print("AI ERROR:", str(e))
                reply = safe_fallback_reply(state)

            # Send back to Messenger
            try:
                fb_send_text(sender, reply)
            except Exception as e:
                print("FB SEND ERROR:", str(e))

    return JSONResponse({"ok": True})
