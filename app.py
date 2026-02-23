import os
import re
import time
from typing import Dict, Any, Optional, Tuple, List

from flask import Flask, request, jsonify

# pip install groq flask
from groq import Groq

app = Flask(__name__)

# -------------------------
# Config
# -------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
if not GROQ_API_KEY:
    raise RuntimeError("Missing GROQ_API_KEY env var")

MODEL = os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")
PORT = int(os.getenv("PORT", "5000"))

# Meta webhook (optional)
VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "verify_token_change_me")

client = Groq(api_key=GROQ_API_KEY)

# -------------------------
# Product Knowledge Base (edit ikut latest HQ)
# -------------------------
PRODUCTS = {
    "nk_age_reverse_cleanser_100ml": {
        "name": "NK Age-Reverse Cleanser 100ml",
        "price": 149.00,
        "currency": "RM",
        "active_ingredients": [
            "Hyaluronic Acid",
            "Bee Venom",
            "Hibiscus sabdariffa (Roselle)",
            "Camellia japonica (Tsubaki)",
            "Essential Oil (Geranium, Rosewood, Lavender, Lemon, Peppermint)",
        ],
        "best_for": ["kusam", "antiaging", "garis halus", "kulit berminyak (lebih seimbang)"],
        "how_to_use": [
            "Basahkan muka, ambil 1-2 pump dan urut lembut 30-60 saat.",
            "Bilas. Boleh guna pagi & malam.",
        ],
        "notes": [
            "Jika kulit sensitif/baru tukar skincare: mula 1x sehari dulu 3-5 hari, kemudian naikkan.",
        ],
    },
    "nk_age_reverse_serum_30ml": {
        "name": "NK Age-Reverse Serum 30ml",
        "price": 229.00,
        "currency": "RM",
        "active_ingredients": [
            "Encapsulated Nano-Retinol",
            "Hibiscus sabdariffa flower extract (Roselle)",
            "Camellia japonica (Tsubaki)",
            "Paeonia albiflora (Peony)",
            "Hyaluronic acid (heavy & light molecules)",
            "Natural herbal extract (Cynanchum Atratum)",
        ],
        "best_for": ["garis halus", "tekstur kulit", "tone tak sekata"],
        "how_to_use": [
            "Selepas cleanser, guna 1-2 titis pada muka kering.",
            "Pakai malam (untuk pemula).",
            "Siang WAJIB sunscreen.",
        ],
        "notes": [
            "Kalau kulit sensitif, start 2-3x seminggu dulu.",
        ],
    },
    "nk_age_reverse_sunscreen_30ml": {
        "name": "NK Age-Reverse Sunscreen 30ml",
        "price": 169.00,
        "currency": "RM",
        "active_ingredients": [
            "Bee venom",
            "Hyaluronic Acid",
            "Hibiscus sabdariffa extract (Roselle)",
            "Camellia japonica (Tsubaki)",
            "Paeonia albiflora (Peony)",
            "Carrot Seed Oil",
        ],
        "best_for": ["perlindungan UV", "tak melekit", "ringan"],
        "how_to_use": [
            "Pakai sebagai step terakhir waktu siang.",
            "Reapply setiap 2-3 jam jika outdoor.",
        ],
        "notes": [],
    },
    "nk_energy_water_mist_100ml": {
        "name": "Energy Water Mist 100ml",
        "price": 139.00,
        "currency": "RM",
        "active_ingredients": [
            "Bee venom",
            "Hyaluronic acid",
            "Rose Hydrosol",
            "Essential Oil (Rose, Geranium, Cedarwood)",
        ],
        "best_for": ["hydration", "kulit nampak segar", "comforting mist"],
        "how_to_use": [
            "Spray selepas cleanser / bila kulit rasa kering.",
        ],
        "notes": [],
    },
    "nk_travel_set": {
        "name": "NK Age-Reverse Travel Set",
        "price": 249.00,
        "currency": "RM",
        "contains": [
            "Cleanser 30ml",
            "Sunscreen 10ml",
            "Serum 10ml",
            "Energy Water Mist 25ml",
            "Limited edition pouch bag",
        ],
    },
    "nk_premium_box": {
        "name": "NK Age-Reverse Premium Box",
        "price": 649.00,
        "currency": "RM",
        "contains": [
            "Cleanser 100ml",
            "Sunscreen 30ml",
            "Serum 30ml",
            "Energy Water Mist 100ml",
            "Exclusive box",
        ],
    },
    "nkbt_face_cleanser_100ml": {
        "name": "NKBT Face Cleanser 100ml",
        "price": 84.00,
        "currency": "RM",
        "active_ingredients": ["Roselle", "Willow Bark", "Provitamin B5"],
        "best_for": ["kulit berminyak", "acne-prone", "pembersihan lembut"],
    },
    "nkbt_creeme_gel_50g": {
        "name": "NKBT Creeme-Gel 50g",
        "price": 87.00,
        "currency": "RM",
        "active_ingredients": ["Roselle", "Tamanu Oil", "Willow Bark", "Niacinamide"],
        "best_for": ["kulit berminyak", "acne-prone", "sebum control"],
    },
    "nkbt_sun_essence_20g": {
        "name": "NKBT Sun-Essence 20g",
        "price": 89.00,
        "currency": "RM",
        "active_ingredients": ["Roselle", "Willow Bark", "Provitamin B5"],
        "best_for": ["UV protection", "ringan", "tak clog pores"],
    },
}

ORDER_LINKS = {
    "whatsapp_hq": "https://wa.me/60199009677",
    # website link kamu kadang 404 pada path tertentu, so bagi homepage + whatsapp
    "website_home": "https://nkarofficial.com/",
}

# -------------------------
# Simple session memory (in-memory). For production use Redis/DB.
# -------------------------
SESSIONS: Dict[str, Dict[str, Any]] = {}
SESSION_TTL_SEC = 60 * 60 * 12  # 12 hours


def now_ts() -> float:
    return time.time()


def get_session(user_id: str) -> Dict[str, Any]:
    s = SESSIONS.get(user_id)
    if not s or (now_ts() - s.get("ts", 0) > SESSION_TTL_SEC):
        s = {"ts": now_ts(), "turns": [], "lead_score": 0, "last_link_ts": 0}
        SESSIONS[user_id] = s
    s["ts"] = now_ts()
    return s


# -------------------------
# Intent & lead scoring
# -------------------------
PRICE_PAT = re.compile(r"\b(harga|price|rm)\b", re.I)
ORDER_PAT = re.compile(r"\b(order|cara order|nak beli|purchase|checkout|link)\b", re.I)
INGR_PAT = re.compile(r"\b(ingredient|ingredients|bahan|aktif|active|bee venom|venom)\b", re.I)
INTEREST_PAT = re.compile(r"\b(nak|ingin|berminat|try|cuba|recommend|rekomen|sesuai)\b", re.I)


def detect_intents(text: str) -> Dict[str, bool]:
    return {
        "ask_price": bool(PRICE_PAT.search(text)),
        "ask_order": bool(ORDER_PAT.search(text)),
        "ask_ingredients": bool(INGR_PAT.search(text)),
        "show_interest": bool(INTEREST_PAT.search(text)),
    }


def bump_lead_score(sess: Dict[str, Any], intents: Dict[str, bool]) -> None:
    score = sess.get("lead_score", 0)
    if intents["show_interest"]:
        score += 2
    if intents["ask_price"]:
        score += 3
    if intents["ask_order"]:
        score += 4
    if intents["ask_ingredients"]:
        score += 1
    sess["lead_score"] = min(score, 20)


def should_send_link(sess: Dict[str, Any], intents: Dict[str, bool]) -> bool:
    # Only send link when customer is hot OR explicitly asking
    if intents["ask_order"] or intents["ask_price"]:
        return True
    if sess.get("lead_score", 0) >= 7:
        return True
    return False


def link_cooldown_ok(sess: Dict[str, Any]) -> bool:
    # avoid link spam: at most once per 10 minutes
    return (now_ts() - sess.get("last_link_ts", 0)) > 600


# -------------------------
# Ingredient lookup helper
# -------------------------
def find_product_by_keyword(text: str) -> List[Dict[str, Any]]:
    t = text.lower()
    hits = []
    for p in PRODUCTS.values():
        name = p.get("name", "").lower()
        if "cleanser" in t and "cleanser" in name:
            hits.append(p)
        elif "serum" in t and "serum" in name:
            hits.append(p)
        elif "sunscreen" in t and "sunscreen" in name:
            hits.append(p)
        elif "mist" in t and ("mist" in name or "water" in name):
            hits.append(p)
        elif "nkbt" in t and "nkbt" in name:
            hits.append(p)
    return hits


def product_price_list() -> str:
    # Short, human-friendly price list
    lines = []
    for key in [
        "nk_age_reverse_cleanser_100ml",
        "nk_age_reverse_serum_30ml",
        "nk_age_reverse_sunscreen_30ml",
        "nk_energy_water_mist_100ml",
        "nk_travel_set",
        "nk_premium_box",
        "nkbt_face_cleanser_100ml",
        "nkbt_creeme_gel_50g",
        "nkbt_sun_essence_20g",
    ]:
        p = PRODUCTS.get(key)
        if not p:
            continue
        lines.append(f"• {p['name']} — {p['currency']}{p['price']:.2f}")
    return "\n".join(lines)


# -------------------------
# SYSTEM PROMPT (Human + Sales Psychology Mode)
# -------------------------
SYSTEM_PROMPT = """
You are NK Age-Reverse's friendly human-like sales assistant on chat.
Goal: help customer choose suitable products, answer questions, and guide them to order.
Style:
- Sound like a real Malaysian human (casual, warm, helpful), use light emojis (1–3) naturally.
- NEVER spam links. Only share ordering links when user asks for price/order OR they show strong interest.
- Keep replies short, clear, and conversational (2–6 lines). Ask 1 simple question at a time.
- Be honest: if you don't know, say you’ll check and offer the official info.
Sales psychology:
- Mirror their concern, reassure, give 1–2 tailored options, and a soft CTA.
- If user asks "harga" -> give price + simple order steps + ask for area/state for shipping if needed.
- If user asks ingredients/bee venom -> answer based on provided product database. If mismatch/uncertain -> say "Based on official product page/label..."
Safety:
- Do not give medical diagnosis. Suggest patch test for sensitive skin and stop if irritation.
"""

def build_context(user_id: str, user_text: str) -> List[Dict[str, str]]:
    sess = get_session(user_id)
    intents = detect_intents(user_text)
    bump_lead_score(sess, intents)

    # Build extra knowledge snippet
    kb = []
    kb.append("PRICE LIST:\n" + product_price_list())
    kb.append("ORDER LINKS:\n" + f"Website: {ORDER_LINKS['website_home']}\nWhatsApp HQ: {ORDER_LINKS['whatsapp_hq']}")

    # Ingredient answering assist
    if intents["ask_ingredients"]:
        hits = find_product_by_keyword(user_text)
        if hits:
            ingr_lines = []
            for p in hits[:2]:
                if p.get("active_ingredients"):
                    ingr_lines.append(f"{p['name']} active ingredients: {', '.join(p['active_ingredients'])}")
            if ingr_lines:
                kb.append("INGREDIENT NOTES:\n" + "\n".join(ingr_lines))

    # Decide whether to include link instruction
    send_link = should_send_link(sess, intents) and link_cooldown_ok(sess)
    sess["send_link_now"] = bool(send_link)
    if send_link:
        sess["last_link_ts"] = now_ts()

    # Store last user text
    sess["turns"].append({"role": "user", "content": user_text})
    sess["turns"] = sess["turns"][-10:]  # keep last 10

    messages = [{"role": "system", "content": SYSTEM_PROMPT.strip()}]
    messages.append({"role": "system", "content": "\n\n".join(kb)})

    # Add small instruction about link if not allowed now
    if not send_link:
        messages.append({"role": "system", "content": "Do NOT include any URL in your reply for this turn."})
    else:
        messages.append({"role": "system", "content": "You MAY include at most 1 ordering link (prefer WhatsApp HQ) if it helps."})

    # Conversation history
    for t in sess["turns"]:
        messages.append(t)

    return messages


def groq_reply(user_id: str, user_text: str) -> str:
    messages = build_context(user_id, user_text)

    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.6,
        max_tokens=250,
        top_p=0.9,
    )
    text = resp.choices[0].message.content.strip()

    # Hard rule: if send_link_now is False, remove any accidental URLs
    sess = get_session(user_id)
    if not sess.get("send_link_now", False):
        text = re.sub(r"https?://\S+", "", text).strip()

    # Keep it tidy
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


# -------------------------
# API: simple chat test
# -------------------------
@app.post("/chat")
def chat():
    data = request.get_json(force=True, silent=True) or {}
    user_id = str(data.get("user_id", "demo_user"))
    text = str(data.get("text", "")).strip()
    if not text:
        return jsonify({"error": "text is required"}), 400

    reply = groq_reply(user_id, text)
    return jsonify({"reply": reply, "user_id": user_id})


# -------------------------
# Meta Webhook (Optional)
# You still need to implement send message via Graph API with PAGE_ACCESS_TOKEN.
# Here we provide webhook receive + verify only.
# -------------------------
@app.get("/webhook")
def webhook_verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge or "", 200
    return "Verification failed", 403


@app.post("/webhook")
def webhook_receive():
    # This receives Meta events. You must add Graph API call to send response.
    payload = request.get_json(force=True, silent=True) or {}
    # For now just acknowledge.
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
