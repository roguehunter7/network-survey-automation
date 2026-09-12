# diagram_inference_engine.py
"""
Functions for analytical inferences on the graph: role inference,
MAC-based link inference, and MOONID propagation.
"""

import logging  # Added for logging
import sqlite3
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

import networkx as nx

# Import from our new config/utils module
from netsurvey.topology.diagram_config_utils import (
    ORIGINAL_MAC_INFERENCE_MIN_JACCARD_INDEX,
    # UPLINK_HIERARCHY_SCORES, # Not directly used in this file, but roles are
    ORIGINAL_MAC_INFERENCE_MIN_SHARED_MACS,
    ROLE_ACCESS_MAX_BETWEENNESS_SCALED,
    ROLE_ACCESS_MAX_INTER_SWITCH_DEGREE,
    ROLE_CORE_MIN_BETWEENNESS_SCALED,
    ROLE_CORE_MIN_INTER_SWITCH_DEGREE,
    ROLE_HIERARCHY_ORDER,
    format_mac_to_standard,
)

logger_inf = logging.getLogger(__name__)

# Import the MOONID propagation function
try:
    from netsurvey.topology.infer_moonids_from_topology import propagate_moonids_in_diagram
except ImportError:
    logger_inf.error(
        "ERROR: Could not import propagate_moonids_in_diagram. MOONID propagation will fail."
    )

    def propagate_moonids_in_diagram(*args, **kwargs):  # type: ignore
        logger_inf.error(
            "    DUMMY: propagate_moonids_in_diagram called (actual import failed)."
        )
        pass


# --- Role Inference Functions ---
def get_preliminary_switch_roles(G_full_topology: nx.Graph) -> Dict[str, str]:
    prelim_roles_map: Dict[str, str] = {}
    managed_switch_graph_nodes = {
        n_id
        for n_id, attr_node in G_full_topology.nodes(data=True)
        if attr_node.get("node_origin") == "managed_switch"
    }
    if not managed_switch_graph_nodes:
        return prelim_roles_map

    G_inter_switch_lldp_cdp = nx.Graph()
    G_inter_switch_lldp_cdp.add_nodes_from(managed_switch_graph_nodes)
    for u_node, v_node, edge_data in G_full_topology.edges(data=True):
        if (
            u_node in managed_switch_graph_nodes
            and v_node in managed_switch_graph_nodes
            and edge_data.get("connection_type") == "lldp_cdp"
        ):
            G_inter_switch_lldp_cdp.add_edge(u_node, v_node)

    if not G_inter_switch_lldp_cdp.nodes() or not G_inter_switch_lldp_cdp.edges():
        for switch_node_id_iso in managed_switch_graph_nodes:
            prelim_roles_map[switch_node_id_iso] = "Access"
        return prelim_roles_map

    degrees_lldp_cdp = dict(G_inter_switch_lldp_cdp.degree())
    try:
        k_val_prelim, num_nodes_prelim_graph = (
            None,
            len(G_inter_switch_lldp_cdp.nodes()),
        )
        if num_nodes_prelim_graph > 2:
            k_val_prelim = (
                min(num_nodes_prelim_graph - 1, 50)
                if num_nodes_prelim_graph > 100
                else None
            )
        betweenness_lldp_cdp = (
            nx.betweenness_centrality(
                G_inter_switch_lldp_cdp, normalized=True, k=k_val_prelim
            )
            if num_nodes_prelim_graph > 1
            else {n_id: 0.0 for n_id in G_inter_switch_lldp_cdp.nodes()}
        )
    except Exception as e_betw_prelim:
        logger_inf.warning(
            f"    Preliminary role betweenness calculation failed: {e_betw_prelim}. Defaulting to 0."
        )
        betweenness_lldp_cdp = {n_id: 0.0 for n_id in G_inter_switch_lldp_cdp.nodes()}

    for switch_node_id_role in managed_switch_graph_nodes:
        degree_val, betweenness_val = (
            degrees_lldp_cdp.get(switch_node_id_role, 0),
            betweenness_lldp_cdp.get(switch_node_id_role, 0.0),
        )
        assigned_role = "Unknown"
        if degree_val == 0:
            assigned_role = "Access"
        elif (
            degree_val >= ROLE_CORE_MIN_INTER_SWITCH_DEGREE
            and betweenness_val >= ROLE_CORE_MIN_BETWEENNESS_SCALED
        ):
            assigned_role = "Core"
        elif (
            degree_val <= ROLE_ACCESS_MAX_INTER_SWITCH_DEGREE
            and betweenness_val <= ROLE_ACCESS_MAX_BETWEENNESS_SCALED
        ):
            assigned_role = "Access"
        else:
            is_distro_candidate_prelim = False
            if switch_node_id_role in G_inter_switch_lldp_cdp:
                for neighbor_node_prelim in G_inter_switch_lldp_cdp.neighbors(
                    switch_node_id_role
                ):
                    if (
                        degrees_lldp_cdp.get(neighbor_node_prelim, 0)
                        >= ROLE_CORE_MIN_INTER_SWITCH_DEGREE
                        and betweenness_lldp_cdp.get(neighbor_node_prelim, 0.0)
                        >= ROLE_CORE_MIN_BETWEENNESS_SCALED
                        and not (
                            degree_val <= ROLE_ACCESS_MAX_INTER_SWITCH_DEGREE
                            and betweenness_val <= ROLE_ACCESS_MAX_BETWEENNESS_SCALED
                        )
                    ):
                        is_distro_candidate_prelim = True
                        break
            if is_distro_candidate_prelim:
                assigned_role = "Distribution"
            elif assigned_role == "Unknown":
                assigned_role = "Access"
        prelim_roles_map[switch_node_id_role] = assigned_role
    return prelim_roles_map


def infer_switch_roles(G_topology: nx.Graph, fas_raw_sns: Optional[List[str]] = None):
    managed_switch_nodes_G = [
        n_id
        for n_id, attr_node in G_topology.nodes(data=True)
        if attr_node.get("node_origin") == "managed_switch"
    ]
    if not managed_switch_nodes_G:
        return

    # Find all FAS graph node IDs from the provided list of SNs
    fas_graph_node_ids: List[str] = []
    if fas_raw_sns:
        for nid_check_fas, ndata_check_fas in G_topology.nodes(data=True):
            if (
                ndata_check_fas.get("raw_id") in fas_raw_sns
                and ndata_check_fas.get("node_origin") == "managed_switch"
            ):
                fas_graph_node_ids.append(nid_check_fas)
                if G_topology.has_node(nid_check_fas):
                    # Mark the node so it can be identified as a FAS later
                    G_topology.nodes[nid_check_fas]["is_fas_override"] = True

    # Build the inter-switch graph for analysis
    g_inter_switch_analysis_final = nx.Graph()
    g_inter_switch_analysis_final.add_nodes_from(managed_switch_nodes_G)
    for u_node_f, v_node_f, attr_edge_f in G_topology.edges(data=True):
        if (
            u_node_f in managed_switch_nodes_G
            and v_node_f in managed_switch_nodes_G
            and attr_edge_f.get("connection_type")
            in ["lldp_cdp", "mac_inferred", "mac_inferred_relaxed_bridge"]
        ):
            g_inter_switch_analysis_final.add_edge(u_node_f, v_node_f)

    # Initialize distance_to_fas for all switches to infinity
    for sw_node_id_init_dist in managed_switch_nodes_G:
        if G_topology.has_node(sw_node_id_init_dist):
            G_topology.nodes[sw_node_id_init_dist]["distance_to_fas"] = float("inf")

    # MODIFIED: Calculate distance to the NEAREST FAS
    if fas_graph_node_ids and g_inter_switch_analysis_final.nodes():
        all_path_lengths = dict(
            nx.all_pairs_shortest_path_length(g_inter_switch_analysis_final)
        )
        for switch_id in managed_switch_nodes_G:
            if G_topology.has_node(switch_id) and switch_id in all_path_lengths:
                min_dist = float("inf")
                for fas_id in fas_graph_node_ids:
                    # Find the distance from the current switch to this specific FAS
                    dist_to_this_fas = all_path_lengths[switch_id].get(
                        fas_id, float("inf")
                    )
                    if dist_to_this_fas < min_dist:
                        min_dist = dist_to_this_fas
                # Set the node's distance_to_fas to the minimum found
                G_topology.nodes[switch_id]["distance_to_fas"] = min_dist

    degrees_inter_sw_final = dict(g_inter_switch_analysis_final.degree())
    try:
        k_val_betw_final, num_nodes_analysis_graph = (
            None,
            len(g_inter_switch_analysis_final.nodes()),
        )
        if num_nodes_analysis_graph > 2:
            k_val_betw_final = (
                min(num_nodes_analysis_graph - 1, 50)
                if num_nodes_analysis_graph > 100
                else None
            )
        betweenness_inter_sw_final = (
            nx.betweenness_centrality(
                g_inter_switch_analysis_final,
                normalized=True,
                weight=None,
                k=k_val_betw_final,
            )
            if num_nodes_analysis_graph > 1
            else {n_id: 0.0 for n_id in g_inter_switch_analysis_final.nodes()}
        )
    except Exception as e_betw_final_calc:
        logger_inf.warning(
            f"    Final role inference betweenness calculation failed: {e_betw_final_calc}. Defaulting to 0."
        )
        betweenness_inter_sw_final = {
            n_id: 0.0 for n_id in g_inter_switch_analysis_final.nodes()
        }

    for switch_node_id_current_role in managed_switch_nodes_G:
        if not G_topology.has_node(switch_node_id_current_role):
            continue
        current_node_attrs = G_topology.nodes[switch_node_id_current_role]
        deg_val_final = degrees_inter_sw_final.get(switch_node_id_current_role, 0)
        betw_val_final = betweenness_inter_sw_final.get(
            switch_node_id_current_role, 0.0
        )
        dist_to_fas_val_final = current_node_attrs.get("distance_to_fas", float("inf"))
        inferred_role_for_node = current_node_attrs.get("prelim_role", "Unknown")
        device_type_from_db = current_node_attrs.get("device_type", "Switch")

        # Check if the current switch is ANY of the FASs
        if fas_graph_node_ids and switch_node_id_current_role in fas_graph_node_ids:
            if device_type_from_db == "Router":
                inferred_role_for_node = "Router"
            else:
                is_fas_ext_connected = False
                if switch_node_id_current_role in G_topology:
                    for neighbor_of_fas in G_topology.neighbors(
                        switch_node_id_current_role
                    ):
                        if (
                            G_topology.has_node(neighbor_of_fas)
                            and G_topology.nodes[neighbor_of_fas].get("node_origin")
                            == "external_lldp_neighbor"
                            and G_topology.nodes[neighbor_of_fas].get(
                                "is_potential_network_device"
                            )
                        ):
                            is_fas_ext_connected = True
                            break
                inferred_role_for_node = (
                    "Core" if is_fas_ext_connected else "Distribution"
                )
        elif device_type_from_db == "Router":
            inferred_role_for_node = "Router"
        else:
            if deg_val_final == 0 and (
                not g_inter_switch_analysis_final.has_node(switch_node_id_current_role)
                or degrees_inter_sw_final.get(switch_node_id_current_role, 0) == 0
            ):
                inferred_role_for_node = "Access"
            elif (
                deg_val_final >= ROLE_CORE_MIN_INTER_SWITCH_DEGREE
                and betw_val_final >= ROLE_CORE_MIN_BETWEENNESS_SCALED
            ):
                inferred_role_for_node = "Core"
            elif (
                deg_val_final <= ROLE_ACCESS_MAX_INTER_SWITCH_DEGREE
                and betw_val_final <= ROLE_ACCESS_MAX_BETWEENNESS_SCALED
            ):
                inferred_role_for_node = "Access"
            else:
                connects_to_higher_tier_final = False
                if switch_node_id_current_role in g_inter_switch_analysis_final:
                    for (
                        neighbor_node_final_check
                    ) in g_inter_switch_analysis_final.neighbors(
                        switch_node_id_current_role
                    ):
                        if G_topology.has_node(neighbor_node_final_check):
                            neighbor_role_G = G_topology.nodes[
                                neighbor_node_final_check
                            ].get("inferred_role")
                            neighbor_dev_type_G = G_topology.nodes[
                                neighbor_node_final_check
                            ].get("device_type")
                            if (
                                neighbor_role_G in ["Core", "Router"]
                                or neighbor_dev_type_G == "Router"
                            ):
                                connects_to_higher_tier_final = True
                                break
                if connects_to_higher_tier_final and not (
                    deg_val_final <= ROLE_ACCESS_MAX_INTER_SWITCH_DEGREE
                    and betw_val_final <= ROLE_ACCESS_MAX_BETWEENNESS_SCALED
                ):
                    inferred_role_for_node = "Distribution"
                elif inferred_role_for_node == "Unknown":
                    inferred_role_for_node = "Access"
            if fas_graph_node_ids and inferred_role_for_node not in [
                "Core",
                "Distribution",
                "Router",
            ]:
                if dist_to_fas_val_final == 1:
                    # Find the nearest FAS's role to make a decision
                    nearest_fas_role = "Unknown"
                    for fas_id in fas_graph_node_ids:
                        if G_topology.has_edge(switch_node_id_current_role, fas_id):
                            fas_role_on_G_topology = G_topology.nodes[fas_id].get(
                                "inferred_role"
                            )
                            if ROLE_HIERARCHY_ORDER.get(
                                fas_role_on_G_topology, -1
                            ) > ROLE_HIERARCHY_ORDER.get(nearest_fas_role, -1):
                                nearest_fas_role = fas_role_on_G_topology

                    if nearest_fas_role == "Core":
                        inferred_role_for_node = (
                            "Distribution"
                            if not (
                                deg_val_final <= ROLE_ACCESS_MAX_INTER_SWITCH_DEGREE
                                and betw_val_final <= ROLE_ACCESS_MAX_BETWEENNESS_SCALED
                            )
                            else "Access"
                        )
                    elif nearest_fas_role in ["Distribution", "Router"]:
                        inferred_role_for_node = "Access"
                elif dist_to_fas_val_final > 1 and dist_to_fas_val_final != float(
                    "inf"
                ):
                    if inferred_role_for_node == "Core":
                        inferred_role_for_node = "Distribution"
                    elif inferred_role_for_node not in ["Distribution", "Router"]:
                        inferred_role_for_node = "Access"
        current_node_attrs["inferred_role"] = inferred_role_for_node
        current_node_attrs["inter_switch_degree"] = deg_val_final
        current_node_attrs["betweenness_centrality"] = round(betw_val_final, 4)


# --- MAC-based Link Inference Functions ---
def _get_mac_data_for_switches_engine(
    conn: sqlite3.Connection, G: nx.Graph, switches_to_query_nodes: Set[str]
) -> Tuple[defaultdict, defaultdict]:
    db_cursor_mac = conn.cursor()
    macs_seen_by_ports_engine = defaultdict(lambda: defaultdict(set))
    switch_own_macs_engine = defaultdict(set)
    for switch_node_id_mac_q in switches_to_query_nodes:
        if not G.has_node(switch_node_id_mac_q) or not G.nodes[
            switch_node_id_mac_q
        ].get("raw_id"):
            continue
        switch_raw_sn_mac_q = G.nodes[switch_node_id_mac_q]["raw_id"]
        base_mac_addr_node = G.nodes[switch_node_id_mac_q].get("base_mac_address")
        if base_mac_addr_node:
            std_base_mac = format_mac_to_standard(base_mac_addr_node)
            if std_base_mac:
                switch_own_macs_engine[switch_node_id_mac_q].add(std_base_mac)
        db_cursor_mac.execute(
            "SELECT mac_address FROM ip_interfaces WHERE switch_serial_number = ? AND mac_address IS NOT NULL",
            (switch_raw_sn_mac_q,),
        )
        for row_ip_mac_engine in db_cursor_mac.fetchall():
            std_ip_mac = format_mac_to_standard(row_ip_mac_engine["mac_address"])
            if std_ip_mac:
                switch_own_macs_engine[switch_node_id_mac_q].add(std_ip_mac)
        db_cursor_mac.execute(
            "SELECT interface_name, mac_address FROM mac_address_table WHERE switch_serial_number = ? AND type = 'DYNAMIC'",
            (switch_raw_sn_mac_q,),
        )
        for row_mac_table_engine in db_cursor_mac.fetchall():
            std_table_mac = format_mac_to_standard(row_mac_table_engine["mac_address"])
            if (
                std_table_mac
                and std_table_mac not in switch_own_macs_engine[switch_node_id_mac_q]
            ):
                macs_seen_by_ports_engine[switch_node_id_mac_q][
                    row_mac_table_engine["interface_name"]
                ].add(std_table_mac)
    return macs_seen_by_ports_engine, switch_own_macs_engine


def find_hierarchical_mac_uplinks_for_pass(
    conn: sqlite3.Connection,
    G_topology: nx.Graph,
    candidate_switch_nodes: Set[str],
    all_managed_switch_nodes: Set[str],
    current_roles_map_hier: Dict[str, str],
    mac_min_shared_hier: int,
    mac_min_jaccard_hier: float,
    fas_raw_sn_hier: Optional[str] = None,
    target_site_hier: Optional[str] = None,
    target_building_hier: Optional[str] = None,
    target_floor_hier: Optional[str] = None,
) -> int:
    if not candidate_switch_nodes:
        return 0
    macs_seen_by_ports_hier, _ = _get_mac_data_for_switches_engine(
        conn, G_topology, candidate_switch_nodes.union(all_managed_switch_nodes)
    )
    links_added_count_hier = 0
    fas_graph_node_id_hier: Optional[str] = None
    if fas_raw_sn_hier:
        for nid_fas_h, ndata_fas_h in G_topology.nodes(data=True):
            if (
                ndata_fas_h.get("raw_id") == fas_raw_sn_hier
                and ndata_fas_h.get("node_origin") == "managed_switch"
            ):
                fas_graph_node_id_hier = nid_fas_h
                break
    temp_inter_switch_graph_hier = nx.Graph()
    mng_sw_nodes_for_temp_graph = {
        n
        for n, d in G_topology.nodes(data=True)
        if d.get("node_origin") == "managed_switch"
    }
    temp_inter_switch_graph_hier.add_nodes_from(mng_sw_nodes_for_temp_graph)
    for u_t, v_t, d_t in G_topology.edges(data=True):
        if (
            u_t in mng_sw_nodes_for_temp_graph
            and v_t in mng_sw_nodes_for_temp_graph
            and d_t.get("connection_type")
            in ["lldp_cdp", "mac_inferred", "mac_inferred_relaxed_bridge"]
        ):
            temp_inter_switch_graph_hier.add_edge(u_t, v_t, **d_t)

    for cand_sw_node_id_hier in candidate_switch_nodes:
        cand_role_hier = current_roles_map_hier.get(cand_sw_node_id_hier, "Unknown")
        is_cand_in_target_floor_for_boost = False
        if target_site_hier and G_topology.has_node(cand_sw_node_id_hier):
            cand_attrs_hier = G_topology.nodes[cand_sw_node_id_hier]
            if (
                str(cand_attrs_hier.get("site", "")).upper()
                == str(target_site_hier).upper()
                and str(cand_attrs_hier.get("building", "")).upper()
                == str(target_building_hier).upper()
                and str(cand_attrs_hier.get("floor", "")).upper()
                == str(target_floor_hier).upper()
            ):
                is_cand_in_target_floor_for_boost = True
        potential_uplinks_list, cand_macs_by_port_hier = (
            [],
            macs_seen_by_ports_hier.get(cand_sw_node_id_hier, {}),
        )
        for cand_port_hier, macs_on_cand_port_hier in cand_macs_by_port_hier.items():
            if len(macs_on_cand_port_hier) < mac_min_shared_hier:
                continue
            for other_sw_node_id_hier in all_managed_switch_nodes:
                if other_sw_node_id_hier == cand_sw_node_id_hier:
                    continue
                other_role_hier = current_roles_map_hier.get(
                    other_sw_node_id_hier, "Unknown"
                )
                other_role_score_hier, cand_role_score_hier = (
                    ROLE_HIERARCHY_ORDER.get(other_role_hier, -1),
                    ROLE_HIERARCHY_ORDER.get(cand_role_hier, -1),
                )
                if cand_role_hier == "Core":
                    continue
                if cand_role_hier == "Router" and other_role_hier != "Core":
                    continue
                if cand_role_hier == "Distribution" and other_role_hier not in [
                    "Core",
                    "Router",
                ]:
                    continue
                if cand_role_hier == "Access" and other_role_hier in [
                    "Access",
                    "Unknown",
                ]:
                    continue
                is_link_to_fas_node_hier = (
                    fas_graph_node_id_hier is not None
                    and other_sw_node_id_hier == fas_graph_node_id_hier
                )
                if (
                    not is_link_to_fas_node_hier
                    and other_role_score_hier <= cand_role_score_hier
                ):
                    continue
                other_macs_by_port_hier = macs_seen_by_ports_hier.get(
                    other_sw_node_id_hier, {}
                )
                for (
                    other_port_hier,
                    macs_on_other_port_hier,
                ) in other_macs_by_port_hier.items():
                    if len(macs_on_other_port_hier) < mac_min_shared_hier:
                        continue
                    intersection_macs = macs_on_cand_port_hier.intersection(
                        macs_on_other_port_hier
                    )
                    if len(intersection_macs) >= mac_min_shared_hier:
                        union_size_macs = len(
                            macs_on_cand_port_hier.union(macs_on_other_port_hier)
                        )
                        jaccard_val_hier = (
                            len(intersection_macs) / union_size_macs
                            if union_size_macs > 0
                            else 0.0
                        )
                        if jaccard_val_hier >= mac_min_jaccard_hier:
                            skip_link_due_to_fas_path = False
                            if (
                                fas_graph_node_id_hier
                                and other_sw_node_id_hier != fas_graph_node_id_hier
                                and temp_inter_switch_graph_hier.has_node(
                                    cand_sw_node_id_hier
                                )
                                and temp_inter_switch_graph_hier.has_node(
                                    fas_graph_node_id_hier
                                )
                                and cand_sw_node_id_hier != fas_graph_node_id_hier
                            ):
                                try:
                                    if nx.has_path(
                                        temp_inter_switch_graph_hier,
                                        source=cand_sw_node_id_hier,
                                        target=fas_graph_node_id_hier,
                                    ):
                                        skip_link_due_to_fas_path = True
                                except (nx.NetworkXNoPath, nx.NodeNotFound):
                                    pass
                            if skip_link_due_to_fas_path:
                                continue
                            current_fas_boost_val = (
                                10
                                if is_cand_in_target_floor_for_boost
                                and is_link_to_fas_node_hier
                                else 0
                            )
                            potential_uplinks_list.append(
                                {
                                    "uplink_candidate_node_id": other_sw_node_id_hier,
                                    "candidate_port": cand_port_hier,
                                    "uplink_port": other_port_hier,
                                    "shared_mac_count": len(intersection_macs),
                                    "jaccard": jaccard_val_hier,
                                    "uplink_role_score": other_role_score_hier,
                                    "uplink_role_name": other_role_hier,
                                    "fas_boost": current_fas_boost_val,
                                }
                            )
        if not potential_uplinks_list:
            continue
        potential_uplinks_list.sort(
            key=lambda x: (
                -x["fas_boost"],
                -x["uplink_role_score"],
                -x["jaccard"],
                -x["shared_mac_count"],
            )
        )
        best_uplink_found = potential_uplinks_list[0]
        u_canon_hier_edge, v_canon_hier_edge = (
            min(cand_sw_node_id_hier, best_uplink_found["uplink_candidate_node_id"]),
            max(cand_sw_node_id_hier, best_uplink_found["uplink_candidate_node_id"]),
        )
        if G_topology.has_edge(u_canon_hier_edge, v_canon_hier_edge):
            continue
        label_prefix_hier = "H-FAS" if best_uplink_found["fas_boost"] > 0 else "H"
        attrs_hier_edge = {
            "connection_type": "mac_inferred",
            "shared_mac_count": best_uplink_found["shared_mac_count"],
            "jaccard_index": round(best_uplink_found["jaccard"], 2),
            "label_detail": f"{label_prefix_hier}: {best_uplink_found['shared_mac_count']} MACs ({best_uplink_found['jaccard']:.2f}) to {best_uplink_found['uplink_role_name']}",
            "u_port": best_uplink_found["candidate_port"]
            if cand_sw_node_id_hier == u_canon_hier_edge
            else best_uplink_found["uplink_port"],
            "v_port": best_uplink_found["uplink_port"]
            if cand_sw_node_id_hier == u_canon_hier_edge
            else best_uplink_found["candidate_port"],
        }
        G_topology.add_edge(u_canon_hier_edge, v_canon_hier_edge, **attrs_hier_edge)
        links_added_count_hier += 1
        if temp_inter_switch_graph_hier.has_node(
            u_canon_hier_edge
        ) and temp_inter_switch_graph_hier.has_node(v_canon_hier_edge):
            temp_inter_switch_graph_hier.add_edge(
                u_canon_hier_edge, v_canon_hier_edge, **attrs_hier_edge
            )
    return links_added_count_hier


def _symmetric_relaxed_mac_inference_for_bridging(
    conn: sqlite3.Connection,
    G_topology: nx.Graph,
    comp1_nodes: Set[str],
    comp2_nodes: Set[str],
    current_min_shared_macs_bridge: int,  # Parameterized
    current_min_jaccard_bridge: float,  # Parameterized
) -> int:
    macs_seen_bridge, _ = _get_mac_data_for_switches_engine(
        conn, G_topology, comp1_nodes.union(comp2_nodes)
    )
    valid_nodes_comp1 = {
        n
        for n in comp1_nodes
        if G_topology.has_node(n)
        and G_topology.nodes[n].get("node_origin") == "managed_switch"
    }
    valid_nodes_comp2 = {
        n
        for n in comp2_nodes
        if G_topology.has_node(n)
        and G_topology.nodes[n].get("node_origin") == "managed_switch"
    }
    if not valid_nodes_comp1 or not valid_nodes_comp2:
        return 0
    best_bridge_link_found = None
    for node_id1_bridge in valid_nodes_comp1:
        for node_id2_bridge in valid_nodes_comp2:
            if node_id1_bridge == node_id2_bridge:
                continue
            u_canon_bridge_edge, v_canon_bridge_edge = (
                min(node_id1_bridge, node_id2_bridge),
                max(node_id1_bridge, node_id2_bridge),
            )
            if G_topology.has_edge(u_canon_bridge_edge, v_canon_bridge_edge):
                continue
            for port1_bridge, macs1_bridge in macs_seen_bridge.get(
                node_id1_bridge, {}
            ).items():
                if len(macs1_bridge) < current_min_shared_macs_bridge:
                    continue
                for port2_bridge, macs2_bridge in macs_seen_bridge.get(
                    node_id2_bridge, {}
                ).items():
                    if len(macs2_bridge) < current_min_shared_macs_bridge:
                        continue
                    intersection_bridge = macs1_bridge.intersection(macs2_bridge)
                    if len(intersection_bridge) >= current_min_shared_macs_bridge:
                        union_len_bridge = len(macs1_bridge.union(macs2_bridge))
                        jaccard_val_bridge = (
                            len(intersection_bridge) / union_len_bridge
                            if union_len_bridge > 0
                            else 0.0
                        )
                        if jaccard_val_bridge >= current_min_jaccard_bridge:
                            quality_score_bridge = (
                                jaccard_val_bridge,
                                len(intersection_bridge),
                            )
                            if (
                                best_bridge_link_found is None
                                or quality_score_bridge
                                > best_bridge_link_found["quality"]
                            ):
                                best_bridge_link_found = {
                                    "u_orig_node_id": node_id1_bridge,
                                    "v_orig_node_id": node_id2_bridge,
                                    "u_canon_node_id": u_canon_bridge_edge,
                                    "v_canon_node_id": v_canon_bridge_edge,
                                    "port1": port1_bridge,
                                    "port2": port2_bridge,
                                    "shared_count": len(intersection_bridge),
                                    "jaccard_val": jaccard_val_bridge,
                                    "quality": quality_score_bridge,
                                }
    if best_bridge_link_found:
        attrs_bridge_edge = {
            "connection_type": "mac_inferred_relaxed_bridge",
            "shared_mac_count": best_bridge_link_found["shared_count"],
            "jaccard_index": round(best_bridge_link_found["jaccard_val"], 2),
            "label_detail": f"Relaxed Bridge: {best_bridge_link_found['shared_count']} MACs ({best_bridge_link_found['jaccard_val']:.2f})",
            "u_port": best_bridge_link_found["port1"]
            if best_bridge_link_found["u_orig_node_id"]
            == best_bridge_link_found["u_canon_node_id"]
            else best_bridge_link_found["port2"],
            "v_port": best_bridge_link_found["port2"]
            if best_bridge_link_found["u_orig_node_id"]
            == best_bridge_link_found["u_canon_node_id"]
            else best_bridge_link_found["port1"],
        }
        G_topology.add_edge(
            best_bridge_link_found["u_canon_node_id"],
            best_bridge_link_found["v_canon_node_id"],
            **attrs_bridge_edge,
        )
        return 1
    return 0


def connect_isolated_switch_components(
    conn: sqlite3.Connection,
    G_topology: nx.Graph,
    max_iterations: int = 3,
    mac_reduction_step: float = 0.8,
    jaccard_reduction_step: float = 0.8,
):
    managed_switch_nodes_iso = {
        n
        for n, a in G_topology.nodes(data=True)
        if a.get("node_origin") == "managed_switch"
    }
    if not managed_switch_nodes_iso:
        return 0
    total_bridges_added_iso = 0
    # Use the original strict values from config for base thresholds
    base_min_shared_macs = ORIGINAL_MAC_INFERENCE_MIN_SHARED_MACS
    base_min_jaccard = ORIGINAL_MAC_INFERENCE_MIN_JACCARD_INDEX

    for iter_num_iso in range(max_iterations):
        g_mngd_current_links = nx.Graph()
        g_mngd_current_links.add_nodes_from(managed_switch_nodes_iso)
        for u_iso, v_iso, d_iso in G_topology.edges(data=True):
            if (
                u_iso in managed_switch_nodes_iso
                and v_iso in managed_switch_nodes_iso
                and d_iso.get("connection_type")
                in ["lldp_cdp", "mac_inferred", "mac_inferred_relaxed_bridge"]
            ):
                g_mngd_current_links.add_edge(u_iso, v_iso)
        if not g_mngd_current_links.nodes():
            break
        connected_components_iso = [
            c for c in nx.connected_components(g_mngd_current_links) if c
        ]
        num_components_iso = len(connected_components_iso)
        if num_components_iso <= 1:
            break

        # Calculate relaxed parameters for this iteration
        current_min_shared_macs_iter = max(
            1, int(base_min_shared_macs * (mac_reduction_step**iter_num_iso))
        )
        current_min_jaccard_iter = max(
            0.01, base_min_jaccard * (jaccard_reduction_step**iter_num_iso)
        )
        if (
            iter_num_iso == max_iterations - 1 and num_components_iso > 1
        ):  # Final desperate attempt
            current_min_shared_macs_iter = 1
            current_min_jaccard_iter = min(current_min_jaccard_iter, 0.02)

        logger_inf.debug(
            f"    Bridge Iter {iter_num_iso + 1}: {num_components_iso} components. Params: MinShared={current_min_shared_macs_iter}, MinJaccard={current_min_jaccard_iter:.3f}"
        )

        iter_bridges_this_pass_iso = 0
        sorted_components_iso = sorted(connected_components_iso, key=len)
        component_pairs_to_try = [
            (sorted_components_iso[i], sorted_components_iso[j])
            for i in range(len(sorted_components_iso))
            for j in range(i + 1, len(sorted_components_iso))
        ]
        for comp1_nodes_iso, comp2_nodes_iso in component_pairs_to_try:
            if not comp1_nodes_iso or not comp2_nodes_iso:
                continue
            bridges_found_pair_iso = _symmetric_relaxed_mac_inference_for_bridging(
                conn,
                G_topology,
                comp1_nodes_iso,
                comp2_nodes_iso,
                current_min_shared_macs_iter,
                current_min_jaccard_iter,  # Pass calculated params
            )
            if bridges_found_pair_iso > 0:
                iter_bridges_this_pass_iso += bridges_found_pair_iso
                total_bridges_added_iso += bridges_found_pair_iso
        if iter_bridges_this_pass_iso == 0:
            break  # No new bridges in this iteration
    return total_bridges_added_iso


def run_iterative_mac_inference_strategy(
    conn: sqlite3.Connection,
    G_topology: nx.Graph,
    prelim_roles_map_iter: Dict[str, str],
    fas_raw_sn_iter: Optional[str] = None,
    target_site_iter: Optional[str] = None,
    target_building_iter: Optional[str] = None,
    target_floor_iter: Optional[str] = None,
):
    logger_inf.info("--- Starting Iterative MAC Inference Strategy ---")
    all_managed_switch_nodes_iter = {
        n
        for n, a in G_topology.nodes(data=True)
        if a.get("node_origin") == "managed_switch"
    }
    if not all_managed_switch_nodes_iter:
        logger_inf.info("    No managed switches. Skipping MAC inference strategy.")
        return
    current_roles_for_iter = prelim_roles_map_iter.copy()
    MAX_OVERALL_LOOPS_ITER = 5
    for loop_num_overall_iter in range(MAX_OVERALL_LOOPS_ITER):
        logger_inf.info(
            f"\n  Overall MAC Inference Loop: {loop_num_overall_iter + 1}/{MAX_OVERALL_LOOPS_ITER}"
        )
        links_added_this_overall_loop_iter = False
        MAX_HIER_PASSES_PER_OVERALL_LOOP = 2
        for hier_pass_num_iter in range(MAX_HIER_PASSES_PER_OVERALL_LOOP):
            hier_candidate_nodes_iter = {
                sw_node
                for sw_node in all_managed_switch_nodes_iter
                if current_roles_for_iter.get(sw_node)
                in ["Access", "Distribution", "Unknown", None]
            }
            if not hier_candidate_nodes_iter:
                break
            new_hier_links_count_iter = find_hierarchical_mac_uplinks_for_pass(
                conn,
                G_topology,
                hier_candidate_nodes_iter,
                all_managed_switch_nodes_iter,
                current_roles_for_iter,
                ORIGINAL_MAC_INFERENCE_MIN_SHARED_MACS,
                ORIGINAL_MAC_INFERENCE_MIN_JACCARD_INDEX,  # Use original strict values
                fas_raw_sn_iter,
                target_site_iter,
                target_building_iter,
                target_floor_iter,
            )
            if new_hier_links_count_iter > 0:
                links_added_this_overall_loop_iter = True
            else:
                break
        relaxed_bridge_links_count_iter = connect_isolated_switch_components(
            conn, G_topology
        )  # Uses its own iterative relaxation
        if relaxed_bridge_links_count_iter > 0:
            links_added_this_overall_loop_iter = True
        if not links_added_this_overall_loop_iter:
            logger_inf.info(
                f"\n--- Iterative MAC Inference stabilized in Loop {loop_num_overall_iter + 1}. ---"
            )
            break
    if (
        loop_num_overall_iter == MAX_OVERALL_LOOPS_ITER - 1
        and links_added_this_overall_loop_iter
    ):
        logger_inf.info(
            "\n--- Iterative MAC Inference reached MAX_OVERALL_LOOPS with changes. ---"
        )
    logger_inf.info("--- Finished Iterative MAC Inference Strategy. ---")


# --- MOONID Propagation Call ---
def trigger_moonid_propagation(
    conn: sqlite3.Connection,
    G_target_graph: nx.Graph,
    fas_raw_sns_prop: Optional[List[str]],
):
    logger_inf.info("  Triggering MOONID propagation (Multi-FAS-Aware)...")
    if "propagate_moonids_in_diagram" in globals() and callable(
        propagate_moonids_in_diagram
    ):
        propagate_moonids_in_diagram(
            conn, G_target_graph, floor_access_switch_sns=fas_raw_sns_prop
        )
    else:
        logger_inf.error(
            "    ERROR: propagate_moonids_in_diagram not available. MOONID propagation skipped."
        )


if __name__ == "__main__":
    print("Diagram Inference Engine Module (for import, not direct execution)")
