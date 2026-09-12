# phase3_review_tool_auto_batch.py
import json
import logging
import os
import platform
import shutil
import signal
import subprocess
import sys
from typing import Any, Dict, List, Literal, Optional, Set

# --- Pydantic Models (Import from gemini.py) ---
try:
    from netsurvey.llm.gemini import (
        ArpEntry,
        DiscoveredUnassignedNetwork,
        Interface,
        IpInterface,
        ItemForReview,
        MacEntry,
        MacEntryList,
        Neighbor,
        NetworkDeviceData,
        Route,
        MoonidAssociation,
        SwitchDetails,
        ValidationError,
        Vlan,
    )

    PYDANTIC_MODELS_IMPORTED = True
except ImportError as e_pydantic_import:
    logging.critical(
        f"CRITICAL ERROR: Could not import Pydantic models from gemini.py: {e_pydantic_import}"
    )
    logging.critical(
        "Ensure gemini.py is in the Python path and contains the necessary Pydantic model definitions."
    )
    PYDANTIC_MODELS_IMPORTED = False

    # Define dummy classes if import fails, so script can load but validation will be crippled
    class BaseModel:
        pass  # Minimal Pydantic-like base

    class NetworkDeviceData(BaseModel):
        pass

    class ItemForReview(BaseModel):
        pass

    class ValidationError(Exception):
        pass


# --- Configuration ---
BASE_API_OUTPUT_DIR = "validated_jsons_api_structured_MAC_CHUNKED_MP"
BASE_ARCHIVE_DIR_SOURCES = os.path.join(BASE_API_OUTPUT_DIR, "_archive_source_files")
REVIEWED_JSON_DIR = "validated_jsons_api_reviewed"
PROCESSED_ORIGINALS_SUBDIR_NAME = "_originals_moved_after_review"
REVIEWED_FILE_SUFFIX = "_reviewed.json"
VALIDATED_FILE_SUFFIX = "_validated.json"

# --- Logging Setup ---
log_format = "%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
logging.basicConfig(level=logging.INFO, format=log_format)
logger = logging.getLogger(__name__)

_shutdown_requested = False


def signal_handler_fn(sig, frame):
    global _shutdown_requested
    logger.warning(
        "Shutdown requested. Will attempt to stop after current operation or next prompt."
    )
    _shutdown_requested = True


# --- Helper Functions ---
def get_corresponding_archive_files(
    validated_json_filepath: str, api_output_dir_base: str, archive_files_base_dir: str
) -> Dict[str, Optional[str]]:
    archive_payload = {
        "metadata": None,
        "log_wave1": None,
        "log_wave2": None,
        "site_moonid": None,
        "llm_input_package": None,
    }
    sn_from_filename = os.path.basename(validated_json_filepath).replace(
        VALIDATED_FILE_SUFFIX, ""
    )
    if not sn_from_filename:
        logger.warning(f"Could not extract SN from {validated_json_filepath}")
        return archive_payload
    try:
        abs_validated_json_filepath = os.path.abspath(validated_json_filepath)
        abs_api_output_dir_base = os.path.abspath(api_output_dir_base)
        if not abs_validated_json_filepath.startswith(abs_api_output_dir_base):
            logger.warning(
                f"Validated JSON path '{abs_validated_json_filepath}' not under base '{abs_api_output_dir_base}'. Cannot find archives."
            )
            return archive_payload
        relative_dir_path = os.path.dirname(
            os.path.relpath(abs_validated_json_filepath, abs_api_output_dir_base)
        )
        sn_specific_archive_path = os.path.join(
            archive_files_base_dir, relative_dir_path, sn_from_filename
        )

        if not os.path.isdir(sn_specific_archive_path):
            logger.debug(
                f"Archive directory not found: {sn_specific_archive_path} for SN {sn_from_filename}"
            )
            return archive_payload

        potential_files = {
            "metadata": f"{sn_from_filename}-WAVE1.meta.json",
            "log_wave1": f"{sn_from_filename}-WAVE1.txt",
            "log_wave2": f"{sn_from_filename}-WAVE2.txt",
            "llm_input_package": f"{sn_from_filename}_llm_input_package.txt",
        }
        for key, filename in potential_files.items():
            path = os.path.join(sn_specific_archive_path, filename)
            if os.path.exists(path):
                archive_payload[key] = path
        for item in os.listdir(sn_specific_archive_path):
            if item.upper().endswith("_MOONIDS.JSON"):
                archive_payload["site_moonid"] = os.path.join(
                    sn_specific_archive_path, item
                )
                break
    except Exception as e:
        logger.error(f"Error finding archive files for {validated_json_filepath}: {e}")
    return archive_payload


def open_file_with_default_app(filepath: str):
    if not os.path.exists(filepath):
        logger.warning(f"Cannot open file: Path does not exist - {filepath}")
        return
    try:
        abs_filepath = os.path.abspath(filepath)
        logger.info(f"Attempting to open: {abs_filepath}")
        if platform.system() == "Darwin":
            subprocess.run(["open", abs_filepath], check=False)
        elif platform.system() == "Windows":
            os.startfile(abs_filepath)
        else:
            subprocess.run(["xdg-open", abs_filepath], check=False)
    except Exception as e:
        logger.error(f"Could not open file {filepath} automatically: {e}")
        print(f"-> Please open manually: {os.path.abspath(filepath)}")


def display_items_for_review(json_data: Dict[str, Any]):
    items = json_data.get("items_for_review", [])
    if not items:
        print("\nINFO: No 'items_for_review' section found or it is empty.")
        return
    print("\n--- Items for Review (from LLM) ---")
    for i, item_dict in enumerate(items):
        if not isinstance(item_dict, dict):
            print(
                f"  WARNING: Item {i + 1} in 'items_for_review' not a dict: {item_dict}"
            )
            continue
        severity = item_dict.get("severity", "N/A")
        item_path = item_dict.get("item_path", "N/A")
        reason = item_dict.get("reason", "N/A")
        details = item_dict.get("details", "N/A")
        print(
            f"\n  {i + 1}. Severity: {severity}\n     Path:     {item_path}\n     Reason:   {reason}\n     Details:  {details}"
        )
    print("-----------------------------------")


def validate_json_with_pydantic(
    filepath_for_log: str, data_to_validate: Optional[Dict[str, Any]] = None
) -> bool:
    if not PYDANTIC_MODELS_IMPORTED:
        logger.error("Pydantic models not imported. Cannot perform validation.")
        return False  # Or True if we want to allow proceeding without validation in this case
    try:
        current_data = data_to_validate
        if current_data is None:
            if not filepath_for_log or not os.path.exists(filepath_for_log):
                logger.error(
                    f"Pydantic Validation: Filepath '{filepath_for_log}' not provided/exists."
                )
                return False
            with open(filepath_for_log, "r", encoding="utf-8") as f:
                current_data = json.load(f)

        if not isinstance(
            current_data, dict
        ):  # Ensure current_data is a dict before proceeding
            logger.error(
                f"Pydantic Validation: Data from '{filepath_for_log if filepath_for_log else 'memory'}' is not a dictionary."
            )
            return False

        temp_items_for_review = current_data.pop("items_for_review", None)

        # Use the imported NetworkDeviceData model
        NetworkDeviceData(**current_data)  # Validate against the main structure

        if (
            temp_items_for_review is not None
        ):  # Restore for data integrity if needed later
            current_data["items_for_review"] = temp_items_for_review

        logger.debug(
            f"Pydantic validation successful for: {filepath_for_log if filepath_for_log else 'memory'}"
        )
        return True
    except json.JSONDecodeError as jde:
        logger.error(
            f"Pydantic Validation: Content from '{filepath_for_log if filepath_for_log else 'memory'}' not valid JSON. {jde}"
        )
        return False
    except ValidationError as ve:  # Imported from gemini or defined as dummy
        logger.error(
            f"Pydantic Validation Error for '{filepath_for_log if filepath_for_log else 'data in memory'}':\n{ve}"
        )
        return False
    except Exception as e:
        logger.error(
            f"Error during Pydantic validation for '{filepath_for_log if filepath_for_log else 'data in memory'}': {type(e).__name__} - {e}"
        )
        return False


def find_all_validated_json_files(base_dir: str) -> List[str]:
    global _shutdown_requested
    validated_files = []
    abs_base_dir = os.path.abspath(base_dir)
    abs_archive_sources_dir = os.path.abspath(BASE_ARCHIVE_DIR_SOURCES)
    # Construct path to _originals_moved_after_review within the base_dir being scanned
    abs_processed_originals_dir = os.path.join(
        abs_base_dir, PROCESSED_ORIGINALS_SUBDIR_NAME
    )

    for root, _, files in os.walk(abs_base_dir):
        if _shutdown_requested:
            break
        abs_root = os.path.abspath(root)
        if (
            abs_root.startswith(abs_archive_sources_dir)
            or abs_root.startswith(abs_processed_originals_dir)
            or os.path.basename(abs_root) == "_batch_script_error_logs"
            or os.path.basename(abs_root) == "_api_error_logs"
            or os.path.basename(abs_root) == "_unified_script_error_logs"
        ):  # Added for unified_processor logs
            continue
        for file in files:
            if _shutdown_requested:
                break
            if file.endswith(VALIDATED_FILE_SUFFIX):
                validated_files.append(os.path.join(root, file))
    if _shutdown_requested:
        logger.info("File discovery interrupted.")
    else:
        logger.info(
            f"Found {len(validated_files)} '{VALIDATED_FILE_SUFFIX}' files in '{base_dir}'."
        )
    return sorted(validated_files)


def process_single_file_for_review_auto_batch(
    json_filepath: str,
    base_api_output_dir: str,
    archive_base_dir_for_sources: str,
    reviewed_json_base_dir: str,
    reviewed_file_suffix: str,
    processed_originals_archive_name: str,
) -> Literal["reviewed", "skipped", "quit_all", "error"]:
    global _shutdown_requested
    if _shutdown_requested:
        return "quit_all"

    sn_display = os.path.basename(json_filepath).replace(VALIDATED_FILE_SUFFIX, "")
    print(
        "\n=============================================================================="
    )
    logger.info(f"Reviewing File for SN: {sn_display} | Path: {json_filepath}")
    print(
        "=============================================================================="
    )

    if not os.path.exists(json_filepath):
        logger.error(f"ERROR: JSON file not found: {json_filepath}")
        return "error"
    try:
        with open(json_filepath, "r", encoding="utf-8") as f:
            device_data = json.load(f)
    except Exception as e:
        logger.error(f"CRITICAL: Could not read/parse JSON file {json_filepath}: {e}")
        return "error"

    display_items_for_review(device_data)
    archive_files = get_corresponding_archive_files(
        json_filepath, base_api_output_dir, archive_base_dir_for_sources
    )

    logger.info("Opening files for review (JSON and relevant archives)...")
    open_file_with_default_app(json_filepath)
    if archive_files.get("metadata"):
        open_file_with_default_app(archive_files["metadata"])
    if archive_files.get("log_wave1"):
        open_file_with_default_app(archive_files["log_wave1"])
    if archive_files.get("log_wave2"):
        open_file_with_default_app(archive_files["log_wave2"])
    if archive_files.get("site_moonid"):
        open_file_with_default_app(archive_files["site_moonid"])

    print(
        "\nINSTRUCTIONS:\n1. JSON and source files (if found) opened.\n2. **Review and EDIT the JSON ('_validated.json'). SAVE changes.**\n3. Return here for next action."
    )

    while not _shutdown_requested:
        action = (
            input(
                f"\nAction for {sn_display}: [R]eviewed & Save, [O]pen again, [S]kip, [Q]uit ALL: "
            )
            .strip()
            .lower()
        )
        if action == "r":
            logger.info(
                f"User marked {sn_display} as reviewed. Validating and processing..."
            )
            try:
                with open(json_filepath, "r", encoding="utf-8") as f_edited:
                    edited_data = json.load(f_edited)
            except Exception as e_load:
                logger.error(f"Failed to re-load edited JSON {json_filepath}: {e_load}")
                print("   Could not load saved changes. Valid JSON?")
                continue

            if not validate_json_with_pydantic(
                json_filepath, edited_data
            ):  # Validate before removing items
                print(
                    f"   ERROR: Edited JSON '{json_filepath}' FAILED Pydantic validation. 'items_for_review' NOT removed."
                )
                if input("   Re-open JSON for correction? (y/n): ").lower() == "y":
                    open_file_with_default_app(json_filepath)
                continue

            if "items_for_review" in edited_data:
                del edited_data["items_for_review"]
                logger.info(f"Removed 'items_for_review' for SN {sn_display}.")
            try:
                abs_json_filepath = os.path.abspath(json_filepath)
                abs_base_api_output_dir = os.path.abspath(base_api_output_dir)
                relative_json_path_dir = os.path.dirname(
                    os.path.relpath(abs_json_filepath, abs_base_api_output_dir)
                )
                reviewed_dest_dir = os.path.join(
                    reviewed_json_base_dir, relative_json_path_dir
                )
                os.makedirs(reviewed_dest_dir, exist_ok=True)
                reviewed_dest_filepath = os.path.join(
                    reviewed_dest_dir, f"{sn_display}{reviewed_file_suffix}"
                )
                with open(reviewed_dest_filepath, "w", encoding="utf-8") as f_reviewed:
                    json.dump(edited_data, f_reviewed, indent=4)
                logger.info(
                    f"Saved reviewed file for SN {sn_display} to: {reviewed_dest_filepath}"
                )

                original_moved_dir = os.path.join(
                    base_api_output_dir,
                    processed_originals_archive_name,
                    relative_json_path_dir,
                )
                os.makedirs(original_moved_dir, exist_ok=True)
                original_moved_filepath = os.path.join(
                    original_moved_dir, os.path.basename(json_filepath)
                )
                shutil.move(json_filepath, original_moved_filepath)
                logger.info(
                    f"Moved original {json_filepath} to {original_moved_filepath}"
                )
                return "reviewed"
            except Exception as e_save_move:
                logger.error(f"Error saving/moving for SN {sn_display}: {e_save_move}")
                return "error"
        elif action == "o":
            logger.info(f"Re-opening files for SN {sn_display}...")
            open_file_with_default_app(json_filepath)  # Re-open potentially edited one
            if archive_files.get("metadata"):
                open_file_with_default_app(archive_files["metadata"])
            if archive_files.get("log_wave1"):
                open_file_with_default_app(archive_files["log_wave1"])
            if archive_files.get("log_wave2"):
                open_file_with_default_app(archive_files["log_wave2"])
            if archive_files.get("site_moonid"):
                open_file_with_default_app(archive_files["site_moonid"])
        elif action == "s":
            logger.info(f"User skipped review for SN {sn_display}.")
            return "skipped"
        elif action == "q":
            logger.info("User requested to quit all processing.")
            _shutdown_requested = True
            return "quit_all"
        else:
            print("Invalid input. Use 'r', 'o', 's', or 'q'.")
    if _shutdown_requested:
        return "quit_all"
    return "error"


def main():
    global _shutdown_requested
    if not PYDANTIC_MODELS_IMPORTED:
        logger.critical(
            "Pydantic models could not be imported from gemini.py. Review tool cannot function correctly. Exiting."
        )
        sys.exit(1)

    original_sigint_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal_handler_fn)
    logger.info("--- Phase 3: Auto-Batch Manual Review and Correction Script ---")

    if not os.path.isdir(BASE_API_OUTPUT_DIR):
        logger.error(
            f"Source API output directory '{BASE_API_OUTPUT_DIR}' not found. Exiting."
        )
        sys.exit(1)
    os.makedirs(REVIEWED_JSON_DIR, exist_ok=True)

    all_potential_validated_files = find_all_validated_json_files(BASE_API_OUTPUT_DIR)
    if _shutdown_requested:
        sys.exit("Shutdown during initial file scan.")
    if not all_potential_validated_files:
        logger.info(
            f"No '{VALIDATED_FILE_SUFFIX}' files found in '{BASE_API_OUTPUT_DIR}'. Nothing to review."
        )
        sys.exit(0)

    files_to_process_this_run: List[str] = []
    sns_with_existing_reviewed_files: Set[str] = set()
    for validated_file_path in all_potential_validated_files:
        if _shutdown_requested:
            break
        sn = os.path.basename(validated_file_path).replace(VALIDATED_FILE_SUFFIX, "")
        abs_validated_file_path = os.path.abspath(validated_file_path)
        abs_base_api_output_dir = os.path.abspath(BASE_API_OUTPUT_DIR)
        if not abs_validated_file_path.startswith(abs_base_api_output_dir):
            continue  # Should not happen with find_all
        relative_dir = os.path.dirname(
            os.path.relpath(abs_validated_file_path, abs_base_api_output_dir)
        )
        expected_reviewed_file_path = os.path.join(
            REVIEWED_JSON_DIR, relative_dir, f"{sn}{REVIEWED_FILE_SUFFIX}"
        )
        if os.path.exists(expected_reviewed_file_path):
            sns_with_existing_reviewed_files.add(sn)
    if _shutdown_requested:
        sys.exit("Shutdown during existing reviewed file check.")

    action_for_existing_reviewed = "process"
    if sns_with_existing_reviewed_files:
        logger.warning(
            f"{len(sns_with_existing_reviewed_files)} SN(s) have existing '{REVIEWED_FILE_SUFFIX}' files."
        )
        user_choice_existing = (
            input(
                "Options: [S]kip all, [D]elete reviewed & re-review originals, [A]bort: "
            )
            .strip()
            .lower()
        )
        if user_choice_existing == "d":
            if (
                input(
                    f"CONFIRM: Delete {len(sns_with_existing_reviewed_files)} files from '{REVIEWED_JSON_DIR}' AND restore originals from '{PROCESSED_ORIGINALS_SUBDIR_NAME}'? (yes/no): "
                ).lower()
                == "yes"
            ):
                logger.info("Deleting reviewed files and restoring originals...")
                for sn_to_clear in sns_with_existing_reviewed_files:
                    if _shutdown_requested:
                        break
                    # Determine original relative path
                    original_validated_path_for_sn = next(
                        (
                            p
                            for p in all_potential_validated_files
                            if os.path.basename(p).startswith(sn_to_clear)
                        ),
                        None,
                    )
                    if not original_validated_path_for_sn:
                        continue
                    abs_orig_validated_path = os.path.abspath(
                        original_validated_path_for_sn
                    )
                    abs_base_api_dir = os.path.abspath(BASE_API_OUTPUT_DIR)
                    relative_dir_for_sn = os.path.dirname(
                        os.path.relpath(abs_orig_validated_path, abs_base_api_dir)
                    )

                    reviewed_file_to_delete = os.path.join(
                        REVIEWED_JSON_DIR,
                        relative_dir_for_sn,
                        f"{sn_to_clear}{REVIEWED_FILE_SUFFIX}",
                    )
                    try:
                        if os.path.exists(reviewed_file_to_delete):
                            os.remove(reviewed_file_to_delete)
                            logger.info(f"Deleted: {reviewed_file_to_delete}")
                    except OSError as e:
                        logger.error(f"Failed to delete {reviewed_file_to_delete}: {e}")

                    moved_original_path = os.path.join(
                        BASE_API_OUTPUT_DIR,
                        PROCESSED_ORIGINALS_SUBDIR_NAME,
                        relative_dir_for_sn,
                        f"{sn_to_clear}{VALIDATED_FILE_SUFFIX}",
                    )
                    destination_for_restore_path = os.path.join(
                        BASE_API_OUTPUT_DIR,
                        relative_dir_for_sn,
                        f"{sn_to_clear}{VALIDATED_FILE_SUFFIX}",
                    )
                    if os.path.exists(moved_original_path):
                        try:
                            os.makedirs(
                                os.path.dirname(destination_for_restore_path),
                                exist_ok=True,
                            )
                            shutil.move(
                                moved_original_path, destination_for_restore_path
                            )
                            logger.info(
                                f"Restored: {moved_original_path} to {destination_for_restore_path}"
                            )
                        except Exception as e_restore:
                            logger.error(
                                f"Failed to restore {moved_original_path}: {e_restore}"
                            )
                    else:  # If not in processed_originals, it should still be in main dir (e.g. if D was run before R)
                        if not os.path.exists(
                            destination_for_restore_path
                        ):  # only log if not already in place
                            logger.debug(
                                f"Original for {sn_to_clear} not found in '{PROCESSED_ORIGINALS_SUBDIR_NAME}' and not at primary. It might have been skipped or errored previously."
                            )

                all_potential_validated_files = find_all_validated_json_files(
                    BASE_API_OUTPUT_DIR
                )  # Re-scan
                action_for_existing_reviewed = "process"
            elif user_choice_existing == "a":
                _shutdown_requested = True
            else:
                action_for_existing_reviewed = "skip"
        else:
            action_for_existing_reviewed = "process"

    if not _shutdown_requested:
        for f_path_check in all_potential_validated_files:
            if _shutdown_requested:
                break
            sn_check = os.path.basename(f_path_check).replace(VALIDATED_FILE_SUFFIX, "")
            if (
                action_for_existing_reviewed == "skip"
                and sn_check in sns_with_existing_reviewed_files
            ):
                logger.info(f"Skipping {f_path_check} (reviewed version exists).")
                continue
            files_to_process_this_run.append(f_path_check)

    if _shutdown_requested:
        logger.info("Processing aborted.")
        sys.exit(0)
    if not files_to_process_this_run:
        logger.info("No files remaining to review.")
        sys.exit(0)

    logger.info(f"Starting review for {len(files_to_process_this_run)} files...")
    if input("Proceed? (y/n): ").lower() != "y":
        logger.info("User chose not to proceed.")
        sys.exit(0)

    reviewed_count, skipped_count, error_count = 0, 0, 0
    for idx, file_path in enumerate(files_to_process_this_run):
        if _shutdown_requested:
            break
        logger.info(
            f"\n--- Processing file {idx + 1} of {len(files_to_process_this_run)} ---"
        )
        status = process_single_file_for_review_auto_batch(
            file_path,
            BASE_API_OUTPUT_DIR,
            BASE_ARCHIVE_DIR_SOURCES,
            REVIEWED_JSON_DIR,
            REVIEWED_FILE_SUFFIX,
            PROCESSED_ORIGINALS_SUBDIR_NAME,
        )
        if status == "reviewed":
            reviewed_count += 1
        elif status == "skipped":
            skipped_count += 1
        elif status == "error":
            error_count += 1
        elif status == "quit_all":
            _shutdown_requested = True
            break

    logger.info(
        f"\n--- Overall Review Summary ---\nFiles presented: {len(files_to_process_this_run)}\nSuccessfully reviewed: {reviewed_count}\nSkipped by user: {skipped_count}\nErrors: {error_count}"
    )
    logger.info("\n--- Review Script Finished ---")
    if _shutdown_requested:
        logger.info("Process shut down by user request.")
    signal.signal(signal.SIGINT, original_sigint_handler)


if __name__ == "__main__":
    main()
