import io
import re
import time
import zipfile
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from lxml import etree


# =========================================================
# CONFIGURATION
# =========================================================
st.set_page_config(
 page_title="GIARDINI | Veille parlementaire",
 page_icon="🏛️",
 layout="wide",
 initial_sidebar_state="expanded",
)

AN_TRANSCRIPTS_URL = (
 "https://data.assemblee-nationale.fr/static/openData/"
 "repository/17/vp/syceronbrut/syseron.xml.zip"
)

AN_AGENDA_URL = "https://www.assemblee-nationale.fr/agendas/index.asp"

BROWSER_HEADERS = {
 "User-Agent": (
 "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
 "AppleWebKit/537.36 (KHTML, like Gecko) "
 "Chrome/124.0.0.0 Safari/537.36"
 ),
 "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
 "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

MONTHS_FR = {
 "janvier": 1,
 "février": 2,
 "mars": 3,
 "avril": 4,
 "mai": 5,
 "juin": 6,
 "juillet": 7,
 "août": 8,
 "septembre": 9,
 "octobre": 10,
 "novembre": 11,
 "décembre": 12,
}

AGENDA_COLUMNS = [
 "EventId",
 "Date",
 "Heure",
 "Type",
 "Instance",
 "Titre",
 "Statut",
 "SourceUrl",
 "SourceUpdatedAt",
]

PLF_COLUMNS = [
 "EventId",
 "Date",
 "Etape",
 "Instance",
 "Titre",
 "Statut",
 "SourceUrl",
 "SourceUpdatedAt",
]


# =========================================================
# UI
# =========================================================
def inject_custom_css(theme: str) -> None:
 light = theme == "LIGHT"

 bg = "#F4F4F0" if light else "#000000"
 bg_secondary = "#EAEAE5" if light else "#0A0A0A"
 text = "#1A1A1A" if light else "#FFFFFF"
 border = "#D2D2D2" if light else "#333333"
 muted = "#777777"

 st.markdown(
 f"""
 <style>
 @import url('https://fonts.googleapis.com/css2?family=Doto:wght@700;900&family=Space+Grotesk:wght@400;600;700&family=Space+Mono:ital,wght@0,400;0,700;1,400&display=swap');

 :root {{
 --bg: {bg};
 --bg-secondary: {bg_secondary};
 --text: {text};
 --border: {border};
 --muted: {muted};
 --accent: #D71921;
 }}

 html, body, [class*="css"], .stApp {{
 font-family: 'Space Grotesk', sans-serif !important;
 background-color: var(--bg) !important;
 color: var(--text) !important;
 }}

 #MainMenu, header, footer {{
 visibility: hidden;
 }}

 .hero-title {{
 font-family: 'Doto', sans-serif;
 font-size: 6vw;
 font-weight: 900;
 line-height: 0.9;
 letter-spacing: -2px;
 text-transform: uppercase;
 color: var(--text);
 }}

 .hero-subtitle {{
 font-family: 'Space Mono', monospace;
 font-size: 14px;
 color: var(--accent);
 text-transform: uppercase;
 letter-spacing: 4px;
 margin-bottom: 28px;
 display: block;
 }}

 .tertiary {{
 font-family: 'Space Mono', monospace;
 font-size: 11px;
 color: var(--muted);
 text-transform: uppercase;
 letter-spacing: 1px;
 }}

 .accent {{
 color: var(--accent) !important;
 }}

 div[data-testid="stExpander"] {{
 border: 1px solid var(--border) !important;
 border-radius: 0 !important;
 background-color: var(--bg) !important;
 }}

 div.stTextInput input,
 div[data-baseweb="select"] > div {{
 background-color: var(--bg-secondary) !important;
 color: var(--text) !important;
 border-color: var(--border) !important;
 }}

 mark.industrial-highlight {{
 background-color: transparent;
 color: var(--accent);
 border-bottom: 2px solid var(--accent);
 font-weight: 700;
 }}
 </style>
 """,
 unsafe_allow_html=True,
 )


# =========================================================
# UTILITAIRES
# =========================================================
def clean_text(value: str) -> str:
 return re.sub(r"\s+", " ", value or "").strip()


def extract_french_date(text: str) -> date | None:
 match = re.search(
 r"\b(\d{1,2})\s+"
 r"(janvier|février|mars|avril|mai|juin|juillet|août|"
 r"septembre|octobre|novembre|décembre)\s+"
 r"(20\d{2})\b",
 text.lower(),
 )

 if not match:
 return None

 day, month_name, year = match.groups()

 try:
 return date(int(year), MONTHS_FR[month_name], int(day))
 except ValueError:
 return None


def parse_french_date_to_sortable(value: str) -> str:
 parsed = extract_french_date(value)
 return parsed.isoformat() if parsed else "0000-00-00"


def extract_time(text: str) -> str:
 match = re.search(r"\b(\d{1,2})\s*h(?:\s*(\d{2}))?\b", text.lower())

 if not match:
 return ""

 hour = int(match.group(1))
 minute = int(match.group(2) or 0)

 return f"{hour:02d}:{minute:02d}"


def request_html(url: str) -> BeautifulSoup:
 response = requests.get(
 url,
 headers=BROWSER_HEADERS,
 timeout=30,
 )
 response.raise_for_status()

 return BeautifulSoup(response.text, "html.parser")


def download_with_resume(
 url: str,
 max_retries: int = 10,
 chunk_size: int = 512 * 1024,
) -> bytes:
 """
 Télécharge l'archive XML de l'Assemblée avec reprise HTTP Range.
 Le CDN peut interrompre les téléchargements longs.
 """
 buffer = bytearray()

 head = requests.head(
 url,
 headers=BROWSER_HEADERS,
 timeout=30,
 )
 head.raise_for_status()

 total_size = int(head.headers.get("Content-Length", 0))
 accepts_ranges = (
 head.headers.get("Accept-Ranges", "none").lower() != "none"
 )

 for attempt in range(max_retries):
 offset = len(buffer)

 if total_size and offset >= total_size:
 return bytes(buffer)

 headers = dict(BROWSER_HEADERS)

 if accepts_ranges and offset > 0:
 headers["Range"] = f"bytes={offset}-"

 try:
 response = requests.get(
 url,
 headers=headers,
 stream=True,
 timeout=60,
 )
 response.raise_for_status()

 if response.status_code == 200 and offset > 0:
 buffer = bytearray()

 for chunk in response.iter_content(chunk_size=chunk_size):
 if chunk:
 buffer.extend(chunk)

 return bytes(buffer)

 except (
 requests.exceptions.ChunkedEncodingError,
 requests.exceptions.ConnectionError,
 requests.exceptions.ReadTimeout,
 ):
 if attempt == max_retries - 1:
 raise

 time.sleep(2 ** (attempt + 1))

 return bytes(buffer)


# =========================================================
# MOTEUR DE RECHERCHE BOOLÉEN
# =========================================================
class BooleanQueryError(Exception):
 pass


def tokenize(query: str) -> list[tuple[str, str]]:
 tokens = []
 position = 0

 while position < len(query):
 char = query[position]

 if char.isspace():
 position += 1
 continue

 if char in "()":
 tokens.append(
 ("LPAREN" if char == "(" else "RPAREN", char)
 )
 position += 1
 continue

 if char == '"':
 end = query.find('"', position + 1)

 if end == -1:
 raise BooleanQueryError("Guillemet fermant manquant.")

 tokens.append(("TERM", query[position + 1:end]))
 position = end + 1
 continue

 if char == "-" and (
 position == 0 or query[position - 1].isspace()
 ):
 tokens.append(("NOT", "NOT"))
 position += 1
 continue

 end = position

 while (
 end < len(query)
 and not query[end].isspace()
 and query[end] not in '()"'
 ):
 end += 1

 value = query[position:end]
 upper = value.upper()

 token_type = (
 upper
 if upper in {"AND", "OR", "NOT"}
 else "TERM"
 )

 tokens.append((token_type, value))
 position = end

 tokens.append(("EOF", ""))

 return tokens


class BooleanParser:
 def __init__(self, tokens: list[tuple[str, str]]):
 self.tokens = tokens
 self.position = 0

 def peek(self) -> str:
 return self.tokens[self.position][0]

 def consume(
 self,
 expected: str | None = None,
 ) -> tuple[str, str]:
 token = self.tokens[self.position]

 if expected and token[0] != expected:
 raise BooleanQueryError(
 f"Attendu : {expected}. Trouvé : {token[1]}."
 )

 self.position += 1

 return token

 def parse(self):
 node = self.parse_or()

 if self.peek() != "EOF":
 raise BooleanQueryError("Requête booléenne mal formée.")

 return node

 def parse_or(self):
 node = self.parse_and()

 while self.peek() == "OR":
 self.consume("OR")
 node = ("OR", node, self.parse_and())

 return node

 def parse_and(self):
 node = self.parse_not()

 while self.peek() not in {"OR", "RPAREN", "EOF"}:
 if self.peek() == "AND":
 self.consume("AND")

 node = ("AND", node, self.parse_not())

 return node

 def parse_not(self):
 if self.peek() == "NOT":
 self.consume("NOT")
 return ("NOT", self.parse_not())

 if self.peek() == "LPAREN":
 self.consume("LPAREN")
 node = self.parse_or()
 self.consume("RPAREN")
 return node

 if self.peek() == "TERM":
 return ("TERM", self.consume("TERM")[1])

 raise BooleanQueryError("Terme ou parenthèse attendu.")


def evaluate_ast(node, text: str) -> bool:
 kind = node[0]

 if kind == "TERM":
 return bool(
 re.search(
 re.escape(node[1]),
 text,
 re.IGNORECASE,
 )
 )

 if kind == "AND":
 return (
 evaluate_ast(node[1], text)
 and evaluate_ast(node[2], text)
 )

 if kind == "OR":
 return (
 evaluate_ast(node[1], text)
 or evaluate_ast(node[2], text)
 )

 if kind == "NOT":
 return not evaluate_ast(node[1], text)

 return False


def positive_terms(node) -> list[str]:
 kind = node[0]

 if kind == "TERM":
 return [node[1]]

 if kind == "NOT":
 return []

 return positive_terms(node[1]) + positive_terms(node[2])


def boolean_search_and_highlight(
 df: pd.DataFrame,
 query: str,
):
 if not query.strip():
 return df.iloc[0:0].copy(), [], None

 try:
 ast = BooleanParser(tokenize(query)).parse()

 except BooleanQueryError as error:
 return df.iloc[0:0].copy(), [], str(error)

 filtered = df[
 df["Verbatim"].astype(str).apply(
 lambda text: evaluate_ast(ast, text)
 )
 ].copy()

 terms = list(dict.fromkeys(positive_terms(ast)))

 if not terms:
 filtered["VerbatimHighlight"] = filtered["Verbatim"]
 filtered["MotsTrouves"] = ""

 return filtered, terms, None

 pattern = re.compile(
 "(" + "|".join(re.escape(term) for term in terms) + ")",
 re.IGNORECASE,
 )

 filtered["VerbatimHighlight"] = (
 filtered["Verbatim"]
 .astype(str)
 .apply(
 lambda text: pattern.sub(
 r'<mark class="industrial-highlight">\1</mark>',
 text,
 )
 )
 )

 filtered["MotsTrouves"] = (
 filtered["Verbatim"]
 .astype(str)
 .apply(
 lambda text: ", ".join(
 dict.fromkeys(
 match.lower()
 for match in pattern.findall(text)
 )
 )
 )
 )

 return filtered, terms, None


# =========================================================
# COMPTES RENDUS — ARCHIVE XML ASSEMBLÉE NATIONALE
# =========================================================
@st.cache_data(ttl=12 * 3600, show_spinner=False)
def fetch_and_index_fr(url: str):
 zip_bytes = download_with_resume(url)

 catalog = {}
 file_pattern = re.compile(
 r"(S\d+\.N\d*\.xml|CRSANR.*\.xml)",
 re.IGNORECASE,
 )

 namespace = {
 "an": "http://schemas.assemblee-nationale.fr/referentiel"
 }

 with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
 for filename in archive.namelist():
 if not file_pattern.search(filename):
 continue

 root = etree.fromstring(archive.read(filename))

 date_nodes = root.xpath(
 "//an:dateSeanceJour",
 namespaces=namespace,
 )

 if not date_nodes or not date_nodes[0].text:
 continue

 label = date_nodes[0].text.strip()
 sort_key = parse_french_date_to_sortable(label)

 catalog.setdefault(
 sort_key,
 {
 "label": label,
 "files": [],
 },
 )["files"].append(filename)

 return zip_bytes, dict(sorted(catalog.items(), reverse=True))


@st.cache_data(show_spinner=False)
def parse_selected_dates_fr(
 zip_bytes: bytes,
 selected_dates_info: dict,
) -> pd.DataFrame:
 namespace = {
 "an": "http://schemas.assemblee-nationale.fr/referentiel"
 }

 rows = []

 with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
 for sort_key, info in selected_dates_info.items():
 for filename in info["files"]:
 root = etree.fromstring(archive.read(filename))

 title_nodes = root.xpath(
 "//an:ouverture/an:titre",
 namespaces=namespace,
 )

 title = (
 clean_text("".join(title_nodes[0].itertext()))
 if title_nodes
 else ""
 )

 lower_title = title.lower()

 if "première" in lower_title:
 moment = "MATIN"
 elif "deuxième" in lower_title:
 moment = "APRÈS-MIDI"
 elif "troisième" in lower_title:
 moment = "NUIT"
 else:
 moment = "SÉANCE"

 for paragraph in root.xpath(
 ".//an:paragraphe",
 namespaces=namespace,
 ):
 text_nodes = paragraph.xpath(
 ".//an:texte",
 namespaces=namespace,
 )

 if not text_nodes:
 continue

 verbatim = clean_text(
 "".join(text_nodes[0].itertext())
 )

 if not verbatim:
 continue

 point = paragraph.xpath(
 "ancestor::an:point[1]",
 namespaces=namespace,
 )

 subject_nodes = (
 point[0].xpath(
 "./an:texte",
 namespaces=namespace,
 )
 if point
 else []
 )

 sequence_nodes = (
 point[0].xpath(
 ".//an:rubrique",
 namespaces=namespace,
 )
 if point
 else []
 )

 speaker_nodes = paragraph.xpath(
 ".//an:orateurs/an:orateur/an:nom",
 namespaces=namespace,
 )

 quality_nodes = paragraph.xpath(
 ".//an:orateurs/an:orateur/an:qualite",
 namespaces=namespace,
 )

 italic_nodes = paragraph.xpath(
 ".//an:texte//an:italique",
 namespaces=namespace,
 )

 rows.append(
 {
 "DateSortKey": sort_key,
 "DateLabel": info["label"],
 "Moment": moment,
 "SujetDebat": (
 clean_text(
 "".join(
 subject_nodes[0].itertext()
 )
 ).upper()
 if subject_nodes
 else "SUJET NON DÉFINI"
 ),
 "Sequence": (
 clean_text(
 "".join(
 sequence_nodes[0].itertext()
 )
 ).upper()
 if sequence_nodes
 else "DÉBAT GÉNÉRAL"
 ),
 "NomOrateur": (
 clean_text(
 speaker_nodes[0].text
 ).upper()
 if speaker_nodes
 and speaker_nodes[0].text
 else "ASSEMBLÉE"
 ),
 "Qualite": (
 clean_text(
 quality_nodes[0].text
 ).upper()
 if quality_nodes
 and quality_nodes[0].text
 else "DÉPUTÉ.E"
 ),
 "Verbatim": verbatim,
 "Reactions": " | ".join(
 clean_text(node.text)
 for node in italic_nodes
 if node.text
 ),
 }
 )

 return pd.DataFrame(rows)


# =========================================================
# AGENDA À VENIR — ASSEMBLÉE NATIONALE
# =========================================================
def classify_agenda_event(text: str) -> str:
 lower = text.lower()

 if "séance publique" in lower:
 return "SÉANCE PUBLIQUE"

 if "conférence des présidents" in lower:
 return "CONFÉRENCE DES PRÉSIDENTS"

 if "commission" in lower:
 return "COMMISSION"

 if "réunion" in lower:
 return "RÉUNION"

 return "AGENDA"


def extract_instance(text: str) -> str:
 lower = text.lower()

 instances = {
 "commission des finances": "COMMISSION DES FINANCES",
 "commission des affaires économiques": (
 "COMMISSION DES AFFAIRES ÉCONOMIQUES"
 ),
 "commission des affaires sociales": (
 "COMMISSION DES AFFAIRES SOCIALES"
 ),
 "commission des lois": "COMMISSION DES LOIS",
 "commission du développement durable": (
 "COMMISSION DU DÉVELOPPEMENT DURABLE"
 ),
 "conférence des présidents": (
 "CONFÉRENCE DES PRÉSIDENTS"
 ),
 }

 for keyword, label in instances.items():
 if keyword in lower:
 return label

 return "ASSEMBLÉE NATIONALE"


@st.cache_data(ttl=60 * 60, show_spinner=False)
def fetch_agenda_fr(
 lookahead_days: int = 90,
) -> pd.DataFrame:
 """
 Récupère les séances et réunions futures depuis la page Agenda.
 Le parser est volontairement tolérant car le HTML de l'AN peut évoluer.
 """
 soup = request_html(AN_AGENDA_URL)

 today = date.today()
 limit = today + timedelta(days=lookahead_days)

 rows = []
 seen = set()

 candidates = soup.select(
 "article, li, tr, .agenda-item, .event, .item, section"
 )

 for candidate in candidates:
 text = clean_text(
 candidate.get_text(" ", strip=True)
 )

 event_date = extract_french_date(text)

 if not event_date:
 continue

 if not today <= event_date <= limit:
 continue

 if not any(
 keyword in text.lower()
 for keyword in (
 "séance",
 "réunion",
 "commission",
 "conférence des présidents",
 )
 ):
 continue

 title_node = candidate.select_one(
 "h1, h2, h3, h4, .title, a"
 )

 title = (
 clean_text(title_node.get_text(" ", strip=True))
 if title_node
 else text[:240]
 )

 link_node = candidate.select_one("a[href]")

 source_url = (
 urljoin(AN_AGENDA_URL, link_node["href"])
 if link_node
 else AN_AGENDA_URL
 )

 event_id = (
 f"{event_date.isoformat()}|{source_url}|{title}"
 ).lower()

 if event_id in seen:
 continue

 seen.add(event_id)

 rows.append(
 {
 "EventId": event_id,
 "Date": event_date.isoformat(),
 "Heure": extract_time(text),
 "Type": classify_agenda_event(text),
 "Instance": extract_instance(text),
 "Titre": title,
 "Statut": "PRÉVUE",
 "SourceUrl": source_url,
 "SourceUpdatedAt": datetime.utcnow().isoformat(
 timespec="seconds"
 ),
 }
 )

 agenda = pd.DataFrame(rows, columns=AGENDA_COLUMNS)

 if agenda.empty:
 return agenda

 return (
 agenda
 .drop_duplicates("EventId")
 .sort_values(["Date", "Heure"])
 .reset_index(drop=True)
 )


# =========================================================
# DOSSIER LÉGISLATIF — PLF 2027
# =========================================================
def classify_plf_step(text: str) -> str:
 lower = text.lower()

 mapping = [
 ("conseil constitutionnel", "CONSEIL CONSTITUTIONNEL"),
 ("commission mixte paritaire", "CMP"),
 ("promulgation", "PROMULGATION"),
 ("séance publique", "SÉANCE PUBLIQUE"),
 ("commission des finances", "COMMISSION DES FINANCES"),
 ("amendement", "AMENDEMENTS"),
 ("rapport", "RAPPORT PUBLIÉ"),
 ("sénat", "NAVETTE AU SÉNAT"),
 ("dépôt", "DÉPÔT"),
 ("première lecture", "PREMIÈRE LECTURE"),
 ]

 for keyword, label in mapping:
 if keyword in lower:
 return label

 return "ÉTAPE À QUALIFIER"


@st.cache_data(ttl=3 * 3600, show_spinner=False)
def fetch_plf_2027_events(
 dossier_url: str,
) -> pd.DataFrame:
 if not dossier_url.strip():
 return pd.DataFrame(columns=PLF_COLUMNS)

 soup = request_html(dossier_url)

 full_text = clean_text(
 soup.get_text(" ", strip=True)
 ).lower()

 if "loi de finances" not in full_text and "plf 2027" not in full_text:
 raise ValueError(
 "Cette URL ne semble pas correspondre "
 "à un dossier de loi de finances."
 )

 rows = []
 seen = set()

 candidates = soup.select(
 "article, li, tr, .timeline-item, .etape, .step, section"
 )

 for candidate in candidates:
 text = clean_text(
 candidate.get_text(" ", strip=True)
 )

 if not text:
 continue

 lower = text.lower()

 keywords = (
 "dépôt",
 "commission",
 "rapport",
 "amendement",
 "séance",
 "sénat",
 "mixte paritaire",
 "constitutionnel",
 "promulgation",
 )

 if not any(keyword in lower for keyword in keywords):
 continue

 event_date = extract_french_date(text)

 title_node = candidate.select_one(
 "h1, h2, h3, h4, .title, a"
 )

 title = (
 clean_text(title_node.get_text(" ", strip=True))
 if title_node
 else text[:260]
 )

 link_node = candidate.select_one("a[href]")

 source_url = (
 urljoin(dossier_url, link_node["href"])
 if link_node
 else dossier_url
 )

 step = classify_plf_step(text)

 event_id = (
 f"{event_date.isoformat() if event_date else 'undated'}"
 f"|{step}|{source_url}"
 ).lower()

 if event_id in seen:
 continue

 seen.add(event_id)

 rows.append(
 {
 "EventId": event_id,
 "Date": (
 event_date.isoformat()
 if event_date
 else ""
 ),
 "Etape": step,
 "Instance": extract_instance(text),
 "Titre": title,
 "Statut": "PUBLIÉ",
 "SourceUrl": source_url,
 "SourceUpdatedAt": datetime.utcnow().isoformat(
 timespec="seconds"
 ),
 }
 )

 events = pd.DataFrame(rows, columns=PLF_COLUMNS)

 if events.empty:
 return events

 return (
 events
 .sort_values(
 "Date",
 ascending=False,
 na_position="last",
 )
 .reset_index(drop=True)
 )


# =========================================================
# ONGLETS
# =========================================================
def render_agenda(agenda_df: pd.DataFrame) -> None:
 st.subheader("Séances et réunions à venir")

 st.caption(
 "Source : agenda officiel de l’Assemblée nationale. "
 "Les comptes rendus publiés restent dans l’onglet Débats."
 )

 if agenda_df.empty:
 st.info(
 "Aucun événement futur détecté dans la fenêtre choisie. "
 "Vérifiez l’agenda officiel ou augmentez l’horizon de veille."
 )
 return

 st.dataframe(
 agenda_df[
 [
 "Date",
 "Heure",
 "Type",
 "Instance",
 "Titre",
 "Statut",
 "SourceUrl",
 ]
 ],
 use_container_width=True,
 hide_index=True,
 )


def render_plf(
 plf_df: pd.DataFrame,
 dossier_url: str,
) -> None:
 st.subheader("PLF 2027 — parcours législatif")

 if not dossier_url.strip():
 st.warning(
 "Renseignez l’URL officielle du dossier législatif "
 "du PLF 2027 dans la barre latérale."
 )
 return

 if plf_df.empty:
 st.info(
 "Aucun jalon n’a été extrait. Vérifiez l’URL du dossier "
 "ou le format de la page officielle."
 )
 return

 st.dataframe(
 plf_df[
 [
 "Date",
 "Etape",
 "Instance",
 "Titre",
 "Statut",
 "SourceUrl",
 ]
 ],
 use_container_width=True,
 hide_index=True,
 )


def render_debates(
 zip_bytes: bytes,
 catalog: dict,
) -> None:
 st.subheader("Débats et comptes rendus publiés")

 st.caption(
 "Source : archive XML des comptes rendus de séance. "
 "Cette source ne contient pas les séances futures."
 )

 selected_dates = st.multiselect(
 "Dates de comptes rendus",
 options=list(catalog.keys()),
 default=[next(iter(catalog))] if catalog else [],
 format_func=lambda key: catalog[key]["label"].upper(),
 )

 if not selected_dates:
 st.info("Sélectionnez au moins une date de compte rendu.")
 return

 query = st.text_input(
 "Requête booléenne",
 placeholder=(
 "Ex. MACRON AND "
 "(NUCLÉAIRE OR ÉNERGIE) NOT GUERRE"
 ),
 )

 st.caption(
 'AND, OR, NOT, -, parenthèses et "expression exacte" '
 "sont pris en charge. Sans opérateur : AND implicite."
 )

 selected_info = {
 key: catalog[key]
 for key in selected_dates
 }

 with st.spinner("Parsing des comptes rendus XML..."):
 debates_df = parse_selected_dates_fr(
 zip_bytes,
 selected_info,
 )

 if debates_df.empty:
 st.warning(
 "Aucune intervention n’a été trouvée "
 "pour les dates sélectionnées."
 )
 return

 filtered_df, terms, bool_error = (
 boolean_search_and_highlight(
 debates_df,
 query,
 )
 )

 st.markdown(
 f"""
 <div class="tertiary">
 {len(selected_dates)} date(s) chargée(s)
 · {len(debates_df)} intervention(s) parsée(s)
 </div>
 """,
 unsafe_allow_html=True,
 )

 if bool_error:
 st.error(f"Erreur de syntaxe : {bool_error}")
 return

 if not query.strip():
 st.info(
 "Saisissez une requête pour afficher "
 "les interventions correspondantes."
 )
 return

 if filtered_df.empty:
 st.warning("Aucune correspondance trouvée.")
 return

 metric_col, chart_col = st.columns([1, 2])

 metric_col.metric(
 "Occurrences",
 len(filtered_df),
 )

 if terms:
 chart = (
 filtered_df
 .groupby("DateSortKey")
 .size()
 .rename("Mentions")
 )

 chart.index = pd.to_datetime(chart.index)

 chart_col.line_chart(
 chart,
 color="#D71921",
 height=180,
 )

 selected_export_indices = []

 for index, row in filtered_df.iterrows():
 label = (
 f"{row['DateLabel']} | "
 f"{row['NomOrateur']} | "
 f"{str(row['Sequence'])[:55]}"
 )

 with st.expander(label):
 include = st.checkbox(
 "Inclure dans l’export",
 key=f"export_{row['DateSortKey']}_{index}",
 )

 if include:
 selected_export_indices.append(index)

 st.markdown(
 f"""
 <div class="tertiary">
 Date : {row['DateLabel']} · Séance : {row['Moment']}<br>
 Rôle : <span class="accent">{row['Qualite']}</span><br>
 Sujet : {row['SujetDebat']}<br>
 Séquence : {row['Sequence']}<br>
 Détections :
 <span class="accent">
 {row['MotsTrouves'].upper()}
 </span>
 </div>
 """,
 unsafe_allow_html=True,
 )

 st.markdown(
 row["VerbatimHighlight"],
 unsafe_allow_html=True,
 )

 if row["Reactions"]:
 st.caption(
 f"Réactions : {row['Reactions']}"
 )

 if selected_export_indices:
 export_df = filtered_df.loc[selected_export_indices]

 csv = (
 export_df
 .drop(
 columns=["VerbatimHighlight"],
 errors="ignore",
 )
 .to_csv(index=False)
 .encode("utf-8-sig")
 )

 st.download_button(
 "Exporter la sélection (CSV)",
 data=csv,
 file_name="giardini_comptes_rendus_selection.csv",
 mime="text/csv",
 )


# =========================================================
# APPLICATION
# =========================================================
def main() -> None:
 if "ui_theme" not in st.session_state:
 st.session_state.ui_theme = "DARK"

 st.sidebar.markdown("### Paramètres")

 theme = st.sidebar.radio(
 "Thème",
 ["DARK", "LIGHT"],
 horizontal=True,
 )

 st.session_state.ui_theme = theme
 inject_custom_css(theme)

 st.markdown(
 '<div class="hero-title">GIARDINI</div>',
 unsafe_allow_html=True,
 )

 st.markdown(
 '<span class="hero-subtitle">'
 "Veille parlementaire — Assemblée nationale"
 "</span>",
 unsafe_allow_html=True,
 )

 st.sidebar.markdown("---")
 st.sidebar.markdown("### Agenda")

 lookahead_days = st.sidebar.slider(
 "Horizon de veille",
 min_value=14,
 max_value=180,
 value=90,
 step=7,
 )

 st.sidebar.markdown("### PLF 2027")

 dossier_url = st.sidebar.text_input(
 "URL du dossier législatif officiel",
 value=st.session_state.get(
 "plf_2027_dossier_url",
 "",
 ),
 placeholder=(
 "https://www.assemblee-nationale.fr/"
 "dyn/17/dossiers/..."
 ),
 ).strip()

 st.session_state["plf_2027_dossier_url"] = dossier_url

 if st.sidebar.button("Actualiser les sources"):
 fetch_agenda_fr.clear()
 fetch_plf_2027_events.clear()
 fetch_and_index_fr.clear()
 parse_selected_dates_fr.clear()
 st.rerun()

 with st.spinner("Synchronisation de l’agenda..."):
 try:
 agenda_df = fetch_agenda_fr(lookahead_days)

 except Exception as error:
 agenda_df = pd.DataFrame(
 columns=AGENDA_COLUMNS
 )

 st.warning(
 "Agenda temporairement indisponible : "
 f"{type(error).__name__}."
 )

 with st.spinner("Chargement du dossier PLF 2027..."):
 try:
 plf_df = fetch_plf_2027_events(
 dossier_url
 )

 except Exception as error:
 plf_df = pd.DataFrame(
 columns=PLF_COLUMNS
 )

 if dossier_url:
 st.warning(
 "Dossier PLF 2027 non exploitable : "
 f"{error}"
 )

 tab_agenda, tab_debats, tab_plf = st.tabs(
 [
 "À venir",
 "Débats & comptes rendus",
 "PLF 2027",
 ]
 )

 with tab_agenda:
 render_agenda(agenda_df)

 with tab_debats:
 with st.spinner(
 "Synchronisation de l’archive de comptes rendus..."
 ):
 try:
 zip_bytes, catalog = fetch_and_index_fr(
 AN_TRANSCRIPTS_URL
 )

 except Exception as error:
 st.error(
 "Archive de comptes rendus indisponible : "
 f"{type(error).__name__} — {error}"
 )

 zip_bytes, catalog = None, None

 if zip_bytes and catalog:
 render_debates(zip_bytes, catalog)

 with tab_plf:
 render_plf(plf_df, dossier_url)


if __name__ == "__main__":
 main()
