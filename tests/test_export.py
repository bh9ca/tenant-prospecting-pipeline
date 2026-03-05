"""Tests for export.py — tier scoring, sort scoring, display categories."""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from export import compute_tier, drive_time_sort_score, display_category, lead_to_row


# ── compute_tier ────────────────────────────────────────────────────────


class TestComputeTier:
    """Tier scoring: the core business logic. Every branch needs testing."""

    def _make_lead(self, business_category="dentist", distinct_location_count=1,
                   drive_time_minutes=15, rating=4.5, rating_count=100,
                   multi_location_signals=None):
        return {
            "business_category": business_category,
            "distinct_location_count": distinct_location_count,
            "drive_time_minutes": drive_time_minutes,
            "rating": rating,
            "rating_count": rating_count,
            "multi_location_signals": multi_location_signals,
        }

    # ── Tier D cases ──

    def test_hospital_system_is_d(self):
        lead = self._make_lead(business_category="hospital_system")
        assert compute_tier(lead) == "D"

    def test_veterinary_is_d(self):
        lead = self._make_lead(business_category="veterinary")
        assert compute_tier(lead) == "D"

    def test_pharmacy_is_d(self):
        lead = self._make_lead(business_category="pharmacy")
        assert compute_tier(lead) == "D"

    def test_gym_is_d(self):
        lead = self._make_lead(business_category="gym")
        assert compute_tier(lead) == "D"

    def test_under_10_min_drive_is_d(self):
        # Already a neighbor — skip
        lead = self._make_lead(drive_time_minutes=5)
        assert compute_tier(lead) == "D"

    def test_exactly_under_10_min_is_d(self):
        lead = self._make_lead(drive_time_minutes=9.9)
        assert compute_tier(lead) == "D"

    def test_zero_drive_time_is_d(self):
        lead = self._make_lead(drive_time_minutes=0)
        assert compute_tier(lead) == "D"

    # ── Tier A cases ──

    def test_tier_a_multi_location_right_type_right_distance(self):
        # Tier 1 type, 2+ locations, 10+ min drive
        lead = self._make_lead(
            business_category="dentist",
            distinct_location_count=3,
            drive_time_minutes=15,
        )
        assert compute_tier(lead) == "A"

    def test_tier_a_tier2_type(self):
        # Tier 2 type also qualifies for A
        lead = self._make_lead(
            business_category="pediatrics",  # tier 2
            distinct_location_count=2,
            drive_time_minutes=12,
        )
        assert compute_tier(lead) == "A"

    def test_tier_a_exactly_10_min(self):
        # 10 min is NOT < 10, so should not be D. Is it >= 10? Yes.
        lead = self._make_lead(
            business_category="dentist",
            distinct_location_count=2,
            drive_time_minutes=10,
        )
        assert compute_tier(lead) == "A"

    def test_not_tier_a_single_location(self):
        # Right type, right distance, but only 1 location → not A
        lead = self._make_lead(
            business_category="dentist",
            distinct_location_count=1,
            drive_time_minutes=15,
        )
        assert compute_tier(lead) != "A"

    def test_not_tier_a_tier3_type(self):
        # Tier 3 type, multi-location → should be B, not A
        lead = self._make_lead(
            business_category="medical_clinic",  # tier 3
            distinct_location_count=5,
            drive_time_minutes=15,
        )
        assert compute_tier(lead) != "A"

    # ── Tier B cases ──

    def test_tier_b_right_type_with_signals(self):
        lead = self._make_lead(
            business_category="dentist",
            distinct_location_count=1,
            drive_time_minutes=15,
            multi_location_signals='[{"source": "website_link"}]',
        )
        assert compute_tier(lead) == "B"

    def test_tier_b_right_type_multi_loc_under_10(self):
        # Type tier 1, 2+ locations, but under 10 min drive → D (neighbor)
        lead = self._make_lead(
            business_category="dentist",
            distinct_location_count=3,
            drive_time_minutes=5,
        )
        assert compute_tier(lead) == "D"

    def test_tier_b_right_type_strong_reviews(self):
        lead = self._make_lead(
            business_category="dentist",
            distinct_location_count=1,
            drive_time_minutes=15,
            rating=4.5,
            rating_count=100,
        )
        assert compute_tier(lead) == "B"

    def test_tier_b_tier3_multi_location(self):
        # Tier 3 type + 2+ distinct locations + 10+ min → B
        lead = self._make_lead(
            business_category="medical_clinic",
            distinct_location_count=2,
            drive_time_minutes=15,
        )
        assert compute_tier(lead) == "B"

    def test_tier_b_tier3_multi_loc_under_10_is_d(self):
        # Tier 3 + multi location but under 10 min → D (neighbor check first)
        lead = self._make_lead(
            business_category="medical_clinic",
            distinct_location_count=3,
            drive_time_minutes=5,
        )
        assert compute_tier(lead) == "D"

    def test_tier_b_not_enough_reviews(self):
        # Good type, 10+ min, but low reviews → should be C (not B via reviews path)
        lead = self._make_lead(
            business_category="dentist",
            distinct_location_count=1,
            drive_time_minutes=15,
            rating=4.5,
            rating_count=10,  # below 50 threshold
        )
        assert compute_tier(lead) == "C"

    def test_tier_b_rating_below_threshold(self):
        # Good type, 10+ min, enough reviews but low rating → C
        lead = self._make_lead(
            business_category="dentist",
            distinct_location_count=1,
            drive_time_minutes=15,
            rating=3.5,  # below 4.0
            rating_count=200,
        )
        assert compute_tier(lead) == "C"

    # ── Tier C cases ──

    def test_tier_c_right_type_no_signals(self):
        lead = self._make_lead(
            business_category="dentist",
            distinct_location_count=1,
            drive_time_minutes=15,
            rating=3.0,
            rating_count=5,
        )
        assert compute_tier(lead) == "C"

    def test_tier_c_tier3_single_location(self):
        lead = self._make_lead(
            business_category="medical_clinic",
            distinct_location_count=1,
            drive_time_minutes=15,
        )
        assert compute_tier(lead) == "C"

    # ── Edge cases ──

    def test_none_drive_time(self):
        # drive_time_minutes is None — should not be D (no neighbor check),
        # and cannot satisfy >= 10 check for A
        lead = self._make_lead(
            business_category="dentist",
            distinct_location_count=3,
            drive_time_minutes=None,
        )
        tier = compute_tier(lead)
        # Can't be A (drive_min >= 10 fails for None), can't be D (< 10 fails for None)
        # Has multi-loc signals? No. distinct_locs >= 2? Yes. type_tier in (1,2)? Yes.
        # Falls to B check: type_tier in (1,2) and distinct_locs >= 2 → B
        assert tier == "B"

    def test_none_distinct_location_count(self):
        # distinct_location_count is None (defaults to 1 in scoring)
        lead = self._make_lead(
            business_category="dentist",
            distinct_location_count=None,
            drive_time_minutes=15,
        )
        tier = compute_tier(lead)
        # distinct_locs = None or 1 → treated as 1
        # type_tier 1, single loc, 15 min drive, no signals, low rating → C
        # But we set rating=4.5, rating_count=100 by default!
        # So: type_tier in (1,2), drive_min >= 10, rating >= 4.0, review_count >= 50 → B
        assert tier == "B"

    def test_none_rating(self):
        lead = self._make_lead(
            business_category="dentist",
            distinct_location_count=1,
            drive_time_minutes=15,
            rating=None,
            rating_count=None,
        )
        assert compute_tier(lead) == "C"

    def test_unknown_category_defaults_to_tier3(self):
        # Unknown category → BUSINESS_TYPE_TIERS.get returns 3
        lead = self._make_lead(
            business_category="some_new_type",
            distinct_location_count=1,
            drive_time_minutes=15,
        )
        assert compute_tier(lead) == "C"

    def test_empty_category(self):
        lead = self._make_lead(
            business_category="",
            distinct_location_count=1,
            drive_time_minutes=15,
        )
        # Empty string → BUSINESS_TYPE_TIERS.get("", 3) → 3
        assert compute_tier(lead) == "C"

    def test_none_category(self):
        lead = self._make_lead(
            business_category=None,
            distinct_location_count=1,
            drive_time_minutes=15,
        )
        # category = None or "" → ""
        # BUSINESS_TYPE_TIERS.get("", 3) → 3
        assert compute_tier(lead) == "C"

    def test_tier_d_type_overrides_distance(self):
        # Even with great distance, hospital system is still D
        lead = self._make_lead(
            business_category="hospital_system",
            distinct_location_count=5,
            drive_time_minutes=15,
        )
        assert compute_tier(lead) == "D"


# ── drive_time_sort_score ───────────────────────────────────────────────


class TestDriveTimeSortScore:
    """Sweet spot scoring for sort order."""

    def test_none_returns_zero(self):
        assert drive_time_sort_score(None) == 0

    def test_sweet_spot_10(self):
        assert drive_time_sort_score(10) == 2

    def test_sweet_spot_25(self):
        assert drive_time_sort_score(25) == 2

    def test_sweet_spot_15(self):
        assert drive_time_sort_score(15) == 2

    def test_under_sweet_spot(self):
        assert drive_time_sort_score(5) == 1

    def test_over_sweet_spot(self):
        assert drive_time_sort_score(30) == 1

    def test_zero(self):
        assert drive_time_sort_score(0) == 1

    def test_just_under_10(self):
        assert drive_time_sort_score(9.99) == 1

    def test_just_over_25(self):
        assert drive_time_sort_score(25.01) == 1


# ── display_category ────────────────────────────────────────────────────


class TestDisplayCategory:
    """Category display names with fallback."""

    def test_known_category(self):
        assert display_category("dentist") == "Dentist"

    def test_known_category_med_spa(self):
        assert display_category("med_spa") == "Med Spa"

    def test_unknown_category_returns_itself(self):
        assert display_category("something_new") == "something_new"

    def test_none_returns_unknown(self):
        assert display_category(None) == "Unknown"

    def test_empty_string(self):
        # CATEGORY_DISPLAY_NAMES.get("", "") → ""
        # But function returns category or "Unknown" → "" or "Unknown"
        result = display_category("")
        assert result == "Unknown"

    def test_hospital_system(self):
        assert display_category("hospital_system") == "Hospital System"


# ── lead_to_row ─────────────────────────────────────────────────────────


class TestLeadToRow:
    """CSV row generation from lead dict."""

    def test_all_none_fields(self):
        lead = {
            "tier": "C",
            "name": "Test Clinic",
            "business_category": None,
            "phone": None,
            "email": None,
            "website": None,
            "address": None,
            "drive_time_minutes": None,
            "drive_zone": None,
            "distinct_location_count": None,
            "org_name": None,
            "rating": None,
            "rating_count": None,
            "description": None,
            "multi_location_signals": None,
        }
        row = lead_to_row(lead)
        assert row[0] == "C"  # tier
        assert row[1] == "Test Clinic"  # name
        assert row[2] == "Unknown"  # category display for None
        assert row[3] == ""  # phone
        assert row[9] == 1  # distinct_location_count default

    def test_populated_lead(self):
        lead = {
            "tier": "A",
            "name": "Smith Dental",
            "business_category": "dentist",
            "phone": "(828) 555-1234",
            "email": "info@smith.com",
            "website": "https://smith.com",
            "address": "123 Main St",
            "drive_time_minutes": 15.2,
            "drive_zone": "10-15 min",
            "distinct_location_count": 3,
            "org_name": "Smith Dental Group",
            "rating": 4.8,
            "rating_count": 200,
            "description": "Family dentistry",
            "multi_location_signals": '[{"source":"website"}]',
        }
        row = lead_to_row(lead)
        assert row[0] == "A"
        assert row[2] == "Dentist"
        assert row[7] == 15.2
        assert row[9] == 3
