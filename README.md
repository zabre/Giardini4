# GIARDINI 🟥
### Veille des débats parlementaires — France · UE · US

Interface industrielle de veille parlementaire en temps réel.  
Recherche booléenne full-text dans les verbatims de séance, surlignage des occurrences, export HTML thémé.

---

## Fonctionnalités

- 🇫🇷 **Assemblée Nationale** — Comptes rendus XML de la 17e législature (open data officiel)
- 🇪🇺 **Parlement Européen** — Comptes rendus de plénière via l'API open data Europarl
- 🇺🇸 **Congrès US** — Daily Congressional Record via l'API congress.gov
- 🔍 Moteur de recherche **booléen** : `AND`, `OR`, `NOT`, `(groupements)`, `"phrases exactes"`
- 📈 Courbe d'évolution temporelle des mentions (rouge `#D71921`)
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
├── download_with_resume()         # Téléchargement avec retry Range headers (fix ChunkedEncodingError)
├── inject_custom_css()            # Design system DARK/LIGHT
├── boolean_search_and_highlight() # Moteur booléen (AND/OR/NOT/phrases)
├── MOTEUR 1 — FRANCE
│   ├── fetch_and_index_fr()       # Téléchargement robuste ZIP ~46MB via download_with_resume()
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

### Fix v2.1 — ChunkedEncodingError France (mai 2026)

**Problème** : Le CDN de l'Assemblée Nationale **coupe la connexion TCP après ~12MB** sur un fichier de 46MB.  
Erreur : `ChunkedEncodingError — IncompleteRead(12189330 bytes read, 33612760 more expected)`

**Cause** : Timeout côté serveur CDN (OVH) sur les connexions longues, indépendant de `timeout=` côté client.

**Solution** — fonction `download_with_resume()` :
- Détection du support `Accept-Ranges` via `HEAD` avant le téléchargement
- En cas de coupure, reprise exacte depuis l'offset reçu via l'en-tête HTTP `Range: bytes=<offset>-`
- **Backoff exponentiel** entre les tentatives : 2s, 4s, 8s… jusqu'à 10 retries max
- Si le serveur ne supporte pas `Range` (réponse 200 au lieu de 206), reprise depuis zéro
- `@st.cache_data(ttl=12h)` — mis en cache après le 1er téléchargement réussi

```python
# Schéma simplifié de la stratégie
buffer = bytearray()
while not complete:
    headers["Range"] = f"bytes={len(buffer)}-"  # Reprendre là où on s'est arrêté
    for chunk in requests.get(url, stream=True).iter_content(512KB):
        buffer.extend(chunk)
    # Si ChunkedEncodingError : wait 2^attempt secondes, retry
```

### Fix v2.0 — Synchronisation France (mai 2026)

L'ancien `timeout=30` expirait sur un fichier de 46MB livré à ~30KB/s. Résolution : `stream=True` + `timeout=300`.

### Fix v2.0 — Moteur US Congress (mai 2026)

L'ancien moteur envoyait 20–30 requêtes HTTP simultанées, explosant le rate limit de la `DEMO_KEY`.  
**Solution** : endpoint `fullIssue` (1 requête par séance) + `time.sleep(0.5)` entre les fetches HTM.

---

## Données sources

| Source | Format | URL | Licence |
|--------|--------|-----|---------|
| Assemblée Nationale (FR) | ZIP/XML | [data.assemblee-nationale.fr](https://data.assemblee-nationale.fr) | Licence Ouverte / Open Licence v2.0 |
| Parlement Européen (UE) | API JSON + XML | [data.europarl.europa.eu](https://data.europarl.europa.eu) | CC BY 4.0 |
| Congrès US | API JSON + HTM | [api.congress.gov](https://api.congress.gov) | Public Domain (US Government Works) |

---

## Changelog

### v2.1.0 — Mai 2026
- ✅ **Fix majeur** synchronisation France : `download_with_resume()` avec `Range` headers + backoff exponentiel
- ✅ Résout `ChunkedEncodingError — IncompleteRead` (CDN AN coupe après ~12MB)
- ✅ Jusqu'à 10 retries automatiques avec reprise depuis l'offset exact
- ✅ Headers `User-Agent` navigateur pour éviter les blocages CDN

### v2.0.0 — Mai 2026
- ✅ Fix synchronisation France : streaming ZIP + timeout 300s (résout la boucle infinie)
- ✅ Fix moteur US : endpoint `fullIssue` + throttle anti-rate-limit
- ✅ Graphique temporel : `st.line_chart`, courbe rouge `#D71921`
- ✅ `import time` ajouté (requis pour `time.sleep`)

### v1.0.0 — Avril 2026
- 🚀 Lancement initial : moteurs France, UE et US
- 🔍 Moteur de recherche booléen (AND / OR / NOT / phrases)
- 🎨 Design system industriel DARK/LIGHT
- 📤 Export HTML thémé
