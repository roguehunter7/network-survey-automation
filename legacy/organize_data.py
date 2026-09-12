# organize_survey_data.py
import json
import logging
import os
import re
import shutil
import sys
from typing import Optional  # Added for type hinting

# --- Attempt to import config and utils for paths and helper functions ---
try:
    CURRENT_SCRIPT_DIR_ORG = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT_ORG = CURRENT_SCRIPT_DIR_ORG

    PARENT_OF_SCRIPT_DIR_ORG = os.path.dirname(CURRENT_SCRIPT_DIR_ORG)
    if os.path.exists(os.path.join(PARENT_OF_SCRIPT_DIR_ORG, "config.py")):
        if PARENT_OF_SCRIPT_DIR_ORG not in sys.path:
            sys.path.insert(0, PARENT_OF_SCRIPT_DIR_ORG)
        PROJECT_ROOT_ORG = PARENT_OF_SCRIPT_DIR_ORG
    elif CURRENT_SCRIPT_DIR_ORG not in sys.path:
        sys.path.insert(0, CURRENT_SCRIPT_DIR_ORG)

    import config as app_config_org
    from utils import (
        PATH_PLACEHOLDER_AREA_DEFAULT,
        PATH_PLACEHOLDER_WING_DEFAULT,
        format_location_log_folder_segment,
        # generate_safe_filename, # Not strictly needed here if LLM package name is fixed
        sanitize_foldername_part,
    )

    UTILS_IMPORTED_SUCCESSFULLY = True
    # Use paths from config.py
    METADATA_DIR = app_config_org.METADATA_DIR  # Hierarchical metadata
    LOGS_BASE_DIR = app_config_org.LOGS_DIR
    SITE_MOONID_DATA_BASE_DIR = app_config_org.DATA_DIR
    OUTPUT_BASE_DIR = os.path.join(
        PROJECT_ROOT_ORG, "organized_llm_input_packages"
    )  # Changed output dir name

    print(
        "organize_survey_data.py: Successfully imported 'config.py' and 'utils.py'. Using configured paths."
    )

except ImportError as e_imp:
    UTILS_IMPORTED_SUCCESSFULLY = False
    print(
        f"organize_survey_data.py: WARNING: Could not import 'config.py' or 'utils.py' (Error: {e_imp})."
    )
    print("Falling back to default relative paths, assuming script is in project root.")
    PROJECT_ROOT_ORG = os.path.dirname(os.path.abspath(__file__))
    # Fallback paths assuming a specific structure if config.py is not found
    METADATA_DIR = os.path.join(
        PROJECT_ROOT_ORG, "survey_outputs", "metadata"
    )  # Adjusted fallback
    LOGS_BASE_DIR = os.path.join(
        PROJECT_ROOT_ORG, "survey_outputs", "logs"
    )  # Adjusted fallback
    SITE_MOONID_DATA_BASE_DIR = os.path.join(PROJECT_ROOT_ORG, "data")
    OUTPUT_BASE_DIR = os.path.join(PROJECT_ROOT_ORG, "organized_llm_input_packages")

    # Define fallback utility functions if utils.py was not imported
    PATH_PLACEHOLDER_WING_DEFAULT = "__NoWing__"
    PATH_PLACEHOLDER_AREA_DEFAULT = "__NoArea__"

    def sanitize_foldername_part(name_part: str, placeholder: str = "Unknown") -> str:
        if name_part is None or str(name_part).strip() == "":
            return placeholder
        s_name = str(name_part)
        s_name = (
            s_name.replace(" ", "_")
            .replace("/", "-")
            .replace("\\", "-")
            .replace(":", "-")
        )
        s_name = (
            s_name.replace("*", "-")
            .replace("?", "")
            .replace('"', "")
            .replace("<", "")
            .replace(">", "")
            .replace("|", "")
        )
        s_name = re.sub(r"[^\w.\-_]", "", s_name)
        s_name = re.sub(r"[_]+", "_", s_name)
        s_name = re.sub(r"[-]+", "-", s_name)
        s_name = s_name.strip("_-.")
        return s_name if s_name else placeholder

    def format_location_log_folder_segment(
        building: str,
        floor: str,
        wing: str,
        area_name: str,
        wing_placeholder: str,
        area_placeholder: str,
    ) -> str:
        s_bldg = sanitize_foldername_part(building, "NoBuilding_Fallback")
        s_floor = sanitize_foldername_part(floor, "NoFloor_Fallback")
        s_wing = sanitize_foldername_part(wing, wing_placeholder)
        s_area = sanitize_foldername_part(area_name, area_placeholder)
        return f"{s_bldg}-{s_floor}-{s_wing}-{s_area}"


# This script might still use its own way to name output packages,
# but utils.generate_safe_filename is generally preferred.
LLM_PROMPT_FILENAME_ORG = "llm_prompt_structured_output_v1.txt"

DELIMITERS_ORG = {
    "prompt_start": "%%%START_LLM_PROMPT_STRUCTURED_OUTPUT_V1%%%",  # Kept for this script's package format
    "prompt_end": "%%%END_LLM_PROMPT_STRUCTURED_OUTPUT_V1%%%",
    "meta_start": "%%%START_META_JSON_CONTENT%%%",
    "meta_end": "%%%END_META_JSON_CONTENT%%%",
    "log1_start": "%%%START_FULL_WAVE1_LOG_CONTENT%%%",
    "log1_end": "%%%END_FULL_WAVE1_LOG_CONTENT%%%",
    "log2_start": "%%%START_FULL_WAVE2_LOG_CONTENT%%%",
    "log2_end": "%%%END_FULL_WAVE2_LOG_CONTENT%%%",
    "moonid_start": "%%%START_SITE_SPECIFIC_MOONID_DATA%%%",
    "moonid_end": "%%%END_SITE_SPECIFIC_MOONID_DATA%%%",
}
MISSING_WAVE1_LOG_PLACEHOLDER_ORG = "[NO WAVE 1 LOG PRESENT FOR THIS SWITCH]"
MISSING_SITE_MOONID_PLACEHOLDER_ORG = (
    "[SITE MOONID DATA FILE NOT FOUND OR NOT APPLICABLE]"
)

logger_org = logging.getLogger("organize_survey_data")
if not logger_org.handlers:
    handler_org = logging.StreamHandler(sys.stdout)
    formatter_org = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler_org.setFormatter(formatter_org)
    logger_org.addHandler(handler_org)
    logger_org.setLevel(logging.INFO)


def sanitize_log_content_for_llm(
    log_text: str,
) -> str:  # Added this function locally if utils not imported
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


# Helper function, similar to unified_processor.py's extract_sn_from_meta_filename
def _extract_sn_from_meta_filename_org(meta_filename: str) -> Optional[str]:
    match = re.match(r"(.+?)-WAVE1\.meta\.json$", meta_filename, re.IGNORECASE)
    return match.group(1).upper() if match else None


def parse_metadata_for_location(meta_filepath: str) -> Optional[dict]:
    try:
        with open(meta_filepath, "r", encoding="utf-8") as f:
            metadata_content = json.load(f)

        sn_from_filename = _extract_sn_from_meta_filename_org(
            os.path.basename(meta_filepath)
        )
        sn_from_content_raw = metadata_content.get(
            "final_serial_number", metadata_content.get("serial_number", "")
        )
        sn_from_content = (
            str(sn_from_content_raw).upper() if sn_from_content_raw else ""
        )

        if not sn_from_filename and not sn_from_content:
            logger_org.warning(
                f"No SN found in filename or content for metadata file: {meta_filepath}. Skipping."
            )
            return None

        final_sn = sn_from_filename if sn_from_filename else sn_from_content
        if sn_from_filename and sn_from_content and sn_from_filename != sn_from_content:
            logger_org.warning(
                f"SN mismatch for {meta_filepath}: File implies '{sn_from_filename}', Content has '{sn_from_content}'. Using filename-derived SN: '{final_sn}'."
            )

        if not final_sn:  # Check if final_sn ended up empty
            logger_org.warning(
                f"SN resolved to empty for metadata file: {meta_filepath}. Skipping."
            )
            return None

        site = metadata_content.get("final_site", metadata_content.get("site"))
        bldg = metadata_content.get("final_building", metadata_content.get("building"))
        flr = metadata_content.get("final_floor", metadata_content.get("floor"))

        if not all([site, bldg, flr, final_sn]):
            logger_org.warning(
                f"Skipping metadata {meta_filepath}: missing site, building, floor, or resolved SN. "
                f"(Site: {site}, Bldg: {bldg}, Floor: {flr}, SN: {final_sn})"
            )
            return None

        wing_val = metadata_content.get("final_wing", metadata_content.get("wing"))
        area_name_val = metadata_content.get(
            "final_area_name", metadata_content.get("area_name")
        )

        return {
            "site": str(site),
            "building": str(bldg),
            "floor": str(flr),
            "wing": str(wing_val) if wing_val is not None else None,
            "area_name": str(area_name_val) if area_name_val is not None else None,
            "sn": final_sn,
            "original_filepath": meta_filepath,
            "raw_metadata_content": metadata_content,  # Keep original key name for this script
        }
    except json.JSONDecodeError as e:
        logger_org.error(f"Error decoding JSON from {meta_filepath}: {e}")
        return None
    except Exception as e:
        logger_org.warning(f"Could not parse metadata from {meta_filepath}: {e}")
        return None


def get_distinct_locations_from_metadata(metadata_base_dir_path):
    """Recursively searches for metadata files in hierarchical storage."""
    all_locations_data = []
    if not os.path.isdir(metadata_base_dir_path):
        logger_org.error(f"Metadata base dir not found: {metadata_base_dir_path}")
        return all_locations_data

    for root, _, files in os.walk(metadata_base_dir_path):
        for filename in files:
            if filename.lower().endswith("-wave1.meta.json"):
                filepath = os.path.join(root, filename)
                loc_data = parse_metadata_for_location(filepath)
                if loc_data and loc_data.get(
                    "sn"
                ):  # SN is already validated in parse_metadata_for_location
                    all_locations_data.append(loc_data)
    return all_locations_data


def select_from_list(prompt_text, options, allow_all=False):
    if not options:
        print(f"No options available for: {prompt_text}")
        return None
    print(f"\n{prompt_text}:")
    display_options = [
        opt for opt in options if opt is not None and str(opt).strip() != ""
    ]
    # If only Nones/empty strings are options, represent them for selection
    if not display_options and any(o is None or str(o).strip() == "" for o in options):
        display_options = [
            "N/A (None/Empty)"
        ]  # Consolidate all None/empty into one N/A option

    if not display_options and not allow_all:
        print("  (No specific items found)")
        return None
    if not display_options and allow_all:  # Allow "ALL" even if no specific items
        pass
    else:
        for i, option_val in enumerate(display_options):
            print(f"  {i + 1}: {option_val}")

    offset = len(display_options)
    if allow_all:
        print(f"  {offset + 1}: ALL (Process for all under current selection)")
    while True:
        try:
            max_choice = offset + (1 if allow_all else 0)
            if max_choice == 0:  # No options and not allow_all
                return None
            choice_str = input(f"Select number (1-{max_choice}): ").strip()
            if not choice_str:
                continue
            choice = int(choice_str)
            if 1 <= choice <= len(display_options):
                selected_display_option = display_options[choice - 1]
                # If N/A was selected, return None to represent that filter value
                return (
                    None
                    if selected_display_option == "N/A (None/Empty)"
                    else selected_display_option
                )
            elif allow_all and choice == offset + 1:
                return "ALL"
            else:
                print(f"Invalid selection (1-{max_choice}).")
        except ValueError:
            print("Invalid input.")
        except EOFError:
            logger_org.warning("EOF received, exiting selection.")
            return None


def interactive_location_selection(all_metadata_locs):
    if not all_metadata_locs:
        logger_org.warning("No metadata to determine locations.")
        return None
    selected_filters = {}
    sites = sorted(
        list(set(loc["site"] for loc in all_metadata_locs if loc.get("site")))
    )
    if not sites:
        logger_org.error("No sites found in metadata.")
        return None
    selected_site = select_from_list("Select Site", sites, allow_all=True)
    if selected_site is None and "ALL" not in str(
        selected_site
    ):  # Check for explicit None vs "ALL"
        logger_org.info("Site selection aborted or no site chosen.")
        return None
    selected_filters["site"] = selected_site
    if selected_site == "ALL":
        selected_filters.update(
            {"building": "ALL", "floor": "ALL", "wing": "ALL", "area_name": "ALL"}
        )
        return selected_filters

    buildings = sorted(
        list(
            set(
                loc["building"]
                for loc in all_metadata_locs
                if loc.get("site") == selected_site and loc.get("building")
            )
        )
    )
    selected_building = select_from_list(
        f"Select Building for site '{selected_site}'", buildings, allow_all=True
    )
    if selected_building is None and "ALL" not in str(selected_building):
        logger_org.info("Building selection aborted or no building chosen.")
        return None
    selected_filters["building"] = selected_building
    if selected_building == "ALL":
        selected_filters.update({"floor": "ALL", "wing": "ALL", "area_name": "ALL"})
        return selected_filters

    floors = sorted(
        list(
            set(
                loc["floor"]
                for loc in all_metadata_locs
                if loc.get("site") == selected_site
                and loc.get("building") == selected_building
                and loc.get("floor")
            )
        )
    )
    selected_floor = select_from_list(
        f"Select Floor for '{selected_site}/{selected_building}'",
        floors,
        allow_all=True,
    )
    if selected_floor is None and "ALL" not in str(selected_floor):
        logger_org.info("Floor selection aborted or no floor chosen.")
        return None
    selected_filters["floor"] = selected_floor
    if selected_floor == "ALL":
        selected_filters.update({"wing": "ALL", "area_name": "ALL"})
        return selected_filters

    # Wing selection: options can include None from parsed metadata
    wings_from_meta = sorted(
        list(
            set(  # set handles uniqueness, including None
                loc.get("wing")  # loc.get("wing") can be None
                for loc in all_metadata_locs
                if loc.get("site") == selected_site
                and loc.get("building") == selected_building
                and loc.get("floor") == selected_floor
            )
        )
    )
    # select_from_list will handle displaying None as "N/A (None/Empty)"
    # and return None if that's chosen.
    selected_wing = select_from_list(
        f"Select Wing for '{selected_site}/{selected_building}/{selected_floor}'",
        wings_from_meta,  # Pass the list which may contain None
        allow_all=True,
    )
    # selected_wing can be a string, None (for N/A), or "ALL"
    if (
        selected_wing is None and selected_filters.get("floor") != "ALL"
    ):  # Check for explicit abort/no choice vs "ALL" coming from parent
        # If select_from_list returned None because user picked "N/A"
        # it means they want to filter FOR None wing.
        # If select_from_list returned None because no options or EOF, it's an abort.
        # This needs careful handling of select_from_list return. Let's assume select_from_list handles abort by returning something distinct or raising.
        # For now, assume if it's None, it means "filter for entries where wing is None"
        pass  # selected_wing is already None, which is what we want for selected_filters["wing"]

    selected_filters["wing"] = selected_wing  # This will be string, None, or "ALL"

    if selected_filters.get("wing") == "ALL":
        selected_filters["area_name"] = "ALL"
        return selected_filters

    # Area Name selection
    current_filter_wing_val = selected_filters.get("wing")  # This can be None
    area_names_from_meta = sorted(
        list(
            set(
                loc["area_name"]  # loc.get("area_name") can be None
                for loc in all_metadata_locs
                if loc.get("site") == selected_site
                and loc.get("building") == selected_building
                and loc.get("floor") == selected_floor
                and loc.get("wing")
                == current_filter_wing_val  # Handles None == None correctly
                # and loc.get("area_name") is not None # No, we want to list None areas too if they exist
                # and loc.get("area_name").strip() != ""
            )
        )
    )

    wing_display_for_prompt = PATH_PLACEHOLDER_WING_DEFAULT
    if isinstance(current_filter_wing_val, str) and current_filter_wing_val.strip():
        wing_display_for_prompt = current_filter_wing_val
    elif current_filter_wing_val is None:  # User selected "N/A (None/Empty)" for wing
        wing_display_for_prompt = "N/A"

    selected_area_name = select_from_list(
        f"Select Area Name for '{selected_site}/{selected_building}/{selected_floor}/{wing_display_for_prompt}'",
        area_names_from_meta,  # Pass list which may contain None
        allow_all=True,
    )
    selected_filters["area_name"] = selected_area_name  # string, None, or "ALL"

    # Check if the final selection step was aborted (e.g. by EOF)
    if (
        selected_area_name is None and selected_filters.get("wing") != "ALL"
    ):  # Check for explicit abort
        # This condition is tricky because selected_area_name can be None if user chose "N/A"
        # select_from_list needs a clearer way to signal abort vs. "N/A choice"
        # Assuming for now if it gets here and it's None, it's a valid "filter for None" choice.
        # If an actual abort happened in select_from_list, it should have returned a distinct value or raised.
        pass

    return selected_filters


def read_file_content_org(filepath, default_content_if_missing=""):
    if not filepath or not os.path.exists(filepath):
        logger_org.debug(
            f"File not found or path is None: {filepath}. Using default content."
        )
        return default_content_if_missing
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        logger_org.warning(f"UTF-8 decoding failed for {filepath}. Attempting latin-1.")
        try:
            with open(filepath, "r", encoding="latin-1") as f:
                logger_org.info(f"Read {filepath} using latin-1.")
                return f.read()
        except Exception as e_latin1:
            logger_org.warning(
                f"latin-1 failed for {filepath} ({e_latin1}). Trying UTF-8 replace."
            )
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    logger_org.info(f"Read {filepath} with UTF-8 replace.")
                    return f.read()
            except Exception as e_fallback:
                logger_org.error(
                    f"Critical read error {filepath}: {e_fallback}. Using default."
                )
                return default_content_if_missing
    except Exception as e_initial_other:
        logger_org.error(
            f"Unexpected read error {filepath}: {e_initial_other}. Using default."
        )
        return default_content_if_missing


def copy_file_to_dest_dir_org(source_path, dest_dir, dest_filename=None):
    if not source_path or not os.path.exists(source_path):
        logger_org.debug(f"Source file for copy not found: {source_path}")
        return None
    try:
        actual_dest_filename = (
            dest_filename if dest_filename else os.path.basename(source_path)
        )
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, actual_dest_filename)
        shutil.copy2(source_path, dest_path)
        logger_org.debug(f"Copied {source_path} to {dest_path}")
        return dest_path
    except Exception as e:
        logger_org.error(f"Error copying file '{source_path}': {e}")
        return None


def organize_survey_data():
    logger_org.info(
        f"--- Starting Data Organization Script (Output: {OUTPUT_BASE_DIR}) ---"
    )
    logger_org.info(f"Effective METADATA_DIR: {os.path.abspath(METADATA_DIR)}")
    logger_org.info(f"Effective LOGS_BASE_DIR: {os.path.abspath(LOGS_BASE_DIR)}")
    logger_org.info(
        f"Effective SITE_MOONID_DATA_BASE_DIR: {os.path.abspath(SITE_MOONID_DATA_BASE_DIR)}"
    )

    if os.path.exists(OUTPUT_BASE_DIR):
        print("-" * 50)
        logger_org.warning(f"Output directory '{OUTPUT_BASE_DIR}' already exists.")
        print(
            f"WARNING: Existing output directory '{os.path.abspath(OUTPUT_BASE_DIR)}' will be DELETED."
        )
        if input("Are you sure? (yes/no): ").strip().lower() == "yes":
            try:
                shutil.rmtree(OUTPUT_BASE_DIR)
                logger_org.info(f"Deleted: {OUTPUT_BASE_DIR}")
            except OSError as e:
                logger_org.error(
                    f"Error deleting '{OUTPUT_BASE_DIR}': {e}. Manually delete and retry."
                )
                return
        else:
            logger_org.info("User aborted. Exiting.")
            return
    print("-" * 50)

    script_dir_org = os.path.dirname(os.path.abspath(__file__))
    llm_prompt_filepath_org = os.path.join(script_dir_org, LLM_PROMPT_FILENAME_ORG)
    llm_prompt_text_org = read_file_content_org(llm_prompt_filepath_org)
    if not llm_prompt_text_org:
        logger_org.critical(
            f"LLM Prompt file '{llm_prompt_filepath_org}' not found/empty. Exiting."
        )
        return
    logger_org.info(f"Loaded LLM prompt template from: {llm_prompt_filepath_org}")

    if not os.path.isdir(METADATA_DIR):
        logger_org.error(f"Metadata dir not found: {METADATA_DIR}. Exiting.")
        return

    all_metadata_locs = get_distinct_locations_from_metadata(METADATA_DIR)
    if not all_metadata_locs:
        logger_org.warning("No metadata files found/parsed. Exiting.")
        return

    selected_filters = interactive_location_selection(all_metadata_locs)
    if (
        not selected_filters
    ):  # This could happen if user aborts at any stage of selection
        logger_org.info("No location selected or selection aborted. Exiting.")
        return
    logger_org.info(
        f"User selected location filters for organization: {selected_filters}"
    )

    try:
        os.makedirs(OUTPUT_BASE_DIR, exist_ok=True)
    except OSError as e:
        logger_org.error(
            f"Could not create base output {OUTPUT_BASE_DIR}: {e}. Exiting."
        )
        return

    target_metadata_items = []
    for loc_data in all_metadata_locs:
        match = True
        # Site filter
        if selected_filters.get("site") != "ALL" and loc_data.get(
            "site"
        ) != selected_filters.get("site"):
            match = False
        # Building filter
        if (
            match
            and selected_filters.get("building") != "ALL"
            and loc_data.get("building") != selected_filters.get("building")
        ):
            match = False
        # Floor filter
        if (
            match
            and selected_filters.get("floor") != "ALL"
            and loc_data.get("floor") != selected_filters.get("floor")
        ):
            match = False

        # Wing filter (loc_data.get("wing") can be None, selected_filters.get("wing") can be None)
        if match and selected_filters.get("wing") != "ALL":
            if loc_data.get("wing") != selected_filters.get("wing"):
                match = False

        # Area Name filter (loc_data.get("area_name") can be None, selected_filters.get("area_name") can be None)
        if match and selected_filters.get("area_name") != "ALL":
            if loc_data.get("area_name") != selected_filters.get("area_name"):
                match = False

        if match:
            target_metadata_items.append(loc_data)

    if not target_metadata_items:
        logger_org.warning(
            f"No metadata files match filters: {selected_filters}. Nothing to process."
        )
        return
    logger_org.info(
        f"Found {len(target_metadata_items)} metadata files matching filters."
    )

    organized_switches_count = 0
    package_creation_errors = 0
    for meta_item in target_metadata_items:
        sn = meta_item.get("sn")
        meta_filepath_original = meta_item.get("original_filepath")
        actual_site = meta_item.get("site")
        actual_building = meta_item.get("building")
        actual_floor = meta_item.get("floor")
        actual_wing_metadata_val = meta_item.get("wing")  # This can be None
        actual_area_name = meta_item.get("area_name")  # This can be None

        # SN, site, building, floor already validated by parse_metadata_for_location
        # meta_filepath_original is also guaranteed if parse_metadata_for_location succeeded

        logger_org.info(
            f"--- Processing SN: {sn} (Loc: {actual_site}/{actual_building}/{actual_floor}/{actual_wing_metadata_val or '-'}/{actual_area_name or '-'}) ---"
        )

        path_site_org_output = sanitize_foldername_part(actual_site, "NoSite_Fallback")
        loc_folder_seg_org_output = format_location_log_folder_segment(
            actual_building,
            actual_floor,
            actual_wing_metadata_val,  # Pass None if it is None
            actual_area_name,  # Pass None if it is None
            PATH_PLACEHOLDER_WING_DEFAULT,
            PATH_PLACEHOLDER_AREA_DEFAULT,
        )
        location_level_output_path = os.path.join(
            OUTPUT_BASE_DIR, path_site_org_output, loc_folder_seg_org_output
        )
        archive_dir_for_package_components = os.path.join(
            location_level_output_path, "Archive_PackageComponents"
        )
        llm_packages_dir_for_output = os.path.join(
            location_level_output_path, "LLM_Input_Packages"
        )
        archive_sn_specific_dir_org = os.path.join(
            archive_dir_for_package_components,
            sanitize_foldername_part(sn, "NoSN_Fallback"),
        )

        try:
            os.makedirs(archive_sn_specific_dir_org, exist_ok=True)
            os.makedirs(llm_packages_dir_for_output, exist_ok=True)
        except OSError as e:
            logger_org.error(
                f"Could not create output subdirs for SN {sn}: {e}. Skipping."
            )
            package_creation_errors += 1
            continue

        log_source_site_sanitized = sanitize_foldername_part(
            actual_site, "NoSite_Fallback"
        )
        log_source_loc_folder_segment = format_location_log_folder_segment(
            actual_building,
            actual_floor,
            actual_wing_metadata_val,  # Pass None if it is None
            actual_area_name,  # Pass None if it is None
            PATH_PLACEHOLDER_WING_DEFAULT,
            PATH_PLACEHOLDER_AREA_DEFAULT,
        )
        specific_log_source_dir = os.path.join(
            LOGS_BASE_DIR, log_source_site_sanitized, log_source_loc_folder_segment
        )

        wave1_log_filename_src = f"{sn}-WAVE1.txt"
        wave1_log_path_at_source = os.path.join(
            specific_log_source_dir, wave1_log_filename_src
        )
        wave2_log_filename_src = f"{sn}-WAVE2.txt"
        wave2_log_path_at_source = os.path.join(
            specific_log_source_dir, wave2_log_filename_src
        )

        site_moonid_filepath_original = None
        if actual_site and os.path.isdir(SITE_MOONID_DATA_BASE_DIR):
            expected_moonid_filename = f"{actual_site.upper()}_moonids.json"
            site_moonid_filepath_original = os.path.join(
                SITE_MOONID_DATA_BASE_DIR, expected_moonid_filename
            )
            if not os.path.exists(site_moonid_filepath_original):
                logger_org.warning(
                    f"Site MOONID file not found for SN {sn} at {site_moonid_filepath_original}. Placeholder used."
                )
                site_moonid_filepath_original = None
        elif not actual_site:  # Should not happen due to earlier checks, but defensive
            logger_org.warning(
                f"Site missing for SN {sn}. MOONID data uses placeholder."
            )
        elif not os.path.isdir(SITE_MOONID_DATA_BASE_DIR):
            logger_org.error(
                f"Site MOONID base dir not found: {SITE_MOONID_DATA_BASE_DIR}"
            )

        copied_meta_path = copy_file_to_dest_dir_org(
            meta_filepath_original, archive_sn_specific_dir_org
        )
        if not copied_meta_path:
            logger_org.error(f"Failed to copy metadata for SN {sn}. Skipping package.")
            package_creation_errors += 1
            continue

        copied_w1_log_path = None
        if os.path.exists(wave1_log_path_at_source):
            copied_w1_log_path = copy_file_to_dest_dir_org(
                wave1_log_path_at_source,
                archive_sn_specific_dir_org,
                wave1_log_filename_src,
            )
        else:
            logger_org.warning(
                f"Wave 1 log not found for SN {sn} at {wave1_log_path_at_source}. Placeholder used."
            )

        copied_w2_log_path = None
        if os.path.exists(wave2_log_path_at_source):
            copied_w2_log_path = copy_file_to_dest_dir_org(
                wave2_log_path_at_source,
                archive_sn_specific_dir_org,
                wave2_log_filename_src,
            )
        else:
            logger_org.debug(f"Wave 2 log not found for SN {sn} (optional).")

        copied_site_moonid_path = None
        if site_moonid_filepath_original and os.path.exists(
            site_moonid_filepath_original
        ):
            copied_site_moonid_path = copy_file_to_dest_dir_org(
                site_moonid_filepath_original, archive_sn_specific_dir_org
            )

        # Use utils.generate_safe_filename if available, else basic SN.
        if UTILS_IMPORTED_SUCCESSFULLY:
            from utils import (
                generate_safe_filename as utils_gsfn,  # Import locally to ensure it's from the successfully imported utils
            )

            package_filename_base = utils_gsfn(sn)
        else:
            package_filename_base = sanitize_foldername_part(
                sn, "UnknownSN"
            )  # Use own sanitize for fallback

        package_filename = f"{package_filename_base}_llm_input_package.txt"
        package_filepath = os.path.join(llm_packages_dir_for_output, package_filename)

        try:
            with open(package_filepath, "w", encoding="utf-8") as f_out:
                f_out.write(
                    f"{DELIMITERS_ORG['prompt_start']}\n{llm_prompt_text_org.strip()}\n{DELIMITERS_ORG['prompt_end']}\n\n"
                )
                meta_content_for_pkg = json.dumps(
                    meta_item.get("raw_metadata_content", {}), indent=4
                )
                f_out.write(
                    f"{DELIMITERS_ORG['meta_start']}\n{meta_content_for_pkg.strip()}\n{DELIMITERS_ORG['meta_end']}\n\n"
                )

                w1_log_content_raw = read_file_content_org(
                    copied_w1_log_path, MISSING_WAVE1_LOG_PLACEHOLDER_ORG
                )
                w1_log_content_for_pack = sanitize_log_content_for_llm(
                    w1_log_content_raw
                )
                f_out.write(
                    f"{DELIMITERS_ORG['log1_start']}\n{w1_log_content_for_pack.strip()}\n{DELIMITERS_ORG['log1_end']}\n\n"
                )

                if copied_w2_log_path:
                    w2_log_content_raw = read_file_content_org(copied_w2_log_path, "")
                    if w2_log_content_raw.strip():
                        w2_log_content_for_pack = sanitize_log_content_for_llm(
                            w2_log_content_raw
                        )
                        f_out.write(
                            f"{DELIMITERS_ORG['log2_start']}\n{w2_log_content_for_pack.strip()}\n{DELIMITERS_ORG['log2_end']}\n\n"
                        )

                site_moonid_raw_content = read_file_content_org(
                    copied_site_moonid_path, MISSING_SITE_MOONID_PLACEHOLDER_ORG
                )
                site_moonid_content_for_pack = site_moonid_raw_content
                if site_moonid_raw_content == MISSING_SITE_MOONID_PLACEHOLDER_ORG:
                    site_moonid_content_for_pack = sanitize_log_content_for_llm(
                        site_moonid_raw_content
                    )

                f_out.write(
                    f"{DELIMITERS_ORG['moonid_start']}\n{site_moonid_content_for_pack.strip()}\n{DELIMITERS_ORG['moonid_end']}\n"
                )
            logger_org.info(
                f"Successfully created LLM input package: {package_filepath}"
            )
            organized_switches_count += 1
        except Exception as e:
            logger_org.error(
                f"Unexpected error creating package {package_filepath} for SN {sn}: {e}",
                exc_info=True,
            )
            package_creation_errors += 1
        logger_org.info(f"--- Finished Processing SN: {sn} ---")

    logger_org.info("--- Data Organization Script Finished ---")
    logger_org.info(f"Total switches organized: {organized_switches_count}")
    if package_creation_errors > 0:
        logger_org.warning(f"Package creation errors: {package_creation_errors}")
    logger_org.info(f"Output data under: {os.path.abspath(OUTPUT_BASE_DIR)}")


if __name__ == "__main__":
    organize_survey_data()
