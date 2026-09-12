# create_log_folders.py
import json
import logging
import os
import re
import sys

# --- Attempt to configure paths by importing config.py and utils.py ---
CONFIG_MODULE_FOUND = False
UTILS_MODULE_FOUND = False

try:
    CURRENT_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT_FOR_IMPORTS = CURRENT_SCRIPT_DIR

    PARENT_OF_SCRIPT_DIR = os.path.dirname(CURRENT_SCRIPT_DIR)
    if os.path.exists(os.path.join(PARENT_OF_SCRIPT_DIR, "config.py")):
        if PARENT_OF_SCRIPT_DIR not in sys.path:
            sys.path.insert(0, PARENT_OF_SCRIPT_DIR)
        PROJECT_ROOT_FOR_IMPORTS = PARENT_OF_SCRIPT_DIR
    elif CURRENT_SCRIPT_DIR not in sys.path:  # If not in parent, try current script dir
        sys.path.insert(0, CURRENT_SCRIPT_DIR)

    from netsurvey import config as app_config

    CONFIG_MODULE_FOUND = True

    from netsurvey.utils import (
        PATH_PLACEHOLDER_AREA_DEFAULT,
        PATH_PLACEHOLDER_WING_DEFAULT,
        format_location_log_folder_segment,
        sanitize_foldername_part,
    )

    UTILS_MODULE_FOUND = True

    LOGS_BASE_DIR = app_config.LOGS_DIR
    LAB_AREAS_JSON_PATH = os.path.join(
        app_config.DATA_DIR, app_config.LAB_AREAS_FILENAME
    )

    print("Successfully imported 'config.py' and 'utils.py'. Using configured paths.")
    print(f"  LOGS_BASE_DIR set to: {os.path.abspath(LOGS_BASE_DIR)}")
    print(f"  LAB_AREAS_JSON_PATH set to: {os.path.abspath(LAB_AREAS_JSON_PATH)}")

except ImportError as e:
    print(f"WARNING: Could not import 'config.py' or 'utils.py' (Error: {e}).")
    if not CONFIG_MODULE_FOUND:
        print("  'config.py' not found or caused an import error.")
    if not UTILS_MODULE_FOUND:
        print("  'utils.py' not found or caused an import error.")

    print(
        "Falling back to default relative paths, assuming this script is run from the project root."
    )
    PROJECT_ROOT_FALLBACK = os.path.dirname(
        os.path.abspath(__file__)
    )  # Script's own dir as root
    # Fallback paths (no "dist/" prefix, direct subfolders of project root)
    LOGS_BASE_DIR = os.path.join(PROJECT_ROOT_FALLBACK, "survey_outputs", "logs")
    LAB_AREAS_JSON_PATH = os.path.join(
        PROJECT_ROOT_FALLBACK, "data", "lab_areas_data.json"
    )
    print(f"  Fallback LOGS_BASE_DIR: {os.path.abspath(LOGS_BASE_DIR)}")
    print(f"  Fallback LAB_AREAS_JSON_PATH: {os.path.abspath(LAB_AREAS_JSON_PATH)}")

    if not UTILS_MODULE_FOUND:
        print("Defining basic fallback utility functions for 'create_log_folders.py'.")
        PATH_PLACEHOLDER_WING_DEFAULT = "__NoWing__"
        PATH_PLACEHOLDER_AREA_DEFAULT = "__NoArea__"

        def sanitize_foldername_part(
            name_part: str, placeholder: str = "Unknown"
        ) -> str:
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


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def create_folders():
    logger.info("Starting log folder creation process.")
    if not CONFIG_MODULE_FOUND:
        logger.warning("Running with fallback paths for config.")
    if not UTILS_MODULE_FOUND:
        logger.warning("Running with fallback utility functions for utils.")

    logger.info(
        f"Effective LAB_AREAS_JSON_PATH: {os.path.abspath(LAB_AREAS_JSON_PATH)}"
    )
    logger.info(f"Effective LOGS_BASE_DIR for output: {os.path.abspath(LOGS_BASE_DIR)}")

    if not os.path.exists(LAB_AREAS_JSON_PATH):
        logger.error(f"CRITICAL: Lab areas data file not found: {LAB_AREAS_JSON_PATH}")
        return

    try:
        with open(LAB_AREAS_JSON_PATH, "r", encoding="utf-8") as f:
            lab_areas_data = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"CRITICAL: Could not parse JSON from {LAB_AREAS_JSON_PATH}: {e}")
        return
    except Exception as e:
        logger.error(
            f"CRITICAL: An unexpected error occurred loading {LAB_AREAS_JSON_PATH}: {e}"
        )
        return

    if not isinstance(lab_areas_data, list):
        logger.error(
            f"CRITICAL: Data in {LAB_AREAS_JSON_PATH} is not a valid JSON list."
        )
        return

    created_count = 0
    skipped_due_to_missing_data = 0
    unique_paths_to_create = set()

    for area_info in lab_areas_data:
        if not isinstance(area_info, dict):
            logger.warning(
                f"Skipping invalid non-dict entry in lab_areas_data: {area_info}"
            )
            continue

        site = area_info.get("site")
        building = area_info.get("building")
        floor = area_info.get("floor")
        wing = area_info.get("wing")
        lab_area_name = area_info.get("lab_area_name")

        if not site or not building or not floor:
            logger.warning(
                f"Skipping area due to missing 'site', 'building', or 'floor': {area_info}"
            )
            skipped_due_to_missing_data += 1
            continue

        sanitized_site_foldername = sanitize_foldername_part(site, "NoSite_Fallback")
        location_specific_foldername = format_location_log_folder_segment(
            building,
            floor,
            wing,
            lab_area_name,
            PATH_PLACEHOLDER_WING_DEFAULT,
            PATH_PLACEHOLDER_AREA_DEFAULT,
        )
        target_log_folder_path = os.path.join(
            LOGS_BASE_DIR, sanitized_site_foldername, location_specific_foldername
        )
        unique_paths_to_create.add(os.path.normpath(target_log_folder_path))

    if not unique_paths_to_create:
        logger.info("No valid lab area paths derived. No folders to create.")
        return

    logger.info(
        f"\nFound {len(unique_paths_to_create)} unique directory paths to create/ensure under '{os.path.abspath(LOGS_BASE_DIR)}':"
    )
    successful_creations = 0
    failed_creations = 0

    for path_to_create in sorted(list(unique_paths_to_create)):
        try:
            os.makedirs(path_to_create, exist_ok=True)
            logger.info(f"  Ensured directory exists: {path_to_create}")
            successful_creations += 1
        except OSError as e:
            logger.error(
                f"  Could not create or access directory {path_to_create}: {e}"
            )
            failed_creations += 1
        except Exception as e_general:
            logger.error(
                f"  An unexpected error occurred creating {path_to_create}: {e_general}"
            )
            failed_creations += 1

    logger.info("\nLog folder creation process finished.")
    logger.info(
        f"Total unique lab area paths identified: {len(unique_paths_to_create)}"
    )
    logger.info(f"Directories successfully ensured/created: {successful_creations}")
    if failed_creations > 0:
        logger.warning(f"Failed to create/access {failed_creations} directories.")
    if skipped_due_to_missing_data > 0:
        logger.warning(
            f"Skipped {skipped_due_to_missing_data} entries from '{LAB_AREAS_JSON_PATH}' due to missing critical fields."
        )


if __name__ == "__main__":
    print("--- Running Log Folder Creation Utility ---")
    create_folders()
    print("--- Log Folder Creation Utility Finished ---")
