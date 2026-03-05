# Technical Approach: Healthcare Tenant Lead Generation

## Goal

Find healthcare businesses (doctors, dentists, PT, chiropractors, etc.) in the Asheville, NC area that might be interested in leasing space at **Shops on Rockwood (330–336 Rockwood Rd, Arden, NC)** — a 9,000 SF shopping center with 1,500–3,300 SF spaces available at $19/SF/YR. Adjacent property at 316 Rockwood Rd also available (1,500–9,000 SF at $26/SF/YR, built 2025).

High-value signal: businesses with **multiple locations** (indicates active expansion).

---

## What's Been Built

| File | Purpose |
|---|---|
| `config.py` | All configuration: property coordinates, search queries, API endpoints, drive zone thresholds, Places API field masks |
| `db.py` | SQLite database initialization, schema creation, and all CRUD helper functions (upsert, update drive time, update org, etc.) |
| `collect.py` | Google Places API (New) Text Search — runs 22 healthcare search queries, paginates results, deduplicates by `place_id`, stores in SQLite |
| `enrich.py` | Three enrichment steps: (1) Google Routes Matrix API for real drive times, (2) multi-location organization detection via domain + name matching, (3) email scraping from business websites |
| `export.py` | Exports ranked leads to CSV and formatted Excel (3 sheets: All Leads, Multi-Location Targets, Summary Stats) |
| `requirements.txt` | Python dependencies: `requests`, `python-dotenv`, `openpyxl` |
| `.env.example` | Template for `GOOGLE_API_KEY` |
| `.gitignore` | Ignores `.env`, `data/`, `__pycache__/`, `.venv/` |
| `data/leads.db` | SQLite database file (initialized, empty until `collect.py` runs) |

---

## Data Collection Approach

### API: Google Places API (New) — Text Search

We use the **Google Places Text Search (New)** endpoint (`POST https://places.googleapis.com/v1/places:searchText`). This is the newer version of the Places API with structured JSON request bodies and field masking.

**Why this API:**
- Best coverage of local businesses with structured data (name, address, phone, website, ratings, types)
- Free tier is sufficient: 1,000 Text Search calls/month free (we need ~50–100)
- Returns up to 60 results per query (paginated in pages of 20)
- No scraping — clean, legal, structured data

**Alternatives rejected:**
- Web scraping (Healthgrades, Yelp): fragile, legal gray area
- Yelp API: weaker coverage of medical businesses, lower free tier
- Manual lookup: doesn't scale

### Search Queries

We run **22 searches** total — 4 type-filtered + 18 text-based:

**Type-filtered searches** (using Google's `includedType` parameter for precise matching):
- `doctor` (query: "doctor in Asheville NC")
- `dentist` (query: "dentist in Asheville NC")
- `physiotherapist` (query: "physiotherapist in Asheville NC")
- `chiropractor` (query: "chiropractor in Asheville NC")

**Text-based searches** (for specialties without clean Google Places types):
- "orthodontist in Asheville NC"
- "oral surgeon in Asheville NC"
- "optometrist in Asheville NC"
- "ophthalmologist in Asheville NC"
- "dermatologist in Asheville NC"
- "podiatrist in Asheville NC"
- "urgent care in Asheville NC"
- "physical therapy in Asheville NC"
- "occupational therapy in Asheville NC"
- "mental health clinic in Asheville NC"
- "pediatrician in Asheville NC"
- "OBGYN in Asheville NC"
- "ENT doctor in Asheville NC"
- "allergy clinic in Asheville NC"
- "medical clinic in Asheville NC"
- "dental clinic in Asheville NC"
- "skin care clinic in Asheville NC"
- "wellness center in Asheville NC"

### Geographic Targeting

**Location bias** (not restriction — we collect everything, filter later):
- Center: Asheville, NC (lat: `35.5951`, lng: `-82.5515`)
- Radius: `20,000 meters` (20 km)
- This is passed as a `locationBias.circle` in the API request body

**Exclusion zone strategy:** We do **not** exclude anything during collection. Instead, we calculate real drive times from the property to every business (see Enrichment below) and tag each with a drive zone. The property owner decides his own cutoff when reviewing leads.

**Property coordinates:** `35.4700, -82.5170` (Shops on Rockwood, 330 Rockwood Rd, Arden, NC)

### Pagination & Deduplication

- Each query can return up to **60 results** (3 pages of 20)
- We follow `nextPageToken` to get all pages
- Deduplication is by **Google `place_id`** — if a business appears in multiple searches (e.g., "doctor" and "pediatrician"), only the first insert is kept (SQLite `UNIQUE` constraint on `place_id`, we catch `IntegrityError` and skip)
- Expected yield: **500–1,500 unique businesses**

### Fields Requested (via `X-Goog-FieldMask`)

```
places.id, places.displayName, places.formattedAddress, places.location,
places.nationalPhoneNumber, places.websiteUri, places.rating,
places.userRatingCount, places.types, places.primaryType, nextPageToken
```

These are Enterprise-tier fields, which are free for Text Search (up to 1,000 calls/month).

---

## Database Design

### Tech: SQLite

- Single file (`data/leads.db`), no server needed
- WAL journal mode for better concurrent read performance
- Foreign keys enabled
- Perfect for this data volume (500–1,500 records)

### Schema

```sql
CREATE TABLE organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    website_domain TEXT,         -- e.g., "missionhealth.org"
    location_count INTEGER DEFAULT 1,
    notes TEXT                   -- e.g., "Matched by name similarity"
);

CREATE TABLE businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    place_id TEXT UNIQUE NOT NULL,   -- Google Places ID (dedup key)
    name TEXT NOT NULL,
    address TEXT,
    lat REAL,
    lng REAL,
    phone TEXT,
    website TEXT,
    email TEXT,                      -- scraped from website (nullable)
    rating REAL,                     -- Google rating (1-5)
    rating_count INTEGER,            -- number of Google reviews
    types TEXT,                      -- JSON array of Google Places types
    primary_type TEXT,               -- e.g., "dentist", "doctor"
    search_query TEXT,               -- which search found this first
    distance_miles REAL,             -- straight-line from property
    drive_time_minutes REAL,         -- actual Google Routes drive time
    drive_zone TEXT,                 -- "<10 min", "10-15 min", "15-20 min", "20+ min"
    organization_id INTEGER,         -- FK to organizations table
    raw_json TEXT,                   -- full Google Places response (JSON)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (organization_id) REFERENCES organizations(id)
);

CREATE TABLE outreach (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    contact_date TEXT,
    method TEXT,                     -- "phone", "email", "in-person"
    notes TEXT,
    status TEXT,                     -- "contacted", "interested", "declined", "no-response"
    FOREIGN KEY (business_id) REFERENCES businesses(id)
);

-- Indexes
CREATE INDEX idx_businesses_place_id ON businesses(place_id);
CREATE INDEX idx_businesses_drive_zone ON businesses(drive_zone);
CREATE INDEX idx_businesses_organization ON businesses(organization_id);
```

### Deduplication

- **Primary dedup:** `place_id UNIQUE` constraint. Same physical business appearing in multiple searches gets inserted once.
- **Organization-level dedup:** Businesses are grouped into organizations (see multi-location detection below), so you can see "Blue Ridge Dental" as one entity even if they have 3 Google Places entries.

---

## Enrichment Strategy

### 1. Drive Time Calculation

**API:** Google Routes Compute Route Matrix (`POST https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix`)

**Why actual drive times, not radius:**
Western NC has winding mountain roads where 5 miles could be 20 minutes. A crude radius estimate would be misleading. We compute the actual driving route.

**Implementation:**
- Origin: property at `35.4700, -82.5170`
- Destinations: batched 25 at a time (API limit)
- Travel mode: `DRIVE`, routing preference: `TRAFFIC_UNAWARE` (baseline, not rush hour)
- Response gives duration in seconds and distance in meters per origin-destination pair
- Fallback: if Routes API fails for a business, we estimate using haversine distance × 1.4 (road factor) ÷ 30 mph

**Drive zones assigned:**

| Minutes | Zone |
|---|---|
| < 10 | `<10 min` |
| 10–15 | `10-15 min` |
| 15–20 | `15-20 min` |
| 20+ | `20+ min` |

### 2. Multi-Location Organization Detection

Two strategies, run in sequence:

**A. Website domain grouping:**
- Extract base domain from each business's `websiteUri` (strip `www.`, protocol)
- Group all businesses sharing the same domain
- If 2+ businesses share a domain → create an organization, link them, set `location_count`
- Example: 3 businesses all linking to `missionhealth.org` → 1 organization with 3 locations

**B. Fuzzy name matching (for businesses without websites):**
- Normalize names: lowercase, strip suffixes (", PC", ", PA", ", PLLC", ", DDS", etc.), remove location qualifiers ("- Asheville", "- Downtown", etc.), remove non-alphanumeric
- Group by normalized name
- If 2+ businesses share a normalized name → create an organization
- Example: "Blue Ridge Dental - Asheville" and "Blue Ridge Dental - Hendersonville" → same org

### 3. Email Extraction

**Method:** HTTP scraping of business websites (best-effort).

For each business that has a `websiteUri` but no email:
1. Fetch the main page
2. If no email found, try `/contact`, `/contact-us`, `/about`, `/about-us`
3. Extract emails with regex: `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}`
4. Filter out junk emails (`@example.com`, `@sentry.io`, `@wix.com`, `noreply@`, image file extensions)
5. Store the first valid email found

**Rate limiting:** 0.3s delay between requests. User-Agent: `"Mozilla/5.0 (compatible; LeadGen/1.0)"`. Timeout: 8 seconds per request.

### 4. Phone Numbers and Websites

These come directly from the Google Places API (`nationalPhoneNumber`, `websiteUri`) — no additional scraping needed.

---

## Ranking / Prioritization

The export sorts all leads by priority using this SQL `ORDER BY`:

```sql
ORDER BY
    COALESCE(o.location_count, 1) DESC,   -- Multi-location first (most locations wins)
    b.rating DESC NULLS LAST,             -- Higher Google rating
    b.rating_count DESC NULLS LAST        -- More reviews = more established
```

**Rationale:**
1. **Multi-location businesses are #1 priority** — they've already demonstrated willingness to expand. A dental group with 4 locations is far more likely to open a 5th than a solo practice.
2. **Higher-rated businesses** are more established and likely profitable enough to expand.
3. **More reviews** = longer track record and higher patient volume.

The Excel export highlights multi-location businesses in green and has a dedicated "Multi-Location Targets" sheet.

---

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3 |
| Database | SQLite (single file, no server) |
| Data source | Google Places API (New) — Text Search |
| Drive times | Google Routes API — Compute Route Matrix |
| Email extraction | HTTP requests + regex (best-effort scraping) |
| HTTP client | `requests` library |
| Config | `python-dotenv` (`.env` file for API key) |
| Excel export | `openpyxl` |
| Virtual environment | Python `venv` |

---

## Current State

### Working
- All 6 Python modules import and run without errors
- Database initializes correctly with full schema + indexes
- Virtual environment set up with all dependencies installed
- Export produces both CSV and formatted Excel with 3 sheets

### Not Yet Run (requires API key)
- `collect.py` — needs `GOOGLE_API_KEY` in `.env` to make API calls
- `enrich.py` — needs data in the database + API key for Routes
- `export.py` — needs data in the database to export

### Known Limitations
- **60-result cap per query**: Google Places Text Search returns max 60 results per query. If a category has more than 60 businesses in the area, we'll miss some. Mitigation: could subdivide geographically (not yet implemented).
- **Email scraping is best-effort**: Many medical practice websites are built with JavaScript frameworks (React, Angular) that won't render with simple HTTP GET. We'll miss emails on those sites. A headless browser would improve yield but adds complexity.
- **Name matching is basic**: The fuzzy name matching strips suffixes and location qualifiers but doesn't do true fuzzy/edit-distance matching. "Asheville Family Medicine" and "AVL Family Med" would not match.
- **No operating hours**: We don't collect/use business hours data, which could indicate if a business is outgrowing its current space.
- **Single-origin drive time**: We calculate from 330 Rockwood Rd only. If someone wanted to compare with another property, we'd need to re-run.

---

## Cost

| API | Free Tier | Our Estimated Usage | Cost |
|---|---|---|---|
| Google Places Text Search (New) | 1,000 calls/month | ~50–100 calls | **$0** |
| Google Routes Compute Matrix | 10,000 elements/month | ~500–1,500 elements | **$0** |
| Website scraping | N/A | ~500–1,500 HTTP requests | **$0** |
| **Total** | | | **$0** |

If usage exceeds free tiers (unlikely): Places Text Search is $32 per 1,000 calls; Routes Matrix is $5 per 1,000 elements.

---

## How to Run

```bash
# 1. Set up API key
cp .env.example .env
# Edit .env and add your Google API key

# 2. Activate virtual environment
source .venv/bin/activate

# 3. Run pipeline
python collect.py    # ~2-5 min — fetches businesses from Google Places
python enrich.py     # ~5-10 min — drive times, org detection, email scraping
python export.py     # ~1 sec — generates data/leads.csv and data/leads.xlsx
```
