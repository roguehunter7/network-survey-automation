# network_diagram_generator.py
"""
Main executable script for generating network diagrams.
Orchestrates graph building, inference, Pydot output, uplink reporting, and MOONID propagation.
"""

import json
import os
import sqlite3
from collections import defaultdict

# Ensure Set and Tuple are imported
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx
import pydot
from networkx.drawing import nx_pydot

# --- Import from custom diagram modules ---
from netsurvey.topology.diagram_config_utils import (
    CLUSTER_LABELS,
    CLUSTER_ORDER,
    DB_FILE,
    DEFAULT_GRAPH_DIRECTION,
    DEFAULT_OUTPUT_FORMAT_EXT,
    NODE_STYLE_MAP,
    OUTPUT_DIR,
    PYDOT_EDGE_DEFAULTS,
    PYDOT_GRAPH_DEFAULTS,
    PYDOT_NODE_DEFAULTS,
    UPLINK_HIERARCHY_SCORES,
    format_mac_to_standard,
    get_color_for_lab_area,
    get_db_connection,
    is_color_dark,
    is_potentially_mac,
    sanitize_node_id_for_pydot,
    shorten_interface_name,
)
from netsurvey.topology.diagram_graph_builder import (
    ALL_AREAS_MARKER,
    connect_access_points_to_graph,
    connect_unmanaged_switches_to_fas,
    load_managed_switches_to_graph,
    load_single_managed_switch_by_sn,
    load_unmanaged_switches_for_area,
    process_lldp_cdp_neighbors_to_graph,
)
from netsurvey.topology.diagram_inference_engine import (
    get_preliminary_switch_roles,
    infer_switch_roles,
    run_iterative_mac_inference_strategy,
    trigger_moonid_propagation,
)

# --- Import and Initialize MAC Vendor Lookup ---
MACOUI = None
MAC_LOOKUP_ENABLED = False
try:
    from mac_vendor_lookup import MacLookup

    MACOUI = MacLookup()
    try:
        print(
            "INFO: Attempting to update MAC vendor list from IEEE. This may take a moment..."
        )
        MACOUI.update_vendors()
        print("INFO: MAC vendor list update attempt complete.")
        MAC_LOOKUP_ENABLED = True
    except Exception as e_update_vendors:
        print(f"WARNING: Could not update MAC vendor list: {e_update_vendors}")
        print(
            "INFO: Will proceed with potentially cached or built-in vendor list if available."
        )
        try:
            # Test if lookup works at all (might use cached data)
            MACOUI.lookup("02:00:00:00:00:00")
        except Exception:
            print(
                "ERROR: MAC vendor lookup failed even with cached list. Disabling feature."
            )
            MACOUI = None
        else:
            MAC_LOOKUP_ENABLED = True
            print("INFO: mac-vendor-lookup will use cached/built-in list.")

    if MACOUI and MAC_LOOKUP_ENABLED:
        print(
            "INFO: mac-vendor-lookup library loaded. MAC-based vendor names will be attempted for external devices."
        )

except ImportError:
    print(
        "WARNING: 'mac-vendor-lookup' library not found. To install: pip install mac-vendor-lookup"
    )
    print(
        "         Vendor names for external devices based on MAC will not be available."
    )
except Exception as e_init_maclookup:
    print(
        f"ERROR: Failed to initialize MacLookup: {e_init_maclookup}. MAC vendor lookup disabled."
    )


# --- Pydot Graph Generation Functions ---


def _create_pydot_legend(P_dot_graph_obj: pydot.Dot, color_cache: Dict[str, str]):
    """Creates a legend subgraph for lab area colors and adds it to the main graph."""
    if not color_cache:
        return

    # Create a cluster for the legend. 'rank=sink' tries to push it to the bottom.
    legend_cluster = pydot.Cluster(
        "cluster_legend",
        label="Lab Area Legend",
        style="solid",
        color="black",
        fontname="Helvetica",
        fontsize="12",
        rank="sink",  # Try to place at bottom
        margin="20",
    )

    # Create a node for each lab area in the legend
    for area_name, color in sorted(color_cache.items()):
        font_color = "#FFFFFF" if is_color_dark(color) else "#000000"
        legend_node = pydot.Node(
            f"legend_node_{sanitize_node_id_for_pydot(area_name)}",  # Unique node name
            label=area_name,
            shape="box",
            style="filled",
            fillcolor=color,
            fontcolor=font_color,
            fontname="Helvetica",
            fontsize="10",
        )
        legend_cluster.add_node(legend_node)

    P_dot_graph_obj.add_subgraph(legend_cluster)


def _get_node_cluster_key(attrs: Dict[str, Any]) -> str:
    origin = attrs.get("node_origin")
    if origin == "managed_switch":
        role = attrs.get("inferred_role")
        if role in CLUSTER_ORDER:
            return role
        # Default to Access if role is unknown
        dt = attrs.get("device_type", "Access")
        if dt == "Router" and "Router" in CLUSTER_ORDER:
            return "Router"
        return "Access"  # Fallback for managed switches
    if origin == "access_point":
        return "APs"
    if origin == "external_lldp_neighbor":
        return "External"
    if origin == "unmanaged_switch_special_mode":
        if "Unmanaged Devices" in CLUSTER_ORDER:
            return "Unmanaged Devices"
        else:
            return (
                "Access"  # Fallback if "Unmanaged Devices" somehow not in CLUSTER_ORDER
            )
    return "Unknown_Cluster"  # Should ideally not happen


def _create_pydot_clusters(
    P_dot_graph_obj: pydot.Dot, G_nx_diagram_obj: nx.Graph
) -> Dict[str, pydot.Cluster]:
    clusters_dict: Dict[str, pydot.Cluster] = {}
    nodes_by_cluster_key_map: Dict[str, List[str]] = defaultdict(list)

    # Ensure nodes exist in Pydot graph before trying to add them to clusters
    for node_id_orig_nx, node_attrs_nx in G_nx_diagram_obj.nodes(data=True):
        pydot_node_id_sanitized = sanitize_node_id_for_pydot(str(node_id_orig_nx))
        # Check if the node actually exists in the Pydot graph
        # P_dot_graph_obj.get_node() returns a list, so check if it's non-empty
        if P_dot_graph_obj.get_node(pydot_node_id_sanitized):
            nodes_by_cluster_key_map[_get_node_cluster_key(node_attrs_nx)].append(
                pydot_node_id_sanitized
            )

    for cluster_key_ordered_val in CLUSTER_ORDER:
        if (
            cluster_key_ordered_val in nodes_by_cluster_key_map
            and nodes_by_cluster_key_map[
                cluster_key_ordered_val
            ]  # Ensure list is not empty
        ):
            cluster_graph_name_str = f"cluster_{cluster_key_ordered_val.lower().replace(' ', '_').replace('&', 'and')}"
            cluster_label_str = CLUSTER_LABELS.get(
                cluster_key_ordered_val,  # Use the key from CLUSTER_ORDER
                cluster_key_ordered_val,  # Fallback to the key itself if not in CLUSTER_LABELS
            )

            pydot_cluster_attributes = {
                "label": cluster_label_str,
                "style": "filled",
                "fillcolor": "#F5F5F5",  # Default light grey
                "color": "darkgray",
                "fontname": "Helvetica",
                "fontsize": "12",
                "labelloc": "t",  # Label at the top
                "margin": "25",  # Default margin
                "rank": "same",
            }
            if cluster_key_ordered_val == "External":
                pydot_cluster_attributes["fillcolor"] = "#FEFEFE"
                pydot_cluster_attributes["margin"] = "30"
            if cluster_key_ordered_val in ["Core", "Router", "Distribution"]:
                pydot_cluster_attributes["margin"] = "20"
            if cluster_key_ordered_val == "Unmanaged Devices":
                pydot_cluster_attributes["fillcolor"] = "#EEEEEE"
                pydot_cluster_attributes["color"] = "dimgray"
                pydot_cluster_attributes["margin"] = "20"

            pydot_cluster_obj = pydot.Cluster(
                graph_name=cluster_graph_name_str, **pydot_cluster_attributes
            )

            for pydot_node_id_to_add_cluster in nodes_by_cluster_key_map[
                cluster_key_ordered_val
            ]:
                node_list_retrieved_pydot = P_dot_graph_obj.get_node(
                    pydot_node_id_to_add_cluster
                )
                if node_list_retrieved_pydot:
                    pydot_cluster_obj.add_node(node_list_retrieved_pydot[0])

            P_dot_graph_obj.add_subgraph(pydot_cluster_obj)
            clusters_dict[cluster_key_ordered_val] = pydot_cluster_obj
    return clusters_dict


def _convert_nx_to_pydot_with_defaults(
    G_nx_to_convert: nx.Graph, graph_direction_layout: str
) -> pydot.Dot:
    node_id_mapping_for_pydot = {
        n_orig: sanitize_node_id_for_pydot(str(n_orig))
        for n_orig in G_nx_to_convert.nodes()
    }
    G_for_pydot_conversion_relabeled = nx.relabel_nodes(
        G_nx_to_convert, node_id_mapping_for_pydot, copy=True
    )
    P_dot_converted = nx_pydot.to_pydot(G_for_pydot_conversion_relabeled)
    pydot_graph_attrs_set = PYDOT_GRAPH_DEFAULTS.copy()
    if graph_direction_layout and "rankdir" not in pydot_graph_attrs_set:
        pydot_graph_attrs_set["rankdir"] = graph_direction_layout
    P_dot_converted.set_graph_defaults(**pydot_graph_attrs_set)
    P_dot_converted.set_node_defaults(**PYDOT_NODE_DEFAULTS)
    P_dot_converted.set_edge_defaults(**PYDOT_EDGE_DEFAULTS)
    return P_dot_converted


def _get_pydot_node_label(
    attrs_from_G_nx_node: Dict[str, Any],
    floor_access_switch_sns_raw_main: Optional[List[str]] = None,
) -> str:
    label_parts_list = []
    original_raw_id_label = attrs_from_G_nx_node.get("raw_id")
    node_origin_label = attrs_from_G_nx_node.get("node_origin")

    is_this_node_fas_label = (
        floor_access_switch_sns_raw_main is not None
        and node_origin_label == "managed_switch"
        and original_raw_id_label in floor_access_switch_sns_raw_main
    ) or attrs_from_G_nx_node.get("is_fas_for_unmanaged_area_diagram", False)

    if node_origin_label == "external_lldp_neighbor" and attrs_from_G_nx_node.get(
        "label_override"
    ):
        return str(attrs_from_G_nx_node["label_override"])

    if node_origin_label == "managed_switch":
        role_label = attrs_from_G_nx_node.get(
            "inferred_role", attrs_from_G_nx_node.get("device_type", "Switch")
        )
        if attrs_from_G_nx_node.get(
            "is_fas_for_unmanaged_area_diagram"
        ) and role_label in ["Unknown", "Access", "Switch"]:
            role_label = "Floor Access Switch"
        model_str_sw_label = f"{attrs_from_G_nx_node.get('make', '')} {attrs_from_G_nx_node.get('model', '')}".strip()
        sn_str_sw_label = (
            str(original_raw_id_label) if original_raw_id_label else "UnknownSN"
        )
        hostname_sw_label = attrs_from_G_nx_node.get(
            "hostname", original_raw_id_label if original_raw_id_label else "NoHostname"
        )
        label_parts_list.append(str(hostname_sw_label))
        label_parts_list.append(f"({role_label})")
        if model_str_sw_label:
            label_parts_list.append(model_str_sw_label)
        if sn_str_sw_label and (
            is_this_node_fas_label
            or sn_str_sw_label != hostname_sw_label
            or not attrs_from_G_nx_node.get("hostname")
        ):
            label_parts_list.append(f"SN:{sn_str_sw_label}")
        if is_this_node_fas_label:
            label_parts_list.append("[FAS]")

    elif node_origin_label == "access_point":
        make_ap_label = attrs_from_G_nx_node.get("reported_make")
        model_ap_label = attrs_from_G_nx_node.get("reported_model", "AP") or "AP"
        label_parts_list.append(
            f"{make_ap_label} {model_ap_label}".strip()
            if make_ap_label
            else model_ap_label
        )
        mac_ap_label = attrs_from_G_nx_node.get("mac_address")
        if mac_ap_label:
            label_parts_list.append(f"MAC:{mac_ap_label}")
        uid_ap_label = original_raw_id_label
        uid_ap_prefix_label = (
            "SN:"
            if uid_ap_label == attrs_from_G_nx_node.get("reported_serial_number")
            else "ID:"
        )
        if uid_ap_label and str(uid_ap_label).lower() != "unknown":
            current_label_str_lower_check = "\n".join(label_parts_list).lower()
            if str(uid_ap_label).lower() not in current_label_str_lower_check or (
                uid_ap_prefix_label == "SN:"
                and "sn:" not in current_label_str_lower_check
            ):
                label_parts_list.append(f"{uid_ap_prefix_label}{uid_ap_label}")

    elif node_origin_label == "external_lldp_neighbor":
        remote_name_reported_ext = attrs_from_G_nx_node.get("remote_name_reported")
        remote_device_id_ext = original_raw_id_label
        model_ext_label = attrs_from_G_nx_node.get("remote_model_reported", "")
        display_name_ext = None
        if remote_name_reported_ext:
            display_name_ext = str(remote_name_reported_ext)
        elif remote_device_id_ext and is_potentially_mac(str(remote_device_id_ext)):
            std_mac_ext = format_mac_to_standard(str(remote_device_id_ext))
            if std_mac_ext:
                vendor_ext = None
                if MAC_LOOKUP_ENABLED and MACOUI:
                    try:
                        vendor_ext = MACOUI.lookup(std_mac_ext)
                        if vendor_ext and (
                            "not found" in vendor_ext.lower()
                            or "no match" in vendor_ext.lower()
                            or std_mac_ext.replace(":", "").upper()[:6]
                            in vendor_ext.upper()
                            .replace("-", "")
                            .replace(" ", "")
                            .replace(".", "")
                        ):
                            vendor_ext = None
                    except Exception:
                        vendor_ext = None
                if vendor_ext:
                    max_vendor_len = 20
                    if len(vendor_ext) > max_vendor_len:
                        suffixes_to_check = [
                            ", Inc.",
                            " Inc.",
                            ", LLC",
                            " LLC",
                            " Co., Ltd.",
                            " Ltd.",
                            " Corp.",
                            " Corporation",
                        ]
                        shortened = False
                        for suffix in suffixes_to_check:
                            if vendor_ext.endswith(suffix):
                                vendor_ext = vendor_ext[: -len(suffix)]
                                if len(vendor_ext) > max_vendor_len - 3:
                                    vendor_ext = (
                                        vendor_ext[: max_vendor_len - 3] + "..."
                                    )
                                shortened = True
                                break
                        if not shortened and len(vendor_ext) > max_vendor_len:
                            vendor_ext = vendor_ext[: max_vendor_len - 3] + "..."
                    display_name_ext = f"({vendor_ext} Device)"
                else:
                    display_name_ext = std_mac_ext
            else:
                display_name_ext = str(remote_device_id_ext)
        elif remote_device_id_ext:
            display_name_ext = str(remote_device_id_ext)
        else:
            display_name_ext = "External Device"
        label_parts_list.append(display_name_ext)
        if model_ext_label:
            label_parts_list.append(f"({model_ext_label})")
        label_parts_list.append(
            "(Unsurveyed SW/RT)"
            if attrs_from_G_nx_node.get("is_potential_network_device")
            else "(Unsurveyed Ext.)"
        )

    elif node_origin_label == "unmanaged_switch_special_mode":
        make_unm = attrs_from_G_nx_node.get(
            "reported_make", attrs_from_G_nx_node.get("make_surveyed", "Unmanaged")
        )
        model_unm = attrs_from_G_nx_node.get(
            "reported_model", attrs_from_G_nx_node.get("model_surveyed", "Device")
        )
        label_parts_list.append(f"{make_unm} {model_unm}".strip())
        label_parts_list.append(
            f"({attrs_from_G_nx_node.get('status_reason', 'Unmanaged')})"
        )
        surveyed_sn = attrs_from_G_nx_node.get("serial_number_surveyed")
        if (
            surveyed_sn
            and surveyed_sn.lower() not in "\n".join(label_parts_list).lower()
            and surveyed_sn.lower() != "unknown"
        ):
            label_parts_list.append(f"SN: {surveyed_sn}")

    else:
        label_parts_list.append(str(original_raw_id_label or "UnknownNode"))
        label_parts_list.append("(Origin Unknown)")

    return "\n".join(filter(None, map(str, label_parts_list)))


def _apply_node_styles_and_labels(
    P_dot_graph_to_style: pydot.Dot,
    G_nx_diagram_ref: nx.Graph,
    floor_access_switch_sns_raw_style: Optional[List[str]] = None,
    is_all_areas_mode: bool = False,
    lab_area_color_cache: Dict[str, str] = {},
):
    for node_id_orig_nx_style, attrs_nx_style in G_nx_diagram_ref.nodes(data=True):
        node_str_pydot_style = sanitize_node_id_for_pydot(str(node_id_orig_nx_style))
        p_node_list_style = P_dot_graph_to_style.get_node(node_str_pydot_style)
        if not p_node_list_style:
            continue
        p_node_to_style = p_node_list_style[0]
        p_node_to_style.set_label(
            _get_pydot_node_label(attrs_nx_style, floor_access_switch_sns_raw_style)
        )
        pydot_node_style_attrs_map: Dict[str, Any] = {}
        diagram_class_node_style = attrs_nx_style.get("diagram_class", "external")
        node_origin_style = attrs_nx_style.get("node_origin")
        is_fas_node = (
            floor_access_switch_sns_raw_style is not None
            and node_origin_style == "managed_switch"
            and attrs_nx_style.get("raw_id") in floor_access_switch_sns_raw_style
        ) or attrs_nx_style.get("is_fas_for_unmanaged_area_diagram", False)
        if is_fas_node:
            pydot_node_style_attrs_map.update(
                {
                    "shape": "doubleoctagon",
                    "penwidth": "4.0",
                    "color": "#00BCD4",
                    "fillcolor": "#E0F7FA",
                    "fontcolor": "#004D40",
                    "fontsize": "11",
                }
            )
            base_style_str_fas = PYDOT_NODE_DEFAULTS.get("style", "solid").replace(
                '"', ""
            )
            style_parts_set_fas = set(
                s.strip() for s in base_style_str_fas.split(",") if s.strip()
            )
            style_parts_set_fas.update(["filled", "bold"])
            pydot_node_style_attrs_map["style"] = (
                f'"{",".join(sorted(list(style_parts_set_fas)))}"'
            )
        else:
            if diagram_class_node_style in NODE_STYLE_MAP:
                fc, c, pw, sh, st_str = NODE_STYLE_MAP[diagram_class_node_style]
                if fc is not None:
                    pydot_node_style_attrs_map["fillcolor"] = fc
                if c:
                    pydot_node_style_attrs_map["color"] = c
                if pw:
                    pydot_node_style_attrs_map["penwidth"] = pw
                if sh:
                    pydot_node_style_attrs_map["shape"] = sh
                if st_str:
                    pydot_node_style_attrs_map["style"] = st_str
            else:
                pydot_node_style_attrs_map.update(
                    {"color": "#777777", "penwidth": "1.0", "style": "solid"}
                )
            if node_origin_style == "managed_switch":
                inferred_role_style = attrs_nx_style.get("inferred_role")
                if inferred_role_style == "Core":
                    pydot_node_style_attrs_map.update(
                        {"shape": "oval", "color": "#E74C3C", "penwidth": "2.5"}
                    )
                elif inferred_role_style == "Distribution":
                    pydot_node_style_attrs_map.update(
                        {"shape": "box", "color": "#F39C12", "penwidth": "2.0"}
                    )

        # Override fillcolor for "All Areas" mode to show lab area affiliation
        if is_all_areas_mode and attrs_nx_style.get("diagram_class") in [
            "managed_in_scope",
            "ap_in_scope",
            "router_in_scope",
            "unmanaged_switch_in_scope",
        ]:
            lab_area = attrs_nx_style.get("lab_area_name")
            if lab_area:
                area_color = get_color_for_lab_area(lab_area, lab_area_color_cache)
                pydot_node_style_attrs_map["fillcolor"] = area_color
                # Ensure style is 'filled' if we are coloring it
                base_style = pydot_node_style_attrs_map.get("style", "solid").replace(
                    '"', ""
                )
                if "filled" not in base_style:
                    pydot_node_style_attrs_map["style"] = f'"{base_style},filled"'
                # Set contrasting font color
                pydot_node_style_attrs_map["fontcolor"] = (
                    "#FFFFFF" if is_color_dark(area_color) else "#000000"
                )

        for k_style_set, v_style_set in pydot_node_style_attrs_map.items():
            if v_style_set is not None:
                p_node_to_style.set(k_style_set, str(v_style_set))


def _apply_edge_styles_and_labels(
    P_dot_graph_edge_style: pydot.Dot, G_nx_diagram_edge_ref: nx.Graph
):
    for u_orig_nx_edge, v_orig_nx_edge, attrs_edge_nx in G_nx_diagram_edge_ref.edges(
        data=True
    ):
        u_s_pydot_edge, v_s_pydot_edge = (
            sanitize_node_id_for_pydot(str(u_orig_nx_edge)),
            sanitize_node_id_for_pydot(str(v_orig_nx_edge)),
        )
        p_edges_list_style = P_dot_graph_edge_style.get_edge(
            u_s_pydot_edge, v_s_pydot_edge
        )
        if not p_edges_list_style:
            continue
        p_edge_to_style = p_edges_list_style[0]
        label_parts_edge, edge_styling_attrs_map = [], {}
        connection_type_edge = attrs_edge_nx.get("connection_type", "unknown")
        port_u_display, port_v_display = (
            shorten_interface_name(attrs_edge_nx.get("u_port")),
            shorten_interface_name(attrs_edge_nx.get("v_port")),
        )
        port_label_str_for_edge = (
            f"{port_u_display} -- {port_v_display}"
            if port_u_display and port_v_display
            else (
                f"{port_u_display} -- ?"
                if port_u_display
                else (f"? -- {port_v_display}" if port_v_display else None)
            )
        )
        if connection_type_edge == "lldp_cdp":
            label_parts_edge.append(attrs_edge_nx.get("protocol", "LLDP/CDP"))
            if port_label_str_for_edge:
                label_parts_edge.append(port_label_str_for_edge)
            edge_styling_attrs_map.update(
                {"style": "solid", "color": "black", "penwidth": "1.5"}
            )
        elif connection_type_edge == "mac_inferred":
            # Simplified label: Only show ports if available.
            if port_label_str_for_edge:
                label_parts_edge.append(port_label_str_for_edge)
            else:
                label_parts_edge.append("MAC Inferred")  # Fallback if no port info
            edge_styling_attrs_map.update(
                {"style": "dotted", "color": "#0000CD", "penwidth": "1.2"}  # MediumBlue
            )
        elif connection_type_edge == "mac_inferred_relaxed_bridge":
            # Simplified label: Only show ports if available.
            if port_label_str_for_edge:
                label_parts_edge.append(port_label_str_for_edge)
            else:
                label_parts_edge.append("MAC Bridge")  # Fallback if no port info
            edge_styling_attrs_map.update(
                {"style": "dashed", "color": "#FF8C00", "penwidth": "1.0"}  # DarkOrange
            )
        elif connection_type_edge == "ap_uplink":
            label_parts_edge.append("AP Uplink")
            switch_port_short_uplink_label = shorten_interface_name(
                attrs_edge_nx.get("switch_port")
            )
            if switch_port_short_uplink_label:
                label_parts_edge.append(f"Port: {switch_port_short_uplink_label}")
            elif port_label_str_for_edge:
                label_parts_edge.append(port_label_str_for_edge)
            ap_uplink_detail = attrs_edge_nx.get("detail")
            if ap_uplink_detail:
                label_parts_edge.append(f"({ap_uplink_detail})")
            edge_styling_attrs_map.update(
                {
                    "style": "solid",
                    "penwidth": "1.5",
                    "arrowhead": "normal",
                    "color": "#228B22",
                }
            )
            if (
                G_nx_diagram_edge_ref.nodes[u_orig_nx_edge].get("node_origin")
                == "access_point"
            ):
                edge_styling_attrs_map["dir"] = "forward"
            elif (
                G_nx_diagram_edge_ref.nodes[v_orig_nx_edge].get("node_origin")
                == "access_point"
            ):
                edge_styling_attrs_map["dir"] = "back"
        elif connection_type_edge == "unmanaged_inferred_uplink":
            edge_detail_unm_inf = attrs_edge_nx.get("detail", "Inferred Uplink")
            label_parts_edge.append(edge_detail_unm_inf)
            edge_styling_attrs_map.update(attrs_edge_nx.get("style_attrs", {}))
            if not edge_styling_attrs_map:
                edge_styling_attrs_map.update(
                    {"style": "dashed", "color": "#1E90FF", "penwidth": "1.0"}
                )
        elif connection_type_edge == "unmanaged_assumed_uplink":
            edge_detail_unm_ass = attrs_edge_nx.get("detail", "Assumed Uplink")
            label_parts_edge.append(edge_detail_unm_ass)
            edge_styling_attrs_map.update(attrs_edge_nx.get("style_attrs", {}))
            if not edge_styling_attrs_map:
                edge_styling_attrs_map.update(
                    {"style": "dotted", "color": "#808080", "penwidth": "0.8"}
                )
        else:
            label_parts_edge.append("Unknown Link")
            if port_label_str_for_edge:
                label_parts_edge.append(port_label_str_for_edge)
            edge_styling_attrs_map.update(
                {"style": "dashed", "color": "gray", "penwidth": "0.8"}
            )
        if label_parts_edge:
            p_edge_to_style.set_label(
                "\n".join(filter(None, map(str, label_parts_edge)))
            )
        for k_style_edge_set, v_style_edge_set in edge_styling_attrs_map.items():
            if v_style_edge_set is not None:
                p_edge_to_style.set(k_style_edge_set, str(v_style_edge_set))


def _write_pydot_graph_to_file(
    P_dot_to_write: pydot.Dot,
    output_filepath_to_write: str,
    output_format_ext_write: str,
    layout_prog_name_write: str,
):
    try:
        print(
            f"Writing graph to {output_filepath_to_write} (format: {output_format_ext_write}, layout: {layout_prog_name_write})..."
        )
        writers_map_write = {
            "svg": P_dot_to_write.write_svg,
            "png": P_dot_to_write.write_png,
            "pdf": P_dot_to_write.write_pdf,
            "dot": P_dot_to_write.write_dot,
            "jpg": P_dot_to_write.write_jpg,
            "ps": P_dot_to_write.write_ps,
        }
        output_dir_path_write = os.path.dirname(output_filepath_to_write)
        if output_dir_path_write and not os.path.exists(output_dir_path_write):
            os.makedirs(output_dir_path_write, exist_ok=True)
        output_format_key = output_format_ext_write.lower().lstrip(".")

        def _emit_with_layout(prog_name):
            if output_format_key in writers_map_write:
                writers_map_write[output_format_key](
                    output_filepath_to_write, prog=prog_name
                )
            else:
                print(
                    f"Warn: Unsupported format '{output_format_ext_write}'. Writing DOT instead."
                )
                dot_fallback_path = os.path.splitext(output_filepath_to_write)[0] + ".dot"
                P_dot_to_write.write_dot(dot_fallback_path, prog=prog_name)

        try:
            _emit_with_layout(layout_prog_name_write)
        except Exception as e_layout:
            # Some Graphviz engines (notably sfdp) fail on very small graphs.
            # Fall back to the robust hierarchical 'dot' layout instead of losing
            # the diagram entirely.
            if layout_prog_name_write != "dot":
                print(
                    f"  Layout '{layout_prog_name_write}' failed "
                    f"({type(e_layout).__name__}: {e_layout}); retrying with 'dot'."
                )
                _emit_with_layout("dot")
            else:
                raise
        print(f"Pydot diagram generated: {os.path.abspath(output_filepath_to_write)}")
    except Exception as e_write_file:
        print(
            f"Error during pydot graph generation/writing: {type(e_write_file).__name__}: {e_write_file}"
        )
        if (
            "failed to execute" in str(e_write_file).lower()
            or "not found" in str(e_write_file).lower()
            or isinstance(e_write_file, FileNotFoundError)
            or (
                getattr(pydot, "InvocationException", None) is not None
                and isinstance(e_write_file, pydot.InvocationException)
            )
        ):
            print(
                f"  This often means Graphviz ('{layout_prog_name_write}') is not installed or not in your system's PATH."
            )
        try:
            debug_dot_path_write = (
                os.path.splitext(output_filepath_to_write)[0] + ".debug.dot"
            )
            P_dot_to_write.write_dot(debug_dot_path_write)
            print(f"  A debug DOT file was saved to: {debug_dot_path_write}")
        except Exception as ed_debug_write:
            print(f"  Could not write debug DOT file: {ed_debug_write}")


def generate_pydot_output(
    G_nx_for_pydot: nx.Graph,
    output_filepath_pydot: str,
    floor_access_switch_sns_raw_pydot: Optional[List[str]] = None,
    output_format_pydot: str = "png",
    layout_program_pydot: str = "sfdp",
    graph_direction_pydot: str = DEFAULT_GRAPH_DIRECTION,
    is_special_unmanaged_mode: bool = False,
    is_all_areas_mode: bool = False,
):
    if not G_nx_for_pydot.nodes():
        print("Skipping Pydot generation: Input graph (G_diagram_final) is empty.")
        return
    output_dir_pydot_create = os.path.dirname(output_filepath_pydot)
    if output_dir_pydot_create and not os.path.exists(output_dir_pydot_create):
        os.makedirs(output_dir_pydot_create, exist_ok=True)
    P_dot_graph_final = _convert_nx_to_pydot_with_defaults(
        G_nx_for_pydot, graph_direction_pydot
    )

    # This cache will be populated by _apply_node_styles_and_labels
    lab_area_color_cache = {}

    _apply_node_styles_and_labels(
        P_dot_graph_final,
        G_nx_for_pydot,
        floor_access_switch_sns_raw_pydot,
        is_all_areas_mode,
        lab_area_color_cache,
    )

    if is_special_unmanaged_mode:
        fas_pydot_node_id, unmanaged_pydot_node_ids, ap_pydot_node_ids = None, [], []
        for node_id_orig, node_attrs in G_nx_for_pydot.nodes(data=True):
            pydot_id = sanitize_node_id_for_pydot(str(node_id_orig))
            if P_dot_graph_final.get_node(pydot_id):
                if node_attrs.get("is_fas_for_unmanaged_area_diagram") or (
                    floor_access_switch_sns_raw_pydot
                    and node_attrs.get("raw_id") in floor_access_switch_sns_raw_pydot
                    and node_attrs.get("node_origin") == "managed_switch"
                ):
                    fas_pydot_node_id = pydot_id
                elif node_attrs.get("node_origin") == "unmanaged_switch_special_mode":
                    unmanaged_pydot_node_ids.append(pydot_id)
                elif node_attrs.get("node_origin") == "access_point":
                    ap_pydot_node_ids.append(pydot_id)
        if fas_pydot_node_id:
            fas_cluster = pydot.Cluster(
                "cluster_fas",
                label=CLUSTER_LABELS.get("Distribution", "Floor Access Switch"),
                style="filled",
                fillcolor="#E0F7FA",
                color="#00796B",
                rank="source",
                margin="20",
            )
            fas_node_obj_list = P_dot_graph_final.get_node(fas_pydot_node_id)
            if fas_node_obj_list:
                fas_cluster.add_node(fas_node_obj_list[0])
            P_dot_graph_final.add_subgraph(fas_cluster)
        if unmanaged_pydot_node_ids:
            unmanaged_cluster = pydot.Cluster(
                "cluster_unmanaged_devices",
                label=CLUSTER_LABELS.get(
                    "Unmanaged Devices", "Unmanaged Network Devices"
                ),
                style="filled",
                fillcolor="#EEEEEE",
                color="dimgray",
                rank="sink",
                margin="20",
            )
            for unm_id in unmanaged_pydot_node_ids:
                unm_node_obj_list = P_dot_graph_final.get_node(unm_id)
                if unm_node_obj_list:
                    unmanaged_cluster.add_node(unm_node_obj_list[0])
            P_dot_graph_final.add_subgraph(unmanaged_cluster)
        if ap_pydot_node_ids:
            ap_cluster = pydot.Cluster(
                "cluster_aps",
                label=CLUSTER_LABELS.get("APs", "Access Points"),
                style="filled",
                fillcolor="#E8F5E9",
                color="#388E3C",
                rank="sink",
                margin="20",
            )
            for ap_id in ap_pydot_node_ids:
                ap_node_obj_list = P_dot_graph_final.get_node(ap_id)
                if ap_node_obj_list:
                    ap_cluster.add_node(ap_node_obj_list[0])
            P_dot_graph_final.add_subgraph(ap_cluster)
    else:
        _create_pydot_clusters(P_dot_graph_final, G_nx_for_pydot)

    _apply_edge_styles_and_labels(P_dot_graph_final, G_nx_for_pydot)

    if is_all_areas_mode and lab_area_color_cache:
        _create_pydot_legend(P_dot_graph_final, lab_area_color_cache)

    _write_pydot_graph_to_file(
        P_dot_graph_final,
        output_filepath_pydot,
        output_format_pydot,
        layout_program_pydot,
    )


# --- Uplink Data Generation and DB Update Functions (RESTORED & ADAPTED) ---


def determine_uplink_details_for_export_from_diagram_topology(
    g_diagram_uplink: nx.Graph, floor_access_switch_sns_raw_uplink: Optional[List[str]]
) -> List[Dict[str, Any]]:
    uplink_data_list_for_export: List[Dict[str, Any]] = []
    fas_node_ids_in_g_diagram_uplink: List[str] = []

    if floor_access_switch_sns_raw_uplink:
        for nid_fas_ul, ndata_fas_ul in g_diagram_uplink.nodes(data=True):
            if (
                ndata_fas_ul.get("raw_id") in floor_access_switch_sns_raw_uplink
                and ndata_fas_ul.get("node_origin") == "managed_switch"
            ):
                fas_node_ids_in_g_diagram_uplink.append(nid_fas_ul)

    managed_switches_in_g_diagram_list = [
        (n_id_sw_ul, attr_sw_ul)
        for n_id_sw_ul, attr_sw_ul in g_diagram_uplink.nodes(data=True)
        if attr_sw_ul.get("node_origin") == "managed_switch"
        and attr_sw_ul.get("raw_id")
    ]

    for (
        switch_node_id_curr_ul,
        switch_attrs_curr_ul,
    ) in managed_switches_in_g_diagram_list:
        local_sn_curr_ul = switch_attrs_curr_ul["raw_id"]
        local_hostname_curr_ul = switch_attrs_curr_ul.get("hostname", local_sn_curr_ul)
        uplink_to_sn_export_val: Optional[str] = None
        uplink_to_hostname_export_val: Optional[str] = None
        uplink_role_of_neighbor_export_val: str = "Unknown"
        connection_type_to_uplink_export_val: Optional[str] = None
        is_isolated_from_fas_flag = False

        is_current_switch_fas_ul = (
            switch_node_id_curr_ul in fas_node_ids_in_g_diagram_uplink
        )

        if is_current_switch_fas_ul:
            uplink_to_sn_export_val = "EXTERNAL_NETWORK"
            uplink_to_hostname_export_val = "External Network"
            uplink_role_of_neighbor_export_val = "Gateway"
            is_isolated_from_fas_flag = False

            highest_ext_uplink_score_fas_ul = (
                UPLINK_HIERARCHY_SCORES.get("Unknown", -1) - 1
            )
            for neighbor_id_fas_ext_ul in g_diagram_uplink.neighbors(
                switch_node_id_curr_ul
            ):
                neighbor_attr_fas_ext_ul = g_diagram_uplink.nodes[
                    neighbor_id_fas_ext_ul
                ]
                edge_data_fas_ext_ul = g_diagram_uplink.get_edge_data(
                    switch_node_id_curr_ul, neighbor_id_fas_ext_ul
                )
                if edge_data_fas_ext_ul and edge_data_fas_ext_ul.get(
                    "connection_type"
                ) in ["lldp_cdp"]:
                    if (
                        neighbor_attr_fas_ext_ul.get("node_origin")
                        == "external_lldp_neighbor"
                        and neighbor_attr_fas_ext_ul.get("is_potential_network_device")
                    ) or (
                        neighbor_attr_fas_ext_ul.get("node_origin") == "managed_switch"
                        and neighbor_attr_fas_ext_ul.get("inferred_role")
                        in ["Core", "Router"]
                    ):
                        neighbor_role_score = UPLINK_HIERARCHY_SCORES.get("Router", 0)
                        if (
                            neighbor_attr_fas_ext_ul.get("node_origin")
                            == "managed_switch"
                        ):
                            neighbor_role_score = UPLINK_HIERARCHY_SCORES.get(
                                neighbor_attr_fas_ext_ul.get(
                                    "inferred_role", "Unknown"
                                ),
                                0,
                            )
                        if neighbor_role_score > highest_ext_uplink_score_fas_ul:
                            highest_ext_uplink_score_fas_ul = neighbor_role_score
                            uplink_to_sn_export_val = neighbor_attr_fas_ext_ul.get(
                                "raw_id", str(neighbor_id_fas_ext_ul)
                            )
                            uplink_to_hostname_export_val = (
                                neighbor_attr_fas_ext_ul.get("hostname")
                                or neighbor_attr_fas_ext_ul.get("remote_name_reported")
                                or neighbor_attr_fas_ext_ul.get("label_override")
                                or str(neighbor_id_fas_ext_ul)
                            )
                            uplink_role_of_neighbor_export_val = (
                                neighbor_attr_fas_ext_ul.get("inferred_role")
                                if neighbor_attr_fas_ext_ul.get("node_origin")
                                == "managed_switch"
                                else "Router"
                            )
                            connection_type_to_uplink_export_val = (
                                edge_data_fas_ext_ul.get("connection_type")
                            )
        else:
            highest_eff_score_for_uplink_ul = (
                UPLINK_HIERARCHY_SCORES.get("Unknown", -1) - 1
            )
            curr_sw_dist_to_fas_ul = switch_attrs_curr_ul.get(
                "distance_to_fas", float("inf")
            )

            if not fas_node_ids_in_g_diagram_uplink or curr_sw_dist_to_fas_ul == float(
                "inf"
            ):
                is_isolated_from_fas_flag = True
            else:
                is_isolated_from_fas_flag = False

            for neighbor_node_id_curr_ul in g_diagram_uplink.neighbors(
                switch_node_id_curr_ul
            ):
                neighbor_attrs_curr_ul = g_diagram_uplink.nodes[
                    neighbor_node_id_curr_ul
                ]
                edge_data_curr_ul = g_diagram_uplink.get_edge_data(
                    switch_node_id_curr_ul, neighbor_node_id_curr_ul
                )
                if not edge_data_curr_ul or edge_data_curr_ul.get(
                    "connection_type"
                ) not in ["lldp_cdp", "mac_inferred", "mac_inferred_relaxed_bridge"]:
                    continue
                role_of_neighbor_curr_ul = "Unknown"
                if neighbor_attrs_curr_ul.get("node_origin") == "managed_switch":
                    role_of_neighbor_curr_ul = neighbor_attrs_curr_ul.get(
                        "inferred_role", "Unknown"
                    )
                    if neighbor_attrs_curr_ul.get("device_type") == "Router":
                        role_of_neighbor_curr_ul = "Router"
                elif neighbor_attrs_curr_ul.get(
                    "node_origin"
                ) == "external_lldp_neighbor" and neighbor_attrs_curr_ul.get(
                    "is_potential_network_device"
                ):
                    role_of_neighbor_curr_ul = "Router"
                else:
                    continue
                current_neighbor_hier_score_ul = UPLINK_HIERARCHY_SCORES.get(
                    role_of_neighbor_curr_ul, -1
                )
                neighbor_dist_to_fas_ul = neighbor_attrs_curr_ul.get(
                    "distance_to_fas", float("inf")
                )
                fas_path_pref_factor_ul = (
                    1
                    if fas_node_ids_in_g_diagram_uplink
                    and neighbor_dist_to_fas_ul < curr_sw_dist_to_fas_ul
                    and neighbor_dist_to_fas_ul != float("inf")
                    else 0
                )
                effective_score_curr_neighbor_ul = (
                    current_neighbor_hier_score_ul + fas_path_pref_factor_ul
                )
                if effective_score_curr_neighbor_ul > highest_eff_score_for_uplink_ul:
                    highest_eff_score_for_uplink_ul = effective_score_curr_neighbor_ul
                    uplink_role_of_neighbor_export_val = role_of_neighbor_curr_ul
                    uplink_to_sn_export_val = neighbor_attrs_curr_ul.get(
                        "raw_id", str(neighbor_node_id_curr_ul)
                    )
                    uplink_to_hostname_export_val = (
                        neighbor_attrs_curr_ul.get("hostname")
                        or neighbor_attrs_curr_ul.get("remote_name_reported")
                        or (
                            neighbor_attrs_curr_ul.get("label_override")
                            if neighbor_attrs_curr_ul.get("node_origin")
                            == "external_lldp_neighbor"
                            else None
                        )
                        or str(
                            neighbor_attrs_curr_ul.get(
                                "raw_id", str(neighbor_node_id_curr_ul)
                            )
                        )
                    )
                    connection_type_to_uplink_export_val = edge_data_curr_ul.get(
                        "connection_type"
                    )

            if is_isolated_from_fas_flag and not uplink_to_sn_export_val:
                uplink_role_of_neighbor_export_val = "Isolated"
                uplink_to_hostname_export_val = "Isolated Network"

        uplink_data_list_for_export.append(
            {
                "local_switch_serial_number": local_sn_curr_ul,
                "local_switch_hostname": local_hostname_curr_ul,
                "uplink_to_serial_number": uplink_to_sn_export_val,
                "uplink_to_hostname": uplink_to_hostname_export_val,
                "uplink_role": uplink_role_of_neighbor_export_val,
                "connection_type": connection_type_to_uplink_export_val,
                "is_isolated_from_fas": is_isolated_from_fas_flag,
            }
        )
    return uplink_data_list_for_export


def update_switch_uplink_info_in_db_from_diagram_topology(
    conn: sqlite3.Connection,
    g_diagram_db_sw: nx.Graph,
    floor_access_switch_sns_raw_db_sw: Optional[List[str]],
):
    db_cursor_sw_ul_update = conn.cursor()
    switches_updated_in_db_count = 0
    fas_node_ids_in_g_diagram_db_sw: List[str] = []

    if floor_access_switch_sns_raw_db_sw:
        for nid_fas_db_sw, ndata_fas_db_sw in g_diagram_db_sw.nodes(data=True):
            if (
                ndata_fas_db_sw.get("raw_id") in floor_access_switch_sns_raw_db_sw
                and ndata_fas_db_sw.get("node_origin") == "managed_switch"
            ):
                fas_node_ids_in_g_diagram_db_sw.append(nid_fas_db_sw)

    managed_switches_in_g_diagram_for_db_sw_list = [
        (n_id_sw_db, attr_sw_db)
        for n_id_sw_db, attr_sw_db in g_diagram_db_sw.nodes(data=True)
        if attr_sw_db.get("node_origin") == "managed_switch"
        and attr_sw_db.get("raw_id")
    ]

    for (
        switch_node_id_curr_db_sw,
        switch_attrs_curr_db_sw,
    ) in managed_switches_in_g_diagram_for_db_sw_list:
        switch_sn_for_db_update_sw = switch_attrs_curr_db_sw["raw_id"]
        db_uplink_type_for_this_switch_val = "Unknown"
        is_current_switch_fas_db_sw = (
            switch_node_id_curr_db_sw in fas_node_ids_in_g_diagram_db_sw
        )

        is_isolated_switch = False
        if not is_current_switch_fas_db_sw:
            if not fas_node_ids_in_g_diagram_db_sw or switch_attrs_curr_db_sw.get(
                "distance_to_fas", float("inf")
            ) == float("inf"):
                is_isolated_switch = True

        if is_isolated_switch:
            db_uplink_type_for_this_switch_val = "Isolated"
        elif is_current_switch_fas_db_sw:
            highest_uplink_score_for_db_sw = (
                UPLINK_HIERARCHY_SCORES.get("Unknown", -1) - 1
            )
            has_external_network_link = False
            for neighbor_node_id_db_sw_ul in g_diagram_db_sw.neighbors(
                switch_node_id_curr_db_sw
            ):
                neighbor_attrs_db_sw_ul = g_diagram_db_sw.nodes[
                    neighbor_node_id_db_sw_ul
                ]
                edge_data_db_sw_ul = g_diagram_db_sw.get_edge_data(
                    switch_node_id_curr_db_sw, neighbor_node_id_db_sw_ul
                )
                if not edge_data_db_sw_ul or edge_data_db_sw_ul.get(
                    "connection_type"
                ) not in ["lldp_cdp"]:
                    continue
                role_of_neighbor_for_db_sw_type = "Unknown"
                if neighbor_attrs_db_sw_ul.get("node_origin") == "managed_switch":
                    role_of_neighbor_for_db_sw_type = neighbor_attrs_db_sw_ul.get(
                        "inferred_role", "Unknown"
                    )
                    if neighbor_attrs_db_sw_ul.get("device_type") == "Router":
                        role_of_neighbor_for_db_sw_type = "Router"
                elif neighbor_attrs_db_sw_ul.get(
                    "node_origin"
                ) == "external_lldp_neighbor" and neighbor_attrs_db_sw_ul.get(
                    "is_potential_network_device"
                ):
                    role_of_neighbor_for_db_sw_type = "Router"
                    has_external_network_link = True
                else:
                    continue
                current_neighbor_hier_score_db_sw = UPLINK_HIERARCHY_SCORES.get(
                    role_of_neighbor_for_db_sw_type, -1
                )
                if current_neighbor_hier_score_db_sw > highest_uplink_score_for_db_sw:
                    highest_uplink_score_for_db_sw = current_neighbor_hier_score_db_sw
                    db_uplink_type_for_this_switch_val = role_of_neighbor_for_db_sw_type
            if has_external_network_link and db_uplink_type_for_this_switch_val in [
                "Router",
                "Core",
            ]:
                db_uplink_type_for_this_switch_val = "Gateway"
            elif db_uplink_type_for_this_switch_val == "Unknown":
                fas_own_role = switch_attrs_curr_db_sw.get(
                    "inferred_role", "Distribution"
                )
                if fas_own_role in ["Core", "Router"]:
                    db_uplink_type_for_this_switch_val = "Gateway"
                elif fas_own_role == "Distribution":
                    db_uplink_type_for_this_switch_val = "Core"
                else:
                    db_uplink_type_for_this_switch_val = "Distribution"
        else:
            highest_uplink_score_for_db_sw = (
                UPLINK_HIERARCHY_SCORES.get("Unknown", -1) - 1
            )
            curr_sw_dist_to_fas_db_sw = switch_attrs_curr_db_sw.get(
                "distance_to_fas", float("inf")
            )
            for neighbor_node_id_db_sw_ul in g_diagram_db_sw.neighbors(
                switch_node_id_curr_db_sw
            ):
                neighbor_attrs_db_sw_ul = g_diagram_db_sw.nodes[
                    neighbor_node_id_db_sw_ul
                ]
                edge_data_db_sw_ul = g_diagram_db_sw.get_edge_data(
                    switch_node_id_curr_db_sw, neighbor_node_id_db_sw_ul
                )
                if not edge_data_db_sw_ul or edge_data_db_sw_ul.get(
                    "connection_type"
                ) not in ["lldp_cdp", "mac_inferred", "mac_inferred_relaxed_bridge"]:
                    continue
                role_of_neighbor_for_db_sw_type = "Unknown"
                if neighbor_attrs_db_sw_ul.get("node_origin") == "managed_switch":
                    role_of_neighbor_for_db_sw_type = neighbor_attrs_db_sw_ul.get(
                        "inferred_role", "Unknown"
                    )
                    if neighbor_attrs_db_sw_ul.get("device_type") == "Router":
                        role_of_neighbor_for_db_sw_type = "Router"
                elif neighbor_attrs_db_sw_ul.get(
                    "node_origin"
                ) == "external_lldp_neighbor" and neighbor_attrs_db_sw_ul.get(
                    "is_potential_network_device"
                ):
                    role_of_neighbor_for_db_sw_type = "Router"
                else:
                    continue
                current_neighbor_hier_score_db_sw = UPLINK_HIERARCHY_SCORES.get(
                    role_of_neighbor_for_db_sw_type, -1
                )
                neighbor_dist_to_fas_db_sw = neighbor_attrs_db_sw_ul.get(
                    "distance_to_fas", float("inf")
                )
                fas_path_pref_factor_db_sw = (
                    1
                    if fas_node_ids_in_g_diagram_db_sw
                    and neighbor_dist_to_fas_db_sw < curr_sw_dist_to_fas_db_sw
                    and neighbor_dist_to_fas_db_sw != float("inf")
                    else 0
                )
                effective_score_db_sw = (
                    current_neighbor_hier_score_db_sw + fas_path_pref_factor_db_sw
                )
                if effective_score_db_sw > highest_uplink_score_for_db_sw:
                    highest_uplink_score_for_db_sw = effective_score_db_sw
                    db_uplink_type_for_this_switch_val = role_of_neighbor_for_db_sw_type
        try:
            existing_uplink_type_in_db = switch_attrs_curr_db_sw.get("uplink_type")
            if (
                db_uplink_type_for_this_switch_val
                and db_uplink_type_for_this_switch_val != "Unknown"
                and (
                    not existing_uplink_type_in_db
                    or existing_uplink_type_in_db == "Unknown"
                    or existing_uplink_type_in_db != db_uplink_type_for_this_switch_val
                )
            ):
                db_cursor_sw_ul_update.execute(
                    "UPDATE switches SET uplink_type = ? WHERE serial_number = ?",
                    (db_uplink_type_for_this_switch_val, switch_sn_for_db_update_sw),
                )
                if db_cursor_sw_ul_update.rowcount > 0:
                    switches_updated_in_db_count += 1
        except sqlite3.Error as e_db_upd_sw_ul:
            print(
                f"    DB Error updating uplink_type for switch {switch_sn_for_db_update_sw}: {e_db_upd_sw_ul}"
            )
    if switches_updated_in_db_count > 0:
        conn.commit()
        print(
            f"  Updated uplink_type for {switches_updated_in_db_count} switches in the database."
        )
    else:
        print(
            "  No switch uplink_types needed updating in the database based on this diagram."
        )


def update_ap_uplink_type_in_db(
    conn: sqlite3.Connection, g_diagram_final_ap_db: nx.Graph
):
    db_cursor_ap_ul_update = conn.cursor()
    aps_updated_in_db_count = 0
    ap_nodes_in_g_diagram_ap_db_list = [
        (n_ap_db, attr_ap_db)
        for n_ap_db, attr_ap_db in g_diagram_final_ap_db.nodes(data=True)
        if attr_ap_db.get("node_origin") == "access_point" and "id" in attr_ap_db
    ]
    for ap_node_id_curr_db, ap_attrs_curr_db in ap_nodes_in_g_diagram_ap_db_list:
        ap_db_pk_id_update = ap_attrs_curr_db["id"]
        uplinked_switch_node_id_for_ap_db: Optional[str] = None
        for neighbor_node_id_ap_uplink_db in g_diagram_final_ap_db.neighbors(
            ap_node_id_curr_db
        ):
            edge_data_ap_uplink_db = g_diagram_final_ap_db.get_edge_data(
                ap_node_id_curr_db, neighbor_node_id_ap_uplink_db
            )
            if (
                edge_data_ap_uplink_db
                and edge_data_ap_uplink_db.get("connection_type") == "ap_uplink"
            ):
                neighbor_attrs = g_diagram_final_ap_db.nodes[
                    neighbor_node_id_ap_uplink_db
                ]
                if neighbor_attrs.get("node_origin") == "managed_switch":
                    uplinked_switch_node_id_for_ap_db = neighbor_node_id_ap_uplink_db
                    break
        determined_ap_uplink_type_for_db = "Isolated"
        if uplinked_switch_node_id_for_ap_db:
            switch_attrs_for_ap_uplink_db = g_diagram_final_ap_db.nodes[
                uplinked_switch_node_id_for_ap_db
            ]
            switch_is_isolated = (
                switch_attrs_for_ap_uplink_db.get("distance_to_fas", float("inf"))
                == float("inf")
                and not switch_attrs_for_ap_uplink_db.get("is_fas", False)
                and not switch_attrs_for_ap_uplink_db.get(
                    "is_fas_for_unmanaged_area_diagram", False
                )
            )
            if switch_is_isolated:
                determined_ap_uplink_type_for_db = "Isolated"
            else:
                switch_dev_type_ap_db = switch_attrs_for_ap_uplink_db.get("device_type")
                switch_inferred_role_ap_db = switch_attrs_for_ap_uplink_db.get(
                    "inferred_role"
                )
                if (
                    switch_inferred_role_ap_db == "Router"
                    or switch_dev_type_ap_db == "Router"
                ):
                    determined_ap_uplink_type_for_db = "Router"
                elif (
                    switch_inferred_role_ap_db in ["Access", "Distribution", "Core"]
                    or switch_dev_type_ap_db == "Switch"
                ):
                    determined_ap_uplink_type_for_db = "Access Switch"
                else:
                    determined_ap_uplink_type_for_db = "Unknown Switch"
        try:
            existing_ap_uplink_type_db = ap_attrs_curr_db.get("uplink_type")
            if determined_ap_uplink_type_for_db and (
                not existing_ap_uplink_type_db
                or existing_ap_uplink_type_db == "Unknown"
                or existing_ap_uplink_type_db != determined_ap_uplink_type_for_db
            ):
                db_cursor_ap_ul_update.execute(
                    "UPDATE logged_access_points SET uplink_type = ? WHERE id = ?",
                    (determined_ap_uplink_type_for_db, ap_db_pk_id_update),
                )
                if db_cursor_ap_ul_update.rowcount > 0:
                    aps_updated_in_db_count += 1
        except sqlite3.Error as e_db_upd_ap_ul:
            print(
                f"    DB Error updating uplink_type for AP ID {ap_db_pk_id_update}: {e_db_upd_ap_ul}"
            )
    if aps_updated_in_db_count > 0:
        conn.commit()
        print(
            f"  Updated uplink_type for {aps_updated_in_db_count} APs in the database."
        )
    else:
        print(
            "  No AP uplink_types needed updating in the database based on this diagram."
        )


def generate_uplink_report_data_from_diagram(
    conn: sqlite3.Connection,
    g_diagram_final_for_report: nx.Graph,
    floor_access_switch_sns_raw_for_report: Optional[List[str]],
    output_filename_base_for_json_final_report: str,
):
    if not g_diagram_final_for_report.nodes():
        uplink_json_filepath_final_empty = os.path.join(
            OUTPUT_DIR, f"{output_filename_base_for_json_final_report}_uplinks.json"
        )
        try:
            os.makedirs(
                os.path.dirname(uplink_json_filepath_final_empty), exist_ok=True
            )
            with open(uplink_json_filepath_final_empty, "w") as f_json_empty_final:
                json.dump([], f_json_empty_final, indent=2)
        except Exception as e_json_save_empty_final:
            print(
                f"  Error saving empty uplink details JSON: {e_json_save_empty_final}"
            )
        return

    print(
        "\n--- Generating Uplink Report Data & Updating Database (from G_diagram_final) ---"
    )
    uplink_export_data_list_final = (
        determine_uplink_details_for_export_from_diagram_topology(
            g_diagram_final_for_report, floor_access_switch_sns_raw_for_report
        )
    )
    uplink_json_filepath_final_report = os.path.join(
        OUTPUT_DIR, f"{output_filename_base_for_json_final_report}_uplinks.json"
    )
    try:
        os.makedirs(os.path.dirname(uplink_json_filepath_final_report), exist_ok=True)
        with open(uplink_json_filepath_final_report, "w") as f_json_final_report:
            json.dump(uplink_export_data_list_final, f_json_final_report, indent=2)
        print(
            f"  Successfully saved switch uplink details for report JSON to: {uplink_json_filepath_final_report}"
        )
    except Exception as e_json_save_final_report:
        print(
            f"  Error saving switch uplink details JSON for report: {e_json_save_final_report}"
        )

    update_switch_uplink_info_in_db_from_diagram_topology(
        conn, g_diagram_final_for_report, floor_access_switch_sns_raw_for_report
    )
    update_ap_uplink_type_in_db(conn, g_diagram_final_for_report)
    print("--- Finished Uplink Report Data Generation & DB Updates ---")


# --- Main Diagram Generation Orchestration ---
def generate_network_diagram_for_lab_area(
    conn_main_orch: sqlite3.Connection,
    target_site_main: str,
    target_building_main: str,
    target_floor_main: str,
    target_area_name_main: str,
    floor_access_switch_sns_raw_main: Optional[List[str]] = None,
    filter_diagram_main: bool = True,
    output_format_main: str = DEFAULT_OUTPUT_FORMAT_EXT.lstrip("."),
    graph_direction_main: str = DEFAULT_GRAPH_DIRECTION,
    include_unmanaged_devices_in_hybrid_mode: bool = False,
):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    is_all_areas_mode = target_area_name_main == ALL_AREAS_MARKER

    current_scope_name_for_file = (
        target_area_name_main if not is_all_areas_mode else "ALL_AREAS"
    )
    sanitized_site_fn_main = sanitize_node_id_for_pydot(str(target_site_main))
    sanitized_bldg_fn_main = sanitize_node_id_for_pydot(str(target_building_main))
    sanitized_floor_fn_main = sanitize_node_id_for_pydot(str(target_floor_main))
    sanitized_area_fn_main = sanitize_node_id_for_pydot(
        str(current_scope_name_for_file)
    )
    final_output_filename_base_main = f"pydot_{sanitized_site_fn_main}_{sanitized_bldg_fn_main}_{sanitized_floor_fn_main}_{sanitized_area_fn_main}"
    output_filepath_image_main = os.path.join(
        OUTPUT_DIR, f"{final_output_filename_base_main}.{output_format_main}"
    )

    scope_display = (
        target_area_name_main if not is_all_areas_mode else "ALL Areas on Floor"
    )
    print(
        f"--- Generating Diagram for: {target_site_main}/{target_building_main}/{target_floor_main}/{scope_display} ---"
    )
    if floor_access_switch_sns_raw_main:
        print(
            f"Floor Access Switch(es) (FAS) specified: {', '.join(floor_access_switch_sns_raw_main)}"
        )
    if is_all_areas_mode:
        print(
            "INFO: 'All Areas' mode active. In-scope devices will be colored by lab area."
        )

    is_special_unmanaged_area_mode = False
    if (
        not is_all_areas_mode
        and floor_access_switch_sns_raw_main
        and len(floor_access_switch_sns_raw_main) == 1
    ):
        single_fas_sn_for_special_mode = floor_access_switch_sns_raw_main[0]
        cursor_check_managed = conn_main_orch.cursor()
        cursor_check_managed.execute(
            "SELECT COUNT(*) FROM switches WHERE site = ? AND building = ? AND floor = ? AND lab_area_name = ?",
            (
                target_site_main,
                target_building_main,
                target_floor_main,
                target_area_name_main,
            ),
        )
        managed_switches_in_area_count = cursor_check_managed.fetchone()[0]
        if managed_switches_in_area_count == 0:
            is_special_unmanaged_area_mode = True
            print(
                f"INFO: Detected 'Unmanaged Area with External FAS' mode for {target_area_name_main}."
            )

    G_diagram_final_main = nx.Graph()

    if is_special_unmanaged_area_mode:
        print("\nStep 1 (Special Mode): Building graph for Unmanaged Area with FAS...")
        single_fas_sn = floor_access_switch_sns_raw_main[0]
        fas_node_id_special_mode = load_single_managed_switch_by_sn(
            conn_main_orch,
            G_diagram_final_main,
            single_fas_sn,
            target_site=target_site_main,
            target_building=target_building_main,
            target_floor=target_floor_main,
            target_area_name=target_area_name_main,
            is_designated_fas=True,
        )
        if not fas_node_id_special_mode:
            print(
                f"ERROR: Could not load designated FAS {single_fas_sn}. Aborting diagram for this area."
            )
            uplink_json_filepath_empty_special = os.path.join(
                OUTPUT_DIR, f"{final_output_filename_base_main}_uplinks.json"
            )
            try:
                os.makedirs(
                    os.path.dirname(uplink_json_filepath_empty_special), exist_ok=True
                )
                with open(uplink_json_filepath_empty_special, "w") as f_json_empty:
                    json.dump([], f_json_empty, indent=2)
            except Exception as e_json_save:
                print(f"  Error saving empty uplink details JSON: {e_json_save}")
            return
        unmanaged_node_ids_in_area = load_unmanaged_switches_for_area(
            conn_main_orch,
            G_diagram_final_main,
            target_site_main,
            target_building_main,
            target_floor_main,
            target_area_name_main,
        )
        if unmanaged_node_ids_in_area:
            connect_unmanaged_switches_to_fas(
                conn_main_orch,
                G_diagram_final_main,
                fas_node_id_special_mode,
                unmanaged_node_ids_in_area,
            )
        print("\nStep 1.1 (Special Mode): Loading and connecting Access Points...")
        connect_access_points_to_graph(
            conn_main_orch,
            G_diagram_final_main,
            target_site_main,
            target_building_main,
            target_floor_main,
            target_area_name_main,
            floor_access_switch_sns_raw_param=floor_access_switch_sns_raw_main,
        )
        if G_diagram_final_main.has_node(
            fas_node_id_special_mode
        ) and not G_diagram_final_main.nodes[fas_node_id_special_mode].get(
            "inferred_role"
        ):
            fas_device_type = G_diagram_final_main.nodes[fas_node_id_special_mode].get(
                "device_type", "Switch"
            )
            G_diagram_final_main.nodes[fas_node_id_special_mode]["inferred_role"] = (
                "Router" if fas_device_type == "Router" else "Distribution"
            )
        if G_diagram_final_main.has_node(fas_node_id_special_mode):
            G_diagram_final_main.nodes[fas_node_id_special_mode]["is_fas"] = True
            G_diagram_final_main.nodes[fas_node_id_special_mode][
                "is_fas_for_unmanaged_area_diagram"
            ] = True
        print("\nSteps 2-4 (Special Mode): Skipping complex topology inference.")
    else:
        G_full_topology_main = nx.Graph()
        external_node_id_cache_main: Dict[Tuple[str, str], str] = {}
        if floor_access_switch_sns_raw_main:
            print(
                f"\nPre-loading designated Floor Access Switch(es): {', '.join(floor_access_switch_sns_raw_main)}..."
            )
            for fas_sn in floor_access_switch_sns_raw_main:
                load_single_managed_switch_by_sn(
                    conn_main_orch,
                    G_full_topology_main,
                    fas_sn,
                    target_site=target_site_main,
                    target_building=target_building_main,
                    target_floor=target_floor_main,
                    target_area_name=target_area_name_main,
                    is_designated_fas=True,
                )
        print("\nStep 1: Building initial graph structure (G_full_topology)...")
        load_managed_switches_to_graph(
            conn_main_orch,
            G_full_topology_main,
            target_site_main,
            target_building_main,
            target_floor_main,
            target_area_name_main,
        )
        process_lldp_cdp_neighbors_to_graph(
            conn_main_orch,
            G_full_topology_main,
            external_node_id_cache_main,
            target_site_main,
            target_building_main,
            target_floor_main,
            target_area_name_main,
        )
        print("\nStep 2: Initializing roles and inferring MAC-based links...")
        prelim_roles_map_main = get_preliminary_switch_roles(G_full_topology_main)
        for sw_node_id_prelim_main, role_prelim_main in prelim_roles_map_main.items():
            if (
                G_full_topology_main.has_node(sw_node_id_prelim_main)
                and G_full_topology_main.nodes[sw_node_id_prelim_main].get(
                    "node_origin"
                )
                == "managed_switch"
            ):
                G_full_topology_main.nodes[sw_node_id_prelim_main]["prelim_role"] = (
                    role_prelim_main
                )
        run_iterative_mac_inference_strategy(
            conn_main_orch,
            G_full_topology_main,
            prelim_roles_map_main,
            fas_raw_sn_iter=floor_access_switch_sns_raw_main[0]
            if floor_access_switch_sns_raw_main
            else None,
            target_site_iter=target_site_main,
            target_building_iter=target_building_main,
            target_floor_iter=target_floor_main,
        )
        connect_access_points_to_graph(
            conn_main_orch,
            G_full_topology_main,
            target_site_main,
            target_building_main,
            target_floor_main,
            target_area_name_main,
            floor_access_switch_sns_raw_param=floor_access_switch_sns_raw_main,
        )
        if (
            include_unmanaged_devices_in_hybrid_mode
            and floor_access_switch_sns_raw_main
        ):
            print(
                "\nStep 2.5 (Hybrid Mode): Loading and connecting unmanaged devices..."
            )
            single_fas_sn_for_hybrid = floor_access_switch_sns_raw_main[0]
            fas_node_id_in_graph_hybrid = None
            for nid_hybrid, ndata_hybrid in G_full_topology_main.nodes(data=True):
                if (
                    ndata_hybrid.get("raw_id") == single_fas_sn_for_hybrid
                    and ndata_hybrid.get("node_origin") == "managed_switch"
                ):
                    fas_node_id_in_graph_hybrid = nid_hybrid
                    break
            if fas_node_id_in_graph_hybrid:
                unmanaged_node_ids_hybrid = load_unmanaged_switches_for_area(
                    conn_main_orch,
                    G_full_topology_main,
                    target_site_main,
                    target_building_main,
                    target_floor_main,
                    target_area_name_main,
                )
                if unmanaged_node_ids_hybrid:
                    connect_unmanaged_switches_to_fas(
                        conn_main_orch,
                        G_full_topology_main,
                        fas_node_id_in_graph_hybrid,
                        unmanaged_node_ids_hybrid,
                    )
            else:
                print(
                    "  WARNING: Could not perform hybrid mode action. The specified FAS was not found in the graph."
                )
        print("\nStep 3: Inferring final switch roles (FAS-aware)...")
        infer_switch_roles(
            G_full_topology_main, fas_raw_sns=floor_access_switch_sns_raw_main
        )
        print(
            "\nStep 4: Optionally filtering graph for final diagram (G_diagram_final)..."
        )
        if filter_diagram_main:
            print(
                "  Filtering enabled. Pruning graph to focus on the selected scope and its immediate connections."
            )
            nodes_to_keep_for_diagram_main: Set[str] = set()
            if floor_access_switch_sns_raw_main:
                for fas_sn_keep in floor_access_switch_sns_raw_main:
                    for n, d in G_full_topology_main.nodes(data=True):
                        if d.get("raw_id") == fas_sn_keep:
                            nodes_to_keep_for_diagram_main.add(n)
                            break
            managed_switch_nodes_in_scope_main = {
                n_ms_main
                for n_ms_main, a_ms_main in G_full_topology_main.nodes(data=True)
                if a_ms_main.get("node_origin") == "managed_switch"
                and a_ms_main.get("diagram_class")
                in ["managed_in_scope", "router_in_scope"]
            }
            nodes_to_keep_for_diagram_main.update(managed_switch_nodes_in_scope_main)
            nodes_to_keep_for_diagram_main.update(
                {
                    n_ap_keep_main
                    for n_ap_keep_main, a_ap_keep_main in G_full_topology_main.nodes(
                        data=True
                    )
                    if a_ap_keep_main.get("node_origin") == "access_point"
                    and a_ap_keep_main.get("diagram_class") == "ap_in_scope"
                }
            )
            if include_unmanaged_devices_in_hybrid_mode:
                nodes_to_keep_for_diagram_main.update(
                    {
                        n_unm_keep
                        for n_unm_keep, a_unm_keep in G_full_topology_main.nodes(
                            data=True
                        )
                        if a_unm_keep.get("node_origin")
                        == "unmanaged_switch_special_mode"
                    }
                )
            potential_unsurveyed_sw_nodes_G_full_main = {
                n_usw_main
                for n_usw_main, a_usw_main in G_full_topology_main.nodes(data=True)
                if a_usw_main.get("node_origin") == "external_lldp_neighbor"
                and a_usw_main.get("is_potential_network_device")
            }
            for unsurveyed_sw_node_id_main in potential_unsurveyed_sw_nodes_G_full_main:
                if G_full_topology_main.has_node(unsurveyed_sw_node_id_main):
                    for neighbor_of_usw_node_id_main in list(
                        G_full_topology_main.neighbors(unsurveyed_sw_node_id_main)
                    ):
                        if (
                            neighbor_of_usw_node_id_main
                            in managed_switch_nodes_in_scope_main
                            and G_full_topology_main.has_edge(
                                unsurveyed_sw_node_id_main, neighbor_of_usw_node_id_main
                            )
                        ):
                            nodes_to_keep_for_diagram_main.add(
                                unsurveyed_sw_node_id_main
                            )
                            break
            for in_scope_node_id_filter in list(nodes_to_keep_for_diagram_main):
                if (
                    G_full_topology_main.has_node(in_scope_node_id_filter)
                    and G_full_topology_main.nodes[in_scope_node_id_filter].get(
                        "node_origin"
                    )
                    == "managed_switch"
                ):
                    for neighbor_id_filter in G_full_topology_main.neighbors(
                        in_scope_node_id_filter
                    ):
                        if (
                            G_full_topology_main.has_node(neighbor_id_filter)
                            and G_full_topology_main.nodes[neighbor_id_filter].get(
                                "node_origin"
                            )
                            == "managed_switch"
                            and G_full_topology_main.nodes[neighbor_id_filter].get(
                                "diagram_class"
                            )
                            not in ["managed_in_scope", "router_in_scope"]
                            and G_full_topology_main.get_edge_data(
                                in_scope_node_id_filter, neighbor_id_filter, {}
                            ).get("connection_type")
                            == "lldp_cdp"
                        ):
                            nodes_to_keep_for_diagram_main.add(neighbor_id_filter)
            G_diagram_final_main = G_full_topology_main.subgraph(
                list(nodes_to_keep_for_diagram_main)
            ).copy()
        else:
            print(
                "  Filtering disabled. Using all initially loaded devices for the diagram."
            )
            G_diagram_final_main = G_full_topology_main.copy()

    if not G_diagram_final_main.nodes():
        empty_graph_message_detail = (
            "for special unmanaged area mode"
            if is_special_unmanaged_area_mode
            else (
                "after filtering"
                if filter_diagram_main and not is_special_unmanaged_area_mode
                else "from the initial load"
            )
        )
        print(
            f"\nNo nodes remaining for the diagram {empty_graph_message_detail}. Skipping image and report generation."
        )
        uplink_json_filepath_final_empty_main = os.path.join(
            OUTPUT_DIR, f"{final_output_filename_base_main}_uplinks.json"
        )
        try:
            os.makedirs(
                os.path.dirname(uplink_json_filepath_final_empty_main), exist_ok=True
            )
            with open(
                uplink_json_filepath_final_empty_main, "w"
            ) as f_json_empty_final_main:
                json.dump([], f_json_empty_final_main, indent=2)
        except Exception as e_json_empty_final_main_save:
            print(
                f"  Error saving empty uplink details JSON: {e_json_empty_final_main_save}"
            )
        return

    print("\nStep 5: Generating Pydot output image...")
    print(
        f"  Diagram content (G_diagram_final_main): {G_diagram_final_main.number_of_nodes()} nodes, {G_diagram_final_main.number_of_edges()} edges."
    )
    generate_pydot_output(
        G_diagram_final_main,
        output_filepath_image_main,
        floor_access_switch_sns_raw_main,
        output_format_main,
        "sfdp",
        graph_direction_main,
        is_special_unmanaged_mode=is_special_unmanaged_area_mode,
        is_all_areas_mode=is_all_areas_mode,
    )

    print("\nStep 6: Generating Uplink Report & Updating DB...")
    generate_uplink_report_data_from_diagram(
        conn_main_orch,
        G_diagram_final_main,
        floor_access_switch_sns_raw_main,
        final_output_filename_base_main,
    )

    print("\nStep 7: Triggering MOONID propagation...")
    trigger_moonid_propagation(
        conn_main_orch,
        G_diagram_final_main,
        fas_raw_sns_prop=floor_access_switch_sns_raw_main,
    )

    print(
        f"\n--- Diagram generation process complete for: {target_site_main}/{target_building_main}/{target_floor_main}/{scope_display} ---"
    )


def exit_gracefully_main(db_conn_main_exit: Optional[sqlite3.Connection]):
    if db_conn_main_exit:
        try:
            db_conn_main_exit.close()
            print("\nDB connection closed.")
        except sqlite3.Error:
            pass
    print("Exiting script.")
    exit()


if __name__ == "__main__":
    print("--- Network Diagram Generator (Main Script) ---")
    db_connection_main = get_db_connection(DB_FILE)
    if db_connection_main:
        selected_site, selected_building, selected_floor, selected_area = (
            None,
            None,
            None,
            None,
        )
        try:
            db_cursor_main_script = db_connection_main.cursor()
            sites_list_main_query = """
                SELECT DISTINCT site FROM switches WHERE site IS NOT NULL AND site != ''
                UNION
                SELECT DISTINCT site FROM logged_other_devices WHERE site IS NOT NULL AND site != ''
                UNION
                SELECT DISTINCT site FROM logged_access_points WHERE site IS NOT NULL AND site != ''
                ORDER BY site;
            """
            sites_list_main = [
                r["site"] for r in db_cursor_main_script.execute(sites_list_main_query)
            ]
            if not sites_list_main:
                print("No sites found in database. Exiting.")
                exit_gracefully_main(db_connection_main)
            print("\nAvailable Sites:")
            [print(f"  {i + 1}: {s}") for i, s in enumerate(sites_list_main)]
            while selected_site is None:
                try:
                    choice_s = input(
                        f"Select site (1-{len(sites_list_main)}): "
                    ).strip()
                    if choice_s:
                        selected_site = sites_list_main[int(choice_s) - 1]
                except (ValueError, IndexError):
                    print("Invalid choice.")
                except (KeyboardInterrupt, EOFError):
                    exit_gracefully_main(db_connection_main)

            buildings_list_main_query = """
                SELECT DISTINCT building FROM switches WHERE site = ? AND building IS NOT NULL AND building != ''
                UNION
                SELECT DISTINCT building FROM logged_other_devices WHERE site = ? AND building IS NOT NULL AND building != ''
                UNION
                SELECT DISTINCT building FROM logged_access_points WHERE site = ? AND building IS NOT NULL AND building != ''
                ORDER BY building;
            """
            buildings_list_main = [
                r["building"]
                for r in db_cursor_main_script.execute(
                    buildings_list_main_query,
                    (selected_site, selected_site, selected_site),
                )
            ]
            if not buildings_list_main:
                print(f"No buildings for site '{selected_site}'. Exiting.")
                exit_gracefully_main(db_connection_main)
            print(f"\nBuildings in {selected_site}:")
            [print(f"  {i + 1}: {b}") for i, b in enumerate(buildings_list_main)]
            while selected_building is None:
                try:
                    choice_b = input(
                        f"Select building (1-{len(buildings_list_main)}): "
                    ).strip()
                    if choice_b:
                        selected_building = buildings_list_main[int(choice_b) - 1]
                except (ValueError, IndexError):
                    print("Invalid choice.")
                except (KeyboardInterrupt, EOFError):
                    exit_gracefully_main(db_connection_main)

            floors_list_main_query = """
                SELECT DISTINCT floor FROM switches WHERE site = ? AND building = ? AND floor IS NOT NULL AND floor != ''
                UNION
                SELECT DISTINCT floor FROM logged_other_devices WHERE site = ? AND building = ? AND floor IS NOT NULL AND floor != ''
                UNION
                SELECT DISTINCT floor FROM logged_access_points WHERE site = ? AND building = ? AND floor IS NOT NULL AND floor != ''
                ORDER BY floor;
            """
            floors_list_main = [
                r["floor"]
                for r in db_cursor_main_script.execute(
                    floors_list_main_query,
                    (
                        selected_site,
                        selected_building,
                        selected_site,
                        selected_building,
                        selected_site,
                        selected_building,
                    ),
                )
            ]
            if not floors_list_main:
                print(f"No floors for {selected_site}/{selected_building}. Exiting.")
                exit_gracefully_main(db_connection_main)
            print(f"\nFloors in {selected_site}/{selected_building}:")
            [print(f"  {i + 1}: {f}") for i, f in enumerate(floors_list_main)]
            while selected_floor is None:
                try:
                    choice_f = input(
                        f"Select floor (1-{len(floors_list_main)}): "
                    ).strip()
                    if choice_f:
                        selected_floor = floors_list_main[int(choice_f) - 1]
                except (ValueError, IndexError):
                    print("Invalid choice.")
                except (KeyboardInterrupt, EOFError):
                    exit_gracefully_main(db_connection_main)

            query_areas_script_main = """
                SELECT DISTINCT lab_area_name FROM (
                    SELECT lab_area_name FROM switches WHERE site=? AND building=? AND floor=? AND lab_area_name IS NOT NULL AND lab_area_name!=''
                    UNION
                    SELECT lab_area_name FROM logged_access_points WHERE site=? AND building=? AND floor=? AND lab_area_name IS NOT NULL AND lab_area_name!=''
                    UNION
                    SELECT lab_area_name FROM logged_other_devices WHERE site=? AND building=? AND floor=? AND lab_area_name IS NOT NULL AND lab_area_name!=''
                ) WHERE lab_area_name IS NOT NULL AND lab_area_name!='' ORDER BY lab_area_name;
            """
            lab_areas_list_main_distinct = [
                r["lab_area_name"]
                for r in db_cursor_main_script.execute(
                    query_areas_script_main,
                    (
                        selected_site,
                        selected_building,
                        selected_floor,
                        selected_site,
                        selected_building,
                        selected_floor,
                        selected_site,
                        selected_building,
                        selected_floor,
                    ),
                )
            ]
            area_options_display = lab_areas_list_main_distinct.copy()
            area_options_display.append("ALL Areas on this Floor")
            print(
                f"\nLab Areas in {selected_site}/{selected_building}/{selected_floor}:"
            )
            for i, area_name_disp in enumerate(area_options_display):
                print(f"  {i + 1}: {area_name_disp}")
            while selected_area is None:
                try:
                    choice_a = input(
                        f"Select lab area (1-{len(area_options_display)}): "
                    ).strip()
                    if choice_a:
                        chosen_index = int(choice_a) - 1
                        if 0 <= chosen_index < len(area_options_display):
                            selected_area_option = area_options_display[chosen_index]
                            selected_area = (
                                ALL_AREAS_MARKER
                                if selected_area_option == "ALL Areas on this Floor"
                                else selected_area_option
                            )
                except (ValueError, IndexError):
                    print("Invalid choice.")
                except (KeyboardInterrupt, EOFError):
                    exit_gracefully_main(db_connection_main)

            fas_sns_input_raw_list: Optional[List[str]] = None
            multi_fas_mode = False
            try:
                multi_fas_choice = (
                    input(
                        "\nAre you specifying multiple Floor Access Switches? (Yes/No, default: No): "
                    )
                    .strip()
                    .lower()
                )
                if multi_fas_choice in ["y", "yes"]:
                    multi_fas_mode = True
            except (KeyboardInterrupt, EOFError):
                exit_gracefully_main(db_connection_main)

            include_unmanaged_devices_hybrid_mode = False
            if multi_fas_mode:
                print("\n--- Multi-FAS Mode Selected (for fully managed networks) ---")
                try:
                    fas_sn_input_str = (
                        input("Enter comma-separated list of FAS Serial Numbers: ")
                        .strip()
                        .upper()
                    )
                    if fas_sn_input_str:
                        fas_sns_input_raw_list = [
                            sn.strip()
                            for sn in fas_sn_input_str.split(",")
                            if sn.strip()
                        ]
                    if not fas_sns_input_raw_list:
                        print("No SNs entered. Continuing without specified FASs.")
                        fas_sns_input_raw_list = None
                except (KeyboardInterrupt, EOFError):
                    print("\nFAS SN input aborted.")
                    fas_sns_input_raw_list = None
            else:
                print("\n--- Single-FAS Mode Selected ---")
                try:
                    single_fas_sn_str = (
                        input(
                            "Enter SN of Floor Access Switch (optional, Enter to skip): "
                        )
                        .strip()
                        .upper()
                    )
                    if single_fas_sn_str:
                        fas_sns_input_raw_list = [single_fas_sn_str]
                    else:
                        fas_sns_input_raw_list = None
                except (KeyboardInterrupt, EOFError):
                    print("\nFAS SN input aborted.")
                    fas_sns_input_raw_list = None
                if fas_sns_input_raw_list:
                    unmanaged_dev_params = [
                        selected_site,
                        selected_building,
                        selected_floor,
                    ]
                    unmanaged_dev_query = "SELECT COUNT(*) FROM logged_other_devices WHERE site = ? AND building = ? AND floor = ?"
                    if selected_area != ALL_AREAS_MARKER:
                        unmanaged_dev_query += " AND lab_area_name = ?"
                        unmanaged_dev_params.append(selected_area)
                    db_cursor_main_script.execute(
                        unmanaged_dev_query, tuple(unmanaged_dev_params)
                    )
                    unmanaged_devices_count = db_cursor_main_script.fetchone()[0]
                    if unmanaged_devices_count > 0:
                        try:
                            hybrid_choice_str = (
                                input(
                                    f"\nFound {unmanaged_devices_count} unmanaged/other devices. Include them? (Yes/No, default: No): "
                                )
                                .strip()
                                .lower()
                            )
                            if hybrid_choice_str in ["yes", "y"]:
                                include_unmanaged_devices_hybrid_mode = True
                        except (KeyboardInterrupt, EOFError):
                            pass

            filter_diagram_choice_input: bool = True
            try:
                filter_choice_str = (
                    input(
                        "\nApply standard filtering to the diagram? (Yes/No, default: Yes): "
                    )
                    .strip()
                    .lower()
                )
                if filter_choice_str in ["no", "n"]:
                    filter_diagram_choice_input = False
            except (KeyboardInterrupt, EOFError):
                pass

            generate_network_diagram_for_lab_area(
                db_connection_main,
                selected_site,
                selected_building,
                selected_floor,
                selected_area,
                floor_access_switch_sns_raw_main=fas_sns_input_raw_list,
                filter_diagram_main=filter_diagram_choice_input,
                output_format_main=DEFAULT_OUTPUT_FORMAT_EXT.lstrip("."),
                graph_direction_main=DEFAULT_GRAPH_DIRECTION,
                include_unmanaged_devices_in_hybrid_mode=include_unmanaged_devices_hybrid_mode,
            )
        except Exception as e_main_script_block:
            print(
                f"An unexpected error occurred: {type(e_main_script_block).__name__} - {e_main_script_block}"
            )
            import traceback

            traceback.print_exc()
        finally:
            if db_connection_main:
                try:
                    db_connection_main.close()
                    print("\nDatabase connection closed.")
                except sqlite3.Error:
                    pass
    else:
        print(f"Failed to connect to the database: {DB_FILE}")
    print("--- Network Diagram Generator Script Finished ---")
