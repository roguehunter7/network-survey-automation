#!/usr/bin/env python3
"""
generate_demo_diagrams.py
=========================
Batch-generates a topology diagram for every lab area (and every floor in
"ALL Areas" mode) found in the synthetic database. Non-interactive wrapper
around network_diagram_generator.generate_network_diagram_for_lab_area.
"""
import os
import sqlite3
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

from netsurvey.topology.diagram_config_utils import DB_FILE, get_db_connection  # noqa: E402
from netsurvey.topology.diagram_graph_builder import ALL_AREAS_MARKER  # noqa: E402
from netsurvey.topology.network_diagram_generator import generate_network_diagram_for_lab_area  # noqa: E402


def main():
    if not os.path.exists(DB_FILE):
        sys.exit("Database not found. Run the loaders first (see README).")
    con = get_db_connection(DB_FILE)
    if con is None:
        sys.exit("Could not open the database.")
    cur = con.cursor()
    rows = cur.execute(
        "SELECT DISTINCT site, building, floor, lab_area_name "
        "FROM switches ORDER BY site, building, floor, lab_area_name"
    ).fetchall()

    for site, bldg, floor, area in rows:
        try:
            generate_network_diagram_for_lab_area(
                con, site, bldg, floor, area,
                filter_diagram_main=True,
                include_unmanaged_devices_in_hybrid_mode=True,
            )
        except Exception as exc:  # keep going on a single failure
            print("FAILED {} {} {} {}: {}".format(site, bldg, floor, area, exc))

    seen = set()
    for site, bldg, floor, _ in rows:
        key = (site, bldg, floor)
        if key in seen:
            continue
        seen.add(key)
        try:
            generate_network_diagram_for_lab_area(
                con, site, bldg, floor, ALL_AREAS_MARKER,
                filter_diagram_main=True,
                include_unmanaged_devices_in_hybrid_mode=True,
            )
        except Exception as exc:
            print("FAILED ALL_AREAS {}: {}".format(key, exc))

    con.close()
    print("Done. Diagrams written to the configured output directory.")


if __name__ == "__main__":
    main()
