"""Configuration for healthcare tenant lead generation."""

import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# --- Property Location ---
# Shops on Rockwood, 330-336 Rockwood Rd, Arden, NC 28704
PROPERTY_LAT = 35.4444
PROPERTY_LNG = -82.5366

# --- Search Configuration ---
# Center of Asheville for location biasing
ASHEVILLE_LAT = 35.5951
ASHEVILLE_LNG = -82.5515
SEARCH_RADIUS_METERS = 20000  # 20 km around Asheville center

# --- Healthcare Search Queries ---
# These combine Google Places types and free-text searches to maximize coverage.

# Type-based searches (using Google Places includedTypes)
TYPE_SEARCHES = [
    "doctor",
    "dentist",
    "physiotherapist",
    "chiropractor",
]

# Text-based searches (for categories without clean Google types)
TEXT_SEARCHES = [
    "orthodontist in Asheville NC",
    "oral surgeon in Asheville NC",
    "optometrist in Asheville NC",
    "ophthalmologist in Asheville NC",
    "dermatologist in Asheville NC",
    "podiatrist in Asheville NC",
    "urgent care in Asheville NC",
    "physical therapy in Asheville NC",
    "occupational therapy in Asheville NC",
    "mental health clinic in Asheville NC",
    "pediatrician in Asheville NC",
    "OBGYN in Asheville NC",
    "ENT doctor in Asheville NC",
    "allergy clinic in Asheville NC",
    "medical clinic in Asheville NC",
    "dental clinic in Asheville NC",
    "skin care clinic in Asheville NC",
    "wellness center in Asheville NC",
    "periodontist in Asheville NC",
    "endodontist in Asheville NC",
    "orthopedic doctor in Asheville NC",
    "pain management clinic in Asheville NC",
    "radiology imaging center in Asheville NC",
    "sports medicine in Asheville NC",
    "audiologist hearing aid in Asheville NC",
    "sleep clinic in Asheville NC",
    "med spa in Asheville NC",
    "acupuncture in Asheville NC",
    "weight loss clinic in Asheville NC",
]

# --- Drive Time Zones ---
DRIVE_ZONES = [
    (10, "<10 min"),
    (15, "10-15 min"),
    (20, "15-20 min"),
    (float("inf"), "20+ min"),
]

# --- Google API Endpoints ---
PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
ROUTES_MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"

# --- Database ---
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "leads.db")

# Fields to request from Places API (Enterprise tier for free text search)
PLACES_FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.nationalPhoneNumber",
    "places.websiteUri",
    "places.rating",
    "places.userRatingCount",
    "places.types",
    "places.primaryType",
    "nextPageToken",
])
