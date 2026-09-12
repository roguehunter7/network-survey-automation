# unified_processor.py

import concurrent.futures
import json
import logging
import os
import re
import shutil
import sys
import time
import traceback
from typing import Dict, List, Optional

# Local imports
from netsurvey import config  # For path constants
from netsurvey import utils  # For utility functions like path formatting

try:
    from netsurvey.llm import gemini
except ImportError:
    logger = logging.getLogger(__name__)  # Ensure logger is defined before use
    logger.critical("CRITICAL ERROR: Could not import gemini.py.")
    sys.exit(1)

if not hasattr(gemini, "process_llm_package_file_to_json"):
    logger = logging.getLogger(__name__)  # Ensure logger is defined before use
    logger.critical(
        "CRITICAL ERROR: gemini.py missing 'process_llm_package_file_to_json'."
    )
    sys.exit(1)

# --- Configuration Constants ---
# Paths will now be primarily sourced from config.py
LAB_AREAS_FILE = os.path.join(
    config.DATA_DIR, "lab_areas_data.json"
)  # For lab area selection

LLM_PROMPT_STAGE1A_FILENAME = "llm_prompt_stage1a.txt"
LLM_PROMPT_STAGE1B_FILENAME = "llm_prompt_stage1b.txt"
LLM_PROMPT_STAGE2_MAC_FILENAME = "llm_prompt_stage2_mac.txt"

DELIMITERS_FOR_DEVICE_DATA_PACKAGE = {
    "meta_start": "%%%START_META_JSON_CONTENT%%%",
    "meta_end": "%%%END_META_JSON_CONTENT%%%",
    "log1_start": "%%%START_FULL_WAVE1_LOG_CONTENT%%%",
    "log1_end": "%%%END_FULL_WAVE1_LOG_CONTENT%%%",
    "log2_start": "%%%START_FULL_WAVE2_LOG_CONTENT%%%",
    "log2_end": "%%%END_FULL_WAVE2_LOG_CONTENT%%%",
    "moonid_start": "%%%START_SITE_SPECIFIC_MOONID_DATA%%%",
    "moonid_end": "%%%END_SITE_SPECIFIC_MOONID_DATA%%%",
}
MISSING_WAVE1_LOG_PLACEHOLDER = "[NO WAVE 1 LOG PRESENT FOR THIS SWITCH]"
MISSING_WAVE2_LOG_PLACEHOLDER = (
    "[NO WAVE 2 LOG PRESENT FOR THIS SWITCH - NOT APPLICABLE OR NOT FOUND]"
)
MISSING_SITE_MOONID_PLACEHOLDER = (
    "[SITE MOONID DATA FILE NOT FOUND OR NOT APPLICABLE FOR THIS SITE]"
)

BASE_OUTPUT_DIR_JSON = (
    "validated_jsons_api_structured_MAC_CHUNKED_MP"  # This could also be a config var
)
BASE_ARCHIVE_DIR = os.path.join(BASE_OUTPUT_DIR_JSON, "_archive_source_files")
ERROR_LOGS_DIR_BATCH = os.path.join(
    BASE_OUTPUT_DIR_JSON, "_unified_script_error_logs")

# PATH_PLACEHOLDER_WING and PATH_PLACEHOLDER_AREA removed, will use utils.PATH_PLACEHOLDER_WING_DEFAULT etc.

MAX_WORKERS_FOR_POOL = 2
PRE_SUBMISSION_DELAY_SECONDS = 0.1

logger = logging.getLogger(__name__)


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(processName)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logger.info("Logging configured.")


def read_file_content(
    filepath: Optional[str], default_content_if_missing: str = ""
) -> str:
    if not filepath or not os.path.exists(filepath):
        logger.debug(
            f"File not found or path is None: {filepath}. Using default.")
        return default_content_if_missing
    try:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            logger.warning(
                f"UTF-8 decoding failed for {filepath}. Trying 'latin-1'.")
            with open(filepath, "r", encoding="latin-1") as f:
                return f.read()
    except Exception as e:
        logger.warning(
            f"Warning: Error reading file {filepath}: {e}. Using default.")
        return default_content_if_missing


def sanitize_log_content_for_llm(log_text: str) -> str:
    if not log_text:
        return ""
    log_text = log_text.replace("\\", "\\\\")
    log_text = log_text.replace('"', '\\"')
    log_text = log_text.replace("\r\n", "\\n")
    log_text = log_text.replace("\r", "\\n")
    log_text = log_text.replace("\n", "\\n")
    log_text = log_text.replace("\t", "\\t")
    log_text = log_text.replace("\x00", "")
    return log_text


def copy_file_to_dest_dir(
    source_path: Optional[str], dest_dir: str, dest_filename: Optional[str] = None
) -> Optional[str]:
    if not source_path or not os.path.exists(source_path):
        logger.debug(f"Archive: Source file not found: {source_path}")
        return None
    try:
        actual_dest_filename = (
            dest_filename if dest_filename else os.path.basename(source_path)
        )
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, actual_dest_filename)
        shutil.copy2(source_path, dest_path)
        logger.debug(f"Archived '{source_path}' to '{dest_path}'")
        return dest_path
    except Exception as e:
        logger.error(
            f"Archive: Error copying '{source_path}' to '{dest_dir}': {e}")
        return None


def extract_sn_from_meta_filename(meta_filename: str) -> Optional[str]:
    match = re.match(r"(.+?)-WAVE1\.meta\.json$", meta_filename, re.IGNORECASE)
    return match.group(1).upper() if match else None


def parse_metadata_for_location_and_sn(meta_filepath: str) -> Optional[dict]:
    try:
        with open(meta_filepath, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        sn_from_filename = extract_sn_from_meta_filename(
            os.path.basename(meta_filepath)
        )
        sn_from_content = str(
            metadata.get("final_serial_number") or metadata.get(
                "serial_number", "")
        ).upper()

        if not sn_from_filename and not sn_from_content:
            logger.warning(
                f"No SN found in filename or content for metadata file: {meta_filepath}"
            )
            return None

        final_sn = sn_from_filename if sn_from_filename else sn_from_content
        if sn_from_filename and sn_from_content and sn_from_filename != sn_from_content:
            logger.warning(
                f"SN mismatch for {meta_filepath}: File implies '{sn_from_filename}', Content has '{sn_from_content}'. Using filename-derived SN: '{final_sn}'."
            )

        site = metadata.get("final_site", metadata.get("site"))
        bldg = metadata.get("final_building", metadata.get("building"))
        flr = metadata.get("final_floor", metadata.get("floor"))

        if not all([site, bldg, flr, final_sn]):
            logger.warning(
                f"Missing essential fields in {meta_filepath}. SN='{final_sn}', Site='{site}', Bldg='{bldg}', Floor='{flr}'"
            )
            return None

        return {
            "site": str(site),
            "building": str(bldg),
            "floor": str(flr),
            "wing": str(metadata.get("final_wing", metadata.get("wing")))
            if metadata.get("final_wing", metadata.get("wing")) is not None
            else None,
            "area_name": str(metadata.get("final_area_name", metadata.get("area_name")))
            if metadata.get("final_area_name", metadata.get("area_name")) is not None
            else None,
            "sn": final_sn,
            "original_meta_filepath": meta_filepath,
            "raw_metadata_content_for_package": metadata,
        }
    except Exception as e:
        logger.error(f"Error parsing metadata {meta_filepath}: {e}")
        return None


def load_all_metadata(metadata_base_dir: str) -> Dict[str, Dict]:
    """Recursively loads all metadata files from the hierarchical structure."""
    all_meta_items_by_sn: Dict[str, Dict] = {}
    if not os.path.isdir(metadata_base_dir):
        logger.error(f"Metadata base directory not found: {metadata_base_dir}")
        return all_meta_items_by_sn

    logger.info(f"Recursively loading metadata from: {metadata_base_dir}")
    found_files_count = 0
    parsed_count = 0

    for root, _, files in os.walk(metadata_base_dir):
        for f_name in files:
            if f_name.lower().endswith("-wave1.meta.json"):
                found_files_count += 1
                meta_filepath = os.path.join(root, f_name)
                parsed_meta = parse_metadata_for_location_and_sn(meta_filepath)
                if parsed_meta and parsed_meta.get("sn"):
                    sn = parsed_meta["sn"]
                    if sn in all_meta_items_by_sn:
                        logger.warning(
                            f"Duplicate metadata found for SN {sn}. Existing: {all_meta_items_by_sn[sn]['original_meta_filepath']}, New: {meta_filepath}. Keeping first entry found."
                        )
                    else:
                        all_meta_items_by_sn[sn] = parsed_meta
                        parsed_count += 1
                else:
                    logger.warning(
                        f"Skipping invalid or SN-less metadata file: {meta_filepath}"
                    )

    logger.info(
        f"Found {found_files_count} Wave1 metadata files, successfully parsed {parsed_count} with valid SNs."
    )
    return all_meta_items_by_sn


def _get_lab_area_options(
    lab_areas_filepath: str,
) -> Optional[List[tuple[str, int, dict]]]:
    """Helper to load and format lab area options for display."""
    if not os.path.isfile(lab_areas_filepath):
        logger.error(f"Lab areas file not found: {lab_areas_filepath}")
        return None
    try:
        with open(lab_areas_filepath, "r", encoding="utf-8") as f:
            la_list = json.load(f)
        if not isinstance(la_list, list) or not all(
            isinstance(i, dict) for i in la_list
        ):
            logger.error(f"{lab_areas_filepath} not valid list of dicts.")
            return None
        if not la_list:
            logger.warning("Lab areas file empty.")
            return None
    except Exception as e:
        logger.error(f"Error reading {lab_areas_filepath}: {e}")
        return None

    opts = []
    for idx, la_entry in enumerate(la_list):
        s = la_entry.get("site", "N/A_Site")
        b = la_entry.get("building", "N/A_Bldg")
        f = la_entry.get("floor", "N/A_Flr")
        w_raw = la_entry.get("wing")
        a_raw = la_entry.get("lab_area_name")
        w_disp = (
            w_raw if w_raw and w_raw.strip() else utils.PATH_PLACEHOLDER_WING_DEFAULT
        )
        a_disp = (
            a_raw if a_raw and a_raw.strip() else utils.PATH_PLACEHOLDER_AREA_DEFAULT
        )
        opts.append((f"{s}/{b}/{f}/{w_disp}/{a_disp}", idx, la_entry))

    opts.sort(key=lambda x: x[0])
    return opts


def _normalize_lab_area_dict(
    selected_la_dict: dict,
) -> Optional[Dict[str, Optional[str]]]:
    """Helper to normalize a lab area dict and validate essential keys."""
    normalized_la = {
        "site": selected_la_dict.get("site"),
        "building": selected_la_dict.get("building"),
        "floor": selected_la_dict.get("floor"),
        "wing": selected_la_dict.get("wing"),  # Keep None if None
        # Keep None if None
        "lab_area_name": selected_la_dict.get("lab_area_name"),
    }
    if not all([normalized_la["site"], normalized_la["building"], normalized_la["floor"]]):
        logger.error(
            "Selected lab area from file is missing site, building, or floor. Cannot proceed."
        )
        return None
    return normalized_la


def select_lab_area(lab_areas_filepath: str) -> Optional[Dict[str, Optional[str]]]:
    opts = _get_lab_area_options(lab_areas_filepath)
    if not opts:
        return None

    print("\nSelect Lab Area for Batch Processing:")
    [print(f"  {i + 1}: {disp_str}")
     for i, (disp_str, _, _) in enumerate(opts)]
    while True:
        try:
            choice_str = input(f"Select number (1-{len(opts)}): ").strip()
            if not choice_str:
                continue
            choice_idx = int(choice_str) - 1
            if 0 <= choice_idx < len(opts):
                # Get the original dict
                _, _, selected_la_dict = opts[choice_idx]
                normalized_la = _normalize_lab_area_dict(selected_la_dict)
                if normalized_la:
                    logger.info(
                        f"User selected Lab Area for batch: {opts[choice_idx][0]}"
                    )
                return normalized_la
            else:
                print(f"Invalid selection (1-{len(opts)}).")
        except ValueError:
            print("Invalid input.")
        except (EOFError, KeyboardInterrupt):
            print("\nLab area selection aborted.")
            return None


def select_multiple_lab_areas(
    lab_areas_filepath: str,
) -> Optional[List[Dict[str, Optional[str]]]]:
    opts = _get_lab_area_options(lab_areas_filepath)
    if not opts:
        return None

    print("\nSelect One or More Lab Areas for Batch Processing:")
    [print(f"  {i + 1}: {disp_str}")
     for i, (disp_str, _, _) in enumerate(opts)]
    print(f"  A: Process ALL {len(opts)} lab areas listed above")
    while True:
        try:
            choice_str = input(
                "Select numbers (e.g., 1,5,11), 'A' for All, or press Enter to cancel: "
            ).strip().lower()

            if not choice_str:
                print("Selection cancelled.")
                return None

            selected_areas_to_normalize = []
            if choice_str == "a":
                selected_areas_to_normalize = [
                    la_dict for _, _, la_dict in opts]
                logger.info(
                    f"User selected ALL {len(selected_areas_to_normalize)} lab areas for processing."
                )
            else:
                indices = [int(i.strip()) -
                           1 for i in choice_str.split(",") if i.strip()]
                if all(0 <= idx < len(opts) for idx in indices):
                    unique_indices = sorted(list(set(indices)))
                    selected_areas_to_normalize = [
                        opts[idx][2] for idx in unique_indices]
                    logger.info(
                        f"User selected {len(selected_areas_to_normalize)} lab areas."
                    )
                else:
                    print(
                        f"Invalid selection. Use numbers between 1 and {len(opts)}.")
                    continue

            final_normalized_list = []
            for la_dict in selected_areas_to_normalize:
                normalized = _normalize_lab_area_dict(la_dict)
                if not normalized:
                    logger.error(
                        f"Skipping invalid lab area definition: {la_dict}")
                    continue
                final_normalized_list.append(normalized)

            return final_normalized_list if final_normalized_list else None

        except ValueError:
            print("Invalid input. Please enter numbers, 'A', or nothing to cancel.")
        except (EOFError, KeyboardInterrupt):
            print("\nLab area selection aborted.")
            return None


def get_target_paths_for_switch(meta_item: Dict) -> tuple[str, str]:
    # Uses utils for sanitization and path segment formatting
    s = utils.sanitize_foldername_part(
        meta_item.get("site"), "NoSite_Fallback")
    loc_segment = utils.format_location_log_folder_segment(
        building=meta_item.get("building"),
        floor=meta_item.get("floor"),
        wing=meta_item.get("wing"),  # Pass original wing (None or str)
        # Pass original area (None or str)
        area_name=meta_item.get("area_name"),
        wing_placeholder=utils.PATH_PLACEHOLDER_WING_DEFAULT,  # from utils
        area_placeholder=utils.PATH_PLACEHOLDER_AREA_DEFAULT,  # from utils
    )
    out_dir = os.path.join(BASE_OUTPUT_DIR_JSON, s, loc_segment)
    arch_dir = os.path.join(BASE_ARCHIVE_DIR, s, loc_segment)
    return out_dir, arch_dir


def prepare_single_switch_device_data_package(
    meta_item_to_process: Dict,
    # This is the path like .../_archive_source_files/Site/Bldg-Flr-Wing-Area
    base_archive_dir_for_switch: str,
) -> Optional[tuple[str, str]]:
    sn = meta_item_to_process["sn"]
    logger.debug(f"Preparing device data package for SN {sn}")
    target_archive_sn_dir = os.path.join(base_archive_dir_for_switch, sn)
    try:
        os.makedirs(target_archive_sn_dir, exist_ok=True)
    except OSError as e:
        logger.error(
            f"SN {sn}: Cannot create SN archive dir {target_archive_sn_dir}: {e}"
        )
        return None

    meta_content_for_package = json.dumps(
        meta_item_to_process.get("raw_metadata_content_for_package", {}), indent=4
    )

    archived_meta_path = copy_file_to_dest_dir(
        meta_item_to_process["original_meta_filepath"],
        target_archive_sn_dir,
        os.path.basename(meta_item_to_process["original_meta_filepath"]),
    )
    if not archived_meta_path:
        logger.error(
            f"SN {sn}: Critical - Failed to archive metadata file. Skipping package prep."
        )
        return None

    # Construct specific log directory path for this switch
    switch_site_sanitized = utils.sanitize_foldername_part(
        meta_item_to_process.get("site"), "NoSite_Fallback"
    )
    switch_loc_segment = utils.format_location_log_folder_segment(
        building=meta_item_to_process.get("building"),
        floor=meta_item_to_process.get("floor"),
        wing=meta_item_to_process.get("wing"),
        area_name=meta_item_to_process.get("area_name"),
        wing_placeholder=utils.PATH_PLACEHOLDER_WING_DEFAULT,
        area_placeholder=utils.PATH_PLACEHOLDER_AREA_DEFAULT,
    )
    specific_log_dir_for_sn = os.path.join(
        config.LOGS_DIR, switch_site_sanitized, switch_loc_segment
    )

    w1_log_path_original = os.path.join(
        specific_log_dir_for_sn, f"{sn}-WAVE1.txt")
    archived_w1_log_path = (
        copy_file_to_dest_dir(
            w1_log_path_original, target_archive_sn_dir, f"{sn}-WAVE1.txt"
        )
        if os.path.exists(w1_log_path_original)
        else None
    )
    if not archived_w1_log_path:
        logger.warning(
            f"SN {sn}: Wave 1 log not found at {w1_log_path_original}")
    w1_log_content_raw = read_file_content(
        archived_w1_log_path, MISSING_WAVE1_LOG_PLACEHOLDER
    )
    w1_log_content_for_package = sanitize_log_content_for_llm(
        w1_log_content_raw)

    w2_log_path_original = os.path.join(
        specific_log_dir_for_sn, f"{sn}-WAVE2.txt")
    archived_w2_log_path = (
        copy_file_to_dest_dir(
            w2_log_path_original, target_archive_sn_dir, f"{sn}-WAVE2.txt"
        )
        if os.path.exists(w2_log_path_original)
        else None
    )
    if not archived_w2_log_path:
        logger.debug(
            f"SN {sn}: Wave 2 log not found at {w2_log_path_original} (optional)."
        )
    w2_log_content_raw = read_file_content(
        archived_w2_log_path, MISSING_WAVE2_LOG_PLACEHOLDER
    )
    w2_log_content_for_package = sanitize_log_content_for_llm(
        w2_log_content_raw)
    sanitized_missing_w2_placeholder = sanitize_log_content_for_llm(
        MISSING_WAVE2_LOG_PLACEHOLDER
    )
    if w2_log_content_for_package == sanitized_missing_w2_placeholder:
        w2_log_content_for_package = ""

    site_for_moonid = meta_item_to_process.get("site")
    raw_moonid_content = MISSING_SITE_MOONID_PLACEHOLDER
    if site_for_moonid:
        expected_moonid_fname = f"{str(site_for_moonid).upper()}_moonids.json"
        potential_moonid_path_original = os.path.join(
            config.DATA_DIR, expected_moonid_fname
        )  # Use config.DATA_DIR
        if os.path.exists(potential_moonid_path_original):
            archived_moonid_data_path = copy_file_to_dest_dir(
                potential_moonid_path_original,
                target_archive_sn_dir,
                os.path.basename(potential_moonid_path_original),
            )
            raw_moonid_content = read_file_content(
                archived_moonid_data_path, MISSING_SITE_MOONID_PLACEHOLDER
            )
        else:
            logger.warning(
                f"SN {sn}: Site MOONID file '{expected_moonid_fname}' not found in {config.DATA_DIR}. Using placeholder."
            )
    else:
        logger.warning(
            f"SN {sn}: Site info missing in metadata. Cannot find MOONID file. Using placeholder."
        )

    if raw_moonid_content == MISSING_SITE_MOONID_PLACEHOLDER:
        moonid_content_for_package = sanitize_log_content_for_llm(
            raw_moonid_content)
    else:
        moonid_content_for_package = (
            raw_moonid_content  # Assume valid JSON, no LLM sanitization
        )

    device_data_package_str = (
        f"{DELIMITERS_FOR_DEVICE_DATA_PACKAGE['meta_start']}\n{meta_content_for_package.strip()}\n{DELIMITERS_FOR_DEVICE_DATA_PACKAGE['meta_end']}\n\n"
        f"{DELIMITERS_FOR_DEVICE_DATA_PACKAGE['log1_start']}\n{w1_log_content_for_package.strip()}\n{DELIMITERS_FOR_DEVICE_DATA_PACKAGE['log1_end']}\n\n"
    )
    if w2_log_content_for_package.strip():
        device_data_package_str += f"{DELIMITERS_FOR_DEVICE_DATA_PACKAGE['log2_start']}\n{w2_log_content_for_package.strip()}\n{DELIMITERS_FOR_DEVICE_DATA_PACKAGE['log2_end']}\n\n"
    device_data_package_str += f"{DELIMITERS_FOR_DEVICE_DATA_PACKAGE['moonid_start']}\n{moonid_content_for_package.strip()}\n{DELIMITERS_FOR_DEVICE_DATA_PACKAGE['moonid_end']}\n"

    device_data_filepath = os.path.join(
        target_archive_sn_dir, f"{sn}_llm_input_package.txt"
    )
    try:
        with open(device_data_filepath, "w", encoding="utf-8") as pkg_f:
            pkg_f.write(device_data_package_str)
        logger.debug(
            f"SN {sn}: Device data package file prepared: {device_data_filepath}"
        )
        return device_data_filepath, sn
    except IOError as e_save:
        logger.error(
            f"SN {sn}: Failed to save device data package '{device_data_filepath}': {e_save}"
        )
        return None


def process_single_switch(
    all_metadata_by_sn: Dict[str, Dict],
    prompt1a: str,
    prompt1b: str,
    prompt2mac: str,
    skip_mac_processing: bool,
):
    logger.info("\n--- Processing Single Switch Mode ---")
    while True:
        target_sn_input = input("Enter SN to process: ").strip().upper()
        if not target_sn_input:
            logger.warning("No SN entered.")
            continue
        if target_sn_input in all_metadata_by_sn:
            target_meta = all_metadata_by_sn[target_sn_input]
            logger.info(f"Found metadata for SN: {target_sn_input}")
            break
        else:
            logger.error(f"SN '{target_sn_input}' not in metadata.")
            if input("Try again? (y/n): ").lower() != "y":
                logger.info("Aborting.")
                return

    output_dir_for_switch, archive_base_dir_for_switch = get_target_paths_for_switch(
        target_meta
    )
    try:
        os.makedirs(output_dir_for_switch, exist_ok=True)
    except OSError as e_mkdir:
        logger.error(
            f"SN {target_sn_input}: Cannot create output dir {output_dir_for_switch}: {e_mkdir}"
        )
        return

    expected_output_path = os.path.join(
        output_dir_for_switch, f"{target_sn_input}_validated.json"
    )
    should_process = True
    if os.path.exists(expected_output_path):
        logger.warning(f"Output file exists: {expected_output_path}")
        while True:
            overwrite_choice = input("Overwrite? (yes/no/abort): ").lower()
            if overwrite_choice == "yes":
                logger.info(f"Will overwrite for SN {target_sn_input}.")
                try:
                    os.remove(expected_output_path)
                except OSError as e_del:
                    logger.error(
                        f"Failed to delete {expected_output_path}: {e_del}. Aborting."
                    )
                    should_process = False
                break
            elif overwrite_choice == "no":
                logger.info(f"Skipping SN {target_sn_input}.")
                should_process = False
                break
            elif overwrite_choice == "abort":
                logger.info("Aborting.")
                should_process = False
                break
            else:
                print("Invalid choice.")
    if not should_process:
        return

    logger.info(f"SN {target_sn_input}: Preparing device data package...")
    prep_result = prepare_single_switch_device_data_package(
        target_meta, archive_base_dir_for_switch
    )
    if not prep_result:
        logger.error(
            f"SN {target_sn_input}: Failed to prepare device data package.")
        return

    device_data_filepath, _ = prep_result
    logger.info(f"SN {target_sn_input}: Calling LLM processing function...")
    try:
        success = gemini.process_llm_package_file_to_json(
            input_device_data_filepath=device_data_filepath,
            serial_number=target_sn_input,
            output_dir=output_dir_for_switch,
            prompt_stage1a_content=prompt1a,
            prompt_stage1b_content=prompt1b,
            prompt_stage2_mac_content=prompt2mac,
            skip_mac_processing=skip_mac_processing,
        )
        if success:
            logger.info(f"SN {target_sn_input}: Successfully processed.")
        else:
            logger.error(
                f"SN {target_sn_input}: Failed processing. Check logs in {output_dir_for_switch}"
            )
    except Exception as e_gemini:
        logger.error(
            f"SN {target_sn_input}: CRITICAL ERROR calling gemini: {e_gemini}")
        logger.error(traceback.format_exc())
    logger.info("--- Single Switch Processing Finished ---")


def _run_batch_for_one_lab_area(
    switches_to_process_queue: List[Dict],
    lab_area_definition: Dict,
    prompt1a: str,
    prompt1b: str,
    prompt2mac: str,
    skip_mac_processing: bool,
):
    """
    Core, non-interactive function to run a multiprocessing batch for a given list of switches.
    Assumes decisions about which switches to process have already been made.
    """
    if not switches_to_process_queue:
        logger.info(
            "No switches in the queue to process for this lab area. Skipping execution.")
        return

    # Use first switch to determine base output path for the entire area
    current_lab_area_output_dir, current_lab_area_archive_base_dir = (
        get_target_paths_for_switch(switches_to_process_queue[0])
    )
    lab_area_display_path = os.path.relpath(
        current_lab_area_output_dir, BASE_OUTPUT_DIR_JSON
    )

    logger.info(
        f"\n--- Running batch for lab area: {lab_area_display_path} ---")
    logger.info(
        f"Will attempt to process {len(switches_to_process_queue)} switches."
    )

    tasks_for_pool: List[tuple] = []
    logger.info(
        "Preparing device data packages for all switches in this batch...")
    prep_failed_count = 0
    for meta_item_prep in switches_to_process_queue:
        package_prep_result = prepare_single_switch_device_data_package(
            meta_item_prep, current_lab_area_archive_base_dir
        )
        if package_prep_result:
            input_pkg_path, sn_prepared = package_prep_result
            tasks_for_pool.append(
                (
                    input_pkg_path,
                    sn_prepared,
                    current_lab_area_output_dir,
                    prompt1a,
                    prompt1b,
                    prompt2mac,
                    skip_mac_processing,
                )
            )
        else:
            logger.error(
                f"Failed to prepare input package for SN {meta_item_prep['sn']}. It will be skipped."
            )
            prep_failed_count += 1

    if not tasks_for_pool:
        logger.error(
            "No tasks could be prepared for processing for this lab area.")
        return
    logger.info(
        f"Successfully prepared {len(tasks_for_pool)} tasks for submission to process pool. ({prep_failed_count} failed preparation)."
    )

    successful_mp_switches = 0
    failed_mp_switches = 0
    try:
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=MAX_WORKERS_FOR_POOL
        ) as executor:
            future_to_task_info: Dict[concurrent.futures.Future, tuple[str, str]] = {
            }
            logger.info(
                f"Submitting {len(tasks_for_pool)} tasks to ProcessPoolExecutor with {MAX_WORKERS_FOR_POOL} workers..."
            )
            for (
                input_pkg_path,
                sn_for_task,
                lab_area_output_dir_for_task,
                p1a_task,
                p1b_task,
                p2m_task,
                skip_mac_flag_for_task,
            ) in tasks_for_pool:
                future = executor.submit(
                    gemini.process_llm_package_file_to_json,
                    input_pkg_path,
                    sn_for_task,
                    lab_area_output_dir_for_task,
                    p1a_task,
                    p1b_task,
                    p2m_task,
                    skip_mac_flag_for_task,
                )
                future_to_task_info[future] = (sn_for_task, input_pkg_path)
                if PRE_SUBMISSION_DELAY_SECONDS > 0:
                    time.sleep(PRE_SUBMISSION_DELAY_SECONDS)

            logger.info(
                f"All {len(tasks_for_pool)} tasks submitted. Waiting for completion..."
            )
            for i, future_item in enumerate(
                concurrent.futures.as_completed(future_to_task_info)
            ):
                sn_processed, pkg_path_processed = future_to_task_info[future_item]
                logger.info(
                    f"--- MP Result {i + 1}/{len(tasks_for_pool)} for SN: {sn_processed} (Package: {os.path.basename(pkg_path_processed)}) ---"
                )
                try:
                    result_success = future_item.result()
                    if result_success:
                        logger.info(
                            f"SN {sn_processed}: Successfully processed by worker."
                        )
                        successful_mp_switches += 1
                    else:
                        logger.error(
                            f"SN {sn_processed}: Failed processing by worker. Check logs in {current_lab_area_output_dir}"
                        )
                        failed_mp_switches += 1
                except Exception as exc:
                    logger.error(
                        f"SN {sn_processed}: Worker process raised an exception: {exc}"
                    )
                    logger.error(traceback.format_exc())
                    failed_mp_switches += 1
                    # Note: gemini.py handles its own detailed error logging
    except KeyboardInterrupt:
        logger.warning(
            "KeyboardInterrupt received by main process during batch execution. Shutting down..."
        )
    except Exception as e_pool:
        logger.critical(
            f"A critical error occurred with the ProcessPoolExecutor: {e_pool}"
        )
        logger.critical(traceback.format_exc())

    logger.info(f"\n--- Summary for Lab Area: {lab_area_display_path} ---")
    logger.info(f"Total tasks prepared for pool: {len(tasks_for_pool)}")
    logger.info(f"Switches skipped due to failed prep: {prep_failed_count}")
    logger.info(f"Successfully processed via pool: {successful_mp_switches}")
    logger.info(f"Failed or errored in pool: {failed_mp_switches}")
    if failed_mp_switches > 0 or prep_failed_count > 0:
        logger.warning(
            f"Check processor & gemini.py error logs for specific SNs under: {os.path.abspath(current_lab_area_output_dir)}"
        )


def process_lab_area_batch(
    all_metadata_by_sn: Dict[str, Dict],
    prompt1a: str,
    prompt1b: str,
    prompt2mac: str,
    skip_mac_processing: bool,
):
    logger.info("\n--- Processing Lab Area Batch Mode (Single Area) ---")
    selected_lab_area_definition = select_lab_area(LAB_AREAS_FILE)
    if not selected_lab_area_definition:
        logger.warning("No lab area selected. Exiting batch.")
        return

    switches_in_selected_lab_area_meta = [
        meta
        for meta in all_metadata_by_sn.values()
        if meta.get("site") == selected_lab_area_definition.get("site")
        and meta.get("building") == selected_lab_area_definition.get("building")
        and meta.get("floor") == selected_lab_area_definition.get("floor")
        and (meta.get("wing") or "") == (selected_lab_area_definition.get("wing") or "")
        and (meta.get("area_name") or "")
        == (selected_lab_area_definition.get("lab_area_name") or "")
    ]

    if not switches_in_selected_lab_area_meta:
        logger.info(
            f"No metadata items found for selected lab area: {selected_lab_area_definition}"
        )
        return
    logger.info(
        f"Found {len(switches_in_selected_lab_area_meta)} switches in selected lab area."
    )

    current_lab_area_output_dir, current_lab_area_archive_base_dir = (
        get_target_paths_for_switch(switches_in_selected_lab_area_meta[0])
    )
    lab_area_display_path = os.path.relpath(
        current_lab_area_output_dir, BASE_OUTPUT_DIR_JSON
    )
    try:
        os.makedirs(current_lab_area_output_dir, exist_ok=True)
        os.makedirs(current_lab_area_archive_base_dir, exist_ok=True)
    except OSError as e_mkdir:
        logger.error(
            f"Could not create dirs for lab area: {lab_area_display_path}: {e_mkdir}"
        )
        return

    switches_to_process_queue: List[Dict] = []
    existing_output_sns: List[str] = [
        meta["sn"]
        for meta in switches_in_selected_lab_area_meta
        if os.path.exists(
            os.path.join(current_lab_area_output_dir,
                         f"{meta['sn']}_validated.json")
        )
    ]

    if existing_output_sns:
        logger.warning(
            f"Found existing output JSONs for {len(existing_output_sns)} SN(s) in {lab_area_display_path}:"
        )
        while True:
            print("\nOptions for handling existing files in this lab area:")
            print(
                "  1: Skip processing for these existing SN(s), process only missing."
            )
            print(
                "  2: Delete ALL outputs & archives for THIS LAB AREA & Reprocess all."
            )
            print("  3: Abort batch processing for this lab area.")
            user_choice_exist = input("Enter choice (1, 2, or 3): ").strip()
            if user_choice_exist == "1":
                logger.info("User chose to SKIP processing for existing SNs.")
                switches_to_process_queue = [
                    meta
                    for meta in switches_in_selected_lab_area_meta
                    if meta["sn"] not in existing_output_sns
                ]
                break
            elif user_choice_exist == "2":
                confirm = (
                    input(
                        f"ARE YOU SURE you want to delete all outputs and archives for ALL {len(switches_in_selected_lab_area_meta)} switches in '{lab_area_display_path}'? (yes/no): "
                    )
                    .strip().lower()
                )
                if confirm == "yes":
                    for meta_to_clear in switches_in_selected_lab_area_meta:
                        sn_to_clear = meta_to_clear["sn"]
                        json_to_delete = os.path.join(
                            current_lab_area_output_dir, f"{sn_to_clear}_validated.json"
                        )
                        if os.path.exists(json_to_delete):
                            try:
                                os.remove(json_to_delete)
                            except OSError:
                                pass
                        sn_archive_dir_to_delete = os.path.join(
                            current_lab_area_archive_base_dir, sn_to_clear
                        )
                        if os.path.isdir(sn_archive_dir_to_delete):
                            try:
                                shutil.rmtree(sn_archive_dir_to_delete)
                            except OSError:
                                pass
                    switches_to_process_queue = list(
                        switches_in_selected_lab_area_meta)
                    break
                else:
                    continue
            elif user_choice_exist == "3":
                logger.info("User chose to ABORT lab area batch processing.")
                return
            else:
                print("Invalid choice.")
    else:
        switches_to_process_queue = list(switches_in_selected_lab_area_meta)

    if not switches_to_process_queue:
        logger.info(
            "No switches remaining in the queue to process for this lab area.")
        return
    if input("Proceed with batch processing? (yes/no): ").strip().lower() != "yes":
        logger.info("Batch processing cancelled by user.")
        return

    _run_batch_for_one_lab_area(
        switches_to_process_queue, selected_lab_area_definition, prompt1a, prompt1b, prompt2mac, skip_mac_processing
    )


def process_multiple_lab_area_batches(
    all_metadata_by_sn: Dict[str, Dict],
    prompt1a: str,
    prompt1b: str,
    prompt2mac: str,
    skip_mac_processing: bool,
):
    logger.info("\n--- Processing Multiple Lab Area Batches Mode ---")
    selected_lab_areas = select_multiple_lab_areas(LAB_AREAS_FILE)
    if not selected_lab_areas:
        logger.warning("No lab areas selected. Exiting multi-batch mode.")
        return

    # --- Pre-flight check and planning phase ---
    logger.info("\n--- Pre-Flight Configuration for Selected Lab Areas ---")
    processing_plan = []
    total_switches_to_process = 0

    for i, lab_area_def in enumerate(selected_lab_areas):
        s_disp = utils.format_location_log_folder_segment(
            lab_area_def["site"], lab_area_def["building"], lab_area_def["floor"],
            lab_area_def["wing"], lab_area_def["lab_area_name"]
        ).replace("/", " / ")
        logger.info(
            f"\n--- Planning for Area {i+1}/{len(selected_lab_areas)}: {s_disp} ---")

        switches_in_area = [
            meta for meta in all_metadata_by_sn.values()
            if meta.get("site") == lab_area_def.get("site")
            and meta.get("building") == lab_area_def.get("building")
            and meta.get("floor") == lab_area_def.get("floor")
            and (meta.get("wing") or "") == (lab_area_def.get("wing") or "")
            and (meta.get("area_name") or "") == (lab_area_def.get("lab_area_name") or "")
        ]

        if not switches_in_area:
            logger.warning(
                f"No metadata found for switches in this area. It will be skipped.")
            continue

        output_dir, archive_dir = get_target_paths_for_switch(
            switches_in_area[0])
        existing_sns = [
            meta["sn"] for meta in switches_in_area
            if os.path.exists(os.path.join(output_dir, f"{meta['sn']}_validated.json"))
        ]

        action = "process_all"
        switches_for_plan = list(switches_in_area)

        if existing_sns:
            while True:
                print(
                    f"Found existing output for {len(existing_sns)} of {len(switches_in_area)} switches.")
                print("Options for this area:")
                print("  1: Skip existing, process only new/missing switches.")
                print(
                    "  2: Reprocess ALL switches in this area (deletes existing outputs).")
                print("  3: Skip this entire lab area.")
                choice = input("Enter choice (1, 2, or 3): ").strip()
                if choice == "1":
                    action = "skip_existing"
                    switches_for_plan = [
                        s for s in switches_in_area if s["sn"] not in existing_sns]
                    logger.info(
                        f"PLAN: Will process {len(switches_for_plan)} new switch(es) in this area.")
                    break
                elif choice == "2":
                    action = "reprocess_all"
                    switches_for_plan = list(switches_in_area)
                    logger.info(
                        f"PLAN: Will reprocess all {len(switches_for_plan)} switch(es) in this area.")
                    break
                elif choice == "3":
                    action = "skip_area"
                    switches_for_plan = []
                    logger.info(f"PLAN: Will skip this entire lab area.")
                    break
                else:
                    print("Invalid choice.")
        else:
            logger.info(
                f"No existing outputs found. Will process all {len(switches_in_area)} switches.")

        if switches_for_plan:
            processing_plan.append({
                "definition": lab_area_def,
                "switches_to_process": switches_for_plan,
                "action": action
            })
            total_switches_to_process += len(switches_for_plan)

    # --- Confirmation Phase ---
    if not processing_plan:
        logger.info(
            "\nNo lab areas or switches are queued for processing after planning phase. Exiting.")
        return

    logger.info("\n--- Overall Processing Plan Summary ---")
    logger.info(
        f"Will process a total of {total_switches_to_process} switches across {len(processing_plan)} lab areas.")
    for plan_item in processing_plan:
        s_disp = utils.format_location_log_folder_segment(
            plan_item["definition"]["site"], plan_item["definition"]["building"], plan_item["definition"]["floor"],
            plan_item["definition"]["wing"], plan_item["definition"]["lab_area_name"]
        ).replace("/", " / ")
        logger.info(
            f"  - Area: {s_disp} -> {len(plan_item['switches_to_process'])} switches ({plan_item['action']})")

    if input("\nProceed with this plan? (yes/no): ").strip().lower() != "yes":
        logger.info("Processing cancelled by user.")
        return

    # --- Execution Phase ---
    logger.info("\n--- Starting Execution of Multi-Batch Plan ---")
    for i, plan_item in enumerate(processing_plan):
        logger.info(f"\n>>> Starting Batch {i+1}/{len(processing_plan)} <<<")
        lab_def = plan_item["definition"]
        switches_to_run = plan_item["switches_to_process"]
        action = plan_item["action"]

        if action == "reprocess_all":
            logger.info(
                "Action is 'reprocess_all', cleaning up existing outputs for this area...")
            output_dir, archive_dir = get_target_paths_for_switch(
                switches_to_run[0])
            all_switches_in_area = [  # Find all switches again to be sure
                meta for meta in all_metadata_by_sn.values()
                if meta.get("site") == lab_def.get("site") and meta.get("building") == lab_def.get("building")
                and meta.get("floor") == lab_def.get("floor") and (meta.get("wing") or "") == (lab_def.get("wing") or "")
                and (meta.get("area_name") or "") == (lab_def.get("lab_area_name") or "")
            ]
            for meta_to_clear in all_switches_in_area:
                sn_to_clear = meta_to_clear["sn"]
                json_to_delete = os.path.join(
                    output_dir, f"{sn_to_clear}_validated.json")
                if os.path.exists(json_to_delete):
                    try:
                        os.remove(json_to_delete)
                    except OSError:
                        pass
                sn_archive_dir_to_delete = os.path.join(
                    archive_dir, sn_to_clear)
                if os.path.isdir(sn_archive_dir_to_delete):
                    try:
                        shutil.rmtree(sn_archive_dir_to_delete)
                    except OSError:
                        pass

        _run_batch_for_one_lab_area(
            switches_to_run, lab_def, prompt1a, prompt1b, prompt2mac, skip_mac_processing
        )

    logger.info("\n--- All Selected Lab Area Batches Have Been Processed ---")


def run_main_processor():
    logger.info(
        "--- Unified Network Survey LLM Processor (Multi-Prompt Version) ---")
    try:
        os.makedirs(BASE_OUTPUT_DIR_JSON, exist_ok=True)
        os.makedirs(BASE_ARCHIVE_DIR, exist_ok=True)
        os.makedirs(ERROR_LOGS_DIR_BATCH, exist_ok=True)
        logger.info(
            f"Output base: {os.path.abspath(BASE_OUTPUT_DIR_JSON)}, Archive base: {os.path.abspath(BASE_ARCHIVE_DIR)}"
        )
    except OSError as e:
        logger.critical(
            f"Could not create base output directories: {e}. Exiting.")
        return

    script_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
    llm_prompt_stage1a_filepath = os.path.join(
        script_dir, LLM_PROMPT_STAGE1A_FILENAME)
    llm_prompt_stage1b_filepath = os.path.join(
        script_dir, LLM_PROMPT_STAGE1B_FILENAME)
    llm_prompt_stage2_mac_filepath = os.path.join(
        script_dir, LLM_PROMPT_STAGE2_MAC_FILENAME
    )

    prompt1a_text = read_file_content(llm_prompt_stage1a_filepath)
    prompt1b_text = read_file_content(llm_prompt_stage1b_filepath)
    prompt2mac_text = read_file_content(llm_prompt_stage2_mac_filepath)

    if not all([prompt1a_text, prompt1b_text, prompt2mac_text]):
        logger.critical(
            f"One or more LLM prompt files are missing/empty. Checked: {LLM_PROMPT_STAGE1A_FILENAME}, {LLM_PROMPT_STAGE1B_FILENAME}, {LLM_PROMPT_STAGE2_MAC_FILENAME}. Exiting."
        )
        return
    logger.info("Loaded all three stage-specific LLM prompts.")

    all_metadata_by_sn = load_all_metadata(config.METADATA_DIR)
    if not all_metadata_by_sn:
        logger.error("No valid metadata loaded. Cannot proceed.")
        return

    # --- Ask user about skipping MAC processing for the entire run ---
    skip_mac_processing_for_run = False
    while True:
        choice = input(
            "\nSkip MAC address table processing (Stage 2) for this run? (yes/no): "
        ).strip().lower()
        if choice in ["yes", "y"]:
            skip_mac_processing_for_run = True
            logger.warning("=" * 60)
            logger.warning(
                "!!! MAC TABLE PROCESSING WILL BE SKIPPED FOR THIS RUN !!!")
            logger.warning(
                "!!! Final JSONs will contain an empty 'mac_entries' list. !!!")
            logger.warning("=" * 60)
            break
        elif choice in ["no", "n"]:
            skip_mac_processing_for_run = False
            logger.info(
                "MAC address table processing is ENABLED for this run.")
            break
        else:
            print("Invalid choice. Please enter 'yes' or 'no'.")

    while True:
        print("\nSelect Processing Mode:")
        print("  1: Process a Single Switch by Serial Number")
        print("  2: Process a Batch for ONE Lab Area (Multiprocessing)")
        print("  3: Process Batches for MULTIPLE Lab Areas (Multiprocessing)")
        print("  4: Exit")
        mode_choice = input("Enter choice (1, 2, 3, or 4): ").strip()

        if mode_choice == "1":
            process_single_switch(
                all_metadata_by_sn, prompt1a_text, prompt1b_text, prompt2mac_text, skip_mac_processing_for_run
            )
        elif mode_choice == "2":
            process_lab_area_batch(
                all_metadata_by_sn, prompt1a_text, prompt1b_text, prompt2mac_text, skip_mac_processing_for_run
            )
        elif mode_choice == "3":
            process_multiple_lab_area_batches(
                all_metadata_by_sn, prompt1a_text, prompt1b_text, prompt2mac_text, skip_mac_processing_for_run
            )
        elif mode_choice == "4":
            logger.info("Exiting processor.")
            break
        else:
            print("Invalid choice. Please enter 1, 2, 3, or 4.")


if __name__ == "__main__":
    setup_logging()
    try:
        run_main_processor()
    except KeyboardInterrupt:
        logger.warning(
            "\nScript execution interrupted by user (KeyboardInterrupt).")
    except Exception as e_main_global:
        logger.critical(
            f"An unhandled critical error occurred: {e_main_global}")
        logger.critical(traceback.format_exc())
        try:
            os.makedirs(ERROR_LOGS_DIR_BATCH, exist_ok=True)
            with open(
                os.path.join(
                    ERROR_LOGS_DIR_BATCH, "PROCESSOR_CRITICAL_GLOBAL_ERROR.txt"
                ),
                "w",
            ) as ge_f:
                ge_f.write(
                    f"Global unhandled error in processor script.\nError: {e_main_global}\nTraceback: {traceback.format_exc()}"
                )
        except Exception as e_log_crit:
            print(
                f"Additionally, failed to write critical error to log file: {e_log_crit}"
            )
    finally:
        logger.info("--- Unified Processor Script Finished ---")
