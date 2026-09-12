# export_all_devices_by_site.py
"""
A tool to extract all device information from the network_survey.db
and export it to a single Excel file, with each site on its own sheet.

Modified to export a specific set of columns including management IP,
MAC address, and detailed MOON ID information.
"""

import logging
import os
import re
import sqlite3

import pandas as pd
from openpyxl.utils import get_column_letter

# --- Configuration ---
DB_FILENAME = "network_survey.db"
EXCEL_FILENAME = "all_devices_by_site_detailed_report.xlsx"

# Define the final columns for the Excel export
FINAL_COLUMNS = [
    "Name",
    "IP",
    "MAC",
    "MOON ID",
    "MOON name",
    "MOON Network (CIDR)",
    "campus_id",
    "Building",
    "floor",
    "Descriptive location / room name",
    "Manufacturer",
    "Model ID",
    "Serial number",
]


# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def get_db_connection(db_file):
    """Establishes a read-only connection to the SQLite database."""
    if not os.path.exists(db_file):
        logging.error(f"Database file '{db_file}' not found.")
        return None
    try:
        # Connect in read-only mode to prevent accidental changes
        conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        logging.info(
            f"Successfully connected to database '{db_file}' in read-only mode."
        )
        return conn
    except sqlite3.Error as e:
        logging.error(f"Error connecting to database '{db_file}': {e}")
        return None


def get_all_sites(conn):
    """Retrieves a list of all unique sites with devices from the database."""
    query = """
    SELECT DISTINCT site FROM switches WHERE site IS NOT NULL AND site != ''
    UNION
    SELECT DISTINCT site FROM logged_access_points WHERE site IS NOT NULL AND site != ''
    UNION
    SELECT DISTINCT site FROM logged_other_devices WHERE site IS NOT NULL AND site != '';
    """
    try:
        cursor = conn.cursor()
        cursor.execute(query)
        sites = sorted([row[0] for row in cursor.fetchall()])
        logging.info(f"Found {len(sites)} unique sites in the database.")
        return sites
    except sqlite3.Error as e:
        logging.error(f"Failed to fetch sites from the database: {e}")
        return []


# --- Data Enrichment Helper Functions ---

def get_switch_management_ip(conn, serial_number):
    """Gets a prioritized management IP for a switch (non-interactive)."""
    if not serial_number:
        return "N/A"
    query = "SELECT interface_name, ip_address_with_prefix, is_management FROM ip_interfaces WHERE switch_serial_number = ?"
    try:
        cursor = conn.cursor()
        cursor.execute(query, (serial_number,))
        rows = cursor.fetchall()
        if not rows:
            return "N/A"

        candidates = [
            {
                "ip": row[1],
                "interface": row[0],
                "is_mgmt_flag": row[2] == 1,
                "is_loopback": str(row[0] or "").lower().startswith("loopback"),
                "is_vlan_if": str(row[0] or "").lower().startswith("vlan"),
            }
            for row in rows
        ]

        # Prioritize IPs
        preferred = [c["ip"] for c in candidates if c["is_mgmt_flag"]]
        if not preferred:
            preferred = [c["ip"] for c in candidates if c["is_loopback"]]
        if not preferred:
            preferred = [c["ip"] for c in candidates if c["is_vlan_if"]]
        if not preferred:
            preferred = [c["ip"] for c in candidates]

        return ", ".join(sorted(list(set(p for p in preferred if p)))) or "N/A"

    except sqlite3.Error as e:
        logging.warning(f"Could not fetch IP for SN {serial_number}: {e}")
        return "Error"


def get_switch_moonid_details(conn, serial_number):
    """Gets all MOON ID details for a managed switch."""
    if not serial_number:
        return {"moon_ids": "N/A", "moon_names": "N/A", "moon_networks": "N/A"}
    query = """
        SELECT sm.moonid, sa.purpose, sa.ip_range_definition
        FROM switch_moonid_map sm
        LEFT JOIN moonid_areas sa ON sm.moonid = sa.moonid
        WHERE sm.switch_serial_number = ?
        ORDER BY sm.moonid;
    """
    try:
        cursor = conn.cursor()
        cursor.execute(query, (serial_number,))
        rows = cursor.fetchall()
        if not rows:
            return {"moon_ids": "N/A", "moon_names": "N/A", "moon_networks": "N/A"}

        moon_ids = ", ".join(sorted(list(set(r[0] for r in rows if r and r[0]))))
        moon_names = ", ".join(sorted(list(set(r[1] for r in rows if r and r[1]))))
        moon_networks = ", ".join(sorted(list(set(r[2] for r in rows if r and r[2]))))
        return {
            "moon_ids": moon_ids or "N/A",
            "moon_names": moon_names or "N/A",
            "moon_networks": moon_networks or "N/A",
        }
    except sqlite3.Error as e:
        logging.warning(f"Could not fetch MOONIDs for SN {serial_number}: {e}")
        return {"moon_ids": "Error", "moon_names": "Error", "moon_networks": "Error"}


def get_single_moonid_details(conn, moonid):
    """Gets details for a single MOON ID (for APs/Other devices)."""
    if not moonid:
        return {"moon_name": "N/A", "moon_network": "N/A"}
    query = "SELECT purpose, ip_range_definition FROM moonid_areas WHERE moonid = ?"
    try:
        cursor = conn.cursor()
        cursor.execute(query, (moonid,))
        row = cursor.fetchone()
        if not row:
            return {"moon_name": "N/A", "moon_network": "N/A"}
        return {"moon_name": row[0] or "N/A", "moon_network": row[1] or "N/A"}
    except sqlite3.Error as e:
        logging.warning(f"Could not fetch details for MOONID {moonid}: {e}")
        return {"moon_name": "Error", "moon_network": "Error"}


def fetch_devices_for_site(conn, site):
    """Fetches a base set of combined device data for post-processing."""
    query = """
    SELECT
        hostname AS "Name",
        serial_number,
        base_mac_address AS "MAC",
        make AS "Manufacturer",
        model AS "Model ID",
        site AS "campus_id",
        building AS "Building",
        floor,
        lab_area_name,
        location_notes AS specific_location,
        NULL AS reported_moonid,
        NULL AS observed_ip,
        'switch' AS source_type
    FROM switches
    WHERE site = ?

    UNION ALL

    SELECT
        COALESCE(reported_make, '') || ' ' || COALESCE(reported_model, '') AS "