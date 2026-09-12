# Architecture

This document describes how the toolkit is put together. The public build is driven
entirely by synthetic data, but the code paths are the same ones used in production.

## 1. Pipeline phases

    Phase 0  Foundation      data/*.json reference data, create_db.py schema, create_log_folders.py
    Phase 1  Field capture   main_app.py GUI -> survey_outputs/metadata + survey_outputs/logs
    Phase 2  LLM extraction  unified_processor.py + gemini.py -> validated_jsons.../*_validated.json
    Phase 3  Human review    phase3_review_tool_auto_batch.py -> *_reviewed.json
    Phase 4  Ingestion       load_validated_json_to_db.py + load_other_devices_json_to_db.py
    Phase 5  Topology        network_diagram_generator.py + diagram_*.py -> diagrams + uplink JSON
    Phase 6  Reporting       export_*.py, vendor_report.py, extract_unassigned_networks.py

## 2. Data contracts

**Metadata** (survey_outputs/metadata/SITE/LOCATION/SN-WAVE1.meta.json) records what the
surveyor captured: hostname, serial, make, model, PoE, rack type, location, access level.

**Console log** (survey_outputs/logs/SITE/LOCATION/SN-WAVE1.txt) is the raw CLI session.
The folder layout is created ahead of time by create_log_folders.py so that the backend
can find every log deterministically.

**Validated JSON** is the LLM output validated against the Pydantic models in gemini.py:

    switch_details, interfaces, vlans, ip_interfaces, mac_entries,
    arp_entries, routes, moonid_associations, discovered_unassigned_networks,
    neighbors, items_for_review

## 2b. Vocabulary

- **MOONID** (Managed Operations Network ID) - the de-branded, synthetic name for the
  internal network-segment identifier. It is the join key between a device and the user
  network it serves (mapped from IP range and VLAN) and is propagated top-down during
  topology analysis. All MOONIDs in this build are fabricated.
- **business_group** - the business unit/division that owns a network segment; generic
  synthetic values only.
- **campus_id** - the campus identifier for a device or network. A campus contains
  multiple buildings.

## 2c. Package layout

    netsurvey/
      config.py, utils.py          shared configuration and helpers
      gui/                         Tkinter survey application
      db/                          schema, log folders, JSON loaders
      llm/                         staged Gemini pipeline + prompts/
      topology/                    graph build, inference, diagram output
      reporting/                   Excel / CSV exports

Entry points are run as modules from the repository root, for example
python -m netsurvey.db.create_db. The root main_app.py is a thin launcher kept for
PyInstaller and for the familiar python main_app.py command.

## 3. Database

SQLite, schema v2.16.0, defined in create_db.py and documented in dbml.txt. Sixteen
tables cover reference data (lab_areas, moonid_areas), device inventory (switches,
logged_other_devices, logged_access_points), and operational detail (interfaces, vlans,
ip_interfaces, mac_address_table, arp_table, lldp_cdp_neighbors, ip_routing_table,
discovered_unassigned_networks, switch_moonid_map).

Foreign keys tie every device to a lab area and cascade cleaning when a switch is
reloaded.

## 4. Topology inference

network_diagram_generator.py orchestrates four cooperating modules:

- **diagram_config_utils.py** - paths, styling, inference thresholds.
- **diagram_graph_builder.py** - builds a NetworkX graph from the database. Resolves and
  de-duplicates external LLDP/CDP neighbours using a prioritised multi-identifier cache.
  Links access points by exact MAC match, then by a systematic last-octet variation.
- **diagram_inference_engine.py** - iteratively infers switch-to-switch links from shared
  MAC tables (hierarchical pass, then a relaxed bridging pass for isolated islands) and
  classifies roles using degree, betweenness centrality and distance to the Floor Access
  Switch.
- **infer_moonids_from_topology.py** - propagates MOONIDs top-down from the FAS and other
  anchored switches, assigning user subnets to downstream devices.

Outputs are a Pydot PNG per scope plus an _uplinks.json sidecar containing each switch's
inferred uplink and an is_isolated_from_fas flag.

## 5. Regenerating the synthetic dataset

tools/generate_synthetic_data.py is the single source of truth for the demo data. It is
seeded, standard-library only, and deterministic:

    python tools/generate_synthetic_data.py --profile small
    python tools/generate_synthetic_data.py --profile full

Everything it writes is fabricated under the rules described in the README (RFC 5737 /
RFC 2544 addresses, lab.example.com hostnames, 02:00:00 MAC prefix, SYN serials, no
running configuration in logs).

tools/generate_demo_diagrams.py wraps the interactive diagram generator so the whole
demo can be rebuilt non-interactively.

## 6. Extending

- Add a parser stage: extend the Pydantic models in gemini.py and the prompt files, then
  add the loader in load_validated_json_to_db.py.
- Add a report: query network_survey.db and write via pandas/openpyxl.
- Add a vendor: extend the synthetic generator's VENDORS table and, if the CLI grammar
  differs, the prompt examples.
