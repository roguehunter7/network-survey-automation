import re
import json
import argparse
import os

def standardize_mac(mac_string):
    """
    Converts a Cisco-style MAC address (e.g., '0200.0000.0001') to
    standard colon-separated uppercase format (e.g., '02:00:00:00:00:01').
    Returns None if the input is not a valid-looking MAC.
    """
    if not mac_string or 'Incomplete' in mac_string:
        return None

    # Remove dots and colons, then convert to uppercase
    cleaned_mac = re.sub(r'[.:-]', '', mac_string).upper()

    if len(cleaned_mac) == 12 and all(c in '0123456789ABCDEF' for c in cleaned_mac):
        # Insert colons every two characters
        return ':'.join(cleaned_mac[i:i+2] for i in range(0, 12, 2))

    return None

def parse_arp_table(log_content):
    """
    Parses the 'show arp' command output from a log file.

    Args:
        log_content (str): The full text content of the log file.

    Returns:
        list: A list of dictionaries, where each dictionary represents an ARP entry.
    """
    arp_entries = []

    # Regex to find the 'show arp' block of text
    # It starts capturing after 'show arp' and stops at the next command prompt
    arp_block_match = re.search(r'show arp\n(.*?)\n[^\n>]+#', log_content, re.DOTALL)

    if not arp_block_match:
        print("Warning: 'show arp' output not found in the log file.")
        return []

    arp_lines = arp_block_match.group(1).strip().split('\n')

    # Regex to parse a single line of the ARP table
    # Groups: 1:IP, 2:Age, 3:MAC, 4:Type, 5:Interface (optional)
    line_regex = re.compile(r'^\w+\s+([0-9.]+)\s+([\d-]+)\s+([\da-fA-F.]+|Incomplete)\s+(\w+)\s*([\w\/-]*)?$')

    for line in arp_lines:
        # Skip header or empty lines
        if 'Protocol' in line or not line.strip():
            continue

        match = line_regex.match(line.strip())
        if not match:
            # This handles potentially broken/wrapped lines in the log
            print(f"Warning: Could not parse line: '{line}'")
            continue

        ip_address, age_str, mac_str, arp_type, interface = match.groups()

        # Process and standardize the captured data

        # 1. Standardize MAC address
        mac_address = standardize_mac(mac_str)

        # 2. Convert age to seconds
        age_in_seconds = None
        if age_str.isdigit():
            age_in_seconds = int(age_str) * 60 # Convert minutes to seconds
        # A '-' indicates the entry is static to the device itself, age is not applicable
        elif age_str == '-':
            age_in_seconds = None

        # 3. Extract VLAN ID from interface if it's a VLAN interface
        vlan_id = None
        if interface and interface.lower().startswith('vlan'):
            vlan_match = re.search(r'(\d+)', interface)
            if vlan_match:
                vlan_id = int(vlan_match.group(1))

        arp_entry = {
            "ip_address": ip_address,
            "mac_address": mac_address,
            "interface_name": interface if interface else None,
            "vlan_id": vlan_id,
            "type": arp_type,
            "age_in_seconds": age_in_seconds
        }
        arp_entries.append(arp_entry)

    return arp_entries

def main():
    """
    Main function to handle command-line arguments and orchestrate the parsing.
    """
    parser = argparse.ArgumentParser(
        description="Extract the ARP table from a network device log file and save it as a JSON file.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "input_file",
        help="Path to the input log file (e.g., 'SYNA0000001_llm_input_package.txt')."
    )
    parser.add_argument(
        "-o", "--output_file",
        help="Path to the output JSON file. Defaults to 'arp_entries.json' in the current directory.",
        default="arp_entries.json"
    )

    args = parser.parse_args()

    # Check if the input file exists
    if not os.path.exists(args.input_file):
        print(f"Error: Input file not found at '{args.input_file}'")
        return

    print(f"Reading log file from: {args.input_file}")
    try:
        with open(args.input_file, 'r', encoding='utf-8') as f:
            log_content = f.read()
    except Exception as e:
        print(f"Error reading file: {e}")
        return

    # Parse the content to get ARP entries
    arp_data = parse_arp_table(log_content)

    if not arp_data:
        print("No ARP entries were extracted. The output file will not be created.")
        return

    # Write the extracted data to the output JSON file
    try:
        with open(args.output_file, 'w', encoding='utf-8') as f:
            json.dump(arp_data, f, indent=4)
        print(f"Successfully extracted {len(arp_data)} ARP entries.")
        print(f"Output saved to: {args.output_file}")
    except Exception as e:
        print(f"Error writing to output file: {e}")

if __name__ == "__main__":
    main()
