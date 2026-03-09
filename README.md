# Healthcare Tenant Lead Generation Pipeline

A data pipeline that identifies, enriches, and ranks healthcare businesses as prospective tenants for two retail properties in Arden, NC. Collects business data from Google Places API, computes drive times via the Routes API, detects multi-location organizations through website scraping and address normalization, classifies businesses by type, and scores each lead into actionable tiers.

Built to automate prospecting for a commercial real estate owner with 4,800-9,000 SF of available retail medical space.

## Problem

Commercial real estate leasing for medical-retail space requires identifying healthcare practices that are:
- The right type (dentists, urgent care, PT clinics -- not hospitals or solo counselors)
- Far enough from the property that it fills a gap in their regional coverage (businesses within 10 min drive are already neighbors -- not prospects)
- Actively expanding (multi-location chains are more likely to open new offices)
- The right size for the available spaces (1,500-9,000 SF)

Manually searching Google Maps, checking websites for multi-location signals, and maintaining spreadsheets doesn't scale. This pipeline automates the entire research workflow and produces a prioritized call list.

## Pipeline

The pipeline runs as three sequential scripts against a local SQLite database:

```
collect.py ──→ enrich.py ──→ export.py
   │               │              │
   ▼               ▼              ▼
Google Places   Routes API     Tier scoring
Text Search     Drive times    CSV + Excel
34 queries      Website scrape Ranked output
Dedup by ID     Org detection
                Classification
```

### 1. Collect (`collect.py`)

Searches Google Places API (New) across 34 healthcare-related queries -- 4 type-based searches (dentist, chiropractor, etc.) and 30 free-text searches (orthodontist, urgent care, med spa, etc.). Handles pagination, deduplicates by Google Place ID, and logs completed searches to avoid redundant API calls on re-runs.

### 2. Enrich (`enrich.py`)

Five enrichment steps, each idempotent:

1. **Drive times** -- Google Routes API (distance matrix) from the property to each business. Batches of 25. Falls back to haversine distance with a 1.4x road-factor estimate when the API fails.
2. **Website scraping** -- Visits up to 5 pages per site (homepage, `/contact`, `/contact-us`, `/about`, `/about-us`). Extracts email addresses (with aggressive junk filtering), meta descriptions, and multi-location signals (link text, headings mentioning "locations"/"offices", 3+ distinct street addresses).
3. **Email cleaning** -- Removes platform emails (Wix, Sentry, Squarespace), placeholders (`user@domain.com`), and file-extension false positives (`logo@2x.png`).
4. **Business classification** -- Five-step priority chain: hospital system domain check, non-healthcare type veto, search query keyword match, name-based corrections (e.g., "Oral & Maxillofacial Surgery" found via orthodontist query gets reclassified), primary type fallback.
5. **Organization detection** -- Groups businesses by website domain, then by phone + address, then by normalized name. Counts distinct physical locations per org via address normalization that strips suite/unit/floor numbers and standardizes street types.

### 3. Export (`export.py`)

Computes a tier score (A/B/C/D) for each lead and exports ranked results:

| Tier | Meaning | Criteria |
|------|---------|----------|
| **A** | Call this week | Right type (tier 1-2), 2+ distinct locations, 10+ min drive |
| **B** | Call this month | Right type + multi-location or expansion signals, or strong reviews (4.0+, 50+); also tier 3 types with 2+ locations and 10+ min drive |
| **C** | Keep on list | Right type but no expansion signals |
| **D** | Skip | Hospital system, too close (<10 min), or wrong type |

**Outputs:**
- `leads_ranked.csv` -- All businesses with tier, category, drive time, org info
- `top_prospects.csv` -- Tier A + B only, deduplicated to one row per practice (org-level + phone-number dedup), filtered to within 45 min drive
- `organizations.csv` -- Multi-location organizations with distinct location counts
- `leads.xlsx` -- Excel workbook with color-coded tier sheets

## Organization Detection

The org detection logic handles three real-world cases:

| Scenario | Same Domain? | Same Address? | Result |
|----------|:---:|:---:|--------|
| Independent practices in the same building | No | Yes | Separate orgs (correct -- different businesses) |
| Same practice, multiple Google listings | Yes | Yes | Same org, 1 location (deduped via address normalization) |
| Multi-location chain | Yes | No | Same org, N locations |

A secondary pass groups businesses by **phone + normalized address** to catch providers at the same practice who have different or missing websites (shared phone = shared front desk = same practice).

Address normalization strips suite/unit/floor designators, standardizes street abbreviations, and removes building number letter suffixes (`75a` -> `75`) to correctly dedup within organizations.

## Project Structure

```
├── config.py        # Search categories, API endpoints, type mappings, tier definitions
├── db.py            # SQLite schema, CRUD helpers, migrations
├── collect.py       # Google Places Text Search collection
├── enrich.py        # Drive times, classification, org detection, website scraping
├── export.py        # Tier scoring, ranked CSV/Excel export
├── tests/           # Unit tests (pytest)
│   ├── test_collect.py
│   ├── test_db.py
│   ├── test_enrich.py
│   └── test_export.py
└── data/            # Generated output (gitignored)
    ├── leads.db
    ├── leads_ranked.csv
    ├── top_prospects.csv
    ├── organizations.csv
    └── leads.xlsx
```

~1,900 lines of pipeline code, ~1,300 lines of tests.

## Setup

**Prerequisites:** Python 3.10+, a Google Cloud project with the [Places API (New)](https://developers.google.com/maps/documentation/places/web-service) and [Routes API](https://developers.google.com/maps/documentation/routes) enabled.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file:

```
GOOGLE_API_KEY=your_api_key_here
```

## Usage

```bash
source .venv/bin/activate

python collect.py    # Collect businesses from Google Places API
python enrich.py     # Drive times, classification, org detection
python export.py     # Export ranked CSVs and Excel
```

The pipeline is re-runnable. `collect.py` skips already-searched queries. `enrich.py` skips businesses that already have drive times and skips website scraping for businesses that already have all three enrichment fields (email, description, multi-location signals); org detection clears and re-runs from scratch since it's fully derived. All generated data lives in `data/`.

Run tests:

```bash
pytest
```

## Technical Decisions

- **SQLite over Postgres/cloud DB.** The dataset is a few hundred rows. SQLite is zero-config, the DB file is portable, and WAL mode handles concurrent reads fine. No reason to add infrastructure.
- **Sequential scripts over a framework.** Three scripts with clear inputs/outputs are easier to debug and re-run partially than a DAG framework. Each step is idempotent.
- **Address normalization over geocode comparison.** Google already geocodes each place, but addresses like "123 Main St Suite 100" and "123 Main St Suite 200" have different coordinates. Normalizing the address string and comparing is more reliable for same-building dedup than a distance threshold.
- **Multi-pass org detection.** Domain grouping catches most chains. Phone + address grouping catches providers at the same practice with different websites. Name normalization catches the rest. Each pass is independent and additive.
- **Aggressive email filtering.** Website scraping picks up platform emails (Sentry, Wix), asset filenames (`logo@2x.png`), and placeholder text (`user@domain.com`). Filtering these out is more valuable than having a high extraction rate.
- **CSV as primary output.** The end user works in Google Sheets. CSV opens natively; Excel is a secondary export.

## Results

From a single pipeline run targeting the Asheville, NC metro area:

- **1,071 businesses** collected across 33 search queries
- **239 actionable prospects** (Tier A + B) after org-level dedup, phone dedup, and drive time filtering
- **157 Tier A** (multi-location chains in the right category and distance)
- **273 Tier B** (right type with expansion signals or strong reviews)
- Zero duplicate phone numbers in the final prospect list
- Zero junk emails (40+ platform/placeholder patterns filtered)

## Built With

- **Python 3.10+** — standard library + requests, BeautifulSoup, openpyxl
- **Google Places API (New)** — Text Search for business discovery
- **Google Routes API** — Distance matrix for drive time computation
- **SQLite** — local database, zero-config, portable
- **pytest** — unit tests for classification, org detection, export logic

## Development Process

This project was built with [Claude Code](https://claude.ai/claude-code) as a pair-programming tool. The pipeline design, API integration, classification logic, and data quality fixes were developed iteratively through natural language conversation — from initial prototype to production-quality output in a series of focused sessions.
