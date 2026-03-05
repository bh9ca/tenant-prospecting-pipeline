"""Collect healthcare businesses from Google Places API (New)."""

import sys
import time
import requests

from config import (
    GOOGLE_API_KEY,
    ASHEVILLE_LAT,
    ASHEVILLE_LNG,
    SEARCH_RADIUS_METERS,
    TYPE_SEARCHES,
    TEXT_SEARCHES,
    PLACES_TEXT_SEARCH_URL,
    PLACES_FIELD_MASK,
)
from db import get_connection, init_db, upsert_business, log_search, is_search_done


def validate_api_key():
    """Run a single test search to verify the API key works. Abort if not."""
    print("Validating API key...")
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": "places.id",
    }
    body = {
        "textQuery": "dentist in Asheville NC",
        "maxResultCount": 1,
    }
    try:
        resp = requests.post(PLACES_TEXT_SEARCH_URL, json=body, headers=headers, timeout=10)
    except requests.RequestException as e:
        print(f"ERROR: Could not reach Google Places API: {e}")
        sys.exit(1)

    if resp.status_code != 200:
        print(f"ERROR: API key validation failed ({resp.status_code}): {resp.text[:300]}")
        print("Check that your GOOGLE_API_KEY is valid and Places API (New) is enabled.")
        sys.exit(1)

    print("API key valid.\n")


def text_search(query, included_type=None, page_token=None):
    """
    Call Google Places Text Search (New) API.

    Args:
        query: Text query string (e.g., "dentist in Asheville NC")
        included_type: Optional Google Places type filter
        page_token: Token for next page of results

    Returns:
        dict with 'places' list and optional 'nextPageToken'
    """
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": PLACES_FIELD_MASK,
    }

    body = {
        "textQuery": query,
        "locationBias": {
            "circle": {
                "center": {
                    "latitude": ASHEVILLE_LAT,
                    "longitude": ASHEVILLE_LNG,
                },
                "radius": SEARCH_RADIUS_METERS,
            }
        },
        "maxResultCount": 20,
    }

    if included_type:
        body["includedType"] = included_type

    if page_token:
        body["pageToken"] = page_token

    resp = requests.post(PLACES_TEXT_SEARCH_URL, json=body, headers=headers)

    if resp.status_code != 200:
        print(f"  ERROR {resp.status_code}: {resp.text[:200]}")
        return {"places": []}

    return resp.json()


def collect_all_pages(query, included_type=None):
    """Collect all pages of results for a single query. Returns list of place dicts."""
    all_places = []
    page_token = None
    page_num = 1

    while True:
        result = text_search(query, included_type=included_type, page_token=page_token)
        places = result.get("places", [])
        all_places.extend(places)
        print(f"    Page {page_num}: {len(places)} results")

        page_token = result.get("nextPageToken")
        if not page_token or not places:
            break

        page_num += 1
        time.sleep(0.5)  # Brief pause between pages

    return all_places


def parse_place(place, search_query):
    """Extract fields from a Places API response into a flat dict."""
    display_name = place.get("displayName", {})
    location = place.get("location", {})

    return {
        "place_id": place.get("id", ""),
        "name": display_name.get("text", "Unknown"),
        "address": place.get("formattedAddress", ""),
        "lat": location.get("latitude"),
        "lng": location.get("longitude"),
        "phone": place.get("nationalPhoneNumber", ""),
        "website": place.get("websiteUri", ""),
        "rating": place.get("rating"),
        "rating_count": place.get("userRatingCount"),
        "types": place.get("types", []),
        "primary_type": place.get("primaryType", ""),
        "search_query": search_query,
        "raw_json": place,
    }


def run_search(conn, query, included_type=None):
    """Run a single search query, log it, and insert results. Returns (inserted, dupes)."""
    if is_search_done(conn, query, included_type):
        print(f"  (skipped — already in search_log)")
        return 0, 0

    places = collect_all_pages(query, included_type=included_type)

    inserted, dupes = 0, 0
    for place in places:
        parsed = parse_place(place, query)
        if upsert_business(conn, **parsed):
            inserted += 1
        else:
            dupes += 1

    # Log this search
    capped = len(places) >= 60
    log_search(conn, query, included_type, ASHEVILLE_LAT, ASHEVILLE_LNG,
               SEARCH_RADIUS_METERS, len(places), capped)
    conn.commit()

    if capped:
        print(f"  *** WARNING: Hit 60-result cap! Results may be truncated. ***")

    print(f"  -> {inserted} new, {dupes} duplicates (total {len(places)} results)")
    return inserted, dupes


def run_collection():
    """Run the full data collection pipeline."""
    if not GOOGLE_API_KEY:
        print("ERROR: GOOGLE_API_KEY not set in .env file.")
        sys.exit(1)

    validate_api_key()
    init_db()
    conn = get_connection()

    total_inserted = 0
    total_dupes = 0

    # --- Type-based searches ---
    for place_type in TYPE_SEARCHES:
        query = f"{place_type} in Asheville NC"
        print(f"\n[TYPE] Searching: {query} (includedType={place_type})")
        inserted, dupes = run_search(conn, query, included_type=place_type)
        total_inserted += inserted
        total_dupes += dupes

    # --- Text-based searches ---
    for query in TEXT_SEARCHES:
        print(f"\n[TEXT] Searching: {query}")
        inserted, dupes = run_search(conn, query)
        total_inserted += inserted
        total_dupes += dupes

    conn.close()

    print("\n" + "=" * 50)
    print(f"Collection complete!")
    print(f"  Total new businesses: {total_inserted}")
    print(f"  Total duplicates skipped: {total_dupes}")


if __name__ == "__main__":
    run_collection()
