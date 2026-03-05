"""Database setup and helper functions for leads database."""

import json
import sqlite3
from config import DB_PATH


def get_connection():
    """Get a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create database tables if they don't exist."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS organizations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            website_domain TEXT,
            location_count INTEGER DEFAULT 1,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS businesses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            place_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            address TEXT,
            lat REAL,
            lng REAL,
            phone TEXT,
            website TEXT,
            email TEXT,
            rating REAL,
            rating_count INTEGER,
            types TEXT,
            primary_type TEXT,
            search_query TEXT,
            distance_miles REAL,
            drive_time_minutes REAL,
            drive_zone TEXT,
            organization_id INTEGER,
            raw_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (organization_id) REFERENCES organizations(id)
        );

        CREATE TABLE IF NOT EXISTS outreach (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            contact_date TEXT,
            method TEXT,
            notes TEXT,
            status TEXT,
            FOREIGN KEY (business_id) REFERENCES businesses(id)
        );

        CREATE INDEX IF NOT EXISTS idx_businesses_place_id ON businesses(place_id);
        CREATE INDEX IF NOT EXISTS idx_businesses_drive_zone ON businesses(drive_zone);
        CREATE INDEX IF NOT EXISTS idx_businesses_organization ON businesses(organization_id);
    """)
    conn.commit()
    conn.close()
    print("Database initialized.")


def upsert_business(conn, place_id, name, address, lat, lng, phone, website,
                    rating, rating_count, types, primary_type, search_query,
                    raw_json):
    """Insert or skip a business (dedup by place_id). Returns True if inserted."""
    try:
        conn.execute(
            """INSERT INTO businesses
               (place_id, name, address, lat, lng, phone, website,
                rating, rating_count, types, primary_type, search_query, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (place_id, name, address, lat, lng, phone, website,
             rating, rating_count, json.dumps(types) if types else None,
             primary_type, search_query, json.dumps(raw_json)),
        )
        return True
    except sqlite3.IntegrityError:
        # Already exists (duplicate place_id)
        return False


def get_all_businesses(conn):
    """Get all businesses as a list of Row objects."""
    return conn.execute("SELECT * FROM businesses ORDER BY id").fetchall()


def get_businesses_without_drive_time(conn):
    """Get businesses that haven't had drive time calculated yet."""
    return conn.execute(
        "SELECT * FROM businesses WHERE drive_time_minutes IS NULL ORDER BY id"
    ).fetchall()


def update_drive_time(conn, business_id, drive_time_minutes, drive_zone, distance_miles=None):
    """Update drive time and zone for a business."""
    conn.execute(
        """UPDATE businesses
           SET drive_time_minutes = ?, drive_zone = ?, distance_miles = ?
           WHERE id = ?""",
        (drive_time_minutes, drive_zone, distance_miles, business_id),
    )


def update_organization(conn, business_id, organization_id):
    """Link a business to an organization."""
    conn.execute(
        "UPDATE businesses SET organization_id = ? WHERE id = ?",
        (organization_id, business_id),
    )


def update_email(conn, business_id, email):
    """Update email for a business."""
    conn.execute(
        "UPDATE businesses SET email = ? WHERE id = ?",
        (email, business_id),
    )


def create_organization(conn, name, website_domain, location_count=1, notes=None):
    """Create an organization and return its id."""
    cursor = conn.execute(
        "INSERT INTO organizations (name, website_domain, location_count, notes) VALUES (?, ?, ?, ?)",
        (name, website_domain, location_count, notes),
    )
    return cursor.lastrowid


def get_stats(conn):
    """Get summary statistics."""
    total = conn.execute("SELECT COUNT(*) FROM businesses").fetchone()[0]
    with_drive = conn.execute(
        "SELECT COUNT(*) FROM businesses WHERE drive_time_minutes IS NOT NULL"
    ).fetchone()[0]
    by_zone = conn.execute(
        """SELECT drive_zone, COUNT(*) as cnt
           FROM businesses
           WHERE drive_zone IS NOT NULL
           GROUP BY drive_zone
           ORDER BY cnt DESC"""
    ).fetchall()
    orgs = conn.execute(
        "SELECT COUNT(*) FROM organizations WHERE location_count > 1"
    ).fetchone()[0]
    return {
        "total_businesses": total,
        "with_drive_time": with_drive,
        "by_zone": [(r["drive_zone"], r["cnt"]) for r in by_zone],
        "multi_location_orgs": orgs,
    }


if __name__ == "__main__":
    init_db()
