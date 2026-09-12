import json
import sys
import os
from pathlib import Path
from typing import List, Dict, Optional
import argparse
from dataclasses import dataclass, asdict
import logging

# TextFSM and ntc-templates imports
try:
    import textfsm
    from ntc_templates.parse import parse_output
    TEXTFSM_AVAILABLE = True
except ImportError:
    TEXTFSM_AVAILABLE = False
    print("ERROR: Required libraries not installed.")
    print("Please install them with:")
    print("pip install textfsm ntc-templates")
    sys.exit(1)

# Set up logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class MacEntry:
    """Data class for MAC address table entries"""
    mac_address: str
    interface_name: str
    vlan_id: int
    type: str


class CiscoMacTableParser:
    """Enhanced parser for Cisco MAC address tables using TextFSM"""

    def __init__(self):
        """Initialize the parser"""
        if not TEXTFSM_AVAILABLE:
            raise ImportError("TextFSM and ntc-templates are required")

    def standardize_mac_address(self, mac_string: str) -> str:
        """
        Converts MAC address to uppercase, colon-separated XX:XX:XX:XX:XX:XX format.
        Handles various input formats like xxxx.xxxx.xxxx, xx:xx:xx:xx:xx:xx, etc.
        """
        if not mac_string:
            raise ValueError("MAC address string is empty")

        # Remove all separators and convert to uppercase
        cleaned_mac = ''.join(c for c in mac_string.upper()
                              if c in '0123456789ABCDEF')

        # Validate MAC address
        if len(cleaned_mac) != 12:
            raise ValueError(f"Invalid MAC address length: {mac_string}")

        # Format as XX:XX:XX:XX:XX:XX
        return ':'.join(cleaned_mac[i:i+2] for i in range(0, 12, 2))

    def parse_cisco_mac_table(self, log_content: str) -> List[MacEntry]:
        """
        Parse Cisco MAC address table using TextFSM templates
        """
        mac_entries = []

        try:
            # Use ntc-templates to parse the output
            # This automatically detects the platform and command
            parsed_data = parse_output(
                platform="cisco_ios",
                command="show mac address-table",
                data=log_content
            )

            logger.debug(f"TextFSM parsed {len(parsed_data)} entries")

            for entry in parsed_data:
                try:
                    # Handle different possible field names from the template
                    mac_addr = entry.get('destination_address') or entry.get(
                        'mac_address') or entry.get('mac')
                    interface = entry.get('destination_port') or entry.get(
                        'interface') or entry.get('ports')
                    vlan = entry.get('vlan')
                    entry_type = entry.get('type', 'UNKNOWN')

                    if not mac_addr:
                        logger.warning(
                            f"No MAC address found in entry: {entry}")
                        continue

                    # Standardize MAC address
                    try:
                        standardized_mac = self.standardize_mac_address(
                            mac_addr)
                    except ValueError as e:
                        logger.warning(
                            f"Skipping invalid MAC address '{mac_addr}': {e}")
                        continue

                    # Handle VLAN ID
                    try:
                        if isinstance(vlan, str) and vlan.lower() == "all":
                            vlan_id = 0
                        else:
                            vlan_id = int(vlan) if vlan else 0
                    except (ValueError, TypeError):
                        logger.warning(f"Invalid VLAN '{vlan}', setting to 0")
                        vlan_id = 0

                    # Skip CPU entries
                    if interface and interface.upper() == "CPU":
                        continue

                    mac_entry = MacEntry(
                        mac_address=standardized_mac,
                        interface_name=interface or "UNKNOWN",
                        vlan_id=vlan_id,
                        type=entry_type.upper()
                    )
                    mac_entries.append(mac_entry)

                except Exception as e:
                    logger.warning(f"Error processing entry {entry}: {e}")
                    continue

        except Exception as e:
            logger.error(f"TextFSM parsing failed: {e}")
            logger.info("Falling back to manual parsing...")
            # Fallback to original regex-based parsing if needed
            return self._fallback_parse(log_content)

        return mac_entries

    def _fallback_parse(self, log_content: str) -> List[MacEntry]:
        """
        Fallback parser using regex (original implementation)
        Used when TextFSM fails
        """
        import re

        mac_entries = []
        in_mac_table_command_output = False
        parsing_actual_data_lines = False

        mac_line_regex = re.compile(
            r"^\s*(\S+)\s+([0-9a-fA-F.]+)\s+(\S+)\s+(.+)$")
        prompt_regex = re.compile(
            r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*([\(][a-zA-Z0-9_.-]*[\)])?[>#]")

        lines = log_content.splitlines()

        for line_text in lines:
            stripped_line_text = line_text.strip()

            # Check if we are entering the MAC table output
            if any(cmd in line_text.lower() for cmd in [
                "sh mac add", "show mac address-table", "show mac-address-table"
            ]):
                in_mac_table_command_output = True
                parsing_actual_data_lines = False
                continue

            if not in_mac_table_command_output:
                continue

            # Check for end of MAC table output
            if (stripped_line_text.startswith("Total Mac Addresses") or
                    (parsing_actual_data_lines and prompt_regex.match(line_text))):
                in_mac_table_command_output = False
                parsing_actual_data_lines = False
                continue

            # Start parsing data lines after headers and separator
            if not parsing_actual_data_lines:
                if (line_text.strip().startswith("----") or
                    (line_text.count('-') > 10 and
                     not any(header in line_text for header in ["Vlan", "Mac Address", "Ports"]))):
                    parsing_actual_data_lines = True
                continue

            if not stripped_line_text:
                continue

            match = mac_line_regex.match(line_text)
            if match:
                vlan_str = match.group(1).strip()
                mac_addr_str = match.group(2).strip()
                type_str = match.group(3).strip().upper()
                ports_str = match.group(4).strip()

                try:
                    standardized_mac = self.standardize_mac_address(
                        mac_addr_str)
                except ValueError:
                    continue

                if vlan_str.lower() == "all":
                    vlan_id_val = 0
                else:
                    try:
                        vlan_id_val = int(vlan_str)
                    except ValueError:
                        continue

                if ports_str.upper() == "CPU":
                    continue

                mac_entry = MacEntry(
                    mac_address=standardized_mac,
                    interface_name=ports_str,
                    vlan_id=vlan_id_val,
                    type=type_str
                )
                mac_entries.append(mac_entry)

        return mac_entries

    def read_file_with_fallback(self, file_path: Path) -> str:
        """
        Read file with UTF-8 encoding, fallback to latin-1 if needed
        """
        encodings = ['utf-8', 'latin-1', 'cp1252']

        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    content = f.read()
                logger.debug(
                    f"Successfully read {file_path} with {encoding} encoding")
                return content
            except UnicodeDecodeError:
                logger.debug(
                    f"Failed to read {file_path} with {encoding} encoding")
                continue

        raise ValueError(
            f"Could not read file {file_path} with any supported encoding")

    def process_directory(self, input_dir: str, output_dir: Optional[str] = None) -> Dict[str, int]:
        """
        Process all .txt files in the input directory
        """
        input_path = Path(input_dir)
        if not input_path.exists() or not input_path.is_dir():
            raise ValueError(
                f"Input directory '{input_dir}' does not exist or is not a directory")

        output_path = Path(output_dir) if output_dir else input_path
        output_path.mkdir(exist_ok=True)

        # Find all .txt files
        txt_files = list(input_path.glob("*.txt"))
        if not txt_files:
            logger.warning(f"No .txt files found in {input_dir}")
            return {}

        results = {}

        logger.info(f"Found {len(txt_files)} .txt files to process")

        for txt_file in txt_files:
            logger.info(f"Processing: {txt_file.name}")

            try:
                # Read file content
                log_content = self.read_file_with_fallback(txt_file)

                # Parse MAC table using TextFSM
                mac_entries = self.parse_cisco_mac_table(log_content)

                # Generate output filename
                output_filename = txt_file.stem + "_mac_table.json"
                output_file_path = output_path / output_filename

                # Convert to dict for JSON serialization
                mac_entries_dict = [asdict(entry) for entry in mac_entries]

                # Write JSON output with pretty formatting
                with open(output_file_path, 'w', encoding='utf-8') as f:
                    json.dump(mac_entries_dict, f, indent=2, sort_keys=True)

                entry_count = len(mac_entries)
                results[txt_file.name] = entry_count

                logger.info(
                    f"✓ Processed {txt_file.name}: {entry_count} MAC entries → {output_filename}")

            except Exception as e:
                logger.error(f"✗ Failed to process {txt_file.name}: {e}")
                results[txt_file.name] = -1  # Error indicator

        return results


def main():
    """Main function with command line argument parsing"""
    parser = argparse.ArgumentParser(
        description="Parse Cisco MAC address tables from log files using TextFSM",
        epilog="Requires: pip install textfsm ntc-templates"
    )
    parser.add_argument(
        "input_dir",
        nargs="?",
        default=".",
        help="Directory containing .txt log files (default: current directory)"
    )
    parser.add_argument(
        "-o", "--output-dir",
        help="Output directory for JSON files (default: same as input directory)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        parser_instance = CiscoMacTableParser()
        results = parser_instance.process_directory(
            args.input_dir, args.output_dir)

        # Print summary
        print("\n" + "="*60)
        print("PROCESSING SUMMARY")
        print("="*60)

        successful = sum(1 for count in results.values() if count >= 0)
        failed = sum(1 for count in results.values() if count < 0)
        total_entries = sum(count for count in results.values() if count >= 0)

        print(f"Files processed: {len(results)}")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"Total MAC entries extracted: {total_entries}")

        if results:
            print("\nDetailed Results:")
            for filename, count in results.items():
                status = f"{count} entries" if count >= 0 else "FAILED"
                print(f"  {filename}: {status}")

    except Exception as e:
        logger.error(f"Application error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
