# Consolidated Network Survey Helper & Automated LLM Processor

> **Repository-layout note.** This runbook predates the package refactor. File names below
> refer to the original flat layout; each now maps to netsurvey/<subpackage>/<name>.py.
> For example create_db.py is now netsurvey/db/create_db.py and is run as
> python -m netsurvey.db.create_db. See docs/TRACEABILITY.md for the full mapping.

**Project Version (GUI): 3.0.1**
**Database Schema Version: 2.16.0**
**LLM Prompt Version for Automated Processing: Staged Prompts (`llm_prompt_stage1a.txt`, `llm_prompt_stage1b.txt`, `llm_prompt_stage2_mac.txt`)**
**Primary LLM Processing Script: `unified_processor.py`**
**LLM API Interaction Module: `gemini.py`**
**Main Network Diagramming Script: `network_diagram_generator.py`**
**Diagramming Helper Modules: `diagram_config_utils.py`, `diagram_graph_builder.py`, `diagram_inference_engine.py`**
**MOONID Propagation Module: `infer_moonids_from_topology.py`**

## 1. Introduction & Strategic Context

### 1.1. Project Goal & Scope
This project provides the `network-survey-helper` GUI application and a comprehensive data collection and processing methodology for network infrastructure surveys. It aims to establish an accurate, reliable, and granular data baseline for network-connected devices, enabling robust analysis and visualization.

The backend processing is divided into two main parts:
1.  **Managed Switch Data Extraction:** Uses `unified_processor.py` to orchestrate `gemini.py` for LLM-based parsing of console logs.
2.  **Network Topology Analysis & Visualization:** Uses `network_diagram_generator.py` along with its helper modules (`diagram_config_utils.py`, `diagram_graph_builder.py`, `diagram_inference_engine.py`) and `infer_moonids_from_topology.py` to process database data, infer relationships, and generate diagrams.

### 1.2. Strategic Importance
The data collected and processed is crucial for:
*   Network upgrade planning and design.
*   Precise procurement and budgeting.
*   Risk mitigation and effective change management.
*   Improved operational handover and documentation.
*   Topological understanding and troubleshooting through diagrams.

### 1.3. Methodology Evolution
The methodology emphasizes:
*   **Field Efficiency:** Streamlined on-site data capture (GUI).
*   **Data Consistency & Quality:** Standardized formats and reference data.
*   **Standardized Log & Metadata Storage:**
    *   Logs: A pre-defined directory structure for console logs, created by `create_log_folders.py`, ensures deterministic log retrieval.
    *   Metadata: `<SN>-WAVE1.meta.json` files are stored hierarchically under `survey_outputs/metadata/` mirroring the log structure.
*   **Automated Log Parsing (LLM - Managed Switches):**
    *   `unified_processor.py`: Orchestrates LLM processing. **Prompts user to select a Lab Area, then automatically determines log paths based on switch metadata and the standardized log folder structure.** Prepares input packages (device data only) for `gemini.py`. Includes a retry mechanism.
    *   `gemini.py`: Handles all Google Gemini API interaction, including selectable model configurations, multi-stage data extraction (with stage-specific prompts provided by `unified_processor.py`), and Pydantic model validation.
    *   `llm_prompt_stage1a.txt`, `llm_prompt_stage1b.txt`, `llm_prompt_stage2_mac.txt`: Detailed, staged instructions for the LLM.
    *   **Optimized Wave 2 checklist loading in `DataManager` by reading from specific metadata subdirectories (cache removed).**
*   **Automated Network Diagramming & Analysis:**
    *   `network_diagram_generator.py`: Main script to generate diagrams.
    *   `diagram_config_utils.py`, `diagram_graph_builder.py`, `diagram_inference_engine.py`, `infer_moonids_from_topology.py`: Helper modules for diagramming.
*   **Concurrency:** `unified_processor.py` uses `concurrent.futures.ProcessPoolExecutor` for batch LLM processing.

## 2. End-to-End Workflow

### Phase 0: Foundation - Pre-Survey Setup
*   **Objective:** Establish foundational data, tools, and log/metadata storage structure.
*   **Process:**
    1.  Curate `data/lab_areas_data.json`, `data/moonid_areas_data.json`, site-specific MOONID files.
    2.  Develop/Refine LLM Staged Prompt Files.
    3.  Define Pydantic Models in `gemini.py`.
    4.  Initialize Database: Run `python create_db.py` (Schema v2.16.0).
    5.  **Create Log Folder Structure:** Run `python create_log_folders.py`.
*   **Outputs:** Accurate reference JSONs, initialized DB, LLM prompts, Pydantic models, empty log folder structure. The root `survey_outputs/metadata/` directory will also be ensured.

### Phase 1: Field - GUI Driven Data Capture
*   **Objective:** Capture raw device information and console logs.
*   **Tool:** `main_app.py` (GUI application).
*   **Process:**
    *   Surveyors use the GUI.
    *   When saving Wave 1 metadata, `DataManager` saves `<SN>-WAVE1.meta.json` into the appropriate hierarchical subdirectory under `survey_outputs/metadata/`.
    *   The GUI instructs the surveyor on the **exact pre-created path** (e.g., `survey_outputs/logs/<Site>/<Bldg-Flr-Wing-Area>/`) where they must **manually save** their console log file (e.g., `<SN>-WAVE1.txt`).
*   **Outputs:** Hierarchically stored metadata files, other device logs (`survey_outputs/other_device_logs/`), and manually saved console logs in their specific location-based folders.

### Phase 2: Automated LLM Processing & Structured JSON Generation (Managed Switches)
*   **Objective:** Parse console logs for managed switches using LLM.
*   **Tools:** `unified_processor.py`, `gemini.py`, staged LLM prompts.
*   **Process:** Run `python unified_processor.py`.
    *   The script prompts the user to select a target Lab Area.
    *   It then **automatically determines the exact path to find console logs** for each switch in that lab area.
    *   It assembles device-data-only packages (metadata, logs, site MOONIDs) for each switch.
    *   `gemini.py` is called, which prepends the appropriate stage-specific prompt content to the device data before sending to the API.
*   **Outputs:** `<SN>_validated.json` files (stored hierarchically under `validated_jsons_api_.../`) and archived source files.

### Phase 3: Manual Review and Correction (LLM Output)
*   **Objective:** Human experts verify/correct LLM-generated `<SN>_validated.json`.
*   **Tool:** `phase3_review_tool_auto_batch.py`.
*   **Output:** `<SN>_reviewed.json` files (or overwritten `_validated.json`).

### Phase 4: Backend - Database Ingestion
*   **Objective:** Load all survey data into `network_survey.db`.
*   **Process:**
    1.  Run `python load_other_devices_json_to_db.py`.
    2.  Ensure `JSON_FOLDER` in `load_validated_json_to_db.py` points to the directory containing final managed switch JSONs (e.g., `validated_jsons_api_reviewed/` or the output of `unified_processor.py`). The script now searches recursively.
    3.  Run `python load_validated_json_to_db.py`.
*   **Output:** Populated `network_survey.db`.

### Phase 5: Network Diagramming & Topology Analysis
*   **Objective:** Visualize network topology, infer roles, connect APs robustly, and propagate MOONIDs.
*   **Tools:** `network_diagram_generator.py` (and its helper modules), `infer_moonids_from_topology.py`.
*   **Process:**
    1.  Run `python network_diagram_generator.py`. This will attempt to update the MAC vendor list from IEEE.
    2.  Follow prompts: Select target Site, Building, Floor, Lab Area (or "ALL Areas on this Floor").
    3.  Optionally, enter the Serial Number of the Floor Access Switch (FAS).
    4.  Optionally, choose whether to apply standard diagram filtering.
*   **Outputs (Phase 5):**
    *   Diagram image (e.g., `.png`) in `network_diagrams_pydot_final/`. For external LLDP neighbors identified by MAC address (where system name is missing), a vendor-derived name (e.g., "(Cisco Device)") is displayed.
    *   `_uplinks.json` file (detailing switch uplinks and **including an `is_isolated_from_fas` flag**) in the same directory.
    *   Database updates: `switches.uplink_type` (can be "Isolated"), `logged_access_points.uplink_type` (can be "Isolated"), and `switch_moonid_map` (with topologically inferred MOONIDs).
    *   More accurate representation of external devices and AP connections due to enhanced de-duplication and linking logic.

### Phase 6: Reporting & Further Analysis
*   **Objective:** Derive insights, generate custom reports.
*   **Tools:** `export_lab_area_to_excel.py` (uses `_uplinks.json` and DB `uplink_type` fields).
*   **Outputs:** Excel reports, data summaries. Isolated managed switches and APs will have "Uplink from", "Uplink Type", and "User Subnet" fields marked as "Isolated", "Isolated", and "Isolated Network" respectively in the Excel export.

## 3. Key Python Scripts & Their Roles

*   **GUI Application:**
    *   `data_manager.py`: Manages loading reference data, **saving Wave 1 metadata hierarchically,** reading metadata from specific subdirectories for Wave 2 checklist (no cache), saving other survey outputs, and managing persistent state.
*   **Database & Initial Data:**
    *   `create_log_folders.py`: Pre-creates standardized log directory structure.
*   **LLM Processing Pipeline:**
    *   `unified_processor.py`: Orchestrates LLM processing. **Prompts for Lab Area, automatically finds logs from standardized paths.** Assembles device-data-only packages.
    *   `gemini.py`: Handles Gemini API interaction, Pydantic validation, and multi-stage data extraction (receives stage-specific prompts from `unified_processor.py`).
*   **Data Loading:**
    *   `load_validated_json_to_db.py`: Loads LLM-processed managed switch JSONs. **Now searches recursively for JSON files.**
*   **Network Diagramming & Analysis (`./`):**
    *   `network_diagram_generator.py`: Main executable for creating diagrams and running topology analyses. **Attempts to update MAC OUI vendor list from IEEE on each execution.**
    *   `diagram_config_utils.py`: Constants (paths, styles, inference params, AP linking constants) and basic utilities for diagramming.
    *   `diagram_graph_builder.py`: Builds the NetworkX graph from database data (switches, APs, LLDP/CDP). Contains **enhanced logic to resolve and de-duplicate external LLDP/CDP neighbor nodes using a multi-identifier cache and to link Access Points using exact and systematically varied MAC addresses.**
    *   `diagram_inference_engine.py`: Performs role inference, MAC-based switch-to-switch link inference, and calls MOONID propagation.
    *   `infer_moonids_from_topology.py`: Contains the FAS-aware MOONID propagation logic.
*   **Reporting (`./`):**
    *   `export_lab_area_to_excel.py`.

## 4. Directory Structure (Expected)
```
project_root/
├── main_app.py, config.py, data_manager.py, ui_components.py, utils.py
├── create_db.py, create_log_folders.py
├── llm_prompt_stage1a.txt, llm_prompt_stage1b.txt, llm_prompt_stage2_mac.txt
├── unified_processor.py, gemini.py, phase3_review_tool_auto_batch.py
├── load_validated_json_to_db.py, load_other_devices_json_to_db.py
├── network_diagram_generator.py, diagram_*.py, infer_moonids_from_topology.py
├── export_lab_area_to_excel.py
├── network_survey.db
├── data/
│   ├── lab_areas_data.json, moonid_areas_data.json, <SITE>_moonids.json
├── survey_outputs/
│   ├── metadata/                       # Root for hierarchical metadata
│   │   └── <Site>/                     # Sanitized Site Name
│   │       └── <Bldg-Flr-Wing-Area>/   # Standardized location segment
│   │           ├── <SN1>-WAVE1.meta.json
│   │           └── ...
│   ├── logs/                           # Standardized Log Directory Root
│   │   └── <Site>/
│   │       └── <Bldg-Flr-Wing-Area>/
│   │           ├── <SN1>-WAVE1.txt
│   │           └── ...
│   └── other_device_logs/
├── validated_jsons_api_structured_MAC_CHUNKED_MP/ # Output from unified_processor.py
│   ├── _archive_source_files/
│   │   └── <Site>/<Bldg-Flr-Wing-Area>/<SN>/
│   │       ├── <SN>-WAVE1.meta.json    # Copied from its hierarchical survey_outputs/metadata path
│   │       └── ... (logs, moonid data, package file)
│   └── <Site>/<Bldg-Flr-Wing-Area>/
│       └── <SN>_validated.json
├── validated_jsons_api_reviewed/ # (Optional)
│   └── <Site>/<Bldg-Flr-Wing-Area>/
│       └── <SN>_reviewed.json
└── network_diagrams_pydot_final/
    └── ... (diagrams and uplink JSONs)
```


*(Note: If the GUI is run as a frozen executable (e.g., PyInstaller), `survey_outputs/` will typically be created relative to the executable's location, not necessarily in `dist/` within the source tree.)*
*(The `<Bldg-Flr-Wing-Area>` segment uses placeholders like `__NoWing__` or `__NoArea__` if wing/area info is missing from `lab_areas_data.json`, generated consistently by `create_log_folders.py`, `ui_components.py` (for user instruction), and backend scripts.)*

## 5. Database Schema (v2.16.0 Highlights)
Refer to `create_db.py` and `dbml.txt` for full details. Key tables for diagramming include `switches`, `interfaces`, `mac_address_table`, `lldp_cdp_neighbors`, `logged_access_points`.

## 6. Network Diagramming & Analysis Strategy (using `network_diagram_generator.py` and its helpers)
*   **Scope:** User selects a specific Lab Area (Site/Building/Floor/Area Name) or "ALL Areas on this Floor".
*   **Floor Access Switch (FAS):** User can optionally provide the SN of the FAS. This anchors local topology analysis, role inference, and MOONID propagation.
*   **Graph Construction (`diagram_graph_builder.py`):** Builds a comprehensive NetworkX graph (`G_full_topology`) containing:
    *   Managed switches from the database relevant to the selected scope.
    *   APs relevant to the selected scope.
    *   LLDP/CDP-discovered neighbors, including external/unsurveyed devices. The `resolve_lldp_cdp_remote_node` function uses an **enhanced internal cache (`Dict[Tuple[str, str], str]`) and a prioritized set of normalized identifiers (system name combined with management IP, system name, standardized MAC as device ID, management IP, raw device ID) to robustly de-duplicate external neighbor nodes and enrich their attributes.**
    *   **Access Point Linking:** APs are connected to switches based on:
        1.  An exact match of the AP's reported wired/LAN MAC address in a switch's MAC address table.
        2.  If an exact match fails, a **systematic MAC address variation** is attempted: the last octet of the AP's MAC is incremented up to `MAX_AP_PORT_INDEX_TO_CHECK` times (or until an octet overflow). A link is formed only if exactly one unique switch port shows one of these candidate MACs.
        3.  The selection of the connecting switch (from candidates found by either method) prioritizes in-scope switches, "Access" role, and proximity to the FAS.
*   **Inference Engine (`diagram_inference_engine.py`):**
    *   **Iterative MAC Linking (Switch-to-Switch):** Identifies potential switch-to-switch links obscured by unmanaged hops using shared MAC address analysis. Employs both a hierarchical approach (favoring uplinks to more central switches/FAS) and a relaxed bridging approach for isolated components.
    *   **Role Inference (FAS-Aware):** Classifies managed switches (Core, Router, Distribution, Access) based on connectivity (degree, betweenness centrality in the inter-switch graph) and their topological relationship (e.g., distance) to the specified FAS. The `device_type` from the database also influences this.
    *   **MOONID Propagation Trigger:** Calls the `propagate_moonids_in_diagram` function from `infer_moonids_from_topology.py`.
*   **MOONID Propagation (`infer_moonids_from_topology.py`):** Propagates MOONIDs in a top-down manner, anchored by the FAS (if specified) and other high-level switches (Core/Distribution/Router) that already possess MOONIDs. Propagation to downstream switches and connected APs is hierarchical and considers the path to the FAS.
*   **Output Generation (`network_diagram_generator.py`):**
    *   Optionally filters `G_full_topology` to create `G_diagram_final` focusing on the selected lab area and directly connected relevant devices. If filtering is disabled, `G_diagram_final` is a copy of `G_full_topology`.
    *   Generates a Pydot image (e.g., `.png`) of `G_diagram_final` and saves it to `network_diagrams_pydot_final/`. The FAS is visually highlighted. Nodes are clustered by their inferred role. **For external LLDP neighbors where the system name is not available but the device ID is a MAC address, it attempts to display a vendor-derived name (e.g., "(Cisco Device)") using the `mac-vendor-lookup` library.**
    *   Creates an `_uplinks.json` file in the same directory, detailing the inferred uplink device (hostname, SN, role), connection type, and **`is_isolated_from_fas` boolean flag** for each managed switch in `G_diagram_final`. This file is used by `export_lab_area_to_excel.py`.
    *   Updates the `switches.uplink_type` and `logged_access_points.uplink_type` fields in the database based on the diagram analysis (these can now be "Isolated").

## 7. Setup and Installation

### 7.1. GUI Application (`main_app.py`)
*   Python 3.9+. Tkinter (usually built-in).

### 7.2. Backend & Diagramming Scripts
1.  Python 3.9+.
2.  **Core Processing & LLM:**
    *   Google Generative AI SDK: `pip install google-genai`
    *   Pydantic: `pip install pydantic` (v2.x recommended for `model_dump_json`).
3.  **Diagramming & Analysis:**
    *   NetworkX: `pip install networkx`
    *   Pydot: `pip install pydot`
    *   **MAC Vendor Lookup**: `pip install mac-vendor-lookup` (used for identifying vendors of external devices by MAC address). The script attempts to update the local vendor list on each run.
    *   Graphviz: Must be installed on your system and its `bin` directory added to the system PATH (e.g., `brew install graphviz` on macOS, download installer for Windows from [graphviz.org](https://graphviz.org/download/)).
4.  **Reporting:**
    *   Pandas & Openpyxl: `pip install pandas openpyxl`.

## 8. Running the Workflow

All Python scripts should generally be executed from the `project_root/`.

## 8. Running the Workflow

**Step 1: Prepare Reference Data, Prompt, Database, and Log Folders**
1.  Populate `data/`.
2.  Ensure LLM staged prompt files are correct.
3.  Verify `gemini.py` Pydantic models (now imported by `phase3_review_tool.py`).
4.  Run `python create_db.py`.
5.  **Run `python create_log_folders.py`** (critical first step).

**Step 2: Run GUI for Field Survey**
1.  Execute `python main_app.py`.
2.  `DataManager` saves `<SN>-WAVE1.meta.json` hierarchically.
3.  Surveyor manually saves console logs to the specific pre-created path instructed by the GUI.

**Step 3: Automated LLM Processing (for Managed Switch logs)**
1.  API Key in `gemini.py`.
2.  Review params in `unified_processor.py`.
3.  Execute: `python unified_processor.py`.
4.  Follow Prompts:
    *   Prompts for **Lab Area** selection to process.
    *   Automatically finds logs and metadata from standardized hierarchical paths.
    *   Select LLM Configuration (if applicable).
    *   Handle prompts for existing output files.

**Step 4: Manual Review of LLM-Generated JSON (Optional but Recommended)**
1.  Review `<SN>_validated.json` files produced in `validated_jsons_api_structured_MAC_CHUNKED_MP/`.
2.  Use `python phase3_review_tool_auto_batch.py` to facilitate this. It helps open files, view review items, and moves processed files.
3.  Reviewed files are typically saved to `validated_jsons_api_reviewed/`.

**Step 5: Load All Data into Database**
1.  Run `python load_other_devices_json_to_db.py` (loads GUI logs for unmanaged devices, APs, etc.).
2.  In `load_validated_json_to_db.py`, ensure `JSON_FOLDER` points to the directory containing the final managed switch JSONs (e.g., `validated_jsons_api_reviewed/` or directly to `validated_jsons_api_structured_MAC_CHUNKED_MP/` if review is skipped).
3.  Run `python load_validated_json_to_db.py`.

**Step 6: Generate Network Diagram & Run Topology Analysis**
1.  Run `python network_diagram_generator.py`. The script will attempt to update its MAC vendor OUI list at the start.
2.  Follow prompts to select the target Site, Building, Floor, and Lab Area (or "ALL Areas on this Floor").
3.  Optionally enter the Serial Number of the Floor Access Switch (FAS) for that area.
4.  Optionally choose whether to apply standard diagram filtering (default is "Yes").
5.  Outputs:
    *   Diagram image (e.g., `.png`) in `network_diagrams_pydot_final/`.
    *   An `_uplinks.json` file in the same directory (includes `is_isolated_from_fas` flag for switches).
    *   Database updated with `switches.uplink_type`, `logged_access_points.uplink_type` (can be "Isolated"), and topologically inferred `switch_moonid_map` entries.

**Step 7: Visualize Diagram & Further Reporting**
1.  Open the generated image file from `network_diagrams_pydot_final/`.
2.  Run `python export_lab_area_to_excel.py` (which now uses the `_uplinks.json` file and DB fields to identify isolated devices).
3.  Use custom SQL queries against `network_survey.db` for other reports.

## 9. Data Quality Considerations & Risks
*   **Reference Data Accuracy:** Accuracy of `lab_areas_data.json`, `moonid_areas_data.json`, and site MOONID files is vital.
*   **Surveyor Discipline:** Critical for consistent log quality, correct console log naming (`<SN>-WAVE1.txt`), accurate GUI input, and **saving logs into the correct pre-created directory as instructed by the GUI.**
*   **Log Folder Creation:** Failure to run `create_log_folders.py` before surveying, or surveyors not saving logs to the precise specified paths, will lead to logs not being found by backend processors.
*   **LLM Content Accuracy:** Highly dependent on the quality of LLM prompt files and the chosen LLM model/configuration. The `items_for_review` section in LLM output is a key indicator for manual checks. The retry mechanism in `unified_processor.py` helps mitigate transient API errors but doesn't correct fundamentally flawed LLM responses.
*   **Pydantic Schema & LLM Prompt Alignment:** The Pydantic models in `gemini.py` must precisely match the JSON structure expected by the LLM prompt.
*   **Concurrency and API Rate Limits:** `MAX_WORKERS_FOR_POOL` in `unified_processor.py` should be set considering API rate limits and system resources.
*   **Manual Review Thoroughness:** If Phase 3 (manual review of LLM output) is performed, its thoroughness is a critical quality gate.
*   **Database Completeness for Diagramming:** `network_diagram_generator.py` relies on comprehensive and accurate data loaded into the database from previous phases.
*   **Inference Heuristics:** MAC-based link inference parameters (in `diagram_config_utils.py`) and switch role classification thresholds may need tuning based on the specific network environment. The AP MAC variation (`MAX_AP_PORT_INDEX_TO_CHECK`) is a heuristic.
*   **FAS Identification:** Correctly identifying the Floor Access Switch SN for diagramming and analysis is important for optimal local role inference and MOONID propagation. The `distance_to_fas` attribute on nodes helps identify isolated components.
*   **LLDP/CDP Data Variability:** The quality and completeness of LLDP/CDP data from devices can vary. The LLM prompt and the `resolve_lldp_cdp_remote_node` function in diagramming attempt to handle this robustly.
*   **MAC Vendor List Freshness:** `network_diagram_generator.py` attempts to update the `mac-vendor-lookup` library's local OUI list on each run. If this update fails (e.g., due to network issues), it will use its cached version. For critical accuracy, ensure the machine running the script can access `http://standards-oui.ieee.org`.
*   **Data Staleness:** Diagrams and analyses reflect the network state at the time of data capture.

## 10. Troubleshooting Common Issues

*   **`unified_processor.py` / `organize_survey_data.py` cannot find logs:**
    *   Ensure `create_log_folders.py` was run before surveying.
    *   Verify that surveyors manually saved the console logs (e.g., `<SN>-WAVE1.txt`) into the exact path structure created by the utility (e.g., `survey_outputs/logs/<Site>/<Building-Floor-Wing-AreaName>/`).
    *   Check that the metadata for the switch (Site, Building, Floor, Wing, Area) matches the folder names (including placeholders like `__NoWing__` or `__NoArea__`). The path generation logic must be identical between `create_log_folders.py`, `ui_components.py` (for user instruction message), and the backend processing scripts.
    *   Confirm `LOGS_BASE_DIR_RAW` in `unified_processor.py` (or `LOGS_BASE_DIR` in `organize_survey_data.py`) correctly points to the root of your log structure (e.g., `survey_outputs/logs` if running from project root where `config.py` also lives, or `dist/survey_outputs/logs` if paths are hardcoded for a `dist` structure). This is now typically handled by importing from `config.py`.
*   **`create_log_folders.py` issues:**
    *   `config.py` or `utils.py` not found: Ensure the script is run from project root, or that its import logic correctly finds these files (sys.path manipulation at the top of the script tries to handle this).
    *   `lab_areas_data.json` not found or malformed: Check path and JSON validity.
    *   Permission errors creating directories.
*   **`unified_processor.py` / `gemini.py` (LLM Pipeline):**
    *   `ImportError: No module named 'gemini'`: Ensure `gemini.py` is in the same directory or Python path.
    *   API Key Issues: Check the hardcoded key in `gemini.py`.
    *   Pydantic Validation Errors: Indicates LLM output does not match the Pydantic schemas in `gemini.py`. Review prompt and models.
    *   `BlockedPromptException`: LLM content safety filters triggered. Review prompt or input log data.
    *   Errors from `ProcessPoolExecutor`: Check script logs (`_unified_script_error_logs/`) and individual SN error logs from `gemini.py` (in the output JSON directory). Note that `unified_processor.py` will retry a failed LLM call once.
*   **Wave 2 checklist (in GUI) does not update or shows incorrect/stale information:**
    *   The application uses a cache for Wave 1 metadata to improve loading speed. This cache is updated on application start and when metadata files change.
    *   Ensure the file modification times in your `survey_outputs/metadata/` directory are updating correctly when files are saved.
    *   If you manually modified a `<SN>-WAVE1.meta.json` file outside the application, restarting the application will ensure the cache picks up these changes.
    *   If a device appears unexpectedly or is missing from the checklist, verify its Wave 1 metadata file for correctness (location matching the current GUI selection, LLDP/CDP operational status, `wave2_data_captured_in_wave1_log` flag) and ensure it hasn't been accidentally marked as Wave 2 complete in the `wave2_completion_status.json` file.
*   **`load_*.py` Scripts:**
    *   `sqlite3.OperationalError: no such table...`: Database schema mismatch. Ensure `create_db.py` (v2.16.0) was run successfully. Check `DB_FILENAME` path in `create_db.py`.
    *   Foreign Key (FK) constraint errors: Usually means `lab_areas_data.json` was not loaded into the DB or a location specified in device data doesn't exist as a primary key in `lab_areas` table.
*   **`network_diagram_generator.py` (and its `diagram_*` helpers):**
    *   `ImportError` for `diagram_config_utils`, `diagram_graph_builder`, `diagram_inference_engine`, `infer_moonids_from_topology`, or **`mac_vendor_lookup`**: Ensure all five Python files for diagramming are in the same directory and all required libraries are installed (e.g., `pip install mac-vendor-lookup`).
    *   Missing `networkx` or `pydot`: `pip install networkx pydot`.
    *   Graphviz/Pydot Errors (e.g., "dot: command not found", "failed to execute"): Graphviz is likely not installed correctly or its `bin` directory is not in the system PATH.
    *   Empty or sparse diagrams: Check DB population for the selected lab area. Ensure data loading scripts ran correctly. Verify if the chosen diagram filtering option is too restrictive.
    *   Inaccurate inferred links/roles: Review inference parameters in `diagram_config_utils.py`, check if the FAS SN was entered correctly if applicable, or investigate source data quality.
    *   AP linking issues: Verify `logged_access_points.mac_address` and `logged_access_points.reported_total_ports` in the database. Check console logs for MAC variation attempts in `diagram_graph_builder.py`.
    *   **`mac-vendor-lookup` update failure:** The script attempts to update the OUI list from IEEE on each run. If it fails (e.g., no internet, IEEE site down), it will proceed with a cached list if available. For consistent results, ensure the machine can access `http://standards-oui.ieee.org/oui.txt`.
*   **General:**
    *   File Not Found Errors: Verify all paths in scripts and `config.py` constants (`DATA_DIR`, `OUTPUT_DIR`, `LOGS_DIR`). Ensure scripts are run from `project_root/`.
    *   `NameError: name 're' is not defined` (or similar for other standard libraries): Ensure `import re` (or other necessary imports) are at the top of the respective Python files.

## 11. Future Enhancements / To-Do List
*   GUI enhancements (e.g., integrated log viewer, direct LLM submission from GUI).
*   More adaptive/configurable parameters for LLM processing (e.g., number of retries, retry delay) and diagram inference (e.g., via a config file instead of hardcoding).
*   Advanced NetworkX analyses (e.g., VLAN tracing, path analysis) to enrich diagram annotations or generate specific reports.
*   CLI arguments for scripts (`unified_processor.py`, `network_diagram_generator.py`) to bypass some interactive prompts for easier automation.
*   Secure API key management (e.g., environment variables, dedicated config files not committed to version control).
*   More robust error handling and summary reporting across all scripts.
*   GUI option to directly invoke `create_log_folders.py` functionality.
*   Validation in `create_log_folders.py` to check for extremely long generated folder names that might exceed OS path limits.
