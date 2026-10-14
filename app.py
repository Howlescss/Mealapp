import streamlit as st
import pandas as pd
from PIL import Image
import streamlit.components.v1 as components
import requests
import io
import os
import re
import json
import base64
from datetime import datetime

# ==========================================
# IMPORTURI OPȚIONALE (COMPATIBIL PYTHON 3.12 - 3.14)
# ==========================================
try:
    from google import genai
    HAS_GENAI_SDK = True
except ImportError:
    genai = None
    HAS_GENAI_SDK = False

try:
    from streamlit_option_menu import option_menu
    HAS_OPTION_MENU = True
except ImportError:
    HAS_OPTION_MENU = False

try:
    import plotly.express as px
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

st.set_page_config(
    page_title="Asistent Nutriție Pro",
    page_icon="🥗",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# ==========================================
# BAZĂ DE DATE LOCALĂ PERMANENTĂ (JSON)
# ==========================================
DB_FILE = "nutritie_db.json"

def load_local_db():
    default_db = {
        "preturi_magazine": {},
        "catalog_nutritie": {},
        "retetar_favorite": [],
        "profil_utilizator": {},
        "custom_api_key": ""
    }
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k in default_db:
                    if k not in data:
                        data[k] = default_db[k]
                return data
        except Exception:
            return default_db
    return default_db

def save_local_db(db_data):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ==========================================
# GESTIONARE CHEI API & MULTI-SERVER AI ENGINE
# ==========================================
def get_api_keys():
    keys = []
    if "db" in st.session_state and st.session_state.db.get("custom_api_key"):
        k_custom = str(st.session_state.db["custom_api_key"]).strip().strip('"').strip("'")
        if k_custom:
            keys.append(k_custom)
    try:
        for k_name in ["GEMINI_API_KEY", "VERTEX_API_KEY", "GOOGLE_API_KEY"]:
            if k_name in st.secrets:
                val = str(st.secrets[k_name]).strip().strip('"').strip("'")
                if val and val not in keys:
                    keys.append(val)
    except Exception:
        pass
    env_k = os.environ.get("GEMINI_API_KEY", "").strip().strip('"').strip("'")
    if env_k and env_k not in keys:
        keys.append(env_k)
    return keys

class SimpleAIResponse:
    def __init__(self, text):
        self.text = text

def extract_text_from_candidates(data):
    candidates = data.get("candidates", [])
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        text_out = "".join(p.get("text", "") for p in parts)
        if text_out:
            return text_out
    return None

def build_gemini_parts(contents):
    parts = []
    if not isinstance(contents, list):
        contents = [contents]
    for item in contents:
        if isinstance(item, str):
            parts.append({"text": item})
        elif isinstance(item, Image.Image):
            buf = io.BytesIO()
            img_rgb = item.convert("RGB") if item.mode not in ("RGB", "L") else item
            img_rgb.save(buf, format="JPEG", quality=85)
            b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")
            parts.append({"inlineData": {"mimeType": "image/jpeg", "data": b64_data}})
        elif isinstance(item, dict) and "data" in item and "mime_type" in item:
            b64_data = base64.b64encode(item["data"]).decode("utf-8")
            parts.append({"inlineData": {"mimeType": item["mime_type"], "data": b64_data}})
    return parts

def call_google_multi_endpoint(api_key, model_name, contents, expect_json=False):
    parts = build_gemini_parts(contents)
    payload_std = {"contents": [{"parts": parts}]}
    payload_vtx = {"contents": [{"role": "user", "parts": parts}]}
    if expect_json:
        payload_std["generationConfig"] = {"responseMimeType": "application/json"}
        payload_vtx["generationConfig"] = {"responseMimeType": "application/json"}

    # Dacă cheia începe cu AQ., prioritizăm Vertex AI Express
    if api_key.startswith("AQ."):
        endpoints = [
            (f"https://aiplatform.googleapis.com/v1/publishers/google/models/{model_name}:generateContent", payload_vtx),
            (f"https://aiplatform.googleapis.com/v1beta1/publishers/google/models/{model_name}:generateContent", payload_vtx),
            (f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent", payload_std),
        ]
    else:
        endpoints = [
            (f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent", payload_std),
            (f"https://aiplatform.googleapis.com/v1/publishers/google/models/{model_name}:generateContent", payload_vtx),
            (f"https://generativelanguage.googleapis.com/v1/models/{model_name}:generateContent", payload_std),
        ]

    last_err = ""
    for url, p_load in endpoints:
        try:
            resp = requests.post(
                url,
                params={"key": api_key},
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                json=p_load,
                timeout=60
            )
            if resp.status_code == 200:
                txt = extract_text_from_candidates(resp.json())
                if txt:
                    return SimpleAIResponse(txt), None
            else:
                last_err = f"HTTP {resp.status_code}"
        except Exception as e:
            last_err = str(e)
    return None, last_err

def call_free_cloud_relay(contents, expect_json=False):
    """Releu AI gratuit (fără cheie Google) folosit automat dacă cheia Google are restricție 403/401."""
    user_content = []
    if not isinstance(contents, list):
        contents = [contents]
    for item in contents:
        if isinstance(item, str):
            user_content.append({"type": "text", "text": item})
        elif isinstance(item, Image.Image):
            buf = io.BytesIO()
            img_rgb = item.convert("RGB") if item.mode not in ("RGB", "L") else item
            img_rgb.save(buf, format="JPEG", quality=80)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    sys_msg = "Ești un nutriționist român expert. Răspunde DOAR în format JSON valid fără blocuri markdown." if expect_json else "Ești un asistent culinar român."
    payload = {
        "model": "openai",
        "messages": [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_content if len(user_content) > 1 else (user_content[0]["text"] if user_content else "")}
        ],
        "temperature": 0.4
    }
    if expect_json:
        payload["response_format"] = {"type": "json_object"}

    for url in ["https://text.pollinations.ai/openai", "https://api.pollinations.ai/v1/chat/completions"]:
        try:
            r = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=75)
            if r.status_code == 200:
                data = r.json()
                choices = data.get("choices", [])
                if choices:
                    txt = choices[0].get("message", {}).get("content", "")
                    if txt:
                        return SimpleAIResponse(txt), "Cloud-AI-Relay"
                elif isinstance(data, dict) and ("lista_cumparaturi" in data or "retete" in data):
                    return SimpleAIResponse(json.dumps(data, ensure_ascii=False)), "Cloud-AI-Relay"
        except Exception:
            continue
    return None, "Releu indisponibil"

def build_smart_fallback_plan():
    """Generator matematic local de siguranță dacă toate serverele externe sunt blocate."""
    zile = st.session_state.zile
    pers = st.session_state.persoane
    batch = st.session_state.batch_cooking
    mag = st.session_state.magazine_selectate[0] if st.session_state.magazine_selectate else "Lidl"
    kcal_t = st.session_state.kcal_tinta
    p_t = st.session_state.prot_tinta
    c_t = st.session_state.carb_tinta
    g_t = st.session_state.gras_tinta
    mult = (zile * pers) if batch else pers

    # Scalare matematică pe ținta utilizatorului
    f_md, f_pr, f_ci = 0.28, 0.42, 0.30
    lista_cump = [
        {"produs": "Piept de pui dezosat", "magazin": mag, "categorie": "Carne & Pește", "cantitate_necesara": f"{int(220*zile*pers)}g", "ambalaj_raft": "Caserolă 1kg", "pret_raft_ron": round(28.90 * max(1, (220*zile*pers)/1000), 2), "kcal_100g": 110},
        {"produs": "Ouă proaspete M", "magazin": mag, "categorie": "Lactate & Ouă", "cantitate_necesara": f"{3*zile*pers} buc", "ambalaj_raft": "Cofraj 10 buc", "pret_raft_ron": round(11.50 * max(1, (3*zile*pers)/10), 2), "kcal_100g": 143},
        {"produs": "Brânză Cottage Light", "magazin": mag, "categorie": "Lactate & Ouă", "cantitate_necesara": f"{int(150*zile*pers)}g", "ambalaj_raft": "Cutie 200g", "pret_raft_ron": round(5.49 * max(1, (150*zile*pers)/200), 2), "kcal_100g": 92},
        {"produs": "Orez Basmati", "magazin": mag, "categorie": "Băcănie", "cantitate_necesara": f"{int(90*zile*pers)}g", "ambalaj_raft": "Pungă 1kg", "pret_raft_ron": 9.90, "kcal_100g": 350},
        {"produs": "File de somon / păstrăv", "magazin": mag, "categorie": "Carne & Pește", "cantitate_necesara": f"{int(180*zile*pers)}g", "ambalaj_raft": "Caserolă 400g", "pret_raft_ron": round(24.90 * max(1, (180*zile*pers)/400), 2), "kcal_100g": 185},
        {"produs": "Cartofi dulci", "magazin": mag, "categorie": "Legume & Fructe", "cantitate_necesara": f"{int(200*zile*pers)}g", "ambalaj_raft": "1 kg", "pret_raft_ron": 8.99, "kcal_100g": 86},
        {"produs": "Mix salată & roșii cherry", "magazin": mag, "categorie": "Legume & Fructe", "cantitate_necesara": f"{int(150*zile*pers)}g", "ambalaj_raft": "Pungă + Caserolă", "pret_raft_ron": 12.50, "kcal_100g": 25},
        {"produs": "Fulgi de ovăz & Fructe de pădure", "magazin": mag, "categorie": "Băcănie", "cantitate_necesara": f"{int(70*zile*pers)}g", "ambalaj_raft": "Pachet 500g", "pret_raft_ron": 11.40, "kcal_100g": 370}
    ]

    retete = []
    perioade = [f"Pentru {zile} zile (Batch)"] if batch else [f"Ziua {i}" for i in range(1, zile + 1)]
    for idx_p, per in enumerate(perioade):
        retete.extend([
            {
                "perioada": per,
                "tip_masa": "Mic dejun",
                "nume": "Omletă proteică cu Cottage Cheese și ovăz" if idx_p % 2 == 0 else "Terci proteic cu fructe și ouă fierte",
                "timp_preparare": "12 min",
                "numar_portii": mult,
                "cost_total_reteta_ron": round(9.50 * mult, 2),
                "cost_per_portie_ron": 9.50,
                "macro_per_portie": {"kcal": int(kcal_t * f_md), "proteine_g": int(p_t * f_md), "carbo_g": int(c_t * f_md), "grasimi_g": int(g_t * f_md)},
                "aparate": ["Aragaz (Plită)"],
                "ingrediente": [
                    {"produs": "Ouă proaspete M", "cantitate": f"{3*mult} buc", "gramaj_g": 165*mult, "magazin": mag, "pret_estimat_ron": round(3.60*mult, 2), "kcal_100g": 143, "prot_100g": 12.6, "carb_100g": 0.7, "gras_100g": 9.5},
                    {"produs": "Brânză Cottage Light", "cantitate": f"{120*mult}g", "gramaj_g": 120*mult, "magazin": mag, "pret_estimat_ron": round(3.30*mult, 2), "kcal_100g": 92, "prot_100g": 13.0, "carb_100g": 3.2, "gras_100g": 3.0},
                    {"produs": "Fulgi de ovăz & Fructe de pădure", "cantitate": f"{50*mult}g", "gramaj_g": 50*mult, "magazin": mag, "pret_estimat_ron": round(2.60*mult, 2), "kcal_100g": 370, "prot_100g": 13.0, "carb_100g": 60.0, "gras_100g": 7.0}
                ],
                "pasi_preparare": [
                    "Bate ouăle cu un praf de sare și gătește-le în tigaia antiaderentă timp de 4 minute.",
                    "Servește alături de brânza Cottage rece și porția de ovăz hidratat cu fructe."
                ],
                "sfat_depozitare": "Se păstrează în caserolă închisă ermetic la frigider până la 3 zile."
            },
            {
                "perioada": per,
                "tip_masa": "Prânz",
                "nume": "Piept de pui rumenit cu orez Basmati și salată proaspătă",
                "timp_preparare": "25 min",
                "numar_portii": mult,
                "cost_total_reteta_ron": round(14.80 * mult, 2),
                "cost_per_portie_ron": 14.80,
                "macro_per_portie": {"kcal": int(kcal_t * f_pr), "proteine_g": int(p_t * f_pr), "carbo_g": int(c_t * f_pr), "grasimi_g": int(g_t * f_pr)},
                "aparate": st.session_state.echipamente[:2] if st.session_state.echipamente else ["Aragaz (Plită)"],
                "ingrediente": [
                    {"produs": "Piept de pui dezosat", "cantitate": f"{220*mult}g", "gramaj_g": 220*mult, "magazin": mag, "pret_estimat_ron": round(8.90*mult, 2), "kcal_100g": 110, "prot_100g": 23.1, "carb_100g": 0.0, "gras_100g": 1.5},
                    {"produs": "Orez Basmati", "cantitate": f"{85*mult}g", "gramaj_g": 85*mult, "magazin": mag, "pret_estimat_ron": round(2.90*mult, 2), "kcal_100g": 350, "prot_100g": 7.5, "carb_100g": 77.0, "gras_100g": 0.9},
                    {"produs": "Mix salată & roșii cherry", "cantitate": f"{120*mult}g", "gramaj_g": 120*mult, "magazin": mag, "pret_estimat_ron": round(3.00*mult, 2), "kcal_100g": 25, "prot_100g": 1.2, "carb_100g": 4.0, "gras_100g": 0.3}
                ],
                "pasi_preparare": [
                    "Condimentează pieptul de pui cu boia, usturoi granulat, sare și piper, apoi gătește-l la Air Fryer sau tigaie 14-16 minute.",
                    "Fierbe orezul Basmati în apă cu sare timp de 12 minute și adaugă salata proaspătă lângă."
                ],
                "sfat_depozitare": "Împarte în caserole individuale; reîncălzește 2 minute înainte de servire."
            },
            {
                "perioada": per,
                "tip_masa": "Cină",
                "nume": "File de păstrăv/somon la cuptor cu cartofi dulci copți",
                "timp_preparare": "25 min",
                "numar_portii": mult,
                "cost_total_reteta_ron": round(16.20 * mult, 2),
                "cost_per_portie_ron": 16.20,
                "macro_per_portie": {"kcal": int(kcal_t * f_ci), "proteine_g": int(p_t * f_ci), "carbo_g": int(c_t * f_ci), "grasimi_g": int(g_t * f_ci)},
                "aparate": ["Cuptor"],
                "ingrediente": [
                    {"produs": "File de somon / păstrăv", "cantitate": f"{180*mult}g", "gramaj_g": 180*mult, "magazin": mag, "pret_estimat_ron": round(12.20*mult, 2), "kcal_100g": 185, "prot_100g": 20.5, "carb_100g": 0.0, "gras_100g": 11.0},
                    {"produs": "Cartofi dulci", "cantitate": f"{200*mult}g", "gramaj_g": 200*mult, "magazin": mag, "pret_estimat_ron": round(4.00*mult, 2), "kcal_100g": 86, "prot_100g": 1.6, "carb_100g": 20.1, "gras_100g": 0.1}
                ],
                "pasi_preparare": [
                    "Taie cartofii dulci cuburi și coace-i la 200°C sau Air Fryer timp de 18 minute.",
                    "Așază fileul de pește cu zeamă de lămâie și ierburi aromatice în ultimele 12 minute."
                ],
                "sfat_depozitare": "Consumă în maximum 48h de la gătire."
            }
        ])
    return json.dumps({"lista_cumparaturi": lista_cump, "retete": retete}, ensure_ascii=False)

def generate_with_ai(contents, expect_json=False, is_meal_plan=False):
    candidate_models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    api_keys = get_api_keys()
    errors = []

    # 1 & 2: Încearcă toate cheile pe Google AI Studio + Vertex AI Express
    for key in api_keys:
        for model_name in candidate_models:
            res, err = call_google_multi_endpoint(key, model_name, contents, expect_json=expect_json)
            if res and res.text:
                st.session_state.last_used_model = f"{model_name} (Google API)"
                return res, None
            if err:
                errors.append(f"{model_name}: {err}")

    # 3: Fallback automat pe Releul AI Cloud Gratuit (dacă cheia Google dă 403/401)
    res_relay, model_relay = call_free_cloud_relay(contents, expect_json=expect_json)
    if res_relay and res_relay.text:
        st.session_state.last_used_model = model_relay
        return res_relay, None

    # 4: Fallback Matematic Local pentru Planul Alimentar
    if is_meal_plan:
        st.session_state.last_used_model = "Smart-Local-Engine"
        return SimpleAIResponse(build_smart_fallback_plan()), None

    return None, " | ".join(errors[:2]) if errors else "Verifică conexiunea sau cheia API din ⚙️ Setări."

def parse_ai_json(raw_text):
    txt = raw_text.strip()
    txt = re.sub(r"^```json\s*", "", txt)
    txt = re.sub(r"^```\s*", "", txt)
    txt = re.sub(r"\s*```$", "", txt).strip()
    start = txt.find("{")
    end = txt.rfind("}")
    if start != -1 and end != -1 and end > start:
        txt = txt[start:end+1]
    return json.loads(txt)

# ==========================================
# LOGO-URI MAGAZINE (SVG INTEGRAT)
# ==========================================
STORE_SVGS = {
    "Lidl": '<svg xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" width="70" height="28" viewBox="0 0 140 56"><rect width="140" height="56" rx="10" fill="#0050AA"/><circle cx="70" cy="28" r="22" fill="#FFF000" stroke="#E60A14" stroke-width="3"/><text x="70" y="34" font-family="Arial,sans-serif" font-size="18" font-weight="900" fill="#0050AA" text-anchor="middle">LIDL</text></svg>',
    "Kaufland": '<svg xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" width="95" height="28" viewBox="0 0 190 56"><rect width="190" height="56" rx="10" fill="#FFFFFF" stroke="#E10915" stroke-width="4"/><rect x="10" y="10" width="36" height="36" rx="4" fill="#E10915"/><text x="28" y="36" font-family="Arial,sans-serif" font-size="24" font-weight="900" fill="#FFFFFF" text-anchor="middle">K</text><text x="118" y="35" font-family="Arial,sans-serif" font-size="20" font-weight="800" fill="#E10915" text-anchor="middle">Kaufland</text></svg>',
    "Carrefour": '<svg xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" width="95" height="28" viewBox="0 0 190 56"><rect width="190" height="56" rx="10" fill="#004E9E"/><circle cx="28" cy="28" r="14" fill="#E3001B"/><text x="112" y="35" font-family="Arial,sans-serif" font-size="20" font-weight="800" fill="#FFFFFF" text-anchor="middle">Carrefour</text></svg>',
    "Mega Image": '<svg xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" width="105" height="28" viewBox="0 0 210 56"><rect width="210" height="56" rx="10" fill="#8B1D41"/><text x="105" y="35" font-family="Arial,sans-serif" font-size="19" font-weight="800" fill="#FFFFFF" text-anchor="middle">MEGA IMAGE</text></svg>',
    "Auchan": '<svg xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" width="85" height="28" viewBox="0 0 170 56"><rect width="170" height="56" rx="10" fill="#E0001A"/><circle cx="28" cy="28" r="13" fill="#009640" stroke="#FFFFFF" stroke-width="2"/><text x="104" y="35" font-family="Arial,sans-serif" font-size="21" font-weight="800" fill="#FFFFFF" text-anchor="middle">Auchan</text></svg>',
    "Penny": '<svg xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" width="80" height="28" viewBox="0 0 160 56"><rect width="160" height="56" rx="10" fill="#CD1719"/><text x="80" y="36" font-family="Arial,sans-serif" font-size="22" font-weight="900" fill="#FFCC00" text-anchor="middle">PENNY.</text></svg>',
    "LaDoiPasi": '<svg xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" width="95" height="28" viewBox="0 0 190 56"><rect width="190" height="56" rx="10" fill="#F37021"/><text x="95" y="35" font-family="Arial,sans-serif" font-size="20" font-weight="900" fill="#FFFFFF" text-anchor="middle">LaDoiPași</text></svg>'
}

def get_store_logo_b64(magazin):
    svg_str = STORE_SVGS.get(
        magazin,
        f'<svg xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" width="80" height="28" viewBox="0 0 160 56"><rect width="160" height="56" rx="10" fill="#1C2541" stroke="#09CEE6" stroke-width="2"/><text x="80" y="35" font-family="Arial" font-size="18" font-weight="bold" fill="#09CEE6" text-anchor="middle">{magazin}</text></svg>'
    )
    b64_svg = base64.b64encode(svg_str.encode("utf-8")).decode("utf-8")
    return f"data:image/svg+xml;base64,{b64_svg}"

def render_store_logos_html(magazine_list, height_px=26):
    if not magazine_list:
        return ""
    return "".join([f'<img src="{get_store_logo_b64(m)}" style="height:{height_px}px; border-radius:6px; margin-right:6px; vertical-align:middle;" title="{m}">' for m in magazine_list])

# ==========================================
# DATE OPȚIUNI & MOTOR AUTO-SYNC PROFIL
# ==========================================
lista_echipamente = ['Aragaz (Plită)', 'Cuptor', 'Air Fryer', 'Cuptor microunde', 'Slow Cooker', 'Multicooker', 'Friteuză', 'Grătar', 'Blender', 'Toaster']
lista_alergeni = ['Lactoză', 'Gluten', 'Avocado', 'Fasole', 'Ciuperci', 'Spanac', 'Soia', 'Nuci', 'Ouă', 'Arahide', 'Crustacee', 'Zahăr adăugat']
lista_medicale = ['Bogat în fibre', 'Pentru Diabetici (Low-GI)', 'Potrivit pentru SOP (Hormon balancing)', 'Antiinflamator']
magazine_disponibile = ["Lidl", "Kaufland", "Auchan", "Carrefour", "Mega Image", "Penny", "LaDoiPasi"]
zile_saptamana = ["Luni", "Marți", "Miercuri", "Joi", "Vineri", "Sâmbătă", "Duminică"]
opts_gatire = ["Simplu și rapid <30 min", "Complex / Gătit avans", "Meal prep (Caserole)", "Cheat Meal / Comfort Food (Burgeri, Pizza, etc.)"]
activ_opts = ["Sedentar (activitate foarte redusă)", "Activitate redusă (1-2 antrenamente)", "Activ (3-4 antrenamente)", "Foarte activ (5-6 antrenamente)"]
obj_opts = ["Menținere greutate", "Slăbire (Deficit caloric)", "Creștere masă musculară (Surplus)"]
ritm_opts = ["Nu mă grăbesc (-10%)", "Lent (-15%)", "Normal (-20%)", "Rapid (-25%)", "Urgent (-30%)"]
distributie_opts = [
    "Echilibrat (25% Proteine, 45% Carbo, 30% Grăsimi)",
    "Menținere masă musculară (2g P/kg corp, 1g G/kg, restul C)",
    "Ketogenic (70% Grăsimi, 20% Proteine, 10% Carbohidrați)"
]

def calculate_biometric_targets():
    sex = st.session_state.sex
    varsta = st.session_state.varsta
    inaltime = st.session_state.inaltime
    greutate = st.session_state.greutate
    activitate = st.session_state.activitate
    obiectiv = st.session_state.obiectiv
    ritm = st.session_state.ritm_slabire
    distributie = st.session_state.distributie_macro
    bf = st.session_state.bf_proc
    stagnare = st.session_state.stagnare_cals

    bmi = greutate / ((inaltime / 100.0) ** 2) if inaltime > 0 else 0.0
    bmr = (10.0 * greutate) + (6.25 * inaltime) - (5.0 * varsta) + (5.0 if sex == "Masculin" else -161.0)
    mult_map = {
        "Sedentar (activitate foarte redusă)": 1.2,
        "Activitate redusă (1-2 antrenamente)": 1.375,
        "Activ (3-4 antrenamente)": 1.55,
        "Foarte activ (5-6 antrenamente)": 1.725
    }
    tdee = bmr * mult_map.get(activitate, 1.375)

    if "Slăbire" in obiectiv:
        def_map = {"Nu mă grăbesc (-10%)": 0.10, "Lent (-15%)": 0.15, "Normal (-20%)": 0.20, "Rapid (-25%)": 0.25, "Urgent (-30%)": 0.30}
        tdee_calc = tdee * (1.0 - def_map.get(ritm, 0.20))
    elif "Creștere masă" in obiectiv:
        tdee_calc = tdee + 400.0
    else:
        tdee_calc = tdee

    tdee_vizual = max(1000.0, tdee_calc - stagnare)

    if "Menținere masă" in distributie:
        prot_calc = (tdee_vizual * 0.40) / 4.0 if ((sex == "Masculin" and bf > 20) or (sex == "Feminin" and bf > 30)) else greutate * 2.2
        gras_calc = greutate * 1.0
        carb_calc = max(0.0, (tdee_vizual - (prot_calc * 4.0) - (gras_calc * 9.0)) / 4.0)
    elif "Ketogenic" in distributie:
        prot_calc, carb_calc, gras_calc = (tdee_vizual * 0.20) / 4.0, (tdee_vizual * 0.10) / 4.0, (tdee_vizual * 0.70) / 9.0
    else:
        prot_calc, carb_calc, gras_calc = (tdee_vizual * 0.25) / 4.0, (tdee_vizual * 0.45) / 4.0, (tdee_vizual * 0.30) / 9.0

    return {"bmi": bmi, "bmr": int(round(bmr)), "kcal": int(round(tdee_vizual)), "prot": int(round(prot_calc)), "carb": int(round(carb_calc)), "gras": int(round(gras_calc))}

def save_profile_to_db():
    if "db" in st.session_state:
        st.session_state.db["profil_utilizator"] = {
            k: st.session_state[k] for k in [
                "sex", "varsta", "inaltime", "greutate", "activitate", "obiectiv",
                "ritm_slabire", "distributie_macro", "bf_proc", "prot_tinta",
                "carb_tinta", "gras_tinta", "kcal_tinta", "stagnare_cals"
            ]
        }
        save_local_db(st.session_state.db)

def recalc_from_biometrics():
    for k in ['sex', 'varsta', 'inaltime', 'greutate', 'activitate', 'obiectiv', 'ritm_slabire', 'distributie_macro', 'bf_proc']:
        if f"ui_{k}" in st.session_state:
            st.session_state[k] = st.session_state[f"ui_{k}"]
    res = calculate_biometric_targets()
    st.session_state.prot_tinta, st.session_state.carb_tinta, st.session_state.gras_tinta, st.session_state.kcal_tinta = res["prot"], res["carb"], res["gras"], res["kcal"]
    st.session_state.ui_prot_tinta, st.session_state.ui_carb_tinta, st.session_state.ui_gras_tinta = res["prot"], res["carb"], res["gras"]
    save_profile_to_db()

def sync_manual_macros():
    for k in ['prot_tinta', 'carb_tinta', 'gras_tinta']:
        if f"ui_{k}" in st.session_state:
            st.session_state[k] = int(st.session_state[f"ui_{k}"])
    st.session_state.kcal_tinta = st.session_state.prot_tinta * 4 + st.session_state.carb_tinta * 4 + st.session_state.gras_tinta * 9
    save_profile_to_db()

# ==========================================
# STATE MANAGEMENT INIȚIAL
# ==========================================
if 'init_done' not in st.session_state:
    db_loaded = load_local_db()
    saved_prof = db_loaded.get("profil_utilizator", {})
    st.session_state.update({
        'db': db_loaded,
        'mod_simplificat': False,
        'last_used_model': 'Multi-Engine Ready',
        'sex': saved_prof.get('sex', "Masculin"),
        'varsta': int(saved_prof.get('varsta', 24)),
        'inaltime': int(saved_prof.get('inaltime', 175)),
        'greutate': float(saved_prof.get('greutate', 77.0)),
        'activitate': saved_prof.get('activitate', "Activitate redusă (1-2 antrenamente)"),
        'obiectiv': saved_prof.get('obiectiv', "Slăbire (Deficit caloric)"),
        'ritm_slabire': saved_prof.get('ritm_slabire', "Normal (-20%)"),
        'distributie_macro': saved_prof.get('distributie_macro', "Echilibrat (25% Proteine, 45% Carbo, 30% Grăsimi)"),
        'bf_proc': int(saved_prof.get('bf_proc', 20)),
        'stagnare_cals': int(saved_prof.get('stagnare_cals', 0)),
        'prot_tinta': int(saved_prof.get('prot_tinta', 120)),
        'carb_tinta': int(saved_prof.get('carb_tinta', 216)),
        'gras_tinta': int(saved_prof.get('gras_tinta', 64)),
        'kcal_tinta': int(saved_prof.get('kcal_tinta', 1923)),
        'zile': 3, 'persoane': 1, 'buget_min': 90, 'buget_max': 240,
        'magazine_selectate': ["Lidl"], 'zi_cumparaturi': "Sâmbătă",
        'echipamente': ['Aragaz (Plită)', 'Cuptor'],
        'alergeni': [], 'alte_restrictii': "", 'preferinte_medicale': [],
        'tip_reteta': "Simplu și rapid <30 min", 'batch_cooking': False, 'camara': "",
        'tip_oferta': "Estimare prețuri actuale + Baza ta de bonuri", 'fisiere_poze': None,
        'config_mese': {}, 'plan_df': None, 'plan_retete': [],
        'retetar_favorite': db_loaded.get("retetar_favorite", []),
        'include_favorites': [], 'mese_de_pastrat': [],
        'water_ml': 0, 'init_done': True
    })
    if not saved_prof:
        recalc_from_biometrics()

def sync(key): st.session_state[key] = st.session_state[f"ui_{key}"]
def init_ui(key):
    st.session_state[f"ui_{key}"] = st.session_state[key]
    return f"ui_{key}"

def sync_budget_from_inputs():
    st.session_state.buget_min = int(st.session_state.ui_buget_min)
    st.session_state.buget_max = max(int(st.session_state.ui_buget_min) + 10, int(st.session_state.ui_buget_max))
    st.session_state.ui_buget_slider = (st.session_state.buget_min, st.session_state.buget_max)

def sync_budget_from_slider():
    b_min, b_max = st.session_state.ui_buget_slider
    st.session_state.buget_min, st.session_state.buget_max = int(b_min), int(b_max)
    st.session_state.ui_buget_min, st.session_state.ui_buget_max = int(b_min), int(b_max)

def on_scale_change():
    st.session_state.zile = st.session_state.ui_zile
    st.session_state.persoane = st.session_state.ui_persoane
    st.session_state.buget_min = 30 * st.session_state.zile * st.session_state.persoane
    st.session_state.buget_max = 80 * st.session_state.zile * st.session_state.persoane
    st.session_state.ui_buget_min, st.session_state.ui_buget_max = st.session_state.buget_min, st.session_state.buget_max
    st.session_state.ui_buget_slider = (st.session_state.buget_min, st.session_state.buget_max)

def add_water(): st.session_state.water_ml = min(2500, st.session_state.water_ml + 250)
def sub_water(): st.session_state.water_ml = max(0, st.session_state.water_ml - 250)
def cut_tdee():
    st.session_state.stagnare_cals += 150
    recalc_from_biometrics()

# ==========================================
# RECALCULARE ACTIVĂ MACRONUTRIENȚI & CARDURI
# ==========================================
def extract_grams_from_text(cant_str):
    if not cant_str: return 100.0
    s = str(cant_str).lower().replace(",", ".")
    kg_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:kg|l)\b", s)
    if kg_m: return float(kg_m.group(1)) * 1000.0
    g_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:g|gr|ml)\b", s)
    if g_m: return float(g_m.group(1))
    b_m = re.search(r"(\d+(?:\.\d+)?)", s)
    if b_m:
        v = float(b_m.group(1))
        return v * 55.0 if v <= 12 else v
    return 100.0

def recalculate_active_recipes_macros(produs_tinta, kcal_100, prot_100, carb_100, gras_100):
    updated_count = 0
    prod_norm = produs_tinta.strip().lower()
    if st.session_state.plan_df is not None and "Produs" in st.session_state.plan_df.columns:
        for idx, row in st.session_state.plan_df.iterrows():
            p_row = str(row["Produs"]).strip().lower()
            if prod_norm in p_row or p_row in prod_norm:
                st.session_state.plan_df.at[idx, "Kcal / 100g"] = int(round(kcal_100))

    for reteta in st.session_state.plan_retete:
        ingrediente = reteta.get("ingrediente", [])
        portii = max(1, int(reteta.get("numar_portii", 1)))
        mod = False
        for ing in ingrediente:
            ing_name = str(ing.get("produs", "")).strip().lower()
            if prod_norm in ing_name or ing_name in prod_norm:
                gramaj = float(ing.get("gramaj_g") or extract_grams_from_text(ing.get("cantitate", "100g")))
                ing["gramaj_g"] = gramaj
                old_k, old_p, old_c, old_g = float(ing.get("kcal_100g", kcal_100)), float(ing.get("prot_100g", prot_100)), float(ing.get("carb_100g", carb_100)), float(ing.get("gras_100g", gras_100))
                ing["kcal_100g"], ing["prot_100g"], ing["carb_100g"], ing["gras_100g"] = float(kcal_100), float(prot_100), float(carb_100), float(gras_100)
                ing["eticheta_verificata"] = True
                mod = True
                f_p = (gramaj / 100.0) / portii
                mc = reteta.get("macro_per_portie", {"kcal": 0, "proteine_g": 0, "carbo_g": 0, "grasimi_g": 0})
                mc["kcal"] = max(0, int(round(mc.get("kcal", 0) + (kcal_100 - old_k) * f_p)))
                mc["proteine_g"] = max(0, int(round(mc.get("proteine_g", 0) + (prot_100 - old_p) * f_p)))
                mc["carbo_g"] = max(0, int(round(mc.get("carbo_g", 0) + (carb_100 - old_c) * f_p)))
                mc["grasimi_g"] = max(0, int(round(mc.get("grasimi_g", 0) + (gras_100 - old_g) * f_p)))
                reteta["macro_per_portie"] = mc
        if mod:
            updated_count += 1
    return updated_count

def get_ics_content():
    ics = "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//NutritieApp//RO\n"
    for idx, r in enumerate(st.session_state.plan_retete):
        ics += f"BEGIN:VEVENT\nSUMMARY:{r.get('perioada', 'Zi')} - {r.get('nume', 'Rețetă')}\nDESCRIPTION:{' | '.join(r.get('pasi_preparare', []))}\nDTSTART;VALUE=DATE:2026101{idx+1}\nEND:VEVENT\n"
    return ics + "END:VCALENDAR"

def render_recipe_card(reteta, index=None, allow_actions=True):
    perioada = reteta.get("perioada", "Plan")
    tip_masa = reteta.get("tip_masa", "Masă")
    nume = reteta.get("nume", "Preparat")
    timp = reteta.get("timp_preparare", "25 min")
    cost_total = float(reteta.get("cost_total_reteta_ron", 0.0))
    cost_portie = float(reteta.get("cost_per_portie_ron", 0.0))
    portii = reteta.get("numar_portii", 1)
    macro = reteta.get("macro_per_portie", {})
    aparate = reteta.get("aparate", [])
    ingrediente = reteta.get("ingrediente", [])
    pasi = reteta.get("pasi_preparare", [])
    sfat_depozitare = reteta.get("sfat_depozitare", "")

    with st.container(border=True):
        st.markdown(
            f'<div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:10px; margin-bottom:10px;">'
            f'<div><span style="background:rgba(9,206,230,0.15); color:#09CEE6; padding:5px 12px; border-radius:8px; font-size:12px; font-weight:700; border:1px solid rgba(9,206,230,0.4); margin-right:6px;">📅 {perioada}</span>'
            f'<span style="background:rgba(255,255,255,0.08); color:#E2E8F0; padding:5px 12px; border-radius:8px; font-size:12px; font-weight:600; margin-right:6px;">🍽️ {tip_masa}</span>'
            f'<span style="background:rgba(255,255,255,0.08); color:#A0AEC0; padding:5px 12px; border-radius:8px; font-size:12px;">⏱️ {timp}</span></div>'
            f'<div><span style="background:rgba(56,161,105,0.2); color:#68D391; padding:6px 14px; border-radius:10px; font-size:14px; font-weight:800; border:1px solid #38A169;">💰 {cost_total:.2f} RON <span style="font-size:11px; color:#CBD5E0;">({cost_portie:.2f} RON/porție)</span></span></div></div>'
            f'<h3 style="margin-top:4px; margin-bottom:12px; color:#FFFFFF; font-size:20px;">{nume}</h3>'
            f'<div style="display:flex; gap:8px; flex-wrap:wrap; background:#0B132B; padding:10px 14px; border-radius:12px; border:1px solid #2D3748; margin-bottom:14px; justify-content:space-between;">'
            f'<span style="font-size:12px; color:#A0AEC0; font-weight:600;">📊 Valori / porție ({portii} porții):</span>'
            f'<div style="display:flex; gap:14px; flex-wrap:wrap;">'
            f'<span style="color:#F6AD55; font-weight:800; font-size:13px;">🔥 {macro.get("kcal", 0)} kcal</span>'
            f'<span style="color:#FC8181; font-weight:700; font-size:13px;">🥩 {macro.get("proteine_g", 0)}g P</span>'
            f'<span style="color:#68D391; font-weight:700; font-size:13px;">🌾 {macro.get("carbo_g", 0)}g C</span>'
            f'<span style="color:#F6E05E; font-weight:700; font-size:13px;">🥑 {macro.get("grasimi_g", 0)}g G</span></div></div>',
            unsafe_allow_html=True
        )

        col_ing, col_prep = st.columns([1.1, 1.3], gap="medium")
        with col_ing:
            st.markdown("**🛒 Ingrediente & Prețuri Magazin**")
            ing_rows = []
            for ing in ingrediente:
                logo_src = get_store_logo_b64(ing.get("magazin", "Lidl"))
                ver = " 🏷️" if ing.get("eticheta_verificata") else ""
                ing_rows.append(
                    f'<div style="display:flex; justify-content:space-between; align-items:center; padding:6px 0; border-bottom:1px dashed #1C2541; font-size:13px;">'
                    f'<div style="display:flex; align-items:center; gap:4px;"><img src="{logo_src}" style="height:15px; border-radius:3px;">'
                    f'<span style="color:#E2E8F0; font-weight:600;">{ing.get("produs", "")}{ver}</span>'
                    f'<span style="color:#09CEE6; font-size:12px;">({ing.get("cantitate", "")})</span></div>'
                    f'<div style="color:#68D391; font-weight:700;">{float(ing.get("pret_estimat_ron", 0.0)):.2f} lei</div></div>'
                )
            st.markdown(f'<div style="background:#0B132B; padding:12px; border-radius:12px; border:1px solid #2D3748;">{"".join(ing_rows)}</div>', unsafe_allow_html=True)
            if aparate:
                st.markdown("<div style='margin-top:6px;'>" + " ".join([f"<span style='background:#0B132B; border:1px solid #3A506B; padding:3px 8px; border-radius:6px; font-size:11px;'>🍳 {a}</span>" for a in aparate]) + "</div>", unsafe_allow_html=True)

        with col_prep:
            st.markdown("**👨‍🍳 Mod de Preparare**")
            step_rows = [
                f'<div style="display:flex; gap:10px; margin-bottom:8px; font-size:13px;"><span style="background:#09CEE6; color:#0B132B; font-weight:800; min-width:20px; height:20px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-size:11px;">{idx_p}</span><span style="color:#E2E8F0;">{re.sub(r"^\\d+[\\.\\)]\\s*", "", str(pas))}</span></div>'
                for idx_p, pas in enumerate(pasi, 1)
            ]
            st.markdown(f'<div style="background:#0B132B; padding:12px; border-radius:12px; border:1px solid #2D3748;">{"".join(step_rows)}</div>', unsafe_allow_html=True)
            if sfat_depozitare:
                st.markdown(f'<div style="margin-top:8px; background:rgba(246,224,94,0.1); border-left:3px solid #ECC94B; padding:7px 10px; border-radius:6px; font-size:12px; color:#FEFCBF;">🥡 <b>Depozitare:</b> {sfat_depozitare}</div>', unsafe_allow_html=True)

        if allow_actions and index is not None:
            c_b1, c_b2 = st.columns(2)
            with c_b1:
                if st.button("🖤 Salvează în Rețetar", type="primary", key=f"fav_{index}", use_container_width=True):
                    if nume not in [x.get('nume') for x in st.session_state.retetar_favorite]:
                        st.session_state.retetar_favorite.append(reteta)
                        st.session_state.db["retetar_favorite"] = st.session_state.retetar_favorite
                        save_local_db(st.session_state.db)
                        st.toast("Rețetă salvată în Rețetar!", icon="✅")
            with c_b2:
                return st.checkbox("🔒 Păstrează la regenerare", key=f"lock_{index}")
    return False

# ==========================================
# CSS PREMIUM
# ==========================================
bg_color, card_bg, text_color, border_col = "#0B132B", "#1C2541", "#E2E8F0", "#3A506B"
st.markdown(f"""
<style>
    #MainMenu {{visibility: hidden;}} footer {{visibility: hidden;}}
    .stApp {{ background-color: {bg_color} !important; }}
    h1, h2, h3, h4, h5, h6, p, label, span, .stMarkdown, .stText, .stCheckbox label, .stRadio label {{ color: {text_color} !important; font-family: 'Inter', sans-serif; }}
    .block-container {{ padding-top: 2.8rem !important; padding-bottom: 3rem !important; max-width: 860px !important; margin: auto; }}
    [data-testid="stVerticalBlockBorderWrapper"] {{ background: linear-gradient(180deg, #1C2541 0%, #161E35 100%) !important; border-radius: 20px !important; border: 1px solid {border_col} !important; padding: 1.2rem !important; margin-bottom: 1rem !important; }}
    button[kind="primary"] {{ background: linear-gradient(135deg, #38A169 0%, #2F855A 100%) !important; color: white !important; border-radius: 14px !important; font-weight: 700 !important; border: none !important; }}
    button[kind="secondary"] {{ border-radius: 14px !important; font-weight: 700 !important; border: 1px solid #3A506B !important; }}
    .stTextInput>div>div>input, .stNumberInput>div>div>input, .stSelectbox>div>div>div, .stMultiSelect>div>div>div, .stTextArea>div>div>textarea {{ background-color: {bg_color} !important; color: {text_color} !important; border-radius: 12px !important; border: 1px solid {border_col} !important; }}
    span[data-baseweb="tag"] {{ background-color: #09CEE6 !important; color: #0B132B !important; font-weight: 700 !important; border-radius: 10px !important; }}
    button[key="gear_settings_btn"] {{ background-color: transparent !important; border: none !important; font-size: 26px !important; padding: 0 !important; }}
    div[data-testid="stTabs"] button[role="tab"] {{ background-color: {bg_color} !important; border-radius: 12px !important; padding: 8px 14px !important; border: 1px solid {border_col} !important; font-weight: 600 !important; }}
    div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {{ background-color: #09CEE6 !important; color: #0B132B !important; font-weight: 800 !important; }}
</style>
""", unsafe_allow_html=True)

# ==========================================
# POP-UP SETĂRI (CU CONFIGURARE CHEIE LIVE)
# ==========================================
@st.dialog("⚙️ Setările Aplicației & Cheie API")
def settings_modal():
    st.checkbox("Mod Simplificat (Ascunde setările avansate din Dietă & Mese)", value=st.session_state.mod_simplificat, key=init_ui('mod_simplificat'), on_change=sync, args=('mod_simplificat',))
    st.write("---")
    st.markdown("#### 🔑 Configurare Rapidă Cheie API (Opțional)")
    st.caption("Dacă cheia din Streamlit Secrets are restricții 403 în Google Cloud, poți lipi aici fie cheia `AQ...` (Vertex AI), fie o cheie nouă `AIzaSy...` fără restricții:")
    new_k = st.text_input("Cheie API (AIzaSy... sau AQ...):", value=st.session_state.db.get("custom_api_key", ""), type="password")
    if st.button("💾 Salvează Cheia în Aplicație", type="primary", use_container_width=True):
        st.session_state.db["custom_api_key"] = new_k.strip()
        save_local_db(st.session_state.db)
        st.success("Cheia a fost salvată! Aplicația folosește acum Multi-Server + Releu AI automat.")
    st.write("---")
    st.caption(f"🤖 Ultimul motor AI folosit: **`{st.session_state.last_used_model}`**")

# ==========================================
# HEADER & NAVBAR
# ==========================================
st.markdown(
    '<div style="text-align:center; padding: 4px 0;">'
    '<div style="display:inline-block; background:rgba(9,206,230,0.12); border:1px solid rgba(9,206,230,0.35); border-radius:20px; padding:3px 12px; font-size:11px; color:#09CEE6; font-weight:700;">SMART NUTRITION & PRICE ENGINE</div>'
    '<h2 style="margin:2px 0; font-size:25px; font-weight:800; color:#FFFFFF;">🥗 Asistent Nutriție Pro</h2>'
    '<p style="color:#A0AEC0; font-size:13px; margin:0;">Mese delicioase, buget optimizat pe magazine & învățare din bonuri fiscale</p></div>',
    unsafe_allow_html=True
)

col_menu, col_set = st.columns([9.1, 0.9], vertical_alignment="center")
with col_menu:
    if HAS_OPTION_MENU:
        selected_tab = option_menu(
            menu_title=None,
            options=["Planificator", "Cumpărături", "Dietă & Mese", "Profil", "Rețetar"],
            icons=["calendar2-week", "cart", "sliders", "person", "book"],
            orientation="horizontal",
            key="main_menu_nav",
            styles={
                "container": {"padding": "5px", "background-color": card_bg, "border-radius": "30px", "border": f"1px solid {border_col}", "display": "flex", "flex-wrap": "nowrap", "overflow-x": "auto"},
                "icon": {"color": "inherit", "font-size": "13px"},
                "nav-link": {"font-size": "11px", "margin": "0px 2px", "color": text_color, "font-weight": "700", "border-radius": "18px", "border": "1px solid rgba(9,206,230,0.35)", "white-space": "nowrap"},
                "nav-link-selected": {"background-color": "#09CEE6", "color": "#0B132B", "font-weight": "800"},
            }
        )
    else:
        selected_tab = st.radio("Navigare", ["Planificator", "Cumpărături", "Dietă & Mese", "Profil", "Rețetar"], horizontal=True, label_visibility="collapsed")

with col_set:
    if st.button("⚙️", key="gear_settings_btn", use_container_width=True):
        settings_modal()

# ==========================================
# TAB 1: PLANIFICATOR
# ==========================================
if selected_tab == "Planificator":
    kcal_zi_tinta = st.session_state.kcal_tinta
    logos_bar = render_store_logos_html(st.session_state.magazine_selectate, height_px=26)
    nr_preturi_db = sum(len(v) for v in st.session_state.db.get("preturi_magazine", {}).values())
    nr_nutri_db = len(st.session_state.db.get("catalog_nutritie", {}))

    with st.container(border=True):
        st.markdown(
            f'<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(165px, 1fr)); gap:10px; margin-bottom:10px;">'
            f'<div style="background:#0B132B; padding:12px; border-radius:14px; border:1px solid #2D3748;"><div style="font-size:11px; color:#A0AEC0;">👨‍👩‍👧 CONFIGURAȚIE PLAN</div><div style="font-size:17px; font-weight:800; color:#FFF; margin-top:4px;">{st.session_state.persoane} Pers. • {st.session_state.zile} Zile</div><div style="font-size:11px; color:#09CEE6;">{"🍲 Mod Batch Cooking" if st.session_state.batch_cooking else "📅 Meniu Zilnic"}</div></div>'
            f'<div style="background:#0B132B; padding:12px; border-radius:14px; border:1px solid #2D3748;"><div style="font-size:11px; color:#A0AEC0;">🎯 ȚINTĂ ZILNICĂ / PERS.</div><div style="font-size:18px; font-weight:800; color:#F6AD55; margin-top:4px;">🔥 {kcal_zi_tinta} kcal</div><div style="font-size:11.5px; font-weight:700;"><span style="color:#FC8181;">{st.session_state.prot_tinta}g P</span> • <span style="color:#68D391;">{st.session_state.carb_tinta}g C</span> • <span style="color:#F6E05E;">{st.session_state.gras_tinta}g G</span></div></div>'
            f'<div style="background:#0B132B; padding:12px; border-radius:14px; border:1px solid #2D3748;"><div style="font-size:11px; color:#A0AEC0;">💰 BUGET & MAGAZINE</div><div style="font-size:17px; font-weight:800; color:#68D391; margin-top:4px;">{st.session_state.buget_min} - {st.session_state.buget_max} RON</div><div style="margin-top:6px;">{logos_bar}</div></div></div>'
            f'<div style="display:flex; justify-content:space-between; flex-wrap:wrap; font-size:11.5px; color:#A0AEC0; background:rgba(9,206,230,0.07); padding:7px 12px; border-radius:10px;">'
            f'<span>👤 <b>Profil Activ:</b> {st.session_state.varsta} ani, {st.session_state.inaltime} cm, {st.session_state.greutate:.1f} kg ({st.session_state.obiectiv})</span>'
            f'<span style="color:#09CEE6;">📦 {nr_preturi_db} prețuri & {nr_nutri_db} etichete ✓</span></div>',
            unsafe_allow_html=True
        )
        with st.expander("✏️ Ajustează Rapid Bugetul sau Magazinele"):
            cb1, cb2 = st.columns(2)
            with cb1: st.number_input("Buget Minim (RON)", min_value=0, step=10, key=init_ui('buget_min'), on_change=sync_budget_from_inputs)
            with cb2: st.number_input("Buget Maxim (RON)", min_value=0, step=10, key=init_ui('buget_max'), on_change=sync_budget_from_inputs)
            st.multiselect("Magazine active:", magazine_disponibile, key=init_ui('magazine_selectate'), on_change=sync, args=('magazine_selectate',))

    if st.button("🔥 GENEREAZĂ PLANUL ȘI CALCULEAZĂ PREȚURILE", type="primary", use_container_width=True):
        with st.spinner(f"Se creează meniul optimizat pentru {kcal_zi_tinta} kcal/zi și se calculează prețurile..."):
            mag = ", ".join(st.session_state.magazine_selectate) if st.session_state.magazine_selectate else "Lidl"
            echip = ", ".join(st.session_state.echipamente)
            alg = ", ".join(st.session_state.alergeni) + " " + st.session_state.alte_restrictii

            preturi_salvate_txt = ""
            for m_sel in st.session_state.magazine_selectate:
                for prod_k, info_p in st.session_state.db.get("preturi_magazine", {}).get(m_sel, {}).items():
                    preturi_salvate_txt += f"- {m_sel}: {prod_k} = {info_p.get('pret')} RON\n"

            if st.session_state.batch_cooking:
                instructiune_mod = f'MOD BATCH COOKING: Generează câte o rețetă pentru Mic dejun, Prânz, Cină cu perioada="Pentru {st.session_state.zile} zile (Batch)" și numar_portii={st.session_state.zile * st.session_state.persoane}.'
            else:
                instructiune_mod = f'MOD ZILNIC: Generează Mic dejun, Prânz și Cină pentru fiecare din cele {st.session_state.zile} zile (Ziua 1..Ziua {st.session_state.zile}).'

            prompt = f"""
            Ești un nutriționist și expert în prețurile din România ({mag}). Răspunde STRICT în format JSON valid, în română.
            Persoane: {st.session_state.persoane} | Zile: {st.session_state.zile} | Buget: {st.session_state.buget_min}-{st.session_state.buget_max} RON.
            Țintă/persoană/zi: {kcal_zi_tinta} kcal ({st.session_state.prot_tinta}g P, {st.session_state.carb_tinta}g C, {st.session_state.gras_tinta}g G).
            Aparate: {echip} | Stil: {st.session_state.tip_reteta} | Restricții: {alg if alg.strip() else 'Fără'}.
            Prețuri din bonuri: {preturi_salvate_txt if preturi_salvate_txt else 'Folosește prețurile reale din România 2026.'}
            {instructiune_mod}
            Schema JSON obligatorie:
            {{
              "lista_cumparaturi": [{{"produs": "Piept de pui", "magazin": "{st.session_state.magazine_selectate[0] if st.session_state.magazine_selectate else 'Lidl'}", "categorie": "Carne & Pește", "cantitate_necesara": "700g", "ambalaj_raft": "Caserolă 1kg", "pret_raft_ron": 28.90, "kcal_100g": 110}}],
              "retete": [{{"perioada": "Ziua 1", "tip_masa": "Prânz", "nume": "Pui cu orez basmati", "timp_preparare": "25 min", "numar_portii": {st.session_state.persoane}, "cost_total_reteta_ron": 14.50, "cost_per_portie_ron": 14.50, "macro_per_portie": {{"kcal": 620, "proteine_g": 52, "carbo_g": 68, "grasimi_g": 12}}, "aparate": ["Aragaz (Plită)"], "ingrediente": [{{"produs": "Piept de pui", "cantitate": "220g", "gramaj_g": 220, "magazin": "Lidl", "pret_estimat_ron": 8.50, "kcal_100g": 110, "prot_100g": 23.0, "carb_100g": 0.0, "gras_100g": 1.5}}], "pasi_preparare": ["Pasul 1", "Pasul 2"], "sfat_depozitare": "La frigider 3 zile."}}]
            }}
            """
            rezultat_ai, _ = generate_with_ai([prompt], expect_json=True, is_meal_plan=True)
            try:
                data_parsed = parse_ai_json(rezultat_ai.text)
            except Exception:
                data_parsed = json.loads(build_smart_fallback_plan())

            lista_cump = data_parsed.get("lista_cumparaturi", [])
            retete_list = data_parsed.get("retete", [])
            if lista_cump:
                df = pd.DataFrame(lista_cump)
                df.rename(columns={"produs": "Produs", "magazin": "Magazin", "categorie": "Categorie", "cantitate_necesara": "Cantitate Rețete", "ambalaj_raft": "Ambalaj Raft", "pret_raft_ron": "Preț Raft (RON)", "kcal_100g": "Kcal / 100g"}, inplace=True)
                if 'Cumpărat' not in df.columns:
                    df.insert(0, 'Cumpărat', False)
                st.session_state.plan_df = df
            if retete_list:
                st.session_state.plan_retete = retete_list

    if st.session_state.plan_df is not None and st.session_state.plan_retete:
        st.write("---")
        df_cump = st.session_state.plan_df
        col_pret = "Preț Raft (RON)" if "Preț Raft (RON)" in df_cump.columns else None
        total_raft = pd.to_numeric(df_cump[col_pret], errors='coerce').sum() if col_pret else 0.0
        total_retete = sum(float(r.get("cost_total_reteta_ron", 0)) for r in st.session_state.plan_retete)
        cost_zi_pers = total_retete / max(1, (st.session_state.zile * st.session_state.persoane))

        st.subheader("📊 Sumar Financiar & Cumpărături")
        with st.container(border=True):
            m1, m2, m3 = st.columns(3)
            m1.metric("🛒 Total Coș la Raft", f"{total_raft:.2f} RON", f"Buget: {st.session_state.buget_min}-{st.session_state.buget_max} RON")
            m2.metric("🍲 Cost Efectiv Porții", f"{total_retete:.2f} RON", "Ingrediente folosite")
            m3.metric("👤 Cost / Zi / Persoană", f"{cost_zi_pers:.2f} RON", f"{', '.join(st.session_state.magazine_selectate)}")
            with st.expander("🧾 Vezi Tabelul Complet cu Prețurile pe Produs", expanded=False):
                st.dataframe(df_cump.drop(columns=['Cumpărat'], errors='ignore'), use_container_width=True, hide_index=True)

        text_desc = f"🛒 LISTA DE CUMPĂRĂTURI (Total Raft: {total_raft:.2f} RON)\n" + df_cump.to_string(index=False)
        col_dl1, col_dl2 = st.columns(2)
        with col_dl1: st.download_button("💾 Descarcă Planul & Prețurile (.txt)", data=text_desc, file_name="Plan_Nutritie.txt", mime="text/plain", use_container_width=True)
        with col_dl2: st.download_button("📅 Exportă în Calendar (.ics)", data=get_ics_content(), file_name="Mese.ics", mime="text/calendar", use_container_width=True)

        st.subheader("🍽️ Planul Tău Alimentar")
        for i, reteta in enumerate(st.session_state.plan_retete):
            render_recipe_card(reteta, index=i, allow_actions=True)

    st.write("---")
    st.subheader("🧊 Frigiderul Magic (Snap & Cook)")
    with st.container(border=True):
        cu_ce_gatesc = st.text_input("Scrie ingredientele pe care le ai în frigider (ex: ouă, brânză, roșii, tortilla):", key="frigider_text")
        if st.button("✨ Găsește-mi o rețetă rapidă", use_container_width=True):
            if cu_ce_gatesc:
                with st.spinner("Se creează rețeta..."):
                    res_snap, _ = generate_with_ai([f"Creează o rețetă rapidă în limba română cu: {cu_ce_gatesc}, incluzând calorii și mod de preparare."], expect_json=False)
                    if res_snap:
                        st.markdown(res_snap.text)
                    else:
                        st.info(f"**Tigaie rapidă cu {cu_ce_gatesc}**: Rumenește ingredientele 8-10 minute în tigaia antiaderentă cu condimente și servește cald (~450 kcal / porție).")

# ==========================================
# TAB 2: CUMPĂRĂTURI
# ==========================================
elif selected_tab == "Cumpărături":
    st.subheader("🛒 Setări Magazin & Cămară")
    with st.container(border=True):
        col_c1, col_c2 = st.columns([1, 1.4])
        with col_c1: st.selectbox("Ziua de cumpărături:", zile_saptamana, key=init_ui('zi_cumparaturi'), on_change=sync, args=('zi_cumparaturi',))
        with col_c2: st.multiselect("Selectează magazinele:", magazine_disponibile, key=init_ui('magazine_selectate'), on_change=sync, args=('magazine_selectate',))
        st.markdown(f'<div style="margin:6px 0 12px 0;">{render_store_logos_html(st.session_state.magazine_selectate, height_px=28)}</div>', unsafe_allow_html=True)
        st.text_area("🥫 Cămara Virtuală (Produse deja acasă):", key=init_ui('camara'), on_change=sync, args=('camara',), height=68)

    st.subheader(f"📋 Lista de Cumpărături ({st.session_state.zi_cumparaturi})")
    if st.session_state.plan_df is not None and not st.session_state.plan_df.empty:
        with st.container(border=True):
            df_edit = st.data_editor(st.session_state.plan_df, column_config={"Cumpărat": st.column_config.CheckboxColumn("În coș", default=False)}, hide_index=True, use_container_width=True)
            st.session_state.plan_df = df_edit
            if "Preț Raft (RON)" in df_edit.columns:
                total_cump = pd.to_numeric(df_edit["Preț Raft (RON)"], errors='coerce').sum()
                ramas = pd.to_numeric(df_edit[~df_edit["Cumpărat"]]["Preț Raft (RON)"], errors='coerce').sum()
                c_tot1, c_tot2 = st.columns(2)
                c_tot1.metric("💰 Total Estimativ la Raft", f"{total_cump:.2f} RON")
                c_tot2.metric("🛒 Rămas de pus în coș", f"{ramas:.2f} RON")
    else:
        st.info("Generează mai întâi un plan în tab-ul 'Planificator'.")

    st.write("---")
    st.subheader("🏷️ Verifică & Actualizează Macronutrienții la Raft")
    with st.container(border=True):
        produse_lista = st.session_state.plan_df["Produs"].tolist() if (st.session_state.plan_df is not None and "Produs" in st.session_state.plan_df.columns) else []
        prod_sel = st.selectbox("Alege produsul:", produse_lista + ["Alt produs (scrie manual)..."])
        prod_final = st.text_input("Nume produs:") if prod_sel == "Alt produs (scrie manual)..." else prod_sel
        poza_et = st.file_uploader("📸 Încarcă poza cu tabelul nutrițional (per 100g):", type=["png", "jpg", "jpeg"])
        if st.button("⚡ Extrage Eticheta & Recalculează Rețetele", type="primary", use_container_width=True) and prod_final and poza_et:
            res_lbl, _ = generate_with_ai(['Extrage valorile nutriționale per 100g în JSON: {"kcal_100g": 115, "prot_100g": 9.0, "carb_100g": 3.8, "gras_100g": 5.0}', Image.open(poza_et)], expect_json=True)
            if res_lbl:
                try:
                    v = parse_ai_json(res_lbl.text)
                    k1, p1, c1, g1 = float(v.get("kcal_100g", 0)), float(v.get("prot_100g", 0)), float(v.get("carb_100g", 0)), float(v.get("gras_100g", 0))
                    st.session_state.db["catalog_nutritie"][prod_final.lower()] = {"nume_afisat": prod_final, "kcal_100g": k1, "prot_100g": p1, "carb_100g": c1, "gras_100g": g1, "data": datetime.now().strftime("%Y-%m-%d")}
                    save_local_db(st.session_state.db)
                    nr_m = recalculate_active_recipes_macros(prod_final, k1, p1, c1, g1)
                    st.success(f"✅ Etichetă salvată pentru **{prod_final}**! S-au recalculat {nr_m} rețete.")
                except Exception as e:
                    st.error(f"Eroare citire etichetă: {e}")

    st.write("---")
    st.subheader("🧾 Scanează Bonul Fiscal")
    with st.container(border=True):
        mag_bon = st.selectbox("Magazin bon:", magazine_disponibile)
        poza_bon = st.file_uploader("📸 Încarcă poza cu bonul fiscal:", type=["png", "jpg", "jpeg"])
        if st.button("💳 Extrage Prețurile de pe Bon", type="primary", use_container_width=True) and poza_bon:
            res_b, _ = generate_with_ai([f'Extrage produsele alimentare de pe bonul {mag_bon} în JSON: {{"produse_bon": [{{"nume_clar": "Produs", "pret_ron": 12.50, "cantitate_sau_ambalaj": "1 buc"}}]}}', Image.open(poza_bon)], expect_json=True)
            if res_b:
                try:
                    lb = parse_ai_json(res_b.text).get("produse_bon", [])
                    st.session_state.db["preturi_magazine"].setdefault(mag_bon, {})
                    for it in lb:
                        np, pr = str(it.get("nume_clar", "")).strip(), float(it.get("pret_ron", 0.0))
                        if np and pr > 0:
                            st.session_state.db["preturi_magazine"][mag_bon][np.lower()] = {"nume_afisat": np, "pret": pr, "ambalaj": str(it.get("cantitate_sau_ambalaj", "1 buc")), "data": datetime.now().strftime("%Y-%m-%d")}
                    save_local_db(st.session_state.db)
                    st.success(f"🎉 S-au salvat {len(lb)} prețuri pentru {mag_bon}!")
                except Exception as e:
                    st.error(f"Eroare procesare bon: {e}")

# ==========================================
# TAB 3: DIETĂ & MESE
# ==========================================
elif selected_tab == "Dietă & Mese":
    st.subheader("👥 Configurare Persoane, Zile & Buget")
    with st.container(border=True):
        c1, c2 = st.columns(2)
        with c1: st.slider("👨‍👩‍👧 Număr persoane:", 1, 10, key=init_ui('persoane'), on_change=on_scale_change)
        with c2: st.slider("📅 Zile planificate:", 1, 7, key=init_ui('zile'), on_change=on_scale_change)
        st.session_state.ui_buget_slider = (int(st.session_state.buget_min), int(st.session_state.buget_max))
        st.slider("💰 Interval Buget Alocat (Min - Max RON):", 20, 2500, step=10, key="ui_buget_slider", on_change=sync_budget_from_slider)

    if not st.session_state.mod_simplificat:
        st.subheader("🏥 Sănătate, Echipamente & Stil Gătire")
        with st.container(border=True):
            col_e1, col_e2 = st.columns(2)
            with col_e1:
                st.multiselect("🍳 Aparate în bucătărie:", lista_echipamente, key=init_ui('echipamente'), on_change=sync, args=('echipamente',))
                st.multiselect("🩺 Preferințe Medicale:", lista_medicale, key=init_ui('preferinte_medicale'), on_change=sync, args=('preferinte_medicale',))
            with col_e2:
                st.multiselect("🚫 Alergeni / Interzise:", lista_alergeni, key=init_ui('alergeni'), on_change=sync, args=('alergeni',))
                st.selectbox("⏱️ Stil de gătire:", opts_gatire, key=init_ui('tip_reteta'), on_change=sync, args=('tip_reteta',))
            st.checkbox("🍲 Activează Mod Batch Cooking (Gătești o singură dată pentru caserole)", key=init_ui('batch_cooking'), on_change=sync, args=('batch_cooking',))

# ==========================================
# TAB 4: PROFIL
# ==========================================
elif selected_tab == "Profil":
    st.subheader("👤 Date Biometrice & Obiectiv (Auto-Sincronizare Activă)")
    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            st.selectbox("Sex", ["Masculin", "Feminin"], key=init_ui('sex'), on_change=recalc_from_biometrics)
            st.number_input("Vârstă (ani)", 14, 100, key=init_ui('varsta'), on_change=recalc_from_biometrics)
            st.number_input("Înălțime (cm)", 120, 250, key=init_ui('inaltime'), on_change=recalc_from_biometrics)
        with col2:
            st.number_input("Greutate actuală (kg)", 40.0, 200.0, step=0.1, key=init_ui('greutate'), on_change=recalc_from_biometrics)
            st.selectbox("Nivel de activitate fizică", activ_opts, key=init_ui('activitate'), on_change=recalc_from_biometrics)
            st.selectbox("Obiectiv nutrițional", obj_opts, key=init_ui('obiectiv'), on_change=recalc_from_biometrics)

    with st.container(border=True):
        c_slab1, c_slab2 = st.columns(2)
        with c_slab1:
            if "Slăbire" in st.session_state.obiectiv:
                st.select_slider("Ritm slăbire:", options=ritm_opts, key=init_ui('ritm_slabire'), on_change=recalc_from_biometrics)
            else:
                st.info("⚖️ Protocol caloric sincronizat automat.")
        with c_slab2:
            st.selectbox("Protocol Macronutrienți:", distributie_opts, key=init_ui('distributie_macro'), on_change=recalc_from_biometrics)

    calc_info = calculate_biometric_targets()
    with st.container(border=True):
        c_m1, c_m2, c_m3 = st.columns(3)
        c_m1.metric("📊 Indice BMI", f"{calc_info['bmi']:.1f}", "Normal" if 18.5 <= calc_info['bmi'] <= 25 else "Atenție")
        c_m2.metric("🔥 Necesar Zilnic", f"{st.session_state.kcal_tinta} kcal", f"BMR: {calc_info['bmr']} kcal")
        with c_m3:
            st.button("⚖️ Am stagnat (-150 Kcal)", on_click=cut_tdee, use_container_width=True)

    with st.container(border=True):
        cw1, cw2, cw3 = st.columns([1, 2, 1])
        with cw1: st.button("➖ 250 ml", on_click=sub_water, use_container_width=True)
        with cw2: st.markdown(f"<h4 style='text-align: center; color: #09CEE6; margin:0;'>💧 {st.session_state.water_ml} ml / 2500 ml</h4>", unsafe_allow_html=True)
        with cw3: st.button("➕ 250 ml", on_click=add_water, use_container_width=True)
        st.progress(min(st.session_state.water_ml / 2500.0, 1.0))

    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1: st.number_input("🥩 Proteine (g)", 0, 500, key=init_ui('prot_tinta'), on_change=sync_manual_macros)
        with c2: st.number_input("🌾 Carbohidrați (g)", 0, 1000, key=init_ui('carb_tinta'), on_change=sync_manual_macros)
        with c3: st.number_input("🥑 Grăsimi (g)", 0, 300, key=init_ui('gras_tinta'), on_change=sync_manual_macros)
        df_macro = pd.DataFrame({
            "Nutrient": ["Proteine", "Carbohidrați", "Grăsimi"],
            "Grame": [st.session_state.prot_tinta, st.session_state.carb_tinta, st.session_state.gras_tinta],
            "Calorii": [st.session_state.prot_tinta * 4, st.session_state.carb_tinta * 4, st.session_state.gras_tinta * 9]
        })
        if HAS_PLOTLY:
            fig = px.pie(df_macro, values='Calorii', names='Nutrient', hole=0.45, color='Nutrient', color_discrete_map={"Proteine": "#FC8181", "Carbohidrați": "#68D391", "Grăsimi": "#F6E05E"})
            fig.update_layout(height=260, margin=dict(t=10, b=10, l=10, r=10), paper_bgcolor='rgba(0,0,0,0)', font=dict(color=text_color))
            st.plotly_chart(fig, use_container_width=True)

# ==========================================
# TAB 5: REȚETAR
# ==========================================
elif selected_tab == "Rețetar":
    sub_fav, sub_etichete, sub_preturi = st.tabs(["📖 Rețete Favorite", "🏷️ Catalog Nutrițional", "💰 Prețuri Bonuri"])
    with sub_fav:
        if not st.session_state.retetar_favorite:
            st.info("Nu ai încă rețete salvate.")
        else:
            for idx, fav in enumerate(st.session_state.retetar_favorite):
                render_recipe_card(fav, index=idx, allow_actions=False)
                if st.button("❌ Șterge din Rețetar", key=f"del_fav_{idx}"):
                    st.session_state.retetar_favorite.pop(idx)
                    st.session_state.db["retetar_favorite"] = st.session_state.retetar_favorite
                    save_local_db(st.session_state.db)
                    st.rerun()
    with sub_etichete:
        cat_n = st.session_state.db.get("catalog_nutritie", {})
        if cat_n:
            st.dataframe(pd.DataFrame([{"Produs": v.get("nume_afisat", k), "Kcal/100g": v.get("kcal_100g", 0), "P (g)": v.get("prot_100g", 0), "C (g)": v.get("carb_100g", 0), "G (g)": v.get("gras_100g", 0)} for k, v in cat_n.items()]), use_container_width=True, hide_index=True)
        else:
            st.caption("Nicio etichetă salvată încă.")
    with sub_preturi:
        rows_p = [{"Magazin": m, "Produs": p.get("nume_afisat", k), "Preț (RON)": p.get("pret", 0.0)} for m, d in st.session_state.db.get("preturi_magazine", {}).items() for k, p in d.items()]
        if rows_p:
            st.dataframe(pd.DataFrame(rows_p), use_container_width=True, hide_index=True)
        else:
            st.caption("Niciun bon fiscal scanat încă.")
