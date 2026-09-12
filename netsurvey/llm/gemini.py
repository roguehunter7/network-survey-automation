# gemini.py (Corrected generation_config to config)

import argparse
import json
import logging
import os
import re
import sys
import time
import traceback
from typing import Dict, List, Literal, Optional

# --- Google Generative AI (New SDK) ---
from google import genai
from google.genai import errors as genai_errors  # For genai_errors.APIError
from google.genai import types as genai_types

# --- Pydantic Imports ---
from pydantic import BaseModel, Field, RootModel, ValidationError


# --- Pydantic Model Definitions (Remain Unchanged) ---
class SwitchDetails(BaseModel):
    serial_number: str = Field(
        description="MANDATORY. From meta.json, VERIFIED in log..."
    )
    hostname: str
    model: str = Field(description="MANDATORY. From meta.json, VERIFIED in log...")
    make: str = Field(
        description="MANDATORY. From meta.json, VERIFIED/inferred reliably in log..."
    )
    device_type: str
    base_mac_address: Optional[str] = None
    lab_area_name: str
    floor: str
    site: str
    building: str
    location_notes: str
    rack_type_detail: str
    access_level: str
    survey_timestamp: str
    log_filename_validated: str
    ip_version_routing: Literal["ipv4", "ipv6", "both", "none"]
    running_config_captured: int
    is_poe_capable: Optional[int] = None
    handles_internal_vlans: int
    user_verified_total_ports: Optional[int] = None
    user_verified_used_ports: Optional[int] = None


class Interface(BaseModel):
    interface_name: str
    status: Optional[str] = None
    vlan: Optional[str] = None
    duplex: Optional[str] = None
    speed: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None


class Vlan(BaseModel):
    vlan_id: int
    vlan_name: Optional[str] = None
    status: Optional[str] = None
    ports_associated_text: Optional[str] = None


class IpInterface(BaseModel):
    interface_name: str
    mac_address: Optional[str] = None
    ip_address_with_prefix: Optional[str] = None
    status: Optional[str] = None
    protocol_status: Optional[str] = None
    is_management: Optional[int] = None


class MacEntry(BaseModel):
    mac_address: str
    interface_name: str
    vlan_id: int
    type: Optional[str] = None


class MacEntryList(RootModel[List[MacEntry]]):
    root: List[MacEntry]

    def __iter__(self):
        return iter(self.root)

    def __getitem__(self, item):
        return self.root[item]


class ArpEntry(BaseModel):
    ip_address: str
    mac_address: Optional[str] = None
    interface_name: Optional[str] = None
    vlan_id: Optional[int] = None
    type: Optional[str] = None
    age_in_seconds: Optional[int] = None


class Route(BaseModel):
    ip_version: Literal["4", "6"]
    destination_prefix: str
    next_hop_ip: Optional[str] = None
    outgoing_interface: Optional[str] = None
    metric: Optional[int] = None
    protocol: Optional[str] = None
    is_default_route: int


class MoonidAssociation(BaseModel):
    moonid: str
    resolution_method: Literal[
        "SVI_IP_Match", "ARP_IP_Match", "Route_Destination_IP_Match", "VLAN_ID_Match"
    ]
    confidence_score: float


class DiscoveredUnassignedNetwork(BaseModel):
    network_prefix: str
    discovery_source_type: Literal[
        "SVI_Unmatched", "ARP_Unmatched_IP", "Route_Unmatched_Destination"
    ]
    discovery_context: Optional[str] = None


class Neighbor(BaseModel):
    local_interface_name: str
    protocol_used: Literal["LLDP", "CDP"]
    remote_device_id: str
    remote_interface_name: str
    remote_system_name: Optional[str] = None
    remote_mgmt_address: Optional[str] = None
    remote_model: Optional[str] = None


class ItemForReview(BaseModel):
    severity: Literal["High", "Medium", "Low"]
    item_path: str
    reason: str
    details: str


class NetworkDeviceDataStage1A(BaseModel):
    switch_details: SwitchDetails
    interfaces: List[Interface]
    vlans: List[Vlan]
    ip_interfaces: List[IpInterface]
    arp_entries: List[ArpEntry]
    routes: List[Route]
    neighbors: List[Neighbor]
    items_for_review: List[ItemForReview]


class NetworkDeviceDataStage1BOutput(BaseModel):
    moonid_associations: List[MoonidAssociation]
    discovered_unassigned_networks: List[DiscoveredUnassignedNetwork]
    items_for_review: List[ItemForReview]


class NetworkDeviceData(BaseModel):  # Final combined model
    switch_details: SwitchDetails
    interfaces: List[Interface]
    vlans: List[Vlan]
    ip_interfaces: List[IpInterface]
    mac_entries: List[MacEntry]
    arp_entries: List[ArpEntry]
    routes: List[Route]
    moonid_associations: List[MoonidAssociation]
    discovered_unassigned_networks: List[DiscoveredUnassignedNetwork]
    neighbors: List[Neighbor]
    items_for_review: List[ItemForReview]


# --- Configuration Constants ---
# Credentials are NEVER hard-coded. Provide the key through the environment:
#     export GEMINI_API_KEY="your-key-here"      (see .env.example)
API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

MAC_BATCH_TARGET_SIZE = 100
MAX_MAC_BATCH_ITERATIONS = 50
MAC_BATCH_DELAY_SECONDS = 1

DELIMITERS = {
    "stage_instruction_start": "%%%START_STAGE_INSTRUCTION%%%",
    "stage_instruction_end": "%%%END_STAGE_INSTRUCTION%%%",
    "stage1a_output_start": "%%%START_STAGE_1A_OUTPUT_CONTEXT%%%",
    "stage1a_output_end": "%%%END_STAGE_1A_OUTPUT_CONTEXT%%%",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)
logger = logging.getLogger(__name__)


# --- Helper Functions ---
def _extract_sn_from_package_filename(package_filepath: str) -> Optional[str]:
    basename = os.path.basename(package_filepath)
    match = re.match(r"^(.*?)_llm_input_package\.txt$", basename, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    logger.warning(f"Could not extract SN from package filename: {basename}")
    return None


def get_prompt_feedback_details(response_obj) -> str:
    """Extracts prompt feedback details if available."""
    if response_obj and hasattr(response_obj, "prompt_feedback"):
        feedback = response_obj.prompt_feedback
        if feedback:
            reason = getattr(feedback, "block_reason", "N/A")
            message = getattr(feedback, "block_reason_message", str(feedback))
            safety_ratings_str = ""
            if hasattr(feedback, "safety_ratings") and feedback.safety_ratings:
                ratings = [
                    f"{r.category}: {r.probability}" for r in feedback.safety_ratings
                ]
                safety_ratings_str = f" SafetyRatings: [{', '.join(ratings)}]"
            return f"BlockReason: {reason}, Message: {message}{safety_ratings_str}"
    return "N/A"


def _write_error_log_internal(
    error_dir: str,
    base_filename_for_error_log: str,
    stage_info: str,
    sn: str,
    error_details: str,
    input_snippet: Optional[str] = None,
    raw_response: Optional[str] = None,
    prompt_feedback_details: Optional[str] = "N/A",
):
    os.makedirs(error_dir, exist_ok=True)
    problem_filename = os.path.join(
        error_dir, f"GEMINI_API_ERROR_{base_filename_for_error_log}_{stage_info}.txt"
    )
    try:
        with open(problem_filename, "w", encoding="utf-8") as pf:
            pf.write(f"--- GEMINI API ERROR {stage_info} ---\n")
            pf.write(f"SN: {sn}\n")
            pf.write(f"Error: {error_details}\n")
            pf.write(f"Prompt Feedback: {prompt_feedback_details}\n\n")
            if input_snippet:
                pf.write(
                    f"--- INPUT SNIPPET ({len(input_snippet)} chars) ---\n{input_snippet}...\n\n"
                )
            if raw_response:
                pf.write(f"--- RAW API RESPONSE ---\n{raw_response}\n")
        logger.info(
            f"Problematic data for SN {sn} (Stage: {stage_info}) saved to {problem_filename}"
        )
    except Exception as e_log:
        logger.error(f"Failed to write error log to {problem_filename}: {e_log}")


# --- Core LLM Processing Function ---
def process_llm_package_file_to_json(
    input_device_data_filepath: str,
    serial_number: str,
    output_dir: str,
    prompt_stage1a_content: str,
    prompt_stage1b_content: str,
    prompt_stage2_mac_content: str,
    skip_mac_processing: bool = False,
) -> bool:
    logger.info(
        f"FUNC: Processing for SN: {serial_number} from device data file: {input_device_data_filepath} using MODEL: {MODEL_NAME}"
    )
    os.makedirs(output_dir, exist_ok=True)

    base_filename_for_error_log = f"{serial_number}_llm_api_processing"
    final_json_filepath = os.path.join(output_dir, f"{serial_number}_validated.json")

    if os.path.exists(final_json_filepath):
        logger.info(
            f"FUNC: Final JSON {final_json_filepath} already exists. Returning True (as per unified_processor logic)."
        )
        return True

    try:
        with open(input_device_data_filepath, "r", encoding="utf-8") as f:
            device_data_for_llm = f.read()
        if not device_data_for_llm.strip():
            logger.error(
                f"FUNC: Input device data file {input_device_data_filepath} is empty for SN {serial_number}."
            )
            return False
    except Exception as e:
        logger.error(
            f"FUNC: Error reading input device data file {input_device_data_filepath} for SN {serial_number}: {e}"
        )
        return False

    if not API_KEY:
        logger.critical(
            "FUNC: GEMINI_API_KEY is not set. Export it before running the LLM pipeline."
        )
        return False

    try:
        client = genai.Client(api_key=API_KEY)
    except Exception as e_client:
        logger.critical(f"FUNC: Failed to initialize Gemini Client: {e_client}")
        return False

    collected_data_stage1a_dict: Optional[Dict] = None
    collected_data_stage1b_dict: Optional[Dict] = None
    all_collected_mac_entries: List[Dict] = []
    combined_items_for_review: List[Dict] = []

    # --- STAGE 1A: Get simpler data fields ---
    logger.info(f"  FUNC (SN {serial_number}): Requesting Stage 1A (Simpler Fields)...")
    stage1a_operational_instruction_text = (
        "CRITICAL INSTRUCTION FOR THIS STAGE 1A REQUEST:\n"
        "Your JSON output for THIS request MUST ONLY contain the data for the fields defined in the 'NetworkDeviceDataStage1A' schema "
        "(refer to the main prompt content that follows this instruction block for field details like 'switch_details', 'interfaces', etc.).\n"
        "The 'items_for_review' for THIS stage should only include issues found within these specific Stage 1A fields.\n"
        "DO NOT include 'moonid_associations', 'discovered_unassigned_networks', or 'mac_entries' in this Stage 1A response."
    )
    llm_input_stage1a = (
        f"{DELIMITERS['stage_instruction_start']}\n"
        f"{stage1a_operational_instruction_text}\n"
        f"{DELIMITERS['stage_instruction_end']}\n\n"
        f"{prompt_stage1a_content.strip()}\n\n"
        f"{device_data_for_llm.strip()}"
    )
    raw_response_text_stage1a = ""
    response_obj_stage1a = None

    try:
        config_for_stage1a = genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=NetworkDeviceDataStage1A,
        )
        logger.info(
            f"    FUNC (SN {serial_number}): Sending to API for Stage 1A (Model: {MODEL_NAME}). Input size: ~{len(llm_input_stage1a)} chars."
        )
        response_obj_stage1a = client.models.generate_content(
            model=f"models/{MODEL_NAME}",
            contents=[llm_input_stage1a],
            config=config_for_stage1a,  # CORRECTED
        )
        raw_response_text_stage1a = response_obj_stage1a.text

        if response_obj_stage1a.parsed is not None and isinstance(
            response_obj_stage1a.parsed, NetworkDeviceDataStage1A
        ):
            collected_data_stage1a_dict = response_obj_stage1a.parsed.model_dump()
        else:
            logger.warning(
                f"FUNC (SN {serial_number}): Stage 1A - SDK response.parsed was None or not NetworkDeviceDataStage1A. Attempting json.loads from text."
            )
            if raw_response_text_stage1a:
                temp_dict = json.loads(raw_response_text_stage1a)
                NetworkDeviceDataStage1A(**temp_dict)
                collected_data_stage1a_dict = temp_dict
            else:
                raise ValueError("Stage 1A response text is empty and parsed is None.")

        if not isinstance(collected_data_stage1a_dict, dict):
            logger.error(
                f"FUNC (SN {serial_number}): Stage 1A - Parsed JSON data is not a dictionary."
            )
            _write_error_log_internal(
                output_dir,
                base_filename_for_error_log,
                "STAGE1A_NOT_DICT",
                serial_number,
                "Parsed JSON data not a dict for Stage 1A.",
                llm_input_stage1a[:2000],
                raw_response_text_stage1a,
                get_prompt_feedback_details(response_obj_stage1a),
            )
            return False

        combined_items_for_review.extend(
            collected_data_stage1a_dict.get("items_for_review", [])
        )
        logger.info(
            f"    FUNC (SN {serial_number}): SUCCESS - Received Stage 1A data. (Review items: {len(collected_data_stage1a_dict.get('items_for_review', []))})"
        )

    except genai_errors.APIError as api_err_stage1a:
        feedback_details = get_prompt_feedback_details(response_obj_stage1a)
        error_text = f"GEMINI_API_ERROR in Stage 1A: {api_err_stage1a}. Feedback: {feedback_details}"
        logger.error(f"  FUNC (SN {serial_number}): {error_text}")
        _write_error_log_internal(
            output_dir,
            base_filename_for_error_log,
            "STAGE1A_API_ERROR",
            serial_number,
            error_text,
            llm_input_stage1a[:2000],
            raw_response_text_stage1a,
            feedback_details,
        )
        return False
    except json.JSONDecodeError as jde_stage1a:
        error_text = f"JSONDecodeError in Stage 1A: {jde_stage1a}."
        logger.error(
            f"  FUNC (SN {serial_number}): {error_text} Raw: '{raw_response_text_stage1a[:500]}...'"
        )
        _write_error_log_internal(
            output_dir,
            base_filename_for_error_log,
            "STAGE1A_JSON_DECODE_ERROR",
            serial_number,
            error_text,
            llm_input_stage1a[:2000],
            raw_response_text_stage1a,
            get_prompt_feedback_details(response_obj_stage1a),
        )
        return False
    except ValidationError as ve_stage1a:
        error_text = f"Pydantic ValidationError in Stage 1A: {ve_stage1a}."
        logger.error(f"  FUNC (SN {serial_number}): {error_text}")
        _write_error_log_internal(
            output_dir,
            base_filename_for_error_log,
            "STAGE1A_PYDANTIC_VALIDATION_ERROR",
            serial_number,
            error_text,
            llm_input_stage1a[:2000],
            raw_response_text_stage1a,
            get_prompt_feedback_details(response_obj_stage1a),
        )
        return False
    except Exception as e_stage1a:
        error_text = (
            f"UNEXPECTED_ERROR in Stage 1A: {type(e_stage1a).__name__} - {e_stage1a}"
        )
        logger.exception(f"  FUNC (SN {serial_number}): {error_text}")
        _write_error_log_internal(
            output_dir,
            base_filename_for_error_log,
            "STAGE1A_UNEXPECTED_ERROR",
            serial_number,
            error_text,
            llm_input_stage1a[:2000],
            raw_response_text_stage1a,
            get_prompt_feedback_details(response_obj_stage1a),
        )
        return False

    if collected_data_stage1a_dict is None:
        logger.error(
            f"  FUNC (SN {serial_number}): Stage 1A data is None after processing attempt. Aborting."
        )
        return False

    # --- STAGE 1B: Get complex data fields ---
    logger.info(f"  FUNC (SN {serial_number}): Requesting Stage 1B (Complex Fields)...")
    stage1a_output_context_str = json.dumps(collected_data_stage1a_dict, indent=2)
    stage1b_operational_instruction_text = (
        "CRITICAL INSTRUCTION FOR THIS STAGE 1B REQUEST:\n"
        "Refer to the main prompt content (following this instruction block) for detailed field descriptions and rules for 'moonid_associations', 'discovered_unassigned_networks', and 'items_for_review'.\n"
        f"You are ALSO provided with the JSON output from a PREVIOUS Stage 1A, delimited by '{DELIMITERS['stage1a_output_start']}' and '{DELIMITERS['stage1a_output_end']}'. "
        "Use this Stage 1A output as crucial CONTEXT for your inferences in this Stage 1B.\n"
        "Your JSON output for THIS Stage 1B request MUST ONLY contain data for the fields defined in the 'NetworkDeviceDataStage1BOutput' schema: "
        "'moonid_associations', 'discovered_unassigned_networks', and 'items_for_review'.\n"
        "The 'items_for_review' for THIS stage should focus on issues related to these complex fields or any inconsistencies found when comparing your Stage 1B findings with the provided Stage 1A context.\n"
        "DO NOT repeat fields already generated in Stage 1A unless it's part of an 'item_for_review' detail."
    )
    llm_input_stage1b = (
        f"{DELIMITERS['stage_instruction_start']}\n"
        f"{stage1b_operational_instruction_text}\n"
        f"{DELIMITERS['stage_instruction_end']}\n\n"
        f"{prompt_stage1b_content.strip()}\n\n"
        f"{DELIMITERS['stage1a_output_start']}\n"
        f"{stage1a_output_context_str}\n"
        f"{DELIMITERS['stage1a_output_end']}\n\n"
        f"{device_data_for_llm.strip()}"
    )
    raw_response_text_stage1b = ""
    response_obj_stage1b = None

    try:
        config_for_stage1b = genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=NetworkDeviceDataStage1BOutput,
        )
        logger.info(
            f"    FUNC (SN {serial_number}): Sending to API for Stage 1B (Model: {MODEL_NAME}). Input size: ~{len(llm_input_stage1b)} chars."
        )
        response_obj_stage1b = client.models.generate_content(
            model=f"models/{MODEL_NAME}",
            contents=[llm_input_stage1b],
            config=config_for_stage1b,  # CORRECTED
        )
        raw_response_text_stage1b = response_obj_stage1b.text

        if response_obj_stage1b.parsed is not None and isinstance(
            response_obj_stage1b.parsed, NetworkDeviceDataStage1BOutput
        ):
            collected_data_stage1b_dict = response_obj_stage1b.parsed.model_dump()
        else:
            logger.warning(
                f"FUNC (SN {serial_number}): Stage 1B - SDK response.parsed was None or not NetworkDeviceDataStage1BOutput. Attempting json.loads from text."
            )
            if raw_response_text_stage1b:
                temp_dict = json.loads(raw_response_text_stage1b)
                NetworkDeviceDataStage1BOutput(**temp_dict)
                collected_data_stage1b_dict = temp_dict
            else:
                raise ValueError("Stage 1B response text is empty and parsed is None.")

        if not isinstance(collected_data_stage1b_dict, dict):
            logger.error(f"FUNC (SN {serial_number}): Stage 1B - Parsed JSON not dict.")
            _write_error_log_internal(
                output_dir,
                base_filename_for_error_log,
                "STAGE1B_NOT_DICT",
                serial_number,
                "Parsed JSON not dict for Stage 1B.",
                llm_input_stage1b[:3000],
                raw_response_text_stage1b,
                get_prompt_feedback_details(response_obj_stage1b),
            )
            return False
        combined_items_for_review.extend(
            collected_data_stage1b_dict.get("items_for_review", [])
        )
        logger.info(
            f"    FUNC (SN {serial_number}): SUCCESS - Received Stage 1B data. (Review items: {len(collected_data_stage1b_dict.get('items_for_review', []))})"
        )

    except genai_errors.APIError as api_err_stage1b:
        feedback_details = get_prompt_feedback_details(response_obj_stage1b)
        error_text = f"GEMINI_API_ERROR in Stage 1B: {api_err_stage1b}. Feedback: {feedback_details}"
        logger.error(f"  FUNC (SN {serial_number}): {error_text}")
        _write_error_log_internal(
            output_dir,
            base_filename_for_error_log,
            "STAGE1B_API_ERROR",
            serial_number,
            error_text,
            llm_input_stage1b[:3000],
            raw_response_text_stage1b,
            feedback_details,
        )
        return False
    except json.JSONDecodeError as jde_stage1b:
        error_text = f"JSONDecodeError in Stage 1B: {jde_stage1b}."
        logger.error(
            f"  FUNC (SN {serial_number}): {error_text} Raw: '{raw_response_text_stage1b[:500]}...'"
        )
        _write_error_log_internal(
            output_dir,
            base_filename_for_error_log,
            "STAGE1B_JSON_DECODE_ERROR",
            serial_number,
            error_text,
            llm_input_stage1b[:3000],
            raw_response_text_stage1b,
            get_prompt_feedback_details(response_obj_stage1b),
        )
        return False
    except ValidationError as ve_stage1b:
        error_text = f"Pydantic ValidationError in Stage 1B: {ve_stage1b}."
        logger.error(f"  FUNC (SN {serial_number}): {error_text}")
        _write_error_log_internal(
            output_dir,
            base_filename_for_error_log,
            "STAGE1B_PYDANTIC_VALIDATION_ERROR",
            serial_number,
            error_text,
            llm_input_stage1b[:3000],
            raw_response_text_stage1b,
            get_prompt_feedback_details(response_obj_stage1b),
        )
        return False
    except Exception as e_stage1b:
        error_text = (
            f"UNEXPECTED_ERROR in Stage 1B: {type(e_stage1b).__name__} - {e_stage1b}"
        )
        logger.exception(f"  FUNC (SN {serial_number}): {error_text}")
        _write_error_log_internal(
            output_dir,
            base_filename_for_error_log,
            "STAGE1B_UNEXPECTED_ERROR",
            serial_number,
            error_text,
            llm_input_stage1b[:3000],
            raw_response_text_stage1b,
            get_prompt_feedback_details(response_obj_stage1b),
        )
        return False

    if collected_data_stage1b_dict is None:
        logger.error(f"  FUNC (SN {serial_number}): Stage 1B data is None. Aborting.")
        return False

    # --- STAGE 2 (Iterative): Get ONLY mac_entries ---
    if not skip_mac_processing:
        logger.info(
            f"  FUNC (SN {serial_number}): Requesting Stage 2 (MAC entries in batches)..."
        )
        stage2_mac_collection_failed = False
        previously_sent_mac_addrs_set = set()
        mac_iteration = 0
        new_macs_last_batch = -1

        while mac_iteration < MAX_MAC_BATCH_ITERATIONS:
            mac_iteration += 1
            if previously_sent_mac_addrs_set:
                MAX_EXCLUDED_MACS_IN_PROMPT_DISPLAY = 100
                excluded_list_for_prompt = sorted(list(previously_sent_mac_addrs_set))
                if len(excluded_list_for_prompt) > MAX_EXCLUDED_MACS_IN_PROMPT_DISPLAY:
                    excluded_macs_prompt_str = "\n".join(
                        excluded_list_for_prompt[:MAX_EXCLUDED_MACS_IN_PROMPT_DISPLAY]
                    )
                    excluded_macs_prompt_str = f"PREVIOUSLY_PROCESSED_MACS_START (truncated, first {MAX_EXCLUDED_MACS_IN_PROMPT_DISPLAY} of {len(excluded_list_for_prompt)})\n{excluded_macs_prompt_str}\nPREVIOUSLY_PROCESSED_MACS_END"
                else:
                    excluded_macs_prompt_str = "\n".join(excluded_list_for_prompt)
                    excluded_macs_prompt_str = f"PREVIOUSLY_PROCESSED_MACS_START\n{excluded_macs_prompt_str}\nPREVIOUSLY_PROCESSED_MACS_END"
            else:
                excluded_macs_prompt_str = "PREVIOUSLY_PROCESSED_MACS_START\n(None yet)\nPREVIOUSLY_PROCESSED_MACS_END"

            stage2_operational_instruction_text = (
                "CRITICAL INSTRUCTION FOR THIS MAC BATCH REQUEST:\n"
                "Refer to the main prompt content (following this instruction block) for 'mac_entries' field details and relevant standardization rules.\n"
                f"Your JSON output MUST ONLY be a list of 'mac_entries' from the MAC address table, aiming for approximately {MAC_BATCH_TARGET_SIZE} new entries.\n"
                "DO NOT output any other fields (like 'items_for_review' or fields from Stage 1A/1B).\n"
                "IMPORTANT: To avoid duplicates, DO NOT include any MAC entries whose 'mac_address' value is listed between "
                "PREVIOUSLY_PROCESSED_MACS_START and PREVIOUSLY_PROCESSED_MACS_END below.\n"
                f"{excluded_macs_prompt_str}\n"
                "If there are NO MORE NEW MAC entries to send, output an EMPTY JSON LIST: []."
            )
            llm_input_stage2 = (
                f"{DELIMITERS['stage_instruction_start']}\n"
                f"{stage2_operational_instruction_text}\n"
                f"{DELIMITERS['stage_instruction_end']}\n\n"
                f"{prompt_stage2_mac_content.strip()}\n\n"
                f"{device_data_for_llm.strip()}"
            )
            raw_response_text_stage2 = ""
            response_obj_stage2 = None
            current_batch_mac_list: Optional[List[Dict]] = None

            try:
                config_for_stage2 = genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=MacEntryList,
                )
                logger.info(
                    f"      FUNC (SN {serial_number}): Sending to API for MAC Batch #{mac_iteration} (Model: {MODEL_NAME}). Input size: ~{len(llm_input_stage2)} chars."
                )
                response_obj_stage2 = client.models.generate_content(
                    model=f"models/{MODEL_NAME}",
                    contents=[llm_input_stage2],
                    config=config_for_stage2,  # CORRECTED
                )
                raw_response_text_stage2 = response_obj_stage2.text

                if response_obj_stage2.parsed is not None and isinstance(
                    response_obj_stage2.parsed, MacEntryList
                ):
                    current_batch_mac_list = [
                        entry.model_dump() for entry in response_obj_stage2.parsed.root
                    ]
                else:
                    logger.warning(
                        f"FUNC (SN {serial_number}): MAC Batch #{mac_iteration} - SDK response.parsed was None or not MacEntryList. Attempting json.loads from text."
                    )
                    if raw_response_text_stage2:
                        loaded_data_stage2 = json.loads(raw_response_text_stage2)
                        if isinstance(loaded_data_stage2, list):
                            valid_entries = []
                            for item_dict in loaded_data_stage2:
                                try:
                                    MacEntry(**item_dict)
                                    valid_entries.append(item_dict)
                                except ValidationError:
                                    logger.warning(
                                        f"Invalid MAC entry in batch {mac_iteration} from raw JSON: {item_dict}"
                                    )
                            current_batch_mac_list = valid_entries
                        elif (
                            isinstance(loaded_data_stage2, dict)
                            and "root" in loaded_data_stage2
                            and isinstance(loaded_data_stage2["root"], list)
                        ):
                            valid_entries = []
                            for item_dict in loaded_data_stage2["root"]:
                                try:
                                    MacEntry(**item_dict)
                                    valid_entries.append(item_dict)
                                except ValidationError:
                                    logger.warning(
                                        f"Invalid MAC entry in batch {mac_iteration} (root) from raw JSON: {item_dict}"
                                    )
                            current_batch_mac_list = valid_entries
                        else:
                            raise ValueError(
                                f"MAC Batch #{mac_iteration} - Raw JSON was not a list or valid RootModel structure."
                            )
                    else:
                        raise ValueError(
                            f"MAC Batch #{mac_iteration} - Response text is empty and parsed is None."
                        )

                if not current_batch_mac_list:
                    logger.info(
                        f"    FUNC (SN {serial_number}): SUCCESS - Empty list for MAC Batch #{mac_iteration}. All MACs collected."
                    )
                    new_macs_last_batch = 0
                    break

                logger.info(
                    f"    FUNC (SN {serial_number}): SUCCESS - Received {len(current_batch_mac_list)} MACs in Batch #{mac_iteration}."
                )
                new_macs_this_batch_count = 0
                for mac_entry_dict in current_batch_mac_list:
                    if not isinstance(mac_entry_dict, dict):
                        logger.warning(
                            f"      SN {serial_number}: MAC Batch #{mac_iteration} - Non-dict item: {mac_entry_dict}"
                        )
                        continue
                    mac_addr = mac_entry_dict.get("mac_address")
                    if mac_addr and mac_addr not in previously_sent_mac_addrs_set:
                        try:
                            MacEntry(**mac_entry_dict)
                            all_collected_mac_entries.append(mac_entry_dict)
                            previously_sent_mac_addrs_set.add(mac_addr)
                            new_macs_this_batch_count += 1
                        except ValidationError as ve_mac_item:
                            logger.warning(
                                f"      SN {serial_number}: MAC Batch #{mac_iteration} - Invalid MAC entry dict: {mac_entry_dict}. Err: {ve_mac_item}"
                            )
                    elif mac_addr in previously_sent_mac_addrs_set:
                        logger.debug(
                            f"      SN {serial_number}: Duplicate MAC {mac_addr} in batch {mac_iteration}."
                        )
                    elif not mac_addr:
                        logger.warning(
                            f"      SN {serial_number}: MAC entry in batch {mac_iteration} missing 'mac_address': {mac_entry_dict}"
                        )

                new_macs_last_batch = new_macs_this_batch_count
                logger.info(
                    f"      FUNC (SN {serial_number}): Added {new_macs_this_batch_count} new unique MACs. Total unique: {len(previously_sent_mac_addrs_set)}."
                )

                if new_macs_this_batch_count == 0 and len(current_batch_mac_list) > 0:
                    logger.warning(
                        f"    SN {serial_number}: MAC Batch #{mac_iteration} returned {len(current_batch_mac_list)} MACs, but all were duplicates/invalid. Assuming end of MACs."
                    )
                    break
                if (
                    MAC_BATCH_DELAY_SECONDS > 0
                    and mac_iteration < MAX_MAC_BATCH_ITERATIONS
                    and current_batch_mac_list
                ):
                    time.sleep(MAC_BATCH_DELAY_SECONDS)

            except genai_errors.APIError as api_err_stage2:
                feedback_details = get_prompt_feedback_details(response_obj_stage2)
                error_text = f"GEMINI_API_ERROR in MAC Batch #{mac_iteration}: {api_err_stage2}. Feedback: {feedback_details}"
                logger.error(f"  FUNC (SN {serial_number}): {error_text}")
                _write_error_log_internal(
                    output_dir,
                    base_filename_for_error_log,
                    f"MAC_BATCH_{mac_iteration}_API_ERROR",
                    serial_number,
                    error_text,
                    llm_input_stage2[:2000],
                    raw_response_text_stage2,
                    feedback_details,
                )
                stage2_mac_collection_failed = True
                break
            except json.JSONDecodeError as jde_stage2:
                error_text = (
                    f"JSONDecodeError in MAC Batch #{mac_iteration}: {jde_stage2}."
                )
                logger.error(
                    f"  FUNC (SN {serial_number}): {error_text} Raw: '{raw_response_text_stage2[:500]}...'"
                )
                _write_error_log_internal(
                    output_dir,
                    base_filename_for_error_log,
                    f"MAC_BATCH_{mac_iteration}_JSON_DECODE_ERR",
                    serial_number,
                    error_text,
                    llm_input_stage2[:2000],
                    raw_response_text_stage2,
                    get_prompt_feedback_details(response_obj_stage2),
                )
                stage2_mac_collection_failed = True
                break
            except ValidationError as ve_stage2:
                error_text = f"Pydantic ValidationError in MAC Batch #{mac_iteration}: {ve_stage2}."
                logger.error(f"  FUNC (SN {serial_number}): {error_text}")
                _write_error_log_internal(
                    output_dir,
                    base_filename_for_error_log,
                    f"MAC_BATCH_{mac_iteration}_PYDANTIC_VALIDATION_ERROR",
                    serial_number,
                    error_text,
                    llm_input_stage2[:2000],
                    raw_response_text_stage2,
                    get_prompt_feedback_details(response_obj_stage2),
                )
                stage2_mac_collection_failed = True
                break
            except Exception as e_stage2:
                error_text = f"UNEXPECTED_ERROR in MAC Batch #{mac_iteration}: {type(e_stage2).__name__} - {e_stage2}"
                logger.exception(f"  FUNC (SN {serial_number}): {error_text}")
                _write_error_log_internal(
                    output_dir,
                    base_filename_for_error_log,
                    f"MAC_BATCH_{mac_iteration}_UNEXPECTED_ERR",
                    serial_number,
                    error_text,
                    llm_input_stage2[:2000],
                    raw_response_text_stage2,
                    get_prompt_feedback_details(response_obj_stage2),
                )
                stage2_mac_collection_failed = True
                break

        if stage2_mac_collection_failed:
            logger.error(
                f"  FUNC (SN {serial_number}): MAC collection (Stage 2) failed. Aborting for this SN."
            )
            return False
        if mac_iteration >= MAX_MAC_BATCH_ITERATIONS and new_macs_last_batch > 0:
            logger.warning(
                f"  FUNC (SN {serial_number}): Reached MAX_MAC_BATCH_ITERATIONS ({MAX_MAC_BATCH_ITERATIONS}) and last batch still added {new_macs_last_batch} new MACs. MAC table may be incomplete."
            )
        logger.info(
            f"  FUNC (SN {serial_number}): Finished Stage 2 (MACs). Total unique MAC entries collected: {len(all_collected_mac_entries)}"
        )
    else:
        logger.info(
            f"  FUNC (SN {serial_number}): SKIPPING Stage 2 (MAC entries) as per configuration."
        )
        # Create a review item to document this
        skip_review_item = {
            "severity": "Low",
            "item_path": "mac_entries",
            "reason": "Processing Skipped",
            "details": "MAC address table processing was intentionally skipped by user configuration.",
        }
        combined_items_for_review.append(ItemForReview(**skip_review_item).model_dump())
        all_collected_mac_entries = []

    # --- Combine and Validate Final Data ---
    if collected_data_stage1a_dict is None or collected_data_stage1b_dict is None:
        logger.critical(
            f"  FUNC (SN {serial_number}): CRITICAL - Stage 1A or Stage 1B data became None. Cannot assemble final data."
        )
        return False

    final_data_to_validate: Dict = {}
    for key, value in collected_data_stage1a_dict.items():
        if key != "items_for_review":
            final_data_to_validate[key] = value
    for key, value in collected_data_stage1b_dict.items():
        if key != "items_for_review":
            final_data_to_validate[key] = value

    final_data_to_validate["items_for_review"] = combined_items_for_review
    final_data_to_validate["mac_entries"] = all_collected_mac_entries

    if "switch_details" in final_data_to_validate and isinstance(
        final_data_to_validate["switch_details"], dict
    ):
        final_data_to_validate["switch_details"]["log_filename_validated"] = (
            f"{serial_number}-WAVE1.txt"
        )
        final_data_to_validate["switch_details"]["serial_number"] = serial_number
    else:
        logger.error(
            f"  FUNC (SN {serial_number}): 'switch_details' missing or invalid. Cannot finalize."
        )
        _write_error_log_internal(
            output_dir,
            base_filename_for_error_log,
            "FINAL_ASSEMBLY_NO_SWITCH_DETAILS",
            serial_number,
            "Switch details missing/invalid.",
            str(final_data_to_validate)[:2000],
        )
        return False

    try:
        logger.info(
            f"  FUNC (SN {serial_number}): Assembling and validating full data structure (Total review items: {len(combined_items_for_review)})..."
        )
        final_validated_data_model = NetworkDeviceData(**final_data_to_validate)
        final_json_output_string = final_validated_data_model.model_dump_json(indent=4)

        with open(final_json_filepath, "w", encoding="utf-8") as f_out:
            f_out.write(final_json_output_string)
        logger.info(
            f"  FUNC (SN {serial_number}): SUCCESS - Saved fully combined and validated JSON to: {final_json_filepath}"
        )
        return True
    except ValidationError as ve_final:
        error_text = f"Pydantic ValidationError during final assembly: {ve_final}"
        logger.error(f"  FUNC (SN {serial_number}): {error_text}")
        problematic_final_dict_path = os.path.join(
            output_dir,
            f"ERROR_{base_filename_for_error_log}_FINAL_VALIDATION_DICT.json",
        )
        try:
            with open(problematic_final_dict_path, "w", encoding="utf-8") as pf_dict:
                json.dump(final_data_to_validate, pf_dict, indent=4)
            logger.info(
                f"    Problematic final dictionary saved to {problematic_final_dict_path}"
            )
        except Exception as e_save_problem_dict:
            logger.error(
                f"    Could not save problematic final dictionary: {e_save_problem_dict}"
            )
        _write_error_log_internal(
            output_dir,
            base_filename_for_error_log,
            "FINAL_VALIDATION_ERROR",
            serial_number,
            error_text,
        )
        return False
    except Exception as e_combine:
        error_text = f"UNEXPECTED_ERROR during final assembly/save: {type(e_combine).__name__} - {e_combine}"
        logger.exception(f"  FUNC (SN {serial_number}): {error_text}")
        _write_error_log_internal(
            output_dir,
            base_filename_for_error_log,
            "FINAL_ASSEMBLY_UNEXPECTED_ERROR",
            serial_number,
            error_text,
        )
        return False


# --- Standalone Execution (for testing gemini.py directly) ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Process a single LLM input package file using Gemini API (Multi-Stage Prompts with new google-genai SDK)."
    )
    parser.add_argument(
        "input_device_data_file", help="Path to the '<SN>_llm_input_package.txt'."
    )
    parser.add_argument(
        "output_dir", help="Directory to save the final '<SN>_validated.json'."
    )
    parser.add_argument("--sn", help="Serial Number (if not derivable from filename).")
    parser.add_argument(
        "--prompt1a", default="llm_prompt_stage1a.txt", help="Stage 1A prompt file."
    )
    parser.add_argument(
        "--prompt1b", default="llm_prompt_stage1b.txt", help="Stage 1B prompt file."
    )
    parser.add_argument(
        "--prompt2mac",
        default="llm_prompt_stage2_mac.txt",
        help="Stage 2 (MAC) prompt file.",
    )
    parser.add_argument(
        "--skip-macs",
        action="store_true",
        help="If set, skips the Stage 2 MAC address table processing.",
    )
    args = parser.parse_args()

    logger.info(
        f"--- Gemini API Processor (google-genai SDK) - Standalone (Model: {MODEL_NAME}) ---"
    )
    logger.info(
        "Gemini API key loaded from environment (GEMINI_API_KEY)."
        if API_KEY else
        "GEMINI_API_KEY is not set - set it before making API calls."
    )

    try:
        import pydantic

        logger.info(f"Pydantic version: {pydantic.__version__}")
    except ImportError:
        logger.error("FATAL: Pydantic not installed.")
        sys.exit(1)

    if not os.path.isfile(args.input_device_data_file):
        logger.error(
            f"FATAL: Input device data file not found: {args.input_device_data_file}"
        )
        sys.exit(1)

    try:
        with open(args.prompt1a, "r", encoding="utf-8") as f:
            p1a_c = f.read()
        with open(args.prompt1b, "r", encoding="utf-8") as f:
            p1b_c = f.read()
        with open(args.prompt2mac, "r", encoding="utf-8") as f:
            p2m_c = f.read()
        if not all([p1a_c, p1b_c, p2m_c]):
            logger.error("FATAL: One or more prompt files are empty.")
            sys.exit(1)
        logger.info(
            f"Loaded prompts: {args.prompt1a}, {args.prompt1b}, {args.prompt2mac}"
        )
    except Exception as e_prompts:
        logger.error(f"FATAL: Error reading prompt files: {e_prompts}")
        sys.exit(1)

    sn_to_use = args.sn or _extract_sn_from_package_filename(
        args.input_device_data_file
    )
    if not sn_to_use:
        sn_in = input("Could not derive SN. Enter Serial Number: ").strip().upper()
        if not sn_in:
            logger.error("FATAL: SN not provided.")
            sys.exit(1)
        sn_to_use = sn_in
    logger.info(f"Target SN for processing: {sn_to_use}")
    os.makedirs(args.output_dir, exist_ok=True)

    success = False
    try:
        success = process_llm_package_file_to_json(
            args.input_device_data_file,
            sn_to_use,
            args.output_dir,
            p1a_c,
            p1b_c,
            p2m_c,
            skip_mac_processing=args.skip_macs,
        )
    except Exception as e_main:
        logger.error(f"FATAL: Unhandled exception in main processing: {e_main}")
        logger.error(traceback.format_exc())
        success = False

    if success:
        logger.info(
            f"OK. Successfully processed SN {sn_to_use}. Output in '{args.output_dir}'."
        )
        sys.exit(0)
    else:
        logger.error(
            f"FAIL. Error processing SN {sn_to_use}. Check logs in '{args.output_dir}'."
        )
        sys.exit(1)
