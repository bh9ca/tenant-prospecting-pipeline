"""Tests for collect.py — API response parsing."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collect import parse_place


class TestParsePlace:
    """parse_place extracts fields from Google Places API response format."""

    def test_full_response(self):
        place = {
            "id": "ChIJ_abc123",
            "displayName": {"text": "Smith Dental"},
            "formattedAddress": "123 Main St, Asheville, NC",
            "location": {"latitude": 35.5, "longitude": -82.5},
            "nationalPhoneNumber": "(828) 555-1234",
            "websiteUri": "https://smithdental.com",
            "rating": 4.8,
            "userRatingCount": 150,
            "types": ["dentist", "health"],
            "primaryType": "dentist",
        }
        result = parse_place(place, "dentist in Asheville NC")

        assert result["place_id"] == "ChIJ_abc123"
        assert result["name"] == "Smith Dental"
        assert result["address"] == "123 Main St, Asheville, NC"
        assert result["lat"] == 35.5
        assert result["lng"] == -82.5
        assert result["phone"] == "(828) 555-1234"
        assert result["website"] == "https://smithdental.com"
        assert result["rating"] == 4.8
        assert result["rating_count"] == 150
        assert result["types"] == ["dentist", "health"]
        assert result["primary_type"] == "dentist"
        assert result["search_query"] == "dentist in Asheville NC"
        assert result["raw_json"] == place

    def test_missing_display_name(self):
        place = {"id": "abc"}
        result = parse_place(place, "test")
        assert result["name"] == "Unknown"

    def test_missing_location(self):
        place = {"id": "abc"}
        result = parse_place(place, "test")
        assert result["lat"] is None
        assert result["lng"] is None

    def test_missing_all_optional_fields(self):
        place = {}
        result = parse_place(place, "test")
        assert result["place_id"] == ""
        assert result["name"] == "Unknown"
        assert result["address"] == ""
        assert result["phone"] == ""
        assert result["website"] == ""
        assert result["rating"] is None
        assert result["rating_count"] is None
        assert result["types"] == []
        assert result["primary_type"] == ""

    def test_empty_display_name_text(self):
        place = {"id": "abc", "displayName": {}}
        result = parse_place(place, "test")
        assert result["name"] == "Unknown"

    def test_search_query_preserved(self):
        place = {"id": "abc"}
        result = parse_place(place, "chiropractor in Asheville NC")
        assert result["search_query"] == "chiropractor in Asheville NC"
