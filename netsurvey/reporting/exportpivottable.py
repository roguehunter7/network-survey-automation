# extract_all_devices_standard_classification.py
"""
A tool to extract all devices from the network_survey.db with standard/non-standard
classification based on specific filteration logic, and export to Excel.
"""

import logging
import os
import sqlite3

import pandas as pd
from openpyxl.utils import get_column_letter

# --- Configuration ---
DB_FILENAME = "network_survey.db"
EXCEL_FILENAME = "all_devices_standard_classification_report.xlsx"

# --- Export Columns ---
EXPORT_COLUMNS = [
    "Site",
    "MOON IDs",
    "Standard/Non-Standard",
    "Make",
    "Model",
    "Used Ports",
    "Free Ports",
    "Serial Number",
    "Location",
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
        conn.row_factory = sqlite3.Row
        logging.info(
            f"Successfully connected to database '{db_file}' in read-only mode."
        )
        return conn
    except sqlite3.Error as e:
        logging.error(f"Error connecting to database '{db_file}': {e}")
        return None


def get_row_value(row, key, default=None):
    """Safely get a value from a sqlite3.Row object by key."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def format_location(row):
    """Format location string with building, floor, lab area, and specific location notes."""
    location_parts = []

    # Add building if available and not empty
    building = get_row_value(row, "building")
    if building and building.strip() and building.strip() != "N/A":
        location_parts.append(building.strip())

    # Add floor if available and not empty
    floor = get_row_value(row, "floor")
    if floor and floor.strip() and floor.strip() != "N/A":
        location_parts.append(floor.strip())

    # Add lab area name if available and not empty
    lab_area = get_row_value(row, "lab_area_name")
    if lab_area and lab_area.strip() and lab_area.strip() != "N/A":
        location_parts.append(lab_area.strip())

    # Join building-floor-lab_area with " - " separator
    base_location = " - ".join(location_parts) if location_parts else ""

    # Add specific location notes
    specific_notes = ""

    # For switches, use location_notes
    location_notes = get_row_value(row, "location_notes")
    if location_notes and location_notes.strip() and location_notes.strip() != "N/A":
        specific_notes = location_notes.strip()

    # For other devices and APs, use specific_location_notes
    if not specific_notes:
        specific_location = get_row_value(row, "specific_location_notes")
        if (
            specific_location
            and specific_location.strip()
            and specific_location.strip() != "N/A"
        ):
            specific_notes = specific_location.strip()

    # Combine base location with specific notes
    if base_location and specific_notes:
        return f"{base_location} - {specific_notes}"
    elif base_location:
        return base_location
    elif specific_notes:
        return specific_notes
    else:
        return "N/A"


def get_switch_moonids(conn, serial_number):
    """Get MOONIDs associated with a switch."""
    sql = "SELECT DISTINCT moonid FROM switch_moonid_map WHERE switch_serial_number = ? ORDER BY moonid"
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (serial_number,))
        rows = cursor.fetchall()
        if not rows:
            return "N/A"
        return ", ".join([row["moonid"] for row in rows])
    except sqlite3.Error as e:
        logging.error(f"Error fetching MOONIDs for SN {serial_number}: {e}")
        return "N/A"


def calculate_switch_ports(conn, switch_row):
    """Calculate used and free ports for a switch."""
    sn = get_row_value(switch_row, "serial_number")
    if not sn:
        logging.warning("Cannot calculate ports for switch_row without serial_number.")
        return "Unknown", "Unknown"

    user_total = get_row_value(switch_row, "user_verified_total_ports")
    user_used = get_row_value(switch_row, "user_verified_used_ports")
    total_ports, used_ports = None, None

    # Use user-verified totals if available
    if user_total is not None:
        total_ports = user_total
    else:
        # Calculate from interfaces table
        sql_total = """
            SELECT COUNT(interface_name) as count FROM interfaces
            WHERE switch_serial_number = ? AND type IS NOT NULL AND lower(type) NOT IN
            ('virtual', 'null', 'loopback', 'tunnel', 'management', 'cpu', 'stackport', 'port-channel', 'vlan')
            AND lower(interface_name) NOT LIKE 'mgmt%' AND lower(interface_name) NOT LIKE 'cpu%'
            AND lower(interface_name) NOT LIKE 'stack%'
        """
        try:
            cursor = conn.cursor()
            cursor.execute(sql_total, (sn,))
            row = cursor.fetchone()
            total_ports = row["count"] if row else 0
        except sqlite3.Error as e:
            logging.error(f"Error calculating total ports for SN {sn}: {e}")
            total_ports = None

    # Use user-verified used ports if available
    if user_used is not None:
        used_ports = user_used
    else:
        # Calculate from interfaces table
        sql_used = """
            SELECT COUNT(interface_name) as count FROM interfaces
            WHERE switch_serial_number = ? AND lower(status) IN ('connected', 'up')
            AND type IS NOT NULL AND lower(type) NOT IN
            ('virtual', 'null', 'loopback', 'tunnel', 'management', 'cpu', 'stackport', 'port-channel', 'vlan')
            AND lower(interface_name) NOT LIKE 'mgmt%' AND lower(interface_name) NOT LIKE 'cpu%'
            AND lower(interface_name) NOT LIKE 'stack%'
        """
        try:
            cursor = conn.cursor()
            cursor.execute(sql_used, (sn,))
            row = cursor.fetchone()
            used_ports = row["count"] if row else 0
        except sqlite3.Error as e:
            logging.error(f"Error calculating used ports for SN {sn}: {e}")
            used_ports = None

    # Calculate free ports
    free_ports_val = "Unknown"
    if total_ports is not None and used_ports is not None:
        try:
            free_ports_val = max(0, int(total_ports) - int(used_ports))
        except (ValueError, TypeError):
            pass

    return (
        str(used_ports) if used_ports is not None else "Unknown",
        str(free_ports_val),
    )


def apply_classification_logic(hostname, make, model):
    """
    Apply the specified filteration logic to determine if device should be excluded
    or classified as standard/non-standard.

    Returns: (include_device: bool, standard_status: str, exclusion_reason: str)
    """
    hostname = (hostname or "").lower()
    make = (make or "").lower()
    model = (model or "").lower()

    # Check for hostname exclusions (with exceptions for specific hostnames)
    excluded_patterns = ["swp", "rss", "sws"]
    exceptions = ["sw-a1-tmp", "sw-c1-002", "sw-c1-003"]

    if (
        any(pattern in hostname for pattern in excluded_patterns)
        and hostname not in exceptions
    ):
        return False, "Excluded", f"Hostname contains one of {excluded_patterns}"

    # Check for Cisco 9k+ series - these are marked as Standard
    elif "cisco" in make and any(
        p in model for p in ["9200", "9300", "9400", "9500", "9600"]
    ):
        return True, "Standard", "Cisco 9k+ Series Model"

    # All other devices are included and marked as Non-Standard
    else:
        return True, "Non-Standard", ""


def fetch_all_managed_switches(conn):
    """Fetch all managed switches from the database."""
    sql = """
        SELECT
            s.*
        FROM switches s
        ORDER BY s.site, s.building, s.floor, s.lab_area_name, s.hostname
    """
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        return cursor.fetchall()
    except sqlite3.Error as e:
        logging.error(f"Error fetching managed switches: {e}")
        return []


def fetch_all_access_points(conn):
    """Fetch all access points from the database."""
    sql = "SELECT * FROM logged_access_points ORDER BY site, building, floor, lab_area_name"
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        return cursor.fetchall()
    except sqlite3.Error as e:
        logging.error(f"Error fetching access points: {e}")
        return []


def fetch_all_other_devices(conn):
    """Fetch all other devices from the database."""
    sql = "SELECT * FROM logged_other_devices ORDER BY site, building, floor, lab_area_name"
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        return cursor.fetchall()
    except sqlite3.Error as e:
        logging.error(f"Error fetching other devices: {e}")
        return []


def auto_adjust_column_width(worksheet):
    """Adjusts column width based on the maximum content length."""
    for col_idx in range(1, worksheet.max_column + 1):
        column_letter = get_column_letter(col_idx)
        max_length = 0
        for cell in worksheet[column_letter]:
            try:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            except:
                pass
        adjusted_width = max_length + 3
        worksheet.column_dimensions[column_letter].width = adjusted_width


def main():
    """Main function to drive the device extraction and report generation."""
    logging.info("--- Starting All Devices Standard Classification Export ---")

    conn = get_db_connection(DB_FILENAME)
    if not conn:
        return

    try:
        all_device_data = []
        excluded_devices = []

        # Process managed switches
        logging.info("Processing managed switches...")
        managed_switches = fetch_all_managed_switches(conn)

        for switch in managed_switches:
            sn = get_row_value(switch, "serial_number")
            hostname = get_row_value(switch, "hostname")
            make = get_row_value(switch, "make")
            model = get_row_value(switch, "model")

            # Apply classification logic
            include_device, standard_status, exclusion_reason = (
                apply_classification_logic(hostname, make, model)
            )

            if not include_device:
                excluded_devices.append(
                    {
                        "Device Type": "Managed Switch",
                        "Site": get_row_value(switch, "site"),
                        "Location": format_location(switch),
                        "Hostname": hostname,
                        "Make": make,
                        "Model": model,
                        "Serial Number": sn,
                        "Exclusion Reason": exclusion_reason,
                    }
                )
                continue

            # Get additional data for included devices
            moonids = get_switch_moonids(conn, sn)
            used_ports, free_ports = calculate_switch_ports(conn, switch)

            # For standard status, use the classification logic result
            # (No need to fall back to database since all non-Cisco 9k+ are Non-Standard)

            row_data = {
                "Site": get_row_value(switch, "site") or "N/A",
                "Location": format_location(switch),
                "MOON IDs": moonids,
                "Standard/Non-Standard": standard_status,
                "Make": make or "Unknown",
                "Model": model or "Unknown",
                "Used Ports": used_ports,
                "Free Ports": free_ports,
                "Serial Number": sn or "Unknown",
            }
            all_device_data.append(row_data)

        # Process access points
        logging.info("Processing access points...")
        access_points = fetch_all_access_points(conn)

        for ap in access_points:
            reported_make = get_row_value(ap, "reported_make")
            reported_model = get_row_value(ap, "reported_model")
            reported_sn = get_row_value(ap, "reported_serial_number")

            # Apply classification logic (APs typically don't have hostnames in the same way)
            include_device, standard_status, exclusion_reason = (
                apply_classification_logic("", reported_make, reported_model)
            )

            if not include_device:
                excluded_devices.append(
                    {
                        "Device Type": "Access Point",
                        "Site": get_row_value(ap, "site"),
                        "Location": format_location(ap),
                        "Hostname": "N/A",
                        "Make": reported_make,
                        "Model": reported_model,
                        "Serial Number": reported_sn,
                        "Exclusion Reason": exclusion_reason,
                    }
                )
                continue

            # Get MOONID and port info
            reported_moonid = get_row_value(ap, "reported_moonid")
            ap_used = get_row_value(ap, "reported_used_ports")
            ap_total = get_row_value(ap, "reported_total_ports")

            ap_free = "Unknown"
            if ap_total is not None and ap_used is not None:
                try:
                    ap_free = max(0, int(ap_total) - int(ap_used))
                except (ValueError, TypeError):
                    ap_free = "Unknown"

            # For standard status, use classification logic or fall back to database
            if standard_status == "Unknown":
                is_standard_val = get_row_value(ap, "is_standard")
                if is_standard_val == 1:
                    standard_status = "Standard"
                elif is_standard_val == 0:
                    standard_status = "Non-Standard"
                else:
                    standard_status = "Unknown"

            row_data = {
                "Site": get_row_value(ap, "site") or "N/A",
                "Location": format_location(ap),
                "MOON IDs": reported_moonid or "N/A",
                "Standard/Non-Standard": standard_status,
                "Make": reported_make or "Unknown",
                "Model": reported_model or "Unknown",
                "Used Ports": str(ap_used) if ap_used is not None else "Unknown",
                "Free Ports": str(ap_free),
                "Serial Number": reported_sn
                or get_row_value(ap, "mac_address")
                or "Unknown",
            }
            all_device_data.append(row_data)

        # Process other devices
        logging.info("Processing other devices...")
        other_devices = fetch_all_other_devices(conn)

        for other in other_devices:
            reported_make = get_row_value(other, "reported_make")
            reported_model = get_row_value(other, "reported_model")
            reported_sn = get_row_value(other, "reported_serial_number")

            # Apply classification logic
            include_device, standard_status, exclusion_reason = (
                apply_classification_logic("", reported_make, reported_model)
            )

            if not include_device:
                excluded_devices.append(
                    {
                        "Device Type": f"Other ({get_row_value(other, 'status_reason')})",
                        "Site": get_row_value(other, "site"),
                        "Location": format_location(other),
                        "Hostname": "N/A",
                        "Make": reported_make,
                        "Model": reported_model,
                        "Serial Number": reported_sn,
                        "Exclusion Reason": exclusion_reason,
                    }
                )
                continue

            # Get MOONID and port info
            reported_moonid = get_row_value(other, "reported_moonid")
            other_used = get_row_value(other, "reported_used_ports")
            other_total = get_row_value(other, "reported_total_ports")

            other_free = "Unknown"
            if other_total is not None and other_used is not None:
                try:
                    other_free = max(0, int(other_total) - int(other_used))
                except (ValueError, TypeError):
                    other_free = "Unknown"

            # For standard status, use classification logic or fall back to database
            if standard_status == "Unknown":
                is_standard_val = get_row_value(other, "is_standard")
                if is_standard_val == 1:
                    standard_status = "Standard"
                elif is_standard_val == 0:
                    standard_status = "Non-Standard"
                else:
                    standard_status = "Unknown"

            row_data = {
                "Site": get_row_value(other, "site") or "N/A",
                "Location": format_location(other),
                "MOON IDs": reported_moonid or "N/A",
                "Standard/Non-Standard": standard_status,
                "Make": reported_make or "Unknown",
                "Model": reported_model or "Unknown",
                "Used Ports": str(other_used) if other_used is not None else "Unknown",
                "Free Ports": str(other_free),
                "Serial Number": reported_sn or "Unknown",
            }
            all_device_data.append(row_data)

        # Generate Excel report
        if not all_device_data:
            logging.warning(
                "No devices found matching criteria. No Excel file generated."
            )
            return

        logging.info(
            f"Preparing Excel export with {len(all_device_data)} included devices and {len(excluded_devices)} excluded devices."
        )

        try:
            with pd.ExcelWriter(EXCEL_FILENAME, engine="openpyxl") as writer:
                # Main devices sheet
                df_devices = pd.DataFrame(all_device_data)
                df_devices_reordered = df_devices.reindex(
                    columns=EXPORT_COLUMNS, fill_value="N/A"
                )
                df_devices_reordered.to_excel(
                    writer, index=False, sheet_name="All Devices"
                )

                worksheet_devices = writer.sheets["All Devices"]
                auto_adjust_column_width(worksheet_devices)

                # Excluded devices sheet (if any)
                if excluded_devices:
                    df_excluded = pd.DataFrame(excluded_devices)
                    df_excluded.to_excel(
                        writer, index=False, sheet_name="Excluded Devices"
                    )

                    worksheet_excluded = writer.sheets["Excluded Devices"]
                    auto_adjust_column_width(worksheet_excluded)

                    logging.info(
                        f"Added {len(excluded_devices)} excluded devices to separate sheet."
                    )

            logging.info(f"Successfully exported data to: {EXCEL_FILENAME}")
            logging.info(f"Total included devices: {len(all_device_data)}")
            logging.info(f"Total excluded devices: {len(excluded_devices)}")

        except Exception as e:
            logging.error(f"Error writing Excel file {EXCEL_FILENAME}: {e}")

    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()
            logging.info("Database connection closed.")


if __name__ == "__main__":
    main()
