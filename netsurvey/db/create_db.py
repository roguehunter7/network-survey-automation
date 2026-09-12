# create_db.py (v2.16.0 - Finalized Schema, Reads data from ./data/ JSON files)
import json
import logging
import os
import sqlite3

# --- Configuration ---
DB_FILENAME = "network_survey.db"
DATA_DIR = "data"  # Subdirectory for JSON input files
LAB_AREAS_JSON_FILENAME = os.path.join(DATA_DIR, "lab_areas_data.json")
MOONID_AREAS_JSON_FILENAME = os.path.join(DATA_DIR, "moonid_areas_data.json")
FORCE_DELETE_EXISTING = True  # Set to False for production use after first run

# Basic Logging Setup
log_format = "%(asctime)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=log_format)
# Consider adding a FileHandler for persistent logs if needed
# logging.getLogger().addHandler(logging.FileHandler("create_db.log"))


# --- Schema Definition (v2.16.0) ---
# Changes from v2.15.3:
# - Added base_mac_address TEXT to switches.
# - Added mac_address TEXT to ip_interfaces.
# - Added is_standard INTEGER to logged_other_devices and logged_access_points.
# - Added inter_site_connectivity INTEGER, internet_access_path TEXT, intranet_access_path TEXT to lab_areas.
# - Added relevant indexes.
# - lldp_cdp_neighbors index on (local_switch_serial_number, local_interface_name) is NOT unique.
SQL_SCHEMA_SCRIPT = """
PRAGMA foreign_keys = ON;

-- Schema Version: 2.16.0

CREATE TABLE IF NOT EXISTS lab_areas (
    lab_area_name TEXT NOT NULL,
    floor TEXT NOT NULL,
    site TEXT NOT NULL,
    building TEXT NOT NULL,
    wing TEXT NOT NULL DEFAULT 'N/A',
    purpose_of_lab TEXT,
    primary_ssid TEXT,
    cabling_type_uplink TEXT,
    cabling_type_downlink TEXT,
    firewall_present INTEGER,
    firewall_description TEXT,
    operator_reported_unmanaged_switch_count INTEGER,
    operator_reported_ap_count INTEGER,
    operator_reported_wired_host_count INTEGER,
    operator_reported_wireless_host_count INTEGER,
    operator_reported_guest_estimate INTEGER,
    total_failed_access_switch_count INTEGER,
    total_non_standard_switch_count INTEGER,
    total_standard_switch_count INTEGER,
    total_ports_used_in_area INTEGER,
    total_ports_free_in_area INTEGER,
    inter_site_connectivity INTEGER,
    internet_access_path TEXT,
    intranet_access_path TEXT,
    PRIMARY KEY (lab_area_name, floor, site, building)
);

CREATE TABLE IF NOT EXISTS moonid_areas (
    moonid TEXT PRIMARY KEY NOT NULL,
    site TEXT NOT NULL,
    ip_range_definition TEXT,
    purpose TEXT,
    business_group TEXT,
    vlan_id INTEGER,
    is_moonid_lab INTEGER DEFAULT 0,
    is_air_gap INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Operational',
    date_retired TEXT,
    is_inter_wing INTEGER,
    is_inter_floor INTEGER,
    is_inter_building INTEGER
);
CREATE INDEX IF NOT EXISTS idx_moonid_areas_moonid ON moonid_areas (moonid);
CREATE INDEX IF NOT EXISTS idx_moonid_areas_status ON moonid_areas (status);
CREATE INDEX IF NOT EXISTS idx_moonid_areas_site ON moonid_areas (site);

CREATE TABLE IF NOT EXISTS switches (
    serial_number TEXT PRIMARY KEY NOT NULL,
    hostname TEXT,
    model TEXT NOT NULL,
    make TEXT NOT NULL,
    device_type TEXT NOT NULL DEFAULT 'Switch',
    base_mac_address TEXT,
    lab_area_name TEXT NOT NULL,
    floor TEXT NOT NULL,
    site TEXT NOT NULL,
    building TEXT NOT NULL,
    location_notes TEXT,
    rack_type_detail TEXT,
    access_level TEXT NOT NULL,
    ip_version_routing TEXT,
    running_config_captured INTEGER NOT NULL DEFAULT 0,
    is_poe_capable INTEGER,
    handles_internal_vlans INTEGER NOT NULL DEFAULT 0,
    log_filename_validated TEXT,
    survey_timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
    user_verified_total_ports INTEGER,
    user_verified_used_ports INTEGER,
    is_switch_standard INTEGER,
    uplink_type TEXT,
    FOREIGN KEY (lab_area_name, floor, site, building) REFERENCES lab_areas (lab_area_name, floor, site, building)
);
CREATE INDEX IF NOT EXISTS idx_switches_hostname ON switches (hostname);
CREATE INDEX IF NOT EXISTS idx_switches_base_mac ON switches (base_mac_address);
CREATE INDEX IF NOT EXISTS idx_switches_location ON switches (lab_area_name, floor, site, building);
CREATE INDEX IF NOT EXISTS idx_switches_device_type ON switches (device_type);
CREATE INDEX IF NOT EXISTS idx_switches_is_standard ON switches (is_switch_standard);
CREATE INDEX IF NOT EXISTS idx_switches_uplink_type ON switches (uplink_type);

CREATE TABLE IF NOT EXISTS logged_other_devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_timestamp TEXT NOT NULL,
    status_reason TEXT NOT NULL,
    lab_area_name TEXT NOT NULL,
    floor TEXT NOT NULL,
    site TEXT NOT NULL,
    building TEXT NOT NULL,
    wing TEXT NOT NULL,
    specific_location_notes TEXT,
    rack_type_detail TEXT,
    reported_make TEXT,
    reported_model TEXT,
    reported_serial_number TEXT,
    reported_asset_tag TEXT,
    reported_moonid TEXT,
    observed_laptop_ip TEXT,
    failure_reason_detail TEXT,
    reported_total_ports INTEGER,
    reported_used_ports INTEGER,
    is_standard INTEGER,
    FOREIGN KEY (lab_area_name, floor, site, building) REFERENCES lab_areas (lab_area_name, floor, site, building)
);
CREATE INDEX IF NOT EXISTS idx_otherdev_status ON logged_other_devices (status_reason);
CREATE INDEX IF NOT EXISTS idx_otherdev_location ON logged_other_devices (lab_area_name, floor, site, building);
CREATE INDEX IF NOT EXISTS idx_otherdev_sn ON logged_other_devices (reported_serial_number);
CREATE INDEX IF NOT EXISTS idx_otherdev_moonid ON logged_other_devices (reported_moonid);
CREATE INDEX IF NOT EXISTS idx_otherdev_is_standard ON logged_other_devices (is_standard);

CREATE TABLE IF NOT EXISTS logged_access_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_timestamp TEXT NOT NULL,
    lab_area_name TEXT NOT NULL,
    floor TEXT NOT NULL,
    site TEXT NOT NULL,
    building TEXT NOT NULL,
    wing TEXT NOT NULL,
    specific_location_notes TEXT,
    rack_type_detail TEXT,
    reported_make TEXT,
    reported_model TEXT,
    reported_serial_number TEXT,
    reported_asset_tag TEXT,
    reported_moonid TEXT,
    observed_laptop_ip TEXT,
    observed_ssid TEXT,
    mac_address TEXT,
    reported_total_ports INTEGER,
    reported_used_ports INTEGER,
    uplink_type TEXT,
    is_standard INTEGER,
    FOREIGN KEY (lab_area_name, floor, site, building) REFERENCES lab_areas (lab_area_name, floor, site, building)
);
CREATE INDEX IF NOT EXISTS idx_ap_location ON logged_access_points (lab_area_name, floor, site, building);
CREATE INDEX IF NOT EXISTS idx_ap_mac ON logged_access_points (mac_address);
CREATE INDEX IF NOT EXISTS idx_ap_sn ON logged_access_points (reported_serial_number);
CREATE INDEX IF NOT EXISTS idx_ap_ssid ON logged_access_points (observed_ssid);
CREATE INDEX IF NOT EXISTS idx_ap_moonid ON logged_access_points (reported_moonid);
CREATE INDEX IF NOT EXISTS idx_ap_uplink_type ON logged_access_points (uplink_type);
CREATE INDEX IF NOT EXISTS idx_ap_is_standard ON logged_access_points (is_standard);

CREATE TABLE IF NOT EXISTS switch_moonid_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    switch_serial_number TEXT NOT NULL,
    moonid TEXT NOT NULL,
    resolution_method TEXT NOT NULL,
    confidence_score REAL,
    FOREIGN KEY (switch_serial_number) REFERENCES switches (serial_number) ON DELETE CASCADE,
    FOREIGN KEY (moonid) REFERENCES moonid_areas (moonid),
    UNIQUE (switch_serial_number, moonid)
);
CREATE INDEX IF NOT EXISTS idx_map_switch_serial_number ON switch_moonid_map (switch_serial_number);
CREATE INDEX IF NOT EXISTS idx_map_moonid ON switch_moonid_map (moonid);

CREATE TABLE IF NOT EXISTS interfaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    switch_serial_number TEXT NOT NULL,
    interface_name TEXT NOT NULL,
    status TEXT,
    vlan TEXT,
    duplex TEXT,
    speed TEXT,
    type TEXT,
    description TEXT,
    is_uplink INTEGER,
    FOREIGN KEY (switch_serial_number) REFERENCES switches (serial_number) ON DELETE CASCADE,
    UNIQUE (switch_serial_number, interface_name)
);
CREATE INDEX IF NOT EXISTS idx_interfaces_switch_serial_number ON interfaces (switch_serial_number);
CREATE INDEX IF NOT EXISTS idx_interfaces_status ON interfaces (status);

CREATE TABLE IF NOT EXISTS vlans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    switch_serial_number TEXT NOT NULL,
    vlan_id INTEGER NOT NULL,
    vlan_name TEXT,
    status TEXT,
    ports_associated_text TEXT,
    FOREIGN KEY (switch_serial_number) REFERENCES switches (serial_number) ON DELETE CASCADE,
    UNIQUE (switch_serial_number, vlan_id)
);
CREATE INDEX IF NOT EXISTS idx_vlans_switch_serial_number ON vlans (switch_serial_number);

CREATE TABLE IF NOT EXISTS ip_interfaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    switch_serial_number TEXT NOT NULL,
    interface_name TEXT NOT NULL,
    mac_address TEXT,
    ip_address_with_prefix TEXT NOT NULL,
    status TEXT,
    protocol_status TEXT,
    is_management INTEGER,
    FOREIGN KEY (switch_serial_number) REFERENCES switches (serial_number) ON DELETE CASCADE,
    UNIQUE (switch_serial_number, interface_name)
);
CREATE INDEX IF NOT EXISTS idx_ip_interfaces_switch_serial_number ON ip_interfaces (switch_serial_number);
CREATE INDEX IF NOT EXISTS idx_ip_interfaces_ip_address ON ip_interfaces (ip_address_with_prefix);
CREATE INDEX IF NOT EXISTS idx_ip_interfaces_mac ON ip_interfaces (mac_address);

CREATE TABLE IF NOT EXISTS mac_address_table (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    switch_serial_number TEXT NOT NULL,
    mac_address TEXT NOT NULL,
    interface_name TEXT NOT NULL,
    vlan_id INTEGER NOT NULL,
    type TEXT,
    timestamp_learned TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (switch_serial_number) REFERENCES switches (serial_number) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_mac_switch_serial_number ON mac_address_table (switch_serial_number);
CREATE INDEX IF NOT EXISTS idx_mac_interface ON mac_address_table (switch_serial_number, interface_name);
CREATE INDEX IF NOT EXISTS idx_mac_mac_address ON mac_address_table (mac_address);

CREATE TABLE IF NOT EXISTS arp_table (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    switch_serial_number TEXT NOT NULL,
    ip_address TEXT NOT NULL,
    mac_address TEXT NOT NULL,
    interface_name TEXT,
    vlan_id INTEGER,
    type TEXT,
    age_in_seconds INTEGER,
    timestamp_learned TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (switch_serial_number) REFERENCES switches (serial_number) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_arp_switch_serial_number ON arp_table (switch_serial_number);
CREATE INDEX IF NOT EXISTS idx_arp_mac_address ON arp_table (mac_address);
CREATE INDEX IF NOT EXISTS idx_arp_ip_address ON arp_table (ip_address);

CREATE TABLE IF NOT EXISTS lldp_cdp_neighbors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_switch_serial_number TEXT NOT NULL,
    local_interface_name TEXT NOT NULL,
    protocol_used TEXT NOT NULL,
    remote_device_id TEXT NOT NULL,
    remote_interface_name TEXT NOT NULL,
    remote_system_name TEXT,
    remote_mgmt_address TEXT,
    remote_model TEXT,
    timestamp_discovered TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (local_switch_serial_number) REFERENCES switches (serial_number) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_neighbor_local_switch_iface ON lldp_cdp_neighbors (local_switch_serial_number, local_interface_name);
CREATE INDEX IF NOT EXISTS idx_neighbor_remote_device ON lldp_cdp_neighbors (remote_device_id);

CREATE TABLE IF NOT EXISTS ip_routing_table (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    switch_serial_number TEXT NOT NULL,
    ip_version INTEGER NOT NULL,
    destination_prefix TEXT NOT NULL,
    next_hop_ip TEXT,
    outgoing_interface TEXT,
    metric INTEGER,
    protocol TEXT,
    is_default_route INTEGER,
    timestamp_learned TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (switch_serial_number) REFERENCES switches (serial_number) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_route_switch_serial_number ON ip_routing_table (switch_serial_number);
CREATE INDEX IF NOT EXISTS idx_route_destination ON ip_routing_table (switch_serial_number, ip_version, destination_prefix);
CREATE INDEX IF NOT EXISTS idx_route_is_default ON ip_routing_table (is_default_route);

CREATE TABLE IF NOT EXISTS discovered_unassigned_networks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    network_prefix TEXT NOT NULL UNIQUE,
    discovery_source_type TEXT NOT NULL,
    discovery_context TEXT,
    first_seen_switch_sn TEXT,
    requires_investigation INTEGER NOT NULL DEFAULT 1,
    investigation_notes TEXT,
    timestamp_added TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(first_seen_switch_sn) REFERENCES switches(serial_number) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_unassigned_net_prefix ON discovered_unassigned_networks (network_prefix);
"""


def create_and_apply_schema(db_file):
    logging.info(f"Step 1: Creating/Applying Database Schema (v2.16.0) to '{db_file}'")
    conn = None
    if FORCE_DELETE_EXISTING and os.path.exists(db_file):
        try:
            os.remove(db_file)
            logging.info(f"Deleted existing database: {db_file}")
        except OSError as e:
            logging.error(f"Error deleting existing database '{db_file}': {e}")
            return False

    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.executescript(SQL_SCHEMA_SCRIPT)
        conn.commit()
        logging.info("Database schema v2.16.0 applied successfully.")
        cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table';")
        table_count = cursor.fetchone()[0]
        expected_tables = 16
        logging.info(
            f"Database contains {table_count} tables (expected: {expected_tables})."
        )
        if table_count != expected_tables:
            logging.warning("Table count does not match expected for v2.16.0 schema!")
        return True
    except sqlite3.Error as e:
        logging.error(f"Database error during schema creation: {e}")
        return False
    finally:
        if conn:
            conn.close()


def populate_lab_areas(db_file, data):
    logging.info(
        f"Step 2: Populating Lab Areas from loaded data ({len(data) if data else 0} records)"
    )
    if not os.path.exists(db_file):
        logging.error(f"DB file not found: {db_file}")
        return
    if not isinstance(data, list) or not data:
        logging.warning("Lab Area data empty/not list. Skipping population.")
        return

    conn = None
    try:
        conn = sqlite3.connect(db_file)
        conn.execute("PRAGMA foreign_keys = ON;")
        cursor = conn.cursor()
        sql = """INSERT OR IGNORE INTO lab_areas (
                    lab_area_name, floor, site, building, wing, purpose_of_lab,
                    primary_ssid, cabling_type_uplink, cabling_type_downlink,
                    firewall_present, firewall_description,
                    operator_reported_unmanaged_switch_count, operator_reported_ap_count,
                    operator_reported_wired_host_count, operator_reported_wireless_host_count,
                    operator_reported_guest_estimate,
                    inter_site_connectivity, internet_access_path, intranet_access_path
                 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        added, ignored, errors = 0, 0, 0
        for area in data:
            if not isinstance(area, dict):
                logging.error(f"  Skipping invalid data format in lab areas: {area}")
                errors += 1
                continue
            pk_values = [
                area.get(k) for k in ["lab_area_name", "floor", "site", "building"]
            ]
            if not all(v is not None for v in pk_values):
                logging.error(f"  Skipping area due to missing PK field: {area}")
                errors += 1
                continue
            try:
                cursor.execute(
                    sql,
                    (
                        area.get("lab_area_name"),
                        area.get("floor"),
                        area.get("site"),
                        area.get("building"),
                        area.get("wing", "N/A"),
                        area.get("purpose_of_lab"),
                        area.get("primary_ssid"),
                        area.get("cabling_type_uplink"),
                        area.get("cabling_type_downlink"),
                        area.get("firewall_present"),
                        area.get("firewall_description"),
                        area.get("operator_reported_unmanaged_switch_count"),
                        area.get("operator_reported_ap_count"),
                        area.get("operator_reported_wired_host_count"),
                        area.get("operator_reported_wireless_host_count"),
                        area.get("operator_reported_guest_estimate"),
                        area.get("inter_site_connectivity"),
                        area.get("internet_access_path"),
                        area.get("intranet_access_path"),
                    ),
                )
                if cursor.rowcount > 0:
                    added += 1
                else:
                    ignored += 1
            except sqlite3.Error as e:
                logging.error(
                    f"  DB Error inserting area {area.get('site')}-{area.get('building')}: {e}"
                )
                errors += 1
            except Exception as e:
                logging.exception(
                    f"  Unexpected Error inserting area {area.get('site')}-{area.get('building')}: {e}"
                )
                errors += 1
        conn.commit()
        logging.info(
            f"Lab areas: Added: {added}, Ignored/Duplicates: {ignored}, Errors: {errors}"
        )
    except sqlite3.Error as e:
        logging.error(f"DB conn/commit error (lab areas): {e}")
    finally:
        if conn:
            conn.close()


def populate_moonid_areas(db_file, data):
    logging.info(f"Step 3: Populating MOONID Areas ({len(data) if data else 0} records)")
    if not os.path.exists(db_file):
        logging.error(f"DB file not found: {db_file}")
        return
    if not isinstance(data, list) or not data:
        logging.warning("MOONID Area data empty/not list. Skipping population.")
        return

    conn = None
    try:
        conn = sqlite3.connect(db_file)
        conn.execute("PRAGMA foreign_keys = ON;")
        cursor = conn.cursor()
        sql = """INSERT OR IGNORE INTO moonid_areas (
                    moonid, site, ip_range_definition, purpose, business_group, vlan_id,
                    is_moonid_lab, is_air_gap, status, date_retired,
                    is_inter_wing, is_inter_floor, is_inter_building
                 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        added, ignored, errors, processed_moonids = 0, 0, 0, set()
        for entry in data:
            if not isinstance(entry, dict):
                logging.error(f"  Skipping invalid MOONID entry: {entry}")
                errors += 1
                continue
            moonid = entry.get("moonid")
            if not isinstance(moonid, str) or not moonid.strip():
                logging.error(f"  Skipping MOONID entry with invalid moonid: {entry}")
                errors += 1
                continue
            moonid_key = moonid.strip().upper()
            if moonid_key in processed_moonids:
                logging.warning(f"  Skipping duplicate MOONID in source: {moonid}")
                continue
            processed_moonids.add(moonid_key)
            site = entry.get("site")
            if not isinstance(site, str) or not site.strip():
                logging.error(f"  Skipping MOONID {moonid} (missing site).")
                errors += 1
                continue
            vlan_id_val = entry.get("vlan_id")
            vlan_id_int = None
            if vlan_id_val is not None:
                try:
                    vlan_id_int = int(vlan_id_val)
                except (ValueError, TypeError):
                    pass
            status = entry.get("status", "Operational") or "Operational"
            date_retired = entry.get("date_retired") if status == "Retired" else None
            try:
                cursor.execute(
                    sql,
                    (
                        moonid,
                        site,
                        entry.get("ip_range_definition"),
                        entry.get("purpose"),
                        entry.get("business_group"),
                        vlan_id_int,
                        int(entry.get("is_moonid_lab", 0) or 0),
                        int(entry.get("is_air_gap", 0) or 0),
                        status,
                        date_retired,
                        entry.get("is_inter_wing"),
                        entry.get("is_inter_floor"),
                        entry.get("is_inter_building"),
                    ),
                )
                if cursor.rowcount > 0:
                    added += 1
                else:
                    ignored += 1
            except sqlite3.Error as e:
                logging.error(f"  DB Error inserting MOONID {moonid}: {e}")
                errors += 1
            except Exception as e:
                logging.exception(f"  Unexpected Error inserting MOONID {moonid}: {e}")
                errors += 1
        conn.commit()
        logging.info(
            f"MOONID areas: Processed Unique: {len(processed_moonids)}, Added: {added}, Ignored/DB Duplicates: {ignored}, Errors: {errors}"
        )
    except sqlite3.Error as e:
        logging.error(f"DB conn/commit error (MOONID areas): {e}")
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    logging.info(
        "--- Starting Database Setup Script (Schema V2.16.0 - JSON Load from ./data/) ---"
    )
    if not os.path.isdir(DATA_DIR):
        logging.error(
            f"Data directory '{DATA_DIR}' not found. Create it and place JSON files inside."
        )
        exit(1)

    loaded_lab_data, loaded_moonid_data = [], []
    logging.info(f"Attempting to load lab areas from '{LAB_AREAS_JSON_FILENAME}'...")
    try:
        with open(LAB_AREAS_JSON_FILENAME, "r", encoding="utf-8") as f:
            loaded_lab_data = json.load(f)
        if not isinstance(loaded_lab_data, list):
            logging.error(f"{LAB_AREAS_JSON_FILENAME} not a JSON list.")
            loaded_lab_data = []
        else:
            logging.info(
                f"Loaded {len(loaded_lab_data)} records from {LAB_AREAS_JSON_FILENAME}"
            )
    except FileNotFoundError:
        logging.error(f"File not found: {LAB_AREAS_JSON_FILENAME}")
    except json.JSONDecodeError as e:
        logging.error(f"JSON parse error {LAB_AREAS_JSON_FILENAME}: {e}")
    except Exception as e:
        logging.exception(f"Unexpected error loading {LAB_AREAS_JSON_FILENAME}: {e}")

    logging.info(
        f"Attempting to load MOONID areas from '{MOONID_AREAS_JSON_FILENAME}'..."
    )
    try:
        with open(MOONID_AREAS_JSON_FILENAME, "r", encoding="utf-8") as f:
            loaded_moonid_data = json.load(f)
        if not isinstance(loaded_moonid_data, list):
            logging.error(f"{MOONID_AREAS_JSON_FILENAME} not a JSON list.")
            loaded_moonid_data = []
        else:
            logging.info(
                f"Loaded {len(loaded_moonid_data)} records from {MOONID_AREAS_JSON_FILENAME}"
            )
    except FileNotFoundError:
        logging.error(f"File not found: {MOONID_AREAS_JSON_FILENAME}")
    except json.JSONDecodeError as e:
        logging.error(f"JSON parse error {MOONID_AREAS_JSON_FILENAME}: {e}")
    except Exception as e:
        logging.exception(f"Unexpected error loading {MOONID_AREAS_JSON_FILENAME}: {e}")

    if create_and_apply_schema(DB_FILENAME):
        populate_lab_areas(DB_FILENAME, loaded_lab_data)
        populate_moonid_areas(DB_FILENAME, loaded_moonid_data)
        logging.info(
            "-" * 30
            + "\n--- Database Setup Script Finished ---\n"
            + f"DB '{DB_FILENAME}' reflects schema v2.16.0.\n"
            + "REMINDER: Ensure source JSONs are accurate and backend scripts populate device tables."
        )
    else:
        logging.error("--- Database Setup Script FAILED (Schema Creation Error) ---")
