import datetime
import json
import logging
import re
import threading
import time
from pathlib import Path

import FreeSimpleGUI as sg
import serial
import serial.tools.list_ports

# --- TextFSM/NTC Templates Import ---
try:
    from ntc_templates.parse import parse_output
except ImportError:
    sg.popup_error(
        "NTC Templates library not found. Please install it: pip install ntc-templates",
        title="Import Error",
    )
    exit()

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(module)s - %(message)s"
)
logger = logging.getLogger(__name__)

# --- Import existing project modules ---
try:
    import config
    import data_manager
    import utils
except ImportError as e:
    sg.popup_error(
        f"Failed to import project modules (config.py, utils.py, data_manager.py).\nError: {e}",
        title="Import Error",
    )
    exit()

# --- Constants ---
APP_TITLE = "Cisco Raw Log Collector"
DEFAULT_NTC_PLATFORM = "cisco_ios"

WAVE1_CMDS_USER = [
    "terminal length 0",
    "show version",
    "show ip route",
    "show ipv6 route",
    "show ip interface",
    "show vlan brief",
    "show interface status",
    "show power inline",
    "show mac address-table",
    "show arp",
]
WAVE1_CMDS_PRIV = [
    "configure terminal",
    "lldp run",
    "cdp run",
    "exit",
    "show running-config",
]
WAVE2_CMDS = [
    "terminal length 0",
    "show version",
    "show lldp neighbors detail",
    "show cdp neighbors detail",
]


# --- Thread-safe Data Manager Wrapper ---
class ThreadSafeDataManager:
    def __init__(self):
        self._dm = data_manager.DataManager()
        self._lock = threading.Lock()

    def get_sites(self):
        with self._lock:
            return self._dm.get_sites()

    def get_buildings(self, site):
        with self._lock:
            return self._dm.get_buildings(site)

    def get_floors(self, site, building):
        with self._lock:
            return self._dm.get_floors(site, building)

    def get_wings(self, site, building, floor):
        with self._lock:
            return self._dm.get_wings(site, building, floor)

    def get_areas(self, site, building, floor, wing):
        with self._lock:
            return self._dm.get_areas(site, building, floor, wing)

    def add_wave2_completed_sn(self, sn, timestamp):
        with self._lock:
            return self._dm.add_wave2_completed_sn(sn, timestamp)


# --- Cisco Connection Handler ---
class CiscoConnection:
    def __init__(self, port, baudrate=9600, timeout=15):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.connection = None
        self.log_buffer = []
        self.hostname = "Unknown"
        self.prompt_pattern = re.compile(r"^\S+(?:\([^)]*\))?[>#]\s*$")

    def connect(self):
        """Establish connection and return status"""
        try:
            self.connection = serial.Serial(
                self.port, self.baudrate, timeout=self.timeout
            )
            time.sleep(0.2)
            self.connection.write(b"\r\n")
            time.sleep(0.5)

            # Get initial response to detect hostname
            initial = self._read_response(timeout=3)
            self._extract_hostname(initial)

            self.log_buffer.append(
                f"Connected to {self.port} - Hostname: {self.hostname}"
            )
            return True, f"Connected to {self.hostname}"
        except Exception as e:
            error_msg = f"Connection failed: {str(e)}"
            self.log_buffer.append(error_msg)
            return False, error_msg

    def _extract_hostname(self, text):
        """Extract hostname from device response"""
        lines = text.strip().split("\n")
        for line in reversed(lines):
            line = line.strip()
            if self.prompt_pattern.match(line):
                match = re.match(r"^(\S+)", line)
                if match:
                    self.hostname = match.group(1)
                    break

    def _read_response(self, timeout=10):
        """Read response until prompt is detected or timeout"""
        if not self.connection or not self.connection.is_open:
            return ""

        response = ""
        start_time = time.time()

        while (time.time() - start_time) < timeout:
            if self.connection.in_waiting > 0:
                try:
                    data = self.connection.read(self.connection.in_waiting)
                    chunk = data.decode("utf-8", errors="replace")
                    response += chunk

                    # Check if we have a complete line with prompt
                    lines = response.split("\n")
                    if lines and self.prompt_pattern.match(lines[-1].strip()):
                        # Remove prompt line
                        return response.rsplit("\n", 1)[0]

                except Exception as e:
                    logger.warning(f"Read error: {e}")
            time.sleep(0.01)

        return response

    def send_command(self, command):
        """Send command and return output"""
        if not self.connection or not self.connection.is_open:
            return "Error: Not connected"

        self.log_buffer.append(f">>> {command}")

        # Send command
        self.connection.write(command.encode("utf-8") + b"\r\n")

        # Dynamic wait based on command
        if any(x in command.lower() for x in ["show run", "show tech"]):
            time.sleep(1.5)
        elif "show version" in command.lower():
            time.sleep(1.0)
        else:
            time.sleep(0.5)

        # Read response with appropriate timeout
        timeout = 60 if "show run" in command.lower() else 20
        output = self._read_response(timeout=timeout)

        # Remove command echo
        if output.startswith(command):
            output = output[len(command) :].lstrip()

        self.log_buffer.append(output)
        return output

    def get_log(self):
        return "\n".join(self.log_buffer)

    def close(self):
        if self.connection and self.connection.is_open:
            self.connection.close()
            self.log_buffer.append(f"Disconnected from {self.port}")


# --- File Operations ---
def safe_file_write(filepath, content, mode="w"):
    """Thread-safe file writing with error handling"""
    try:
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, mode, encoding="utf-8") as f:
            if isinstance(content, dict):
                json.dump(content, f, indent=2, default=str)
            else:
                f.write(content)
        return True, str(filepath)
    except Exception as e:
        return False, f"File write error: {e}"


def extract_show_version_data(log_content):
    """Extract and parse show version output"""
    try:
        # Find show version output in log
        pattern = r">>> show version\s*\n(.*?)(?=>>>|\Z)"
        match = re.search(pattern, log_content, re.DOTALL)
        if not match:
            return None, None, None

        version_output = match.group(1).strip()

        # Parse with NTC templates
        parsed = parse_output(
            platform=DEFAULT_NTC_PLATFORM, command="show version", data=version_output
        )
        if not parsed or not parsed[0]:
            return None, None, None

        data = parsed[0]

        # Extract key information
        hostname = data.get("hostname", "Unknown")
        model = (
            data.get("hardware", ["Unknown"])[0] if data.get("hardware") else "Unknown"
        )

        # Get serial number
        serial = data.get("serial", [])
        if isinstance(serial, list) and serial:
            serial_num = str(serial[0]).strip().upper()
        elif serial:
            serial_num = str(serial).strip().upper()
        else:
            serial_num = None

        return hostname, model, serial_num

    except Exception as e:
        logger.error(f"Show version parsing error: {e}")
        return None, None, None


# --- Main Application ---
class CiscoCollectorApp:
    def __init__(self):
        self.dm = ThreadSafeDataManager()
        self.location_data = None
        self.com_port = None
        self.window = None

        # Get screen dimensions for scaling
        self.screen_width, self.screen_height = sg.Window.get_screen_size()

        # Calculate scaling factors based on screen size
        # Base design assumes 1920x1080, scale accordingly
        self.width_scale = max(1.0, self.screen_width / 1920)
        self.height_scale = max(1.0, self.screen_height / 1080)

        # Font scaling
        base_font_size = 10
        self.font_size = int(base_font_size * min(self.width_scale, self.height_scale))
        self.large_font_size = int(self.font_size * 1.2)

        # Element scaling
        self.combo_width = int(20 * self.width_scale)
        self.text_width = int(15 * self.width_scale)
        self.button_width = int(15 * self.width_scale)
        self.input_width = int(25 * self.width_scale)

    def create_layout(self):
        """Create scaled GUI layout with expandable elements"""

        # Set default font for all elements
        sg.set_options(font=("Arial", self.font_size))

        # Location Selection Section
        location_frame = [
            [
                sg.Text("Site:", size=(self.text_width, 1)),
                sg.Combo(
                    self.dm.get_sites() or ["No Sites"],
                    key="-SITE-",
                    size=(self.combo_width, 1),
                    enable_events=True,
                    readonly=True,
                    font=("Arial", self.font_size),
                    expand_x=True,
                ),
            ],
            [
                sg.Text("Building:", size=(self.text_width, 1)),
                sg.Combo(
                    [],
                    key="-BUILDING-",
                    size=(self.combo_width, 1),
                    enable_events=True,
                    readonly=True,
                    disabled=True,
                    font=("Arial", self.font_size),
                    expand_x=True,
                ),
            ],
            [
                sg.Text("Floor:", size=(self.text_width, 1)),
                sg.Combo(
                    [],
                    key="-FLOOR-",
                    size=(self.combo_width, 1),
                    enable_events=True,
                    readonly=True,
                    disabled=True,
                    font=("Arial", self.font_size),
                    expand_x=True,
                ),
            ],
            [
                sg.Text("Wing:", size=(self.text_width, 1)),
                sg.Combo(
                    [],
                    key="-WING-",
                    size=(self.combo_width, 1),
                    enable_events=True,
                    readonly=True,
                    disabled=True,
                    font=("Arial", self.font_size),
                    expand_x=True,
                ),
            ],
            [
                sg.Text("Area:", size=(self.text_width, 1)),
                sg.Combo(
                    [],
                    key="-AREA-",
                    size=(int(self.combo_width * 1.5), 1),
                    enable_events=True,
                    readonly=True,
                    disabled=True,
                    font=("Arial", self.font_size),
                    expand_x=True,
                ),
            ],
        ]

        # Connection Section
        connection_frame = [
            [
                sg.Text("COM Port:", size=(self.text_width, 1)),
                sg.Combo(
                    self.get_com_ports(),
                    key="-COM-PORT-",
                    size=(int(self.combo_width * 0.8), 1),
                    enable_events=True,
                    font=("Arial", self.font_size),
                    expand_x=True,
                ),
            ],
            [
                sg.Button(
                    "Refresh",
                    key="-REFRESH-COM-",
                    size=(int(self.button_width * 0.6), 1),
                    font=("Arial", self.font_size),
                ),
            ],
            [sg.HSeparator()],
            [
                sg.Button(
                    "Setup Complete",
                    key="-SETUP-COMPLETE-",
                    size=(self.button_width, 1),
                    disabled=True,
                    font=("Arial", self.font_size),
                    expand_x=True,
                ),
            ],
            [
                sg.Button(
                    "Reset",
                    key="-RESET-",
                    size=(int(self.button_width * 0.6), 1),
                    font=("Arial", self.font_size),
                ),
            ],
        ]

        # Device Info Section
        device_frame = [
            [sg.Text("Access Level:", font=("Arial", self.font_size))],
            [
                sg.Radio(
                    "User Mode (>)",
                    "ACCESS",
                    key="-USER-",
                    default=True,
                    font=("Arial", self.font_size),
                ),
                sg.Radio(
                    "Privileged (#)",
                    "ACCESS",
                    key="-PRIV-",
                    font=("Arial", self.font_size),
                ),
            ],
            [
                sg.Text("Location Detail:", font=("Arial", self.font_size)),
            ],
            [
                sg.Input(
                    key="-LOCATION-DETAIL-",
                    size=(self.input_width, 1),
                    font=("Arial", self.font_size),
                    expand_x=True,
                ),
            ],
            [
                sg.Text("Rack Type:", font=("Arial", self.font_size)),
                sg.Combo(
                    [
                        "",
                        "Network",
                        "Server",
                        "Mini",
                        "Ceiling",
                        "Floor",
                        "Wall",
                        "Other",
                    ],
                    key="-RACK-TYPE-",
                    size=(int(self.combo_width * 0.7), 1),
                    font=("Arial", self.font_size),
                    expand_x=True,
                ),
            ],
            [
                sg.Text("PoE Capable:", font=("Arial", self.font_size)),
                sg.Radio("Yes", "POE", key="-POE-YES-", font=("Arial", self.font_size)),
                sg.Radio(
                    "No",
                    "POE",
                    key="-POE-NO-",
                    default=True,
                    font=("Arial", self.font_size),
                ),
            ],
        ]

        # Calculate frame sizes based on scaling
        frame_height = int(280 * self.height_scale)

        # Main layout with horizontal expansion
        layout = [
            [
                sg.Frame(
                    "Location Setup",
                    location_frame,
                    size=(None, frame_height),
                    font=("Arial", self.large_font_size),
                    expand_x=True,
                    element_justification="left",
                ),
                sg.Frame(
                    "Connection",
                    connection_frame,
                    size=(None, frame_height),
                    font=("Arial", self.large_font_size),
                    expand_x=True,
                    element_justification="center",
                ),
                sg.Frame(
                    "Device Info",
                    device_frame,
                    size=(None, frame_height),
                    font=("Arial", self.large_font_size),
                    expand_x=True,
                    element_justification="left",
                ),
            ],
            [sg.HSeparator()],
            [
                sg.Button(
                    "Run Wave 1",
                    key="-WAVE1-",
                    size=(int(self.button_width * 0.8), 3),
                    disabled=True,
                    font=("Arial", self.large_font_size),
                ),
                sg.Button(
                    "Run Wave 2",
                    key="-WAVE2-",
                    size=(int(self.button_width * 0.8), 3),
                    disabled=True,
                    font=("Arial", self.large_font_size),
                ),
                sg.Push(),
                sg.Text(
                    "Status: Ready",
                    key="-STATUS-",
                    font=("Arial", self.font_size),
                    expand_x=True,
                    justification="right",
                ),
            ],
            [
                sg.Multiline(
                    size=(int(120 * self.width_scale), int(20 * self.height_scale)),
                    key="-OUTPUT-",
                    autoscroll=True,
                    font=("Courier", max(9, int(self.font_size * 0.9))),
                    disabled=True,
                    expand_x=True,
                    expand_y=True,
                )
            ],
        ]

        return layout

    def get_com_ports(self):
        """Get available COM ports"""
        try:
            return [port.device for port in serial.tools.list_ports.comports()]
        except:
            return []

    def update_dropdowns(self, level, values):
        """Update location dropdowns based on selection"""
        site = values.get("-SITE-")
        building = values.get("-BUILDING-")
        floor = values.get("-FLOOR-")
        wing = values.get("-WING-")

        if level == "site" and site:
            buildings = self.dm.get_buildings(site)
            self.window["-BUILDING-"].update(
                values=buildings, value="", disabled=not buildings
            )
            for key in ["-FLOOR-", "-WING-", "-AREA-"]:
                self.window[key].update(values=[], value="", disabled=True)

        elif level == "building" and site and building:
            floors = self.dm.get_floors(site, building)
            self.window["-FLOOR-"].update(values=floors, value="", disabled=not floors)
            for key in ["-WING-", "-AREA-"]:
                self.window[key].update(values=[], value="", disabled=True)

        elif level == "floor" and site and building and floor:
            wings = self.dm.get_wings(site, building, floor)
            if not wings or wings == ["N/A"]:
                self.window["-WING-"].update(
                    values=["N/A"], value="N/A", disabled=False
                )
                areas = self.dm.get_areas(site, building, floor, "N/A")
                self.window["-AREA-"].update(
                    values=areas or [], value="", disabled=not areas
                )
            else:
                self.window["-WING-"].update(values=wings, value="", disabled=False)
                self.window["-AREA-"].update(values=[], value="", disabled=True)

        elif level == "wing" and site and building and floor and wing:
            areas = self.dm.get_areas(site, building, floor, wing)
            self.window["-AREA-"].update(
                values=areas or [], value="", disabled=not areas
            )

        # Check if setup can be completed
        can_complete = all(
            [
                values.get("-SITE-"),
                values.get("-BUILDING-"),
                values.get("-FLOOR-"),
                values.get("-WING-"),
                values.get("-AREA-"),
                values.get("-COM-PORT-"),
            ]
        )
        self.window["-SETUP-COMPLETE-"].update(disabled=not can_complete)

    def complete_setup(self, values):
        """Complete location and connection setup"""
        self.location_data = {
            "site": values["-SITE-"],
            "building": values["-BUILDING-"],
            "floor": values["-FLOOR-"],
            "wing": values["-WING-"] if values["-WING-"] != "N/A" else "",
            "area_name": values["-AREA-"],
        }
        self.com_port = values["-COM-PORT-"]

        # Disable setup controls
        setup_keys = [
            "-SITE-",
            "-BUILDING-",
            "-FLOOR-",
            "-WING-",
            "-AREA-",
            "-COM-PORT-",
            "-REFRESH-COM-",
            "-SETUP-COMPLETE-",
        ]
        for key in setup_keys:
            self.window[key].update(disabled=True)

        # Enable wave buttons
        self.window["-WAVE1-"].update(disabled=False)
        self.window["-WAVE2-"].update(disabled=False)

        self.log(
            f"Setup Complete - Location: {self.location_data['site']}/{self.location_data['building']}/{self.location_data['floor']}"
        )
        self.log(f"COM Port: {self.com_port}")

    def reset_setup(self):
        """Reset all setup"""
        self.location_data = None
        self.com_port = None

        # Reset dropdowns
        self.window["-SITE-"].update(value="", disabled=False)
        for key in ["-BUILDING-", "-FLOOR-", "-WING-", "-AREA-"]:
            self.window[key].update(value="", values=[], disabled=True)

        self.window["-COM-PORT-"].update(
            value="", values=self.get_com_ports(), disabled=False
        )
        self.window["-REFRESH-COM-"].update(disabled=False)
        self.window["-SETUP-COMPLETE-"].update(disabled=True)

        # Disable wave buttons
        self.window["-WAVE1-"].update(disabled=True)
        self.window["-WAVE2-"].update(disabled=True)

        self.log("Setup Reset")

    def run_wave(self, wave_num, values):
        """Execute wave collection"""
        if not self.location_data or not self.com_port:
            sg.popup_error("Complete setup first!")
            return

        self.window["-STATUS-"].update(f"Running Wave {wave_num}...")
        self.log(f"\n=== Starting Wave {wave_num} Collection ===")

        # Determine commands
        if wave_num == 1:
            commands = list(WAVE1_CMDS_USER)
            if values["-PRIV-"]:
                commands.extend(WAVE1_CMDS_PRIV)
        else:
            commands = WAVE2_CMDS

        # Execute collection
        conn = CiscoConnection(self.com_port)
        try:
            # Connect
            success, msg = conn.connect()
            if not success:
                sg.popup_error(f"Connection failed: {msg}")
                return

            self.log(f"Connected: {msg}")

            # Send commands
            for cmd in commands:
                self.log(f"Sending: {cmd}")
                self.window["-STATUS-"].update(f"Wave {wave_num}: {cmd[:30]}...")
                self.window.refresh()
                conn.send_command(cmd)

            # Get results
            log_content = conn.get_log()
            hostname, model, serial_num = extract_show_version_data(log_content)

            if not serial_num:
                sg.popup_error("Could not extract serial number!")
                return

            self.log(
                f"Device Info - Host: {hostname}, Model: {model}, SN: {serial_num}"
            )

            # Save files
            self.save_wave_data(
                wave_num, log_content, hostname, model, serial_num, values
            )

            self.window["-STATUS-"].update(f"Wave {wave_num} Complete")
            self.log(f"=== Wave {wave_num} Collection Complete ===\n")

        except Exception as e:
            error_msg = f"Wave {wave_num} failed: {str(e)}"
            self.log(error_msg)
            sg.popup_error(error_msg)
        finally:
            conn.close()

    def save_wave_data(
        self, wave_num, log_content, hostname, model, serial_num, values
    ):
        """Save wave data and metadata"""
        # Create folder structure
        site_folder = utils.sanitize_foldername_part(
            self.location_data["site"], "NoSite"
        )
        loc_segment = utils.format_location_log_folder_segment(
            building=self.location_data["building"],
            floor=self.location_data["floor"],
            wing=self.location_data["wing"],
            area_name=self.location_data["area_name"],
            wing_placeholder="NoWing",
            area_placeholder="NoArea",
        )

        log_dir = Path(config.LOGS_DIR) / site_folder / loc_segment
        base_filename = utils.generate_safe_filename(serial_num)

        # Save log file
        log_file = log_dir / f"{base_filename}-WAVE{wave_num}.txt"
        success, filepath = safe_file_write(log_file, log_content)
        if success:
            self.log(f"Log saved: {filepath}")
        else:
            self.log(f"Log save failed: {filepath}")

        # Save metadata for Wave 1
        if wave_num == 1:
            metadata = {
                "helper_script_version": config.APP_VERSION,
                "metadata_capture_timestamp": datetime.datetime.now().isoformat(),
                "access_level": "Privileged" if values["-PRIV-"] else "User",
                "device_type": "Switch",
                "final_hostname": hostname or "Unknown",
                "final_serial_number": serial_num,
                "final_make": "Cisco",
                "final_model": model or "Unknown",
                "is_poe_capable": 1 if values["-POE-YES-"] else 0,
                "final_rack_type_detail": values["-RACK-TYPE-"] or "N/A",
                "final_site": self.location_data["site"],
                "final_building": self.location_data["building"],
                "final_floor": self.location_data["floor"],
                "final_wing": self.location_data["wing"],
                "final_area_name": self.location_data["area_name"],
                "final_location_notes": values["-LOCATION-DETAIL-"].strip() or "N/A",
            }

            meta_dir = Path(config.METADATA_DIR) / site_folder / loc_segment
            meta_file = meta_dir / f"{base_filename}-WAVE1.meta.json"
            success, filepath = safe_file_write(meta_file, metadata)
            if success:
                self.log(f"Metadata saved: {filepath}")
            else:
                self.log(f"Metadata save failed: {filepath}")

        # Update Wave 2 completion status
        elif wave_num == 2:
            timestamp = datetime.datetime.now().isoformat()
            success, msg = self.dm.add_wave2_completed_sn(serial_num, timestamp)
            if success:
                self.log(f"Wave 2 completion recorded for SN: {serial_num}")
            else:
                self.log(f"Wave 2 completion update failed: {msg}")

    def log(self, message):
        """Add message to output log"""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.window["-OUTPUT-"].print(f"[{timestamp}] {message}")

    def run(self):
        """Main application loop"""
        # Create window with maximized state and scaling
        self.window = sg.Window(
            APP_TITLE,
            self.create_layout(),
            finalize=True,
            resizable=True,
            size=(int(self.screen_width * 0.95), int(self.screen_height * 0.9)),
            location=(0, 0),
            return_keyboard_events=True,
            use_default_focus=False,
        )

        # Maximize the window
        self.window.maximize()

        while True:
            event, values = self.window.read(timeout=100)

            if event == sg.WIN_CLOSED:
                break

            # Location dropdown events
            elif event == "-SITE-":
                self.update_dropdowns("site", values)
            elif event == "-BUILDING-":
                self.update_dropdowns("building", values)
            elif event == "-FLOOR-":
                self.update_dropdowns("floor", values)
            elif event == "-WING-":
                self.update_dropdowns("wing", values)
            elif event == "-AREA-":
                self.update_dropdowns("area", values)
            elif event == "-COM-PORT-":
                can_complete = all(
                    [
                        values.get("-SITE-"),
                        values.get("-BUILDING-"),
                        values.get("-FLOOR-"),
                        values.get("-WING-"),
                        values.get("-AREA-"),
                        values.get("-COM-PORT-"),
                    ]
                )
                self.window["-SETUP-COMPLETE-"].update(disabled=not can_complete)

            # Control events
            elif event == "-REFRESH-COM-":
                self.window["-COM-PORT-"].update(values=self.get_com_ports(), value="")
            elif event == "-SETUP-COMPLETE-":
                self.complete_setup(values)
            elif event == "-RESET-":
                self.reset_setup()
            elif event == "-WAVE1-":
                self.run_wave(1, values)
            elif event == "-WAVE2-":
                if (
                    sg.popup_yes_no(
                        "Ensure device is in PRIVILEGED mode (#) for Wave 2.\n\nContinue?"
                    )
                    == "Yes"
                ):
                    self.run_wave(2, values)

        self.window.close()


# --- Application Entry Point ---
if __name__ == "__main__":
    try:
        app = CiscoCollectorApp()
        app.run()
    except Exception as e:
        sg.popup_error(f"Application error: {e}")
        logger.error(f"Application error: {e}")
