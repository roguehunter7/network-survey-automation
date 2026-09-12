# config.py
"""Application configuration constants and path definitions."""

import os
import sys

# --- Application Info ---
APP_VERSION = "3.0.1"  # Assuming this is the current version from your files
APP_TITLE = f"Consolidated Network Survey Helper - v{APP_VERSION}"

# --- Base Directory and Data Directory Logic ---
# Determine base directory and data directory for executable or script
# Uses sys._MEIPASS for bundled resources if available (PyInstaller)
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    # Running as a bundled app (frozen)
    _RESOURCE_PATH = sys._MEIPASS
    BASE_DIR = os.path.dirname(sys.executable)  # Output relative to executable
    DATA_DIR = os.path.join(_RESOURCE_PATH, "data")  # Data bundled within
    # print(f"DEBUG: Running Frozen. MEIPASS={_RESOURCE_PATH}, BASE={BASE_DIR}, DATA={DATA_DIR}")
else:
    # Running as a normal script
    try:
        # Assumes config.py is in the project root.
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    except NameError:  # Fallback for environments like REPL
        BASE_DIR = os.getcwd()
    DATA_DIR = os.path.join(BASE_DIR, "data")
    # print(f"DEBUG: Running as Script. BASE={BASE_DIR}, DATA={DATA_DIR}")


# --- Data File Names (External - MUST be in DATA_DIR) ---
LAB_AREAS_FILENAME = "lab_areas_data.json"
MOONID_AREAS_FILENAME = "moonid_areas_data.json"

# --- Input/Output Paths (Derived from BASE_DIR) ---
OUTPUT_DIR = os.path.join(BASE_DIR, "survey_outputs")

# Standardized root directory for manually saved console logs.
# Subfolders (<Site>/<Building-Floor-Wing-AreaName>/) are expected to be
# pre-created by the 'create_log_folders.py' utility script.
LOGS_DIR = os.path.join(OUTPUT_DIR, "logs")

METADATA_DIR = os.path.join(OUTPUT_DIR, "metadata")
OTHER_DEVICE_LOGS_DIR = os.path.join(OUTPUT_DIR, "other_device_logs")

# --- State File Paths (Relative to where app runs from - BASE_DIR) ---
# Changed SESSION_STATE_DIR to BASE_DIR for simplicity unless specifically needed elsewhere.
SESSION_STATE_DIR = BASE_DIR
WAVE2_STATUS_FILENAME = os.path.join(SESSION_STATE_DIR, "wave2_completion_status.json")
# DEFERRED_SWITCH_STATUS_FILENAME was removed

# --- GUI Styling / Constants ---
DEFAULT_STATUS_REASON = "Unmanaged (No CLI)"  # Default for Log Other Device
DEFAULT_DEVICE_TYPE = "Switch"  # Default for Wave 1
DEFAULT_IP_RANGE_TEXT = "---"  # Placeholder for MOONID lookup
WINDOW_MIN_WIDTH = 850
WINDOW_MIN_HEIGHT = 750

# Note: Directory creation for OUTPUT_DIR, METADATA_DIR, OTHER_DEVICE_LOGS_DIR,
# and SESSION_STATE_DIR (if BASE_DIR itself needs creation, though unlikely for script run)
# is typically handled by DataManager initialization in the GUI application.
# The specific, deep subfolders within LOGS_DIR are expected to be pre-created
# by the 'create_log_folders.py' utility script before surveyors save logs into them.
