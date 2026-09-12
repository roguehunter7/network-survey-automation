import csv
import ipaddress
import os
import sqlite3
from collections import defaultdict

# --- Configuration ---
# The name of your SQLite database file.
DB_FILENAME = "network_survey.db"

# Filename for the complete, raw data dump.
RAW_OUTPUT_FILENAME = "unassigned_networks_RAW_DATA.csv"

# Filename for the processed, intelligent report with device counts.
GROUPED_REPORT_FILENAME = "unassigned_networks_GROUPED_REPORT.csv"
# -------------------


def get_logical_network(prefix_string):
    """Calculates the logical /24 or /64 network for a given prefix."""
    try:
        ip_iface = ipaddress.ip_interface(prefix_string)
        if ip_iface.version == 4 and ip_iface.network.prefixlen == 32:
            return str(ipaddress.ip_network(f"{ip_iface.ip}/24", strict=False))
        if ip_iface.version == 6 and ip_iface.network.prefixlen == 128:
            return str(ipaddress.ip_network(f"{ip_iface.ip}/64", strict=False))
        return str(ip_iface.network)
    except ValueError:
        return None


def extract_raw_data(conn):
    """
    Extracts all raw unassigned network entries and saves them to a CSV file.
    """
    print("--- Task 1: Generating Raw Data File ---")
    print("Querying database for all raw discovery entries...")
    cursor = conn.cursor()

    sql_query = """
    SELECT
        s.site,
        s.floor,
        s.lab_area_name,
        d.network_prefix
    FROM
        discovered_unassigned_networks AS d
    LEFT JOIN
        switches AS s ON d.first_seen_switch_sn = s.serial_number;
    """
    cursor.execute(sql_query)
    rows = cursor.fetchall()
    print(f"Found {len(rows)} raw entries.")

    with open(RAW_OUTPUT_FILENAME, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["campus_id", "Floor", "Lab", "Network_Prefix"])
        # Convert rows of Row objects to simple tuples for writerows
        writer.writerows([tuple(row) for row in rows])

    print(f"Success! Raw data saved to '{RAW_OUTPUT_FILENAME}'\n")


def generate_grouped_report(conn):
    """
    Generates an advanced report with networks grouped and devices counted
    using the MAC address table where possible.
    """
    print("--- Task 2: Generating Grouped and Counted Report ---")
    cursor = conn.cursor()

    # Step 1: Fetch detailed data needed for processing
    sql_query = """
    SELECT
        s.site, s.floor, s.lab_area_name,
        d.network_prefix, d.first_seen_switch_sn, d.discovery_source_type
    FROM discovered_unassigned_networks AS d
    LEFT JOIN switches AS s ON d.first_seen_switch_sn = s.serial_number;
    """
    print("Fetching detailed entries for processing...")
    cursor.execute(sql_query)
    rows = cursor.fetchall()
    print(f"Processing {len(rows)} entries to group and count...")

    # Step 2: Group discoveries by logical network
    grouped_discoveries = defaultdict(list)
    for row in rows:
        logical_net = get_logical_network(row["network_prefix"])
        if logical_net:
            grouped_discoveries[logical_net].append(dict(row))

    print(
        f"Grouped into {len(grouped_discoveries)} logical networks. Calculating device counts..."
    )

    # Step 3: Calculate accurate counts for each group
    final_report_data = []
    for network, discoveries in grouped_discoveries.items():
        device_count = 0
        comment = "Count of discovery events (ARP/MAC lookup not applicable or failed)"

        # Try to find a VLAN via ARP to perform a MAC count
        for discovery in discoveries:
            if (
                discovery["first_seen_switch_sn"]
                and "/32" in discovery["network_prefix"]
            ):
                switch_sn = discovery["first_seen_switch_sn"]
                ip_addr = discovery["network_prefix"].split("/")[0]

                cursor.execute(
                    "SELECT vlan_id FROM arp_table WHERE switch_serial_number = ? AND ip_address = ?",
                    (switch_sn, ip_addr),
                )
                arp_result = cursor.fetchone()

                if arp_result and arp_result["vlan_id"]:
                    vlan_id = arp_result["vlan_id"]
                    cursor.execute(
                        "SELECT COUNT(DISTINCT mac_address) FROM mac_address_table WHERE switch_serial_number = ? AND vlan_id = ?",
                        (switch_sn, vlan_id),
                    )
                    mac_count = cursor.fetchone()[0]
                    if mac_count > 0:
                        device_count = mac_count
                        comment = f"Count from MAC Table on VLAN {vlan_id}"
                        break  # Found our count, no need to check other discoveries

        # Fallback to event count if no MAC count was found
        if device_count == 0:
            device_count = len(discoveries)

        # Prepare the final row
        rep = discoveries[0]
        final_report_data.append(
            {
                "campus_id": rep["site"] or "N/A",
                "Floor": rep["floor"] or "N/A",
                "Lab": rep["lab_area_name"] or "N/A",
                "IP_Range": network,
                "Device_Count": device_count,
                "Comments": comment,
            }
        )

    # Step 4: Write the final grouped report
    with open(GROUPED_REPORT_FILENAME, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["campus_id", "Floor", "Lab", "IP_Range", "Device_Count", "Comments"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(final_report_data)

    print(f"Success! Grouped report saved to '{GROUPED_REPORT_FILENAME}'")


# --- Main Execution Block ---
if __name__ == "__main__":
    if not os.path.exists(DB_FILENAME):
        print(
            f"Error: Database file '{DB_FILENAME}' not found. Please place it in the same directory."
        )
    else:
        conn = None
        try:
            conn = sqlite3.connect(DB_FILENAME)
            conn.row_factory = sqlite3.Row  # Makes rows accessible by column name

            extract_raw_data(conn)
            generate_grouped_report(conn)

        except sqlite3.Error as e:
            print(f"A database error occurred: {e}")
        finally:
            if conn:
                conn.close()
                print("\nDatabase connection closed.")
