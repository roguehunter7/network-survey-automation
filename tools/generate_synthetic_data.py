#!/usr/bin/env python3
"""
generate_synthetic_data.py
==========================
Generates a fully synthetic, de-identified dataset for the Network Survey
Automation toolkit. Nothing here is real.

Guarantees:
  * No company name, person name, e-mail, or real hostname is produced.
  * All hostnames use the reserved domain "lab.example.com" (RFC 2606).
  * All MAC addresses use the locally-administered prefix 02:00:00:... so
    they can never collide with a real vendor OUI.
  * All IP addresses come only from reserved blocks:
        RFC 5737 : 192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24
        RFC 2544 : 198.18.0.0/15
        RFC 3849 : 2001:db8::/32
  * Serial numbers are prefixed SYN.
  * Console logs contain only operational "show" output - never a running
    configuration, password, or SNMP community string.

Usage:
    python tools/generate_synthetic_data.py --profile small
    python tools/generate_synthetic_data.py --profile full
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import zlib
from datetime import datetime, timedelta

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = 20240501

# --------------------------------------------------------------------------
# Fabricated universe definition
# --------------------------------------------------------------------------
SITES = {
    "SITE-A": {
        "buildings": {
            "BLD-1": ["Ground Floor", "First Floor", "Second Floor", "Third Floor"],
            "BLD-2": ["Ground Floor", "First Floor"],
        }
    },
    "SITE-B": {
        "buildings": {
            "BLD-1": ["Ground Floor", "First Floor", "Second Floor", "Third Floor", "Fourth Floor", "Fifth Floor"]
        }
    },
    "SITE-C": {
        "buildings": {
            "BLD-1": ["Ground Floor", "First Floor", "Second Floor"],
            "BLD-2": ["Ground Floor"],
        }
    },
    "SITE-D": {
        "buildings": {
            "BLD-1": ["Ground Floor", "First Floor"],
            "BLD-2": ["Ground Floor", "First Floor"],
        }
    },
}

AREA_POOL = [
    "Application Lab", "Automation Lab", "Avionics Lab", "Calibration Lab",
    "Comms Room", "Component Lab", "Control Lab", "Data Centre",
    "Development Lab", "Diagnostics Lab", "Display Lab", "Dynamics Lab",
    "Electronics Lab", "Environmental Lab", "Integration Lab", "Materials Lab",
    "Metrology Lab", "Networking Lab", "Optics Lab", "Power Lab",
    "Prototyping Lab", "Quality Lab", "Reliability Lab", "Robotics Lab",
    "Sensor Lab", "Server Room", "Simulation Lab", "Software Lab",
    "Storage Lab", "Telemetry Lab", "Test Lab", "Thermal Lab",
    "Training Lab", "Validation Lab", "Wireless Lab", "Workshop",
]

WING_POOL = ["North Wing", "South Wing", "East Wing", "West Wing"]

RACK_TYPES = ["Network", "Server", "Wall", "Ceiling", "Floor", "Mini", "Under Floor", "N/A"]

# Fictional model catalogue and a deliberately even vendor split, so the synthetic
# fleet does not fingerprint any real hardware mix.
VENDORS = [
    ("Cisco", 0.34, ["CS-2200-24T", "CS-2200-48T", "CS-3300-24G", "CS-3300-48G", "CS-4400-48X"]),
    ("D-Link", 0.20, ["DXS-1800-28P", "DXS-2800-28X", "DXS-3800-52P"]),
    ("HP", 0.18, ["HP-2600-24G", "HP-2600-48G", "HP-3800-24G"]),
    ("Huawei", 0.15, ["HW-5700-28X", "HW-6700-24T"]),
    ("Aruba", 0.13, ["AR-2900-24G", "AR-2900-48G"]),
]

OTHER_VENDORS = [
    ("D-Link", ["DX-1008", "DX-1016", "DX-1024"]),
    ("TP-Link", ["TP-108", "TP-1016", "TP-1024"]),
    ("NETGEAR", ["NG-308", "NG-116", "NG-726"]),
    ("Cisco", ["CS-110-16", "CS-250-8", "CS-250-08"]),
    ("HP", ["HP-1400-16", "HP-1800-24"]),
    ("Huawei", ["HW-1700-8", "HW-1700-24"]),
    ("Extreme Networks", ["EX-240-24"]),
    ("Aruba", ["AR-1810"]),
]

STATUS_REASONS = [
    ("Unmanaged (No CLI)", 0.55),
    ("Failed Access (Creds Unknown)", 0.15),
    ("Failed Access (No Response)", 0.10),
    ("Failed Access (Port Damaged)", 0.08),
    ("Other (See Notes)", 0.04),
    ("Access Point (Observed)", 0.08),
]

MOONID_STATUS = [
    ("Operational", 0.38), ("Retired", 0.20), ("Being built", 0.27), ("Being retired", 0.15),
]

PROFILES = {
    "small": dict(max_areas=24, sw_per_area=(1, 3), other_per_area=(1, 3), ap_prob=0.30, moonids_per_area=(1, 3)),
    "full": dict(max_areas=52, sw_per_area=(1, 5), other_per_area=(1, 5), ap_prob=0.35, moonids_per_area=(2, 6)),
}


# --------------------------------------------------------------------------
# Small deterministic helpers
# --------------------------------------------------------------------------
def weighted_choice(rng, pairs):
    total = sum(w for _, w in pairs)
    r = rng.random() * total
    upto = 0.0
    for item, w in pairs:
        upto += w
        if r <= upto:
            return item
    return pairs[-1][0]


def sanitize_part(name, placeholder="Unknown"):
    import re as _re
    if name is None or str(name).strip() == "":
        return placeholder
    s = str(name).replace(" ", "_").replace("/", "-").replace("\\", "-").replace(":", "-")
    s = _re.sub(r'[<>*?"|]', "", s)
    s = _re.sub(r"[^\w.\-_]", "", s)
    s = _re.sub(r"[_]+", "_", s)
    s = _re.sub(r"[-]+", "-", s)
    s = s.strip("_-.")
    return s or placeholder


def location_segment(building, floor, wing, area):
    return "{}-{}-{}-{}".format(
        sanitize_part(building, "NoBuilding_Fallback"),
        sanitize_part(floor, "NoFloor_Fallback"),
        sanitize_part(wing, "__NoWing__"),
        sanitize_part(area, "__NoArea__"),
    )


def ip_from_block(idx, block="198.18"):
    """RFC 2544 benchmark space: 198.18.x.y (and 198.19.x.y)."""
    if block == "198.18":
        third = idx // 254
        host = idx % 254 + 1
        return "198.18.{}.{}".format(third % 256, host)
    third = idx // 254
    host = idx % 254 + 1
    return "198.19.{}.{}".format(third % 256, host)


class AddrPool:
    """RFC 5737 documentation addresses for management / external links."""
    BLOCKS = ["192.0.2.", "198.51.100.", "203.0.113."]

    def __init__(self, start=1):
        self.i = start

    def next(self):
        v = self.i
        self.i += 1
        blk = self.BLOCKS[v % 3]
        host = (v // 3) % 251 + 1
        return blk + str(host)


class MacPool:
    """Locally-administered 02:00:00:xx:xx:xx addresses."""
    def __init__(self, start=1):
        self.i = start

    def next(self):
        v = self.i
        self.i += 1
        return "02:00:{:02X}:{:02X}:{:02X}:{:02X}".format(
            (v >> 24) & 0xFF, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF)

    @staticmethod
    def cisco(mac):
        return mac.replace(":", "").lower()


# --------------------------------------------------------------------------
# Universe construction
# --------------------------------------------------------------------------
def build_universe(profile_name):
    prof = PROFILES[profile_name]
    rng = random.Random(SEED)
    areas = []
    used_names = set()
    for site, sdef in SITES.items():
        for building, floors in sdef["buildings"].items():
            for floor in floors:
                n_here = rng.choice([1, 1, 2])
                for k in range(n_here):
                    if len(areas) >= prof["max_areas"]:
                        break
                    name = rng.choice([a for a in AREA_POOL if a not in used_names] or AREA_POOL)
                    used_names.add(name)
                    wing = "Nil" if k == 0 else rng.choice(WING_POOL)
                    areas.append({
                        "site": site, "building": building, "floor": floor,
                        "wing": wing, "lab_area_name": name, "purpose_of_lab": None,
                    })
                if len(areas) >= prof["max_areas"]:
                    break
            if len(areas) >= prof["max_areas"]:
                break
        if len(areas) >= prof["max_areas"]:
            break
    return prof, rng, areas


def gen_moonids(rng, areas, prof):
    moonids = []
    moonid_of_area = {}
    counter = 100001
    for area in areas:
        n = rng.randint(*prof["moonids_per_area"])
        assigned = []
        for _ in range(n):
            idx = len(moonids)
            sid = "MOON{}".format(counter)
            counter += 1
            assigned.append(sid)
            status = weighted_choice(rng, MOONID_STATUS)
            business_group = "GROUP-{:02d}".format(rng.randint(1, 12)) if rng.random() < 0.5 else None
            moonids.append({
                "moonid": sid,
                "site": area["site"],
                "ip_range_definition": "198.{}.{}.0/24".format(18 + (idx % 2), (idx // 2) % 256),
                "purpose": "{}-CORP-{}-{}".format(
                    area["site"], rng.choice(["ENG", "OPS", "LAB", "QA", "IT"]),
                    area["lab_area_name"].replace(" ", "")),
                "business_group": business_group,
                "vlan_id": rng.randint(1, 1001),
                "is_moonid_lab": 0,
                "is_air_gap": 1 if rng.random() < 0.30 else 0,
                "status": status,
                "date_retired": None,
            })
        moonid_of_area[area_key(area)] = assigned
    return moonids, moonid_of_area


def area_key(a):
    return "{}|{}|{}|{}|{}".format(a["site"], a["building"], a["floor"], a["wing"], a["lab_area_name"])


def gen_switches(rng, areas, prof, mgmt_pool, mac_pool):
    switches = []
    seq = 0
    for area in areas:
        for _ in range(rng.randint(*prof["sw_per_area"])):
            seq += 1
            vendor = weighted_choice(rng, [(v, w) for v, w, _ in VENDORS])
            models = next(m for v, w, m in VENDORS if v == vendor)
            model = rng.choice(models)
            ports = 48 if "48" in model else 24
            site_letter = area["site"].split("-")[-1].lower()
            bldg_digit = "".join(ch for ch in area["building"] if ch.isdigit()) or "1"
            hostname = "sw-{}{}-{:03d}".format(site_letter, bldg_digit, seq)
            serial = "SYN{}{:07d}".format(site_letter.upper(), seq)
            base_mac = mac_pool.next()
            switches.append({
                "area": area,
                "serial_number": serial,
                "hostname": hostname,
                "make": vendor,
                "model": model,
                "device_type": "Switch",
                "base_mac_address": base_mac,
                "ports": ports,
                "is_poe_capable": 1 if rng.random() < 0.35 else 0,
                "rack_type_detail": rng.choice(RACK_TYPES),
                "access_level": "Privileged" if rng.random() < 0.9 else "User",
                "location_notes": rng.choice([
                    "Rack {r} unit {u}", "Wall mounted", "Top of rack",
                    "Middle of rack", "Server rack", "Cabinet {c}"])
                    .replace("{r}", str(rng.randint(1, 20))).replace("{u}", str(rng.randint(1, 48)))
                    .replace("{c}", str(rng.randint(1, 9))),
                "mgmt_ip": mgmt_pool.next(),
                "wave2": rng.random() < 0.7,
            })
    return switches


# --------------------------------------------------------------------------
# Console-log synthesis (operational show output only)
# --------------------------------------------------------------------------
def gen_log(sw):
    rng = random.Random(zlib.crc32(sw["serial_number"].encode()))
    macpool = MacPool(rng.randint(1, 900000))
    h = sw["hostname"]
    ports = sw["ports"]
    lines = []
    lines.append("")
    lines.append("{h}#terminal length 0".format(h=h))
    lines.append("{h}#show version".format(h=h))
    lines.append("{} uptime is 12 weeks, 3 days".format(sw["model"]))
    lines.append("System returned to ROM by reload")
    lines.append("System image file is \"flash:/images/{}".format(sw["model"].replace(" ", "_")))
    lines.append("")
    lines.append("{h}#show interfaces status".format(h=h))
    lines.append("Port      Name      Status       Vlan       Duplex  Speed Type")
    vlan_choices = ["1", "10", "20", "30", "trunk"]
    for i in range(1, ports + 1):
        st = "connected" if rng.random() < 0.55 else "notconnect"
        v = rng.choice(vlan_choices)
        lines.append("Gi1/0/{:<3}            {:<12} {:<10} a-full  a-1000 10/100/1000BaseTX".format(i, st, v))
    lines.append("")
    lines.append("{h}#show vlan".format(h=h))
    lines.append("VLAN Name                             Status    Ports")
    lines.append("---- -------------------------------- --------- -------------------------------")
    lines.append("1    default                          active    Gi1/0/1, Gi1/0/2")
    lines.append("10   DATA                             active    Gi1/0/7, Gi1/0/8")
    lines.append("20   VOICE                            active    Gi1/0/9")
    lines.append("")
    lines.append("{h}#show mac address-table count".format(h=h))
    lines.append("Dynamic Address Counts:")
    lines.append("  Total Mac Addresses for this criterion: {}".format(rng.randint(10, 400)))
    lines.append("")
    lines.append("{h}#show ip interface brief".format(h=h))
    lines.append("Interface              IP-Address      OK? Method Status                Protocol")
    lines.append("Vlan1                  {}        YES NVRAM  up                    up".format(sw["mgmt_ip"]))
    lines.append("Vlan10                 198.18.{}.1      YES NVRAM  up                    up".format(rng.randint(0, 60)))
    lines.append("")
    lines.append("{h}#show arp".format(h=h))
    lines.append("Protocol  Address          Age (min)  Hardware Addr   Type   Interface")
    for _ in range(rng.randint(2, 6)):
        lines.append("Internet  198.18.{}.{:<4}    {:>3}     {}  ARPA   Vlan10".format(
            rng.randint(0, 60), rng.randint(10, 250), rng.randint(0, 120), MacPool.cisco(macpool.next())))
    lines.append("")
    lines.append("{h}#show ip route".format(h=h))
    lines.append("Gateway of last resort is {} to network 0.0.0.0".format(sw["mgmt_ip"]))
    lines.append("S*    0.0.0.0/0 [1/0] via {}".format(sw["mgmt_ip"]))
    lines.append("C     198.18.0.0/24 is directly connected, Vlan10")
    lines.append("")
    lines.append("{h}#show cdp neighbors detail".format(h=h))
    lines.append("Device ID: SW-NEIGHBOUR.example.lab")
    lines.append("  IP address: {}".format(sw["mgmt_ip"]))
    lines.append("  Platform: {}, Capabilities: Switch".format(sw["model"]))
    lines.append("  Interface: GigabitEthernet1/0/1, Port ID (outgoing port): GigabitEthernet1/0/24")
    lines.append("")
    lines.append("{h}#show lldp neighbors detail".format(h=h))
    lines.append("Chassis id: 0200.0000.00aa")
    lines.append("System Name: sw-peer.example.lab")
    lines.append("Management Addresses: {}".format(sw["mgmt_ip"]))
    lines.append("")
    lines.append("{h}#".format(h=h))
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Validated-JSON synthesis
# --------------------------------------------------------------------------
def gen_validated(sw, peers, moonids_of_area):
    rng = random.Random(zlib.crc32(sw["serial_number"].encode()) ^ 0x5A5A)
    area = sw["area"]
    ports = sw["ports"]
    macpool = MacPool(rng.randint(1, 900000))
    interfaces = []
    for i in range(1, ports + 1):
        st = "connected" if rng.random() < 0.55 else "notconnect"
        interfaces.append({
            "interface_name": "GigabitEthernet1/0/{}".format(i),
            "status": st,
            "vlan": rng.choice(["1", "10", "20", "30", "trunk (native 10)"]),
            "duplex": "full", "speed": "1000M", "type": "GigabitEthernet",
            "description": "Access port" if rng.random() < 0.5 else "Uplink port",
        })
    vlans = [{"vlan_id": 1, "vlan_name": "default", "status": "active", "ports_associated_text": "Gi1/0/1, Gi1/0/2"}]
    for vid, vname in [(10, "DATA"), (20, "VOICE"), (30, "MGMT")][: rng.randint(1, 3)]:
        vlans.append({"vlan_id": vid, "vlan_name": vname, "status": "active",
                      "ports_associated_text": ", ".join("Gi1/0/{}".format(n) for n in sorted(rng.sample(range(1, ports + 1), min(8, ports))))})
    ip_interfaces = [{
        "interface_name": "Vlan10",
        "mac_address": sw["base_mac_address"],
        "ip_address_with_prefix": sw["mgmt_ip"] + "/24",
        "status": "up", "protocol_status": "up", "is_management": 1,
    }]
    mac_entries = []
    for _ in range(rng.randint(15, 90)):
        mac_entries.append({
            "mac_address": macpool.next(),
            "interface_name": "Gi1/0/{}".format(rng.randint(1, ports)),
            "vlan_id": rng.choice([1, 10, 20, 30]),
            "type": "DYNAMIC",
        })
    arp_entries = []
    for _ in range(rng.randint(2, 12)):
        arp_entries.append({
            "ip_address": "198.{}.{}.{}".format(18 + rng.randint(0, 1), rng.randint(0, 80), rng.randint(10, 250)),
            "mac_address": macpool.next(),
            "interface_name": "Vlan10",
            "vlan_id": 10, "type": "ARPA", "age_in_seconds": rng.randint(0, 14400),
        })
    routes = [
        {"ip_version": "4", "destination_prefix": "0.0.0.0/0", "next_hop_ip": "203.0.113.1",
         "outgoing_interface": "Vlan10", "metric": 0, "protocol": "Static", "is_default_route": 1},
        {"ip_version": "4", "destination_prefix": "198.18.0.0/16", "next_hop_ip": None,
         "outgoing_interface": "Vlan10", "metric": 0, "protocol": "Connected", "is_default_route": 0},
    ]
    neighbors = []
    for p in rng.sample(peers, min(len(peers), rng.randint(1, 3))) if peers else []:
        neighbors.append({
            "local_interface_name": "GigabitEthernet1/0/1",
            "protocol_used": rng.choice(["LLDP", "CDP"]),
            "remote_device_id": p["base_mac_address"].replace(":", "").lower(),
            "remote_interface_name": "GigabitEthernet1/0/24",
            "remote_system_name": "{}.lab.example.com".format(p["hostname"]),
            "remote_mgmt_address": p["mgmt_ip"],
            "remote_model": p["model"],
        })
    associations = [{"moonid": s, "resolution_method": "SVI_IP_Match", "confidence_score": round(rng.uniform(0.6, 0.99), 2)}
                    for s in moonids_of_area[: rng.randint(0, 2)]]
    discovered = [{"network_prefix": "198.{}.{}.0/24".format(18 + rng.randint(0, 1), rng.randint(0, 200)),
                   "discovery_source_type": rng.choice(["SVI_Unmatched", "ARP_Unmatched_IP", "Route_Unmatched_Destination"]),
                   "discovery_context": "Synthetic discovery event"}]
    items = [{"severity": "Low", "item_path": "switch_details.location_notes",
              "reason": "Synthetic_Review_Item",
              "details": "This is fabricated review content used for demonstration."}]

    return {
        "switch_details": {
            "serial_number": sw["serial_number"],
            "hostname": sw["hostname"],
            "model": sw["model"],
            "make": sw["make"],
            "device_type": "Switch",
            "base_mac_address": sw["base_mac_address"],
            "lab_area_name": area["lab_area_name"],
            "floor": area["floor"],
            "site": area["site"],
            "building": area["building"],
            "location_notes": sw["location_notes"],
            "rack_type_detail": sw["rack_type_detail"],
            "access_level": sw["access_level"],
            "survey_timestamp": (datetime(2025, 1, 1) + timedelta(days=rng.randint(0, 150))).isoformat(),
            "log_filename_validated": "{}-WAVE1.txt".format(sw["serial_number"]),
            "ip_version_routing": "ipv4",
            "running_config_captured": 0,
            "is_poe_capable": sw["is_poe_capable"],
            "handles_internal_vlans": 1,
            "user_verified_total_ports": ports,
            "user_verified_used_ports": rng.randint(1, ports),
        },
        "interfaces": interfaces,
        "vlans": vlans,
        "ip_interfaces": ip_interfaces,
        "mac_entries": mac_entries,
        "arp_entries": arp_entries,
        "routes": routes,
        "moonid_associations": associations,
        "discovered_unassigned_networks": discovered,
        "neighbors": neighbors,
        "items_for_review": items,
    }


def gen_other_devices(rng, area, moonid_of_area, mac_pool):
    entries = []
    n = rng.randint(1, 3)
    for i in range(n):
        reason = weighted_choice(rng, [(r, w) for r, w in STATUS_REASONS])
        if reason == "Access Point (Observed)":
            make, model = rng.choice([("Aruba", "AP-515"), ("Cisco", "C9120AXI"), ("Ubiquiti", "U6-Pro")])
            ssid = rng.choice(["CORP-WIFI", "LAB-WIFI", "GUEST-WIFI", "IOT-WIFI"])
            mac = mac_pool.next()
            entries.append({
                "Timestamp": "2025-06-{:02d} {:02d}:{:02d}:00".format(rng.randint(1, 28), rng.randint(8, 18), rng.randint(0, 59)),
                "StatusReason": reason, "Site": area["site"], "Building": area["building"],
                "Floor": area["floor"], "Wing": area["wing"], "AreaName": area["lab_area_name"],
                "SpecificLocationNotes": "Ceiling mount", "RackTypeDetail": "Ceiling",
                "ReportedMake": make, "ReportedModel": model,
                "ReportedSerialNumber": "SYNAP{:06d}".format(rng.randint(1, 999999)),
                "ReportedAssetTag": "Unknown",
                "ReportedMOONID": moonid_of_area[0] if moonid_of_area else None,
                "ObservedLaptopIP": None, "FailureReason": "N/A",
                "ObservedSSID": ssid, "MACAddress": mac,
                "ReportedTotalPorts": "0", "ReportedUsedPorts": "0",
            })
        else:
            make, models = rng.choice(OTHER_VENDORS)
            model = rng.choice(models)
            total = rng.choice(["5", "8", "16", "24", "48"])
            used = str(rng.randint(1, int(total)))
            entries.append({
                "Timestamp": "2025-06-{:02d} {:02d}:{:02d}:00".format(rng.randint(1, 28), rng.randint(8, 18), rng.randint(0, 59)),
                "StatusReason": reason, "Site": area["site"], "Building": area["building"],
                "Floor": area["floor"], "Wing": area["wing"], "AreaName": area["lab_area_name"],
                "SpecificLocationNotes": rng.choice(["Under desk", "Wall mounted", "Rack", "On shelf"]),
                "RackTypeDetail": rng.choice(RACK_TYPES),
                "ReportedMake": make, "ReportedModel": model,
                "ReportedSerialNumber": "SYNOD{:06d}".format(rng.randint(1, 999999)),
                "ReportedAssetTag": "Unknown",
                "ReportedMOONID": rng.choice(moonid_of_area) if moonid_of_area else None,
                "ObservedLaptopIP": "198.18.{}.{}".format(rng.randint(0, 80), rng.randint(10, 250)),
                "FailureReason": "N/A", "ObservedSSID": "", "MACAddress": "",
                "ReportedTotalPorts": total, "ReportedUsedPorts": used,
            })
    return entries


# --------------------------------------------------------------------------
# Writers
# --------------------------------------------------------------------------
def reset_dir(path):
    if os.path.isdir(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=list(PROFILES), default="small")
    args = ap.parse_args()

    prof, rng, areas = build_universe(args.profile)
    moonids, moonid_of_area = gen_moonids(rng, areas, prof)
    mgmt_pool = AddrPool()
    mac_pool = MacPool()
    switches = gen_switches(rng, areas, prof, mgmt_pool, mac_pool)

    by_area = {}
    for s in switches:
        by_area.setdefault(area_key(s["area"]), []).append(s)

    # ----- reference data -------------------------------------------------
    data_dir = os.path.join(REPO_ROOT, "data")
    os.makedirs(data_dir, exist_ok=True)
    write_json(os.path.join(data_dir, "lab_areas_data.json"), areas)
    write_json(os.path.join(data_dir, "moonid_areas_data.json"), moonids)
    for site in SITES:
        write_json(os.path.join(data_dir, "{}_moonids.json".format(site)),
                   [s for s in moonids if s["site"] == site])

    # ----- survey outputs -------------------------------------------------
    out_dir = os.path.join(REPO_ROOT, "survey_outputs")
    reset_dir(os.path.join(out_dir, "metadata"))
    reset_dir(os.path.join(out_dir, "logs"))
    reset_dir(os.path.join(out_dir, "other_device_logs"))
    packages_root = os.path.join(REPO_ROOT, "organized_llm_input_packages")
    validated_root = os.path.join(REPO_ROOT, "validated_jsons_api_structured_MAC_CHUNKED_MP")

    timestamp = datetime(2025, 6, 1, 9, 0, 0)
    for sw in switches:
        area = sw["area"]
        seg = location_segment(area["building"], area["floor"], area["wing"], area["lab_area_name"])
        base = os.path.join(area["site"], seg)
        meta = {
            "helper_script_version": "3.0.1",
            "metadata_capture_timestamp": (timestamp + timedelta(minutes=len(sw["serial_number"]))).isoformat(),
            "access_level": sw["access_level"],
            "device_type": "Switch",
            "final_hostname": sw["hostname"],
            "final_serial_number": sw["serial_number"],
            "final_make": sw["make"],
            "final_model": sw["model"],
            "is_poe_capable": sw["is_poe_capable"],
            "final_rack_type_detail": sw["rack_type_detail"],
            "final_site": area["site"],
            "final_building": area["building"],
            "final_floor": area["floor"],
            "final_wing": area["wing"],
            "final_area_name": area["lab_area_name"],
            "final_location_notes": sw["location_notes"],
        }
        write_json(os.path.join(out_dir, "metadata", base, "{}-WAVE1.meta.json".format(sw["serial_number"])), meta)
        write_text(os.path.join(out_dir, "logs", base, "{}-WAVE1.txt".format(sw["serial_number"])), gen_log(sw))

        peers = [p for p in by_area.get(area_key(area), []) if p["serial_number"] != sw["serial_number"]]
        peers += rng.sample(switches, min(2, len(switches)))
        val = gen_validated(sw, peers, moonid_of_area.get(area_key(area), []))
        write_json(os.path.join(validated_root, base, "{}_validated.json".format(sw["serial_number"])), val)

        # LLM input package (metadata + log + site MOONID data)
        pkg_dir = os.path.join(packages_root, area["site"], seg, "LLM_Input_Packages")
        os.makedirs(pkg_dir, exist_ok=True)
        site_moonids = [s for s in moonids if s["site"] == area["site"]]
        with open(os.path.join(pkg_dir, "{}_llm_input_package.txt".format(sw["serial_number"])), "w", encoding="utf-8") as fh:
            fh.write("%%%START_LLM_PROMPT_STRUCTURED_OUTPUT_V1%%%\n")
            fh.write("SYNTHETIC DEMO PACKAGE - fabricated data for the public showcase build.\n")
            fh.write("%%%END_LLM_PROMPT_STRUCTURED_OUTPUT_V1%%%\n")
            fh.write("%%%START_META_JSON_CONTENT%%%\n")
            fh.write(json.dumps(meta, indent=2))
            fh.write("\n%%%END_META_JSON_CONTENT%%%\n")
            fh.write("%%%START_FULL_WAVE1_LOG_CONTENT%%%\n")
            fh.write(gen_log(sw))
            fh.write("%%%END_FULL_WAVE1_LOG_CONTENT%%%\n")
            fh.write("%%%START_SITE_SPECIFIC_MOONID_DATA%%%\n")
            fh.write(json.dumps(site_moonids, indent=2))
            fh.write("\n%%%END_SITE_SPECIFIC_MOONID_DATA%%%\n")

    # ----- other device logs (APs + unmanaged) ----------------------------
    for area in areas:
        entries = gen_other_devices(rng, area, moonid_of_area.get(area_key(area), []), mac_pool)
        fname = "{}_{}_{}_{}_other_devices.json".format(
            sanitize_part(area["site"]), sanitize_part(area["building"]),
            sanitize_part(area["floor"]), sanitize_part(area["lab_area_name"]))
        write_json(os.path.join(out_dir, "other_device_logs", fname), entries)

    # ----- summary --------------------------------------------------------
    print("Synthetic dataset generated (profile='{}')".format(args.profile))
    print("  lab areas          : {}".format(len(areas)))
    print("  MOONIDs             : {}".format(len(moonids)))
    print("  managed switches   : {}".format(len(switches)))
    print("  validated JSONs    : {}".format(len(switches)))
    print("  console logs       : {}".format(len(switches)))
    print("  LLM input packages : {}".format(len(switches)))
    print("  other-device files : {}".format(len(areas)))


if __name__ == "__main__":
    main()
