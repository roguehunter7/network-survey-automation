# diagram_graph_builder.py
"""
Functions for building the initial NetworkX graph from database data.
Includes loading switches, APs, and processing LLDP/CDP neighbors.
Node IDs in the NetworkX graph (G) for managed switches & APs are often their raw_ids (e.g., serial numbers).
External node IDs in G are sanitized.
"""

import sqlite3
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx

from netsurvey.topology.diagram_config_utils import (
    MAX_AP_PORT_INDEX_TO_CHECK,
    NODE_STYLE_MAP,  # For diagram_class setting in unmanaged devices
    format_mac_to_standard,
    is_potentially_mac,
    sanitize_node_id_for_pydot,
    shorten_interface_name,
)

# --- Constants for "ALL" selections (Must match network_diagram_generator.py) ---
ALL_AREAS_MARKER = "__ALL_AREAS_ON_FLOOR__"


# --- Core Graph Node and Edge Manipulation Helpers (Defined FIRST) ---


def add_or_update_node_in_graph(
    G: nx.Graph,
    node_id_in_graph: str,
    attributes: Dict[str, Any],
    target_site: Optional[str] = None,
    target_building: Optional[str] = None,
    target_floor: Optional[str] = None,
    target_area_name: Optional[str] = None,  # Can be ALL_AREAS_MARKER
    force_in_scope_as_fas: bool = False,
):
    if "raw_id" not in attributes:
        # For external nodes, node_id_in_graph is sanitized Pydot ID
        # For unmanaged_switch_special_mode, raw_id will be like 'other_dev_dbid_X'
        attributes["raw_id"] = node_id_in_graph

    is_new_node = not G.has_node(node_id_in_graph)

    node_origin = attributes.get("node_origin")
    device_type = attributes.get("device_type")  # From 'switches' table
    surveyed_device_type = attributes.get(
        "device_type_surveyed"
    )  # From 'logged_other_devices'

    # diagram_class might be pre-set by the loading function (e.g., for unmanaged devices)
    determined_diagram_class = attributes.get("diagram_class")

    # Determine diagram_class if not already set, or if it's an existing node being updated
    if determined_diagram_class is None or not is_new_node:
        if node_origin == "managed_switch":
            is_in_scope = False
            # If this node is already in the graph, check if it was marked as a designated FAS.
            # If so, it should ALWAYS be considered in-scope for this diagram run.
            is_already_designated_fas_in_graph = False
            if not is_new_node:
                is_already_designated_fas_in_graph = G.nodes[node_id_in_graph].get(
                    "is_fas_for_unmanaged_area_diagram", False
                )

            if force_in_scope_as_fas or is_already_designated_fas_in_graph:
                is_in_scope = True
            elif all(
                [target_site, target_building, target_floor]
            ):  # Must have all target location parts
                is_in_scope = (
                    str(attributes.get("site", "")).upper() == str(target_site).upper()
                    and str(attributes.get("building", "")).upper()
                    == str(target_building).upper()
                    and str(attributes.get("floor", "")).upper()
                    == str(target_floor).upper()
                )
                if (  # If a specific area is targeted (not ALL_AREAS_MARKER)
                    target_area_name != ALL_AREAS_MARKER
                    and target_area_name is not None
                ):
                    is_in_scope = (
                        is_in_scope
                        and str(attributes.get("lab_area_name", "")).upper()
                        == str(target_area_name).upper()
                    )

            if device_type == "Router":  # From 'switches' table
                determined_diagram_class = (
                    "router_in_scope" if is_in_scope else "router_out_of_scope"
                )
            else:  # Assumed Switch if not Router from 'switches' table
                determined_diagram_class = (
                    "managed_in_scope" if is_in_scope else "managed_out_of_scope"
                )

        elif node_origin == "unmanaged_switch_special_mode":
            # The diagram_class for these should be set by load_unmanaged_switches_for_area
            # based on status_reason or device_type_surveyed.
            # If it's somehow None here, use a fallback.
            if determined_diagram_class is None:
                # Check if 'unmanaged_switch_in_scope' is a valid key in NODE_STYLE_MAP
                # This key is used in diagram_config_utils.py
                if "unmanaged_switch_in_scope" in NODE_STYLE_MAP:
                    determined_diagram_class = "unmanaged_switch_in_scope"
                else:  # Fallback if the style key itself is missing
                    determined_diagram_class = "external"  # A generic fallback style
            # The actual styling (color, shape) comes from NODE_STYLE_MAP using this class.

        elif node_origin == "access_point":
            is_in_scope_ap = False
            if all([target_site, target_building, target_floor]):
                is_in_scope_ap = (
                    str(attributes.get("site", "")).upper() == str(target_site).upper()
                    and str(attributes.get("building", "")).upper()
                    == str(target_building).upper()
                    and str(attributes.get("floor", "")).upper()
                    == str(target_floor).upper()
                )
                if (
                    target_area_name != ALL_AREAS_MARKER
                    and target_area_name is not None
                ):
                    is_in_scope_ap = (
                        is_in_scope_ap
                        and str(attributes.get("lab_area_name", "")).upper()
                        == str(target_area_name).upper()
                    )
            determined_diagram_class = (
                "ap_in_scope" if is_in_scope_ap else "ap_out_of_scope"
            )
        elif node_origin == "external_lldp_neighbor":
            if determined_diagram_class is None:  # Only set if not already determined
                determined_diagram_class = (
                    "unsurveyed_network_device"  # Grey box, dashed
                    if attributes.get("is_potential_network_device")
                    else "external"  # Orange ellipse
                )
        elif determined_diagram_class is None:  # Fallback for any other unknown origin
            # Needs a style in NODE_STYLE_MAP or will use Pydot defaults
            determined_diagram_class = "unknown_origin_class"

    attributes["diagram_class"] = determined_diagram_class

    if is_new_node:
        G.add_node(node_id_in_graph, **attributes)
    else:  # Update existing node
        for key, value in attributes.items():
            if key == "diagram_class":  # Always update diagram_class if provided
                G.nodes[node_id_in_graph][key] = value
            elif value is not None:  # Overwrite with new non-None values
                G.nodes[node_id_in_graph][key] = value
            elif (
                key not in G.nodes[node_id_in_graph]
                # Add if key is new and value is None (to ensure all attrs exist)
            ):
                G.nodes[node_id_in_graph][key] = value
        # Ensure diagram_class is set if it was part of incoming attributes, even if it was None and re-determined
        if "diagram_class" in attributes:
            G.nodes[node_id_in_graph]["diagram_class"] = attributes["diagram_class"]


def resolve_lldp_cdp_remote_node(
    conn: sqlite3.Connection,
    remote_device_id_raw: str,
    remote_system_name_raw: Optional[str],
    remote_mgmt_address_raw: Optional[str],
    remote_model_raw: Optional[str],
    external_node_cache: Dict[
        Tuple[str, str], str
    ],  # Cache: (identifier_type, identifier_value) -> graph_node_id
    G: nx.Graph,
    target_site: str,
    target_building: str,
    target_floor: str,
    target_area_name: str,
) -> Optional[str]:
    db_cursor = conn.cursor()

    # Normalize remote_system_name for consistent matching
    remote_system_name_raw_stripped_upper: Optional[str] = None
    remote_system_name_short_upper: Optional[str] = None
    if remote_system_name_raw:
        remote_system_name_raw_stripped_upper = remote_system_name_raw.strip().upper()
        remote_system_name_short_upper = remote_system_name_raw_stripped_upper.split(
            "."
        )[0]

    # --- Stage 1: Try to resolve as an existing *managed switch* in G or DB ---
    # Check G first (nodes already loaded)
    for node_id_g, node_data_g in G.nodes(data=True):
        if node_data_g.get("node_origin") == "managed_switch":
            # Direct match on raw_id (typically serial number)
            current_raw_id = node_data_g.get("raw_id")
            if current_raw_id and current_raw_id == remote_device_id_raw:
                # Update its scope if necessary (it might have been out-of-scope initially)
                add_or_update_node_in_graph(
                    G,
                    node_id_g,  # Use existing graph node ID
                    node_data_g.copy(),  # Pass existing attributes
                    target_site,
                    target_building,
                    target_floor,
                    target_area_name,
                )
                return node_id_g  # Return existing graph node ID

            # Match on base_mac_address if remote_device_id is a MAC
            std_mac_remote = (
                format_mac_to_standard(remote_device_id_raw)
                if is_potentially_mac(remote_device_id_raw)
                else None
            )
            if std_mac_remote and node_data_g.get("base_mac_address") == std_mac_remote:
                add_or_update_node_in_graph(
                    G,
                    node_id_g,
                    node_data_g.copy(),
                    target_site,
                    target_building,
                    target_floor,
                    target_area_name,
                )
                return node_id_g

            # Enhanced Hostname Match (in-graph): Compare short versions of hostnames
            if remote_system_name_short_upper:
                graph_node_hostname = node_data_g.get("hostname", "").strip().upper()
                if graph_node_hostname:
                    graph_node_hostname_short = graph_node_hostname.split(".")[0]
                    if graph_node_hostname_short == remote_system_name_short_upper:
                        add_or_update_node_in_graph(
                            G,
                            node_id_g,
                            node_data_g.copy(),
                            target_site,
                            target_building,
                            target_floor,
                            target_area_name,
                        )
                        return node_id_g

    # If not in G, check DB for managed switch
    possible_db_identifiers = []
    if remote_device_id_raw:  # Raw device ID might be SN or MAC
        possible_db_identifiers.append(("serial_number", remote_device_id_raw))

    if remote_system_name_raw:  # Use original case for DB hostname lookup
        remote_name_original_case_stripped = remote_system_name_raw.strip()
        possible_db_identifiers.append(("hostname", remote_name_original_case_stripped))
        if (
            "." in remote_name_original_case_stripped
        ):  # Also try short hostname if different
            remote_name_original_case_short = remote_name_original_case_stripped.split(
                "."
            )[0]
            if (
                remote_name_original_case_short
                and remote_name_original_case_short.lower()
                != remote_name_original_case_stripped.lower()
            ):
                possible_db_identifiers.append(
                    ("hostname", remote_name_original_case_short)
                )

    std_mac_remote_db = (  # Standardized MAC from remote_device_id for base_mac_address lookup
        format_mac_to_standard(remote_device_id_raw)
        if is_potentially_mac(remote_device_id_raw)
        else None
    )
    if std_mac_remote_db:
        possible_db_identifiers.append(("base_mac_address", std_mac_remote_db))

    # Deduplicate identifiers for DB query
    unique_possible_db_identifiers = []
    seen_db_ids_for_query = set()  # (field_type, value_lower_if_hostname_else_value)
    for field_check, value_check in possible_db_identifiers:
        seen_key_tuple = (
            (field_check, str(value_check).lower())
            if field_check == "hostname"
            else (field_check, value_check)
        )
        if seen_key_tuple not in seen_db_ids_for_query:
            unique_possible_db_identifiers.append((field_check, value_check))
            seen_db_ids_for_query.add(seen_key_tuple)

    for field, value in unique_possible_db_identifiers:
        if not value:
            continue  # Skip empty values
        # Basic validation for serial_number length if that's the field
        if field == "serial_number" and not (value and 5 < len(str(value)) < 40):
            continue

        db_cursor.execute(f"SELECT * FROM switches WHERE {field} = ?", (value,))
        db_row = db_cursor.fetchone()
        if db_row:
            switch_data_from_db = dict(db_row)
            managed_switch_raw_id_db = str(
                switch_data_from_db["serial_number"]
            )  # Use SN as graph ID
            attrs_db = {
                **switch_data_from_db,
                "node_origin": "managed_switch",
                "raw_id": managed_switch_raw_id_db,
            }
            add_or_update_node_in_graph(
                G,
                managed_switch_raw_id_db,
                attrs_db,
                target_site,
                target_building,
                target_floor,
                target_area_name,
            )
            return managed_switch_raw_id_db

    # Try resolving by management IP address from DB
    if remote_mgmt_address_raw:
        addr_no_prefix_db = remote_mgmt_address_raw.split("/")[
            0
        ]  # Remove CIDR if present
        db_cursor.execute(
            "SELECT s.* FROM switches s JOIN ip_interfaces i ON s.serial_number=i.switch_serial_number "
            "WHERE i.ip_address_with_prefix LIKE ? OR i.ip_address_with_prefix = ? OR i.ip_address_with_prefix LIKE ? LIMIT 1",
            (
                remote_mgmt_address_raw + "%",
                remote_mgmt_address_raw,
                addr_no_prefix_db + "%",
            ),  # Try with and without prefix matching
        )
        db_row_ip = db_cursor.fetchone()
        if db_row_ip:
            switch_data_ip_db = dict(db_row_ip)
            managed_switch_raw_id_ip_db = str(switch_data_ip_db["serial_number"])
            attrs_ip_db = {
                **switch_data_ip_db,
                "node_origin": "managed_switch",
                "raw_id": managed_switch_raw_id_ip_db,
            }
            add_or_update_node_in_graph(
                G,
                managed_switch_raw_id_ip_db,
                attrs_ip_db,
                target_site,
                target_building,
                target_floor,
                target_area_name,
            )
            return managed_switch_raw_id_ip_db

    # --- Stage 2: Handle as an *external (unsurveyed)* node ---
    # Normalize identifiers for cache lookup and node ID generation
    norm_device_id = (
        str(remote_device_id_raw).strip().upper() if remote_device_id_raw else None
    )
    std_mac_as_device_id = (
        format_mac_to_standard(remote_device_id_raw)
        if is_potentially_mac(remote_device_id_raw)
        else None
    )
    # norm_system_name is remote_system_name_raw_stripped_upper (already defined)
    norm_mgmt_ip = (
        remote_mgmt_address_raw.split("/")[0].strip().upper()
        if remote_mgmt_address_raw
        else None
    )

    # Build a prioritized list of keys to check in the cache or use for new ID
    lookup_keys_to_try: List[Tuple[str, str]] = []  # (key_type, key_value)
    # To avoid duplicates in lookup_keys_to_try
    _added_keys_values_for_lookup = set()

    def _add_key_to_lookup_list(key_type, key_val):
        if key_val and (key_type, key_val) not in _added_keys_values_for_lookup:
            lookup_keys_to_try.append((key_type, key_val))
            _added_keys_values_for_lookup.add((key_type, key_val))

    # Highest priority: System Name + Mgmt IP (if both exist)
    if remote_system_name_raw_stripped_upper and norm_mgmt_ip:
        _add_key_to_lookup_list(
            "system_name_plus_mgmt_ip",
            f"{remote_system_name_raw_stripped_upper}::{norm_mgmt_ip}",
        )
    # System Name (if not just a MAC address string)
    if remote_system_name_raw_stripped_upper:
        # Avoid using system name if it's just the MAC address itself (without colons)
        if not std_mac_as_device_id or (
            std_mac_as_device_id
            and remote_system_name_raw_stripped_upper
            != std_mac_as_device_id.replace(":", "")
        ):
            _add_key_to_lookup_list(
                "system_name", remote_system_name_raw_stripped_upper
            )
    # Standardized MAC as Device ID
    if std_mac_as_device_id:
        _add_key_to_lookup_list("standardized_mac_device_id", std_mac_as_device_id)
    # Management IP
    if norm_mgmt_ip:
        _add_key_to_lookup_list("mgmt_ip", norm_mgmt_ip)
    # Raw Device ID (if not already covered by standardized MAC)
    if norm_device_id:
        is_std_mac_format = (
            std_mac_as_device_id and norm_device_id == std_mac_as_device_id
        )
        if not is_std_mac_format:  # Don't add raw_device_id if it's identical to the standardized MAC already added
            _add_key_to_lookup_list("raw_device_id", norm_device_id)

    # Check cache for existing external node ID
    existing_node_id_from_cache: Optional[str] = None
    for key_type, key_val in lookup_keys_to_try:
        cache_tuple = (key_type, key_val)
        if cache_tuple in external_node_cache:
            cached_id = external_node_cache[cache_tuple]
            # Ensure cached node still exists and is an external neighbor (could have been promoted)
            if (
                G.has_node(cached_id)
                and G.nodes[cached_id].get("node_origin") == "external_lldp_neighbor"
            ):
                existing_node_id_from_cache = cached_id
                break
            else:  # Cache entry is stale or node was promoted
                del external_node_cache[cache_tuple]

    if existing_node_id_from_cache:
        # Update existing external node's attributes with any new info
        existing_node_data = G.nodes[existing_node_id_from_cache].copy()
        if remote_system_name_raw and not existing_node_data.get(
            "remote_name_reported"
        ):
            existing_node_data["remote_name_reported"] = remote_system_name_raw
        if remote_mgmt_address_raw and not existing_node_data.get(
            "remote_mgmt_address_reported"
        ):
            existing_node_data["remote_mgmt_address_reported"] = remote_mgmt_address_raw
        if remote_model_raw and (
            not existing_node_data.get("remote_model_reported")
            or (
                existing_node_data.get("remote_model_reported")
                and len(remote_model_raw)
                > len(str(existing_node_data.get("remote_model_reported")))
            )
        ):  # Prefer longer model string
            existing_node_data["remote_model_reported"] = remote_model_raw

        # Logic to update raw_id if a better one (e.g. MAC over placeholder) is found
        existing_raw_id_on_node = existing_node_data.get("raw_id")
        current_is_mac = std_mac_as_device_id is not None
        existing_is_mac = is_potentially_mac(str(existing_raw_id_on_node))
        existing_is_placeholder = (
            existing_raw_id_on_node and "ext_" in str(existing_raw_id_on_node).lower()
        )

        if remote_device_id_raw:  # If current LLDP provides a device ID
            if not existing_raw_id_on_node:  # If node had no raw_id
                existing_node_data["raw_id"] = remote_device_id_raw
            elif current_is_mac and not existing_is_mac:  # Prefer MAC over non-MAC
                existing_node_data["raw_id"] = remote_device_id_raw
            elif (
                existing_is_placeholder and "ext_" not in remote_device_id_raw.lower()
            ):  # Prefer non-placeholder
                existing_node_data["raw_id"] = remote_device_id_raw
            elif (
                current_is_mac
                and existing_is_mac
                and remote_device_id_raw == std_mac_as_device_id
            ):  # Prefer standardized MAC form
                existing_node_data["raw_id"] = remote_device_id_raw

        add_or_update_node_in_graph(
            G, existing_node_id_from_cache, existing_node_data
        )  # No target_* args for external
        # Update cache for all lookup keys to point to this unified ID
        for ct, cv in lookup_keys_to_try:
            external_node_cache[(ct, cv)] = existing_node_id_from_cache
        return existing_node_id_from_cache

    # If not in cache, create a new external node
    # Base name for sanitized ID generation (prefer name, then MAC, then IP, then raw ID)
    base_name_for_ext_id = (
        remote_system_name_raw_stripped_upper
        or std_mac_as_device_id
        or norm_mgmt_ip
        or norm_device_id
        or "unknown_external_device"
    )
    sanitized_base_ext_id = sanitize_node_id_for_pydot(f"ext_{base_name_for_ext_id}")

    # Ensure unique sanitized ID in the graph
    final_ext_node_sanitized_id = sanitized_base_ext_id
    id_counter = 0
    while G.has_node(final_ext_node_sanitized_id):
        id_counter += 1
        final_ext_node_sanitized_id = f"{sanitized_base_ext_id}_{id_counter}"

    # Add to cache with all its identifiers
    for ct, cv in lookup_keys_to_try:
        external_node_cache[(ct, cv)] = final_ext_node_sanitized_id

    # Determine if it's potentially a network device based on model/name keywords
    is_potential_net_dev_ext = False
    keywords_net_dev_list = [
        "switch",
        "router",
        "catalyst",
        "nexus",
        "arista",
        "juniper",
        "meraki",
        "ruckus",
        "firewall",
        "fortigate",
        "paloalto",
        "cisco",
        "ios",
        "nxos",
    ]
    if remote_model_raw and any(
        kw in remote_model_raw.lower() for kw in keywords_net_dev_list
    ):
        is_potential_net_dev_ext = True
    if (
        not is_potential_net_dev_ext
        and remote_system_name_raw
        and any(kw in remote_system_name_raw.lower() for kw in keywords_net_dev_list)
    ):
        is_potential_net_dev_ext = True

    ext_node_attributes = {
        "node_origin": "external_lldp_neighbor",
        "raw_id": remote_device_id_raw,  # Store the original remote_device_id
        "remote_name_reported": remote_system_name_raw,
        "remote_model_reported": remote_model_raw,
        "remote_mgmt_address_reported": remote_mgmt_address_raw,
        "is_potential_network_device": is_potential_net_dev_ext,
        # Default location attributes for external nodes
        "site": "External",
        "building": "External",
        "floor": "External",
        "lab_area_name": "External",
    }
    add_or_update_node_in_graph(G, final_ext_node_sanitized_id, ext_node_attributes)
    return final_ext_node_sanitized_id


# --- Graph Construction Functions ---


def load_single_managed_switch_by_sn(
    conn: sqlite3.Connection,
    G: nx.Graph,
    switch_serial_number: str,
    target_site: Optional[str] = None,
    target_building: Optional[str] = None,
    target_floor: Optional[str] = None,
    target_area_name: Optional[str] = None,
    is_designated_fas: bool = False,  # For special unmanaged area mode
) -> Optional[str]:
    """
    Loads a single managed switch by its serial number into the graph.
    Returns the graph node ID if successful, else None.
    """
    print(f"    Attempting to load single switch by SN: {switch_serial_number}")
    cursor = conn.cursor()
    sql_query_single_switch = "SELECT * FROM switches WHERE serial_number = ?;"
    cursor.execute(sql_query_single_switch, (switch_serial_number,))
    switch_row_data_db = cursor.fetchone()

    if switch_row_data_db:
        switch_data_from_db_load = dict(switch_row_data_db)
        # Graph node ID for managed switches is their serial number
        node_id_for_switch_in_G = str(switch_data_from_db_load["serial_number"])

        # Determine the 'in_scope' class for FAS, as it's always considered in scope for its diagram
        diagram_class_for_fas = "managed_in_scope"
        if switch_data_from_db_load.get("device_type") == "Router":
            diagram_class_for_fas = "router_in_scope"

        attributes_for_switch = {
            **switch_data_from_db_load,
            "node_origin": "managed_switch",
            "node_type_hint": switch_data_from_db_load.get("device_type", "Switch"),
            "raw_id": node_id_for_switch_in_G,
            "is_fas_for_unmanaged_area_diagram": is_designated_fas,  # Mark it as special FAS
        }

        # The add_or_update_node_in_graph function's force_in_scope_as_fas handles setting
        # the diagram_class to an 'in_scope' variant if is_designated_fas is True.
        add_or_update_node_in_graph(
            G,
            node_id_for_switch_in_G,
            attributes_for_switch,
            target_site=target_site,  # Pass target scope for context
            target_building=target_building,
            target_floor=target_floor,
            target_area_name=target_area_name,
            # This ensures it's treated as in-scope
            force_in_scope_as_fas=is_designated_fas,
        )

        # Explicitly set 'is_fas' and ensure correct diagram_class after node addition/update
        # This is somewhat redundant if force_in_scope_as_fas works as intended, but ensures consistency.
        if is_designated_fas and G.has_node(node_id_for_switch_in_G):
            G.nodes[node_id_for_switch_in_G]["diagram_class"] = diagram_class_for_fas
            # General FAS marker
            G.nodes[node_id_for_switch_in_G]["is_fas"] = True
            # Note: Its actual location attributes (site, building, floor, lab_area_name from DB) are preserved.
            # The force_in_scope_as_fas ensures it's *diagrammatically* in scope for this specific diagram.

        print(f"    Loaded designated FAS: {node_id_for_switch_in_G}")
        return node_id_for_switch_in_G
    else:
        print(
            f"    ERROR: Designated FAS with SN {switch_serial_number} not found in database."
        )
        return None


def load_unmanaged_switches_for_area(
    conn: sqlite3.Connection,
    G: nx.Graph,
    target_site: str,
    target_building: str,
    target_floor: str,
    target_area_name: str,
) -> List[str]:
    """
    Loads ALL devices from logged_other_devices for a specific scope.
    If target_area_name is ALL_AREAS_MARKER, loads for the entire floor.
    """
    cursor = conn.cursor()
    sql_params = [target_site, target_building, target_floor]

    if target_area_name == ALL_AREAS_MARKER:
        # Load all unmanaged devices on the floor
        sql_query_all_other_devices = """
            SELECT * FROM logged_other_devices
            WHERE site = ? AND building = ? AND floor = ?;
        """
        print(
            f"  Loading ALL devices from logged_other_devices for floor: {target_site}/{target_building}/{target_floor}..."
        )
    else:
        # Load devices for the specific lab area
        sql_query_all_other_devices = """
            SELECT * FROM logged_other_devices
            WHERE site = ? AND building = ? AND floor = ? AND lab_area_name = ?;
        """
        sql_params.append(target_area_name)
        print(
            f"  Loading ALL devices from logged_other_devices for area: {target_site}/{target_building}/{target_floor}/{target_area_name}..."
        )

    cursor.execute(sql_query_all_other_devices, tuple(sql_params))

    loaded_device_node_ids = []
    count = 0
    for row_data in cursor.fetchall():
        device_data = dict(row_data)
        # Use the primary key 'id' from logged_other_devices for a unique node ID
        node_id_for_device = f"other_dev_dbid_{device_data['id']}"

        current_status = device_data.get("status_reason", "").lower()
        device_type_surveyed = device_data.get("device_type_surveyed", "Device").lower()

        diagram_class_for_device = "external"  # Default style

        if (
            "unmanaged" in current_status
            or "hub" in current_status
            or "switch" in device_type_surveyed
        ):
            diagram_class_for_device = "unmanaged_switch_in_scope"
        elif "failed access" in current_status or "no response" in current_status:
            # Style for failed/unresponsive but potentially network gear
            diagram_class_for_device = "unsurveyed_network_device"

        attributes_for_device = {
            **device_data,
            "node_origin": "unmanaged_switch_special_mode",  # For clustering
            "raw_id": node_id_for_device,  # Graph's internal ID
            "diagram_class": diagram_class_for_device,  # Determined style class
            "node_type_hint": device_data.get("device_type_surveyed", "Device"),
            "site": device_data.get("site"),
            "building": device_data.get("building"),
            "floor": device_data.get("floor"),
            "lab_area_name": device_data.get("lab_area_name"),
        }
        add_or_update_node_in_graph(
            G,
            node_id_for_device,
            attributes_for_device,
            target_site,  # Pass target scope for context
            target_building,
            target_floor,
            target_area_name,
        )
        loaded_device_node_ids.append(node_id_for_device)
        count += 1

    print(
        f"    Loaded {count} devices from logged_other_devices for the specified scope."
    )
    return loaded_device_node_ids


def connect_unmanaged_switches_to_fas(
    conn: sqlite3.Connection,
    G: nx.Graph,
    fas_node_id: str,  # This is the graph node ID of the FAS
    unmanaged_device_node_ids: List[str],  # Changed name for clarity
):
    """
    Connects unmanaged/other devices (from logged_other_devices) to the FAS.
    Inference is based on ARP/MAC tables on the FAS using the device's observed_laptop_ip.
    """
    if not fas_node_id or not G.has_node(fas_node_id):
        print(
            "    Cannot connect unmanaged devices: FAS node ID invalid or not in graph."
        )
        return

    fas_attrs = G.nodes[fas_node_id]
    fas_sn = fas_attrs.get("raw_id")  # FAS raw_id is its serial number
    if not fas_sn:
        print(
            "    Cannot connect unmanaged devices: FAS serial number missing on graph node."
        )
        return

    print(
        f"  Attempting to connect {len(unmanaged_device_node_ids)} unmanaged/other devices to FAS ({fas_sn})..."
    )
    db_cursor = conn.cursor()
    edges_added = 0

    for unmanaged_node_id in unmanaged_device_node_ids:
        if not G.has_node(unmanaged_node_id):
            print(
                f"    Skipping connection for non-existent unmanaged node: {unmanaged_node_id}"
            )
            continue

        unmanaged_attrs = G.nodes[unmanaged_node_id]
        observed_ip = unmanaged_attrs.get(
            "observed_laptop_ip"
        )  # From logged_other_devices table
        link_established_by_arp_mac = False
        fas_port_for_link_raw = None  # Will store the FAS port if found

        if observed_ip:
            base_observed_ip = observed_ip.split("/")[0]  # Remove CIDR if any
            # Find MAC for this IP in FAS's ARP table
            db_cursor.execute(
                "SELECT mac_address FROM arp_table WHERE switch_serial_number = ? AND ip_address = ? LIMIT 1",
                (fas_sn, base_observed_ip),
            )
            arp_entry = db_cursor.fetchone()
            if arp_entry:
                mac_from_arp = arp_entry["mac_address"]
                mac_from_arp_std = format_mac_to_standard(mac_from_arp)
                if mac_from_arp_std:
                    # Find port for this MAC in FAS's MAC table
                    db_cursor.execute(
                        "SELECT interface_name FROM mac_address_table WHERE switch_serial_number = ? AND mac_address = ? AND type = 'DYNAMIC' LIMIT 1",
                        (fas_sn, mac_from_arp_std),
                    )
                    mac_table_entry = db_cursor.fetchone()
                    if mac_table_entry:
                        fas_port_for_link_raw = mac_table_entry["interface_name"]
                        fas_port_for_link_short = (
                            shorten_interface_name(fas_port_for_link_raw)
                            or fas_port_for_link_raw
                        )

                        # Determine u_temp, v_temp for canonical edge ordering
                        u_temp, v_temp = (
                            min(fas_node_id, unmanaged_node_id),
                            max(fas_node_id, unmanaged_node_id),
                        )
                        # Assign port to the correct side of the edge
                        port_on_u_side = (
                            fas_port_for_link_raw
                            if u_temp == fas_node_id
                            else None  # Unmanaged side port unknown
                        )
                        port_on_v_side = (
                            fas_port_for_link_raw
                            if v_temp == fas_node_id
                            else None  # Unmanaged side port unknown
                        )

                        edge_attrs = {
                            "connection_type": "unmanaged_inferred_uplink",
                            "detail": f"Inferred (IP: {base_observed_ip}, FAS Port: {fas_port_for_link_short})",
                            "u_port": port_on_u_side,
                            "v_port": port_on_v_side,
                            "style": "dashed",  # Pydot style attribute
                            "color": "#1E90FF",  # DodgerBlue
                            "penwidth": "1.0",
                            "style_attrs": {
                                "style": "dashed",
                                "color": "#1E90FF",
                                "penwidth": "1.0",
                            },  # For direct use too
                        }
                        if not G.has_edge(u_temp, v_temp):
                            G.add_edge(u_temp, v_temp, **edge_attrs)
                            link_established_by_arp_mac = True
                            edges_added += 1
                        elif (
                            G.get_edge_data(u_temp, v_temp).get("connection_type")
                            == "unmanaged_assumed_uplink"
                        ):
                            # Upgrade assumed link to inferred
                            G[u_temp][v_temp].update(edge_attrs)
                            link_established_by_arp_mac = True
                            # Not a new edge, but an upgraded one

        if (
            not link_established_by_arp_mac
        ):  # If ARP/MAC lookup failed, create an "assumed" link
            edge_attrs = {
                "connection_type": "unmanaged_assumed_uplink",
                "detail": "Assumed Uplink",
                "style": "dotted",
                "color": "#808080",  # Grey
                "penwidth": "0.8",
                "style_attrs": {
                    "style": "dotted",
                    "color": "#808080",
                    "penwidth": "0.8",
                },
            }
            u, v = (
                min(fas_node_id, unmanaged_node_id),
                max(fas_node_id, unmanaged_node_id),
            )
            if not G.has_edge(u, v):  # Only add if no edge (e.g. inferred) exists
                G.add_edge(u, v, **edge_attrs)
                edges_added += 1

    print(
        f"    Added/Updated {edges_added} links between FAS and unmanaged/other devices."
    )


def load_managed_switches_to_graph(
    conn: sqlite3.Connection,
    G: nx.Graph,
    target_site: str,
    target_building: str,
    target_floor: str,
    target_area_name: str,  # Can be ALL_AREAS_MARKER
):
    print("  Loading managed switches from database...")
    cursor = conn.cursor()
    sql_params = [target_site, target_building, target_floor]
    if target_area_name == ALL_AREAS_MARKER:
        sql_query_switches = (  # Load all switches on the floor
            "SELECT * FROM switches WHERE site = ? AND building = ? AND floor = ?;"
        )
    else:  # Load switches for the specific lab area
        sql_query_switches = "SELECT * FROM switches WHERE site = ? AND building = ? AND floor = ? AND lab_area_name = ?;"
        sql_params.append(target_area_name)

    cursor.execute(sql_query_switches, tuple(sql_params))
    count = 0
    for switch_row_data_db in cursor.fetchall():
        switch_data_from_db_load = dict(switch_row_data_db)
        node_id_for_switch_in_G = str(switch_data_from_db_load["serial_number"])
        attributes_for_switch = {
            **switch_data_from_db_load,
            "node_origin": "managed_switch",
            "node_type_hint": switch_data_from_db_load.get(
                "device_type", "Switch"
            ),  # For role inference
            "raw_id": node_id_for_switch_in_G,
        }
        add_or_update_node_in_graph(
            G,
            node_id_for_switch_in_G,
            attributes_for_switch,
            target_site,
            target_building,
            target_floor,
            target_area_name,  # Pass the target scope to determine in_scope/out_of_scope
        )
        count += 1
    print(
        f"    Loaded/Updated {count} managed switches in the graph for the selected scope."
    )


def process_lldp_cdp_neighbors_to_graph(
    conn: sqlite3.Connection,
    G: nx.Graph,
    external_node_id_cache: Dict[
        Tuple[str, str], str
    ],  # Shared cache for external nodes
    target_site: str,
    target_building: str,
    target_floor: str,
    target_area_name: str,
):
    print("  Processing LLDP/CDP neighbors...")
    db_cursor_lldp = conn.cursor()
    # Query to get LLDP/CDP neighbor info, also try to get remote model from 'switches' table if it's a known switch
    query_lldp_str = """
        SELECT n.*, s_remote.model AS remote_model_from_db_lookup
        FROM lldp_cdp_neighbors n
        LEFT JOIN switches s_remote ON (
            (n.remote_device_id = s_remote.serial_number OR n.remote_system_name = s_remote.hostname)
            OR (n.remote_device_id = s_remote.base_mac_address) /* Added MAC check */
        ) OR (
             n.remote_mgmt_address IS NOT NULL AND
             EXISTS (SELECT 1 FROM ip_interfaces ipi_check
                     WHERE ipi_check.switch_serial_number = s_remote.serial_number AND
                           (ipi_check.ip_address_with_prefix LIKE n.remote_mgmt_address || '%' OR
                            ipi_check.ip_address_with_prefix = n.remote_mgmt_address OR
                            (INSTR(n.remote_mgmt_address, '/') > 0 AND ipi_check.ip_address_with_prefix LIKE SUBSTR(n.remote_mgmt_address, 1, INSTR(n.remote_mgmt_address, '/') -1 ) || '%') OR
                            (INSTR(n.remote_mgmt_address, '/') = 0 AND ipi_check.ip_address_with_prefix LIKE n.remote_mgmt_address || '%')
                           )
                    )
        );
    """
    db_cursor_lldp.execute(query_lldp_str)
    lldp_edges_added_this_pass = 0
    for lldp_neighbor_row_db in db_cursor_lldp.fetchall():
        lldp_data_current_row = dict(lldp_neighbor_row_db)
        local_switch_raw_sn_lldp = str(
            lldp_data_current_row["local_switch_serial_number"]
        )
        # Local switch should already be in G if it was loaded by load_managed_switches_to_graph
        local_switch_graph_node_id_lldp = local_switch_raw_sn_lldp

        if not G.has_node(local_switch_graph_node_id_lldp):
            # This can happen if the LLDP neighbor entry is for a switch not in the current diagram's scope
            # For example, an out-of-scope switch reporting its neighbors.
            # We only add edges if the local switch is part of the current diagram focus.
            continue

        # Ensure local switch's scope status is up-to-date
        add_or_update_node_in_graph(
            G,
            local_switch_graph_node_id_lldp,
            G.nodes[
                local_switch_graph_node_id_lldp
            ].copy(),  # Pass its existing attributes
            target_site,
            target_building,
            target_floor,
            target_area_name,
        )

        # Use remote model from LLDP if available, otherwise from DB lookup if neighbor is known switch
        effective_remote_model_lldp_data = lldp_data_current_row.get(
            "remote_model"  # From LLDP data itself
        ) or lldp_data_current_row.get("remote_model_from_db_lookup")

        # Resolve the remote device (could be existing managed switch, new managed switch, or external)
        remote_graph_node_id_lldp = resolve_lldp_cdp_remote_node(
            conn,
            lldp_data_current_row["remote_device_id"],
            lldp_data_current_row["remote_system_name"],
            lldp_data_current_row["remote_mgmt_address"],
            effective_remote_model_lldp_data,
            external_node_id_cache,
            G,
            target_site,
            target_building,
            target_floor,
            target_area_name,
        )
        if remote_graph_node_id_lldp is None:  # Could not resolve remote node
            continue

        # Create edge in canonical order (min_id, max_id) to avoid duplicates
        u_edge_node, v_edge_node = (
            min(local_switch_graph_node_id_lldp, remote_graph_node_id_lldp),
            max(local_switch_graph_node_id_lldp, remote_graph_node_id_lldp),
        )

        if not G.has_edge(u_edge_node, v_edge_node):
            edge_attributes_for_lldp = {
                "connection_type": "lldp_cdp",
                "protocol": lldp_data_current_row["protocol_used"],
                # Assign ports to u_port/v_port based on canonical node order
                "u_port": lldp_data_current_row["local_interface_name"]
                if local_switch_graph_node_id_lldp == u_edge_node
                else lldp_data_current_row["remote_interface_name"],
                "v_port": lldp_data_current_row["remote_interface_name"]
                if local_switch_graph_node_id_lldp
                == u_edge_node  # If local is u, remote is v, so v_port gets remote_interface
                else lldp_data_current_row[
                    "local_interface_name"
                ],  # If local is v, remote is u, so v_port gets local_interface
            }
            G.add_edge(u_edge_node, v_edge_node, **edge_attributes_for_lldp)
            lldp_edges_added_this_pass += 1
    print(f"    Added {lldp_edges_added_this_pass} LLDP/CDP edges to the graph.")


def _select_best_ap_uplink_switch(
    G: nx.Graph,
    ap_node_id: str,  # Graph ID of the AP
    candidate_switch_ports: List[
        Tuple[str, str]
    ],  # List of (switch_graph_id, switch_port_name)
    fas_raw_sns: Optional[List[str]],  # SNs of the designated Floor Access Switches
    # Returns (best_switch_graph_id, best_switch_port_name)
) -> Optional[Tuple[str, str]]:
    if not candidate_switch_ports:
        return None

    best_candidate: Optional[Tuple[str, str]] = None
    highest_score = -1  # Initialize score

    # Find the graph node IDs of the FASs if SNs are provided
    fas_graph_node_ids: List[str] = []
    if fas_raw_sns:
        for nid, ndata in G.nodes(data=True):
            if (
                ndata.get("raw_id") in fas_raw_sns
                and ndata.get("node_origin") == "managed_switch"
            ):
                fas_graph_node_ids.append(nid)

    ap_attributes = G.nodes[ap_node_id]
    ap_is_in_scope = ap_attributes.get("diagram_class") == "ap_in_scope"

    # List to store ( (score, distance_to_fas), switch_id, switch_port )
    scored_candidates = []

    for switch_node_id, switch_port_name in candidate_switch_ports:
        if not G.has_node(switch_node_id):
            continue  # Should not happen if graph is consistent

        switch_attrs = G.nodes[switch_node_id]
        if switch_attrs.get("node_origin") != "managed_switch":
            continue  # APs should connect to managed switches

        score = 0
        # Priority 1: Both AP and Switch are in scope
        switch_is_in_scope = switch_attrs.get("diagram_class") in [
            "managed_in_scope",
            "router_in_scope",  # Consider in-scope routers too
        ]
        if ap_is_in_scope and switch_is_in_scope:
            score += 1000
        elif switch_is_in_scope:  # Switch in scope, AP out of scope
            score += 500
        # Else (both out of scope, or AP in scope and Switch out of scope) score remains lower

        # Priority 2: Switch role (Access preferred)
        switch_role = switch_attrs.get("inferred_role", "Unknown")
        if switch_role == "Access":
            score += 100
        elif switch_role == "Distribution":
            score += 50
        # Core/Router switches get lower priority for direct AP connection unless no other choice

        # Priority 3: Proximity to nearest FAS (closer is better)
        # distance_to_fas is calculated during role inference
        dist_to_fas = switch_attrs.get("distance_to_fas", float("inf"))
        if dist_to_fas != float("inf"):
            score += 50 - dist_to_fas  # Max 50 points, less for farther switches

        # Special boost if the candidate switch IS one of the FASs
        if fas_graph_node_ids and switch_node_id in fas_graph_node_ids:
            score += 2000  # Strong preference for direct FAS connection

        scored_candidates.append(
            ((score, dist_to_fas), switch_node_id, switch_port_name)
        )

    if not scored_candidates:
        return None

    # Sort candidates: higher score first, then lower distance_to_fas (closer)
    scored_candidates.sort(key=lambda x: (-x[0][0], x[0][1]))

    # Return the top candidate
    return scored_candidates[0][1], scored_candidates[0][2]


def connect_access_points_to_graph(
    conn: sqlite3.Connection,
    G: nx.Graph,  # The graph to add APs and edges to
    target_site: str,
    target_building: str,
    target_floor: str,
    target_area_name: str,  # Can be ALL_AREAS_MARKER
    # FAS SN(s) for prioritization
    floor_access_switch_sns_raw_param: Optional[List[str]],
):
    print("  Connecting Access Points to the graph...")
    db_cursor_ap = conn.cursor()

    # Query APs based on the target scope
    sql_params_ap = [target_site, target_building, target_floor]
    if target_area_name == ALL_AREAS_MARKER:
        query_aps_str = "SELECT * FROM logged_access_points WHERE site=? AND building=? AND floor=?;"
    else:
        query_aps_str = "SELECT * FROM logged_access_points WHERE site = ? AND building = ? AND floor = ? AND lab_area_name = ?;"
        sql_params_ap.append(target_area_name)

    db_cursor_ap.execute(query_aps_str, tuple(sql_params_ap))
    ap_uplinks_added_count = 0

    for ap_row_data_db in db_cursor_ap.fetchall():
        ap_data_from_db = dict(ap_row_data_db)

        # Determine a unique and descriptive raw_id for the AP node
        ap_id_options = [
            ap_data_from_db.get("reported_serial_number"),  # Prefer SN
            format_mac_to_standard(
                ap_data_from_db.get("mac_address")
            ),  # Then standardized MAC
            f"db_ap_id_{ap_data_from_db['id']}",  # Fallback to DB ID
        ]
        ap_raw_id_for_graph = next(
            (
                opt
                for opt in ap_id_options
                if opt and str(opt).strip().lower() not in ["unknown", ""]
            ),
            f"db_ap_id_{ap_data_from_db['id']}",  # Ensure a raw_id
        )
        ap_graph_node_id = ap_raw_id_for_graph  # Use this as the primary graph node ID

        ap_node_attributes = {
            **ap_data_from_db,  # Include all DB data
            "node_origin": "access_point",
            "node_type_hint": "AccessPoint",  # For role/clustering logic
            "raw_id": ap_raw_id_for_graph,
        }
        add_or_update_node_in_graph(
            G,
            ap_graph_node_id,
            ap_node_attributes,
            target_site,
            target_building,
            target_floor,
            target_area_name,  # Determine scope
        )

        # Attempt to find uplink switch using AP's MAC address
        ap_label_mac_raw = ap_data_from_db.get(
            "mac_address"
        )  # Usually wired/LAN MAC for uplink
        if not ap_label_mac_raw or not is_potentially_mac(ap_label_mac_raw):
            # print(f"    AP {ap_graph_node_id} has no valid MAC for uplink search. Skipping connection attempt.")
            continue

        ap_std_label_mac = format_mac_to_standard(ap_label_mac_raw)
        if not ap_std_label_mac:
            # print(f"    AP {ap_graph_node_id} MAC {ap_label_mac_raw} could not be standardized. Skipping.")
            continue

        found_uplink_switch_node_id: Optional[str] = None
        found_uplink_switch_port: Optional[str] = None
        connection_detail_log = ""

        # Stage 1: Exact MAC match
        exact_match_candidates: List[
            Tuple[str, str]
        ] = []  # (switch_node_id, switch_port_name)
        # Iterate over *managed switches currently in the graph G*
        for switch_node_id_exact, switch_data_exact in G.nodes(data=True):
            if switch_data_exact.get("node_origin") == "managed_switch":
                switch_sn_exact = switch_data_exact.get("raw_id")
                if not switch_sn_exact:
                    continue

                # Check MAC table of this switch for the AP's MAC
                db_cursor_ap.execute(
                    "SELECT interface_name FROM mac_address_table WHERE switch_serial_number=? AND mac_address=? AND type='DYNAMIC' LIMIT 1",
                    (switch_sn_exact, ap_std_label_mac),
                )
                mac_table_match = db_cursor_ap.fetchone()
                if mac_table_match:
                    exact_match_candidates.append(
                        (switch_node_id_exact, mac_table_match["interface_name"])
                    )

        if exact_match_candidates:
            selected_uplink = _select_best_ap_uplink_switch(
                G,
                ap_graph_node_id,
                exact_match_candidates,
                floor_access_switch_sns_raw_param,
            )
            if selected_uplink:
                found_uplink_switch_node_id, found_uplink_switch_port = selected_uplink
                connection_detail_log = f"Exact MAC ({ap_std_label_mac})"

        # Stage 2: Varied MAC match (if exact match failed)
        if not found_uplink_switch_node_id:
            num_ethernet_ports_on_ap = ap_data_from_db.get(
                "reported_total_ports"
            )  # From logged_access_points table
            if (
                num_ethernet_ports_on_ap
                and isinstance(num_ethernet_ports_on_ap, int)
                and num_ethernet_ports_on_ap > 0
            ):
                varied_mac_candidates_on_switches: List[
                    Tuple[str, str, str]
                ] = []  # (varied_mac, switch_id, switch_port)
                try:
                    mac_oui_parts = ap_std_label_mac.split(":")[:5]  # First 5 octets
                    last_octet_hex = ap_std_label_mac.split(":")[-1]
                    last_octet_int = int(last_octet_hex, 16)

                    # Iterate through potential port indices on the AP
                    for port_index in range(
                        min(num_ethernet_ports_on_ap, MAX_AP_PORT_INDEX_TO_CHECK)
                    ):
                        current_last_octet_val = last_octet_int + port_index
                        if current_last_octet_val > 255:
                            break  # Octet overflow

                        varied_mac_last_octet_hex = f"{current_last_octet_val:02X}"
                        varied_mac = ":".join(
                            mac_oui_parts + [varied_mac_last_octet_hex]
                        )

                        if varied_mac == ap_std_label_mac and port_index > 0:
                            continue  # Skip base MAC if already checked

                        # Search for this varied MAC on all managed switches in G
                        for switch_node_id_varied, switch_data_varied in G.nodes(
                            data=True
                        ):
                            if (
                                switch_data_varied.get("node_origin")
                                == "managed_switch"
                            ):
                                switch_sn_varied = switch_data_varied.get("raw_id")
                                if not switch_sn_varied:
                                    continue

                                db_cursor_ap.execute(
                                    "SELECT interface_name FROM mac_address_table WHERE switch_serial_number=? AND mac_address=? AND type='DYNAMIC' LIMIT 1",
                                    (switch_sn_varied, varied_mac),
                                )
                                mac_table_match_varied = db_cursor_ap.fetchone()
                                if mac_table_match_varied:
                                    varied_mac_candidates_on_switches.append(
                                        (
                                            varied_mac,  # The MAC that matched
                                            switch_node_id_varied,  # Switch where it was found
                                            mac_table_match_varied[
                                                "interface_name"
                                            ],  # Port on that switch
                                        )
                                    )
                except ValueError:  # e.g., if last_octet_hex is not valid hex
                    pass  # Silently skip MAC variation if base MAC is malformed for this

                if varied_mac_candidates_on_switches:
                    # If varied MACs are found, check if they all point to a *single unique switch port*
                    unique_switch_ports_found = set(
                        (sw_id, port)
                        for _, sw_id, port in varied_mac_candidates_on_switches
                    )
                    if (
                        len(unique_switch_ports_found) == 1
                    ):  # Only one switch port saw any of these varied MACs
                        varied_mac_used, sw_id, sw_port = (
                            varied_mac_candidates_on_switches[0]
                        )  # Take the first one found

                        single_varied_candidate_list = [(sw_id, sw_port)]
                        selected_varied_uplink = _select_best_ap_uplink_switch(
                            G,
                            ap_graph_node_id,
                            single_varied_candidate_list,
                            floor_access_switch_sns_raw_param,
                        )
                        if selected_varied_uplink:
                            found_uplink_switch_node_id, found_uplink_switch_port = (
                                selected_varied_uplink
                            )
                            # Determine which varied MAC was responsible or if it was the base MAC found this way
                            detail_mac_val = varied_mac_used
                            assumed_idx_val = (
                                int(varied_mac_used.split(":")[-1], 16) - last_octet_int
                            )
                            if varied_mac_used == ap_std_label_mac:
                                connection_detail_log = (
                                    f"Varied MAC (base {ap_std_label_mac} matched)"
                                )
                            else:
                                connection_detail_log = f"Varied MAC ({detail_mac_val} from base {ap_std_label_mac}, assumed port_idx {assumed_idx_val})"
                    # else: More than one switch/port saw the varied MACs, too ambiguous.

        # If a unique uplink was found (either exact or varied)
        if found_uplink_switch_node_id and found_uplink_switch_port:
            u_ap_edge, v_ap_edge = (  # Canonical edge ordering
                min(ap_graph_node_id, found_uplink_switch_node_id),
                max(ap_graph_node_id, found_uplink_switch_node_id),
            )
            if not G.has_edge(u_ap_edge, v_ap_edge):
                # AP port is usually not known/relevant for diagram, switch port is key
                port_on_ap_side = None  # Or "eth0" etc. if known, but usually not
                port_on_switch_side = found_uplink_switch_port

                # Assign u_port and v_port based on canonical order
                edge_u_p = (
                    port_on_ap_side
                    if ap_graph_node_id == u_ap_edge
                    else port_on_switch_side
                )
                edge_v_p = (
                    port_on_switch_side
                    if ap_graph_node_id != u_ap_edge
                    else port_on_ap_side
                )  # Corrected logic

                G.add_edge(
                    u_ap_edge,
                    v_ap_edge,
                    connection_type="ap_uplink",
                    switch_port=found_uplink_switch_port,  # Store the actual switch port name
                    u_port=edge_u_p,
                    v_port=edge_v_p,
                    detail=connection_detail_log,
                )
                ap_uplinks_added_count += 1

    print(f"    Added {ap_uplinks_added_count} AP uplink edges to the graph.")


if __name__ == "__main__":
    print("Diagram Graph Builder Module (for import, not direct execution)")
