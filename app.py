import streamlit as st
import requests
import zipfile
import io
import pandas as pd
import re
from lxml import etree
from bs4 import BeautifulSoup

# ==========================================
# CONFIGURATION ET UI
# ==========================================
st.set_page_config(
    page_title="GIARDINI | Veille Parlementaire",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded"
)

def inject_custom_css(theme):
    if theme == "LIGHT":
        bg_color = "#F4F4F0"; bg_sec_color = "#EAEAE5"; text_color = "#1A1A1A"
        border_color = "#D2D2D2"; muted_color = "#777777"
    else:
        bg_color = "#000000"; bg_sec_color = "#0A0A0A"; text_color = "#FFFFFF"
        border_color = "#333333"; muted_color = "#666666"

    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Doto:wght@700;900&family=Space+Grotesk:wght@400;600;700&family=Space+Mono:ital,wght@0,400;0,700;1,400&display=swap');
    :root {{ --bg: {bg_color}; --bg-sec: {bg_sec_color}; --text: {text_color}; --border: {border_color}; --muted: {muted_color}; --accent: #D71921; }}
    html, body, [class*="css"], .stApp {{ font-family: 'Space Grotesk', sans-serif !important; background-color: var(--bg) !important; color: var(--text) !important; }}
    #MainMenu {{visibility: hidden;}} header {{visibility: hidden;}} footer {{visibility: hidden;}}
    div[data-testid="stDecoration"] {{display: none;}}
    .hero-title {{ font-family: 'Doto', sans-serif; font-size: 6vw; font-weight: 900; line-height: 0.9; letter-spacing: -2px; text-transform: uppercase; margin: 0; padding: 0; color: var(--text); }}
    .hero-subtitle {{ font-family: 'Space Mono', monospace; font-size: 14px; color: var(--accent); text-transform: uppercase; letter-spacing: 4px; margin-bottom: 40px; display: block; }}
    .tertiary-text {{ font-family: 'Space Mono', monospace; font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }}
    .red-accent {{ color: var(--accent) !important; }}
    div[data-testid="stExpander"] {{ background-color: var(--bg) !important; border: 1px solid var(--border) !important; border-radius: 0px !important; box-shadow: none !important; margin-bottom: 10px; }}
    div[data-testid="stExpander"] summary {{ font-family: 'Space Grotesk', sans-serif; font-weight: 600; color: var(--text) !important; }}
    div.stTextInput > div > div > input, div[data-baseweb="select"] > div {{ border-radius: 4px !important; border: 1px solid var(--border) !important; background-color: var(--bg-sec) !important; font-family: 'Space Mono', monospace !important; font-size: 13px !important; color: var(--text) !important; }}
    div.stTextInput > div > div > input:focus {{ border-color: var(--accent) !important; box-shadow: none !important; }}
    span[data-baseweb="tag"] {{ background-color: var(--accent) !important; color: #FFF !important; border-radius: 0px !important; border: none !important; font-family: 'Space Mono', monospace !important; font-size: 11px !important; }}
    label[data-testid="stWidgetLabel"] {{ display: none; }}
    div[role="radiogroup"] label {{ font-family: 'Space Mono', monospace !important; font-size: 12px !important; color: var(--text) !important; }}
    div.stButton > button {{ background-color: var(--bg-sec) !important; color: var(--text) !important; border: 1px solid var(--border) !important; border-radius: 4px !important; font-family: 'Space Mono', monospace !important; text-transform: uppercase; letter-spacing: 1px; font-size: 12px !important; }}
    div.stButton > button:hover {{ border-color: var(--accent) !important; color: var(--accent) !important; }}
    mark.industrial-highlight {{ background-color: transparent; color: var(--accent); font-weight: bold; border-bottom: 2px solid var(--accent); padding: 0 2px; }}
    ::-webkit-scrollbar {{ width: 8px; height: 8px; }}
    ::-webkit-scrollbar-track {{ background: var(--bg); }}
    ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 0px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: var(--accent); }}
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# UTILITAIRES COMMUNS
# ==========================================
def parse_french_date_to_sortable(datestr):
    months = {"janvier":"01","février":"02","mars":"03","avril":"04","mai":"05","juin":"06",
               "juillet":"07","août":"08","septembre":"09","octobre":"10","novembre":"11","décembre":"12"}
    match = re.search(r"(\d{1,2})\s+([a-zéû]+)\s+(\d{4})", datestr.lower())
    if match:
        return f"{match.group(3)}-{months.get(match.group(2), '00')}-{match.group(1).zfill(2)}"
    return "0000-00-00"

def search_and_highlight(df, acteurs, motscles):
    all_terms = [t.strip() for t in acteurs.split(',') + motscles.split(',') if t.strip()]
    if not all_terms:
        return df, []
    pattern = '|'.join(re.escape(t) for t in all_terms)
    regex = re.compile(f"({pattern})", flags=re.IGNORECASE)
    mask = df['Verbatim'].str.contains(pattern, case=False, na=False, regex=True)
    filtered_df = df[mask].copy()
    filtered_df['VerbatimHighlight'] = filtered_df['Verbatim'].apply(
        lambda x: regex.sub(r'<mark class="industrial-highlight">\1</mark>', str(x)))
    filtered_df['MotsTrouves'] = filtered_df['Verbatim'].apply(
        lambda x: ", ".join(list(set(m.lower() for m in regex.findall(str(x))))))
    return filtered_df, all_terms

def get_secret_key(secret_name, default_val):
    try:
        return st.secrets[secret_name]
    except (FileNotFoundError, KeyError):
        return default_val

# ==========================================
# MOTEUR 1 : ASSEMBLÉE NATIONALE (FRANCE)
# ==========================================
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_and_index_fr(url):
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        zip_bytes = response.content
    except Exception:
        return None, None
    catalog = {}
    regex_file = re.compile(r"(S\d+\.N\d*\.xml|CRSANR.*\.xml)", re.IGNORECASE)
    ns = {'an': 'http://schemas.assemblee-nationale.fr/referentiel'}
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            for filename in z.namelist():
                if regex_file.search(filename):
                    xml_content = z.read(filename)
                    root = etree.fromstring(xml_content)
                    date_nodes = root.xpath('//an:dateSeanceJour', namespaces=ns)
                    if date_nodes and date_nodes[0].text:
                        raw_date = date_nodes[0].text.strip()
                        sort_key = parse_french_date_to_sortable(raw_date)
                        if sort_key not in catalog:
                            catalog[sort_key] = {"label": raw_date, "files": []}
                        catalog[sort_key]["files"].append(filename)
    except zipfile.BadZipFile:
        return None, None
    return zip_bytes, dict(sorted(catalog.items(), key=lambda item: item[0], reverse=True))

@st.cache_data(show_spinner=False)
def parse_selected_dates_fr(zip_bytes, selected_dates_info):
    ns = {'an': 'http://schemas.assemblee-nationale.fr/referentiel'}
    data = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for sort_key, info in selected_dates_info.items():
            date_label = info['label']
            for filename in info['files']:
                xml_content = z.read(filename)
                root = etree.fromstring(xml_content)
                moment = "SÉANCE"
                titre_nodes = root.xpath('//an:ouverture/an:titre', namespaces=ns) or root.xpath('//an:titre', namespaces=ns)
                if titre_nodes and titre_nodes[0].text:
                    ts = titre_nodes[0].text.lower()
                    if "première" in ts: moment = "MATIN"
                    elif "deuxième" in ts: moment = "APRÈS-MIDI"
                    elif "troisième" in ts: moment = "NUIT"
                for para in root.xpath('.//an:paragraphe', namespaces=ns):
                    point_node = para.xpath('ancestor::an:point[1]/an:texte', namespaces=ns)
                    sujet = "".join(point_node[0].itertext()).strip() if point_node else "Sujet non défini"
                    rubrique_node = para.xpath('ancestor::an:point[1]//an:rubrique', namespaces=ns)
                    sequence = "".join(rubrique_node[0].itertext()).strip() if rubrique_node else "DÉBAT GÉNÉRAL"
                    orateur_node = para.xpath('.//an:orateurs/an:orateur/an:nom', namespaces=ns)
                    nom_orateur = orateur_node[0].text.strip() if orateur_node and orateur_node[0].text else "Assemblée"
                    qualite_node = para.xpath('.//an:orateurs/an:orateur/an:qualite', namespaces=ns)
                    qualite = qualite_node[0].text.strip() if qualite_node and qualite_node[0].text else "DÉPUTÉ.E"
                    texte_node = para.xpath('.//an:texte', namespaces=ns)
                    if not texte_node: continue
                    verbatim = "".join(texte_node[0].itertext()).strip()
                    if not verbatim: continue
                    italiques = para.xpath('.//an:texte//an:italique', namespaces=ns)
                    reactions = " | ".join([it.text.strip() for it in italiques if it.text and it.text.strip()])
                    data.append({
                        "DateSortKey": sort_key, "DateLabel": date_label, "Moment": moment.upper(),
                        "SujetDebat": sujet.upper(), "Sequence": sequence.upper(),
                        "NomOrateur": nom_orateur.upper(), "Qualite": qualite.upper(),
                        "Verbatim": verbatim, "Reactions": reactions
                    })
    return pd.DataFrame(data)

# ==========================================
# MOTEUR 2 : PARLEMENT EUROPÉEN (UE)
# ==========================================
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_and_index_eu():
    try:
        url = "https://data.europarl.europa.eu/api/v2/plenary-session-documents"
        params = {"work_type": "def/ep-document-types/CRE_PLENARY", "limit": 1000}
        headers = {"Accept": "application/ld+json"}
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json().get("data", [])
    except Exception:
        return None, None
    catalog = {}
    for doc in data:
        doc_id = doc.get("identifier", "") 
        if not doc_id or not doc_id.startswith("CRE-"): continue
        parts = doc_id.split("-")
        if len(parts) >= 5:
            try:
                year, month, day = parts[2], parts[3], parts[4]
                sort_key = f"{year}-{month}-{day}"
                date_label = f"{day}/{month}/{year}"
                if sort_key not in catalog:
                    catalog[sort_key] = {"label": date_label, "files": [doc_id]}
                else:
                    catalog[sort_key]["files"].append(doc_id)
            except Exception:
                continue
    return b"eu_placeholder", dict(sorted(catalog.items(), key=lambda item: item[0], reverse=True))

@st.cache_data(show_spinner=False)
def parse_selected_dates_eu(dummy, selected_dates_info):
    data = []
    for sort_key, info in selected_dates_info.items():
        date_label = info['label']
        for doc_id in info['files']:
            xml_url = f"https://www.europarl.europa.eu/doceo/document/{doc_id}_FR.xml"
            try:
                resp = requests.get(xml_url, timeout=30)
                if resp.status_code != 200: continue
                root = etree.fromstring(resp.content)
            except Exception:
                continue
            for intervention in root.xpath('//INTERVENTION'):
                orateur_node = intervention.xpath('.//ORATEUR')
                if orateur_node:
                    nom = orateur_node[0].attrib.get('LIB', 'INCONNU').replace(' | ', ' ').upper()
                    groupe = orateur_node[0].attrib.get('PP', 'GROUPE N/A').upper()
                else:
                    nom = "ASSEMBLÉE"
                    groupe = "PLÉNIÈRE"
                paras = intervention.xpath('.//PARA')
                verbatim = " ".join(["".join(p.itertext()).strip() for p in paras]).strip()
                if not verbatim: continue
                chapter_title = intervention.xpath('ancestor::CHAPTER/TITLE/text()')
                sujet = chapter_title[0].strip().upper() if chapter_title else "DÉBAT DE PLÉNIÈRE"
                agenda_point = intervention.xpath('ancestor::AGENDA-POINT/@number')
                sequence = f"POINT {agenda_point[0]}" if agenda_point else "N/A"
                italiques = intervention.xpath('.//I | .//i')
                reactions = " | ".join(["".join(it.itertext()).strip() for it in italiques if "".join(it.itertext()).strip()])
                data.append({
                    "DateSortKey": sort_key, "DateLabel": date_label, "Moment": "PLÉNIÈRE",
                    "SujetDebat": sujet, "Sequence": sequence, "NomOrateur": nom,
                    "Qualite": groupe, "Verbatim": verbatim, "Reactions": reactions
                })
    return pd.DataFrame(data)

# ==========================================
# MOTEUR 3 : CONGRÈS AMÉRICAIN (US)
# ==========================================
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_and_index_us():
    api_key = get_secret_key("CONGRESS_API_KEY", "DEMO_KEY")
    url = "https://api.congress.gov/v3/daily-congressional-record"
    params = {"api_key": api_key, "limit": 100, "format": "json"}
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        issues = response.json().get("dailyCongressionalRecord", [])
    except Exception:
        return None, None

    catalog = {}
    for issue in issues:
        date_raw = issue.get("issueDate", "")[:10]
        if not date_raw: continue
        vol = str(issue.get("volumeNumber", ""))
        num = str(issue.get("issueNumber", ""))
        
        parts = date_raw.split("-")
        date_label = f"{parts[2]}/{parts[1]}/{parts[0]}" if len(parts) == 3 else date_raw
        
        if date_raw not in catalog:
            catalog[date_raw] = {"label": f"{date_label} (Vol.{vol} No.{num})", "files": [f"{vol}/{num}"]}
        else:
            catalog[date_raw]["files"].append(f"{vol}/{num}")
            
    return b"us_placeholder", dict(sorted(catalog.items(), key=lambda item: item[0], reverse=True))

@st.cache_data(show_spinner=False)
def parse_selected_dates_us(dummy, selected_dates_info):
    api_key = get_secret_key("CONGRESS_API_KEY", "DEMO_KEY")
    data = []
    
    for sort_key, info in selected_dates_info.items():
        date_label = info['label'].split(" ")[0]
        for file_id in info['files']:
            vol, num = file_id.split('/')
            art_url = f"https://api.congress.gov/v3/daily-congressional-record/{vol}/{num}/articles"
            try:
                resp = requests.get(art_url, params={"api_key": api_key, "format": "json"}, timeout=30)
                if resp.status_code != 200: continue
                articles = resp.json().get('articles', [])
            except Exception:
                continue
                
            for section in articles:
                chamber = section.get('name', 'SECTION UNKNOWN')
                for article in section.get('sectionArticles', []):
                    title = article.get('title', 'DEBATE')
                    for text_item in article.get('text', []):
                        if text_item.get('type') == 'Formatted Text':
                            try:
                                htm_resp = requests.get(text_item['url'], timeout=30)
                                if htm_resp.status_code != 200: continue
                                
                                soup = BeautifulSoup(htm_resp.content, 'html.parser')
                                paras = soup.find_all('p')
                                
                                if paras:
                                    verbatim = " \n".join([p.get_text().strip() for p in paras if p.get_text().strip()])
                                else:
                                    pre = soup.find('pre')
                                    verbatim = pre.get_text().strip() if pre else soup.get_text().strip()
                                
                                if not verbatim: continue
                                
                                nom_orateur = "CONGRESS MEMBER"
                                speaker_match = re.search(r'^\s*(?:Mr\.|Ms\.|Mrs\.|The\s[A-Z\s]+)\s+([A-Za-z\s\.\'-]+)\.', verbatim)
                                if speaker_match:
                                    nom_orateur = speaker_match.group(0).strip(' .')
                                    
                                data.append({
                                    "DateSortKey": sort_key,
                                    "DateLabel": date_label,
                                    "Moment": chamber.upper(),
                                    "SujetDebat": title.upper(),
                                    "Sequence": f"VOL.{vol} NO.{num}",
                                    "NomOrateur": nom_orateur.upper(),
                                    "Qualite": chamber.replace(" Section", "").upper(),
                                    "Verbatim": verbatim,
                                    "Reactions": ""
                                })
                            except Exception:
                                continue
    return pd.DataFrame(data)

# ==========================================
# EXPORT HTML
# ==========================================
def generate_html_export(df, theme, institution):
    bg_color = "#F4F4F0" if theme == "LIGHT" else "#000000"
    text_color = "#1A1A1A" if theme == "LIGHT" else "#FFFFFF"
    border_color = "#D2D2D2" if theme == "LIGHT" else "#333333"
    dates_header = ", ".join(df['DateLabel'].unique())
    
    if "UE" in institution:
        source_label = "PARLEMENT EUROPÉEN"
    elif "US" in institution:
        source_label = "CONGRÈS AMÉRICAIN"
    else:
        source_label = "ASSEMBLÉE NATIONALE"
        
    html = f"""<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8">
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;700&family=Space+Mono&display=swap');
    body {{ font-family: 'Space Grotesk', sans-serif; background: {bg_color}; color: {text_color}; padding: 40px; max-width: 900px; margin: 0 auto; }}
    h1 {{ font-family: 'Space Mono', monospace; font-size: 14px; color: #D71921; text-transform: uppercase; letter-spacing: 2px; border-bottom: 1px solid {border_color}; padding-bottom: 20px; }}
    .item {{ border: 1px solid {border_color}; padding: 24px; margin-bottom: 20px; }}
    .orateur {{ font-family: 'Space Mono', monospace; color: #D71921; font-weight: bold; margin-bottom: 4px; font-size: 14px; }}
    .metadata {{ font-family: 'Space Mono', monospace; color: #888; font-size: 10px; margin-bottom: 16px; text-transform: uppercase; border-bottom: 1px dashed {border_color}; padding-bottom: 12px; }}
    .verbatim {{ font-size: 16px; line-height: 1.6; text-align: justify; }}
    mark {{ background: transparent; color: #D71921; border-bottom: 2px solid #D71921; font-weight: bold; padding: 0 2px; }}
    .reactions {{ font-family: 'Space Mono', monospace; color: #888; font-size: 10px; margin-top: 20px; }}
    </style></head><body>
    <h1>GIARDINI EXPORT // {source_label} // {dates_header} // {len(df)} MENTIONS</h1>"""
    
    for _, row in df.iterrows():
        html += f"""<div class="item">
            <div class="orateur">{row['NomOrateur']} [{row['Qualite']}]</div>
            <div class="metadata">DATE: {row['DateLabel']} ({row['Moment']}) <br> SUJET: {row['SujetDebat']} <br> SÉQUENCE: {row['Sequence']}</div>
            <div class="verbatim">{row['VerbatimHighlight']}</div>"""
        if row['Reactions']:
            html += f'<div class="reactions">RX: {row["Reactions"]}</div>'
        html += "</div>"
    html += "</body></html>"
    return html

# ==========================================
# APPLICATION PRINCIPALE (MAIN)
# ==========================================
def main():
    if 'ui_theme' not in st.session_state:
        st.session_state.ui_theme = "DARK"
    inject_custom_css(st.session_state.ui_theme)

    st.markdown('<div class="hero-title">GIARDINI</div>', unsafe_allow_html=True)
    st.markdown('<span class="hero-subtitle">Veille des Comptes Rendus In Extenso (CRE)</span>', unsafe_allow_html=True)

    # --- SIDEBAR ---
    st.sidebar.markdown('<div class="tertiary-text red-accent">[ PARAMÈTRES UI ]</div>', unsafe_allow_html=True)
    theme_choice = st.sidebar.radio("THÈME", ["DARK", "LIGHT"], index=0 if st.session_state.ui_theme == "DARK" else 1, horizontal=True)
    if theme_choice != st.session_state.ui_theme:
        st.session_state.ui_theme = theme_choice
        st.rerun()

    st.sidebar.markdown('<br><div class="tertiary-text red-accent">[ SOURCE DES DONNÉES ]</div>', unsafe_allow_html=True)
    institution = st.sidebar.radio("INSTITUTION", ["ASSEMBLÉE NATIONALE (FR)", "PARLEMENT EUROPÉEN (UE)", "CONGRÈS AMÉRICAIN (US)"])

    # --- CHARGEMENT DES DONNÉES ---
    with st.spinner(f"SYNCHRONISATION ({institution.split('(')[1].replace(')','')})..."):
        if "FR" in institution:
            url = "https://data.assemblee-nationale.fr/static/openData/repository/17/vp/syceronbrut/syseron.xml.zip"
            source_bytes, catalog = fetch_and_index_fr(url)
        elif "UE" in institution:
            source_bytes, catalog = fetch_and_index_eu()
        else:
            source_bytes, catalog = fetch_and_index_us()

    if not source_bytes or not catalog:
        st.markdown('<div class="tertiary-text red-accent">ERROR: SOURCE DE DONNÉES INACCESSIBLE OU CLÉ API INVALIDE</div>', unsafe_allow_html=True)
        st.stop()

    st.sidebar.markdown('<br><div class="tertiary-text red-accent">[ DATES DES SÉANCES ]</div>', unsafe_allow_html=True)
    selected_date_keys = st.sidebar.multiselect(
        "DATES",
        options=list(catalog.keys()),
        default=[list(catalog.keys())[0]] if catalog else [],
        format_func=lambda x: catalog[x]['label'].upper()
    )
    
    if not selected_date_keys:
        st.markdown('<div class="tertiary-text red-accent">SYS.HALT: VEUILLEZ SÉLECTIONNER AU MOINS UNE DATE.</div>', unsafe_allow_html=True)
        st.stop()

    st.sidebar.markdown('<br><div class="tertiary-text red-accent">[ MOTEUR DE RECHERCHE ]</div>', unsafe_allow_html=True)
    acteurs_input = st.sidebar.text_input("ACTEURS", placeholder="EX: MACRON, BIDEN, SCHUMER")
    mots_input = st.sidebar.text_input("MOTS-CLÉS", placeholder="EX: NUCLÉAIRE, TAXONOMIE, TAX")

    # --- PARSING ---
    selected_dates_info = {k: catalog[k] for k in selected_date_keys}
    with st.spinner("PARSING DES DONNÉES..."):
        if "FR" in institution:
            df = parse_selected_dates_fr(source_bytes, selected_dates_info)
        elif "UE" in institution:
            df = parse_selected_dates_eu(source_bytes, selected_dates_info)
        else:
            df = parse_selected_dates_us(source_bytes, selected_dates_info)

    st.markdown(f'<div class="tertiary-text">SYS.STATUS: {len(selected_date_keys)} DATES EN MÉMOIRE | {len(df)} ENTRÉES PARSÉES.</div><br>', unsafe_allow_html=True)

    if df.empty:
        st.markdown('<div class="tertiary-text red-accent">NULL: AUCUNE DONNÉE DISPONIBLE POUR CETTE SÉLECTION.</div>', unsafe_allow_html=True)
        st.stop()

    # --- RECHERCHE ---
    filtered_df, search_terms = search_and_highlight(df, acteurs_input, mots_input)
    selected_indices = [
        idx for idx in filtered_df.index
        if st.session_state.get(f"chk_{filtered_df.loc[idx, 'DateSortKey']}_{idx}", False)
    ]

    # --- LAYOUT ---
    col_data, col_meta = st.columns([3, 1])

    with col_meta:
        st.markdown('<div class="tertiary-text">MÉTRIQUES</div>', unsafe_allow_html=True)
        st.markdown(f'<div style="font-family: Doto, sans-serif; font-size: 48px; line-height: 1;">{len(filtered_df)}</div>', unsafe_allow_html=True)
        st.markdown('<div class="tertiary-text">OCCURRENCES TROUVÉES</div><br>', unsafe_allow_html=True)

        # --- NOUVEAU GRAPHIQUE BAR CHART ---
        if len(filtered_df) > 0 and len(search_terms) > 0:
            st.markdown('<br><div class="tertiary-text">[ ÉVOLUTION TEMPORELLE ]</div>', unsafe_allow_html=True)
            
            # Agrégation des mentions par date (utilisation de DateLabel pour que l'axe X soit joli (ex: 23/04/2026))
            chart_data = filtered_df.groupby('DateLabel').size().reset_index(name='Mentions')
            
            # Convertir l'index pour Streamlit (l'index devient l'axe X du graphique)
            chart_data = chart_data.set_index('DateLabel')
            
            # Affichage du bar chart
            st.bar_chart(data=chart_data, y="Mentions", color="#D71921", height=250)

        if search_terms and len(selected_indices) > 0:
            st.markdown('<div class="tertiary-text">[ EXPORT SÉLECTIF ]</div><br>', unsafe_allow_html=True)
            df_to_export = filtered_df.loc[selected_indices]
            html_export = generate_html_export(df_to_export, st.session_state.ui_theme, institution)
            suffix = "US" if "US" in institution else ("UE" if "UE" in institution else "FR")
            filename = f"giardini_export_{suffix}_{len(selected_date_keys)}DATES.html"
            st.download_button("EXPORTER SÉLECTION (HTML)", data=html_export, file_name=filename, mime="text/html", type="primary")

    with col_data:
        if not search_terms:
            st.markdown('<div class="tertiary-text">WAITING FOR INPUT: VEUILLEZ SAISIR UNE REQUÊTE DANS LE PANNEAU DE CONTRÔLE.</div>', unsafe_allow_html=True)
        elif filtered_df.empty:
            st.markdown('<div class="tertiary-text red-accent">NULL: AUCUNE CORRESPONDANCE TROUVÉE.</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="tertiary-text">RÉSULTATS (Cochez pour exporter)</div><br>', unsafe_allow_html=True)
            
            for idx, row in filtered_df.iterrows():
                expander_title = f"{row['DateLabel']} | {row['NomOrateur']} ({row['Qualite']}) | {str(row['Sequence'])[:40]}..."
                
                with st.expander(expander_title, expanded=False):
                    chk_key = f"chk_{row['DateSortKey']}_{idx}"
                    st.checkbox("INCLURE DANS L'EXPORT", key=chk_key)
                    st.markdown("---")
                    
                    st.markdown(f"""
                        <div class="tertiary-text" style="line-height: 1.8;">
                        DATE &nbsp;&nbsp;&nbsp;&nbsp;: {row['DateLabel']} (SÉANCE : {row['Moment']})<br>
                        RÔLE &nbsp;&nbsp;&nbsp;&nbsp;: <span class="red-accent">{row['Qualite']}</span><br>
                        SUJET &nbsp;&nbsp;&nbsp;: {row['SujetDebat']}<br>
                        SÉQUENCE: {row['Sequence']}<br>
                        DÉTECTION: <span class="red-accent">{row['MotsTrouves'].upper()}</span>
                        </div><br>
                    """, unsafe_allow_html=True)
                    
                    st.markdown(f'<div style="line-height: 1.6; text-align: justify;">{row["VerbatimHighlight"]}</div>', unsafe_allow_html=True)
                    if row['Reactions']:
                        st.markdown(f'<br><div class="tertiary-text">RX: {row["Reactions"]}</div>', unsafe_allow_html=True)

if __name__ == '__main__':
    main()
