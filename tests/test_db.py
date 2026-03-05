"""Tests for db.py — database operations with in-memory SQLite."""

import json
import os
import sqlite3
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# We need to patch DB_PATH before importing db functions that use it at module level
import config
_orig_db_path = config.DB_PATH


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Redirect DB_PATH to a temp directory for each test."""
    db_path = str(tmp_path / "test_leads.db")
    monkeypatch.setattr(config, "DB_PATH", db_path)
    # Re-import won't work; patch the db module's reference too
    import db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    # Also need to patch the get_connection function to use new path
    return db_path


@pytest.fixture
def db_conn(temp_db):
    """Initialize DB and return a connection."""
    from db import init_db, get_connection
    init_db()
    conn = get_connection()
    yield conn
    conn.close()


class TestInitDb:
    def test_creates_tables(self, temp_db):
        from db import init_db, get_connection
        init_db()
        conn = get_connection()
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        assert "businesses" in tables
        assert "organizations" in tables
        assert "search_log" in tables
        assert "outreach" in tables

    def test_idempotent(self, temp_db):
        from db import init_db
        # Calling twice should not error
        init_db()
        init_db()


class TestMigrateDb:
    def test_adds_missing_columns(self, db_conn):
        from db import migrate_db
        migrate_db()
        cols = {r[1] for r in db_conn.execute("PRAGMA table_info(businesses)").fetchall()}
        assert "business_category" in cols

    def test_idempotent(self, db_conn):
        from db import migrate_db
        migrate_db()
        migrate_db()  # Should not error on second call


class TestUpsertBusiness:
    def test_insert_returns_true(self, db_conn):
        from db import upsert_business
        result = upsert_business(
            db_conn, "place_1", "Test Clinic", "123 Main St",
            35.5, -82.5, "555-1234", "http://test.com",
            4.5, 100, ["dentist"], "dentist", "dentist in Asheville", {"id": "place_1"}
        )
        db_conn.commit()
        assert result is True

    def test_duplicate_returns_false(self, db_conn):
        from db import upsert_business
        upsert_business(
            db_conn, "place_1", "Test Clinic", "123 Main St",
            35.5, -82.5, "555-1234", "http://test.com",
            4.5, 100, ["dentist"], "dentist", "query", {"id": "place_1"}
        )
        db_conn.commit()
        result = upsert_business(
            db_conn, "place_1", "Different Name", "456 Other St",
            36.0, -83.0, "555-5678", "http://other.com",
            3.0, 50, ["doctor"], "doctor", "query2", {"id": "place_1"}
        )
        assert result is False

    def test_types_stored_as_json(self, db_conn):
        from db import upsert_business
        types = ["dentist", "health", "medical_clinic"]
        upsert_business(
            db_conn, "place_1", "Test", "addr", 35.5, -82.5,
            None, None, None, None, types, None, "query", {}
        )
        db_conn.commit()
        row = db_conn.execute("SELECT types FROM businesses WHERE place_id='place_1'").fetchone()
        assert json.loads(row["types"]) == types

    def test_none_types_stored_as_null(self, db_conn):
        from db import upsert_business
        upsert_business(
            db_conn, "place_1", "Test", "addr", 35.5, -82.5,
            None, None, None, None, None, None, "query", {}
        )
        db_conn.commit()
        row = db_conn.execute("SELECT types FROM businesses WHERE place_id='place_1'").fetchone()
        assert row["types"] is None


class TestIsSearchDone:
    def test_not_done_initially(self, db_conn):
        from db import is_search_done
        assert is_search_done(db_conn, "dentist in Asheville") is False

    def test_done_after_logging(self, db_conn):
        from db import log_search, is_search_done
        log_search(db_conn, "dentist in Asheville", None, 35.5, -82.5, 20000, 20, False)
        db_conn.commit()
        assert is_search_done(db_conn, "dentist in Asheville") is True

    def test_type_search_distinct(self, db_conn):
        from db import log_search, is_search_done
        # Log a type search
        log_search(db_conn, "dentist in Asheville", "dentist", 35.5, -82.5, 20000, 20, False)
        db_conn.commit()
        # Same query WITHOUT type should NOT be marked done
        assert is_search_done(db_conn, "dentist in Asheville", included_type=None) is False
        # Same query WITH type should be done
        assert is_search_done(db_conn, "dentist in Asheville", included_type="dentist") is True

    def test_different_query_not_done(self, db_conn):
        from db import log_search, is_search_done
        log_search(db_conn, "dentist in Asheville", None, 35.5, -82.5, 20000, 20, False)
        db_conn.commit()
        assert is_search_done(db_conn, "chiropractor in Asheville") is False


class TestCreateOrganization:
    def test_returns_id(self, db_conn):
        from db import create_organization
        org_id = create_organization(db_conn, "Test Org", "test.com", 3, "notes")
        db_conn.commit()
        assert isinstance(org_id, int)
        assert org_id > 0

    def test_fields_stored(self, db_conn):
        from db import create_organization
        org_id = create_organization(db_conn, "Test Org", "test.com", 5, "multi-location")
        db_conn.commit()
        row = db_conn.execute("SELECT * FROM organizations WHERE id=?", (org_id,)).fetchone()
        assert row["name"] == "Test Org"
        assert row["website_domain"] == "test.com"
        assert row["location_count"] == 5
        assert row["notes"] == "multi-location"


class TestGetStats:
    def test_empty_db(self, db_conn):
        from db import get_stats
        stats = get_stats(db_conn)
        assert stats["total_businesses"] == 0
        assert stats["with_drive_time"] == 0
        assert stats["by_zone"] == []
        assert stats["multi_location_orgs"] == 0

    def test_with_data(self, db_conn):
        from db import upsert_business, update_drive_time, create_organization, get_stats
        upsert_business(db_conn, "p1", "Biz1", "addr", 35.5, -82.5,
                        None, None, None, None, None, None, "q", {})
        upsert_business(db_conn, "p2", "Biz2", "addr", 35.5, -82.5,
                        None, None, None, None, None, None, "q", {})
        # Get biz IDs
        rows = db_conn.execute("SELECT id FROM businesses ORDER BY id").fetchall()
        update_drive_time(db_conn, rows[0]["id"], 12.5, "10-15 min", 8.0)
        create_organization(db_conn, "Org1", "test.com", 3, None)
        db_conn.commit()

        stats = get_stats(db_conn)
        assert stats["total_businesses"] == 2
        assert stats["with_drive_time"] == 1
        assert stats["multi_location_orgs"] == 1
