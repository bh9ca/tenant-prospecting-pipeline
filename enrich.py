"""Enrich businesses with drive times, organization detection, and email extraction."""

import math
import re
import sys
import time
from collections import defaultdict
from urllib.parse import urlparse

import requests

from config import (
    GOOGLE_API_KEY,
    PROPERTY_LAT,
    PROPERTY_LNG,
    DRIVE_ZONES,
    ROUTES_MATRIX_URL,
)
from db import (
    get_connection,
    get_businesses_without_drive_time,
    get_all_businesses,
    update_drive_time,
    update_organization,
    update_email,
    create_organization,
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
        # Strip www.
        if domain.startswith("www."):
            domain = domain[4:]
        return domain if domain else None
    except Exception:
        return None


def normalize_name(name):
    """Normalize a business name for fuzzy matching."""
    name = name.lower()
    # Remove common suffixes
    for suffix in [", pc", ", pa", ", pllc", ", llc", ", inc", ", md",
                   ", dds", ", dmd", ", do", ", od", " pc", " pa", " pllc"]:
        name = name.replace(suffix, "")
    # Remove location qualifiers
    name = re.sub(r'\s*[-–—|]\s*(asheville|arden|hendersonville|fletcher|'
                  r'weaverville|black mountain|brevard|waynesville|canton|'
                  r'north|south|east|west|downtown).*$', '', name, flags=re.IGNORECASE)
    # Remove non-alphanumeric
    name = re.sub(r'[^a-z0-9\s]', '', name)
    return name.strip()


def detect_multi_location_orgs():
    """Group businesses into organizations based on website domain and name similarity."""
    conn = get_connection()
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

    # Create organizations for domain groups with multiple locations
    for domain, group in domain_groups.items():
        if len(group) >= 2:
            # Use the shortest name as the org name
            org_name = min([b["name"] for b in group], key=len)
            org_id = create_organization(conn, org_name, domain,
                                         location_count=len(group))
            for biz in group:
                update_organization(conn, biz["id"], org_id)
            orgs_created += 1
            print(f"  Multi-location: {org_name} ({domain}) — {len(group)} locations")
        elif len(group) == 1:
            # Single location, still create org for tracking
            biz = group[0]
            org_id = create_organization(conn, biz["name"], domain, location_count=1)
            update_organization(conn, biz["id"], org_id)

    # Create organizations for name groups
    for norm_name, group in name_groups.items():
        if len(group) >= 2:
            org_name = min([b["name"] for b in group], key=len)
            org_id = create_organization(conn, org_name, None,
                                         location_count=len(group),
                                         notes="Matched by name similarity")
            for biz in group:
                update_organization(conn, biz["id"], org_id)
            orgs_created += 1
            print(f"  Multi-location (name match): {org_name} — {len(group)} locations")

    conn.commit()
    conn.close()
    print(f"\nOrganizations created: {orgs_created} multi-location groups found.")


# ── Email Extraction ────────────────────────────────────────────────────


EMAIL_REGEX = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
)

# Common non-useful email patterns to skip
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
    # Filter out junk
    filtered = []
    for email in emails:
        email = email.lower()
        if any(re.search(pat, email) for pat in SKIP_EMAIL_PATTERNS):
            continue
        if email.endswith(('.png', '.jpg', '.gif', '.svg', '.css', '.js')):
            continue
        filtered.append(email)
    return list(set(filtered))


def scrape_email(website_url):
    """Try to find an email address from a business website."""
    if not website_url:
        return None

    # Normalize URL
    if not website_url.startswith("http"):
        website_url = f"https://{website_url}"

    # Try main page, then /contact, then /about
    paths_to_try = ["", "/contact", "/contact-us", "/about", "/about-us"]

    for path in paths_to_try:
        url = website_url.rstrip("/") + path
        try:
            resp = requests.get(url, timeout=8, headers={
                "User-Agent": "Mozilla/5.0 (compatible; LeadGen/1.0)"
            })
            if resp.status_code == 200:
                emails = extract_emails_from_html(resp.text)
                if emails:
                    return emails[0]  # Return the first valid email
        except Exception:
            continue

    return None


def extract_all_emails():
    """Try to extract emails for all businesses that have a website but no email."""
    conn = get_connection()
    businesses = conn.execute(
        "SELECT id, name, website FROM businesses WHERE website IS NOT NULL AND website != '' AND email IS NULL"
    ).fetchall()

    if not businesses:
        print("No businesses need email extraction.")
        conn.close()
        return

    print(f"Attempting email extraction for {len(businesses)} businesses...")

    found = 0
    for i, biz in enumerate(businesses):
        if (i + 1) % 20 == 0:
            print(f"  Progress: {i + 1}/{len(businesses)}...")

        email = scrape_email(biz["website"])
        if email:
            update_email(conn, biz["id"], email)
            found += 1

        time.sleep(0.3)  # Be polite

    conn.commit()
    conn.close()
    print(f"Found emails for {found}/{len(businesses)} businesses.")


# ── Main ────────────────────────────────────────────────────────────────


def run_enrichment():
    """Run all enrichment steps."""
    if not GOOGLE_API_KEY:
        print("ERROR: GOOGLE_API_KEY not set.")
        sys.exit(1)

    print("=" * 50)
    print("STEP 1: Calculate drive times")
    print("=" * 50)
    calculate_all_drive_times()

    print("\n" + "=" * 50)
    print("STEP 2: Detect multi-location organizations")
    print("=" * 50)
    detect_multi_location_orgs()

    print("\n" + "=" * 50)
    print("STEP 3: Extract emails from websites")
    print("=" * 50)
    extract_all_emails()

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
