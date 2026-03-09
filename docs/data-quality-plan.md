Implement this plan exactly as specified. Do not re-plan or propose alternatives.

# Data Quality Fixes — Zero Embarrassments

## Context

My father is the audience. He's skeptical of AI, busy, and will lose trust the moment he sees a fake email, a duplicate row, or a doctor's name where a practice name should be. The bar is: he opens this spreadsheet, makes 10 calls, and every single one is a real business with accurate info. Zero embarrassments.

A prior audit found: 57 junk emails, 28 duplicate sets (37 extra rows), 221/452 top prospects with a person's name as Org Name, 84 wrong categories, 34 out-of-scope businesses, and 8 institutional facilities in top_prospects.

I had this plan reviewed by a senior engineer. Below is the corrected, final plan. **Implement it exactly as specified.** Do NOT re-investigate or re-audit — the investigation is done. Just implement, then verify.

---

## Execution Order

Implement in this order. Commit after each part passes its verification step.

1. Part 1: Email cleanup (enrich.py)
2. Part 2: Category fixes (config.py + enrich.py)  
3. Part 3: Org name selection + phone/address grouping (enrich.py)
4. Part 4: Export dedup & filtering (export.py)
5. Re-run `python enrich.py` then `python export.py` (NOT collect.py)
6. Final verification

---

## Part 1: Email Cleanup (enrich.py)

### 1a. Expand SKIP_EMAIL_PATTERNS

Replace the existing `SKIP_EMAIL_PATTERNS` list with:

```python
SKIP_EMAIL_PATTERNS = [
    r'@example\.com',
    r'@sentry',                    # sentry.io, sentry.wixpress.com, sentry-next.wixpress.com
    r'@wix\.com',
    r'@wixpress\.com',
    r'@squarespace\.com',
    r'@wordpress\.com',
    r'@godaddy\.com',
    r'@mailchimp\.com',
    r'@hubspot\.com',
    r'@constantcontact\.com',
    r'noreply@',
    r'no-reply@',
    r'^user@domain\.com$',
    r'^example@',                  # example@email.com, example@domain.com
    r'^your@email\.com$',
    r'^email@email\.com$',
    r'^first\.last@company\.com$',
    r'^test@',
    r'^hi@mystore\.com$',
    r'^xx@',                       # xx@xxxx.xx placeholder pattern
    r'^filler@',
]
```

### 1b. Expand file extension check

In `extract_emails_from_html`, add `.webp` and `.avif` to the endswith tuple:

```python
if email.endswith(('.png', '.jpg', '.gif', '.svg', '.css', '.js', '.webp', '.avif')):
```

### 1c. Add `clean_junk_emails()` function

Add this function to enrich.py. It scans all existing emails in the DB and nulls out junk, avoiding a full re-scrape:

```python
def clean_junk_emails():
    """Remove junk/placeholder emails from existing data."""
    conn = get_connection()
    businesses = conn.execute(
        "SELECT id, email FROM businesses WHERE email IS NOT NULL"
    ).fetchall()
    cleaned = 0
    for biz in businesses:
        email = biz["email"].lower()
        if any(re.search(pat, email) for pat in SKIP_EMAIL_PATTERNS):
            update_email(conn, biz["id"], None)
            cleaned += 1
        elif email.endswith(('.png', '.jpg', '.gif', '.svg', '.css', '.js', '.webp', '.avif')):
            update_email(conn, biz["id"], None)
            cleaned += 1
    conn.commit()
    conn.close()
    print(f"Cleaned {cleaned} junk emails.")
```

Call `clean_junk_emails()` in `run_enrichment()` as a new step BEFORE classification (after drive times, before scraping or after scraping — doesn't matter, just before org detection).

### 1d. Update tests

Add tests for the new email patterns in `test_enrich.py`:
- `test_skips_user_at_domain` — `user@domain.com` → filtered
- `test_skips_example_prefix` — `example@anything.com` → filtered  
- `test_skips_xx_prefix` — `xx@xxxx.xx` → filtered
- `test_skips_wixpress` — `tracking@sentry-next.wixpress.com` → filtered
- `test_skips_mailchimp` — `mc@mailchimp.com` → filtered
- `test_skips_webp_extension` — `image@2x.webp` → filtered
- `test_keeps_real_email` — `info@ashevilledental.com` → NOT filtered (sanity check)

### Verification

```bash
sqlite3 data/leads.db "SELECT email, COUNT(*) FROM businesses WHERE email IS NOT NULL GROUP BY email HAVING COUNT(*) > 2"
```
Should show only real clinic emails (like `info@somepractice.com`), not templates.

---

## Part 2: Category Fixes (config.py + enrich.py)

### 2a. Add non-healthcare types to config.py

Add to `PRIMARY_TYPE_TO_CATEGORY`:
```python
"spa": "cosmetic_spa",
"beauty_salon": "beauty_salon",
"hair_care": "beauty_salon",
"fitness_center": "gym",
"hotel": "hotel",
"store": "retail_store",
"consultant": "consultant",
"corporate_office": "institutional",
```

Add to `BUSINESS_TYPE_TIERS`:
```python
"cosmetic_spa": 0, "beauty_salon": 0, "hotel": 0,
"retail_store": 0, "consultant": 0, "institutional": 0,
```

Add to `CATEGORY_DISPLAY_NAMES`:
```python
"cosmetic_spa": "Cosmetic Spa", "beauty_salon": "Beauty Salon",
"hotel": "Hotel", "retail_store": "Retail Store",
"consultant": "Consultant", "institutional": "Institutional",
```

Add two new config constants:
```python
NON_HEALTHCARE_TYPES = {
    "spa", "beauty_salon", "hair_care", "hotel", "fitness_center",
    "gym", "store", "consultant", "corporate_office",
}

MEDICAL_NAME_KEYWORDS = {
    "medical", "med ", "clinic", "health", "doctor", "physician",
    "dental", "dermatol", "therapy", "ophthalmol", "surgical",
    "orthop", "chiro", "pediatr", "urolog", "cardio", "oncol",
    "neurol", "gastro", "pulmon", "psych", "pharm",
}

INSTITUTIONAL_NAME_PATTERNS = [
    r'\bsurgery center\b',
    r'\bsurgical center\b',
    r'\bimaging center\b',
    r'\bmedical center\b',
    r'\bregional hospital\b',
]
```

### 2b. Restructure `classify_business_type()` in enrich.py

Replace the current function with a 5-step classification:

```python
def classify_business_type(business):
    """
    Classify a business into a category. Priority chain:
    1. Hospital system domain check
    2. Primary type veto for non-healthcare (spa, salon, hotel, gym)
    3. Search query keyword match
    4. Name-based corrections for common misclassifications
    5. Primary type fallback
    """
    # Step 1: Hospital system domain
    domain = extract_domain(business["website"])
    if domain and domain in HOSPITAL_SYSTEM_DOMAINS:
        return "hospital_system"

    name_lower = (business["name"] or "").lower()
    primary_type = business["primary_type"] or ""

    # Step 2: Primary type veto — non-healthcare types
    # If Google says it's a spa/salon/hotel/gym AND the name doesn't contain
    # medical keywords, trust Google's typing over our search query match.
    if primary_type in NON_HEALTHCARE_TYPES:
        has_medical_keyword = any(kw in name_lower for kw in MEDICAL_NAME_KEYWORDS)
        if not has_medical_keyword:
            return PRIMARY_TYPE_TO_CATEGORY.get(primary_type, "cosmetic_spa")

    # Step 3: Search query keyword match (existing logic)
    search_query = (business["search_query"] or "").lower()
    category = None
    for keyword, cat in SEARCH_QUERY_TO_CATEGORY:
        if keyword in search_query:
            category = cat
            break

    # Step 4: Name-based corrections
    if category:
        # Oral surgeons found via orthodontist query
        if re.search(r'oral surg|maxillofacial', name_lower):
            category = "oral_surgery"
        # Eye care classified as medical_clinic
        elif category == "medical_clinic" and re.search(r'\beye\b|vision|optical|ophthalm', name_lower):
            category = "optometry"
        # PT classified as medical_clinic
        elif category == "medical_clinic" and re.search(r'physical therapy|physiotherapy', name_lower):
            category = "physical_therapy"
    
    if category:
        # Institutional facility check (overrides category)
        if re.search(r'|'.join(INSTITUTIONAL_NAME_PATTERNS), name_lower):
            # But not if it's part of a practice name like "oral surgery center"
            if not re.search(r'oral|dental|eye|dermatol|pain|spine', name_lower):
                return "institutional"
        return category

    # Step 5: Primary type fallback
    if primary_type in PRIMARY_TYPE_TO_CATEGORY:
        return PRIMARY_TYPE_TO_CATEGORY[primary_type]

    return "medical_clinic"
```

Import the new config constants at the top of enrich.py:
```python
from config import (
    ...,
    NON_HEALTHCARE_TYPES,
    MEDICAL_NAME_KEYWORDS,
    INSTITUTIONAL_NAME_PATTERNS,
)
```

### 2c. Update tests

Add tests to `test_enrich.py` for the new classification logic:
- `test_spa_primary_type_vetoed` — primary_type="spa", name="Illusions Day Spa" → cosmetic_spa
- `test_medical_spa_not_vetoed` — primary_type="beauty_salon", name="Mountain Radiance Medical Spa", search_query="med spa in Asheville NC" → med_spa
- `test_oral_surgeon_corrected` — search_query="orthodontist in Asheville NC", name="Asheville Oral & Maxillofacial Surgery" → oral_surgery
- `test_hotel_vetoed` — primary_type="hotel", name="Omni Grove Park Inn & Spa" → hotel
- `test_eye_care_corrected` — search_query="medical clinic in Asheville NC", name="Blue Ridge Eye Center" → optometry
- `test_institutional_surgery_center` — name="Asheville Surgery Center" → institutional
- `test_oral_surgery_not_institutional` — name="Blue Ridge Oral Surgery Center" → oral_surgery (not institutional)

### Verification

```bash
sqlite3 data/leads.db "SELECT name, business_category FROM businesses WHERE business_category IN ('cosmetic_spa', 'beauty_salon', 'hotel', 'institutional')" 
```
Should show spas, salons, hotel, surgery centers correctly categorized.

```bash
sqlite3 data/leads.db "SELECT name, business_category FROM businesses WHERE name LIKE '%Oral Surg%'"
```
Should all be `oral_surgery`, not `orthodontist`.

---

## Part 3: Org Grouping + Name Selection (enrich.py)

This is the most important part. The current org detection groups by domain, then by name. This misses the core problem: individual providers at the same practice have separate Google listings with different names and sometimes different/no websites, but they share the same phone number and address.

### 3a. Add `is_provider_name()` and `pick_org_name()`

```python
PROVIDER_SUFFIX_PATTERN = re.compile(
    r',?\s*\b(MD|DDS|DMD|DO|PA-C|PA|NP|FNP|OD|DPM|DC|PT|DPT|'
    r'LCSW|LPC|PhD|PsyD|MAGD|FAGD|MHS|MPT|FACS|RN|APRN|CNM|'
    r'FAAD|FAAOS|Jr|Sr|III|IV)\b'
    r'|^(Dr|Mr|Ms|Mrs)\.?\s',
    re.IGNORECASE
)

def is_provider_name(name):
    """True if name looks like a person (provider) rather than a practice."""
    return bool(PROVIDER_SUFFIX_PATTERN.search(name))

def pick_org_name(names):
    """Pick practice name over provider name. Prefer longest practice name."""
    practice_names = [n for n in names if not is_provider_name(n)]
    if practice_names:
        return max(practice_names, key=len)
    return max(names, key=len)
```

### 3b. Add `normalize_phone()`

```python
def normalize_phone(phone):
    """Strip phone to last 10 digits for comparison."""
    if not phone:
        return None
    digits = re.sub(r'\D', '', phone)
    if len(digits) >= 10:
        return digits[-10:]
    return digits if digits else None
```

### 3c. Rewrite `detect_multi_location_orgs()`

The new function has THREE grouping passes:

1. **Domain grouping** (existing) — businesses sharing a website domain
2. **Phone+address grouping** (NEW) — businesses sharing a phone number AND normalized address that weren't caught by domain grouping. This catches individual providers at the same practice.
3. **Name grouping** (existing) — for remaining no-domain businesses

Here's the key change. After the domain grouping loop and before the name grouping loop, add:

```python
# --- Pass 2: Phone + address grouping for ungrouped businesses ---
# This catches providers at the same practice with different/no websites.
# Key insight: independent practices sharing a building have DIFFERENT phones.
# Providers at the same practice share the SAME phone (one front desk).

ungrouped = conn.execute("""
    SELECT b.id, b.name, b.phone, b.address, b.organization_id, o.location_count
    FROM businesses b
    LEFT JOIN organizations o ON b.organization_id = o.id
    WHERE b.phone IS NOT NULL AND b.phone != ''
""").fetchall()

# Build phone+address groups, but only merge businesses that are currently
# solo entries (org with location_count = 1) or share an org with only 1 member
phone_addr_groups = defaultdict(list)
for biz in ungrouped:
    norm_phone = normalize_phone(biz["phone"])
    norm_addr = normalize_address(biz["address"])
    if norm_phone and norm_addr:
        key = (norm_phone, norm_addr)
        phone_addr_groups[key].append(biz)

for (phone, addr), group in phone_addr_groups.items():
    if len(group) < 2:
        continue
    
    # Collect all unique org_ids in this group
    org_ids = set(biz["organization_id"] for biz in group if biz["organization_id"])
    
    if len(org_ids) <= 1 and all(biz["organization_id"] for biz in group):
        # All already in the same org — nothing to do
        continue
    
    # Pick the best org name from all names in this group
    all_names = [biz["name"] for biz in group]
    best_name = pick_org_name(all_names)
    
    # Find if any existing org should be the target (prefer the one with practice name)
    target_org_id = None
    if org_ids:
        # Use existing org, update its name
        target_org_id = list(org_ids)[0]  # pick one
        conn.execute("UPDATE organizations SET name = ? WHERE id = ?", 
                     (best_name, target_org_id))
    else:
        # Create new org
        domain = extract_domain(group[0]["website"]) if group[0]["website"] else None
        target_org_id = create_organization(conn, best_name, domain,
                                           location_count=len(group))
    
    # Merge: point all businesses to the target org
    for biz in group:
        if biz["organization_id"] != target_org_id:
            update_organization(conn, biz["id"], target_org_id)
    
    # Delete orphaned orgs
    for old_org_id in org_ids:
        if old_org_id != target_org_id:
            remaining = conn.execute(
                "SELECT COUNT(*) FROM businesses WHERE organization_id = ?",
                (old_org_id,)
            ).fetchone()[0]
            if remaining == 0:
                conn.execute("DELETE FROM organizations WHERE id = ?", (old_org_id,))
    
    # Update location count and distinct locations
    total = conn.execute(
        "SELECT COUNT(*) FROM businesses WHERE organization_id = ?",
        (target_org_id,)
    ).fetchone()[0]
    conn.execute("UPDATE organizations SET location_count = ? WHERE id = ?",
                (total, target_org_id))
    
    # Recalculate distinct addresses
    addrs = conn.execute(
        "SELECT address FROM businesses WHERE organization_id = ?",
        (target_org_id,)
    ).fetchall()
    distinct = len(set(normalize_address(a["address"]) for a in addrs))
    update_org_distinct_locations(conn, target_org_id, distinct)
    
    print(f"  Phone+addr merge: {best_name} ({phone[-4:]}) — "
          f"{len(group)} entries, {distinct} distinct locations")

conn.commit()
```

Also replace `min([b["name"] for b in group], key=len)` with `pick_org_name([b["name"] for b in group])` in both the domain grouping loop (line ~529) and the name grouping loop (line ~576).

### 3d. Update tests

Add tests to `test_enrich.py`:
- `test_is_provider_name_with_md` — "Jordan S Masters, MD" → True
- `test_is_provider_name_with_dds` — "John Smith, DDS" → True  
- `test_is_provider_name_with_dr_prefix` — "Dr. Jane Doe" → True
- `test_is_provider_name_practice` — "Asheville Eye Associates" → False
- `test_is_provider_name_plain_practice` — "Blue Ridge Dental" → False
- `test_pick_org_name_prefers_practice` — ["Jordan S Masters, MD", "Asheville Eye Associates"] → "Asheville Eye Associates"
- `test_pick_org_name_longest_practice` — ["Eye Associates", "Asheville Eye Associates"] → "Asheville Eye Associates"
- `test_pick_org_name_all_providers` — ["John Smith, MD", "Jane Doe, MD"] → "Jane Doe, MD" (longest)
- `test_normalize_phone_strips_formatting` — "(828) 555-1234" → "8285551234"
- `test_normalize_phone_with_country_code` — "+1-828-555-1234" → "8285551234"
- `test_normalize_phone_none` — None → None
- `test_normalize_phone_empty` — "" → None

### Verification

```bash
sqlite3 data/leads.db "SELECT name FROM organizations WHERE name LIKE '%MD%' OR name LIKE '%DDS%' OR name LIKE '%DO' OR name LIKE '%, PA-C'"
```
Should return 0 rows (or very few genuine solo practices).

Check known cases:
```bash
sqlite3 data/leads.db "SELECT o.name, o.location_count, o.distinct_location_count FROM organizations o JOIN businesses b ON b.organization_id = o.id WHERE b.name LIKE '%Asheville Eye%' LIMIT 1"
```
Should show org name = "Asheville Eye Associates" (or similar practice name), not "Jordan S Masters, MD".

---

## Part 4: Export Dedup & Filtering (export.py)

### 4a. One row per org in `top_prospects.csv`

Import `is_provider_name` from enrich at the top of export.py.

Add a representative selection function:

```python
def pick_representative(group):
    """Pick the best representative row for an org group.
    
    Prefer: practice name > has email > 10-25 min drive > highest rating > most reviews.
    """
    def score(lead):
        return (
            0 if is_provider_name(lead["name"]) else 1,  # practice name preferred
            1 if lead["email"] else 0,
            drive_time_sort_score(lead["drive_time_minutes"]),
            lead["rating"] or 0,
            lead["rating_count"] or 0,
        )
    return max(group, key=score)
```

### 4b. Add phone-number dedup as safety net

Modify `export_top_prospects_csv()`:

```python
MAX_DRIVE_TIME_PROSPECTS = 45

def export_top_prospects_csv(leads):
    """Export Tier A + B leads, deduplicated to one row per practice."""
    top = [l for l in leads if l["tier"] in ("A", "B")]
    
    # Filter out far-flung locations
    top = [l for l in top if l["drive_time_minutes"] is None 
           or l["drive_time_minutes"] <= MAX_DRIVE_TIME_PROSPECTS]
    
    # Dedup by organization_id
    from collections import defaultdict
    org_groups = defaultdict(list)
    for lead in top:
        key = lead.get("organization_id") or f"solo_{lead['id']}"
        org_groups[key].append(lead)
    
    deduped = []
    for group in org_groups.values():
        deduped.append(pick_representative(group))
    
    # Safety net: phone-number dedup for anything org detection missed
    phone_seen = {}
    final = []
    for lead in deduped:
        phone = normalize_phone(lead.get("phone"))
        if phone and phone in phone_seen:
            # Skip — already have a row for this phone number
            continue
        if phone:
            phone_seen[phone] = True
        final.append(lead)
    
    # Re-sort after dedup
    tier_order = {"A": 0, "B": 1, "C": 2, "D": 3}
    final.sort(key=lambda l: (
        tier_order.get(l["tier"], 4),
        -(l["distinct_location_count"] or 1),
        -drive_time_sort_score(l["drive_time_minutes"]),
        -(1 if l["email"] else 0),
        -(l["rating"] or 0),
        -(l["rating_count"] or 0),
    ))
    
    filepath = os.path.join(OUTPUT_DIR, "top_prospects.csv")
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(LEAD_CSV_HEADERS)
        for lead in final:
            writer.writerow(lead_to_row(lead))
    print(f"CSV exported: {filepath} ({len(final)} unique practices, "
          f"deduped from {len(top)} entries)")
```

Import `normalize_phone` from enrich at the top of export.py, alongside `is_provider_name`.

### 4c. Update the `get_all_leads()` query

The current query doesn't include `organization_id` or `id` in the SELECT. Add them so the dedup can use them:

```sql
SELECT
    b.id, b.name, b.address, b.phone, b.website, b.email,
    b.description, b.rating, b.rating_count, b.primary_type,
    b.business_category, b.drive_time_minutes, b.drive_zone,
    b.distance_miles, b.search_query, b.multi_location_signals,
    b.organization_id,
    o.name as org_name, o.website_domain as org_domain,
    o.location_count, o.distinct_location_count
FROM businesses b
LEFT JOIN organizations o ON b.organization_id = o.id
```

(Add `b.organization_id` to the SELECT — it's already joined but not selected.)

### 4d. Explicit drive time threshold comment

In `compute_tier()`, add a comment on the `< 10` check:

```python
# Tier D: already a neighbor (strictly < 10 min; exactly 10.0 = included)
if drive_min is not None and drive_min < 10:
    return "D"
```

### 4e. Update tests

Add tests to `test_export.py`:
- `test_pick_representative_prefers_practice_name` 
- `test_pick_representative_prefers_email`
- `test_drive_time_max_filter` — lead with 50 min drive time excluded from top prospects

### Verification

```bash
# No phone number should appear twice in top_prospects
python3 -c "
import csv
phones = {}
with open('data/top_prospects.csv') as f:
    for row in csv.DictReader(f):
        p = row['Phone']
        if p:
            phones[p] = phones.get(p, 0) + 1
dupes = {k:v for k,v in phones.items() if v > 1}
print(f'Duplicate phones: {len(dupes)}')
for p, c in list(dupes.items())[:5]:
    print(f'  {p}: {c} times')
"
```
Should print `Duplicate phones: 0`.

---

## Final Verification Checklist

After running `python enrich.py` and `python export.py`:

1. **Zero junk emails**: `sqlite3 data/leads.db "SELECT email FROM businesses WHERE email LIKE '%example%' OR email LIKE '%user@domain%' OR email LIKE '%xx@%' OR email LIKE '%@wixpress%'"` → 0 rows
2. **Zero duplicate practices in top_prospects**: Sort by phone — no phone appears twice
3. **Practice names as org names**: `sqlite3 data/leads.db "SELECT name FROM organizations WHERE name LIKE '%MD%' OR name LIKE '%DDS%' OR name LIKE '%DO' OR name LIKE '%, PA-C'"` → 0 rows
4. **No non-healthcare**: Search top_prospects for "spa", "salon", "hotel", "gym" → zero unless "med spa"
5. **No far-flung**: No drive times >45 min in top_prospects
6. **Tier summary printed**: Tier A should be ~30-80 (down from 164 after dedup + filtering)
7. **Spot-check known cases**:
   - Asheville Eye → org name "Asheville Eye Associates" (not "Jordan S Masters, MD"), 1 row in top_prospects
   - Movement for Life → org name "Movement for Life Physical Therapy" (not "Taylor Leiby"), 1 row
   - Comprehensive Pain → org name "Comprehensive Pain Consultants of the Carolinas" (not "Dr. Erik Dahl"), 1 row
   - Omni Grove Park Inn → Tier D, not in top_prospects
8. **All tests pass**: `python -m pytest tests/ -v`

---

## Files Modified

- **config.py**: Add non-healthcare types to PRIMARY_TYPE_TO_CATEGORY, BUSINESS_TYPE_TIERS, CATEGORY_DISPLAY_NAMES. Add NON_HEALTHCARE_TYPES, MEDICAL_NAME_KEYWORDS, INSTITUTIONAL_NAME_PATTERNS constants.
- **enrich.py**: Expand SKIP_EMAIL_PATTERNS. Add clean_junk_emails(), is_provider_name(), pick_org_name(), normalize_phone(). Restructure classify_business_type() with 5-step chain. Add phone+address merge pass to detect_multi_location_orgs(). Replace min(names, key=len) with pick_org_name().
- **export.py**: Import is_provider_name, normalize_phone from enrich. Add pick_representative(). Rewrite export_top_prospects_csv() with org dedup + phone dedup safety net + drive time max filter. Add b.organization_id to get_all_leads() query. Add explicit comment on <10 threshold.
- **tests/test_enrich.py**: Add tests for new email patterns, classification, provider name detection, phone normalization.
- **tests/test_export.py**: Add tests for representative selection, drive time filtering.

**Do NOT modify**: collect.py, db.py. Do NOT re-run collect.py.
