"""Enrich businesses with drive times, organization detection, and website scraping."""

import json
import math
import re
import sys
import time
from collections import defaultdict
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from config import (
    GOOGLE_API_KEY,
    PROPERTY_LAT,
    PROPERTY_LNG,
    DRIVE_ZONES,
    ROUTES_MATRIX_URL,
    SEARCH_QUERY_TO_CATEGORY,
    PRIMARY_TYPE_TO_CATEGORY,
    HOSPITAL_SYSTEM_DOMAINS,
)
from db import (
    get_connection,
    get_businesses_without_drive_time,
    get_all_businesses,
    update_drive_time,
    update_organization,
    update_email,
    update_description,
    update_multi_location_signals,
    update_business_category,
    update_org_distinct_locations,
    create_organization,
    migrate_db,
    get_stats,
)


# ── Drive Time Calculation ──────────────────────────────────────────────


def haversine_miles(lat1, lng1, lat2, lng2):
    """Straight-line distance in miles between two coordinates."""
    R = 3958.8  # Earth's radius in miles
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def classify_drive_zone(minutes):
    """Return the drive zone label for a given number of minutes."""
    for threshold, label in DRIVE_ZONES:
        if minutes < threshold:
            return label
    return "20+ min"


def compute_drive_times(businesses):
    """
    Use Google Routes Compute Route Matrix to get drive times from the property
    to a batch of businesses. Max 25 destinations per request.

    Returns: dict mapping business_id -> (drive_time_minutes, distance_miles)
    """
    if not businesses:
        return {}

    origins = [{
        "waypoint": {
            "location": {
                "latLng": {
                    "latitude": PROPERTY_LAT,
                    "longitude": PROPERTY_LNG,
                }
            }
        }
    }]

    destinations = []
    for biz in businesses:
        destinations.append({
            "waypoint": {
                "location": {
                    "latLng": {
                        "latitude": biz["lat"],
                        "longitude": biz["lng"],
                    }
                }
            }
        })

    body = {
        "origins": origins,
        "destinations": destinations,
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_UNAWARE",
    }

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": "originIndex,destinationIndex,duration,distanceMeters,status",
    }

    resp = requests.post(ROUTES_MATRIX_URL, json=body, headers=headers)

    if resp.status_code != 200:
        print(f"  Routes API error {resp.status_code}: {resp.text[:200]}")
        return {}

    results = {}
    for entry in resp.json():
        if entry.get("status", {}).get("code", 0) != 0 and "duration" not in entry:
            continue
        dest_idx = entry.get("destinationIndex", 0)
        duration_str = entry.get("duration", "0s")
        # Duration comes as "XXXs" (seconds string)
        seconds = int(duration_str.replace("s", ""))
        minutes = seconds / 60.0
        distance_m = entry.get("distanceMeters", 0)
        distance_miles = distance_m / 1609.34

        biz = businesses[dest_idx]
        results[biz["id"]] = (round(minutes, 1), round(distance_miles, 1))

    return results


def calculate_all_drive_times():
    """Calculate drive times for all businesses that don't have one yet."""
    conn = get_connection()
    businesses = get_businesses_without_drive_time(conn)

    if not businesses:
        print("All businesses already have drive times.")
        conn.close()
        return

    print(f"Calculating drive times for {len(businesses)} businesses...")

    batch_size = 25
    processed = 0

    for i in range(0, len(businesses), batch_size):
        batch = businesses[i:i + batch_size]
        print(f"  Batch {i // batch_size + 1}: {len(batch)} businesses...")

        results = compute_drive_times(batch)

        for biz in batch:
            if biz["id"] in results:
                minutes, miles = results[biz["id"]]
                zone = classify_drive_zone(minutes)
                update_drive_time(conn, biz["id"], minutes, zone, miles)
                processed += 1
            else:
                # Fallback: use straight-line distance as rough estimate
                if biz["lat"] and biz["lng"]:
                    miles = haversine_miles(PROPERTY_LAT, PROPERTY_LNG,
                                           biz["lat"], biz["lng"])
                    # Rough estimate: 1.4x straight-line distance at 30mph
                    est_minutes = (miles * 1.4) / 30 * 60
                    zone = classify_drive_zone(est_minutes)
                    update_drive_time(conn, biz["id"], round(est_minutes, 1),
                                     zone, round(miles, 1))
                    processed += 1

        conn.commit()
        time.sleep(0.3)

    conn.close()
    print(f"Drive times calculated for {processed} businesses.")


# ── Multi-Location Detection ────────────────────────────────────────────


def extract_domain(url):
    """Extract the base domain from a URL."""
    if not url:
        return None
    try:
        parsed = urlparse(url if url.startswith("http") else f"https://{url}")
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain if domain else None
    except Exception:
        return None


def normalize_name(name):
    """Normalize a business name for fuzzy matching."""
    name = name.lower()
    for suffix in [", pc", ", pa", ", pllc", ", llc", ", inc", ", md",
                   ", dds", ", dmd", ", do", ", od", " pc", " pa", " pllc"]:
        name = name.replace(suffix, "")
    name = re.sub(r'\s*[-–—|]\s*(asheville|arden|hendersonville|fletcher|'
                  r'weaverville|black mountain|brevard|waynesville|canton|'
                  r'north|south|east|west|downtown).*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[^a-z0-9\s]', '', name)
    return name.strip()


def normalize_address(address):
    """
    Normalize address to canonical building key for dedup within an org.

    Google Places format: "123 Main St Suite 200, Asheville, NC 28801, USA"
    Sometimes: "Building Name, 123 Main St, Asheville, NC 28801, USA"
    Returns: "{number} {street}, {city}" as canonical key.
    """
    if not address:
        return ""

    addr = address.lower().strip()
    # Remove country suffix
    addr = re.sub(r',?\s*usa?\s*$', '', addr)

    parts = [p.strip() for p in addr.split(',')]

    # Find the street part (first comma-segment starting with a digit)
    street = None
    city_idx = None
    for i, part in enumerate(parts):
        if re.match(r'\d', part.strip()):
            street = part.strip()
            city_idx = i + 1
            break

    if street is None:
        # No numbered street found, return first two parts as-is
        return ', '.join(parts[:2]) if len(parts) >= 2 else addr

    city = parts[city_idx].strip() if city_idx and city_idx < len(parts) else ""

    # Strip suite/unit/floor designators
    street = re.sub(
        r'\s*[,.]?\s*(?:suite|ste|unit|apt|#|room|rm|bldg|building)\s*\.?\s*[\w-]*',
        '', street
    )
    street = re.sub(r'\s*,?\s*\d+(?:st|nd|rd|th)\s+(?:floor|fl)\b', '', street)

    # Normalize letter suffixes on building number: "75a" or "75 b" → "75"
    street = re.sub(r'^(\d+)\s*[a-z]\b', r'\1', street)

    # Standardize street type abbreviations
    for full, abbr in [('street', 'st'), ('avenue', 'ave'), ('road', 'rd'),
                        ('drive', 'dr'), ('boulevard', 'blvd'), ('lane', 'ln'),
                        ('court', 'ct'), ('place', 'pl'), ('parkway', 'pkwy'),
                        ('highway', 'hwy'), ('circle', 'cir')]:
        street = re.sub(r'\b' + full + r'\b', abbr, street)

    street = ' '.join(street.split())
    return f"{street}, {city}" if city else street


def classify_business_type(business):
    """
    Classify a business into a category using search_query keywords first,
    then hospital system domain check, then primary_type fallback.
    """
    domain = extract_domain(business["website"])
    if domain and domain in HOSPITAL_SYSTEM_DOMAINS:
        return "hospital_system"

    search_query = (business["search_query"] or "").lower()
    for keyword, category in SEARCH_QUERY_TO_CATEGORY:
        if keyword in search_query:
            return category

    primary_type = business["primary_type"] or ""
    if primary_type in PRIMARY_TYPE_TO_CATEGORY:
        return PRIMARY_TYPE_TO_CATEGORY[primary_type]

    return "medical_clinic"


def classify_all_business_types():
    """Classify all businesses into categories."""
    conn = get_connection()
    businesses = get_all_businesses(conn)

    for biz in businesses:
        category = classify_business_type(biz)
        update_business_category(conn, biz["id"], category)

    conn.commit()

    counts = conn.execute("""
        SELECT business_category, COUNT(*) as cnt
        FROM businesses WHERE business_category IS NOT NULL
        GROUP BY business_category ORDER BY cnt DESC
    """).fetchall()

    print(f"Classified {len(businesses)} businesses:")
    for row in counts:
        print(f"  {row['business_category']}: {row['cnt']}")

    conn.close()


MULTI_LOCATION_KEYWORDS = [
    "locations", "our offices", "find us", "our locations",
    "clinic locations", "office locations", "multiple locations",
    "our practices", "find a location",
]

# Regex to detect street addresses (e.g., "123 Main St")
ADDRESS_PATTERN = re.compile(r'\b\d{1,5}\s+[A-Z][a-z]+\s+(?:St|Ave|Rd|Dr|Blvd|Ln|Way|Ct|Pl|Pkwy|Hwy)\b')


def scrape_website(website_url):
    """
    Single-pass website scraping. Visits homepage + /contact + /about and extracts:
    1. Email addresses
    2. Meta description
    3. Multi-location signals (link text, headings, address count)

    Returns: (email, description, signals_list)
    """
    if not website_url:
        return None, None, []

    if not website_url.startswith("http"):
        website_url = f"https://{website_url}"

    paths_to_try = ["", "/contact", "/contact-us", "/about", "/about-us"]
    all_emails = []
    description = None
    signals = []
    addresses_found = set()

    for path in paths_to_try:
        url = website_url.rstrip("/") + path
        try:
            resp = requests.get(url, timeout=8, headers={
                "User-Agent": "Mozilla/5.0 (compatible; LeadGen/1.0)"
            })
            if resp.status_code != 200:
                continue
        except Exception:
            continue

        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        # --- Email extraction ---
        emails = extract_emails_from_html(html)
        all_emails.extend(emails)

        # --- Meta description (take from first page that has one) ---
        if not description:
            meta = (soup.find("meta", attrs={"name": "description"}) or
                    soup.find("meta", attrs={"property": "og:description"}))
            if meta and meta.get("content"):
                description = meta["content"].strip()[:500]

        # --- Multi-location signals ---
        # Scan <a> tags for location keywords
        for a_tag in soup.find_all("a"):
            link_text = (a_tag.get_text() or "").strip().lower()
            for keyword in MULTI_LOCATION_KEYWORDS:
                if keyword in link_text:
                    signals.append({"source": "website_link", "text": a_tag.get_text().strip(), "page": path or "/"})
                    break

        # Scan headings for location keywords
        for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
            heading_text = (tag.get_text() or "").strip().lower()
            for keyword in MULTI_LOCATION_KEYWORDS:
                if keyword in heading_text:
                    signals.append({"source": "heading", "text": tag.get_text().strip(), "page": path or "/"})
                    break

        # Count distinct street addresses
        found = ADDRESS_PATTERN.findall(html)
        addresses_found.update(found)

    # 3+ distinct addresses suggests multi-location
    if len(addresses_found) >= 3:
        signals.append({"source": "address_count", "count": len(addresses_found)})

    # Deduplicate signals by text
    seen = set()
    unique_signals = []
    for s in signals:
        key = s.get("text", s.get("count", ""))
        if key not in seen:
            seen.add(key)
            unique_signals.append(s)

    email = list(set(all_emails))[0] if all_emails else None
    return email, description, unique_signals


# ── Email Extraction Helper ────────────────────────────────────────────


EMAIL_REGEX = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
)

SKIP_EMAIL_PATTERNS = [
    r'@example\.com',
    r'@sentry\.io',
    r'@wix\.com',
    r'@squarespace\.com',
    r'noreply@',
    r'no-reply@',
]


def extract_emails_from_html(html):
    """Extract email addresses from HTML content."""
    emails = EMAIL_REGEX.findall(html)
    filtered = []
    for email in emails:
        email = email.lower()
        if any(re.search(pat, email) for pat in SKIP_EMAIL_PATTERNS):
            continue
        if email.endswith(('.png', '.jpg', '.gif', '.svg', '.css', '.js')):
            continue
        filtered.append(email)
    return list(set(filtered))


def scrape_all_websites():
    """Single-pass website scraping for all businesses with a website."""
    conn = get_connection()
    businesses = conn.execute(
        """SELECT id, name, website FROM businesses
           WHERE website IS NOT NULL AND website != ''
           AND (email IS NULL OR description IS NULL OR multi_location_signals IS NULL)"""
    ).fetchall()

    if not businesses:
        print("No businesses need website scraping.")
        conn.close()
        return

    print(f"Scraping websites for {len(businesses)} businesses...")

    emails_found = 0
    descriptions_found = 0
    signals_found = 0

    for i, biz in enumerate(businesses):
        if (i + 1) % 20 == 0:
            print(f"  Progress: {i + 1}/{len(businesses)}...")

        email, description, signals = scrape_website(biz["website"])

        if email:
            update_email(conn, biz["id"], email)
            emails_found += 1
        if description:
            update_description(conn, biz["id"], description)
            descriptions_found += 1
        if signals:
            update_multi_location_signals(conn, biz["id"], signals)
            signals_found += 1

        if (i + 1) % 50 == 0:
            conn.commit()

        time.sleep(0.3)  # Be polite

    conn.commit()
    conn.close()
    print(f"Website scraping complete:")
    print(f"  Emails found: {emails_found}/{len(businesses)}")
    print(f"  Descriptions found: {descriptions_found}/{len(businesses)}")
    print(f"  Multi-location signals: {signals_found}/{len(businesses)}")


def detect_multi_location_orgs():
    """
    Group businesses into organizations and count distinct physical locations.

    Three cases for address dedup:
    1. Same address, DIFFERENT domains → separate orgs (independent practices). No dedup.
    2. Same address, SAME domain → same org, one location. Dedup via address normalization.
    3. Different addresses, SAME domain → same org, multiple locations.
    """
    conn = get_connection()

    # Clear existing orgs for clean re-run (org data is fully derived from businesses)
    conn.execute("UPDATE businesses SET organization_id = NULL")
    conn.execute("DELETE FROM organizations")
    conn.commit()

    businesses = get_all_businesses(conn)

    # Group by website domain
    domain_groups = defaultdict(list)
    no_domain = []

    for biz in businesses:
        domain = extract_domain(biz["website"])
        if domain:
            domain_groups[domain].append(biz)
        else:
            no_domain.append(biz)

    # Group by normalized name for businesses without websites
    name_groups = defaultdict(list)
    for biz in no_domain:
        norm = normalize_name(biz["name"])
        name_groups[norm].append(biz)

    orgs_created = 0

    # Create organizations for domain groups
    for domain, group in domain_groups.items():
        org_name = min([b["name"] for b in group], key=len)
        location_count = len(group)

        # Count distinct physical locations by normalized address
        addr_map = defaultdict(list)
        for biz in group:
            norm_addr = normalize_address(biz["address"])
            addr_map[norm_addr].append(biz)
        distinct_count = len(addr_map)

        # Lat/lng proximity warning: flag if different normalized addresses are within 100m
        addrs = list(addr_map.keys())
        for i in range(len(addrs)):
            for j in range(i + 1, len(addrs)):
                biz_i = addr_map[addrs[i]][0]
                biz_j = addr_map[addrs[j]][0]
                if biz_i["lat"] and biz_i["lng"] and biz_j["lat"] and biz_j["lng"]:
                    dist = haversine_miles(biz_i["lat"], biz_i["lng"],
                                           biz_j["lat"], biz_j["lng"])
                    if dist < 0.062:  # ~100m
                        print(f"  Warning: {org_name} has close addresses ({int(dist * 1609)}m):")
                        print(f"    {addrs[i]}")
                        print(f"    {addrs[j]}")

        has_website_signals = any(biz["multi_location_signals"] for biz in group)

        notes = None
        if domain in HOSPITAL_SYSTEM_DOMAINS:
            notes = "Hospital/health system"
        if location_count == 1 and has_website_signals:
            notes = (notes + "; " if notes else "") + "Multi-location via website signals"

        org_id = create_organization(conn, org_name, domain,
                                     location_count=location_count, notes=notes)
        update_org_distinct_locations(conn, org_id, distinct_count)

        for biz in group:
            update_organization(conn, biz["id"], org_id)

        if location_count >= 2 or has_website_signals:
            orgs_created += 1
            print(f"  Multi-location: {org_name} ({domain}) — "
                  f"{distinct_count} distinct / {location_count} entries")

    # Create organizations for name groups
    for norm_name, group in name_groups.items():
        if len(group) >= 2:
            org_name = min([b["name"] for b in group], key=len)
            addr_map = defaultdict(list)
            for biz in group:
                norm_addr = normalize_address(biz["address"])
                addr_map[norm_addr].append(biz)
            distinct_count = len(addr_map)

            org_id = create_organization(conn, org_name, None,
                                         location_count=len(group),
                                         notes="Matched by name similarity")
            update_org_distinct_locations(conn, org_id, distinct_count)
            for biz in group:
                update_organization(conn, biz["id"], org_id)
            orgs_created += 1
            print(f"  Multi-location (name match): {org_name} — "
                  f"{distinct_count} distinct / {len(group)} entries")

    conn.commit()
    conn.close()
    print(f"\nOrganizations: {orgs_created} multi-location groups found.")


# ── Main ────────────────────────────────────────────────────────────────


def run_enrichment():
    """Run all enrichment steps."""
    if not GOOGLE_API_KEY:
        print("ERROR: GOOGLE_API_KEY not set.")
        sys.exit(1)

    migrate_db()

    print("=" * 50)
    print("STEP 1: Calculate drive times")
    print("=" * 50)
    calculate_all_drive_times()

    print("\n" + "=" * 50)
    print("STEP 2: Scrape websites (email + description + multi-location signals)")
    print("=" * 50)
    scrape_all_websites()

    print("\n" + "=" * 50)
    print("STEP 3: Classify business types")
    print("=" * 50)
    classify_all_business_types()

    print("\n" + "=" * 50)
    print("STEP 4: Detect multi-location organizations")
    print("=" * 50)
    detect_multi_location_orgs()

    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    conn = get_connection()
    stats = get_stats(conn)
    conn.close()

    print(f"Total businesses: {stats['total_businesses']}")
    print(f"With drive times: {stats['with_drive_time']}")
    print(f"Multi-location organizations: {stats['multi_location_orgs']}")
    print("By drive zone:")
    for zone, count in stats["by_zone"]:
        print(f"  {zone}: {count}")


if __name__ == "__main__":
    run_enrichment()
