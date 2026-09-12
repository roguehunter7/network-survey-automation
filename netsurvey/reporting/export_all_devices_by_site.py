# export_device_reports.py
"""
A tool to extract device information from the network_survey.db and export it
into two separate Excel files: one for all managed switches, and another for
all other devices (APs, etc.) that have a recorded, valid serial number.

This version explicitly excludes devices with invalid serial numbers and also
filters out any MOON ID information for MOON IDs marked as 'Retired' or
'Being retired'.
"""

import logging
import os
import sqlite3

import pandas as pd
from openpyxl.utils import get_column_letter

# --- Configuration ---
DB_FILENAME = "network_survey.db"
SWITCHES_EXCEL_FILENAME = "managed_switches_report.xlsx"
OTHER_DEVICES_EXCEL_FILENAME = "other_devices_with_sn_report.xlsx"

# Define the final columns for the Excel export (used for both files)
FINAL_COLUMNS = [
    "Name",
    "Device Type",
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
        conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        logging.info(
            f"Successfully connected to database '{db_file}' in read-only mode."
        )
        return conn
    except sqlite3.Error as e:
        logging.error(f"Error connecting to database '{db_file}': {e}")
        return None


# --- Data Enrichment Helper Functions ---


def get_switch_management_ip(conn, serial_number):
    """Gets a prioritized management IP for a switch (non-interactive)."""
    if not serial_number:
        return "N/A"
    query = "SELECT ip_address_with_prefix, is_management, interface_name FROM ip_interfaces WHERE switch_serial_number = ?"
    try:
        rows = conn.execute(query, (serial_number,)).fetchall()
        if not rows:
            return "N/A"
        candidates = [
            {
                "ip": r[0],
                "is_mgmt": r[1] == 1,
                "is_loopback": str(r[2] or "").lower().startswith("loopback"),
            }
            for r in rows
        ]
        preferred = (
            [c["ip"] for c in candidates if c["is_mgmt"]]
            or [c["ip"] for c in candidates if c["is_loopback"]]
            or [c["ip"] for c in candidates]
        )
        return ", ".join(sorted(list(set(p for p in preferred if p)))) or "N/A"
    except sqlite3.Error as e:
        logging.warning(f"Could not fetch IP for SN {serial_number}: {e}")
        return "Error"


def get_switch_moonid_details(conn, serial_number):
    """Gets all non-retired MOON ID details for a managed switch."""
    if not serial_number:
        return {"moon_ids": "N/A", "moon_names": "N/A", "moon_networks": "N/A"}
    # --- MODIFIED QUERY ---
    query = """
        SELECT sm.moonid, sa.purpose, sa.ip_range_definition
        FROM switch_moonid_map sm
        LEFT JOIN moonid_areas sa ON sm.moonid = sa.moonid
        WHERE sm.switch_serial_number = ?
          AND lower(sa.status) NOT IN ('retired', 'being retired')
        ORDER BY sm.moonid;
    """
    try:
        rows = conn.execute(query, (serial_number,)).fetchall()
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
    except sqlite3.Error:
        return {"moon_ids": "Error", "moon_names": "Error", "moon_networks": "Error"}


def get_single_moonid_details(conn, moonid):
    """Gets details for a single non-retired MOON ID."""
    if not moonid:
        return {"moon_name": "N/A", "moon_network": "N/A"}
    # --- MODIFIED QUERY ---
    query = """
        SELECT purpose, ip_range_definition FROM moonid_areas
        WHERE moonid = ?
          AND lower(status) NOT IN ('retired', 'being retired')
    """
    try:
        row = conn.execute(query, (moonid,)).fetchone()
        if not row:
            return {"moon_name": "N/A", "moon_network": "N/A"}
        return {"moon_name": row[0] or "N/A", "moon_network": row[1] or "N/A"}
    except sqlite3.Error:
        return {"moon_name": "Error", "moon_network": "Error"}


# --- Data Fetching Functions ---


def fetch_all_managed_switches(conn):
    """Fetches all managed switches from the database with a valid serial number."""
    query = """
    SELECT
        hostname AS name,
        device_type,
        serial_number,
        base_mac_address AS mac,
        make AS manufacturer,
        model AS model_id,
        site AS campus_id,
        building,
        floor,
        lab_area_name,
        location_notes AS specific_location
    FROM switches
    WHERE
        serial_number IS NOT NULL
        AND serial_number != ''
        AND lower(serial_number) NOT IN ('unknown', 'na', 'n/a')
    ORDER BY site, building, floor, name;
    """
    try:
        df = pd.read_sql_query(query, conn)
        logging.info(
            f"Fetched {len(df)} total managed switch records with valid serial numbers."
        )
        return df
    except Exception as e:
        logging.error(f"Failed to fetch managed switches: {e}")
        return pd.DataFrame()


def fetch_all_other_devices_with_sn(conn):
    """Fetches all APs and Other Devices that have a valid serial number."""
    query = """
    SELECT
        COALESCE(reported_make, '') || ' ' || COALESCE(reported_model, '') AS name,
        'Access Point' AS device_type,
        reported_serial_number AS serial_number,
        mac_address AS mac,
        reported_make AS manufacturer,
        reported_model AS model_id,
        site AS campus_id,
        building,
        floor,
        lab_area_name,
        specific_location_notes AS specific_location,
        reported_moonid,
        observed_laptop_ip AS observed_ip
    FROM logged_access_points
    WHERE
        reported_serial_number IS NOT NULL
        AND reported_serial_number != ''
        AND lower(reported_serial_number) NOT IN ('unknown', 'na', 'n/a')

    UNION ALL

    SELECT
        COALESCE(reported_make, '') || ' ' || COALESCE(reported_model, '') AS name,
        status_reason AS device_type,
        reported_serial_number AS serial_number,
        NULL AS mac, -- No MAC field in this table
        reported_make AS manufacturer,
        reported_model AS model_id,
        site AS campus_id,
        building,
        floor,
        lab_area_name,
        specific_location_notes AS specific_location,
        reported_moonid,
        observed_laptop_ip AS observed_ip
    FROM logged_other_devices
    WHERE
        reported_serial_number IS NOT NULL
        AND reported_serial_number != ''
        AND lower(reported_serial_number) NOT IN ('unknown', 'na', 'n/a')
    ORDER BY campus_id, building, floor, name;
    """
    try:
        df = pd.read_sql_query(query, conn)
        logging.info(
            f"Fetched {len(df)} total other devices with valid serial numbers."
        )
        return df
    except Exception as e:
        logging.error(f"Failed to fetch other devices: {e}")
        return pd.DataFrame()


def auto_adjust_column_width(worksheet):
    """Adjusts column width based on the maximum content length."""
    for col_idx in range(1, worksheet.max_column + 1):
        column_letter = get_column_letter(col_idx)
        max_length = len(str(worksheet.cell(row=1, column=col_idx).value))
        for cell in worksheet[column_letter]:
            try:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            except:
                pass
        adjusted_width = min(max_length + 3, 60)
        worksheet.column_dimensions[column_letter].width = adjusted_width


def process_and_export(df, conn, filename, device_category):
    """General function to enrich data and export a DataFrame to Excel."""
    if df.empty:
        logging.warning(
            f"No data for {device_category} report. Skipping file generation for {filename}."
        )
        return

    enriched_data = []
    for row in df.itertuples(index=False):
        device_dict = row._asdict()

        if device_category == "switches":
            sn = device_dict.get("serial_number")
            device_dict["ip"] = get_switch_management_ip(conn, sn)
            moon_details = get_switch_moonid_details(conn, sn)
            device_dict.update(
                {
                    "moon_id": moon_details["moon_ids"],
                    "moon_name": moon_details["moon_names"],
                    "moon_network": moon_details["moon_networks"],
                }
            )
        else:  # Other Devices
            moonid = device_dict.get("reported_moonid")
            moon_details = get_single_moonid_details(conn, moonid)
            device_dict.update(
                {
                    "ip": device_dict.get("observed_ip"),
                    "moon_id": moonid or "N/A",
                    "moon_name": moon_details["moon_name"],
                    "moon_network": moon_details["moon_network"],
                }
            )

        loc_parts = [
            device_dict.get("lab_area_name"),
            device_dict.get("specific_location"),
        ]
        device_dict["descriptive_location"] = " - ".join(p for p in loc_parts if p)
        enriched_data.append(
            {k: (v if not pd.isna(v) else "N/A") for k, v in device_dict.items()}
        )

    final_df = pd.DataFrame(enriched_data)
    rename_map = {
        "name": "Name",
        "device_type": "Device Type",
        "ip": "IP",
        "mac": "MAC",
        "moon_id": "MOON ID",
        "moon_name": "MOON name",
        "moon_network": "MOON Network (CIDR)",
        "campus_id": "campus_id",
        "building": "Building",
        "descriptive_location": "Descriptive location / room name",
        "manufacturer": "Manufacturer",
        "model_id": "Model ID",
        "serial_number": "Serial number",
    }
    final_df.rename(columns=rename_map, inplace=True)

    for col in FINAL_COLUMNS:
        if col not in final_df.columns:
            final_df[col] = "N/A"
    final_df = final_df[FINAL_COLUMNS]

    try:
        with pd.ExcelWriter(filename, engine="openpyxl") as writer:
            sheet_name = (
                "Managed Switches" if device_category == "switches" else "Other Devices"
            )
            final_df.to_excel(writer, sheet_name=sheet_name, index=False)
            worksheet = writer.sheets[sheet_name]
            auto_adjust_column_width(worksheet)
        logging.info(
            f"--- Successfully generated report: '{filename}' with {len(final_df)} devices ---"
        )
    except Exception as e:
        logging.error(f"Failed to write Excel file {filename}: {e}", exc_info=True)


def main():
    """Main function to drive the device extraction and report generation."""
    logging.info("--- Starting Managed Switch and Other Device Report Generator ---")

    conn = get_db_connection(DB_FILENAME)
    if not conn:
        return

    try:
        # Process and export Managed Switches
        switches_df = fetch_all_managed_switches(conn)
        process_and_export(switches_df, conn, SWITCHES_EXCEL_FILENAME, "switches")

        # Process and export Other Devices with Serial Numbers
        other_devices_df = fetch_all_other_devices_with_sn(conn)
        process_and_export(
            other_devices_df, conn, OTHER_DEVICES_EXCEL_FILENAME, "other"
        )

    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()
            logging.info("Database connection closed.")


if __name__ == "__main__":
    main()
