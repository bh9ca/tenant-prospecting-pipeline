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

# --- Business Type Classification ---

# Maps search query keywords → clean category. Checked in order; first match wins.
SEARCH_QUERY_TO_CATEGORY = [
    ("dentist", "dentist"),
    ("dental", "dentist"),
    ("orthodontist", "orthodontist"),
    ("periodontist", "periodontist"),
    ("endodontist", "endodontist"),
    ("oral surgeon", "oral_surgery"),
    ("optometrist", "optometry"),
    ("ophthalmologist", "optometry"),
    ("dermatologist", "dermatology"),
    ("skin care", "dermatology"),
    ("podiatrist", "podiatry"),
    ("urgent care", "urgent_care"),
    ("physical therapy", "physical_therapy"),
    ("physiotherapist", "physical_therapy"),
    ("occupational therapy", "occupational_therapy"),
    ("mental health", "mental_health_group"),
    ("pediatrician", "pediatrics"),
    ("obgyn", "obgyn"),
    ("ent doctor", "ent"),
    ("allergy", "allergy"),
    ("chiropractor", "chiropractic"),
    ("wellness center", "wellness_center"),
    ("orthopedic", "orthopedic"),
    ("pain management", "pain_management"),
    ("radiology", "radiology"),
    ("sports medicine", "sports_medicine"),
    ("audiologist", "audiology"),
    ("hearing aid", "audiology"),
    ("sleep clinic", "sleep_clinic"),
    ("med spa", "med_spa"),
    ("acupuncture", "acupuncture"),
    ("weight loss", "weight_loss"),
    ("medical clinic", "medical_clinic"),
]

# Fallback: Google Places primary_type → category
PRIMARY_TYPE_TO_CATEGORY = {
    "doctor": "medical_clinic",
    "dentist": "dentist",
    "dental_clinic": "dentist",
    "physiotherapist": "physical_therapy",
    "chiropractor": "chiropractic",
    "medical_clinic": "medical_clinic",
    "health": "medical_clinic",
    "hospital": "hospital_system",
    "pharmacy": "pharmacy",
    "veterinary_care": "veterinary",
    "gym": "gym",
    "university": "university",
    "spa": "cosmetic_spa",
    "beauty_salon": "beauty_salon",
    "hair_care": "beauty_salon",
    "fitness_center": "gym",
    "hotel": "hotel",
    "store": "retail_store",
    "consultant": "consultant",
    "corporate_office": "institutional",
}

# Tenant fitness tiers: 1=best fit, 2=good, 3=possible, 0=skip
BUSINESS_TYPE_TIERS = {
    "dentist": 1, "orthodontist": 1, "urgent_care": 1,
    "physical_therapy": 1, "chiropractic": 1, "optometry": 1,
    "med_spa": 1, "dermatology": 1,
    "pediatrics": 2, "audiology": 2, "allergy": 2,
    "weight_loss": 2, "pain_management": 2, "podiatry": 2,
    "oral_surgery": 2, "sleep_clinic": 2, "wellness_center": 2,
    "obgyn": 3, "ent": 3, "orthopedic": 3, "acupuncture": 3,
    "mental_health_group": 3, "occupational_therapy": 3, "radiology": 3,
    "sports_medicine": 3, "periodontist": 3, "endodontist": 3,
    "medical_clinic": 3,
    "hospital_system": 0, "home_health": 0, "solo_counselor": 0,
    "veterinary": 0, "university": 0, "gym": 0, "pharmacy": 0,
    "cosmetic_spa": 0, "beauty_salon": 0, "hotel": 0,
    "retail_store": 0, "consultant": 0, "institutional": 0,
}

# Known hospital/health system domains — not retail tenant prospects
HOSPITAL_SYSTEM_DOMAINS = {
    "missionhealth.org", "missionhealthphysicians.org", "adventhealth.com",
    "pardeehospital.org", "mahec.net", "novanthealth.org", "va.gov",
    "wncchs.org", "appalachianmountainhealth.org",
}

# Human-readable category labels
CATEGORY_DISPLAY_NAMES = {
    "dentist": "Dentist", "orthodontist": "Orthodontist",
    "periodontist": "Periodontist", "endodontist": "Endodontist",
    "oral_surgery": "Oral Surgery", "optometry": "Optometry",
    "dermatology": "Dermatology", "podiatry": "Podiatry",
    "urgent_care": "Urgent Care", "physical_therapy": "Physical Therapy",
    "chiropractic": "Chiropractic",
    "occupational_therapy": "Occupational Therapy",
    "mental_health_group": "Mental Health", "pediatrics": "Pediatrics",
    "obgyn": "OB/GYN", "ent": "ENT",
    "allergy": "Allergy & Immunology", "medical_clinic": "Medical Clinic",
    "wellness_center": "Wellness Center", "orthopedic": "Orthopedic",
    "pain_management": "Pain Management", "radiology": "Radiology",
    "sports_medicine": "Sports Medicine", "audiology": "Audiology",
    "sleep_clinic": "Sleep Clinic", "med_spa": "Med Spa",
    "acupuncture": "Acupuncture", "weight_loss": "Weight Loss",
    "hospital_system": "Hospital System", "home_health": "Home Health",
    "solo_counselor": "Solo Counselor", "veterinary": "Veterinary",
    "university": "University", "gym": "Gym", "pharmacy": "Pharmacy",
    "cosmetic_spa": "Cosmetic Spa", "beauty_salon": "Beauty Salon",
    "hotel": "Hotel", "retail_store": "Retail Store",
    "consultant": "Consultant", "institutional": "Institutional",
}

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
