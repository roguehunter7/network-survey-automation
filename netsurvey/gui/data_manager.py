# data_manager.py
"""Manages loading, accessing, and saving survey data and state."""

import datetime
import ipaddress
import json
import logging
import os

# Assuming config.py and utils.py are in the same directory or Python path
from netsurvey import config
from netsurvey import utils

# Use a named logger for better control if this module is part of a larger app
logger = logging.getLogger(__name__)


class DataManager:
    """Handles loading reference data, saving survey outputs, and managing state."""

    def __init__(self):
        """Initializes the DataManager and loads initial data."""
        self.lab_areas_data = []  # List of dicts
        self.moonid_areas_data = {}  # Dict keyed by MOONID (UPPERCASE)
        self.persistent_wave2_completed_sns = {}  # Dict {sn_upper: timestamp_str}
        # self.deferred_switches_data = [] # Removed

        self._load_all_data()  # Also ensures directories

    def _ensure_directories(self):
        """
        Creates necessary output directories defined in config if they don't exist.
        Note: LOGS_DIR subfolders are NOT created here; they are expected to be
        pre-created by the create_log_folders.py utility. This function ensures
        the root LOGS_DIR itself exists, along with other output directories.
        The METADATA_DIR root is created here; its subfolders for hierarchical
        storage will be created by save_wave1_metadata as needed.
        """
        dirs_to_create = [
            config.DATA_DIR,
            config.OUTPUT_DIR,
            config.LOGS_DIR,
            config.METADATA_DIR,  # Root metadata directory
            config.OTHER_DEVICE_LOGS_DIR,
            config.SESSION_STATE_DIR,
        ]

        unique_dirs = sorted(list(set(dirs_to_create)))

        for dir_path in unique_dirs:
            try:
                os.makedirs(dir_path, exist_ok=True)
                logger.debug(f"Ensured directory exists: {dir_path}")
            except OSError as e:
                logger.exception(
                    f"Could not create or access directory {dir_path}: {e}"
                )
            except Exception as e_gen:
                logger.exception(
                    f"An unexpected error occurred ensuring directory {dir_path}: {e_gen}"
                )

    def _load_all_data(self):
        """Loads initial data from external files and ensures directories exist."""
        self._ensure_directories()
        self._load_lab_areas()
        self._load_moonid_areas()
        self._load_wave2_completion_status()
        # self._load_deferred_switches_status() # Removed
        # Removed initial cache scan: self._scan_metadata_dir_for_cache()

    def _load_lab_areas(self):
        filepath = os.path.join(config.DATA_DIR, config.LAB_AREAS_FILENAME)
        self.lab_areas_data = []
        try:
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self.lab_areas_data = data
                    logger.info(
                        f"Loaded {len(data)} lab area records from {config.LAB_AREAS_FILENAME}."
                    )
                else:
                    logger.error(
                        f"Error: {filepath} should contain a JSON list. Lab areas not loaded."
                    )
            else:
                logger.error(
                    f"Lab areas data file not found: {filepath}. Lab areas not loaded."
                )
        except json.JSONDecodeError as e:
            logger.exception(
                f"Error decoding JSON from {filepath}: {e}. Lab areas not loaded."
            )
        except IOError as e:
            logger.exception(
                f"IOError loading lab areas data from {filepath}: {e}. Lab areas not loaded."
            )
        except Exception as e_gen:
            logger.exception(
                f"Unexpected error loading lab areas from {filepath}: {e_gen}. Lab areas not loaded."
            )

    def _load_moonid_areas(self):
        filepath = os.path.join(config.DATA_DIR, config.MOONID_AREAS_FILENAME)
        self.moonid_areas_data = {}
        try:
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    data_list = json.load(f)
                if not isinstance(data_list, list):
                    logger.error(
                        f"Error: {filepath} should contain a JSON list. MOONID areas not loaded."
                    )
                    return

                loaded_count = 0
                skipped_invalid = 0
                for item in data_list:
                    if isinstance(item, dict):
                        moonid = item.get("moonid")
                        if isinstance(moonid, str) and moonid.strip():
                            self.moonid_areas_data[moonid.strip().upper()] = item
                            loaded_count += 1
                        else:
                            logger.warning(
                                f"Skipping MOONID entry with missing/invalid 'moonid' string in {filepath}: {item}"
                            )
                            skipped_invalid += 1
                    else:
                        logger.warning(
                            f"Skipping non-dict item in MOONID list from {filepath}: {item}"
                        )
                        skipped_invalid += 1
                logger.info(
                    f"Loaded {loaded_count} MOONID area records from {config.MOONID_AREAS_FILENAME}."
                )
                if skipped_invalid > 0:
                    logger.warning(
                        f"Skipped {skipped_invalid} invalid entries from {config.MOONID_AREAS_FILENAME}."
                    )
            else:
                logger.error(
                    f"MOONID areas data file not found: {filepath}. MOONID areas not loaded."
                )
        except json.JSONDecodeError as e:
            logger.exception(
                f"Error decoding JSON from {filepath}: {e}. MOONID areas not loaded."
            )
        except IOError as e:
            logger.exception(
                f"IOError loading MOONID areas data from {filepath}: {e}. MOONID areas not loaded."
            )
        except Exception as e_gen:
            logger.exception(
                f"Unexpected error loading MOONID areas from {filepath}: {e_gen}. MOONID areas not loaded."
            )

    def get_sites(self):
        sites = set()
        for item in self.lab_areas_data:
            if isinstance(item, dict):
                site = item.get("site")
                _ = sites.add(site) if isinstance(site, str) else None
        return sorted(list(sites))

    def get_buildings(self, site):
        if not site:
            return []
        buildings = set()
        for item in self.lab_areas_data:
            if isinstance(item, dict):
                building = item.get("building")
                _ = (
                    buildings.add(building)
                    if item.get("site") == site and isinstance(building, str)
                    else None
                )
        return sorted(list(buildings))

    def get_floors(self, site, building):
        if not site or not building:
            return []
        floors = set()
        for item in self.lab_areas_data:
            if isinstance(item, dict):
                floor_val = item.get("floor")
                _ = (
                    floors.add(floor_val)
                    if item.get("site") == site
                    and item.get("building") == building
                    and isinstance(floor_val, str)
                    else None
                )
        return sorted(list(floors))

    def get_wings(self, site, building, floor):
        if not site or not building or not floor:
            return []
        wings = set()
        found_specific_wing = False
        for item in self.lab_areas_data:
            if (
                isinstance(item, dict)
                and item.get("site") == site
                and item.get("building") == building
                and item.get("floor") == floor
            ):
                wing = item.get("wing")
                if isinstance(wing, str) and wing.strip():
                    wings.add(wing)
                    found_specific_wing = True
        if not found_specific_wing and any(
            isinstance(item, dict)
            and item.get("site") == site
            and item.get("building") == building
            and item.get("floor") == floor
            for item in self.lab_areas_data
        ):
            wings.add("N/A")
        return sorted(list(wings))

    def get_areas(self, site, building, floor, wing):
        if not site or not building or not floor:
            return []
        target_wing_for_match = "" if wing == "N/A" else wing
        areas = set()
        for item in self.lab_areas_data:
            if (
                isinstance(item, dict)
                and item.get("site") == site
                and item.get("building") == building
                and item.get("floor") == floor
            ):
                item_wing_val = item.get("wing") or ""
                if item_wing_val == target_wing_for_match:
                    area_name = item.get("lab_area_name")
                    if isinstance(area_name, str):
                        areas.add(area_name)
        return sorted(list(areas))

    def lookup_moonid_ip_range(self, moonid):
        if not moonid or not isinstance(moonid, str):
            return config.DEFAULT_IP_RANGE_TEXT
        moonid_upper = moonid.strip().upper()
        area_info = self.moonid_areas_data.get(moonid_upper)
        if area_info and isinstance(area_info, dict):
            ip_range = area_info.get("ip_range_definition")
            return str(ip_range) if ip_range else "IP Range Not Defined"
        return "MOONID Not Found in Data"

    def lookup_moonids_by_ip(self, ip_address_str: str) -> list:
        """
        Finds MOONIDs whose ip_range_definition includes the given IP address.
        Returns a list of dicts, each containing 'moonid', 'status', 'purpose',
        and 'ip_range_definition' for matches.
        """
        found_moonids = []
        try:
            target_ip = ipaddress.ip_address(ip_address_str)
        except ValueError:
            logger.warning(f"Invalid IP address format for lookup: {ip_address_str}")
            return found_moonids  # Return empty list for invalid IP

        for moonid_key, moonid_data in self.moonid_areas_data.items():
            ip_range_def = moonid_data.get("ip_range_definition")
            if not ip_range_def:
                continue

            ranges_to_check = []
            if isinstance(ip_range_def, list):  # If JSON stores it as a list
                ranges_to_check = [
                    str(r).strip() for r in ip_range_def if str(r).strip()
                ]
            elif isinstance(ip_range_def, str):  # If JSON stores it as a string
                ranges_to_check = [
                    r.strip() for r in ip_range_def.split(",") if r.strip()
                ]
            else:
                logger.warning(
                    f"MOONID {moonid_key} has unexpected ip_range_definition type: {type(ip_range_def)}"
                )
                continue

            for range_item_str in ranges_to_check:
                if not range_item_str:
                    continue
                try:
                    # Try to interpret as a network (CIDR)
                    network = ipaddress.ip_network(range_item_str, strict=False)
                    if target_ip in network:
                        found_moonids.append(
                            {
                                "moonid": moonid_key,
                                "status": moonid_data.get("status", "N/A"),
                                "purpose": moonid_data.get("purpose", "N/A"),
                                "ip_range_definition": ip_range_def,  # Original definition for context
                            }
                        )
                        break  # Found a match for this MOONID, move to the next MOONID
                except ValueError:
                    # Not a valid network string, try to interpret as a single IP address
                    try:
                        individual_ip = ipaddress.ip_address(range_item_str)
                        if target_ip == individual_ip:
                            found_moonids.append(
                                {
                                    "moonid": moonid_key,
                                    "status": moonid_data.get("status", "N/A"),
                                    "purpose": moonid_data.get("purpose", "N/A"),
                                    "ip_range_definition": ip_range_def,
                                }
                            )
                            break  # Found a match for this MOONID
                    except ValueError:
                        logger.debug(
                            f"Could not parse '{range_item_str}' as network or IP for MOONID {moonid_key}"
                        )

        found_moonids.sort(key=lambda x: x["moonid"])  # Sort for consistent display order
        return found_moonids

    def save_wave1_metadata(self, metadata, filename_meta_json):
        """Saves Wave 1 metadata to a JSON file in a hierarchical structure under METADATA_DIR."""
        if (
            not isinstance(metadata, dict)
            or not isinstance(filename_meta_json, str)
            or not filename_meta_json
        ):
            logger.error(
                "Invalid input for save_wave1_metadata. Metadata or filename is invalid."
            )
            return False, "Invalid input provided for saving metadata."

        # Extract location details from metadata for path construction
        loc_site = metadata.get("final_site")
        loc_building = metadata.get("final_building")
        loc_floor = metadata.get("final_floor")
        loc_wing = metadata.get("final_wing")  # Can be None or empty
        loc_area = metadata.get("final_area_name")  # Can be None or empty

        if (
            not all(
                isinstance(val, str)
                for val in [loc_site, loc_building, loc_floor]
                if val is not None
            )
            or not loc_site
            or not loc_building
            or not loc_floor
        ):  # Site, Building, Floor are mandatory for path
            logger.error(
                f"Cannot save metadata {filename_meta_json}: Missing essential location fields (site, building, floor) in metadata content."
            )
            return False, "Metadata content missing essential location fields."

        sanitized_site_folder = utils.sanitize_foldername_part(
            loc_site, "NoSite_Fallback"
        )
        location_segment_folder = utils.format_location_log_folder_segment(
            building=loc_building,
            floor=loc_floor,
            wing=loc_wing,  # Pass original wing (None or str)
            area_name=loc_area,  # Pass original area name (None or str)
            wing_placeholder=utils.PATH_PLACEHOLDER_WING_DEFAULT,
            area_placeholder=utils.PATH_PLACEHOLDER_AREA_DEFAULT,
        )

        target_subdir = os.path.join(
            config.METADATA_DIR, sanitized_site_folder, location_segment_folder
        )
        try:
            os.makedirs(target_subdir, exist_ok=True)
        except OSError as e:
            logger.exception(
                f"Could not create metadata subdirectory {target_subdir}: {e}"
            )
            return False, f"Could not create metadata directory: {e}"

        filepath = os.path.join(target_subdir, filename_meta_json)
        success_flag = False
        return_message_or_path = ""

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4, ensure_ascii=False)
            logger.info(f"Saved Wave 1 metadata to {filepath}")
            success_flag = True
            return_message_or_path = filepath

            if metadata.get("wave2_data_captured_in_wave1_log") is True:
                sn = metadata.get("final_serial_number")
                if sn:
                    timestamp = metadata.get(
                        "metadata_capture_timestamp",
                        datetime.datetime.now().isoformat(sep=" ", timespec="seconds"),
                    )
                    logger.info(
                        f"Wave 2 data for SN {sn} was captured in its Wave 1 log. Marking Wave 2 as complete."
                    )
                    self.add_wave2_completed_sn(sn, timestamp)
                else:
                    logger.warning(
                        "Metadata indicates Wave 2 in Wave 1 log, but final_serial_number is missing. Cannot auto-complete W2 status."
                    )
            return success_flag, return_message_or_path
        except IOError as e:
            logger.exception(f"IOError saving Wave 1 metadata to {filepath}: {e}")
            return_message_or_path = f"Could not save metadata file: {e}"
        except Exception as e_gen:
            logger.exception(
                f"Unexpected error saving Wave 1 metadata to {filepath}: {e_gen}"
            )
            return_message_or_path = (
                f"An unexpected error occurred during save: {e_gen}"
            )
        return False, return_message_or_path

    def save_other_device_log_entry(self, log_entry, target_filename_json):
        if (
            not isinstance(log_entry, dict)
            or not isinstance(target_filename_json, str)
            or not target_filename_json
        ):
            logger.error("Invalid input for save_other_device_log_entry.")
            return False, "Invalid input provided for saving device log."

        target_filepath = os.path.join(
            config.OTHER_DEVICE_LOGS_DIR, target_filename_json
        )
        all_entries = []
        try:
            if os.path.exists(target_filepath):
                with open(target_filepath, "r", encoding="utf-8") as f_read:
                    try:
                        existing_data = json.load(f_read)
                        if isinstance(existing_data, list):
                            all_entries = existing_data
                        else:
                            logger.warning(
                                f"Data in {target_filepath} is not a list. Will overwrite."
                            )
                            all_entries = []
                    except json.JSONDecodeError:
                        logger.exception(
                            f"Error decoding JSON from {target_filepath}. File will be overwritten."
                        )
                        all_entries = []
            all_entries.append(log_entry)
            with open(target_filepath, "w", encoding="utf-8") as f_write:
                json.dump(all_entries, f_write, indent=4, ensure_ascii=False)
            logger.info(f"Appended/Saved other device entry to {target_filepath}")
            return True, f"Device entry saved to:\n{target_filename_json}"
        except IOError as e:
            logger.exception(
                f"IOError processing other device log file {target_filepath}: {e}"
            )
            return False, f"Could not save log to:\n{target_filename_json}\nError: {e}"
        except Exception as e_gen:
            logger.exception(
                f"Unexpected error saving other device log to {target_filepath}: {e_gen}"
            )
            return False, f"An unexpected error occurred:\n{e_gen}"

    def _load_wave2_completion_status(self):
        self.persistent_wave2_completed_sns = {}
        filepath = config.WAVE2_STATUS_FILENAME
        try:
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self.persistent_wave2_completed_sns = {
                        str(k).upper(): str(v) for k, v in data.items()
                    }
                    logger.info(
                        f"Loaded {len(self.persistent_wave2_completed_sns)} Wave 2 statuses."
                    )
                else:
                    logger.error(
                        f"Error: {filepath} should contain a JSON object (dict). Wave 2 status not loaded."
                    )
            else:
                logger.info(
                    f"Wave 2 status file not found ({filepath}), starting fresh."
                )
        except (json.JSONDecodeError, IOError) as e:
            logger.exception(f"Error loading Wave 2 status from {filepath}: {e}")
        except Exception as e_gen:
            logger.exception(
                f"Unexpected error loading W2 status from {filepath}: {e_gen}"
            )

    def save_wave2_completion_status(self):
        filepath = config.WAVE2_STATUS_FILENAME
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(
                    self.persistent_wave2_completed_sns, f, indent=4, ensure_ascii=False
                )
            logger.info(
                f"Saved Wave 2 status ({len(self.persistent_wave2_completed_sns)} items) to {filepath}"
            )
            return True, "Wave 2 Status Saved."
        except IOError as e:
            logger.exception(f"Error saving W2 status to {filepath}: {e}")
            return False, f"Could not save W2 status: {e}"
        except Exception as e_gen:
            logger.exception(f"Unexpected error saving W2 status: {e_gen}")
            return False, f"Unexpected W2 status save error: {e_gen}"

    def get_wave2_completed_sns(self):
        return self.persistent_wave2_completed_sns.copy()

    def add_wave2_completed_sn(self, sn, timestamp):
        sn_upper = str(sn).strip().upper()
        if sn_upper and isinstance(timestamp, str):
            self.persistent_wave2_completed_sns[sn_upper] = timestamp
            return self.save_wave2_completion_status()
        logger.warning(
            f"Attempted to add invalid SN ('{sn}') or timestamp ('{timestamp}') to Wave 2 completion."
        )
        return False, "Invalid SN or timestamp provided."

    def get_wave1_metadata_files_info(self, current_location: dict) -> list:
        """
        Gets Wave 1 metadata for devices in the current_location, ready for Wave 2 checklist.
        Reads directly from the specific hierarchical metadata subdirectory.
        """
        checklist_items = []
        if not isinstance(current_location, dict):
            logger.warning(
                "Cannot get W1 metadata: current_location is not a valid dict."
            )
            return checklist_items

        loc_site = current_location.get("site")
        loc_building = current_location.get("building")
        loc_floor = current_location.get("floor")
        # Use the stored wing value (empty string for N/A) for path construction
        loc_wing = current_location.get("wing", "")
        loc_area = current_location.get("area_name")

        if (
            not all(
                isinstance(val, str)
                for val in [loc_site, loc_building, loc_floor, loc_area]
                if val is not None
            )
            or not loc_site
            or not loc_building
            or not loc_floor
            or not loc_area
        ):
            logger.warning(
                f"Cannot get W1 metadata: current location dict is incomplete/invalid. "
                f"Site: {loc_site}, Bldg: {loc_building}, Floor: {loc_floor}, Area: {loc_area}"
            )
            return checklist_items

        sanitized_site_folder = utils.sanitize_foldername_part(
            loc_site, "NoSite_Fallback"
        )
        location_segment_folder = utils.format_location_log_folder_segment(
            building=loc_building,
            floor=loc_floor,
            wing=loc_wing,  # Use actual wing value (empty string if N/A) for path
            area_name=loc_area,
            wing_placeholder=utils.PATH_PLACEHOLDER_WING_DEFAULT,
            area_placeholder=utils.PATH_PLACEHOLDER_AREA_DEFAULT,
        )
        target_metadata_subdir = os.path.join(
            config.METADATA_DIR, sanitized_site_folder, location_segment_folder
        )

        if not os.path.isdir(target_metadata_subdir):
            logger.info(
                f"Metadata subdirectory not found for location: {target_metadata_subdir}. No items for checklist."
            )
            return checklist_items

        processed_sns_for_checklist = set()
        files_in_dir_count = 0
        skipped_malformed = 0
        skipped_criteria = 0

        try:
            for f_name in os.listdir(target_metadata_subdir):
                if not f_name.lower().endswith("-wave1.meta.json"):
                    continue
                files_in_dir_count += 1
                filepath = os.path.join(target_metadata_subdir, f_name)
                try:
                    with open(filepath, "r", encoding="utf-8") as f_meta:
                        metadata = json.load(f_meta)
                    if not isinstance(metadata, dict):
                        logger.warning(
                            f"Skipping {f_name}: content is not a JSON object."
                        )
                        skipped_malformed += 1
                        continue

                    sn_meta = metadata.get("final_serial_number")
                    filter_keys = {
                        "sn_meta": str(sn_meta).strip().upper() if sn_meta else None,
                        "os_stat": metadata.get("lldp_cdp_operational_status"),
                        "site": metadata.get("final_site"),
                        "building": metadata.get("final_building"),
                        "floor": metadata.get("final_floor"),
                        "area": metadata.get("final_area_name"),
                        "w2_in_w1_log": metadata.get(
                            "wave2_data_captured_in_wave1_log", False
                        )
                        is True,
                        "hostname": str(metadata.get("final_hostname", "N/A")),
                        "make": str(metadata.get("final_make", "N/A")),
                        "model": str(metadata.get("final_model", "N/A")),
                        "location_notes": str(metadata.get("final_location_notes", "")),
                    }

                    sn_upper = filter_keys["sn_meta"]
                    if not (
                        sn_upper
                        and isinstance(filter_keys["os_stat"], str)
                        and isinstance(filter_keys["site"], str)
                        and isinstance(filter_keys["building"], str)
                        and isinstance(filter_keys["floor"], str)
                        and isinstance(filter_keys["area"], str)
                    ):
                        logger.warning(
                            f"Malformed essential metadata in {f_name}. Skipping."
                        )
                        skipped_malformed += 1
                        continue

                    if sn_upper in processed_sns_for_checklist:
                        logger.debug(
                            f"Skipping SN {sn_upper} (from {f_name}) as already processed for checklist."
                        )
                        continue
                    processed_sns_for_checklist.add(sn_upper)

                    location_match_content = (
                        filter_keys["site"] == loc_site
                        and filter_keys["building"] == loc_building
                        and filter_keys["floor"] == loc_floor
                        and filter_keys["area"] == loc_area
                    )
                    if not location_match_content:
                        logger.warning(
                            f"Metadata content location in {f_name} ({filter_keys['site']}/{filter_keys['building']}/{filter_keys['floor']}/{filter_keys['area']}) "
                            f"does not match current survey location ({loc_site}/{loc_building}/{loc_floor}/{loc_area}). Skipping for checklist."
                        )
                        skipped_criteria += 1
                        continue

                    is_operational = filter_keys["os_stat"] == "Operational"
                    is_completed = sn_upper in self.persistent_wave2_completed_sns
                    w2_in_w1_log = filter_keys["w2_in_w1_log"]

                    if not (is_operational and not is_completed and not w2_in_w1_log):
                        skipped_criteria += 1
                        continue

                    checklist_items.append(
                        {
                            "sn": sn_upper,
                            "hostname": filter_keys["hostname"],
                            "make": filter_keys["make"],
                            "model": filter_keys["model"],
                            "location_notes": filter_keys["location_notes"],
                        }
                    )

                except (json.JSONDecodeError, IOError) as e_file:
                    logger.warning(
                        f"Error reading/parsing {filepath} for W2 checklist: {e_file}"
                    )
                    skipped_malformed += 1
                except Exception as e_file_gen:
                    logger.warning(
                        f"Unexpected error processing {filepath} for W2 checklist: {e_file_gen}"
                    )
                    skipped_malformed += 1

        except OSError as e_dir:
            logger.error(
                f"Error listing metadata directory {target_metadata_subdir}: {e_dir}"
            )
            return []

        if skipped_malformed > 0:
            logger.warning(
                f"Skipped {skipped_malformed} malformed/unreadable metadata entries during W2 checklist for {target_metadata_subdir}."
            )

        logger.info(
            f"W2 Checklist: Processed {files_in_dir_count} files from {target_metadata_subdir}. "
            f"Found {len(checklist_items)} pending items. "
            f"Skipped {skipped_criteria} due to unmet criteria."
        )

        checklist_items.sort(
            key=lambda x: (x.get("hostname", "").lower(), x.get("sn", "").lower())
        )
        return checklist_items

    def verify_sn_for_wave2(
        self, sn_to_verify: str, current_location: dict
    ) -> tuple[bool, any]:
        """Verifies if an SN is eligible for Wave 2 based on its Wave 1 metadata."""
        if (
            not sn_to_verify
            or not isinstance(sn_to_verify, str)
            or not isinstance(current_location, dict)
        ):
            return False, "Invalid input for SN verification."

        sn_upper = sn_to_verify.strip().upper()
        loc_site = current_location.get("site")
        loc_building = current_location.get("building")
        loc_floor = current_location.get("floor")
        loc_wing = current_location.get("wing", "")  # Stored wing value
        loc_area = current_location.get("area_name")

        if (
            not all(
                isinstance(val, str)
                for val in [loc_site, loc_building, loc_floor, loc_area]
                if val is not None
            )
            or not loc_site
            or not loc_building
            or not loc_floor
            or not loc_area
        ):
            return (
                False,
                "Current location is incomplete or invalid for SN verification.",
            )

        base_filename_for_meta = utils.generate_safe_filename(sn_upper)
        if not base_filename_for_meta or base_filename_for_meta == "unknown_filename":
            return False, f"Cannot determine metadata filename for SN {sn_upper}."
        metadata_filename = f"{base_filename_for_meta}-WAVE1.meta.json"

        sanitized_site_folder = utils.sanitize_foldername_part(
            loc_site, "NoSite_Fallback"
        )
        location_segment_folder = utils.format_location_log_folder_segment(
            building=loc_building,
            floor=loc_floor,
            wing=loc_wing,  # Use actual wing value for path
            area_name=loc_area,
            wing_placeholder=utils.PATH_PLACEHOLDER_WING_DEFAULT,
            area_placeholder=utils.PATH_PLACEHOLDER_AREA_DEFAULT,
        )
        target_metadata_file_path = os.path.join(
            config.METADATA_DIR,
            sanitized_site_folder,
            location_segment_folder,
            metadata_filename,
        )

        if not os.path.exists(target_metadata_file_path):
            return (
                False,
                f"Metadata file for SN {sn_upper} not found at expected location: {target_metadata_file_path}.",
            )

        try:
            with open(target_metadata_file_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            if not isinstance(metadata, dict):
                return False, f"Metadata file {metadata_filename} is corrupt."

            meta_content_sn = (
                str(metadata.get("final_serial_number", "")).strip().upper()
            )
            meta_content_site = metadata.get("final_site")
            meta_content_building = metadata.get("final_building")
            meta_content_floor = metadata.get("final_floor")
            meta_content_area = metadata.get("final_area_name")
            meta_content_wing_raw = metadata.get("final_wing")
            meta_content_wing_for_match = (
                meta_content_wing_raw if meta_content_wing_raw is not None else ""
            )

            if meta_content_sn != sn_upper:
                logger.warning(
                    f"SN mismatch in {metadata_filename}: Filename implies {sn_upper}, content has {meta_content_sn}."
                )

            if not (
                meta_content_site == loc_site
                and meta_content_building == loc_building
                and meta_content_floor == loc_floor
                and meta_content_area == loc_area
                and meta_content_wing_for_match
                == (loc_wing if loc_wing is not None else "")
            ):
                return False, (
                    f"SN {sn_upper} metadata location "
                    f"({meta_content_site}/{meta_content_building}/{meta_content_floor}/Wing:'{meta_content_wing_for_match}'/Area:{meta_content_area}) "
                    f"does not match current survey location ({loc_site}/{loc_building}/{loc_floor}/Wing:'{loc_wing if loc_wing is not None else ''}'/Area:{loc_area})."
                )

            if metadata.get("lldp_cdp_operational_status") != "Operational":
                return (
                    False,
                    f"SN {sn_upper} LLDP/CDP status in Wave 1 was not 'Operational'.",
                )
            if metadata.get("wave2_data_captured_in_wave1_log", False) is True:
                return (
                    False,
                    f"Wave 2 data for SN {sn_upper} was already captured in its Wave 1 log.",
                )
            if sn_upper in self.persistent_wave2_completed_sns:
                return False, f"SN {sn_upper} is already marked as Wave 2 complete."

            device_info = {
                "sn": sn_upper,
                "hostname": metadata.get("final_hostname", "N/A"),
                "make": metadata.get("final_make", "N/A"),
                "model": metadata.get("final_model", "N/A"),
            }
            return True, device_info
        except (json.JSONDecodeError, IOError) as e:
            return False, f"Error accessing metadata for SN {sn_upper}: {e}"
        except Exception as e_gen:
            logger.exception(f"Unexpected error verifying SN {sn_upper}: {e_gen}")
            return False, f"Unexpected error verifying SN {sn_upper}."

    # All deferred switches methods (_load_deferred_switches_status, save_deferred_switches_status,
    # add_deferred_switch_entry, get_pending_deferred_switches, update_deferred_switch_status)
    # have been removed from this file.
