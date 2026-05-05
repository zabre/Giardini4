# GIARDINI 🟥
### Veille des débats parlementaires — France · UE · US

Interface industrielle de veille parlementaire en temps réel.  
Recherche booléenne full-text dans les verbatims de séance, surlignage des occurrences, export HTML thémé.

---

## Fonctionnalités

- 🇫🇷 **Assemblée Nationale** — Comptes rendus XML de la 17e législature (open data officiel)
- 🇪🇺 **Parlement Européen** — Comptes rendus de plénière via l’API open data Europarl
- 🇺🇸 **Congrès US** — Daily Congressional Record via l’API congress.gov
- 🔍 Moteur de recherche **booléen** : `AND`, `OR`, `NOT`, `(groupements)`, `"phrases exactes"`
- 📈 Courbe d’évolution temporelle des mentions (rouge `#D71921`)
- ✅ Sélection granulaire des résultats pour export HTML thémé (DARK / LIGHT)
- 🎨 Design system industriel — thème DARK / LIGHT dynamique

---

## Installation

```bash
git clone https://github.com/zabre/Giardini4.git
cd Giardini4
pip install -r requirements.txt
streamlit run app.py
```

---

## Requirements

```
streamlit>=1.30.0
pandas>=2.0.0
requests>=2.31.0
lxml>=4.9.3
beautifulsoup4>=4.12.0
```

---

## Configuration (optionnelle)

Pour le Congrès US, une clé API `congress.gov` lève les restrictions de rate limit (5 req/min avec `DEMO_KEY`) :

Créez un fichier `.streamlit/secrets.toml` :

```toml
CONGRESS_API_KEY = "votre_clé_ici"
```

Obtenez une clé gratuite sur [api.congress.gov](https://api.congress.gov/).

---

## Architecture

```
app.py
├── inject_custom_css()            # Design system DARK/LIGHT
├── boolean_search_and_highlight() # Moteur booléen (AND/OR/NOT/phrases)
├── MOTEUR 1 — FRANCE
│   ├── fetch_and_index_fr()       # Téléchargement streaming ZIP ~46MB (timeout 300s)
│   └── parse_selected_dates_fr()  # Parsing XML comptes rendus AN
├── MOTEUR 2 — UE
│   ├── fetch_and_index_eu()       # Index via API Europarl open data
│   └── parse_selected_dates_eu()  # Parsing XML interventions
├── MOTEUR 3 — US
│   ├── fetch_and_index_us()       # Index séances via API congress.gov
│   └── parse_selected_dates_us()  # Parsing HTM via endpoint fullIssue (1 req/séance)
├── generate_html_export()         # Export HTML thémé
└── main()                         # UI Streamlit
```

---

## Notes techniques

### Fix v2 — Synchronisation France (mai 2026)

Le fichier `syseron.xml.zip` fait **~46MB** et le serveur open data de l’Assemblée Nationale délivre à ~30KB/s depuis l’extérieur.  
L’ancien `timeout=30` expirait systématiquement avant la fin du téléchargement, causant une boucle de chargement infinie.

**Solution implémentée :**
- `stream=True` + `iter_content(chunk_size=512KB)` — maintient la connexion active
- `timeout=300` — 5 minutes de marge
- `@st.cache_data(ttl=12h)` — le fichier est mis en cache après le 1er chargement réussi, les suivants sont instantanés

### Fix v2 — Moteur US Congress (mai 2026)

L’ancien moteur envoyait 20–30 requêtes HTTP simultanées (1 par article), explosant le rate limit de la `DEMO_KEY` (5 req/min).

**Solution implémentée :**
- Endpoint `fullIssue` : **1 seule requête API** pour récupérer toute la structure d’une séance
- `time.sleep(0.5)` entre chaque fetch HTM pour respecter le rate limit
- Parsing regex des blocs de parole (pattern `Mr./Ms./The SPEAKER...`)

---

## Données sources

| Source | Format | URL | Licence |
|--------|--------|-----|---------|
| Assemblée Nationale (FR) | ZIP/XML | [data.assemblee-nationale.fr](https://data.assemblee-nationale.fr) | Licence Ouverte / Open Licence v2.0 |
| Parlement Européen (UE) | API JSON + XML | [data.europarl.europa.eu](https://data.europarl.europa.eu) | CC BY 4.0 |
| Congrès US | API JSON + HTM | [api.congress.gov](https://api.congress.gov) | Public Domain (US Government Works) |

---

## Changelog

### v2.0.0 — Mai 2026
- ✅ Fix synchronisation France : streaming ZIP + timeout 300s (résout la boucle infinie)
- ✅ Fix moteur US : endpoint `fullIssue` + throttle anti-rate-limit
- ✅ Graphique temporel : `st.line_chart`, courbe rouge `#D71921`
- ✅ Message spinner FR explicite : `[ FICHIER ~46MB — PATIENCE ]`
- ✅ `import time` ajouté (requis pour `time.sleep`)

### v1.0.0 — Avril 2026
- 🚀 Lancement initial : moteurs France, UE et US
- 🔍 Moteur de recherche booléen (AND / OR / NOT / phrases)
- 🎨 Design system industriel DARK/LIGHT
- 📤 Export HTML thémé
