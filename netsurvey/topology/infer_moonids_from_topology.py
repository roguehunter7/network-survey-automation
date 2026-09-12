# infer_moonids_from_topology.py
import logging  # Added for logging
import re  # Added for regex parsing
import sqlite3
from collections import deque
from typing import List, Optional, Set, Tuple

import networkx as nx

# Attempt to import shorten_interface_name from diagram_config_utils
try:
    from netsurvey.topology.diagram_config_utils import shorten_interface_name

    SHORTEN_IFACE_IMPORTED = True
except ImportError:
    SHORTEN_IFACE_IMPORTED = False
    logging.warning(
        "infer_moonids_from_topology: Could not import shorten_interface_name from diagram_config_utils. Using fallback."
    )

    # Fallback minimal shorten_interface_name if direct import fails
    def shorten_interface_name(if_name: Optional[str]) -> Optional[str]:  # type: ignore
        if not if_name:
            return None
        name = str(if_name)
        name = re.sub(r"TwentyFiveGigE", "TF", name, flags=re.IGNORECASE)
        name = re.sub(r"FortyGigabitEthernet", "Fo", name, flags=re.IGNORECASE)
        name = re.sub(r"HundredGigE", "Hu", name, flags=re.IGNORECASE)
        name = re.sub(r"TenGigabitEthernet", "Te", name, flags=re.IGNORECASE)
        name = re.sub(r"GigabitEthernet", "Gi", name, flags=re.IGNORECASE)
        name = re.sub(r"FastEthernet", "Fa", name, flags=re.IGNORECASE)
        name = re.sub(r"Ethernet", "Eth", name, flags=re.IGNORECASE)
        name = re.sub(r"Port-channel", "Po", name, flags=re.IGNORECASE)
        name = re.sub(r"Loopback", "Lo", name, flags=re.IGNORECASE)
        name = re.sub(r"Serial", "Se", name, flags=re.IGNORECASE)
        name = re.sub(r"Vlan", "Vl", name, flags=re.IGNORECASE)
        name = re.sub(r"Virtual-Access", "VA", name, flags=re.IGNORECASE)
        return name


# Role hierarchy for determining uplink/downlink (higher value = higher in hierarchy)
ROLE_HIERARCHY_SCORES = {
    "Core": 3,
    "Router": 2,
    "Distribution": 2,
    "Access": 1,
    "Unknown": 0,
}
VALID_SWITCH_PROPAGATION_LINK_TYPES = [
    "lldp_cdp",
    "mac_inferred",
    "mac_inferred_relaxed_bridge",
]
TOPOLOGY_VLAN_RESOLUTION_METHOD = "Topology_VLAN_Path_Inherited"
TOPOLOGY_VLAN_CONFIDENCE_SCORE = 0.70

logger_moonid_prop = logging.getLogger(__name__)  # Use a named logger


def _get_switch_current_moonids(
    conn: sqlite3.Connection, switch_serial_number: str
) -> Set[str]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT moonid FROM switch_moonid_map WHERE switch_serial_number = ?",
        (switch_serial_number,),
    )
    return {row[0] for row in cursor.fetchall()}


def _get_ap_current_moonid(conn: sqlite3.Connection, ap_db_id: int) -> Optional[str]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT reported_moonid FROM logged_access_points WHERE id = ?", (ap_db_id,)
    )
    row = cursor.fetchone()
    return row[0] if row and row[0] and str(row[0]).strip() != "" else None


def _parse_interface_name_parts(
    interface_name_str: str,
) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    # Try to match common patterns like "GigabitEthernet0/1", "Gi1/0/1", "TF1/2/3", "Po10"
    # Pattern 1: Prefix, optional slot/module path, port number (e.g., Gi1/0/1, TF0/0/0/1, Eth1)
    match_complex = re.match(
        r"^([a-zA-Z\-]+)((?:[0-9]+/)*)([0-9]+)$", interface_name_str, re.IGNORECASE
    )
    if match_complex:
        return (
            match_complex.group(1),
            match_complex.group(2) or None,
            int(match_complex.group(3)),
        )
    # Pattern 2: Simpler Prefix + Number (e.g. Po1, Vl100)
    match_simple = re.match(
        r"^([a-zA-Z\-]+)([0-9]+)$", interface_name_str, re.IGNORECASE
    )
    if match_simple:
        return match_simple.group(1), None, int(match_simple.group(2))
    logger_moonid_prop.debug(
        f"Could not parse interface name components: {interface_name_str}"
    )
    return None, None, None


def _is_interface_in_list_entry(target_full_iface_name: str, list_entry: str) -> bool:
    short_target_iface = shorten_interface_name(target_full_iface_name)
    short_list_entry = shorten_interface_name(list_entry)

    if not short_target_iface or not short_list_entry:
        return False
    if short_target_iface.lower() == short_list_entry.lower():
        return True  # Case-insensitive direct match

    target_prefix, target_base, target_num = _parse_interface_name_parts(
        short_target_iface
    )
    if target_num is None:
        return False  # Cannot compare if target is not parsable

    # Try to match range patterns like "Gi0/1-3", "Gi1/0/1-1/0/5" (more complex), "Te1-4"
    # Simple range: PrefixNum-Num (e.g. Gi1-4, Te10-12)
    range_match_simple = re.match(
        r"^([a-zA-Z\-]+)([0-9]+)\s*-\s*([0-9]+)$", short_list_entry, re.IGNORECASE
    )
    if range_match_simple:
        entry_prefix, entry_start_str, entry_end_str = range_match_simple.groups()
        if (
            target_prefix
            and target_prefix.lower() == entry_prefix.lower()
            and target_base is None
        ):  # Simple prefix match
            try:
                entry_start, entry_end = int(entry_start_str), int(entry_end_str)
                if entry_start <= target_num <= entry_end:
                    return True
            except ValueError:
                pass  # Should not happen with regex

    # Complex range: PrefixSlot/Module/Port-Port (e.g. Gi1/0/1-5)
    range_match_complex_port_only = re.match(
        r"^([a-zA-Z\-]+)((?:[0-9]+/)+)([0-9]+)\s*-\s*([0-9]+)$",
        short_list_entry,
        re.IGNORECASE,
    )
    if range_match_complex_port_only:
        entry_prefix, entry_base_val, entry_start_str, entry_end_str = (
            range_match_complex_port_only.groups()
        )
        if (
            target_prefix
            and target_prefix.lower() == entry_prefix.lower()
            and target_base
            and target_base.lower() == (entry_base_val or "").lower()
        ):
            try:
                entry_start, entry_end = int(entry_start_str), int(entry_end_str)
                if entry_start <= target_num <= entry_end:
                    return True
            except ValueError:
                pass

    # Complex range with full path: PrefixSlot/Module/Port - PrefixSlot/Module/Port (e.g. Gi1/0/1-Gi1/0/5)
    # This one is harder and usually not seen in `show vlan` port lists. For now, relying on simpler matches.
    # A more robust parser might be needed if such complex ranges are common in the source data's `ports_associated_text`.

    return False  # If no specific match or range match


def _get_vlans_for_interface(
    conn: sqlite3.Connection, switch_sn: str, interface_name: str
) -> Set[int]:
    cursor = conn.cursor()
    vlan_ids_on_interface: Set[int] = set()
    cursor.execute(
        "SELECT vlan FROM interfaces WHERE switch_serial_number = ? AND interface_name = ?",
        (switch_sn, interface_name),
    )
    if_row = cursor.fetchone()
    if not if_row:
        return vlan_ids_on_interface

    interface_vlan_field_val = if_row[0]
    if interface_vlan_field_val:
        if interface_vlan_field_val.isdigit():
            vlan_ids_on_interface.add(int(interface_vlan_field_val))
            return vlan_ids_on_interface  # Access port, only one VLAN
        elif interface_vlan_field_val.lower().startswith("trunk"):
            # For trunk, we need to check 'show vlan' output (vlans.ports_associated_text)
            cursor.execute(
                "SELECT vlan_id, ports_associated_text FROM vlans WHERE switch_serial_number = ?",
                (switch_sn,),
            )
            for vlan_row_data in cursor.fetchall():
                vlan_id_db, ports_text_db = vlan_row_data[0], vlan_row_data[1]
                if not ports_text_db:
                    continue
                port_entries_in_vlan_db = [p.strip() for p in ports_text_db.split(",")]
                for entry_in_db in port_entries_in_vlan_db:
                    if _is_interface_in_list_entry(interface_name, entry_in_db):
                        vlan_ids_on_interface.add(vlan_id_db)
                        break  # Found this interface in this VLAN's port list
    return vlan_ids_on_interface


def _get_moonids_for_vlan_ids(conn: sqlite3.Connection, vlan_ids: Set[int]) -> Set[str]:
    if not vlan_ids:
        return set()
    placeholders = ",".join("?" for _ in vlan_ids)
    sql = f"SELECT DISTINCT moonid FROM moonid_areas WHERE vlan_id IN ({placeholders})"
    cursor = conn.cursor()
    cursor.execute(sql, tuple(vlan_ids))
    return {row[0] for row in cursor.fetchall() if row[0]}


def propagate_moonids_in_diagram(
    conn: sqlite3.Connection,
    G_diagram: nx.Graph,
    floor_access_switch_sns: Optional[List[str]],
):
    logger_moonid_prop.info(
        "--- Starting MOONID Inference from Topology (Multi-FAS-Aware, Top-Down, VLAN-Sensitive) ---"
    )
    switches_moonids_assigned_count = 0
    aps_moonids_assigned_count = 0
    cursor = conn.cursor()

    fas_node_ids_in_diagram: List[str] = []
    managed_switch_nodes_in_diagram: List[str] = []

    for node_id, attrs in G_diagram.nodes(data=True):
        # distance_to_fas is now distance to *nearest* FAS, pre-calculated by inference engine
        # It's pre-set, so we don't need to initialize it here.
        attrs["is_fas"] = False
        if attrs.get("node_origin") == "managed_switch":
            managed_switch_nodes_in_diagram.append(node_id)
            sn = attrs.get("raw_id")
            if sn:
                attrs["current_moonids"] = _get_switch_current_moonids(conn, sn)
                if floor_access_switch_sns and sn in floor_access_switch_sns:
                    fas_node_ids_in_diagram.append(node_id)
                    attrs["is_fas"] = True
            else:
                attrs["current_moonids"] = set()
        elif attrs.get("node_origin") == "access_point":
            ap_db_id = attrs.get("id")  # DB primary key for logged_access_points
            if ap_db_id is not None:
                attrs["current_reported_moonid"] = _get_ap_current_moonid(
                    conn, int(ap_db_id)
                )
            else:
                attrs["current_reported_moonid"] = None

    if floor_access_switch_sns and not fas_node_ids_in_diagram:
        logger_moonid_prop.warning(
            f"  Specified FAS SN(s) '{floor_access_switch_sns}' not found. Propagation may be limited."
        )
    elif fas_node_ids_in_diagram:
        fas_hostnames_display = [
            G_diagram.nodes[fas_id].get("hostname", fas_id)
            for fas_id in fas_node_ids_in_diagram
        ]
        logger_moonid_prop.info(
            f"  Identified Floor Access Switch(es) (FAS): {', '.join(fas_hostnames_display)}"
        )
        # The 'distance_to_fas' is assumed to be pre-calculated by infer_switch_roles to be 'distance_to_nearest_fas'

    queue = deque()
    visited_nodes_for_propagation_as_source = (
        set()
    )  # Nodes whose MOONIDs have been used to propagate
    initial_source_candidates: List[
        Tuple[float, float, str]
    ] = []  # (neg_role_score, dist_fas, node_id)

    # Seed the queue with all specified FASs that have MOONIDs
    if fas_node_ids_in_diagram:
        for fas_node_id in fas_node_ids_in_diagram:
            fas_attrs = G_diagram.nodes[fas_node_id]
            if fas_attrs.get("current_moonids"):
                fas_role = fas_attrs.get("inferred_role", "Distribution")
                fas_role_score = ROLE_HIERARCHY_SCORES.get(fas_role, 0)
                # FAS nodes have distance 0 to themselves (nearest FAS)
                initial_source_candidates.append((-fas_role_score, 0.0, fas_node_id))

    # If no FAS specified or FASs have no MOONIDs, use other high-tier switches
    if not initial_source_candidates:
        logger_moonid_prop.info(
            "  No FAS specified or FAS(s) have no initial MOONIDs. Considering other high-tier switches as propagation seeds."
        )
        for node_id_seed in managed_switch_nodes_in_diagram:
            attrs_seed = G_diagram.nodes[node_id_seed]
            if attrs_seed.get("current_moonids"):
                role_seed = attrs_seed.get("inferred_role", "Unknown")
                if role_seed in ["Core", "Distribution", "Router"]:
                    dist_fas_seed = attrs_seed.get(
                        "distance_to_fas", float("inf")
                    )  # This is distance_to_nearest_fas
                    role_score_seed = ROLE_HIERARCHY_SCORES.get(role_seed, 0)
                    initial_source_candidates.append(
                        (-role_score_seed, dist_fas_seed, node_id_seed)
                    )

    initial_source_candidates.sort()  # Sort by highest role first, then by distance to FAS
    for _, _, node_id_q_init in initial_source_candidates:
        if node_id_q_init not in visited_nodes_for_propagation_as_source:
            queue.append(node_id_q_init)
            visited_nodes_for_propagation_as_source.add(node_id_q_init)

    while queue:
        u_id = queue.popleft()
        u_attrs = G_diagram.nodes[u_id]
        u_sn = u_attrs.get("raw_id")

        if not (
            u_attrs.get("node_origin") == "managed_switch"
            and u_sn
            and u_attrs.get("current_moonids")
        ):
            continue

        u_role_score = ROLE_HIERARCHY_SCORES.get(
            u_attrs.get("inferred_role", "Unknown"), 0
        )
        u_dist_fas = u_attrs.get("distance_to_fas", float("inf"))

        for v_id in G_diagram.neighbors(u_id):
            v_attrs = G_diagram.nodes[v_id]
            edge_data = G_diagram.get_edge_data(u_id, v_id)
            if not edge_data:
                continue

            # Determine the port on switch 'u' that connects to 'v'
            u_port_name_on_u_to_v = (
                edge_data.get("u_port") if u_id < v_id else edge_data.get("v_port")
            )
            if not u_port_name_on_u_to_v:
                continue  # No port info on edge

            link_vlan_ids = _get_vlans_for_interface(conn, u_sn, u_port_name_on_u_to_v)
            if not link_vlan_ids:
                continue

            moonids_to_propagate_via_vlans = _get_moonids_for_vlan_ids(
                conn, link_vlan_ids
            )
            if not moonids_to_propagate_via_vlans:
                continue

            # Filter MOONIDs to propagate: only those already on switch 'u'
            propagating_moonids_set = moonids_to_propagate_via_vlans.intersection(
                u_attrs.get("current_moonids", set())
            )
            if not propagating_moonids_set:
                continue

            if v_attrs.get("node_origin") == "managed_switch":
                v_sn_target = v_attrs.get("raw_id")
                if not v_sn_target:
                    continue
                if v_id in fas_node_ids_in_diagram:
                    continue  # Do not propagate TO any of the FASs

                v_role_score = ROLE_HIERARCHY_SCORES.get(
                    v_attrs.get("inferred_role", "Unknown"), 0
                )
                v_dist_fas_target = v_attrs.get("distance_to_fas", float("inf"))

                is_hierarchically_downstream = u_role_score > v_role_score
                # A switch is topologically downstream if its distance to the nearest FAS is greater than the source's.
                is_topologically_downstream_fas = (
                    fas_node_ids_in_diagram
                    and u_dist_fas < v_dist_fas_target
                    and v_dist_fas_target != float("inf")
                ) or (
                    not fas_node_ids_in_diagram
                )  # If no FAS, any hierarchical downstream is ok

                if (
                    is_hierarchically_downstream
                    and is_topologically_downstream_fas
                    and edge_data.get("connection_type")
                    in VALID_SWITCH_PROPAGATION_LINK_TYPES
                ):
                    assigned_new_moonid_to_v = False
                    for moonid_val_prop in propagating_moonids_set:
                        if moonid_val_prop not in v_attrs.get("current_moonids", set()):
                            try:
                                cursor.execute(
                                    "INSERT INTO switch_moonid_map (switch_serial_number, moonid, resolution_method, confidence_score) VALUES (?, ?, ?, ?)",
                                    (
                                        v_sn_target,
                                        moonid_val_prop,
                                        TOPOLOGY_VLAN_RESOLUTION_METHOD,
                                        TOPOLOGY_VLAN_CONFIDENCE_SCORE,
                                    ),
                                )
                                if cursor.rowcount > 0:
                                    assigned_new_moonid_to_v = True
                            except sqlite3.IntegrityError:  # (SN, MOONID) pair already exists, perhaps by other means
                                logger_moonid_prop.debug(
                                    f"MOONID {moonid_val_prop} for switch {v_sn_target} already mapped (IntegrityError)."
                                )
                            except sqlite3.Error as e_db_sw:
                                logger_moonid_prop.error(
                                    f"DB Error assigning MOONID '{moonid_val_prop}' to switch {v_sn_target}: {e_db_sw}"
                                )

                    if assigned_new_moonid_to_v:
                        conn.commit()
                        v_attrs["current_moonids"] = _get_switch_current_moonids(
                            conn, v_sn_target
                        )
                        switches_moonids_assigned_count += 1

                    if (
                        v_id not in visited_nodes_for_propagation_as_source
                        and v_attrs.get("current_moonids")
                    ):
                        queue.append(v_id)
                        visited_nodes_for_propagation_as_source.add(v_id)

            elif v_attrs.get("node_origin") == "access_point":
                ap_db_id_target = v_attrs.get("id")
                if ap_db_id_target is None:
                    continue

                u_is_in_fas_domain = (not fas_node_ids_in_diagram) or (
                    u_dist_fas != float("inf")
                )

                if (
                    u_is_in_fas_domain
                    and edge_data.get("connection_type") == "ap_uplink"
                ):
                    current_ap_moonids_str = v_attrs.get("current_reported_moonid")
                    existing_ap_moonids_set = (
                        set(
                            s.strip()
                            for s in current_ap_moonids_str.split(",")
                            if s.strip()
                        )
                        if current_ap_moonids_str
                        else set()
                    )

                    newly_propagated_to_ap = False
                    for moonid_val_ap_prop in propagating_moonids_set:
                        if moonid_val_ap_prop not in existing_ap_moonids_set:
                            existing_ap_moonids_set.add(moonid_val_ap_prop)
                            newly_propagated_to_ap = True

                    if newly_propagated_to_ap:
                        new_consolidated_moonids_str = ",".join(
                            sorted(list(existing_ap_moonids_set))
                        )
                        try:
                            cursor.execute(
                                "UPDATE logged_access_points SET reported_moonid = ? WHERE id = ?",
                                (new_consolidated_moonids_str, int(ap_db_id_target)),
                            )
                            if cursor.rowcount > 0:
                                conn.commit()
                                v_attrs["current_reported_moonid"] = (
                                    new_consolidated_moonids_str
                                )
                                aps_moonids_assigned_count += 1
                        except sqlite3.Error as e_db_ap:
                            logger_moonid_prop.error(
                                f"DB Error assigning MOONID(s) to AP ID {ap_db_id_target}: {e_db_ap}"
                            )

    if switches_moonids_assigned_count > 0:
        logger_moonid_prop.info(
            f"  Inferred MOONIDs for {switches_moonids_assigned_count} switches via VLAN topology."
        )
    if aps_moonids_assigned_count > 0:
        logger_moonid_prop.info(
            f"  Updated MOONIDs for {aps_moonids_assigned_count} APs via connected switch VLANs."
        )
    if switches_moonids_assigned_count == 0 and aps_moonids_assigned_count == 0:
        logger_moonid_prop.info(
            "  No new MOONIDs inferred or updated for any devices in this propagation run."
        )
    logger_moonid_prop.info("--- Finished MOONID Inference from Topology ---")


if __name__ == "__main__":
    # This part is for standalone testing, which might require a dummy DB and graph.
    # For integration, the main network_diagram_generator.py calls propagate_moonids_in_diagram.
    print(
        "infer_moonids_from_topology.py should be called as part of network_diagram_generator.py"
    )
    # Example basic setup for testing (requires a test DB and graph)
    # conn_test = sqlite3.connect("test_network_survey.db") # Create a test DB
    # G_test = nx.Graph()
    # Add some nodes and edges to G_test with attributes similar to the main script
    # ...
    # propagate_moonids_in_diagram(conn_test, G_test, floor_access_switch_sns=["FAS_SN1", "FAS_SN2"])
    # conn_test.close()
