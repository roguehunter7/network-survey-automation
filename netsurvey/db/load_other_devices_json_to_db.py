# load_other_devices_json_to_db.py
import json
import logging
import os
import sqlite3

# Local imports
from netsurvey import config  # Import config to use its path constants

# --- Configuration ---
# Use the path defined in config.py for where other device logs are stored
JSON_LOG_DIR = config.OTHER_DEVICE_LOGS_DIR
DB_FILE = "network_survey.db"  # Assumes DB is in the PROJECT ROOT directory

# --- Logging Setup ---
log_format = "%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
logging.basicConfig(level=logging.INFO, format=log_format)
# Uncomment to log to file as well
# logging.getLogger().addHandler(logging.FileHandler("load_other_devices.log"))

# --- Helper Functions ---


def get_log_json_files(folder_path):
    """Finds all *_other_devices.json files in the specified folder."""
    if not os.path.isdir(folder_path):
        logging.error(
            f"JSON log folder not found at expected path: {os.path.abspath(folder_path)}"
        )
        logging.error(
            "This path is derived from 'config.OTHER_DEVICE_LOGS_DIR'. Ensure this directory exists relative to the project root (or executable location if packaged)."
        )
        return []
    try:
        files = [
            os.path.join(folder_path, f)
            for f in os.listdir(folder_path)
            if os.path.isfile(os.path.join(folder_path, f))
            and f.lower().endswith("_other_devices.json")
        ]
        logging.info(
            f"Found {len(files)} '*_other_devices.json' files in '{folder_path}'."
        )
        return files
    except Exception as e:
        logging.exception(f"Error listing files in {folder_path}: {e}")
        return []


def safe_int_or_none(value):
    """Safely converts a value to an integer, returning None on failure or if empty."""
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        logging.warning(f"Could not convert value '{value}' to int, returning None.")
        return None


# --- Main Processing Function ---


def process_log_file(filepath, conn):
    """Loads device entries from a single JSON log file into the database."""
    logging.info(f"Processing file: {filepath}")
    processed_count = 0
    error_in_file = False

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            device_entries = json.load(f)
            if not isinstance(device_entries, list):
                logging.error(
                    f"Invalid format: {filepath} does not contain a JSON list. Skipping."
                )
                return 0, True
    except FileNotFoundError:
        logging.error(f"File not found: {filepath}")
        return 0, True
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in file {filepath}: {e}")
        return 0, True
    except Exception as e:
        logging.exception(f"Error reading file {filepath}: {e}")
        return 0, True

    cursor = conn.cursor()

    for entry_index, entry in enumerate(device_entries):
        if not isinstance(entry, dict):
            logging.warning(
                f"Skipping non-dictionary item #{entry_index + 1} in {filepath}: {entry}"
            )
            error_in_file = True
            continue

        status_reason = entry.get("StatusReason")
        if not status_reason:
            logging.warning(
                f"Skipping entry #{entry_index + 1} in {filepath} due to missing 'StatusReason': {entry}"
            )
            error_in_file = True
            continue

        common_data = {
            "log_timestamp": entry.get("Timestamp"),
            "lab_area_name": entry.get("AreaName"),
            "floor": entry.get("Floor"),
            "site": entry.get("Site"),
            "building": entry.get("Building"),
            "wing": entry.get("Wing", ""),
            "specific_location_notes": entry.get("SpecificLocationNotes"),
            "rack_type_detail": entry.get("RackTypeDetail"),
            "reported_make": entry.get("ReportedMake"),
            "reported_model": entry.get("ReportedModel"),
            "reported_serial_number": entry.get("ReportedSerialNumber"),
            "reported_asset_tag": entry.get("ReportedAssetTag"),
            "reported_moonid": entry.get("ReportedMOONID"),
            "observed_laptop_ip": entry.get("ObservedLaptopIP"),
            "reported_total_ports": safe_int_or_none(entry.get("ReportedTotalPorts")),
            "reported_used_ports": safe_int_or_none(entry.get("ReportedUsedPorts")),
            "is_standard": None,  # To be populated by backend analysis
        }

        required_loc_keys = ["lab_area_name", "floor", "site", "building"]
        if not all(common_data.get(k) for k in required_loc_keys):
            logging.warning(
                f"Skipping entry #{entry_index + 1} in {filepath} due to missing location keys ({required_loc_keys}): {entry}"
            )
            error_in_file = True
            continue

        try:
            if status_reason == "Access Point (Observed)":
                sql = """
                    INSERT INTO logged_access_points (
                        log_timestamp, lab_area_name, floor, site, building, wing,
                        specific_location_notes, rack_type_detail, reported_make,
                        reported_model, reported_serial_number, reported_asset_tag,
                        reported_moonid, observed_laptop_ip, observed_ssid, mac_address,
                        reported_total_ports, reported_used_ports, is_standard, uplink_type
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """
                params = (
                    common_data["log_timestamp"],
                    common_data["lab_area_name"],
                    common_data["floor"],
                    common_data["site"],
                    common_data["building"],
                    common_data["wing"],
                    common_data["specific_location_notes"],
                    common_data["rack_type_detail"],
                    common_data["reported_make"],
                    common_data["reported_model"],
                    common_data["reported_serial_number"],
                    common_data["reported_asset_tag"],
                    common_data["reported_moonid"],
                    common_data["observed_laptop_ip"],
                    entry.get("ObservedSSID"),
                    entry.get("MACAddress"),
                    common_data["reported_total_ports"],
                    common_data["reported_used_ports"],
                )
                cursor.execute(sql, params)
                logging.debug(
                    f"Inserted AP entry from {filepath}: {entry.get('ReportedMake')}/{entry.get('ReportedModel')}"
                )
            else:
                sql = """
                    INSERT INTO logged_other_devices (
                        log_timestamp, status_reason, lab_area_name, floor, site, building, wing,
                        specific_location_notes, rack_type_detail, reported_make,
                        reported_model, reported_serial_number, reported_asset_tag,
                        reported_moonid, observed_laptop_ip, failure_reason_detail,
                        reported_total_ports, reported_used_ports, is_standard
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """
                params = (
                    common_data["log_timestamp"],
                    status_reason,
                    common_data["lab_area_name"],
                    common_data["floor"],
                    common_data["site"],
                    common_data["building"],
                    common_data["wing"],
                    common_data["specific_location_notes"],
                    common_data["rack_type_detail"],
                    common_data["reported_make"],
                    common_data["reported_model"],
                    common_data["reported_serial_number"],
                    common_data["reported_asset_tag"],
                    common_data["reported_moonid"],
                    common_data["observed_laptop_ip"],
                    entry.get("FailureReason"),  # Other device specific
                    common_data["reported_total_ports"],
                    common_data["reported_used_ports"],
                )
                cursor.execute(sql, params)
                logging.debug(
                    f"Inserted Other Device entry from {filepath}: Status {status_reason}"
                )
            processed_count += 1
        except sqlite3.IntegrityError as int_err:
            logging.error(
                f"Integrity Error inserting record #{entry_index + 1} from {filepath}: {int_err}"
            )
            logging.error(
                f"--> Check if location ({common_data['site']}/{common_data['building']}/{common_data['floor']}/{common_data['lab_area_name']}) exists in 'lab_areas' table."
            )
            logging.error(f"--> Record skipped: {entry}")
            error_in_file = True  # Mark file as having an error, but continue with other records in this file.
        except sqlite3.Error as db_err:
            logging.error(
                f"DB Error inserting record #{entry_index + 1} from {filepath}: {db_err} - Record: {entry}"
            )
            error_in_file = True
            # For other DB errors, we might want to stop processing this file to avoid cascading issues.
            # However, to allow as much data as possible, we'll continue to the next record.
            # To stop file processing: return processed_count, True
        except Exception as e:
            logging.exception(
                f"Unexpected error processing record #{entry_index + 1} from {filepath}: {e} - Record: {entry}"
            )
            error_in_file = True
            # To stop file processing: return processed_count, True

    logging.info(
        f"Finished processing file {filepath}. Processed {processed_count} entries from this file."
    )
    return processed_count, error_in_file


# --- Main Execution ---
if __name__ == "__main__":
    logging.info(f"--- Starting Other Devices JSON Log Load to DB ({DB_FILE}) ---")
    logging.info(
        f"Expected JSON Source Folder: {os.path.abspath(JSON_LOG_DIR)} (from config.OTHER_DEVICE_LOGS_DIR)"
    )
    logging.info(f"Expected DB File: {DB_FILE} (relative to project root)")

    if not os.path.isdir(JSON_LOG_DIR):
        logging.error(
            f"Source directory '{os.path.abspath(JSON_LOG_DIR)}' not found. Make sure path is correct and GUI saves logs there. Exiting."
        )
        exit(1)

    json_files = get_log_json_files(JSON_LOG_DIR)
    if not json_files:
        logging.warning("No '*_other_devices.json' files found to process. Exiting.")
        exit(0)

    if not os.path.exists(DB_FILE):
        logging.error(
            f"Database file '{DB_FILE}' not found in project root. Run create_db.py? Exiting."
        )
        exit(1)

    conn = None
    total_records_processed_and_committed = 0
    total_files_processed = 0
    files_with_record_errors = 0  # Files that had at least one record error but might still commit other records

    try:
        conn = sqlite3.connect(DB_FILE)
        conn.execute("PRAGMA foreign_keys = ON;")

        for filepath_index, filepath in enumerate(json_files):
            logging.info(
                f"--- Processing File {filepath_index + 1}/{len(json_files)}: {os.path.basename(filepath)} ---"
            )
            # Each file is its own transaction for more resilience
            try:
                with conn:  # Start transaction for this file
                    records_from_file, had_record_errors_in_file = process_log_file(
                        filepath, conn
                    )
                    total_records_processed_and_committed += records_from_file
                    if had_record_errors_in_file:
                        files_with_record_errors += 1
                # If 'with conn' completes without exception, it's committed.
                logging.info(
                    f"Successfully committed {records_from_file} records from {os.path.basename(filepath)}."
                )
            except sqlite3.Error as e_file_transaction:
                # This would catch errors if process_log_file itself raised an unhandled DB error
                # or if the commit failed for some reason.
                logging.error(
                    f"Transaction failed for file {filepath}: {e_file_transaction}. Data from this file rolled back."
                )
                files_with_record_errors += 1  # Count this file as having errors.
            except Exception as e_file_general:
                logging.exception(
                    f"General error processing file {filepath} transaction: {e_file_general}. Data from this file may not be committed."
                )
                files_with_record_errors += 1
            total_files_processed += 1

        logging.info("--- Load Process Finished ---")
        logging.info(
            f"Total files attempted: {total_files_processed} of {len(json_files)} found."
        )
        logging.info(
            f"Total device entries successfully committed across all files: {total_records_processed_and_committed}"
        )
        if files_with_record_errors > 0:
            logging.warning(
                f"{files_with_record_errors} file(s) encountered one or more record-level errors (skipped records). Check logs for details."
            )

    except sqlite3.Error as e:
        logging.exception(
            f"A database error occurred during connection or initial setup: {e}"
        )
    except Exception as e:
        logging.exception(f"An unexpected error occurred: {e}")
    finally:
        if conn:
            conn.close()
            logging.info("Database connection closed.")

    logging.info(
        f"Final Summary -> Files Attempted: {total_files_processed}, Files with one or more record errors: {files_with_record_errors}, Total Records Committed: {total_records_processed_and_committed}"
    )
