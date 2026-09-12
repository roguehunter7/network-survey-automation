# generate_vendor_summary_from_raw_files.py
"""
A tool to generate a multi-sheet summary report of device counts by vendor,
including a sheet for all excluded devices, reading directly from raw survey files.
Includes an exception for the hostname 'sw-a1-tmp'.
"""

import json
import logging
import os
import re
import sys

import pandas as pd
from openpyxl.utils import get_column_letter

# --- Attempt to import config for standard paths ---
try:
    CURRENT_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    if CURRENT_SCRIPT_DIR not in sys.path:
        sys.path.insert(0, CURRENT_SCRIPT_DIR)

    PARENT_DIR = os.path.dirname(CURRENT_SCRIPT_DIR)
    if PARENT_DIR not in sys.path:
        sys.path.insert(0, PARENT_DIR)

    from netsurvey import config

    METADATA_BASE_DIR = config.METADATA_DIR
    OTHER_DEVICES_LOG_DIR = config.OTHER_DEVICE_LOGS_DIR
    logging.info("Successfully imported paths from config.py.")

except ImportError:
    logging.warning("Could not import config.py. Using default relative paths.")
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
    SURVEY_OUTPUTS_DIR = os.path.join(PROJECT_ROOT, "survey_outputs")
    METADATA_BASE_DIR = os.path.join(SURVEY_OUTPUTS_DIR, "metadata")
    OTHER_DEVICES_LOG_DIR = os.path.join(SURVEY_OUTPUTS_DIR, "other_device_logs")

# --- Configuration ---
EXCEL_FILENAME = "vendor_summary_from_raw_files_by_site.xlsx"

# --- VENDOR NORMALIZATION MAPPING ---
VENDOR_MAP = {
    "Cisco": ["cisco"],
    "D-Link": [
        "d-link",
        "dlink",
        "d - link",
        "dllink",
        "d- link",
        "dx-1008",
        "delink",
        "dxs-1800-28p",
    ],
    "Netgear": ["netgear", "netger"],
    "TP-Link": ["tp-link", "tp link", "tp - link", "tplink"],
    "HP / Aruba": ["hp", "aruba", "hewlett packard", "procurve"],
    "Extreme Networks": ["extreme"],
    "Linksys": ["linksys"],
    "Dell": ["dell"],
    "Huawei": ["huawei"],
    "Juniper": ["juniper"],
    "Arista": ["arista"],
    "Ubiquiti": ["ubiquiti", "unifi"],
    "3COM": ["3com"],
    "Nortel": ["nortel"],
    "TrendNet": ["trendnet", "trendnedt"],
    "Digisol": ["digisol"],
    "Asus": ["asus"],
    "WTI": ["wti", "western telematic"],
    "IFS / Interlogix": ["ifs", "interlogix"],
    "Magnum": ["magnum"],
    "Tejas Networks": ["tejas"],
}

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def normalize_vendor_name(vendor_string):
    """Normalizes a vendor name using the VENDOR_MAP."""
    if (
        not vendor_string
        or not isinstance(vendor_string, str)
        or vendor_string.strip().lower() in ["", "unknown"]
    ):
        return "Unknown"

    lower_vendor = vendor_string.lower()
    for canonical_name, variations in VENDOR_MAP.items():
        if any(variation in lower_vendor for variation in variations):
            return canonical_name
    return vendor_string.strip().title()


def sanitize_sheet_name(name):
    """Sanitizes a string to be a valid Excel sheet name."""
    if not name:
        return "Unnamed"
    name = re.sub(r"[\\/*?:\[\]]", "", name)
    return name[:31]


def fetch_managed_switches_from_metadata(metadata_dir):
    """Parses metadata files, returning lists for included and excluded devices."""
    included_list, excluded_list = [], []
    if not os.path.isdir(metadata_dir):
        logging.error(f"Metadata directory not found: {metadata_dir}")
        return included_list, excluded_list

    logging.info(f"Scanning for managed switch metadata in: {metadata_dir}")
    for root, _, files in os.walk(metadata_dir):
        for filename in files:
            if filename.lower().endswith("-wave1.meta.json"):
                filepath = os.path.join(root, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        meta_data = json.load(f)

                    details = {
                        "site": meta_data.get("final_site"),
                        "building": meta_data.get("final_building"),
                        "floor": meta_data.get("final_floor"),
                        "lab_area_name": meta_data.get("final_area_name"),
                        "hostname": meta_data.get("final_hostname"),
                        "make": meta_data.get("final_make"),
                        "model": meta_data.get("final_model"),
                        "source_table": "Managed Switch (metadata)",
                    }
                    hostname = (details["hostname"] or "").lower()
                    make = (details["make"] or "").lower()
                    model = (details["model"] or "").lower()

                    exclusion_reason = None
                    # Apply hostname exclusion WITH the exception for 'sw-a1-tmp'
                    if (
                        any(sub in hostname for sub in ["swp", "rss", "sws"])
                        and hostname != "sw-a1-tmp"
                    ):
                        exclusion_reason = (
                            "Hostname contains one of ['swp', 'rss', 'sws']"
                        )
                    elif "cisco" in make and any(
                        p in model for p in ["9200", "9300", "9400", "9500", "9600"]
                    ):
                        exclusion_reason = "Cisco 9k+ Series Model"

                    if exclusion_reason:
                        details["exclusion_reason"] = exclusion_reason
                        excluded_list.append(details)
                    else:
                        included_list.append(details)

                except (json.JSONDecodeError, Exception) as e:
                    logging.warning(f"Error processing metadata file {filepath}: {e}")

    logging.info(
        f"Found {len(included_list)} includable and {len(excluded_list)} excludable managed switches."
    )
    return included_list, excluded_list


def fetch_other_devices_from_logs(logs_dir):
    """Parses other device logs, returning lists for included and excluded devices."""
    included_list, excluded_list = [], []
    if not os.path.isdir(logs_dir):
        logging.error(f"Other device logs directory not found: {logs_dir}")
        return included_list, excluded_list

    logging.info(f"Scanning for other device logs in: {logs_dir}")
    for filename in os.listdir(logs_dir):
        if filename.lower().endswith("_other_devices.json"):
            filepath = os.path.join(logs_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    log_entries = json.load(f)

                if isinstance(log_entries, list):
                    for entry in log_entries:
                        details = {
                            "site": entry.get("Site"),
                            "building": entry.get("Building"),
                            "floor": entry.get("Floor"),
                            "lab_area_name": entry.get("AreaName"),
                            "hostname": entry.get("ReportedSerialNumber"),
                            "make": entry.get("ReportedMake"),
                            "model": entry.get("ReportedModel"),
                            "source_table": f"Other Device ({entry.get('StatusReason', 'N/A')})",
                        }
                        make = (details["make"] or "").lower()
                        model = (details["model"] or "").lower()

                        if "cisco" in make and any(
                            p in model for p in ["9200", "9300", "9400", "9500", "9600"]
                        ):
                            details["exclusion_reason"] = "Cisco 9k+ Series Model"
                            excluded_list.append(details)
                        else:
                            included_list.append(details)
            except (json.JSONDecodeError, Exception) as e:
                logging.warning(f"Error processing log file {filepath}: {e}")

    logging.info(
        f"Found {len(included_list)} includable and {len(excluded_list)} excludable 'other' devices."
    )
    return included_list, excluded_list


def auto_adjust_column_width(worksheet):
    """Adjusts column width based on the maximum content length."""
    for col_idx in range(1, worksheet.max_column + 1):
        column_letter = get_column_letter(col_idx)
        max_length = 0
        header_cell = worksheet.cell(row=1, column=col_idx)
        if header_cell.value:
            max_length = len(str(header_cell.value))
        for cell in worksheet[column_letter]:
            try:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            except:
                pass
        adjusted_width = max_length + 3
        worksheet.column_dimensions[column_letter].width = adjusted_width


def main():
    """Main function to drive the summary generation from raw files."""
    logging.info("--- Starting Vendor Summary Report Generator (from Raw Files) ---")

    managed_included, managed_excluded = fetch_managed_switches_from_metadata(
        METADATA_BASE_DIR
    )
    other_included, other_excluded = fetch_other_devices_from_logs(
        OTHER_DEVICES_LOG_DIR
    )

    all_included_devices = managed_included + other_included
    all_excluded_devices = managed_excluded + other_excluded

    included_df = (
        pd.DataFrame(all_included_devices) if all_included_devices else pd.DataFrame()
    )
    excluded_df = (
        pd.DataFrame(all_excluded_devices) if all_excluded_devices else pd.DataFrame()
    )

    if not included_df.empty:
        included_df.dropna(
            subset=["site", "building", "floor", "lab_area_name"], inplace=True
        )
        included_df["Vendor"] = included_df["make"].apply(normalize_vendor_name)

    try:
        logging.info(f"Writing report to Excel file: '{EXCEL_FILENAME}'")
        with pd.ExcelWriter(EXCEL_FILENAME, engine="openpyxl") as writer:
            if not included_df.empty:
                sites = sorted(included_df["site"].unique())
                for site in sites:
                    sheet_name = sanitize_sheet_name(site)
                    logging.info(f"Creating sheet '{sheet_name}' for site '{site}'...")

                    site_df_filtered = included_df[included_df["site"] == site].copy()

                    site_summary_series = site_df_filtered.groupby(
                        ["building", "floor", "lab_area_name", "Vendor"]
                    ).size()

                    if site_summary_series.empty:
                        continue

                    site_summary_df = site_summary_series.unstack(
                        level="Vendor", fill_value=0
                    )
                    site_summary_df["Total Devices"] = site_summary_df.sum(axis=1)
                    site_summary_df.reset_index(inplace=True)

                    site_summary_df.to_excel(writer, sheet_name=sheet_name, index=False)
                    auto_adjust_column_width(writer.sheets[sheet_name])
            else:
                logging.warning(
                    "No includable device data found to generate summary sheets."
                )

            if not excluded_df.empty:
                logging.info("Creating sheet for excluded devices...")
                excluded_df.to_excel(writer, sheet_name="Excluded Devices", index=False)
                auto_adjust_column_width(writer.sheets["Excluded Devices"])
            else:
                logging.info("No excluded devices found to report.")

        logging.info(f"--- Successfully generated Excel report: '{EXCEL_FILENAME}' ---")
    except Exception as e:
        logging.error(f"An error occurred during Excel generation: {e}", exc_info=True)


if __name__ == "__main__":
    main()
