# load_validated_json_to_db.py
import json
import logging
import os
import sqlite3

# --- Configuration ---
JSON_FOLDER = (
    "validated_jsons_api_structured_MAC_CHUNKED_MP"  # Base folder to search for JSONs
)
DB_FILE = "network_survey.db"

DELETE_EXISTING_SWITCH_DATA_BEFORE_LOAD = True
TARGET_JSON_SUFFIX = "_validated.json"
IP_CONCAT_SEPARATOR = ", "

# --- Logging Setup ---
log_format = "%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
logging.basicConfig(level=logging.INFO, format=log_format)

# --- Helper Functions ---


def get_json_files(base_folder_path):
    """Recursively finds all files ending with TARGET_JSON_SUFFIX in the specified folder and its subdirectories."""
    json_files_found = []
    if not os.path.isdir(base_folder_path):
        logging.error(
            f"JSON base folder not found: {os.path.abspath(base_folder_path)}"
        )
        return json_files_found

    logging.info(
        f"Recursively searching for files ending with '{TARGET_JSON_SUFFIX}' in '{os.path.abspath(base_folder_path)}'..."
    )
    for root, _, files in os.walk(base_folder_path):
        for file in files:
            if file.lower().endswith(TARGET_JSON_SUFFIX.lower()):
                json_files_found.append(os.path.join(root, file))

    logging.info(
        f"Found {len(json_files_found)} '{TARGET_JSON_SUFFIX}' files.")
    return sorted(json_files_found)


def delete_switch_data(cursor, serial_number):
    if not serial_number:
        logging.warning(
            "Attempted to delete data with empty serial number. Skipping.")
        return
    logging.debug(
        f"Attempting to delete existing data for SN: {serial_number}")
    try:
        cursor.execute(
            "DELETE FROM switches WHERE serial_number = ?", (serial_number,))
        # Cascade delete should handle related tables: interfaces, vlans, ip_interfaces, mac_address_table,
        # arp_table, lldp_cdp_neighbors, ip_routing_table, switch_moonid_map.
        # discovered_unassigned_networks.first_seen_switch_sn is ON DELETE SET NULL.
        logging.info(
            f"Successfully deleted/unlinked existing data for SN: {serial_number} (via cascade/set null)."
        )
    except sqlite3.Error as e:
        logging.error(
            f"Database error deleting data for SN {serial_number}: {e}")
        raise


# --- Data Loading Functions ---
def load_switch_details(cursor, data):
    switch_data = data.get("switch_details")
    json_filename_for_log = (
        os.path.basename(data.get("json_filepath", "Unknown"))
        if isinstance(data, dict)
        else "Unknown"
    )

    if not switch_data:
        logging.warning(
            f"JSON missing 'switch_details' in file {json_filename_for_log}. Skipping switch load."
        )
        return None
    sn = switch_data.get("serial_number")
    if not sn:
        logging.error(
            f"JSON 'switch_details' missing 'serial_number' in file {json_filename_for_log}. Cannot process this file."
        )
        raise ValueError("Missing mandatory serial_number in switch_details")

    # Ensure all required fields are present for DB insertion, using None if missing from JSON
    # to avoid KeyError and rely on DB defaults or NULL constraints.
    sql = """
        INSERT OR REPLACE INTO switches (
            serial_number, hostname, model, make, device_type, base_mac_address,
            lab_area_name, floor, site, building, location_notes, rack_type_detail,
            access_level, ip_version_routing, running_config_captured, is_poe_capable,
            handles_internal_vlans, log_filename_validated, survey_timestamp,
            user_verified_total_ports, user_verified_used_ports,
            is_switch_standard, uplink_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
    """
    try:
        cursor.execute(
            sql,
            (
                sn,
                switch_data.get("hostname"),
                switch_data.get("model"),
                switch_data.get("make"),
                switch_data.get("device_type"),
                switch_data.get("base_mac_address"),
                switch_data.get("lab_area_name"),
                switch_data.get("floor"),
                switch_data.get("site"),
                switch_data.get("building"),
                switch_data.get("location_notes"),
                switch_data.get("rack_type_detail"),
                switch_data.get("access_level"),
                switch_data.get("ip_version_routing"),
                switch_data.get("running_config_captured"),
                switch_data.get("is_poe_capable"),
                switch_data.get("handles_internal_vlans"),
                switch_data.get("log_filename_validated"),
                switch_data.get("survey_timestamp"),
                switch_data.get("user_verified_total_ports"),
                switch_data.get("user_verified_used_ports"),
            ),
        )
        logging.info(f"Loaded/Replaced switch details for SN: {sn}")
        return sn
    except sqlite3.IntegrityError as ie:
        logging.error(
            f"DB IntegrityError loading switch details for SN {sn} from {json_filename_for_log}: {ie}"
        )
        logging.error(
            f"  Location: {switch_data.get('site')}/{switch_data.get('building')}/{switch_data.get('floor')}/{switch_data.get('lab_area_name')}"
        )
        logging.error(
            "  Ensure this location exists in 'lab_areas' table and matches exactly."
        )
        raise
    except sqlite3.Error as e:
        logging.error(
            f"DB Error loading switch details for SN {sn} from {json_filename_for_log}: {e}"
        )
        raise
    except (
        Exception
    ) as e:  # Catch other potential errors during .get() or value preparation
        logging.error(
            f"Unexpected error preparing switch details for SN {sn} from {json_filename_for_log}: {e}"
        )
        raise


def load_interfaces(cursor, serial_number, data):
    interfaces_data = data.get("interfaces", [])
    json_filename_for_log = (
        os.path.basename(data.get("json_filepath", "Unknown"))
        if isinstance(data, dict)
        else "Unknown"
    )
    if not interfaces_data:
        logging.debug(
            f"No interface data found for SN {serial_number} in {json_filename_for_log}."
        )
        return

    sql = """
        INSERT INTO interfaces (
            switch_serial_number, interface_name, status, vlan, duplex, speed, type, description, is_uplink
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
    """
    rows_to_insert = []
    for iface in interfaces_data:
        if not iface.get("interface_name"):
            logging.warning(
                f"Skipping interface for SN {serial_number} from {json_filename_for_log} due to missing name: {iface}"
            )
            continue
        rows_to_insert.append(
            (
                serial_number,
                iface.get("interface_name"),
                iface.get("status"),
                iface.get("vlan"),
                iface.get("duplex"),
                iface.get("speed"),
                iface.get("type"),
                iface.get("description"),
            )
        )
    if rows_to_insert:
        try:
            cursor.executemany(sql, rows_to_insert)
            logging.info(
                f"Loaded {len(rows_to_insert)} interfaces for SN: {serial_number}"
            )
        except sqlite3.Error as e:
            logging.error(
                f"DB Error loading interfaces for SN {serial_number} from {json_filename_for_log}: {e}"
            )
            raise


def load_vlans(cursor, serial_number, data):
    vlans_data = data.get("vlans", [])
    json_filename_for_log = (
        os.path.basename(data.get("json_filepath", "Unknown"))
        if isinstance(data, dict)
        else "Unknown"
    )
    if not vlans_data:
        logging.debug(
            f"No VLAN data found for SN {serial_number} in {json_filename_for_log}."
        )
        return

    sql = """
        INSERT INTO vlans (
            switch_serial_number, vlan_id, vlan_name, status, ports_associated_text
        ) VALUES (?, ?, ?, ?, ?)
    """
    rows_to_insert = []
    for vlan in vlans_data:
        vlan_id = vlan.get("vlan_id")
        if vlan_id is None:
            logging.warning(
                f"Skipping vlan for SN {serial_number} from {json_filename_for_log} due to missing vlan_id: {vlan}"
            )
            continue
        try:
            vlan_id_int = int(vlan_id)
        except (ValueError, TypeError):
            logging.warning(
                f"Skipping vlan for SN {serial_number} from {json_filename_for_log} due to non-integer vlan_id '{vlan_id}': {vlan}"
            )
            continue
        rows_to_insert.append(
            (
                serial_number,
                vlan_id_int,
                vlan.get("vlan_name"),
                vlan.get("status"),
                vlan.get("ports_associated_text"),
            )
        )
    if rows_to_insert:
        try:
            cursor.executemany(sql, rows_to_insert)
            logging.info(
                f"Loaded {len(rows_to_insert)} vlans for SN: {serial_number}")
        except sqlite3.Error as e:
            logging.error(
                f"DB Error loading vlans for SN {serial_number} from {json_filename_for_log}: {e}"
            )
            raise


def load_ip_interfaces(cursor, serial_number, data):
    ip_interfaces_data = data.get("ip_interfaces", [])
    json_filename_for_log = (
        os.path.basename(data.get("json_filepath", "Unknown"))
        if isinstance(data, dict)
        else "Unknown"
    )
    if not ip_interfaces_data:
        logging.debug(
            f"No IP interface data found for SN {serial_number} in {json_filename_for_log}."
        )
        return

    aggregated_interfaces = {}
    for ip_iface in ip_interfaces_data:
        interface_name_val = ip_iface.get("interface_name")
        ip_address_val = ip_iface.get("ip_address_with_prefix")

        if not interface_name_val:
            logging.warning(
                f"Skipping IP interface for SN {serial_number} from {json_filename_for_log} due to missing interface_name: {ip_iface}"
            )
            continue
        if not ip_address_val:  # If primary IP is missing, this specific entry might be problematic for aggregation
            logging.warning(
                f"IP interface entry for SN {serial_number}, Interface '{interface_name_val}' from {json_filename_for_log} has no ip_address_with_prefix: {ip_iface}. This specific entry won't contribute an IP."
            )
            # If it's the first time we see this interface_name, we still initialize it.
            if interface_name_val not in aggregated_interfaces:
                aggregated_interfaces[interface_name_val] = {
                    "mac_address": ip_iface.get("mac_address"),
                    "status": ip_iface.get("status"),
                    "protocol_status": ip_iface.get("protocol_status"),
                    "is_management": ip_iface.get("is_management"),
                    "ip_addresses": [],
                }
            continue  # Skip adding this particular null IP

        if interface_name_val not in aggregated_interfaces:
            aggregated_interfaces[interface_name_val] = {
                "mac_address": ip_iface.get("mac_address"),
                "status": ip_iface.get("status"),
                "protocol_status": ip_iface.get("protocol_status"),
                "is_management": ip_iface.get("is_management"),
                "ip_addresses": [],
            }
        aggregated_interfaces[interface_name_val]["ip_addresses"].append(
            ip_address_val)

    sql = """
        INSERT INTO ip_interfaces (
            switch_serial_number, interface_name, mac_address, ip_address_with_prefix,
            status, protocol_status, is_management
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    rows_to_insert = []
    for iface_name, details in aggregated_interfaces.items():
        concatenated_ips = (
            IP_CONCAT_SEPARATOR.join(
                sorted(list(set(details["ip_addresses"]))))
            if details["ip_addresses"]
            else None
        )
        if (
            concatenated_ips is None
        ):  # Strict: if no valid IPs found for this interface name, skip it.
            logging.warning(
                f"Skipping aggregated IP interface '{iface_name}' for SN {serial_number} from {json_filename_for_log} as no valid IPs were found for it."
            )
            continue
        rows_to_insert.append(
            (
                serial_number,
                iface_name,
                details["mac_address"],
                concatenated_ips,
                details["status"],
                details["protocol_status"],
                details["is_management"],
            )
        )

    if rows_to_insert:
        try:
            cursor.executemany(sql, rows_to_insert)
            logging.info(
                f"Loaded {len(rows_to_insert)} aggregated IP interfaces for SN: {serial_number}"
            )
        except sqlite3.Error as e:  # More specific errors like IntegrityError might be caught by main try-except
            logging.error(
                f"DB Error loading IP interfaces for SN {serial_number} from {json_filename_for_log}: {e}"
            )
            raise


def load_mac_entries(cursor, serial_number, data):
    mac_entries_data = data.get("mac_entries", [])
    json_filename_for_log = (
        os.path.basename(data.get("json_filepath", "Unknown"))
        if isinstance(data, dict)
        else "Unknown"
    )
    if not mac_entries_data:
        logging.debug(
            f"No MAC entry data found for SN {serial_number} in {json_filename_for_log}."
        )
        return

    sql = """
        INSERT INTO mac_address_table (
            switch_serial_number, mac_address, interface_name, vlan_id, type
        ) VALUES (?, ?, ?, ?, ?)
    """
    rows_to_insert = []
    for entry in mac_entries_data:
        if (
            not entry.get("mac_address")
            or not entry.get("interface_name")
            or entry.get("vlan_id") is None
        ):
            logging.warning(
                f"Skipping MAC entry for SN {serial_number} from {json_filename_for_log} due to missing fields: {entry}"
            )
            continue
        try:
            vlan_id_int = int(entry["vlan_id"])
        except (ValueError, TypeError):
            logging.warning(
                f"Skipping MAC entry for SN {serial_number} from {json_filename_for_log} due to non-integer vlan_id '{entry['vlan_id']}': {entry}"
            )
            continue
        rows_to_insert.append(
            (
                serial_number,
                entry.get("mac_address"),
                entry.get("interface_name"),
                vlan_id_int,
                entry.get("type"),
            )
        )
    if rows_to_insert:
        try:
            cursor.executemany(sql, rows_to_insert)
            logging.info(
                f"Loaded {len(rows_to_insert)} MAC entries for SN: {serial_number}"
            )
        except sqlite3.Error as e:
            logging.error(
                f"DB Error loading MAC entries for SN {serial_number} from {json_filename_for_log}: {e}"
            )
            raise


def load_arp_entries(cursor, serial_number, data):
    arp_entries_data = data.get("arp_entries", [])
    json_filename_for_log = (
        os.path.basename(data.get("json_filepath", "Unknown"))
        if isinstance(data, dict)
        else "Unknown"
    )
    if not arp_entries_data:
        logging.debug(
            f"No ARP entry data found for SN {serial_number} in {json_filename_for_log}."
        )
        return

    sql = """
        INSERT INTO arp_table (
            switch_serial_number, ip_address, mac_address, interface_name, vlan_id, type, age_in_seconds
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    rows_to_insert = []
    for entry in arp_entries_data:
        # MODIFIED: Check for both ip_address and mac_address
        if not entry.get("ip_address") or not entry.get("mac_address"):
            missing_fields = []
            if not entry.get("ip_address"):
                missing_fields.append("IP address")
            if not entry.get("mac_address"):
                missing_fields.append("MAC address")
            logging.warning(
                f"Skipping ARP entry for SN {serial_number} from {json_filename_for_log} due to missing {' and '.join(missing_fields)}: {entry}"
            )
            continue

        vlan_id_int = None
        age_int = None
        try:
            if entry.get("vlan_id") is not None:
                vlan_id_int = int(entry["vlan_id"])
        except (ValueError, TypeError):
            logging.warning(
                f"Null ARP vlan_id for SN {serial_number} (non-int '{entry.get('vlan_id')}'): {entry}"
            )
        try:
            if entry.get("age_in_seconds") is not None:
                age_int = int(entry["age_in_seconds"])
        except (ValueError, TypeError):
            logging.warning(
                f"Null ARP age for SN {serial_number} (non-int '{entry.get('age_in_seconds')}'): {entry}"
            )
        rows_to_insert.append(
            (
                serial_number,
                entry.get("ip_address"),
                entry.get("mac_address"),
                entry.get("interface_name"),
                vlan_id_int,
                entry.get("type"),
                age_int,
            )
        )
    if rows_to_insert:
        try:
            cursor.executemany(sql, rows_to_insert)
            logging.info(
                f"Loaded {len(rows_to_insert)} ARP entries for SN: {serial_number}"
            )
        except sqlite3.Error as e:
            logging.error(
                f"DB Error loading ARP entries for SN {serial_number} from {json_filename_for_log}: {e}"
            )
            raise


def load_routes(cursor, serial_number, data):
    routes_data = data.get("routes", [])
    json_filename_for_log = (
        os.path.basename(data.get("json_filepath", "Unknown"))
        if isinstance(data, dict)
        else "Unknown"
    )
    if not routes_data:
        logging.debug(
            f"No route data found for SN {serial_number} in {json_filename_for_log}."
        )
        return

    sql = """
        INSERT INTO ip_routing_table (
            switch_serial_number, ip_version, destination_prefix, next_hop_ip,
            outgoing_interface, metric, protocol, is_default_route
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows_to_insert = []
    for route in routes_data:
        if route.get("ip_version") is None or not route.get("destination_prefix"):
            logging.warning(
                f"Skipping route for SN {serial_number} from {json_filename_for_log} due to missing version/prefix: {route}"
            )
            continue
        try:
            ip_version_int = int(route["ip_version"])
            metric_int = (
                int(route["metric"]) if route.get(
                    "metric") is not None else None
            )
            is_default_int = (
                int(route["is_default_route"])
                if route.get("is_default_route") is not None
                else None
            )
        except (ValueError, TypeError) as conv_e:
            logging.warning(
                f"Skipping route for SN {serial_number} from {json_filename_for_log} due to conversion error ({conv_e}): {route}"
            )
            continue
        rows_to_insert.append(
            (
                serial_number,
                ip_version_int,
                route.get("destination_prefix"),
                route.get("next_hop_ip"),
                route.get("outgoing_interface"),
                metric_int,
                route.get("protocol"),
                is_default_int,
            )
        )
    if rows_to_insert:
        try:
            cursor.executemany(sql, rows_to_insert)
            logging.info(
                f"Loaded {len(rows_to_insert)} routes for SN: {serial_number}")
        except sqlite3.Error as e:
            logging.error(
                f"DB Error loading routes for SN {serial_number} from {json_filename_for_log}: {e}"
            )
            raise


def load_moonid_associations(cursor, serial_number, data):
    associations_data = data.get("moonid_associations", [])
    json_filename_for_log = (
        os.path.basename(data.get("json_filepath", "Unknown"))
        if isinstance(data, dict)
        else "Unknown"
    )
    if not associations_data:
        logging.debug(
            f"No MOONID association data found for SN {serial_number} in {json_filename_for_log}."
        )
        return

    sql = """
        INSERT OR IGNORE INTO switch_moonid_map (
            switch_serial_number, moonid, resolution_method, confidence_score
        ) VALUES (?, ?, ?, ?)
    """  # Use INSERT OR IGNORE for UNIQUE constraint (switch_serial_number, moonid)
    rows_to_insert = []
    for assoc in associations_data:
        if not assoc.get("moonid") or not assoc.get("resolution_method"):
            logging.warning(
                f"Skipping MOONID assoc for SN {serial_number} from {json_filename_for_log} due to missing fields: {assoc}"
            )
            continue
        rows_to_insert.append(
            (
                serial_number,
                assoc.get("moonid"),
                assoc.get("resolution_method"),
                assoc.get("confidence_score"),
            )
        )
    if rows_to_insert:
        try:
            cursor.executemany(sql, rows_to_insert)
            # cursor.rowcount for executemany with INSERT OR IGNORE reflects rows actually inserted, not ignored ones.
            logging.info(
                f"Loaded/Attempted {len(rows_to_insert)} MOONID associations for SN: {serial_number} (Inserted: {cursor.rowcount})"
            )
        except (
            sqlite3.IntegrityError
        ) as ie:  # Should be rare due to OR IGNORE if MOONID not in moonid_areas
            logging.error(
                f"DB IntegrityError on MOONID associations for SN {serial_number} from {json_filename_for_log}: {ie}. Check if MOONID exists in 'moonid_areas'."
            )
            # Decide if this should raise or just log. If MOONID FK is strict, this is an error.
        except sqlite3.Error as e:
            logging.error(
                f"DB Error loading MOONID associations for SN {serial_number} from {json_filename_for_log}: {e}"
            )
            raise


def load_discovered_networks(cursor, serial_number, data):
    discovered_data = data.get("discovered_unassigned_networks", [])
    json_filename_for_log = (
        os.path.basename(data.get("json_filepath", "Unknown"))
        if isinstance(data, dict)
        else "Unknown"
    )
    if not discovered_data:
        logging.debug(
            f"No discovered unassigned network data found for SN {serial_number} in {json_filename_for_log}."
        )
        return

    sql = """
        INSERT OR IGNORE INTO discovered_unassigned_networks (
            network_prefix, discovery_source_type, discovery_context, first_seen_switch_sn,
            requires_investigation, investigation_notes -- Added new fields
        ) VALUES (?, ?, ?, ?, ?, ?)
    """  # Added requires_investigation, investigation_notes
    rows_to_insert = []
    for net in discovered_data:
        if not net.get("network_prefix") or not net.get("discovery_source_type"):
            logging.warning(
                f"Skipping discovered network for SN {serial_number} from {json_filename_for_log} due to missing fields: {net}"
            )
            continue
        rows_to_insert.append(
            (
                net.get("network_prefix"),
                net.get("discovery_source_type"),
                net.get("discovery_context"),
                serial_number,
                1,
                # Default requires_investigation to 1 (True), notes to None
                None,
            )
        )
    if rows_to_insert:
        try:
            cursor.executemany(sql, rows_to_insert)
            logging.info(
                f"Attempted to load {len(rows_to_insert)} discovered networks for SN: {serial_number}. Inserted/Ignored: {cursor.rowcount}"
            )
        except sqlite3.Error as e:
            logging.error(
                f"DB Error loading discovered networks for SN {serial_number} from {json_filename_for_log}: {e}"
            )
            raise


def load_neighbors(cursor, serial_number, data):
    neighbors_data = data.get("neighbors", [])
    json_filename_for_log = (
        os.path.basename(data.get("json_filepath", "Unknown"))
        if isinstance(data, dict)
        else "Unknown"
    )
    if not neighbors_data:
        logging.debug(
            f"No neighbor data found for SN {serial_number} in {json_filename_for_log}."
        )
        return

    sql = """
        INSERT INTO lldp_cdp_neighbors (
            local_switch_serial_number, local_interface_name, protocol_used,
            remote_device_id, remote_interface_name, remote_system_name,
            remote_mgmt_address, remote_model
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows_to_insert = []
    for neighbor_entry in neighbors_data:
        local_iface_name = neighbor_entry.get("local_interface_name")
        if (
            not all(
                key in neighbor_entry
                for key in [
                    "protocol_used",
                    "remote_device_id",
                    "remote_interface_name",
                ]
            )
            or not local_iface_name
        ):
            logging.warning(
                f"Skipping neighbor entry for SN {serial_number} (File: {json_filename_for_log}) due to missing required fields: {neighbor_entry}"
            )
            continue
        rows_to_insert.append(
            (
                serial_number,
                local_iface_name,
                neighbor_entry.get("protocol_used"),
                neighbor_entry.get("remote_device_id"),
                neighbor_entry.get("remote_interface_name"),
                neighbor_entry.get("remote_system_name"),
                neighbor_entry.get("remote_mgmt_address"),
                neighbor_entry.get("remote_model"),
            )
        )
    if rows_to_insert:
        try:
            cursor.executemany(sql, rows_to_insert)
            logging.info(
                f"Loaded {len(rows_to_insert)} neighbor entries for SN: {serial_number}"
            )
        # No UNIQUE constraint, so IntegrityError for duplicates is less likely here.
        except sqlite3.Error as e:
            logging.error(
                f"DB Error loading neighbor entries for SN {serial_number} from {json_filename_for_log}: {e}"
            )
            raise


# --- Main Processing Function ---
def process_json_file(filepath, conn):
    logging.info(f"Processing file: {filepath}")
    data = None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                data["json_filepath"] = filepath  # Store filepath for logging
    except FileNotFoundError:
        logging.error(f"File not found: {filepath}")
        return False
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in file {filepath}: {e}")
        return False
    except Exception as e:
        logging.exception(f"Error reading file {filepath}: {e}")
        return False

    if not isinstance(data, dict):
        logging.error(
            f"Loaded data from {filepath} is not a dictionary. Skipping.")
        return False

    required_keys = [
        "switch_details"
    ]  # Can add more if certain top-level keys are always expected
    if not all(key in data for key in required_keys):
        logging.error(
            f"JSON file {filepath} is missing required top-level keys ({required_keys}). Skipping."
        )
        return False

    serial_number = data.get("switch_details", {}).get("serial_number")
    if not serial_number:
        logging.error(
            f"Cannot process {filepath}: Missing 'serial_number' in 'switch_details'."
        )
        return False

    cursor = conn.cursor()
    try:
        if DELETE_EXISTING_SWITCH_DATA_BEFORE_LOAD:
            delete_switch_data(cursor, serial_number)

        load_switch_details(cursor, data)
        load_interfaces(cursor, serial_number, data)
        load_vlans(cursor, serial_number, data)
        load_ip_interfaces(cursor, serial_number, data)
        load_mac_entries(cursor, serial_number, data)
        load_arp_entries(cursor, serial_number, data)
        load_routes(cursor, serial_number, data)
        load_moonid_associations(cursor, serial_number, data)
        load_discovered_networks(cursor, serial_number, data)
        load_neighbors(cursor, serial_number, data)
        # Items for review are not loaded into a separate DB table in this script.
        # They are part of the JSON for manual review or other tools.
        logging.info(f"Successfully staged data from: {filepath}")
        return True
    except (
        sqlite3.Error,
        ValueError,
        Exception,
    ) as e:  # Catch broader errors from load functions
        logging.error(
            f"Failed to process file {filepath} due to error: {e}", exc_info=True
        )
        # No conn.rollback() here, as it's handled by the 'with conn:' context in main.
        return False


# --- Main Execution ---
if __name__ == "__main__":
    logging.info(f"--- Starting JSON Data Load to DB ({DB_FILE}) ---")
    logging.info(
        f"JSON Source Folder (recursive search): {os.path.abspath(JSON_FOLDER)}"
    )
    logging.info(
        f"Delete Existing Switch Data Before Load: {DELETE_EXISTING_SWITCH_DATA_BEFORE_LOAD}"
    )
    logging.info(f"Targeting files ending with: '{TARGET_JSON_SUFFIX}'")

    json_files = get_json_files(JSON_FOLDER)
    if not json_files:
        logging.warning("No JSON files found to process. Exiting.")
        exit()

    if not os.path.exists(DB_FILE):
        logging.error(
            f"Database file '{DB_FILE}' not found. Run create_db.py? Exiting."
        )
        exit()

    conn = None
    success_count = 0
    error_count = 0
    files_attempted_count = 0

    try:
        conn = sqlite3.connect(DB_FILE)
        conn.execute("PRAGMA foreign_keys = ON;")

        with conn:  # Transaction for the entire batch of files
            for filepath in json_files:
                files_attempted_count += 1
                if process_json_file(filepath, conn):
                    success_count += 1
                else:
                    error_count += 1
                    # If one file fails, rollback the entire batch
                    raise RuntimeError(
                        f"Stopping batch load and rolling back due to error processing file: {filepath}"
                    )

        logging.info("--- Load Process Finished ---")
        logging.info(f"Successfully committed data for {success_count} files.")
        if error_count > 0:
            logging.warning(
                f"{error_count} file(s) caused a rollback of the entire batch."
            )

    except sqlite3.Error as e:
        logging.exception(f"A database error occurred: {e}")
        logging.error("Transaction likely rolled back for all files.")
        success_count = 0  # Reset success count on rollback
        # All attempted files effectively failed if batch rolled back
        error_count = files_attempted_count
    except RuntimeError as e_runtime:  # Catch the explicit rollback trigger
        logging.error(str(e_runtime))
        logging.error(
            "Transaction rolled back for all files due to error in one file.")
        success_count = 0
        # error_count is already incremented when RuntimeError is raised
    except Exception as e_global:
        logging.exception(f"An unexpected global error occurred: {e_global}")
        logging.error("Transaction likely rolled back for all files.")
        success_count = 0
        error_count = files_attempted_count
    finally:
        if conn:
            conn.close()
            logging.info("Database connection closed.")

    logging.info(
        f"Final Summary -> Files Attempted: {files_attempted_count}, Files Successfully Committed (if no errors in batch): {success_count}, Files Causing Rollback (or part of rolled-back batch): {error_count}"
    )
