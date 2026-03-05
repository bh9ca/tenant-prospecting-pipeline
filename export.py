"""Export leads to CSV and Excel with priority ranking."""

import csv
import json
import os
import sys
from datetime import datetime

from db import get_connection

# Output directory
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data")


def get_ranked_leads(conn):
    """
    Fetch all businesses with organization info, ranked by priority:
    1. Multi-location businesses (most locations first)
    2. Higher ratings
    3. More reviews (established businesses)
    """
    query = """
        SELECT
            b.id,
            b.name,
            b.address,
            b.phone,
            b.website,
            b.email,
            b.description,
            b.rating,
            b.rating_count,
            b.primary_type,
            b.drive_time_minutes,
            b.drive_zone,
            b.distance_miles,
            b.lat,
            b.lng,
            b.search_query,
            b.multi_location_signals,
            o.name as org_name,
            o.website_domain as org_domain,
            o.location_count,
            o.notes as org_notes
        FROM businesses b
        LEFT JOIN organizations o ON b.organization_id = o.id
        ORDER BY
            COALESCE(o.location_count, 1) DESC,
            b.rating DESC NULLS LAST,
            b.rating_count DESC NULLS LAST
    """
    return conn.execute(query).fetchall()


def export_csv(conn, filename="leads.csv"):
    """Export ranked leads to CSV."""
    leads = get_ranked_leads(conn)
    filepath = os.path.join(OUTPUT_DIR, filename)

    headers = [
        "Rank", "Name", "Address", "Phone", "Website", "Email",
        "Description", "Rating", "Reviews", "Type", "Drive Time (min)",
        "Drive Zone", "Distance (mi)", "Org Name", "Locations",
        "Multi-Location Signals", "Search Query",
    ]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for rank, lead in enumerate(leads, 1):
            writer.writerow([
                rank,
                lead["name"],
                lead["address"],
                lead["phone"],
                lead["website"],
                lead["email"] or "",
                lead["description"] or "",
                lead["rating"] or "",
                lead["rating_count"] or "",
                lead["primary_type"] or "",
                lead["drive_time_minutes"] or "",
                lead["drive_zone"] or "",
                lead["distance_miles"] or "",
                lead["org_name"] or "",
                lead["location_count"] or 1,
                lead["multi_location_signals"] or "",
                lead["search_query"] or "",
            ])

    print(f"CSV exported: {filepath} ({len(leads)} leads)")
    return filepath


def export_excel(conn, filename="leads.xlsx"):
    """Export ranked leads to Excel with formatting."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        print("openpyxl not installed. Skipping Excel export. Install with: pip install openpyxl")
        return None

    leads = get_ranked_leads(conn)
    filepath = os.path.join(OUTPUT_DIR, filename)

    wb = Workbook()

    # ── Sheet 1: All Leads (ranked) ──
    ws = wb.active
    ws.title = "All Leads"

    headers = [
        "Rank", "Name", "Address", "Phone", "Website", "Email",
        "Description", "Rating", "Reviews", "Type", "Drive Time (min)",
        "Drive Zone", "Distance (mi)", "Org Name", "Locations",
        "Multi-Location Signals", "Search Query",
    ]

    # Header styling
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=11)

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    # Data rows
    multi_loc_fill = PatternFill(start_color="D4EDDA", end_color="D4EDDA", fill_type="solid")

    for rank, lead in enumerate(leads, 1):
        row = rank + 1
        values = [
            rank,
            lead["name"],
            lead["address"],
            lead["phone"],
            lead["website"],
            lead["email"] or "",
            lead["description"] or "",
            lead["rating"],
            lead["rating_count"],
            lead["primary_type"] or "",
            lead["drive_time_minutes"],
            lead["drive_zone"] or "",
            lead["distance_miles"],
            lead["org_name"] or "",
            lead["location_count"] or 1,
            lead["multi_location_signals"] or "",
            lead["search_query"] or "",
        ]

        for col, value in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=value)
            # Highlight multi-location businesses in green
            if (lead["location_count"] or 1) > 1:
                cell.fill = multi_loc_fill

    # Auto-width columns
    from openpyxl.utils import get_column_letter
    for col in range(1, len(headers) + 1):
        max_len = max(
            len(str(ws.cell(row=r, column=col).value or ""))
            for r in range(1, min(len(leads) + 2, 100))
        )
        ws.column_dimensions[get_column_letter(col)].width = min(max_len + 2, 40)

    # Freeze header row
    ws.freeze_panes = "A2"

    # ── Sheet 2: Multi-Location Targets ──
    ws2 = wb.create_sheet("Multi-Location Targets")

    headers2 = [
        "Org Name", "Domain", "Locations", "Businesses",
    ]

    for col, header in enumerate(headers2, 1):
        cell = ws2.cell(row=1, column=col, value=header)
        cell.fill = header_fill
        cell.font = header_font

    orgs = conn.execute("""
        SELECT o.name, o.website_domain, o.location_count,
               GROUP_CONCAT(b.name, ' | ') as businesses
        FROM organizations o
        JOIN businesses b ON b.organization_id = o.id
        WHERE o.location_count > 1
        GROUP BY o.id
        ORDER BY o.location_count DESC
    """).fetchall()

    for i, org in enumerate(orgs, 2):
        ws2.cell(row=i, column=1, value=org["name"])
        ws2.cell(row=i, column=2, value=org["website_domain"] or "")
        ws2.cell(row=i, column=3, value=org["location_count"])
        ws2.cell(row=i, column=4, value=org["businesses"])

    ws2.freeze_panes = "A2"

    # ── Sheet 3: Summary Stats ──
    ws3 = wb.create_sheet("Summary")

    stats_header_font = Font(bold=True, size=12)

    ws3.cell(row=1, column=1, value="Healthcare Tenant Lead Summary").font = Font(bold=True, size=14)
    ws3.cell(row=2, column=1, value=f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    row = 4
    ws3.cell(row=row, column=1, value="Total Businesses").font = stats_header_font
    ws3.cell(row=row, column=2, value=len(leads))

    # By drive zone
    row += 2
    ws3.cell(row=row, column=1, value="By Drive Zone").font = stats_header_font
    row += 1
    zone_counts = conn.execute("""
        SELECT drive_zone, COUNT(*) as cnt FROM businesses
        WHERE drive_zone IS NOT NULL
        GROUP BY drive_zone ORDER BY
        CASE drive_zone
            WHEN '<10 min' THEN 1
            WHEN '10-15 min' THEN 2
            WHEN '15-20 min' THEN 3
            WHEN '20+ min' THEN 4
        END
    """).fetchall()
    for z in zone_counts:
        ws3.cell(row=row, column=1, value=z["drive_zone"])
        ws3.cell(row=row, column=2, value=z["cnt"])
        row += 1

    # By type
    row += 1
    ws3.cell(row=row, column=1, value="By Business Type").font = stats_header_font
    row += 1
    type_counts = conn.execute("""
        SELECT primary_type, COUNT(*) as cnt FROM businesses
        WHERE primary_type IS NOT NULL AND primary_type != ''
        GROUP BY primary_type ORDER BY cnt DESC
    """).fetchall()
    for t in type_counts:
        ws3.cell(row=row, column=1, value=t["primary_type"])
        ws3.cell(row=row, column=2, value=t["cnt"])
        row += 1

    # Multi-location count
    row += 1
    ws3.cell(row=row, column=1, value="Multi-Location Organizations").font = stats_header_font
    ws3.cell(row=row, column=2, value=len(orgs))

    wb.save(filepath)
    print(f"Excel exported: {filepath} ({len(leads)} leads, {len(orgs)} multi-location orgs)")
    return filepath


def print_summary(conn):
    """Print a text summary of the leads database."""
    total = conn.execute("SELECT COUNT(*) FROM businesses").fetchone()[0]
    with_email = conn.execute("SELECT COUNT(*) FROM businesses WHERE email IS NOT NULL").fetchone()[0]
    multi_loc = conn.execute(
        "SELECT COUNT(*) FROM organizations WHERE location_count > 1"
    ).fetchone()[0]

    print("\n" + "=" * 50)
    print("LEAD GENERATION SUMMARY")
    print("=" * 50)
    print(f"Total businesses collected: {total}")
    print(f"With email addresses: {with_email}")
    print(f"Multi-location organizations: {multi_loc}")

    # Top multi-location orgs
    top_orgs = conn.execute("""
        SELECT o.name, o.location_count, o.website_domain
        FROM organizations o
        WHERE o.location_count > 1
        ORDER BY o.location_count DESC
        LIMIT 10
    """).fetchall()

    if top_orgs:
        print("\nTop Multi-Location Organizations:")
        for org in top_orgs:
            print(f"  {org['name']} — {org['location_count']} locations ({org['website_domain'] or 'no website'})")

    # Drive zone breakdown
    zones = conn.execute("""
        SELECT drive_zone, COUNT(*) as cnt FROM businesses
        WHERE drive_zone IS NOT NULL
        GROUP BY drive_zone ORDER BY
        CASE drive_zone
            WHEN '<10 min' THEN 1
            WHEN '10-15 min' THEN 2
            WHEN '15-20 min' THEN 3
            WHEN '20+ min' THEN 4
        END
    """).fetchall()

    if zones:
        print("\nDrive Time Zones:")
        for z in zones:
            print(f"  {z['drive_zone']}: {z['cnt']} businesses")


def run_export():
    """Run the full export pipeline."""
    conn = get_connection()

    total = conn.execute("SELECT COUNT(*) FROM businesses").fetchone()[0]
    if total == 0:
        print("No businesses in database. Run collect.py first.")
        conn.close()
        sys.exit(1)

    print(f"Exporting {total} businesses...\n")

    export_csv(conn)
    export_excel(conn)
    print_summary(conn)

    conn.close()


if __name__ == "__main__":
    run_export()
