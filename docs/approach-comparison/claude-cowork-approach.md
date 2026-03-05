# Technical Approach — Cowork Session (Supabase + Python)

## 1. What I've Built

| File | Purpose |
|------|---------|
| `config.py` | Search grid (14 geographic zones with lat/lng/radius), 40 healthcare search categories mapped to enum values, exclusion zone logic, haversine distance calculator |
| `collect.py` | Main data collection script — queries Google Places API across all zones × all categories, deduplicates, stores businesses + locations in Supabase |
| `enrich.py` | Website scraper — visits each business's website + /contact + /about pages to extract emails, detect multi-location signals (link text, headings, address pattern count), pull meta descriptions |
| `report.py` | Reporting/export — terminal summary dashboard (by practice type, by city), top-N ranked leads table, CSV export with all fields |
| `requirements.txt` | Dependencies: google-maps-services, supabase, httpx, beautifulsoup4, python-dotenv, rich |
| `.env.example` | Template for API keys (Google Maps + Supabase service role) |
| `README.md` | Setup instructions, architecture overview, cost estimates |

**Additionally created:** A live Supabase project (`rockwood-leads`, project ID `fpqzriqghxcldtcyqylx`, region `us-east-1`) with the full schema already deployed via migration.

---

## 2. Data Collection Approach

### Data Source
**Google Places API** (Text Search endpoint via the `googlemaps` Python client). Each query combines a healthcare search term with a geographic center point and radius.

### Search Categories (40 queries)
Each maps to a `practice_type` enum value in the database:

```
dentist → dentist
orthodontist → orthodontist
oral surgeon → oral_surgeon
periodontist → periodontist
endodontist → endodontist
physical therapy → physical_therapy
occupational therapy → occupational_therapy
chiropractor → chiropractor
optometrist → optometrist
ophthalmologist → ophthalmologist
dermatologist → dermatologist
family doctor → primary_care
primary care physician → primary_care
internal medicine → internal_medicine
pediatrician → pediatrics
urgent care → urgent_care
medical clinic → medical_group
medical group → medical_group
psychiatrist → psychiatry_psychology
psychologist → psychiatry_psychology
therapist mental health → psychiatry_psychology
podiatrist → podiatrist
allergist → allergist
ENT doctor → ent
ear nose throat → ent
OB GYN → obgyn
orthopedic doctor → orthopedic
pain management clinic → pain_management
radiology imaging center → imaging_radiology
MRI CT scan → imaging_radiology
specialty medical clinic → specialty_clinic
veterinarian → veterinary
pharmacy → pharmacy
acupuncture → other
sports medicine → other
hearing aid audiologist → other
sleep clinic → other
dialysis center → specialty_clinic
wound care clinic → specialty_clinic
weight loss clinic → specialty_clinic
med spa → other
```

### Geographic Targeting

**14 overlapping search zones** covering Greater Asheville, each defined as (latitude, longitude, radius_meters, label):

```python
(35.5951, -82.5515, 5000, "downtown_asheville")
(35.6150, -82.5600, 5000, "north_asheville")      # Montford, Grove Park, Five Points
(35.5800, -82.5000, 5000, "east_asheville")
(35.5850, -82.5900, 5000, "west_asheville")
(35.5400, -82.5500, 4000, "south_asheville_north") # North of exclusion zone
(35.6970, -82.5607, 5000, "weaverville")
(35.6179, -82.3213, 5000, "black_mountain")
(35.5978, -82.3978, 4000, "swannanoa")
(35.5200, -82.5300, 3000, "biltmore_area")
(35.6350, -82.5700, 3000, "woodfin")
(35.5700, -82.6700, 5000, "leicester_candler")
(35.5400, -82.6300, 4000, "enka_area")
(35.5133, -82.3967, 5000, "fairview")
(35.6600, -82.5500, 5000, "north_broad")
```

**Total search space:** 40 categories × 14 zones = **560 API searches**, each returning up to 60 results (3 pages of 20).

### Exclusion Zone

Property location: `35.4621, -82.5540` (Shops on Rockwood, 330-336 Rockwood Rd, Arden, NC).

**Exclusion radius: 4.0 miles** (approximates a 5-10 minute drive). Distance calculated via haversine formula. Any business within this radius is skipped during collection — the check happens twice:

1. **Quick pre-filter** before the expensive Place Details API call (uses coordinates from the search result)
2. **Final check** during the upsert function (uses the same coordinates, belt-and-suspenders)

---

## 3. Database Design

### Platform
**Supabase** (hosted PostgreSQL). Project: `rockwood-leads`, region: `us-east-1`, project ID: `fpqzriqghxcldtcyqylx`. Schema deployed via Supabase migration.

### Custom Enums

```sql
CREATE TYPE practice_type AS ENUM (
  'dentist', 'orthodontist', 'oral_surgeon', 'periodontist', 'endodontist',
  'physical_therapy', 'occupational_therapy', 'chiropractor', 'optometrist',
  'ophthalmologist', 'dermatologist', 'primary_care', 'internal_medicine',
  'pediatrics', 'urgent_care', 'medical_group', 'psychiatry_psychology',
  'podiatrist', 'allergist', 'ent', 'obgyn', 'orthopedic', 'pain_management',
  'imaging_radiology', 'specialty_clinic', 'veterinary', 'pharmacy', 'other'
);

CREATE TYPE outreach_status AS ENUM (
  'not_contacted', 'email_sent', 'called', 'voicemail_left', 'spoke_with',
  'meeting_scheduled', 'interested', 'not_interested', 'follow_up_needed'
);

CREATE TYPE lead_tier AS ENUM ('high', 'medium', 'low', 'skip');
```

### Tables

**`businesses`** — The parent entity (a dental group, a PT chain, etc.)

| Column | Type | Purpose |
|--------|------|---------|
| id | UUID PK | Auto-generated |
| name | TEXT NOT NULL | Business name |
| practice_type | practice_type enum | Category |
| practice_type_detail | TEXT | Freeform specifics (e.g., "pediatric dentistry") |
| website | TEXT | Primary website |
| email | TEXT | Primary email (from enrichment) |
| phone | TEXT | Primary phone |
| location_count | INT DEFAULT 1 | Number of locations found |
| is_multi_location | BOOLEAN DEFAULT FALSE | Multi-location flag |
| has_expanded_recently | BOOLEAN DEFAULT FALSE | Expansion signal |
| expansion_notes | TEXT | How expansion was detected |
| description | TEXT | Meta description from website |
| notes | TEXT | Free-form notes for outreach context |
| lead_tier | lead_tier DEFAULT 'medium' | Ranking tier |
| outreach_status | outreach_status DEFAULT 'not_contacted' | CRM-like tracking |
| outreach_notes | TEXT | Notes from calls/emails |
| last_contacted_at | TIMESTAMPTZ | Last outreach timestamp |
| google_places_id | TEXT | For deduplication |
| data_source | TEXT DEFAULT 'google_places' | Provenance |
| created_at | TIMESTAMPTZ | Auto-set |
| updated_at | TIMESTAMPTZ | Auto-updated via trigger |

**`locations`** — Individual addresses for each business

| Column | Type | Purpose |
|--------|------|---------|
| id | UUID PK | Auto-generated |
| business_id | UUID FK → businesses(id) ON DELETE CASCADE | Parent link |
| name | TEXT | Location-specific name if different |
| address | TEXT NOT NULL | Full formatted address |
| city | TEXT | Parsed from address |
| state | TEXT DEFAULT 'NC' | Parsed from address |
| zip | TEXT | Parsed from address |
| latitude | DOUBLE PRECISION | For distance calculations |
| longitude | DOUBLE PRECISION | For distance calculations |
| phone | TEXT | Location-specific phone |
| google_places_id | TEXT | Location-level dedup |
| google_rating | NUMERIC(2,1) | Google star rating |
| google_review_count | INT | Number of Google reviews |
| is_primary_location | BOOLEAN DEFAULT FALSE | Flag for HQ/main office |
| distance_from_property_miles | NUMERIC(5,1) | Pre-calculated distance |
| drive_time_minutes | INT | Placeholder for future use |
| created_at | TIMESTAMPTZ | Auto-set |

**`search_log`** — Tracks which API searches have been run

| Column | Type | Purpose |
|--------|------|---------|
| id | UUID PK | Auto-generated |
| query | TEXT NOT NULL | Search term used |
| latitude | DOUBLE PRECISION | Center point |
| longitude | DOUBLE PRECISION | Center point |
| radius_meters | INT | Search radius |
| results_count | INT | How many results came back |
| searched_at | TIMESTAMPTZ | When the search ran |

### Indexes

```sql
idx_businesses_practice_type ON businesses(practice_type)
idx_businesses_lead_tier ON businesses(lead_tier)
idx_businesses_outreach_status ON businesses(outreach_status)
idx_businesses_location_count ON businesses(location_count DESC)
idx_businesses_google_places_id ON businesses(google_places_id)
idx_locations_business_id ON locations(business_id)
idx_locations_city ON locations(city)
idx_locations_google_places_id ON locations(google_places_id)
```

### Deduplication Strategy

- **Location-level:** Check `locations.google_places_id` before inserting. If the Place ID already exists, skip entirely.
- **Business-level:** Before creating a new business, do an exact name match against `businesses.name`. If found, add the new location to the existing business and increment `location_count` + set `is_multi_location = True`.
- **Pre-filter:** The dedup check happens before the expensive Place Details API call, saving money.

### Multi-Location Tracking

When a second location is found for an existing business name:
1. `location_count` is incremented
2. `is_multi_location` is set to `True`
3. A new row is added to `locations` with the same `business_id`

During enrichment, website scraping adds another detection layer (see section 4).

---

## 4. Enrichment Strategy

### Approach
**HTTP scraping** using `httpx` + `BeautifulSoup`. For each business with a website URL:

1. Fetch the homepage
2. Fetch `/contact`, `/contact-us`, `/about`, `/about-us` (common patterns)
3. Extract data from all fetched pages

### Email Extraction
- Regex: `[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}`
- **Junk filter:** Removes emails from domains like `example.com`, `sentry.io`, `wixpress.com`, `googleapis.com`, `schema.org`, `facebook.com`, `twitter.com`, etc.
- Also filters out emails ending in `.png` or `.jpg` (common false positives from image alt text)
- First email found becomes the primary `email` on the business; additional emails stored in `notes`

### Multi-Location Detection (Website-Based)
Three signals checked:

1. **Link text scanning:** All `<a>` tags are checked for keywords like "locations", "our offices", "find us", "our locations", "office locations", "multiple locations", "visit us", "find a location", "our practices", "clinic locations"
2. **Heading scanning:** All `<h1>`–`<h4>` tags checked for the same keywords
3. **Address pattern counting:** Regex looks for street address patterns (e.g., "123 Main St"). If 3+ distinct address patterns found, flags as multi-location.

When multi-location is detected via website scraping:
- `is_multi_location` → `True`
- `has_expanded_recently` → `True`
- `expansion_notes` → the detection reason
- `lead_tier` → auto-promoted to `"high"`

### Description Extraction
Pulls `<meta name="description">` or `<meta property="og:description">` from homepage, truncated to 500 chars. Stored as `description` on the business.

### Phone/Website
These come from Google Places API (Place Details endpoint), not from scraping. Fields: `formatted_phone_number` and `website`.

---

## 5. Ranking / Prioritization

### Lead Tier System

| Tier | Criteria |
|------|----------|
| **high** | Multi-location practices (detected via duplicate business names in Google Places OR via website scraping). Auto-promoted during enrichment. |
| **medium** | Default tier for all new businesses. Established single-location practices. |
| **low** | Manually set. Small, new, or uncertain fit. |
| **skip** | Manually set. Not a good fit. |

### Sorting
`report.py` sorts by `location_count DESC`, then `lead_tier`. Businesses with the most locations appear first. The CSV export follows the same ordering.

### Signals Used
- **Location count** (strongest signal): More locations = bigger operation = more likely to need additional space
- **Multi-location boolean**: Binary flag for quick filtering
- **Has expanded recently**: Detected via website "locations" pages
- **Google rating + review count**: Available per-location for context but not used for automated ranking

---

## 6. Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3 |
| Data source | Google Places API (Text Search + Place Details) |
| Database | Supabase (hosted PostgreSQL) |
| Database client | `supabase-py` v2.11.0 |
| Google Maps client | `googlemaps` v2.2.0 (official Python client) |
| Web scraping | `httpx` v0.27.0 + `beautifulsoup4` v4.12.3 |
| Configuration | `python-dotenv` v1.0.1 |
| CLI output | `rich` v13.9.4 (progress bars, tables, colored output) |
| Schema management | Supabase migrations (applied via MCP tool) |

---

## 7. Current State

### What's Done
- ✅ Supabase project created and schema deployed (3 tables, 3 enums, 8 indexes, 1 trigger)
- ✅ `config.py` — full search grid and category definitions
- ✅ `collect.py` — complete with pagination handling, dedup, exclusion zone filtering, progress bar, dry-run mode, practice-type filtering
- ✅ `enrich.py` — complete with email extraction, multi-location detection, description pulling
- ✅ `report.py` — complete with summary stats, top-N table, CSV export
- ✅ All files saved to user's workspace folder

### What's Not Yet Done
- ⬜ **Actually running the collection** — scripts are written but haven't been executed yet (requires user to set up `.env` with their Google API key and Supabase service key, then run locally or via Claude Code)
- ⬜ **UI/dashboard** — planned as a future phase; Supabase backend is ready for it
- ⬜ **Drive time calculation** — `drive_time_minutes` field exists in schema but is not populated (would require Google Distance Matrix API, additional cost)
- ⬜ **Advanced name matching** — business dedup uses exact name match only. "Asheville Dental" and "Asheville Dental Group" would be treated as separate businesses. Fuzzy matching could improve this.
- ⬜ **Email verification** — extracted emails are not validated (no MX record check or deliverability test)
- ⬜ **Outreach tracking UI** — `outreach_status`, `outreach_notes`, `last_contacted_at` fields exist but there's no interface for updating them yet

### Known Limitations
- **Google Places API returns max 60 results per query** (3 pages × 20). For very common categories like "dentist" in a 5km radius, some results may be missed. The overlapping grid mitigates this.
- **Business name matching is exact only.** Businesses with slightly different names across locations (e.g., "Blue Ridge PT - Asheville" vs "Blue Ridge Physical Therapy") will be created as separate businesses.
- **Website scraping is best-effort.** JavaScript-rendered sites (SPAs) won't return useful HTML via `httpx`. A headless browser (Playwright/Selenium) would improve coverage but adds complexity.
- **No rate limiting backoff** — there's a fixed `time.sleep()` between requests but no exponential backoff on 429 errors.
- **Address parsing is naive** — splits on commas to extract city/state/zip. Works for standard US addresses but may fail on unusual formatting.

---

## 8. Cost Estimate

### Google Places API

| Endpoint | Cost per call | Estimated calls | Estimated cost |
|----------|--------------|-----------------|----------------|
| Text Search | $0.032 per call | ~560 searches (40 categories × 14 zones) + pagination ≈ 800 | ~$25 |
| Place Details | $0.017 per call | ~500-1500 unique places | ~$8-25 |
| **Total** | | | **~$33-50** |

Google provides **$200/month free credit** for Maps Platform, so this should be fully covered by the free tier.

### Supabase
Free tier. No cost.

### Total Estimated Cost
**$0** (within Google's free tier).

Note: If the collection is run multiple times (e.g., iterating on search parameters), costs accumulate. The dedup logic and `search_log` table help avoid re-running the same searches.
