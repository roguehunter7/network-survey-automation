# diagram_config_utils.py
"""
Configuration constants and basic utility functions for the network diagram generator.
"""

import os
import re
import sqlite3
from typing import Optional

# --- Database and Path Constants ---
DB_FILE = "network_survey.db"  # Database used by diagramming scripts
OUTPUT_DIR = "network_diagrams_pydot_final"  # Output for diagrams
DEFAULT_OUTPUT_FORMAT_EXT = ".png"
DEFAULT_GRAPH_DIRECTION = "TD"  # Top-to-Down default layout

# --- MAC Inference Parameters ---
ORIGINAL_MAC_INFERENCE_MIN_SHARED_MACS = 1
ORIGINAL_MAC_INFERENCE_MIN_JACCARD_INDEX = 0.5

# These can be temporarily modified by the inference engine for relaxed passes
MAC_INFERENCE_MIN_SHARED_MACS = ORIGINAL_MAC_INFERENCE_MIN_SHARED_MACS
MAC_INFERENCE_MIN_JACCARD_INDEX = ORIGINAL_MAC_INFERENCE_MIN_JACCARD_INDEX

# --- Role Inference Constants ---
ROLE_CORE_MIN_INTER_SWITCH_DEGREE = 4
ROLE_CORE_MIN_BETWEENNESS_SCALED = 0.1
ROLE_ACCESS_MAX_INTER_SWITCH_DEGREE = 2
ROLE_ACCESS_MAX_BETWEENNESS_SCALED = 0.05

# --- AP Linking Constants ---
MAX_AP_PORT_INDEX_TO_CHECK = 4  # Max port index (0-based) for MAC variation

# --- Pydot Styling Constants ---
PYDOT_NODE_DEFAULTS = {
    "shape": "box",
    "style": "solid",
    "fontname": "Helvetica",
    "fontsize": "10",
}
PYDOT_EDGE_DEFAULTS = {"fontname": "Helvetica", "fontsize": "7"}

PYDOT_GRAPH_DEFAULTS = {
    "overlap": "prism",
    "beautify": "true",
    "splines": "true",
    "sep": "+30",
    "K": "0.8",
    "smoothing": "graph_dist",
    "pack": "true",
    "packmode": "graph",
    "outputorder": "edgesfirst",
    "repulsiveforce": "1.5",
    "normalize": "true",
}

NODE_STYLE_MAP = {
    "managed_in_scope": (None, "#3498DB", "2", "box", "solid"),
    "managed_out_of_scope": (None, "#8E44AD", "1.5", "box", '"solid,dashed"'),
    "ap_in_scope": (None, "#2ECC71", "2", "diamond", "solid"),
    "ap_out_of_scope": (None, "#E74C3C", "1.5", "diamond", '"solid,dashed"'),
    "external": (None, "#F39C12", "1.5", "ellipse", "solid"),
    "unsurveyed_network_device": (None, "#5D6D7E", "1.5", "box", '"solid,dashed"'),
    "router_in_scope": (None, "#AF7AC5", "2", "oval", "solid"),
    "router_out_of_scope": (None, "#AF7AC5", "1.5", "oval", '"solid,dashed"'),
    # LightGrey fill, DarkGray border
    "unmanaged_switch_in_scope": ("#E0E0E0", "#A9A9A9", "1.5", "box", '"solid,filled"'),
}

CLUSTER_ORDER = [
    "Core",
    "Router",
    "Distribution",
    "Access",
    "APs",
    "Unmanaged Devices",
    "External",
]
CLUSTER_LABELS = {
    "Core": "Core Switches",
    "Router": "Routers",
    "Distribution": "Distribution Switches",
    "Access": "Access Switches",
    "APs": "Access Points",
    "Unmanaged Devices": "Unmanaged Network Devices",  # New Label
    "External": "External & Unsurveyed Network Devices",
}

ROLE_HIERARCHY_ORDER = {
    "Unknown": -1,
    "Access": 0,
    "Distribution": 1,
    "Router": 2,
    "Core": 3,
}
UPLINK_HIERARCHY_SCORES = {
    "Unknown": -1,
    "Access": 0,
    "Distribution": 1,
    "Router": 2,
    "Core": 3,
}

# --- Basic Utility Functions ---


def get_db_connection(db_path: str = DB_FILE) -> Optional[sqlite3.Connection]:
    if not os.path.exists(db_path):
        print(f"Database file '{db_path}' not found.")
        return None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn
    except sqlite3.Error as e:
        print(f"Error connecting to database {db_path}: {e}")
        return None


def sanitize_node_id_for_pydot(text: str, prefix_if_numeric: str = "id_") -> str:
    if not text:
        return "unknown_node"
    s = str(text)
    s = re.sub(r"[^a-zA-Z0-9_.-]", "_", s)
    if s and s[0].isdigit() and not s.startswith(prefix_if_numeric):
        s = prefix_if_numeric + s
    s = re.sub(r"__+", "_", s)
    s = s.strip("_")
    return s if s else "sanitized_unknown_node"


def is_potentially_mac(text: str) -> bool:
    if not isinstance(text, str):
        return False
    normalized = text.replace(":", "").replace("-", "").replace(".", "").lower()
    return len(normalized) == 12 and all(c in "0123456789abcdef" for c in normalized)


def format_mac_to_standard(mac_like_string: Optional[str]) -> Optional[str]:
    if not mac_like_string:
        return None
    normalized = (
        mac_like_string.replace(":", "").replace("-", "").replace(".", "").upper()
    )
    if len(normalized) == 12 and all(c in "0123456789ABCDEF" for c in normalized):
        return ":".join(normalized[i : i + 2] for i in range(0, 12, 2))
    return None


def shorten_interface_name(if_name: Optional[str]) -> Optional[str]:
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


# --- Lab Area Visualization Constants (NEW & IMPROVED) ---
# A palette of visually distinct, light, and colorblind-safe colors.
# Chosen from established qualitative data visualization palettes (like ColorBrewer Set3).
LAB_AREA_COLORS = [
    "#8dd3c7",  # Mint Green / Teal
    "#ffffb3",  # Pale Yellow
    "#bebada",  # Lavender
    "#fb8072",  # Salmon Red
    "#80b1d3",  # Cornflower Blue
    "#fdb462",  # Light Orange
    "#b3de69",  # Lime Green
    "#fccde5",  # Carnation Pink
    "#d9d9d9",  # Light Grey
    "#bc80bd",  # Orchid Purple
    "#ccebc5",  # Celadon Green
    "#ffed6f",  # Daffodil Yellow
]


def get_color_for_lab_area(lab_area_name: str, color_cache: dict) -> str:
    """
    Assigns a consistent color to a lab area name for the duration of a diagram run.
    Uses a predefined list of colors and cycles through them.

    Args:
        lab_area_name (str): The name of the lab area.
        color_cache (dict): A dictionary to store and retrieve assignments.

    Returns:
        str: The hex color code for the lab area.
    """
    if lab_area_name not in color_cache:
        # Assign the next available color from the palette, cycling if necessary
        next_color_index = len(color_cache) % len(LAB_AREA_COLORS)
        color_cache[lab_area_name] = LAB_AREA_COLORS[next_color_index]
    return color_cache[lab_area_name]


# Helper to determine if a color is "dark" to choose a contrasting font color (white/black)
def is_color_dark(hex_color: str) -> bool:
    """
    Determines if a hex color is dark based on luminance.
    Used to select a contrasting font color (e.g., black or white).
    """
    hex_color = hex_color.lstrip("#")
    # Handle short hex codes
    if len(hex_color) == 3:
        hex_color = "".join([c * 2 for c in hex_color])

    if len(hex_color) != 6:
        return False  # Invalid hex

    rgb = tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    # Standard luminance formula
    luminance = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255
    return luminance < 0.5


if __name__ == "__main__":
    print("Diagram Configuration & Utilities Module (Not meant for direct execution)")
