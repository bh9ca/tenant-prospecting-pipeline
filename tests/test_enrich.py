"""Tests for enrich.py — drive times, domain extraction, name/address normalization,
business classification, and email extraction."""

import math
import pytest
import sys
import os

# Add project root to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enrich import (
    haversine_miles,
    classify_drive_zone,
    extract_domain,
    normalize_name,
    normalize_address,
    classify_business_type,
    extract_emails_from_html,
)


# ── haversine_miles ─────────────────────────────────────────────────────


class TestHaversineMiles:
    """Haversine distance: critical for fallback drive time estimates."""

    def test_same_point_returns_zero(self):
        assert haversine_miles(35.5, -82.5, 35.5, -82.5) == 0.0

    def test_known_distance_asheville_to_charlotte(self):
        # Asheville (35.5951, -82.5515) to Charlotte (35.2271, -80.8431)
        # Straight-line ~100 miles
        d = haversine_miles(35.5951, -82.5515, 35.2271, -80.8431)
        assert 95 < d < 105, f"Asheville-Charlotte should be ~100mi, got {d}"

    def test_known_distance_short(self):
        # Arden property to Asheville center: ~10 miles
        d = haversine_miles(35.4444, -82.5366, 35.5951, -82.5515)
        assert 8 < d < 12, f"Arden-Asheville should be ~10mi, got {d}"

    def test_antipodal_points(self):
        # North pole to south pole: ~12,436 miles (half circumference)
        d = haversine_miles(90, 0, -90, 0)
        assert 12400 < d < 12500, f"Pole-to-pole should be ~12,430mi, got {d}"

    def test_symmetry(self):
        d1 = haversine_miles(35.0, -82.0, 36.0, -81.0)
        d2 = haversine_miles(36.0, -81.0, 35.0, -82.0)
        assert d1 == pytest.approx(d2)

    def test_equator_one_degree_longitude(self):
        # 1 degree of longitude at equator ≈ 69.1 miles
        d = haversine_miles(0, 0, 0, 1)
        assert 68 < d < 70, f"1 deg longitude at equator should be ~69mi, got {d}"

    def test_returns_float(self):
        d = haversine_miles(35.0, -82.0, 35.1, -82.1)
        assert isinstance(d, float)


# ── classify_drive_zone ─────────────────────────────────────────────────


class TestClassifyDriveZone:
    """Drive zone classification: boundary-sensitive bucketing."""

    def test_under_10(self):
        assert classify_drive_zone(5) == "<10 min"

    def test_exactly_10(self):
        # 10 is NOT < 10, so it should be "10-15 min"
        assert classify_drive_zone(10) == "10-15 min"

    def test_between_10_and_15(self):
        assert classify_drive_zone(12) == "10-15 min"

    def test_exactly_15(self):
        # 15 is NOT < 15, so it should be "15-20 min"
        assert classify_drive_zone(15) == "15-20 min"

    def test_between_15_and_20(self):
        assert classify_drive_zone(18) == "15-20 min"

    def test_exactly_20(self):
        # 20 is NOT < 20, and < inf, so "20+ min"
        assert classify_drive_zone(20) == "20+ min"

    def test_over_20(self):
        assert classify_drive_zone(45) == "20+ min"

    def test_zero(self):
        assert classify_drive_zone(0) == "<10 min"

    def test_very_large(self):
        assert classify_drive_zone(999) == "20+ min"

    def test_fractional_boundary(self):
        # 9.99 < 10, should be "<10 min"
        assert classify_drive_zone(9.99) == "<10 min"

    def test_just_over_boundary(self):
        assert classify_drive_zone(10.01) == "10-15 min"


# ── extract_domain ──────────────────────────────────────────────────────


class TestExtractDomain:
    """Domain extraction: URL parsing edge cases."""

    def test_full_https_url(self):
        assert extract_domain("https://www.example.com/page") == "example.com"

    def test_http_url(self):
        assert extract_domain("http://example.com") == "example.com"

    def test_www_stripped(self):
        assert extract_domain("https://www.missionhealth.org") == "missionhealth.org"

    def test_no_scheme(self):
        assert extract_domain("example.com/path") == "example.com"

    def test_subdomain_preserved(self):
        assert extract_domain("https://patients.missionhealth.org") == "patients.missionhealth.org"

    def test_empty_string(self):
        assert extract_domain("") is None

    def test_none(self):
        assert extract_domain(None) is None

    def test_just_www(self):
        # "www." stripped leaves empty string
        result = extract_domain("https://www.")
        # After stripping www., domain would be empty
        assert result is None or result == ""

    def test_trailing_slash(self):
        assert extract_domain("https://example.com/") == "example.com"

    def test_port_number(self):
        assert extract_domain("https://example.com:8080/path") == "example.com:8080"

    def test_complex_path(self):
        assert extract_domain("https://www.emergeortho.com/locations/asheville") == "emergeortho.com"


# ── normalize_name ──────────────────────────────────────────────────────


class TestNormalizeName:
    """Business name normalization for org matching."""

    def test_basic_lowercase(self):
        assert normalize_name("Smith Dental") == "smith dental"

    def test_strips_pc_suffix(self):
        assert normalize_name("Smith Dental, PC") == "smith dental"

    def test_strips_pa_suffix(self):
        assert normalize_name("Dr. Jones, PA") == "dr jones"

    def test_strips_llc_suffix(self):
        assert normalize_name("Asheville Eye, LLC") == "asheville eye"

    def test_strips_md_suffix(self):
        assert normalize_name("John Smith, MD") == "john smith"

    def test_strips_dds_suffix(self):
        assert normalize_name("Jane Doe, DDS") == "jane doe"

    def test_strips_location_dash(self):
        result = normalize_name("Blue Ridge Dental - Asheville")
        assert "asheville" not in result
        assert result == "blue ridge dental"

    def test_strips_location_pipe(self):
        result = normalize_name("Summit Eye | Hendersonville")
        assert "hendersonville" not in result

    def test_strips_special_chars(self):
        result = normalize_name("Dr. Smith's Clinic")
        # Special chars removed: periods, apostrophes
        assert "'" not in result
        assert "." not in result

    def test_strips_multiple_suffixes(self):
        # Should handle , PC and location
        result = normalize_name("Smith Dental, PC - Asheville")
        assert result == "smith dental"

    def test_preserves_core_name(self):
        result = normalize_name("EmergeOrtho")
        assert result == "emergeortho"


# ── normalize_address ───────────────────────────────────────────────────


class TestNormalizeAddress:
    """Address normalization: the most complex function, drives org dedup."""

    def test_basic_google_format(self):
        result = normalize_address("123 Main St, Asheville, NC 28801, USA")
        assert result == "123 main st, asheville"

    def test_strips_suite(self):
        result = normalize_address("123 Main St Suite 200, Asheville, NC 28801, USA")
        assert "suite" not in result
        assert "200" not in result or result == "123 main st, asheville"

    def test_strips_ste(self):
        result = normalize_address("123 Main St Ste 100, Asheville, NC 28801, USA")
        assert "ste" not in result

    def test_strips_unit(self):
        result = normalize_address("123 Main St Unit B, Asheville, NC 28801, USA")
        assert "unit" not in result

    def test_strips_hash_number(self):
        result = normalize_address("123 Main St #5, Asheville, NC 28801, USA")
        assert "#" not in result

    def test_strips_floor(self):
        result = normalize_address("123 Main St, 2nd Floor, Asheville, NC 28801, USA")
        assert "floor" not in result

    def test_normalizes_street_to_st(self):
        result = normalize_address("123 Main Street, Asheville, NC 28801, USA")
        assert "st" in result
        assert "street" not in result

    def test_normalizes_avenue_to_ave(self):
        result = normalize_address("456 Park Avenue, Asheville, NC 28801, USA")
        assert "ave" in result
        assert "avenue" not in result

    def test_normalizes_road_to_rd(self):
        result = normalize_address("789 Airport Road, Asheville, NC 28801, USA")
        assert "rd" in result

    def test_strips_usa_suffix(self):
        result = normalize_address("123 Main St, Asheville, NC 28801, USA")
        assert "usa" not in result

    def test_building_name_prefix(self):
        # Google sometimes puts building name first
        result = normalize_address("Medical Plaza, 123 Main St, Asheville, NC 28801, USA")
        # Should find the numbered street part
        assert "123 main st" in result

    def test_letter_suffix_stripped(self):
        # "75a" or "75 b" should normalize to "75"
        result = normalize_address("75a Main St, Asheville, NC 28801, USA")
        assert result.startswith("75 main")

    def test_same_address_different_suites_match(self):
        a1 = normalize_address("123 Main St Suite 100, Asheville, NC 28801, USA")
        a2 = normalize_address("123 Main St Suite 200, Asheville, NC 28801, USA")
        assert a1 == a2

    def test_empty_string(self):
        assert normalize_address("") == ""

    def test_none(self):
        assert normalize_address(None) == ""

    def test_no_number_fallback(self):
        # Address without a number: should return first two parts
        result = normalize_address("Medical Arts Building, Asheville, NC 28801, USA")
        assert result != ""

    def test_preserves_city(self):
        result = normalize_address("123 Main St, Hendersonville, NC 28739, USA")
        assert "hendersonville" in result

    def test_rockwood_rd(self):
        # The actual property addresses
        result = normalize_address("330 Rockwood Rd, Arden, NC 28704, USA")
        assert "330 rockwood rd" in result
        assert "arden" in result


# ── classify_business_type ──────────────────────────────────────────────


class TestClassifyBusinessType:
    """Business type classification: priority chain matters."""

    def _make_biz(self, search_query="", website="", primary_type=""):
        """Helper to create a minimal business-like dict."""
        return {
            "search_query": search_query,
            "website": website,
            "primary_type": primary_type,
        }

    def test_hospital_domain_takes_priority(self):
        # Hospital domain should override search_query
        biz = self._make_biz(
            search_query="dentist in Asheville NC",
            website="https://www.missionhealth.org/dental",
        )
        assert classify_business_type(biz) == "hospital_system"

    def test_search_query_keyword_dentist(self):
        biz = self._make_biz(search_query="dentist in Asheville NC")
        assert classify_business_type(biz) == "dentist"

    def test_search_query_keyword_dental(self):
        biz = self._make_biz(search_query="dental clinic in Asheville NC")
        assert classify_business_type(biz) == "dentist"

    def test_search_query_chiropractor(self):
        biz = self._make_biz(search_query="chiropractor in Asheville NC")
        assert classify_business_type(biz) == "chiropractic"

    def test_search_query_first_match_wins(self):
        # "dental clinic" contains "dental" which maps to "dentist"
        # It also contains "clinic" but "dental" is matched first in the list
        biz = self._make_biz(search_query="dental clinic in Asheville NC")
        assert classify_business_type(biz) == "dentist"

    def test_primary_type_fallback(self):
        biz = self._make_biz(primary_type="doctor")
        assert classify_business_type(biz) == "medical_clinic"

    def test_primary_type_hospital(self):
        biz = self._make_biz(primary_type="hospital")
        assert classify_business_type(biz) == "hospital_system"

    def test_primary_type_veterinary(self):
        biz = self._make_biz(primary_type="veterinary_care")
        assert classify_business_type(biz) == "veterinary"

    def test_default_fallback(self):
        # No keyword match, no primary_type match → default
        biz = self._make_biz(search_query="something random", primary_type="unknown_type")
        assert classify_business_type(biz) == "medical_clinic"

    def test_no_data_at_all(self):
        biz = self._make_biz()
        assert classify_business_type(biz) == "medical_clinic"

    def test_none_search_query(self):
        biz = {"search_query": None, "website": None, "primary_type": None}
        assert classify_business_type(biz) == "medical_clinic"

    def test_search_query_case_insensitive(self):
        biz = self._make_biz(search_query="DENTIST in Asheville NC")
        assert classify_business_type(biz) == "dentist"

    def test_obgyn_case_handling(self):
        biz = self._make_biz(search_query="OBGYN in Asheville NC")
        assert classify_business_type(biz) == "obgyn"

    def test_med_spa(self):
        biz = self._make_biz(search_query="med spa in Asheville NC")
        assert classify_business_type(biz) == "med_spa"

    def test_hospital_domain_adventhealth(self):
        biz = self._make_biz(website="https://www.adventhealth.com/location/asheville")
        assert classify_business_type(biz) == "hospital_system"

    def test_hospital_domain_va(self):
        biz = self._make_biz(website="https://www.va.gov/asheville")
        assert classify_business_type(biz) == "hospital_system"

    def test_search_query_overrides_primary_type(self):
        # search_query "dentist" should win over primary_type "doctor"
        biz = self._make_biz(search_query="dentist in Asheville NC", primary_type="doctor")
        assert classify_business_type(biz) == "dentist"

    def test_physiotherapist_type_search(self):
        biz = self._make_biz(search_query="physiotherapist in Asheville NC")
        assert classify_business_type(biz) == "physical_therapy"


# ── extract_emails_from_html ────────────────────────────────────────────


class TestExtractEmailsFromHtml:
    """Email extraction from HTML with filtering."""

    def test_basic_email(self):
        html = '<a href="mailto:info@clinic.com">info@clinic.com</a>'
        result = extract_emails_from_html(html)
        assert "info@clinic.com" in result

    def test_skips_example_com(self):
        html = "contact user@example.com for info"
        result = extract_emails_from_html(html)
        assert len(result) == 0

    def test_skips_sentry(self):
        html = "error@sentry.io"
        result = extract_emails_from_html(html)
        assert len(result) == 0

    def test_skips_wix(self):
        html = "user@wix.com"
        result = extract_emails_from_html(html)
        assert len(result) == 0

    def test_skips_noreply(self):
        html = "noreply@clinic.com"
        result = extract_emails_from_html(html)
        assert len(result) == 0

    def test_skips_no_reply(self):
        html = "no-reply@clinic.com"
        result = extract_emails_from_html(html)
        assert len(result) == 0

    def test_skips_image_extensions(self):
        html = "logo@2x.png background@1x.jpg icon@3x.gif"
        result = extract_emails_from_html(html)
        assert len(result) == 0

    def test_skips_css_js_extensions(self):
        html = "bundle@hash.css app@hash.js"
        result = extract_emails_from_html(html)
        assert len(result) == 0

    def test_deduplication(self):
        html = "info@clinic.com info@clinic.com info@clinic.com"
        result = extract_emails_from_html(html)
        assert len(result) == 1

    def test_multiple_valid_emails(self):
        html = "contact@clinic.com and billing@clinic.com"
        result = extract_emails_from_html(html)
        assert len(result) == 2

    def test_lowercased(self):
        html = "Info@Clinic.Com"
        result = extract_emails_from_html(html)
        assert result[0] == "info@clinic.com"

    def test_email_with_plus(self):
        html = "user+tag@clinic.com"
        result = extract_emails_from_html(html)
        assert "user+tag@clinic.com" in result

    def test_no_emails(self):
        html = "<p>No contact info here</p>"
        result = extract_emails_from_html(html)
        assert result == []

    def test_skips_squarespace(self):
        html = "user@squarespace.com"
        result = extract_emails_from_html(html)
        assert len(result) == 0

    def test_svg_extension(self):
        html = "icon@logo.svg"
        result = extract_emails_from_html(html)
        assert len(result) == 0

    def test_skips_user_at_domain(self):
        html = "user@domain.com"
        result = extract_emails_from_html(html)
        assert len(result) == 0

    def test_skips_example_prefix(self):
        html = "example@anything.com"
        result = extract_emails_from_html(html)
        assert len(result) == 0

    def test_skips_xx_prefix(self):
        html = "xx@xxxx.xx"
        result = extract_emails_from_html(html)
        assert len(result) == 0

    def test_skips_wixpress(self):
        html = "tracking@sentry-next.wixpress.com"
        result = extract_emails_from_html(html)
        assert len(result) == 0

    def test_skips_mailchimp(self):
        html = "mc@mailchimp.com"
        result = extract_emails_from_html(html)
        assert len(result) == 0

    def test_skips_webp_extension(self):
        html = "image@2x.webp"
        result = extract_emails_from_html(html)
        assert len(result) == 0

    def test_keeps_real_email(self):
        html = "info@ashevilledental.com"
        result = extract_emails_from_html(html)
        assert "info@ashevilledental.com" in result
