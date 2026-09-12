import datetime
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Dict, Optional

import FreeSimpleGUI as sg
import serial
import serial.tools.list_ports

# --- TextFSM/NTC Templates Import ---
try:
    from ntc_templates.parse import parse_output
except ImportError:
    sg.popup_error(
        "NTC Templates library not found. Please install it: pip install ntc-templates"
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
    sg.popup_error(f"Failed to import project modules: {e}")
    exit()

# --- Constants ---
APP_TITLE = "Cisco Raw Log Collector - Multi-Instance"
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


@dataclass
class LocationData:
    site: str
    building: str
    floor: str
    wing: str
    area_name: str


@dataclass
class DeviceInfo:
    hostname: str = "Unknown"
    model: str = "Unknown"
    serial_num: Optional[str] = None


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
        try:
            self.connection = serial.Serial(
                self.port, self.baudrate, timeout=self.timeout
            )
            time.sleep(0.2)
            self.connection.write(b"\r\n")
            time.sleep(0.5)

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
        lines = text.strip().split("\n")
        for line in reversed(lines):
            line = line.strip()
            if self.prompt_pattern.match(line):
                match = re.match(r"^(\S+)", line)
                if match:
                    self.hostname = match.group(1)
                    break

    def _read_response(self, timeout=10):
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

                    lines = response.split("\n")
                    if lines and self.prompt_pattern.match(lines[-1].strip()):
                        return response.rsplit("\n", 1)[0]
                except Exception as e:
                    logger.warning(f"Read error: {e}")
            time.sleep(0.01)
        return response

    def send_command(self, command):
        if not self.connection or not self.connection.is_open:
            return "Error: Not connected"

        self.log_buffer.append(f">>> {command}")
        self.connection.write(command.encode("utf-8") + b"\r\n")

        # Dynamic wait based on command
        if any(x in command.lower() for x in ["show run", "show tech"]):
            time.sleep(1.5)
        elif "show version" in command.lower():
            time.sleep(1.0)
        else:
            time.sleep(0.5)

        timeout = 60 if "show run" in command.lower() else 20
        output = self._read_response(timeout=timeout)

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


class WaveRunner:
    def __init__(self, instance_id: str, message_queue: Queue):
        self.instance_id = instance_id
        self.message_queue = message_queue

    def log(self, message):
        self.message_queue.put((self.instance_id, "log", message))

    def update_status(self, status):
        self.message_queue.put((self.instance_id, "status", status))

    def run_wave(
        self,
        wave_num: int,
        com_port: str,
        location_data: LocationData,
        device_config: Dict[str, Any],
    ):
        try:
            self.log(f"Starting Wave {wave_num} Collection on {com_port}")
            self.update_status(f"Running Wave {wave_num}...")

            # Determine commands
            commands = list(WAVE1_CMDS_USER)
            if wave_num == 1 and device_config.get("privileged", False):
                commands.extend(WAVE1_CMDS_PRIV)
            elif wave_num == 2:
                commands = WAVE2_CMDS

            # Execute collection
            conn = CiscoConnection(com_port)
            success, msg = conn.connect()
            if not success:
                self.log(f"Connection failed: {msg}")
                self.update_status("Connection Failed")
                return

            self.log(f"Connected: {msg}")

            # Send commands
            for cmd in commands:
                self.log(f"Sending: {cmd}")
                self.update_status(f"Wave {wave_num}: {cmd[:30]}...")
                conn.send_command(cmd)

            # Get results and extract device info
            log_content = conn.get_log()
            device_info = self._extract_device_info(log_content)

            if not device_info.serial_num:
                self.log("Could not extract serial number!")
                self.update_status("Serial Number Error")
                return

            self.log(
                f"Device Info - Host: {device_info.hostname}, Model: {device_info.model}, SN: {device_info.serial_num}"
            )

            # Save files
            self._save_wave_data(
                wave_num, log_content, device_info, location_data, device_config
            )

            self.update_status(f"Wave {wave_num} Complete")
            self.log(f"Wave {wave_num} Collection Complete")

        except Exception as e:
            error_msg = f"Wave {wave_num} failed: {str(e)}"
            self.log(error_msg)
            self.update_status("Error")
        finally:
            if "conn" in locals():
                conn.close()

    def _extract_device_info(self, log_content) -> DeviceInfo:
        try:
            pattern = r">>> show version\s*\n(.*?)(?=>>>|\Z)"
            match = re.search(pattern, log_content, re.DOTALL)
            if not match:
                return DeviceInfo()

            version_output = match.group(1).strip()
            parsed = parse_output(
                platform=DEFAULT_NTC_PLATFORM,
                command="show version",
                data=version_output,
            )
            if not parsed or not parsed[0]:
                return DeviceInfo()

            data = parsed[0]
            hostname = data.get("hostname", "Unknown")
            model = (
                data.get("hardware", ["Unknown"])[0]
                if data.get("hardware")
                else "Unknown"
            )

            serial = data.get("serial", [])
            if isinstance(serial, list) and serial:
                serial_num = str(serial[0]).strip().upper()
            elif serial:
                serial_num = str(serial).strip().upper()
            else:
                serial_num = None

            return DeviceInfo(hostname=hostname, model=model, serial_num=serial_num)
        except Exception as e:
            logger.error(f"Device info parsing error: {e}")
            return DeviceInfo()

    def _save_wave_data(
        self,
        wave_num: int,
        log_content: str,
        device_info: DeviceInfo,
        location_data: LocationData,
        device_config: Dict[str, Any],
    ):
        # Create folder structure
        site_folder = utils.sanitize_foldername_part(location_data.site, "NoSite")
        loc_segment = utils.format_location_log_folder_segment(
            building=location_data.building,
            floor=location_data.floor,
            wing=location_data.wing,
            area_name=location_data.area_name,
            wing_placeholder="NoWing",
            area_placeholder="NoArea",
        )

        log_dir = Path(config.LOGS_DIR) / site_folder / loc_segment
        base_filename = utils.generate_safe_filename(device_info.serial_num)

        # Save log file
        log_file = log_dir / f"{base_filename}-WAVE{wave_num}.txt"
        success, filepath = self._safe_file_write(log_file, log_content)
        if success:
            self.log(f"Log saved: {filepath}")
        else:
            self.log(f"Log save failed: {filepath}")

        # Save metadata for Wave 1
        if wave_num == 1:
            metadata = {
                "helper_script_version": config.APP_VERSION,
                "metadata_capture_timestamp": datetime.datetime.now().isoformat(),
                "access_level": "Privileged"
                if device_config.get("privileged", False)
                else "User",
                "device_type": "Switch",
                "final_hostname": device_info.hostname,
                "final_serial_number": device_info.serial_num,
                "final_make": "Cisco",
                "final_model": device_info.model,
                "is_poe_capable": 1 if device_config.get("poe_capable", False) else 0,
                "final_rack_type_detail": device_config.get("rack_type", "N/A"),
                "final_site": location_data.site,
                "final_building": location_data.building,
                "final_floor": location_data.floor,
                "final_wing": location_data.wing,
                "final_area_name": location_data.area_name,
                "final_location_notes": device_config.get("location_detail", "N/A"),
            }

            meta_dir = Path(config.METADATA_DIR) / site_folder / loc_segment
            meta_file = meta_dir / f"{base_filename}-WAVE1.meta.json"
            success, filepath = self._safe_file_write(meta_file, metadata)
            if success:
                self.log(f"Metadata saved: {filepath}")
            else:
                self.log(f"Metadata save failed: {filepath}")

        # Update Wave 2 completion status
        elif wave_num == 2:
            dm = ThreadSafeDataManager()
            timestamp = datetime.datetime.now().isoformat()
            success, msg = dm.add_wave2_completed_sn(device_info.serial_num, timestamp)
            if success:
                self.log(f"Wave 2 completion recorded for SN: {device_info.serial_num}")
            else:
                self.log(f"Wave 2 completion update failed: {msg}")

    def _safe_file_write(self, filepath, content, mode="w"):
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


class CiscoCollectorApp:
    def __init__(self):
        self.dm = ThreadSafeDataManager()
        self.message_queue = Queue()
        self.instances = {"Instance 1": {}, "Instance 2": {}}
        self.current_instance = "Instance 1"

        # GUI scaling
        self.screen_width, self.screen_height = sg.Window.get_screen_size()
        self.width_scale = max(1.0, self.screen_width / 1920)
        self.height_scale = max(1.0, self.screen_height / 1080)
        self.font_size = int(10 * min(self.width_scale, self.height_scale))

        self.window = None

    def get_com_ports(self):
        try:
            return [port.device for port in serial.tools.list_ports.comports()]
        except:
            return []

    def create_layout(self):
        sg.set_options(font=("Arial", self.font_size))

        # Instance selector
        instance_frame = [
            [
                sg.Radio(
                    "Instance 1",
                    "INSTANCE",
                    key="-INSTANCE1-",
                    default=True,
                    enable_events=True,
                ),
                sg.Radio(
                    "Instance 2", "INSTANCE", key="-INSTANCE2-", enable_events=True
                ),
            ]
        ]

        # Location selection (reusable for both instances)
        location_frame = [
            [
                sg.Text("Site:"),
                sg.Combo(
                    self.dm.get_sites() or ["No Sites"],
                    key="-SITE-",
                    enable_events=True,
                    readonly=True,
                    expand_x=True,
                ),
            ],
            [
                sg.Text("Building:"),
                sg.Combo(
                    [],
                    key="-BUILDING-",
                    enable_events=True,
                    readonly=True,
                    disabled=True,
                    expand_x=True,
                ),
            ],
            [
                sg.Text("Floor:"),
                sg.Combo(
                    [],
                    key="-FLOOR-",
                    enable_events=True,
                    readonly=True,
                    disabled=True,
                    expand_x=True,
                ),
            ],
            [
                sg.Text("Wing:"),
                sg.Combo(
                    [],
                    key="-WING-",
                    enable_events=True,
                    readonly=True,
                    disabled=True,
                    expand_x=True,
                ),
            ],
            [
                sg.Text("Area:"),
                sg.Combo(
                    [],
                    key="-AREA-",
                    enable_events=True,
                    readonly=True,
                    disabled=True,
                    expand_x=True,
                ),
            ],
        ]

        # Connection and device info
        config_frame = [
            [
                sg.Text("COM Port:"),
                sg.Combo(
                    self.get_com_ports(),
                    key="-COM-PORT-",
                    enable_events=True,
                    expand_x=True,
                ),
                sg.Button("Refresh", key="-REFRESH-COM-", size=(8, 1)),
            ],
            [
                sg.Text("Access Level:"),
                sg.Radio("User (>)", "ACCESS", key="-USER-", default=True),
                sg.Radio("Privileged (#)", "ACCESS", key="-PRIV-"),
            ],
            [
                sg.Text("Location Detail:"),
                sg.Input(key="-LOCATION-DETAIL-", expand_x=True),
            ],
            [
                sg.Text("Rack Type:"),
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
                    expand_x=True,
                ),
            ],
            [
                sg.Text("PoE Capable:"),
                sg.Radio("Yes", "POE", key="-POE-YES-"),
                sg.Radio("No", "POE", key="-POE-NO-", default=True),
            ],
        ]

        # Control buttons
        control_frame = [
            [
                sg.Button(
                    "Setup Complete",
                    key="-SETUP-COMPLETE-",
                    disabled=True,
                    expand_x=True,
                )
            ],
            [sg.Button("Reset", key="-RESET-", size=(10, 1))],
            [sg.HSeparator()],
            [
                sg.Button("Run Wave 1", key="-WAVE1-", disabled=True, size=(12, 2)),
                sg.Button("Run Wave 2", key="-WAVE2-", disabled=True, size=(12, 2)),
            ],
        ]

        # Status display
        status_frame = [
            [
                sg.Text("Instance 1 Status:", size=(15, 1)),
                sg.Text("Ready", key="-STATUS1-", expand_x=True),
            ],
            [
                sg.Text("Instance 2 Status:", size=(15, 1)),
                sg.Text("Ready", key="-STATUS2-", expand_x=True),
            ],
        ]

        layout = [
            [sg.Frame("Instance Selection", instance_frame, expand_x=True)],
            [
                sg.Frame("Location Setup", location_frame, expand_x=True),
                sg.Frame("Configuration", config_frame, expand_x=True),
                sg.Frame("Controls", control_frame),
            ],
            [sg.Frame("Status", status_frame, expand_x=True)],
            [
                sg.Multiline(
                    size=(120, 20),
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

    def switch_instance(self, new_instance):
        if new_instance == self.current_instance:
            return

        # Save current instance state
        current_values = self.get_current_values()
        self.instances[self.current_instance] = current_values

        # Switch to new instance
        self.current_instance = new_instance
        self.load_instance_data(new_instance)
        self.log(f"Switched to {new_instance}")

    def get_current_values(self):
        if not self.window:
            return {}

        values = {}
        for key in [
            "-SITE-",
            "-BUILDING-",
            "-FLOOR-",
            "-WING-",
            "-AREA-",
            "-COM-PORT-",
            "-LOCATION-DETAIL-",
            "-RACK-TYPE-",
            "-USER-",
            "-PRIV-",
            "-POE-YES-",
            "-POE-NO-",
        ]:
            try:
                values[key] = self.window[key].get()
            except:
                values[key] = ""
        return values

    def load_instance_data(self, instance_name):
        data = self.instances.get(instance_name, {})

        # Load values back to GUI
        for key, value in data.items():
            if key in self.window.AllKeysDict:
                try:
                    if key in ["-USER-", "-PRIV-", "-POE-YES-", "-POE-NO-"]:
                        self.window[key].update(value=value)
                    else:
                        self.window[key].update(value)
                except:
                    pass

        # Update setup button state
        self.update_setup_button_state()

    def update_dropdowns(self, level, values):
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

        self.update_setup_button_state()

    def update_setup_button_state(self):
        values = self.get_current_values()
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

    def complete_setup(self):
        values = self.get_current_values()
        instance_data = self.instances[self.current_instance]

        instance_data["setup_complete"] = True
        instance_data["location_data"] = LocationData(
            site=values["-SITE-"],
            building=values["-BUILDING-"],
            floor=values["-FLOOR-"],
            wing=values["-WING-"] if values["-WING-"] != "N/A" else "",
            area_name=values["-AREA-"],
        )
        instance_data["com_port"] = values["-COM-PORT-"]
        instance_data["device_config"] = {
            "privileged": values["-PRIV-"],
            "poe_capable": values["-POE-YES-"],
            "rack_type": values["-RACK-TYPE-"],
            "location_detail": values["-LOCATION-DETAIL-"].strip(),
        }

        # Enable wave buttons
        self.window["-WAVE1-"].update(disabled=False)
        self.window["-WAVE2-"].update(disabled=False)

        self.log(
            f"{self.current_instance} setup complete - COM: {values['-COM-PORT-']}"
        )

    def reset_instance(self):
        self.instances[self.current_instance] = {}

        # Reset GUI
        self.window["-SITE-"].update(value="")
        for key in ["-BUILDING-", "-FLOOR-", "-WING-", "-AREA-"]:
            self.window[key].update(value="", values=[], disabled=True)
        self.window["-COM-PORT-"].update(value="", values=self.get_com_ports())
        self.window["-LOCATION-DETAIL-"].update("")
        self.window["-RACK-TYPE-"].update("")
        self.window["-USER-"].update(True)
        self.window["-POE-NO-"].update(True)

        # Disable buttons
        self.window["-SETUP-COMPLETE-"].update(disabled=True)
        self.window["-WAVE1-"].update(disabled=True)
        self.window["-WAVE2-"].update(disabled=True)

        self.log(f"{self.current_instance} reset")

    def run_wave(self, wave_num):
        instance_data = self.instances[self.current_instance]
        if not instance_data.get("setup_complete"):
            sg.popup_error("Complete setup first!")
            return

        if wave_num == 2:
            if (
                sg.popup_yes_no(
                    "Ensure device is in PRIVILEGED mode (#) for Wave 2.\n\nContinue?"
                )
                != "Yes"
            ):
                return

        # Run in separate thread
        runner = WaveRunner(self.current_instance, self.message_queue)
        thread = threading.Thread(
            target=runner.run_wave,
            args=(
                wave_num,
                instance_data["com_port"],
                instance_data["location_data"],
                instance_data["device_config"],
            ),
            daemon=True,
        )
        thread.start()

    def process_messages(self):
        try:
            while True:
                instance_id, msg_type, message = self.message_queue.get_nowait()

                if msg_type == "log":
                    self.log(f"[{instance_id}] {message}")
                elif msg_type == "status":
                    status_key = (
                        "-STATUS1-" if instance_id == "Instance 1" else "-STATUS2-"
                    )
                    self.window[status_key].update(message)
        except Empty:
            pass

    def log(self, message):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.window["-OUTPUT-"].print(f"[{timestamp}] {message}")

    def run(self):
        self.window = sg.Window(
            APP_TITLE,
            self.create_layout(),
            finalize=True,
            resizable=True,
            size=(int(self.screen_width * 0.95), int(self.screen_height * 0.9)),
        )
        self.window.maximize()

        while True:
            event, values = self.window.read(timeout=100)

            # Process background messages
            self.process_messages()

            if event == sg.WIN_CLOSED:
                break

            # Instance switching
            elif event == "-INSTANCE1-":
                self.switch_instance("Instance 1")
            elif event == "-INSTANCE2-":
                self.switch_instance("Instance 2")

            # Location dropdown events
            elif event in ["-SITE-", "-BUILDING-", "-FLOOR-", "-WING-", "-AREA-"]:
                level = event.replace("-", "").replace("-", "").lower()
                self.update_dropdowns(level, values)
            elif event == "-COM-PORT-":
                self.update_setup_button_state()

            # Control events
            elif event == "-REFRESH-COM-":
                self.window["-COM-PORT-"].update(values=self.get_com_ports(), value="")
            elif event == "-SETUP-COMPLETE-":
                self.complete_setup()
            elif event == "-RESET-":
                self.reset_instance()
            elif event == "-WAVE1-":
                self.run_wave(1)
            elif event == "-WAVE2-":
                self.run_wave(2)

        self.window.close()


if __name__ == "__main__":
    try:
        app = CiscoCollectorApp()
        app.run()
    except Exception as e:
        sg.popup_error(f"Application error: {e}")
        logger.error(f"Application error: {e}")
