import streamlit as st
from google import genai
import plotly.express as px
import pandas as pd
from PIL import Image
from streamlit_option_menu import option_menu
import streamlit.components.v1 as components
import io
import os
import re
import json
import base64
from datetime import datetime

# ==========================================
# SETĂRI PAGINĂ & CACHING
# ==========================================
st.set_page_config(
    page_title="Asistent Nutriție Pro",
    page_icon="🥗",
    layout="centered",
    initial_sidebar_state="collapsed"
)

@st.cache_resource
def get_ai_client():
    return genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

client = get_ai_client()

# ==========================================
# BAZĂ DE DATE LOCALĂ PERMANENTĂ (JSON)
# ==========================================
DB_FILE = "nutritie_db.json"

def load_local_db():
    default_db = {
        "preturi_magazine": {},
        "catalog_nutritie": {},
        "retetar_favorite": [],
        "profil_utilizator": {}
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
# LOGO-URI MAGAZINE (SVG INTEGRAT + SUPORT FOLDER LOCAL)
# ==========================================
STORE_SVGS = {
    "Lidl": '<svg xmlns="http://www.w3.org/2000/svg" width="70" height="28" viewBox="0 0 140 56"><rect width="140" height="56" rx="10" fill="#0050AA"/><circle cx="70" cy="28" r="22" fill="#FFF000" stroke="#E60A14" stroke-width="3"/><text x="70" y="34" font-family="Arial,sans-serif" font-size="18" font-weight="900" fill="#0050AA" text-anchor="middle">LIDL</text></svg>',
    "Kaufland": '<svg xmlns="http://www.w3.org/2000/svg" width="95" height="28" viewBox="0 0 190 56"><rect width="190" height="56" rx="10" fill="#FFFFFF" stroke="#E10915" stroke-width="4"/><rect x="10" y="10" width="36" height="36" rx="4" fill="#E10915"/><text x="28" y="36" font-family="Arial,sans-serif" font-size="24" font-weight="900" fill="#FFFFFF" text-anchor="middle">K</text><text x="118" y="35" font-family="Arial,sans-serif" font-size="20" font-weight="800" fill="#E10915" text-anchor="middle">Kaufland</text></svg>',
    "Carrefour": '<svg xmlns="http://www.w3.org/2000/svg" width="95" height="28" viewBox="0 0 190 56"><rect width="190" height="56" rx="10" fill="#004E9E"/><circle cx="28" cy="28" r="14" fill="#E3001B"/><text x="112" y="35" font-family="Arial,sans-serif" font-size="20" font-weight="800" fill="#FFFFFF" text-anchor="middle">Carrefour</text></svg>',
    "Mega Image": '<svg xmlns="http://www.w3.org/2000/svg" width="105" height="28" viewBox="0 0 210 56"><rect width="210" height="56" rx="10" fill="#8B1D41"/><text x="105" y="35" font-family="Arial,sans-serif" font-size="19" font-weight="800" fill="#FFFFFF" text-anchor="middle">MEGA IMAGE</text></svg>',
    "Auchan": '<svg xmlns="http://www.w3.org/2000/svg" width="85" height="28" viewBox="0 0 170 56"><rect width="170" height="56" rx="10" fill="#E0001A"/><circle cx="28" cy="28" r="13" fill="#009640" stroke="#FFFFFF" stroke-width="2"/><text x="104" y="35" font-family="Arial,sans-serif" font-size="21" font-weight="800" fill="#FFFFFF" text-anchor="middle">Auchan</text></svg>',
    "Penny": '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="28" viewBox="0 0 160 56"><rect width="160" height="56" rx="10" fill="#CD1719"/><text x="80" y="36" font-family="Arial,sans-serif" font-size="22" font-weight="900" fill="#FFCC00" text-anchor="middle">PENNY.</text></svg>',
    "LaDoiPasi": '<svg xmlns="http://www.w3.org/2000/svg" width="95" height="28" viewBox="0 0 190 56"><rect width="190" height="56" rx="10" fill="#F37021"/><text x="95" y="35" font-family="Arial,sans-serif" font-size="20" font-weight="900" fill="#FFFFFF" text-anchor="middle">LaDoiPași</text></svg>'
}

def get_store_logo_b64(magazin):
    local_dir = "logos"
    for ext in ["png", "jpg", "jpeg", "webp"]:
        local_path = os.path.join(local_dir, f"{magazin}.{ext}")
        if os.path.exists(local_path):
            try:
                with open(local_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                    mime = "image/png" if ext == "png" else "image/jpeg"
                    return f"data:{mime};base64,{b64}"
            except Exception:
                pass

    svg_str = STORE_SVGS.get(
        magazin,
        f'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="28" viewBox="0 0 160 56"><rect width="160" height="56" rx="10" fill="#1C2541" stroke="#09CEE6" stroke-width="2"/><text x="80" y="35" font-family="Arial" font-size="18" font-weight="bold" fill="#09CEE6" text-anchor="middle">{magazin}</text></svg>'
    )
    b64_svg = base64.b64encode(svg_str.encode("utf-8")).decode("utf-8")
    return f"data:image/svg+xml;base64,{b64_svg}"

def render_store_logos_html(magazine_list, height_px=26):
    if not magazine_list:
        return ""
    imgs = []
    for mag in magazine_list:
        src = get_store_logo_b64(mag)
        imgs.append(f'<img src="{src}" style="height:{height_px}px; border-radius:6px; margin-right:6px; vertical-align:middle; box-shadow:0 2px 6px rgba(0,0,0,0.3);" title="{mag}">')
    return "".join(imgs)

# ==========================================
# MOTOR AI DINAMIC (PRIORITIZARE 3.1 -> 3.0 -> 2.5 -> 2.0)
# ==========================================
@st.cache_data(show_spinner=False, ttl=3600)
def get_available_models():
    preferred_order = [
        "gemini-3.1-flash",
        "gemini-3.1-pro",
        "gemini-3.1-flash-lite",
        "gemini-3.0-flash",
        "gemini-3.0-pro",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-2.0-flash-001",
        "gemini-flash-latest"
    ]
    exclude_keywords = [
        "embedding", "imagen", "veo", "tts", "audio",
        "aqa", "robotics", "computer-use", "bisect", "thinking"
    ]
    
    discovered = []
    try:
        for m in client.models.list():
            raw_name = getattr(m, "name", "")
            short_name = raw_name.replace("models/", "")
            actions = getattr(m, "supported_actions", None) or getattr(m, "supported_generation_methods", None)
            if actions and "generateContent" not in actions:
                continue
            if "gemini" in short_name.lower() and not any(k in short_name.lower() for k in exclude_keywords):
                discovered.append(short_name)
    except Exception:
        pass

    if not discovered:
        return ["gemini-2.5-flash", "gemini-2.0-flash"]

    sorted_models = []
    for m in discovered:
        if m.startswith("gemini-3") and m not in sorted_models:
            sorted_models.append(m)
    for m in preferred_order:
        if m in discovered and m not in sorted_models:
            sorted_models.append(m)
    for m in discovered:
        if m not in sorted_models and "flash" in m.lower() and "exp" not in m.lower():
            sorted_models.append(m)
    for m in discovered:
        if m not in sorted_models:
            sorted_models.append(m)
            
    return sorted_models

def generate_with_ai(contents, expect_json=False):
    candidate_models = get_available_models()
    errors = []
    
    for model_name in candidate_models:
        try:
            if expect_json:
                res = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config={"response_mime_type": "application/json"}
                )
            else:
                res = client.models.generate_content(model=model_name, contents=contents)
                
            if res and res.text:
                st.session_state.last_used_model = model_name
                return res, None
        except Exception as e:
            if expect_json:
                try:
                    res = client.models.generate_content(model=model_name, contents=contents)
                    if res and res.text:
                        st.session_state.last_used_model = model_name
                        return res, None
                except Exception as e2:
                    errors.append(f"{model_name}: {str(e2)}")
                    continue
            errors.append(f"{model_name}: {str(e)}")
            continue
            
    return None, "\n".join(errors[:3])

def parse_ai_json(raw_text):
    clean_json = re.sub(r"^```json\s*", "", raw_text.strip())
    clean_json = re.sub(r"^```\s*", "", clean_json)
    clean_json = re.sub(r"\s*```$", "", clean_json).strip()
    return json.loads(clean_json)

# ==========================================
# DATE OPȚIUNI & MULTIPLICATORI
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

# ==========================================
# MOTOR AUTO-SYNC PROFIL -> PLANIFICATOR
# ==========================================
def calculate_biometric_targets():
    """Calculează BMR, Necesarul Kcal și gramele P/C/G exacte din datele profilului."""
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
        def_map = {
            "Nu mă grăbesc (-10%)": 0.10,
            "Lent (-15%)": 0.15,
            "Normal (-20%)": 0.20,
            "Rapid (-25%)": 0.25,
            "Urgent (-30%)": 0.30
        }
        tdee_calc = tdee * (1.0 - def_map.get(ritm, 0.20))
    elif "Creștere masă" in obiectiv:
        tdee_calc = tdee + 400.0
    else:
        tdee_calc = tdee

    tdee_vizual = max(1000.0, tdee_calc - stagnare)

    if "Menținere masă" in distributie:
        if (sex == "Masculin" and bf > 20) or (sex == "Feminin" and bf > 30):
            prot_calc = (tdee_vizual * 0.40) / 4.0
        else:
            prot_calc = greutate * 2.2
        gras_calc = greutate * 1.0
        carb_calc = max(0.0, (tdee_vizual - (prot_calc * 4.0) - (gras_calc * 9.0)) / 4.0)
    elif "Ketogenic" in distributie:
        prot_calc = (tdee_vizual * 0.20) / 4.0
        carb_calc = (tdee_vizual * 0.10) / 4.0
        gras_calc = (tdee_vizual * 0.70) / 9.0
    else:
        # Echilibrat (25% P, 45% C, 30% G)
        prot_calc = (tdee_vizual * 0.25) / 4.0
        carb_calc = (tdee_vizual * 0.45) / 4.0
        gras_calc = (tdee_vizual * 0.30) / 9.0

    return {
        "bmi": bmi,
        "bmr": int(round(bmr)),
        "kcal": int(round(tdee_vizual)),
        "prot": int(round(prot_calc)),
        "carb": int(round(carb_calc)),
        "gras": int(round(gras_calc))
    }

def save_profile_to_db():
    if "db" in st.session_state:
        st.session_state.db["profil_utilizator"] = {
            "sex": st.session_state.sex,
            "varsta": st.session_state.varsta,
            "inaltime": st.session_state.inaltime,
            "greutate": st.session_state.greutate,
            "activitate": st.session_state.activitate,
            "obiectiv": st.session_state.obiectiv,
            "ritm_slabire": st.session_state.ritm_slabire,
            "distributie_macro": st.session_state.distributie_macro,
            "bf_proc": st.session_state.bf_proc,
            "prot_tinta": st.session_state.prot_tinta,
            "carb_tinta": st.session_state.carb_tinta,
            "gras_tinta": st.session_state.gras_tinta,
            "kcal_tinta": st.session_state.kcal_tinta,
            "stagnare_cals": st.session_state.stagnare_cals
        }
        save_local_db(st.session_state.db)

def recalc_from_biometrics():
    """Sincronizează automat orice modificare din Profil direct cu Planificatorul."""
    for k in ['sex', 'varsta', 'inaltime', 'greutate', 'activitate', 'obiectiv', 'ritm_slabire', 'distributie_macro', 'bf_proc']:
        ui_k = f"ui_{k}"
        if ui_k in st.session_state:
            st.session_state[k] = st.session_state[ui_k]

    res = calculate_biometric_targets()
    st.session_state.prot_tinta = res["prot"]
    st.session_state.carb_tinta = res["carb"]
    st.session_state.gras_tinta = res["gras"]
    st.session_state.kcal_tinta = res["kcal"]

    st.session_state.ui_prot_tinta = res["prot"]
    st.session_state.ui_carb_tinta = res["carb"]
    st.session_state.ui_gras_tinta = res["gras"]
    save_profile_to_db()

def sync_manual_macros():
    """Dacă utilizatorul editează manual gramele P/C/G, actualizează automat și Kcal în Planificator."""
    for k in ['prot_tinta', 'carb_tinta', 'gras_tinta']:
        ui_k = f"ui_{k}"
        if ui_k in st.session_state:
            st.session_state[k] = int(st.session_state[ui_k])
    st.session_state.kcal_tinta = (
        st.session_state.prot_tinta * 4 +
        st.session_state.carb_tinta * 4 +
        st.session_state.gras_tinta * 9
    )
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
        'last_used_model': 'Auto-Detect',
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
        'water_ml': 0, 'camera_active': False,
        'init_done': True
    })
    # Dacă nu exista un profil salvat anterior, calculăm valorile inițiale din biometrie
    if not saved_prof:
        recalc_from_biometrics()

def sync(key):
    st.session_state[key] = st.session_state[f"ui_{key}"]

def init_ui(key):
    ui_key = f"ui_{key}"
    st.session_state[ui_key] = st.session_state[key]
    return ui_key

def sync_budget_from_inputs():
    st.session_state.buget_min = int(st.session_state.ui_buget_min)
    st.session_state.buget_max = max(int(st.session_state.ui_buget_min) + 10, int(st.session_state.ui_buget_max))
    st.session_state.ui_buget_slider = (st.session_state.buget_min, st.session_state.buget_max)

def sync_budget_from_slider():
    b_min, b_max = st.session_state.ui_buget_slider
    st.session_state.buget_min = int(b_min)
    st.session_state.buget_max = int(b_max)
    st.session_state.ui_buget_min = int(b_min)
    st.session_state.ui_buget_max = int(b_max)

def on_scale_change():
    st.session_state.zile = st.session_state.ui_zile
    st.session_state.persoane = st.session_state.ui_persoane
    st.session_state.buget_min = 30 * st.session_state.zile * st.session_state.persoane
    st.session_state.buget_max = 80 * st.session_state.zile * st.session_state.persoane
    st.session_state.ui_buget_min = st.session_state.buget_min
    st.session_state.ui_buget_max = st.session_state.buget_max
    st.session_state.ui_buget_slider = (st.session_state.buget_min, st.session_state.buget_max)

def add_water(): st.session_state.water_ml = min(2500, st.session_state.water_ml + 250)
def sub_water(): st.session_state.water_ml = max(0, st.session_state.water_ml - 250)
def cut_tdee():
    st.session_state.stagnare_cals += 150
    recalc_from_biometrics()

# ==========================================
# RECALCULARE ACTIVĂ MACRONUTRIENȚI ÎN REȚETE
# ==========================================
def extract_grams_from_text(cant_str):
    if not cant_str:
        return 100.0
    s = str(cant_str).lower().replace(",", ".")
    kg_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:kg|l)\b", s)
    if kg_match:
        return float(kg_match.group(1)) * 1000.0
    g_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:g|gr|ml)\b", s)
    if g_match:
        return float(g_match.group(1))
    buc_match = re.search(r"(\d+(?:\.\d+)?)", s)
    if buc_match:
        val = float(buc_match.group(1))
        return val * 55.0 if val <= 12 else val
    return 100.0

def recalculate_active_recipes_macros(produs_tinta, kcal_100, prot_100, carb_100, gras_100):
    updated_count = 0
    prod_norm = produs_tinta.strip().lower()

    if st.session_state.plan_df is not None and "Produs" in st.session_state.plan_df.columns:
        df = st.session_state.plan_df
        for idx, row in df.iterrows():
            p_row = str(row["Produs"]).strip().lower()
            if prod_norm in p_row or p_row in prod_norm:
                df.at[idx, "Kcal / 100g"] = int(round(kcal_100))
        st.session_state.plan_df = df

    for reteta in st.session_state.plan_retete:
        ingrediente = reteta.get("ingrediente", [])
        portii = max(1, int(reteta.get("numar_portii", 1)))
        modified_this_recipe = False

        for ing in ingrediente:
            ing_name = str(ing.get("produs", "")).strip().lower()
            if prod_norm in ing_name or ing_name in prod_norm:
                gramaj = float(ing.get("gramaj_g") or extract_grams_from_text(ing.get("cantitate", "100g")))
                ing["gramaj_g"] = gramaj
                
                old_kcal = float(ing.get("kcal_100g", kcal_100))
                old_p = float(ing.get("prot_100g", prot_100))
                old_c = float(ing.get("carb_100g", carb_100))
                old_g = float(ing.get("gras_100g", gras_100))

                ing["kcal_100g"] = float(kcal_100)
                ing["prot_100g"] = float(prot_100)
                ing["carb_100g"] = float(carb_100)
                ing["gras_100g"] = float(gras_100)
                ing["eticheta_verificata"] = True
                modified_this_recipe = True

                factor_portie = (gramaj / 100.0) / portii
                macro_curent = reteta.get("macro_per_portie", {"kcal": 0, "proteine_g": 0, "carbo_g": 0, "grasimi_g": 0})
                macro_curent["kcal"] = max(0, int(round(macro_curent.get("kcal", 0) + (kcal_100 - old_kcal) * factor_portie)))
                macro_curent["proteine_g"] = max(0, int(round(macro_curent.get("proteine_g", 0) + (prot_100 - old_p) * factor_portie)))
                macro_curent["carbo_g"] = max(0, int(round(macro_curent.get("carbo_g", 0) + (carb_100 - old_c) * factor_portie)))
                macro_curent["grasimi_g"] = max(0, int(round(macro_curent.get("grasimi_g", 0) + (gras_100 - old_g) * factor_portie)))
                reteta["macro_per_portie"] = macro_curent

        if modified_this_recipe:
            updated_count += 1
            if all("prot_100g" in i and "gramaj_g" in i for i in ingrediente):
                tot_kcal = sum((float(i["gramaj_g"]) / 100.0) * float(i["kcal_100g"]) for i in ingrediente) / portii
                tot_p = sum((float(i["gramaj_g"]) / 100.0) * float(i["prot_100g"]) for i in ingrediente) / portii
                tot_c = sum((float(i["gramaj_g"]) / 100.0) * float(i["carb_100g"]) for i in ingrediente) / portii
                tot_g = sum((float(i["gramaj_g"]) / 100.0) * float(i["gras_100g"]) for i in ingrediente) / portii
                reteta["macro_per_portie"] = {
                    "kcal": int(round(tot_kcal)),
                    "proteine_g": int(round(tot_p)),
                    "carbo_g": int(round(tot_c)),
                    "grasimi_g": int(round(tot_g))
                }

    return updated_count

def get_ics_content():
    ics = "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//NutritieApp//RO\n"
    for idx, r in enumerate(st.session_state.plan_retete):
        titlu = f"{r.get('perioada', 'Zi')} - {r.get('nume', 'Rețetă')}"
        pasi = " | ".join(r.get('pasi_preparare', []))
        ics += f"BEGIN:VEVENT\nSUMMARY:{titlu}\nDESCRIPTION:{pasi}\nDTSTART;VALUE=DATE:2026101{idx+1}\nEND:VEVENT\n"
    ics += "END:VCALENDAR"
    return ics

# ==========================================
# CARD REȚETĂ PREMIUM
# ==========================================
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
        header_html = (
            f'<div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:10px; margin-bottom:10px;">'
            f'<div>'
            f'<span style="background:linear-gradient(135deg, rgba(9,206,230,0.2), rgba(9,206,230,0.05)); color:#09CEE6; padding:5px 12px; border-radius:8px; font-size:12px; font-weight:700; border:1px solid rgba(9,206,230,0.4); margin-right:6px;">📅 {perioada}</span>'
            f'<span style="background-color:rgba(255,255,255,0.08); color:#E2E8F0; padding:5px 12px; border-radius:8px; font-size:12px; font-weight:600; margin-right:6px;">🍽️ {tip_masa}</span>'
            f'<span style="background-color:rgba(255,255,255,0.08); color:#A0AEC0; padding:5px 12px; border-radius:8px; font-size:12px;">⏱️ {timp}</span>'
            f'</div>'
            f'<div style="text-align:right;">'
            f'<span style="background:linear-gradient(135deg, rgba(56,161,105,0.25), rgba(56,161,105,0.1)); color:#68D391; padding:6px 14px; border-radius:10px; font-size:14px; font-weight:800; border:1px solid #38A169;">'
            f'💰 {cost_total:.2f} RON <span style="font-size:11px; font-weight:500; color:#CBD5E0;">({cost_portie:.2f} RON / porție)</span>'
            f'</span>'
            f'</div>'
            f'</div>'
            f'<h3 style="margin-top:4px; margin-bottom:12px; color:#FFFFFF; font-size:21px; letter-spacing:-0.3px;">{nume}</h3>'
        )
        st.markdown(header_html, unsafe_allow_html=True)

        kcal = macro.get("kcal", 0)
        prot = macro.get("proteine_g", 0)
        carb = macro.get("carbo_g", 0)
        gras = macro.get("grasimi_g", 0)

        macro_html = (
            f'<div style="display:flex; gap:8px; flex-wrap:wrap; background-color:#0B132B; padding:10px 14px; border-radius:12px; border:1px solid #2D3748; margin-bottom:16px; align-items:center; justify-content:space-between;">'
            f'<span style="font-size:12px; color:#A0AEC0; font-weight:600;">📊 Valori / porție (din {portii} porții):</span>'
            f'<div style="display:flex; gap:14px; flex-wrap:wrap;">'
            f'<span style="color:#F6AD55; font-weight:800; font-size:13px;">🔥 {kcal} kcal</span>'
            f'<span style="color:#FC8181; font-weight:700; font-size:13px;">🥩 {prot}g P</span>'
            f'<span style="color:#68D391; font-weight:700; font-size:13px;">🌾 {carb}g C</span>'
            f'<span style="color:#F6E05E; font-weight:700; font-size:13px;">🥑 {gras}g G</span>'
            f'</div>'
            f'</div>'
        )
        st.markdown(macro_html, unsafe_allow_html=True)

        col_ing, col_prep = st.columns([1.1, 1.3], gap="medium")

        with col_ing:
            st.markdown("**🛒 Ingrediente & Prețuri Magazin**")
            ing_rows = []
            for ing in ingrediente:
                item_name = ing.get("produs", "")
                cant = ing.get("cantitate", "")
                mag = ing.get("magazin", "Lidl")
                pret_ing = float(ing.get("pret_estimat_ron", 0.0))
                verificat = " 🏷️" if ing.get("eticheta_verificata") else ""
                logo_src = get_store_logo_b64(mag)
                row = (
                    f'<div style="display:flex; justify-content:space-between; align-items:center; padding:7px 0; border-bottom:1px dashed #1C2541; font-size:13px;">'
                    f'<div style="display:flex; align-items:center; flex-wrap:wrap; gap:4px;">'
                    f'<img src="{logo_src}" style="height:16px; border-radius:3px; margin-right:3px;">'
                    f'<span style="color:#E2E8F0; font-weight:600;">{item_name}{verificat}</span>'
                    f'<span style="color:#09CEE6; font-size:12px;">({cant})</span>'
                    f'</div>'
                    f'<div style="color:#68D391; font-weight:700; white-space:nowrap; margin-left:8px;">{pret_ing:.2f} lei</div>'
                    f'</div>'
                )
                ing_rows.append(row)
                
            ing_html = f'<div style="background-color:#0B132B; padding:12px 14px; border-radius:12px; border:1px solid #2D3748;">{"".join(ing_rows)}</div>'
            st.markdown(ing_html, unsafe_allow_html=True)

            if aparate:
                ap_badges = " ".join([f'<span style="background:#0B132B; border:1px solid #3A506B; padding:4px 8px; border-radius:6px; font-size:11px; display:inline-block; margin-top:4px;">🍳 {a}</span>' for a in aparate])
                st.markdown(f'<div style="margin-top:8px;">{ap_badges}</div>', unsafe_allow_html=True)

        with col_prep:
            st.markdown("**👨‍🍳 Mod de Preparare**")
            step_rows = []
            for idx_p, pas in enumerate(pasi, 1):
                pas_curat = re.sub(r"^\d+[\.\)]\s*", "", str(pas))
                s_row = (
                    f'<div style="display:flex; gap:10px; margin-bottom:9px; font-size:13.5px; line-height:1.45;">'
                    f'<span style="background-color:#09CEE6; color:#0B132B; font-weight:800; min-width:22px; height:22px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-size:11px; margin-top:2px;">{idx_p}</span>'
                    f'<span style="color:#E2E8F0;">{pas_curat}</span>'
                    f'</div>'
                )
                step_rows.append(s_row)
                
            steps_html = f'<div style="background-color:#0B132B; padding:12px 14px; border-radius:12px; border:1px solid #2D3748;">{"".join(step_rows)}</div>'
            st.markdown(steps_html, unsafe_allow_html=True)

            if sfat_depozitare:
                depo_html = (
                    f'<div style="margin-top:8px; background-color:rgba(246,224,94,0.1); border-left:3px solid #ECC94B; padding:8px 12px; border-radius:6px; font-size:12px; color:#FEFCBF;">'
                    f'🥡 <b>Depozitare & Caserole:</b> {sfat_depozitare}'
                    f'</div>'
                )
                st.markdown(depo_html, unsafe_allow_html=True)

        if allow_actions and index is not None:
            st.markdown('<div style="margin-top:10px;"></div>', unsafe_allow_html=True)
            c_b1, c_b2 = st.columns(2)
            with c_b1:
                if st.button("🖤 Salvează în Rețetar", type="primary", key=f"fav_{index}", use_container_width=True):
                    if nume not in [x.get('nume') for x in st.session_state.retetar_favorite]:
                        st.session_state.retetar_favorite.append(reteta)
                        st.session_state.db["retetar_favorite"] = st.session_state.retetar_favorite
                        save_local_db(st.session_state.db)
                        st.toast("Rețetă salvată permanent în Rețetar!", icon="✅")
            with c_b2:
                pastrat = st.checkbox("🔒 Păstrează rețeta la regenerare", key=f"lock_{index}")
                return pastrat
    return False

# ==========================================
# CULORI & CSS PREMIUM (OPTIMIZAT MOBILE & DESKTOP)
# ==========================================
bg_color, card_bg, text_color, border_col = "#0B132B", "#1C2541", "#E2E8F0", "#3A506B"

st.markdown(f"""
<style>
    #MainMenu {{visibility: hidden;}} footer {{visibility: hidden;}}
    .stApp {{ background-color: {bg_color} !important; }}
    h1, h2, h3, h4, h5, h6, p, label, span, .stMarkdown, .stText, .stCheckbox label, .stRadio label {{
        color: {text_color} !important; font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }}
    
    .block-container {{ padding-top: 3.2rem !important; padding-bottom: 3rem !important; max-width: 860px !important; margin: auto; }}
    
    [data-testid="stVerticalBlockBorderWrapper"] {{
        background: linear-gradient(180deg, #1C2541 0%, #161E35 100%) !important;
        border-radius: 20px !important;
        border: 1px solid {border_col} !important;
        padding: 1.25rem !important;
        box-shadow: 0 8px 24px rgba(0,0,0,0.32) !important;
        margin-bottom: 1rem !important;
    }}
    
    button[kind="primary"] {{
        background: linear-gradient(135deg, #38A169 0%, #2F855A 100%) !important;
        color: white !important; border-radius: 14px !important; padding: 12px 18px !important;
        font-size: 15px !important; font-weight: 700 !important; border: none !important;
        box-shadow: 0 4px 12px rgba(56, 161, 105, 0.3) !important;
        transition: all 0.15s ease !important;
    }}
    button[kind="secondary"] {{ border-radius: 14px !important; font-weight: 700 !important; border: 1px solid #3A506B !important; }}

    iframe[title="streamlit_option_menu.option_menu"] {{ background-color: transparent !important; border-radius: 30px !important; overflow: hidden !important; }}
    div[data-testid="stIFrame"] {{ background-color: transparent !important; border-radius: 30px !important; }}
    
    .stTextInput>div>div>input, .stNumberInput>div>div>input, .stSelectbox>div>div>div, .stMultiSelect>div>div>div, .stTextArea>div>div>textarea {{
        background-color: {bg_color} !important; color: {text_color} !important; border-radius: 12px !important; border: 1px solid {border_col} !important;
    }}
    span[data-baseweb="tag"] {{ background-color: #09CEE6 !important; color: #0B132B !important; font-weight: 700 !important; border-radius: 10px !important; }}
    span[data-baseweb="tag"] svg {{ fill: #0B132B !important; }}
    
    button[key="gear_settings_btn"] {{
        background-color: transparent !important; border: none !important; box-shadow: none !important;
        font-size: 28px !important; padding: 0 !important; display: flex !important;
        align-items: center !important; justify-content: center !important; height: 100% !important; margin-top: 4px !important;
    }}
    
    div[data-testid="stTabs"] [data-baseweb="tab-highlight"], div[data-testid="stTabs"] [data-baseweb="tab-border"] {{ display: none !important; }}
    div[data-testid="stTabs"] [role="tablist"] {{ gap: 8px; margin-bottom: 14px !important; overflow-x: auto; padding-bottom: 5px; }}
    div[data-testid="stTabs"] button[role="tab"] {{ background-color: {bg_color} !important; border-radius: 12px !important; padding: 8px 14px !important; border: 1px solid {border_col} !important; font-weight: 600 !important; }}
    div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {{ background-color: #09CEE6 !important; border-color: #09CEE6 !important; color: #0B132B !important; font-weight: 800 !important; }}
    [data-testid="stDataFrame"] {{ border-radius: 14px; overflow: hidden; }}

    @media (max-width: 640px) {{
        .block-container {{ padding-top: 2.2rem !important; padding-left: 0.7rem !important; padding-right: 0.7rem !important; }}
        [data-testid="stVerticalBlockBorderWrapper"] {{ padding: 0.95rem !important; border-radius: 16px !important; }}
    }}
</style>
""", unsafe_allow_html=True)

# ==========================================
# POP-UP SETĂRI
# ==========================================
@st.dialog("⚙️ Setările Aplicației")
def settings_modal():
    st.markdown("#### ⚡ Experiență Utilizator")
    st.checkbox("Mod Simplificat (Ascunde setările avansate din Dietă & Mese)", value=st.session_state.mod_simplificat, key=init_ui('mod_simplificat'), on_change=sync, args=('mod_simplificat',))
    
    modele_active = get_available_models()
    st.write("---")
    st.markdown("#### 🤖 Status Motor AI & Bază de Date")
    st.caption(f"Model principal selectat automat: **`{modele_active[0] if modele_active else 'Auto'}`**")
    nr_preturi = sum(len(v) for v in st.session_state.db.get("preturi_magazine", {}).values())
    nr_etichete = len(st.session_state.db.get("catalog_nutritie", {}))
    st.caption(f"📦 Prețuri învățate din bonuri: **{nr_preturi}** | 🏷️ Etichete nutriționale salvate: **{nr_etichete}**")
    with st.expander("Vezi toate modelele disponibile pe cheia ta API"):
        st.write(modele_active)

# ==========================================
# HEADER PREMIUM
# ==========================================
header_top_html = (
    '<div style="text-align:center; padding: 6px 0 4px 0;">'
    '<div style="display:inline-block; background:rgba(9,206,230,0.12); border:1px solid rgba(9,206,230,0.35); border-radius:20px; padding:3px 12px; font-size:11px; color:#09CEE6; font-weight:700; margin-bottom:4px;">SMART NUTRITION & PRICE ENGINE</div>'
    '<h2 style="margin:0; padding:0; font-size:26px; font-weight:800; color:#FFFFFF;">🥗 Asistent Nutriție Pro</h2>'
    '<p style="color:#A0AEC0; font-size:13px; margin-top:2px; margin-bottom:0;">Mese delicioase, buget optimizat pe magazine & învățare din bonuri fiscale</p>'
    '</div>'
)
st.markdown(header_top_html, unsafe_allow_html=True)

# ==========================================
# NAVBAR NATIV + Rotița ⚙️
# ==========================================
col_menu, col_set = st.columns([9.1, 0.9], vertical_alignment="center")

with col_menu:
    selected_tab = option_menu(
        menu_title=None,
        options=["Planificator", "Cumpărături", "Dietă & Mese", "Profil", "Rețetar"],
        icons=["calendar2-week", "cart", "sliders", "person", "book"],
        orientation="horizontal",
        key="main_menu_nav",
        styles={
            "container": {
                "padding": "5px", "background-color": card_bg, "border-radius": "30px", "border": f"1px solid {border_col}",
                "display": "flex", "flex-wrap": "nowrap", "overflow-x": "auto", "width": "100%"
            },
            "icon": {"color": "inherit", "font-size": "13px"},
            "nav-link": {
                "font-size": "11px", "margin": "0px 2px", "color": text_color, "font-weight": "700",
                "border-radius": "18px", "border": "1px solid rgba(9,206,230,0.35)", "background-color": "transparent",
                "display": "flex", "flex-direction": "row", "align-items": "center", "justify-content": "center", "white-space": "nowrap", "gap": "4px"
            },
            "nav-link-selected": {"background-color": "#09CEE6", "color": "#0B132B", "font-weight": "800"},
        }
    )

with col_set:
    if st.button("⚙️", key="gear_settings_btn", use_container_width=True):
        settings_modal()

st.write("")
view_to_show = selected_tab

# ==========================================
# TAB 1: PLANIFICATOR (SINCRONIZAT INSTANT CU PROFILUL)
# ==========================================
if view_to_show == "Planificator":
    kcal_zi_tinta = st.session_state.kcal_tinta
    logos_bar = render_store_logos_html(st.session_state.magazine_selectate, height_px=26)
    nr_preturi_db = sum(len(v) for v in st.session_state.db.get("preturi_magazine", {}).values())
    nr_nutri_db = len(st.session_state.db.get("catalog_nutritie", {}))

    with st.container(border=True):
        dashboard_html = (
            f'<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(165px, 1fr)); gap:10px; margin-bottom:10px;">'
            f'<div style="background:#0B132B; padding:12px; border-radius:14px; border:1px solid #2D3748;">'
            f'<div style="font-size:11px; color:#A0AEC0; font-weight:600;">👨‍👩‍👧 CONFIGURAȚIE PLAN</div>'
            f'<div style="font-size:17px; font-weight:800; color:#FFF; margin-top:4px;">{st.session_state.persoane} Pers. • {st.session_state.zile} Zile</div>'
            f'<div style="font-size:11px; color:#09CEE6; margin-top:2px;">{"🍲 Mod Batch Cooking" if st.session_state.batch_cooking else "📅 Meniu Zilnic"}</div>'
            f'</div>'
            f'<div style="background:#0B132B; padding:12px; border-radius:14px; border:1px solid #2D3748;">'
            f'<div style="font-size:11px; color:#A0AEC0; font-weight:600;">🎯 ȚINTĂ ZILNICĂ / PERS.</div>'
            f'<div style="font-size:18px; font-weight:800; color:#F6AD55; margin-top:4px;">🔥 {kcal_zi_tinta} kcal</div>'
            f'<div style="font-size:11.5px; font-weight:700; margin-top:2px;"><span style="color:#FC8181;">{st.session_state.prot_tinta}g P</span> • <span style="color:#68D391;">{st.session_state.carb_tinta}g C</span> • <span style="color:#F6E05E;">{st.session_state.gras_tinta}g G</span></div>'
            f'</div>'
            f'<div style="background:#0B132B; padding:12px; border-radius:14px; border:1px solid #2D3748;">'
            f'<div style="font-size:11px; color:#A0AEC0; font-weight:600;">💰 BUGET & MAGAZINE</div>'
            f'<div style="font-size:17px; font-weight:800; color:#68D391; margin-top:4px;">{st.session_state.buget_min} - {st.session_state.buget_max} RON</div>'
            f'<div style="margin-top:6px;">{logos_bar}</div>'
            f'</div>'
            f'</div>'
            f'<div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px; font-size:11.5px; color:#A0AEC0; background:rgba(9,206,230,0.07); padding:7px 12px; border-radius:10px;">'
            f'<span>👤 <b>Profil Activ:</b> {st.session_state.varsta} ani, {st.session_state.inaltime} cm, {st.session_state.greutate:.1f} kg ({st.session_state.obiectiv})</span>'
            f'<span style="color:#09CEE6;">📦 {nr_preturi_db} prețuri & {nr_nutri_db} etichete ✓</span>'
            f'</div>'
        )
        st.markdown(dashboard_html, unsafe_allow_html=True)

        with st.expander("✏️ Ajustează Rapid Bugetul sau Magazinele"):
            cb1, cb2 = st.columns(2)
            with cb1:
                st.number_input("Buget Minim (RON)", min_value=0, step=10, key=init_ui('buget_min'), on_change=sync_budget_from_inputs)
            with cb2:
                st.number_input("Buget Maxim (RON)", min_value=0, step=10, key=init_ui('buget_max'), on_change=sync_budget_from_inputs)
            st.multiselect("Magazine active:", magazine_disponibile, key=init_ui('magazine_selectate'), on_change=sync, args=('magazine_selectate',))

    if st.session_state.retetar_favorite:
        with st.container(border=True):
            st.multiselect("🖤 Include obligatoriu rețete din Rețetarul tău:", [r.get('nume', 'Rețetă') for r in st.session_state.retetar_favorite], key=init_ui('include_favorites'), on_change=sync, args=('include_favorites',))

    with st.container(border=True):
        st.markdown("#### 🛍️ Optimizare Oferte & Cataloage")
        st.session_state.tip_oferta = st.radio(
            "Sursă prețuri:",
            ["Estimare prețuri actuale + Baza ta de bonuri", "Încarcă poze cu revista de oferte"],
            horizontal=True
        )
        if st.session_state.tip_oferta == "Încarcă poze cu revista de oferte":
            st.session_state.fisiere_poze = st.file_uploader("Încarcă imagini din catalogul de reduceri:", type=["png", "jpg", "jpeg"], accept_multiple_files=True)

    if st.button("🔥 GENEREAZĂ PLANUL ȘI CALCULEAZĂ PREȚURILE", type="primary", use_container_width=True):
        with st.spinner(f"Se consultă baza de prețuri {', '.join(st.session_state.magazine_selectate)} și se creează rețetele pentru {kcal_zi_tinta} kcal/zi..."):
            mag = ", ".join(st.session_state.magazine_selectate) if st.session_state.magazine_selectate else "Lidl"
            echip = ", ".join(st.session_state.echipamente)
            med_pref = ", ".join(st.session_state.preferinte_medicale)
            alg = ", ".join(st.session_state.alergeni) + " " + st.session_state.alte_restrictii

            preturi_salvate_txt = ""
            for m_sel in st.session_state.magazine_selectate:
                p_mag = st.session_state.db.get("preturi_magazine", {}).get(m_sel, {})
                for prod_k, info_p in p_mag.items():
                    preturi_salvate_txt += f"- {m_sel}: {prod_k} = {info_p.get('pret')} RON ({info_p.get('ambalaj', '1 buc')})\n"

            nutri_salvate_txt = ""
            for prod_n, info_n in st.session_state.db.get("catalog_nutritie", {}).items():
                nutri_salvate_txt += (
                    f"- {info_n.get('nume_afisat', prod_n)} (per 100g): "
                    f"{info_n.get('kcal_100g')} kcal, {info_n.get('prot_100g')}g P, "
                    f"{info_n.get('carb_100g')}g C, {info_n.get('gras_100g')}g G\n"
                )

            if st.session_state.batch_cooking:
                mese_batch = st.session_state.config_mese.get("Ziua 1", ["Mic dejun", "Prânz", "Cină"]) if st.session_state.config_mese else ["Mic dejun", "Prânz", "Cină"]
                instructiune_mod = f"""
                MOD BATCH COOKING ACTIVAT:
                - Utilizatorul gătește O SINGURĂ DATĂ pentru toate cele {st.session_state.zile} zile ({st.session_state.persoane} persoane).
                - Generează EXACT câte un obiect în `retete` pentru fiecare masă din șablonul: {', '.join(mese_batch)}.
                - NU genera Ziua 1, Ziua 2, Ziua 3 separat!
                - În câmpul `perioada` scrie exact: "Pentru {st.session_state.zile} zile (Batch)".
                - Cantitățile și prețurile din rețetă trebuie să fie ÎNMULȚITE pentru toate cele {st.session_state.zile * st.session_state.persoane} porții totale!
                """
            else:
                cfg = "".join([f"- {zi}: {', '.join(mese)}\n" for zi, mese in st.session_state.config_mese.items()]) if st.session_state.config_mese else f"3 mese pe zi (Mic dejun, Prânz, Cină) pentru {st.session_state.zile} zile."
                instructiune_mod = f"MOD ZILNIC: Generează rețetele pentru fiecare zi conform structurii:\n{cfg}"

            prompt = f"""
            Ești un nutriționist și expert în prețurile supermarketurilor din România ({mag}).
            Răspunde STRICT în format JSON valid, în limba română.
            
            PARAMETRI PLAN:
            - Persoane: {st.session_state.persoane} | Zile: {st.session_state.zile}
            - Magazine selectate: {mag}
            - Buget total țintă: {st.session_state.buget_min} - {st.session_state.buget_max} RON
            - Țintă EXACTĂ / persoană / zi: {kcal_zi_tinta} kcal ({st.session_state.prot_tinta}g Proteine, {st.session_state.carb_tinta}g Carbohidrați, {st.session_state.gras_tinta}g Grăsimi). Suma meselor dintr-o zi trebuie să respecte această țintă!
            - Aparate disponibile: {echip}
            - Stil gătire: {st.session_state.tip_reteta}
            - Preferințe medicale: {med_pref if med_pref else 'Niciuna'}
            - Restricții/Alergeni: {alg if alg.strip() else 'Niciuna'}
            - Ingrediente deja în cămară (cost 0 în lista de cumpărături): {st.session_state.camara if st.session_state.camara else 'Niciunul'}
            
            PREȚURI REALE EXTRASE DIN BONURILE UTILIZATORULUI (Folosește OBLIGATORIU aceste prețuri când incluzi aceste produse):
            {preturi_salvate_txt if preturi_salvate_txt else 'Niciun bon scanat încă - folosește prețurile reale din România 2026.'}

            VALORI NUTRIȚIONALE EXACTE DIN ETICHETELE SCANATE DE UTILIZATOR (Folosește OBLIGATORIU aceste valori per 100g):
            {nutri_salvate_txt if nutri_salvate_txt else 'Nicio etichetă scanată încă.'}

            {instructiune_mod}

            SCHEMA JSON OBLIGATORIE:
            {{
              "lista_cumparaturi": [
                {{
                  "produs": "Piept de pui dezosat",
                  "magazin": "{st.session_state.magazine_selectate[0] if st.session_state.magazine_selectate else 'Lidl'}",
                  "categorie": "Carne & Pește",
                  "cantitate_necesara": "750g",
                  "ambalaj_raft": "Caserolă 1kg",
                  "pret_raft_ron": 28.90,
                  "kcal_100g": 110
                }}
              ],
              "retete": [
                {{
                  "perioada": "Pentru 3 zile (Batch)",
                  "tip_masa": "Prânz",
                  "nume": "Pui cu orez basmati și legume",
                  "timp_preparare": "30 min",
                  "numar_portii": {st.session_state.zile * st.session_state.persoane},
                  "cost_total_reteta_ron": 38.50,
                  "cost_per_portie_ron": 12.83,
                  "macro_per_portie": {{
                    "kcal": 580,
                    "proteine_g": 52,
                    "carbo_g": 64,
                    "grasimi_g": 11
                  }},
                  "aparate": ["Aragaz (Plită)"],
                  "ingrediente": [
                    {{
                      "produs": "Piept de pui",
                      "cantitate": "750g",
                      "gramaj_g": 750,
                      "magazin": "{st.session_state.magazine_selectate[0] if st.session_state.magazine_selectate else 'Lidl'}",
                      "pret_estimat_ron": 22.00,
                      "kcal_100g": 110,
                      "prot_100g": 23.0,
                      "carb_100g": 0.0,
                      "gras_100g": 1.5
                    }}
                  ],
                  "pasi_preparare": [
                    "Spală orezul și fierbe-l în apă cu sare timp de 12 minute.",
                    "Taie pieptul de pui cubulețe și rumenește-l în tigaie."
                  ],
                  "sfat_depozitare": "Împarte în 3 caserole egale. Rezistă la frigider până la 4 zile."
                }}
              ]
            }}
            """
            
            continut_ai = [prompt]
            if st.session_state.tip_oferta == "Încarcă poze cu revista de oferte" and st.session_state.fisiere_poze:
                for f in st.session_state.fisiere_poze:
                    continut_ai.append(Image.open(f))

            rezultat_ai, eroare_detaliata = generate_with_ai(continut_ai, expect_json=True)

            if rezultat_ai is not None:
                try:
                    data_parsed = parse_ai_json(rezultat_ai.text)
                    lista_cump = data_parsed.get("lista_cumparaturi", [])
                    retete_list = data_parsed.get("retete", [])
                    
                    if lista_cump:
                        df = pd.DataFrame(lista_cump)
                        rename_map = {
                            "produs": "Produs",
                            "magazin": "Magazin",
                            "categorie": "Categorie",
                            "cantitate_necesara": "Cantitate Rețete",
                            "ambalaj_raft": "Ambalaj Raft",
                            "pret_raft_ron": "Preț Raft (RON)",
                            "kcal_100g": "Kcal / 100g"
                        }
                        df.rename(columns=rename_map, inplace=True)
                        if 'Cumpărat' not in df.columns:
                            df.insert(0, 'Cumpărat', False)
                        st.session_state.plan_df = df
                        
                    if retete_list:
                        st.session_state.plan_retete = retete_list
                    else:
                        st.error("AI-ul nu a returnat lista de rețete. Mai încearcă o dată.")
                except Exception as e:
                    st.error(f"Eroare la procesarea datelor: {str(e)}")
            else:
                st.error(f"❌ Eroare la apelarea API-ului Google:\n\n{eroare_detaliata}")

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

        text_desc = f"🛒 LISTA DE CUMPĂRĂTURI (Total Raft: {total_raft:.2f} RON)\n========================================\n" + df_cump.to_string(index=False) + "\n\n🍽️ PLAN ALIMENTAR DETALIAT\n========================================\n"
        for r in st.session_state.plan_retete:
            text_desc += f"\n[{r.get('perioada')}] {r.get('tip_masa')} - {r.get('nume')} ({r.get('cost_total_reteta_ron')} RON)\n"
            for ing in r.get("ingrediente", []):
                text_desc += f"  - {ing.get('produs')}: {ing.get('cantitate')} ({ing.get('magazin')} - {ing.get('pret_estimat_ron')} RON)\n"
            for pas in r.get("pasi_preparare", []):
                text_desc += f"  * {pas}\n"

        col_dl1, col_dl2 = st.columns(2)
        with col_dl1: st.download_button("💾 Descarcă Planul & Prețurile (.txt)", data=text_desc, file_name="Plan_Nutritie_Preturi.txt", mime="text/plain", use_container_width=True)
        with col_dl2: st.download_button("📅 Exportă în Calendar (.ics)", data=get_ics_content(), file_name="Mese.ics", mime="text/calendar", use_container_width=True)
        
        st.subheader("🍽️ Planul Tău Alimentar")
        mese_bifate_pentru_pastrare = []
        for i, reteta in enumerate(st.session_state.plan_retete):
            pastrat = render_recipe_card(reteta, index=i, allow_actions=True)
            if pastrat:
                mese_bifate_pentru_pastrare.append(reteta.get('nume', ''))
        st.session_state.mese_de_pastrat = mese_bifate_pentru_pastrare

    st.write("---")
    st.subheader("🧊 Frigiderul Magic (Snap & Cook)")
    with st.container(border=True):
        t1, t2, t3 = st.tabs(["📝 Scrie Ingredientele", "🎙️ Comandă Vocală", "📸 Pozează Frigiderul"])
        cu_ce_gatesc, audio_frigider, poza_frigider = None, None, None
        
        with t1: cu_ce_gatesc = st.text_input("Ex: ouă, brânză, roșii, tortilla", key="frigider_text")
        with t2: audio_frigider = st.audio_input("Dictează ingredientele pe care le ai:")
        with t3:
            poza_up = st.file_uploader("Încarcă sau fă o poză la ingrediente", type=["png", "jpg", "jpeg"], key="snap_cook_up")
            poza_frigider = poza_up

        if st.button("✨ Găsește-mi o rețetă rapidă", use_container_width=True):
            if cu_ce_gatesc or poza_frigider or audio_frigider:
                with st.spinner("Se creează rețeta..."):
                    continut_snap = [f"Ești asistent culinar. RĂSPUNDE STRICT ÎN ROMÂNĂ. Creează o rețetă structurată folosind ingredientele oferite. Calculează macro și preț estimat pentru {st.session_state.persoane} persoane."]
                    if cu_ce_gatesc: continut_snap.append(f"Ingrediente: {cu_ce_gatesc}")
                    if poza_frigider: continut_snap.append(Image.open(poza_frigider))
                    if audio_frigider: continut_snap.append({"mime_type": "audio/wav", "data": audio_frigider.getvalue()})
                    rezultat_ai, eroare_detaliata = generate_with_ai(continut_snap, expect_json=False)
                    if rezultat_ai is not None:
                        st.success("Rețetă găsită!")
                        st.markdown(rezultat_ai.text)
                    else:
                        st.error(f"❌ Eroare API Google:\n\n{eroare_detaliata}")
            else:
                st.warning("Introdu ingrediente (text, poză sau voce)!")

# ==========================================
# TAB 2: CUMPĂRĂTURI
# ==========================================
elif selected_tab == "Cumpărături":
    st.subheader("🛒 Setări Magazin & Cămară")
    with st.container(border=True):
        col_c1, col_c2 = st.columns([1, 1.4])
        with col_c1:
            st.selectbox("Ziua de cumpărături:", zile_saptamana, key=init_ui('zi_cumparaturi'), on_change=sync, args=('zi_cumparaturi',))
        with col_c2:
            st.multiselect("Selectează magazinele:", magazine_disponibile, key=init_ui('magazine_selectate'), on_change=sync, args=('magazine_selectate',))
        
        st.markdown(f'<div style="margin:6px 0 12px 0;">{render_store_logos_html(st.session_state.magazine_selectate, height_px=28)}</div>', unsafe_allow_html=True)
        st.markdown("**🥫 Cămara Virtuală (Produse pe care le ai deja acasă - excluse de la plată)**")
        st.text_area("Ex: Ulei de măsline, orez, sare, piper, condimente", key=init_ui('camara'), on_change=sync, args=('camara',), height=68)

    st.subheader(f"📋 Lista de Cumpărături ({st.session_state.zi_cumparaturi})")
    if st.session_state.plan_df is not None and not st.session_state.plan_df.empty:
        with st.container(border=True):
            df_edit = st.data_editor(
                st.session_state.plan_df,
                column_config={"Cumpărat": st.column_config.CheckboxColumn("În coș", default=False)},
                hide_index=True,
                use_container_width=True
            )
            st.session_state.plan_df = df_edit

            if "Preț Raft (RON)" in df_edit.columns:
                total_cump = pd.to_numeric(df_edit["Preț Raft (RON)"], errors='coerce').sum()
                bifat_count = int(df_edit["Cumpărat"].sum()) if "Cumpărat" in df_edit.columns else 0
                total_items = max(1, len(df_edit))
                procent_cos = bifat_count / total_items
                ramas_de_plata = pd.to_numeric(df_edit[~df_edit["Cumpărat"]]["Preț Raft (RON)"], errors='coerce').sum()

                st.progress(procent_cos, text=f"Progres cumpărături: {bifat_count} din {total_items} produse puse în coș ({int(procent_cos*100)}%)")
                c_tot1, c_tot2 = st.columns(2)
                c_tot1.metric("💰 Total Estimativ la Raft", f"{total_cump:.2f} RON")
                c_tot2.metric("🛒 Rămas de pus în coș", f"{ramas_de_plata:.2f} RON")
    else:
        st.info("Nu ai generat încă o listă de cumpărături. Mergi în tab-ul 'Planificator' și apasă pe Generează.")

    st.write("---")
    st.subheader("🏷️ Verifică & Actualizează Macronutrienții la Raft")
    with st.container(border=True):
        st.caption("Ești în magazin și ai luat un produs? Fă o poză etichetei nutriționale! Aplicația îi salvează valorile exacte și **recalculează activ macronutrienții din rețetele tale**.")
        
        produse_lista = st.session_state.plan_df["Produs"].tolist() if (st.session_state.plan_df is not None and "Produs" in st.session_state.plan_df.columns) else []
        optiuni_produs = produse_lista + ["Alt produs (scrie manual)..."]
        
        col_et1, col_et2 = st.columns(2)
        with col_et1:
            prod_selectat_raft = st.selectbox("Alege produsul din lista ta:", optiuni_produs, key="raft_prod_sel")
            if prod_selectat_raft == "Alt produs (scrie manual)...":
                prod_final_raft = st.text_input("Scrie numele produsului:", placeholder="Ex: Iaurt Grecesc Pilos 10%", key="raft_prod_manual")
            else:
                prod_final_raft = prod_selectat_raft
        with col_et2:
            poza_eticheta_raft = st.file_uploader("📸 Încarcă / Fă poză la tabelul nutrițional (per 100g):", type=["png", "jpg", "jpeg"], key="raft_label_img")

        if st.button("⚡ Extrage Eticheta & Recalculează Rețetele Active", type="primary", use_container_width=True):
            if prod_final_raft and poza_eticheta_raft:
                with st.spinner(f"Se citește eticheta nutrițională pentru '{prod_final_raft}'..."):
                    prompt_label = """
                    Analizează imaginea cu eticheta nutrițională a produsului.
                    Extrage valorile nutriționale STRICT per 100g (sau 100ml).
                    Răspunde STRICT în format JSON valid:
                    {
                      "kcal_100g": 115,
                      "prot_100g": 9.0,
                      "carb_100g": 3.8,
                      "gras_100g": 5.0
                    }
                    """
                    res_lbl, err_lbl = generate_with_ai([prompt_label, Image.open(poza_eticheta_raft)], expect_json=True)
                    if res_lbl:
                        try:
                            val_lbl = parse_ai_json(res_lbl.text)
                            k_100 = float(val_lbl.get("kcal_100g", 0))
                            p_100 = float(val_lbl.get("prot_100g", 0))
                            c_100 = float(val_lbl.get("carb_100g", 0))
                            g_100 = float(val_lbl.get("gras_100g", 0))

                            cheie_prod = prod_final_raft.strip().lower()
                            st.session_state.db["catalog_nutritie"][cheie_prod] = {
                                "nume_afisat": prod_final_raft.strip(),
                                "kcal_100g": k_100,
                                "prot_100g": p_100,
                                "carb_100g": c_100,
                                "gras_100g": g_100,
                                "data": datetime.now().strftime("%Y-%m-%d")
                            }
                            save_local_db(st.session_state.db)

                            nr_retete_mod = recalculate_active_recipes_macros(prod_final_raft, k_100, p_100, c_100, g_100)
                            st.success(f"✅ Etichetă salvată pentru **{prod_final_raft}** ({k_100} kcal, {p_100}g P, {c_100}g C, {g_100}g G / 100g)! S-au recalculat automat macronutrienții în **{nr_retete_mod}** rețete active!")
                        except Exception as e:
                            st.error(f"Eroare la citirea cifrelor de pe etichetă: {e}")
                    else:
                        st.error(f"Eroare AI: {err_lbl}")
            else:
                st.warning("Selectează produsul și încarcă poza cu eticheta nutrițională!")

    st.write("---")
    st.subheader("🧾 Scanează Bonul Fiscal (Salvare Prețuri Exacte pe Magazin)")
    with st.container(border=True):
        st.caption("Ai terminat cumpărăturile? Selectează magazinul și încarcă poza cu bonul fiscal. Aplicația învață prețurile reale și le folosește automat la viitoarele meniuri!")
        
        col_bon1, col_bon2 = st.columns([1, 1.3])
        with col_bon1:
            magazin_bon = st.selectbox("De la ce magazin ai făcut cumpărăturile?", magazine_disponibile, key="bon_magazin_sel")
            st.markdown(render_store_logos_html([magazin_bon], height_px=34), unsafe_allow_html=True)
        with col_bon2:
            poza_bon = st.file_uploader("📸 Încarcă poza cu bonul fiscal:", type=["png", "jpg", "jpeg"], key="bon_img_up")

        if st.button("💳 Extrage Prețurile de pe Bon & Actualizează Baza de Date", type="primary", use_container_width=True):
            if poza_bon:
                with st.spinner(f"Se citesc produsele și prețurile de pe bonul {magazin_bon}..."):
                    prompt_bon = f"""
                    Analizează această imagine a unui bon fiscal de la magazinul {magazin_bon} din România.
                    Extrage toate produsele alimentare și prețul final plătit în RON pentru fiecare produs.
                    Normalizează denumirile prescurtate de pe bon în denumiri clare în limba română (ex: 'PIEPT PUI DEZ' -> 'Piept de pui dezosat').
                    Răspunde STRICT în format JSON valid:
                    {{
                      "produse_bon": [
                        {{
                          "nume_clar": "Piept de pui dezosat",
                          "pret_ron": 27.90,
                          "cantitate_sau_ambalaj": "1 buc / kg"
                        }}
                      ]
                    }}
                    """
                    res_bon, err_bon = generate_with_ai([prompt_bon, Image.open(poza_bon)], expect_json=True)
                    if res_bon:
                        try:
                            data_bon = parse_ai_json(res_bon.text)
                            lista_bon = data_bon.get("produse_bon", [])
                            if lista_bon:
                                if magazin_bon not in st.session_state.db["preturi_magazine"]:
                                    st.session_state.db["preturi_magazine"][magazin_bon] = {}
                                
                                updated_in_list = 0
                                for item in lista_bon:
                                    nume_p = str(item.get("nume_clar", "")).strip()
                                    pret_p = float(item.get("pret_ron", 0.0))
                                    amb_p = str(item.get("cantitate_sau_ambalaj", "1 buc"))
                                    if nume_p and pret_p > 0:
                                        st.session_state.db["preturi_magazine"][magazin_bon][nume_p.lower()] = {
                                            "nume_afisat": nume_p,
                                            "pret": pret_p,
                                            "ambalaj": amb_p,
                                            "data": datetime.now().strftime("%Y-%m-%d")
                                        }
                                        if st.session_state.plan_df is not None and "Produs" in st.session_state.plan_df.columns:
                                            for idx, row in st.session_state.plan_df.iterrows():
                                                p_lista = str(row["Produs"]).strip().lower()
                                                if nume_p.lower() in p_lista or p_lista in nume_p.lower():
                                                    st.session_state.plan_df.at[idx, "Preț Raft (RON)"] = pret_p
                                                    st.session_state.plan_df.at[idx, "Magazin"] = magazin_bon
                                                    updated_in_list += 1

                                save_local_db(st.session_state.db)
                                st.success(f"🎉 Am extras și salvat **{len(lista_bon)} prețuri reale** pentru **{magazin_bon}**! ({updated_in_list} produse au fost actualizate direct în lista ta curentă).")
                                st.dataframe(pd.DataFrame(lista_bon), use_container_width=True, hide_index=True)
                            else:
                                st.warning("Nu s-au putut identifica produse clare pe bon. Asigură-te că poza este clară.")
                        except Exception as e:
                            st.error(f"Eroare la procesarea bonului: {e}")
                    else:
                        st.error(f"Eroare AI: {err_bon}")
            else:
                st.warning("Te rog să încarci mai întâi o poză cu bonul fiscal!")

# ==========================================
# TAB 3: DIETĂ & MESE
# ==========================================
elif selected_tab == "Dietă & Mese":
    st.subheader("👥 Configurare Persoane, Zile & Buget")
    with st.container(border=True):
        c1, c2 = st.columns(2)
        with c1:
            st.slider("👨‍👩‍👧 Număr persoane:", 1, 10, key=init_ui('persoane'), on_change=on_scale_change)
        with c2:
            st.slider("📅 Zile planificate:", 1, 7, key=init_ui('zile'), on_change=on_scale_change)
        
        st.write("---")
        st.session_state.ui_buget_slider = (int(st.session_state.buget_min), int(st.session_state.buget_max))
        st.slider(
            "💰 Interval Buget Alocat (Min - Max RON):",
            min_value=20,
            max_value=2500,
            step=10,
            key="ui_buget_slider",
            on_change=sync_budget_from_slider
        )
        st.caption(f"Buget activ: **{st.session_state.buget_min} RON – {st.session_state.buget_max} RON** (aprox. {st.session_state.buget_max / max(1, st.session_state.zile * st.session_state.persoane):.1f} RON / zi / persoană)")
    
    if not st.session_state.mod_simplificat:
        st.subheader("🏥 Sănătate, Echipamente & Stil Gătire")
        with st.container(border=True):
            col_e1, col_e2 = st.columns(2)
            with col_e1:
                st.multiselect("🍳 Aparate deținute în bucătărie:", lista_echipamente, key=init_ui('echipamente'), on_change=sync, args=('echipamente',))
                st.multiselect("🩺 Preferințe Medicale:", lista_medicale, key=init_ui('preferinte_medicale'), on_change=sync, args=('preferinte_medicale',))
            with col_e2:
                st.multiselect("🚫 Alergeni / Ingrediente Interzise:", lista_alergeni, key=init_ui('alergeni'), on_change=sync, args=('alergeni',))
                st.selectbox("⏱️ Stil de gătire preferat:", opts_gatire, key=init_ui('tip_reteta'), on_change=sync, args=('tip_reteta',))
            
            st.write("---")
            st.checkbox("🍲 Activează Mod Batch Cooking (Gătești o singură dată cantități mari pentru caserole)", key=init_ui('batch_cooking'), on_change=sync, args=('batch_cooking',))

    st.subheader("📅 Cronologia Meselor")
    with st.container(border=True):
        if st.session_state.batch_cooking:
            st.info(f"🍲 Mod Batch Cooking activ pentru {st.session_state.zile} zile! Configurează mai jos tipurile de mese pe care vrei să le gătești la caserolă.")
            taburi_zile = st.tabs(["Structură Mese (Batch)"])
            zile_iter = [1]
        else:
            taburi_zile = st.tabs([f"Ziua {i}" for i in range(1, st.session_state.zile + 1)])
            zile_iter = range(1, st.session_state.zile + 1)
            if not st.session_state.config_mese:
                for i in range(1, 8):
                    st.session_state.config_mese[f"Ziua {i}"] = ["Mic dejun", "Prânz", "Cină"]

        for idx, tab_zi in enumerate(taburi_zile):
            zi = zile_iter[idx]
            with tab_zi:
                nr_mese = st.number_input("Număr de mese principale:", 1, 6, value=3, key=f"nr_m_{zi}")
                mese_azi = []
                cols_m = st.columns(min(3, nr_mese))
                for m in range(nr_mese):
                    opt = ["Mic dejun", "Prânz", "Cină", "Masa 4", "Masa 5", "Personalizat..."]
                    n_def = "Mic dejun" if m==0 else "Prânz" if m==1 else "Cină" if m==2 else f"Masa {m+1}"
                    if f"sel_tip_m_{zi}_{m}" not in st.session_state:
                        st.session_state[f"sel_tip_m_{zi}_{m}"] = opt[opt.index(n_def) if n_def in opt else 5]
                    with cols_m[m % len(cols_m)]:
                        sel = st.selectbox(f"Masa {m+1}", options=opt, key=f"sel_tip_m_{zi}_{m}")
                        if sel == "Personalizat...":
                            if f"nume_pers_{zi}_{m}" not in st.session_state:
                                st.session_state[f"nume_pers_{zi}_{m}"] = ""
                            n = st.text_input("Denumire:", key=f"nume_pers_{zi}_{m}")
                        else:
                            n = sel
                    mese_azi.append(n if n.strip() else f"Masa {m+1}")
                
                if f"chk_snack_{zi}" not in st.session_state:
                    st.session_state[f"chk_snack_{zi}"] = False
                if st.checkbox("🍎 Include gustări între mese", key=f"chk_snack_{zi}"):
                    crono = []
                    if f"g_s_{zi}" not in st.session_state: st.session_state[f"g_s_{zi}"] = False
                    if st.checkbox(f"Înainte de {mese_azi[0]}", key=f"g_s_{zi}"): crono.append("Gustare dimineață")
                    for j in range(nr_mese):
                        crono.append(mese_azi[j])
                        if j < nr_mese - 1:
                            if f"g_m_{zi}_{j}" not in st.session_state: st.session_state[f"g_m_{zi}_{j}"] = False
                            if st.checkbox(f"Între {mese_azi[j]} & {mese_azi[j+1]}", key=f"g_m_{zi}_{j}"): crono.append("Gustare")
                        else:
                            if f"g_e_{zi}" not in st.session_state: st.session_state[f"g_e_{zi}"] = False
                            if st.checkbox(f"După {mese_azi[j]}", key=f"g_e_{zi}"): crono.append("Gustare seară")
                    st.session_state.config_mese[f"Ziua {zi}"] = crono
                else:
                    st.session_state.config_mese[f"Ziua {zi}"] = mese_azi

# ==========================================
# TAB 4: PROFIL (CU AUTO-SYNC ÎN TIMP REAL SPRE PLANIFICATOR)
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
        st.markdown("#### 📉 Configurare Protocol Caloric & Macronutrienți")
        c_slab1, c_slab2 = st.columns(2)
        with c_slab1:
            if "Slăbire" in st.session_state.obiectiv:
                st.select_slider(
                    "Ritm slăbire:",
                    options=ritm_opts,
                    key=init_ui('ritm_slabire'),
                    on_change=recalc_from_biometrics
                )
            elif "Creștere masă" in st.session_state.obiectiv:
                st.info("💪 Surplus caloric activ (+400 kcal / zi pentru construcție musculară)")
            else:
                st.info("⚖️ Regim de menținere activ (100% din TDEE)")
        with c_slab2:
            st.selectbox(
                "Protocol Macronutrienți:",
                distributie_opts,
                key=init_ui('distributie_macro'),
                on_change=recalc_from_biometrics
            )
            if "Menținere masă" in st.session_state.distributie_macro:
                st.number_input("Grăsime Corporală Estimată (%)", 5, 60, key=init_ui('bf_proc'), on_change=recalc_from_biometrics)
        
        if st.button("🚀 Aplică & Sincronizează Formula în Planificator", type="primary", use_container_width=True):
            recalc_from_biometrics()
            st.toast(f"Țintă sincronizată: {st.session_state.kcal_tinta} kcal ({st.session_state.prot_tinta}P / {st.session_state.carb_tinta}C / {st.session_state.gras_tinta}G)!", icon="✅")

    calc_info = calculate_biometric_targets()

    with st.container(border=True):
        c_m1, c_m2, c_m3 = st.columns(3)
        c_m1.metric("📊 Indice BMI", f"{calc_info['bmi']:.1f}", "Normal" if 18.5 <= calc_info['bmi'] <= 25 else "Atenție")
        c_m2.metric("🔥 Necesar Zilnic (Sincronizat)", f"{st.session_state.kcal_tinta} kcal", f"BMR: {calc_info['bmr']} kcal")
        with c_m3:
            st.write("")
            st.button("⚖️ Am stagnat (-150 Kcal)", on_click=cut_tdee, use_container_width=True)

    with st.container(border=True):
        st.markdown("#### 💧 Hidratare Zilnică")
        cw1, cw2, cw3 = st.columns([1, 2, 1])
        with cw1: st.button("➖ 250 ml", on_click=sub_water, use_container_width=True)
        with cw2: st.markdown(f"<h4 style='text-align: center; color: #09CEE6; margin:0;'>{st.session_state.water_ml} ml / 2500 ml</h4>", unsafe_allow_html=True)
        with cw3: st.button("➕ 250 ml", on_click=add_water, use_container_width=True)
        st.progress(min(st.session_state.water_ml / 2500.0, 1.0))

    with st.container(border=True):
        st.subheader("🎯 Țintă Macronutrienți / Persoană / Zi")
        st.caption("Aceste valori se actualizează automat din datele tale de mai sus și sunt trimise direct în **Planificator** (le poți ajusta și manual dacă dorești):")
        c1, c2, c3 = st.columns(3)
        with c1: st.number_input("🥩 Proteine (g)", 0, 500, key=init_ui('prot_tinta'), on_change=sync_manual_macros)
        with c2: st.number_input("🌾 Carbohidrați (g)", 0, 1000, key=init_ui('carb_tinta'), on_change=sync_manual_macros)
        with c3: st.number_input("🥑 Grăsimi (g)", 0, 300, key=init_ui('gras_tinta'), on_change=sync_manual_macros)

        df_macro = pd.DataFrame({
            "Nutrient": ["Proteine", "Carbohidrați", "Grăsimi"],
            "Grame": [st.session_state.prot_tinta, st.session_state.carb_tinta, st.session_state.gras_tinta],
            "Calorii": [st.session_state.prot_tinta * 4, st.session_state.carb_tinta * 4, st.session_state.gras_tinta * 9]
        })
        fig = px.pie(df_macro, values='Calorii', names='Nutrient', hover_data=['Grame'], hole=0.45, color='Nutrient', color_discrete_map={"Proteine": "#FC8181", "Carbohidrați": "#68D391", "Grăsimi": "#F6E05E"})
        fig.update_layout(height=280, margin=dict(t=10, b=10, l=10, r=10), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color=text_color))
        st.plotly_chart(fig, use_container_width=True)

# ==========================================
# TAB 5: REȚETAR & CATALOG ETICHETE NUTRIȚIONALE / PREȚURI
# ==========================================
elif selected_tab == "Rețetar":
    sub_fav, sub_etichete, sub_preturi = st.tabs([
        "📖 Rețete Favorite",
        "🏷️ Scanner Etichete Nutriționale",
        "💰 Bază Prețuri Bonuri"
    ])

    with sub_fav:
        st.subheader("📖 Rețetarul Meu (Salvate Permanent)")
        if not st.session_state.retetar_favorite:
            st.info("Nu ai încă rețete salvate. Generează un plan în 'Planificator' și apasă pe '🖤 Salvează în Rețetar'!")
        else:
            for idx, fav in enumerate(st.session_state.retetar_favorite):
                render_recipe_card(fav, index=idx, allow_actions=False)
                if st.button("❌ Șterge din Rețetar", type="secondary", key=f"del_fav_{idx}"):
                    st.session_state.retetar_favorite.pop(idx)
                    st.session_state.db["retetar_favorite"] = st.session_state.retetar_favorite
                    save_local_db(st.session_state.db)
                    st.rerun()

    with sub_etichete:
        st.subheader("🏷️ Adaugă Produs prin Poză la Eticheta Nutrițională")
        with st.container(border=True):
            st.caption("Fă o poză tabelului nutrițional de pe orice produs. Valorile (Kcal, Proteine, Carbohidrați, Grăsimi per 100g) rămân salvate în aplicație pentru calcule nutriționale exacte!")
            
            c_l1, c_l2 = st.columns(2)
            with c_l1:
                nume_prod_eticheta = st.text_input("Denumirea produsului (și marca):", placeholder="Ex: Brânză Cottage Lidl Pilos 3%", key="retetar_lbl_name")
            with c_l2:
                poza_lbl_retetar = st.file_uploader("📸 Încarcă poza cu eticheta nutrițională:", type=["png", "jpg", "jpeg"], key="retetar_lbl_img")

            if st.button("💾 Scanează & Salvează în Catalogul Nutrițional", type="primary", use_container_width=True):
                if poza_lbl_retetar:
                    with st.spinner("Se extrag macronutrienții de pe etichetă..."):
                        prompt_lbl2 = f"""
                        Analizează imaginea cu eticheta nutrițională.
                        Dacă utilizatorul nu a scris numele, identifică și denumirea produsului.
                        Extrage valorile nutriționale STRICT per 100g (sau 100ml).
                        Răspunde STRICT în format JSON valid:
                        {{
                          "nume_identificat": "{nume_prod_eticheta if nume_prod_eticheta else 'Produs Alimentar'}",
                          "kcal_100g": 115,
                          "prot_100g": 9.0,
                          "carb_100g": 3.8,
                          "gras_100g": 5.0
                        }}
                        """
                        res_l2, err_l2 = generate_with_ai([prompt_lbl2, Image.open(poza_lbl_retetar)], expect_json=True)
                        if res_l2:
                            try:
                                d_l2 = parse_ai_json(res_l2.text)
                                final_name = nume_prod_eticheta.strip() if nume_prod_eticheta.strip() else str(d_l2.get("nume_identificat", "Produs")).strip()
                                k_v = float(d_l2.get("kcal_100g", 0))
                                p_v = float(d_l2.get("prot_100g", 0))
                                c_v = float(d_l2.get("carb_100g", 0))
                                g_v = float(d_l2.get("gras_100g", 0))

                                st.session_state.db["catalog_nutritie"][final_name.lower()] = {
                                    "nume_afisat": final_name,
                                    "kcal_100g": k_v,
                                    "prot_100g": p_v,
                                    "carb_100g": c_v,
                                    "gras_100g": g_v,
                                    "data": datetime.now().strftime("%Y-%m-%d")
                                }
                                save_local_db(st.session_state.db)
                                recalculate_active_recipes_macros(final_name, k_v, p_v, c_v, g_v)
                                st.success(f"✅ Produsul **{final_name}** ({k_v} kcal | {p_v}g P | {c_v}g C | {g_v}g G per 100g) a fost salvat în baza de date!")
                            except Exception as e:
                                st.error(f"Eroare la citirea etichetei: {e}")
                        else:
                            st.error(f"Eroare AI: {err_l2}")
                else:
                    st.warning("Încarcă o poză cu eticheta nutrițională!")

        st.markdown("#### 📦 Produse Salvate în Catalogul Tău Nutrițional")
        cat_nutri = st.session_state.db.get("catalog_nutritie", {})
        if cat_nutri:
            rows_n = []
            for k, v in cat_nutri.items():
                rows_n.append({
                    "Produs": v.get("nume_afisat", k),
                    "Kcal / 100g": v.get("kcal_100g", 0),
                    "Proteine (g)": v.get("prot_100g", 0),
                    "Carbohidrați (g)": v.get("carb_100g", 0),
                    "Grăsimi (g)": v.get("gras_100g", 0),
                    "Data Salvării": v.get("data", "-")
                })
            st.dataframe(pd.DataFrame(rows_n), use_container_width=True, hide_index=True)
        else:
            st.caption("Nu ai scanat încă nicio etichetă nutrițională.")

    with sub_preturi:
        st.subheader("💰 Prețuri Reale Memorate din Bonurile Tale")
        preturi_db = st.session_state.db.get("preturi_magazine", {})
        rows_p = []
        for mag_k, prods_dict in preturi_db.items():
            for prod_k, p_info in prods_dict.items():
                rows_p.append({
                    "Magazin": mag_k,
                    "Produs": p_info.get("nume_afisat", prod_k),
                    "Preț Bon (RON)": p_info.get("pret", 0.0),
                    "Ambalaj / Cantitate": p_info.get("ambalaj", "1 buc"),
                    "Actualizat la": p_info.get("data", "-")
                })
        if rows_p:
            st.dataframe(pd.DataFrame(rows_p), use_container_width=True, hide_index=True)
            if st.button("🗑️ Resetează Istoricul de Prețuri", type="secondary"):
                st.session_state.db["preturi_magazine"] = {}
                save_local_db(st.session_state.db)
                st.rerun()
        else:
            st.info("Nu ai scanat încă niciun bon fiscal. Mergi în tab-ul 'Cumpărături' după ce vii de la magazin și încarcă o poză cu bonul!")

# ==========================================
# INJECȚIE JAVASCRIPT PT. CULORI BUTOANE
# ==========================================
components.html("""
<script>
    const observer = new MutationObserver(function() {
        const buttons = window.parent.document.querySelectorAll('button');
        buttons.forEach(b => {
            if(b.innerText.includes('250 ml')) {
                b.style.backgroundColor = '#09CEE6'; b.style.color = '#0B132B'; b.style.border = 'none';
            }
            if(b.innerText.includes('Am stagnat')) {
                b.style.backgroundColor = '#FFD54F'; b.style.color = '#0B132B'; b.style.border = 'none';
            }
            if(b.innerText.includes('❌') || b.innerText.includes('🗑️')) {
                b.style.backgroundColor = '#E53E3E'; b.style.color = 'white'; b.style.border = 'none';
            }
        });
    });
    observer.observe(window.parent.document.body, {childList: true, subtree: true});
</script>
""", height=0)