# Traceability - original repository to clean build

This is the comparison instrument requested at the end of the cleanup: every artefact
that existed in the working repository, and where it lives (or why it does not) in the
public build.

Legend:

- **Ported** - same file, behaviour preserved.
- **Renamed / de-branded** - same code, name or contents generalised for publication.
- **Archived** - moved to legacy/ as historical evidence (no longer on the critical path).
- **Regenerated** - real data replaced by output of tools/generate_synthetic_data.py.
- **Dropped** - intentionally not carried over, with a reason.

## 1. Application and GUI

| Original | Disposition | Notes |
| --- | --- | --- |
| main_app.py | Ported | GUI entry point. |
| config.py | Ported | Path constants; unchanged apart from generic data filenames. |
| data_manager.py | Ported | Reference data + hierarchical metadata handling. |
| ui_components.py | Ported | All widget builders and handlers. |
| utils.py | Ported | Folder naming and dialog helpers. |

## 2. Database and setup

| Original | Disposition | Notes |
| --- | --- | --- |
| create_db.py | Ported | Schema v2.16.0; internal network-segment identifier -> MOONID, internal business-group field -> business_group. |
| create_log_folders.py | Ported | Creates the standard log tree. |
| dbml.txt | Ported | Schema documentation; terminology generalised. |

## 3. LLM pipeline

| Original | Disposition | Notes |
| --- | --- | --- |
| unified_processor.py | Ported | Orchestration, batching, path resolution. |
| gemini.py | Ported / de-branded | API key moved to GEMINI_API_KEY env var. |
| phase3_review_tool.py | Renamed | Now phase3_review_tool_auto_batch.py to match its own header and docs. |
| llm_prompt_stage1a.txt | Ported | Example IPs moved to documentation ranges. |
| llm_prompt_stage1b.txt | Ported | Same. |
| llm_prompt_stage2_mac.txt | Ported | Same. |
| llm_prompt_structured_output_v1.txt | Ported | Same. |

## 4. Ingestion

| Original | Disposition | Notes |
| --- | --- | --- |
| load_validated_json_to_db.py | Ported | Recursive loader; column names generalised. |
| load_other_devices_json_to_db.py | Ported | Unmanaged devices and APs. |

## 5. Topology and diagramming

| Original | Disposition | Notes |
| --- | --- | --- |
| network_diagram_generator.py | Ported | Plus a layout fallback and pydot-v4 compatibility fix. |
| diagram_config_utils.py | Ported | Thresholds and styling. |
| diagram_graph_builder.py | Ported | Graph construction and AP/link resolution. |
| diagram_inference_engine.py | Ported | Role inference, MAC inference, MOONID propagation triggers. |
| (original propagation module) | Renamed | Now infer_moonids_from_topology.py. |

## 6. Reporting

| Original | Disposition | Notes |
| --- | --- | --- |
| export_lab_area_to_excel.py | Archived | Truncated and non-parseable in the original repo (unterminated SQL string, no main()). Archived as legacy/export_lab_area_to_excel.TRUNCATED.py; superseded by export_all_devices_by_site.py. |
| export_all_devices_by_site.py | Ported | Same. |
| exportpivottable.py | Ported | Standard/non-standard classification export. |
| exportcjexcel.py | Ported | Scoped audit report. |
| exportswitchcountcons.py | Ported | Consolidated switch counts. |
| extract_unassigned_networks.py | Ported | Runs in the demo; emits campus_id header. |
| vendor_report.py | Ported | Vendor mix report. |
| generate_vendor_summary_from_raw_files.py | Ported | Vendor summary from metadata/logs. |

## 7. Legacy and prototypes (now in legacy/)

| Original | Disposition | Notes |
| --- | --- | --- |
| new.py | Archived | First serial collector prototype. |
| new1.py | Archived | Second prototype, threaded. |
| organize_data.py | Archived | Superseded package builder. |
| dist/extract_macs.py | Archived | TextFSM MAC parser experiment. |
| dist/extract_arps.py | Archived | ARP parser experiment. |
| new1.spec | Archived / de-branded | Local Python path removed. |
| build1.bat | Archived | Prototype build script. |
| 1zip.bat | Archived | Output bundling helper. |
| diagrams/render_mermaid.py | Moved | Now tools/render_mermaid.py (generic utility). |
| build.bat | Ported | PyInstaller build for main_app.py. |
| main_app.spec | Ported | Packaging spec. |

## 8. Reference data and generated artefacts

| Original | Disposition | Notes |
| --- | --- | --- |
| data/lab_areas_data.json | Regenerated | Synthetic campuses, buildings, areas. |
| (original reference dataset) | Regenerated | Now data/moonid_areas_data.json. |
| (original per-site reference files) | Regenerated | Now <SITE>_moonids.json. |
| survey_outputs/ (43 MB) | Regenerated | Synthetic metadata, logs, other-device files. |
| organized_llm_input_packages/ (138 MB) | Regenerated | Synthetic LLM packages. |
| validated_jsons_api_structured_MAC_CHUNKED_MP/ (36 MB) | Regenerated | Synthetic validated JSON. |
| network_diagrams_pydot_final/ (27 MB) | Regenerated | 43 synthetic diagrams + uplink JSON. |
| network_survey.db (27 MB) | Regenerated | Built from synthetic data by the real loaders. |
| unassigned_networks_*.csv | Regenerated | Synthetic report output. |
| dist/survey_outputs/, dist/network_survey.db | Dropped | Stale duplicate output trees. |

## 9. Reports and binaries not reproduced

| Original | Disposition | Notes |
| --- | --- | --- |
| managed_switches_report.xlsx | Not reproduced | Contained production inventory; regenerate with exportpivottable.py against synthetic data. |
| other_devices_with_sn_report.xlsx | Not reproduced | Same. |
| Report-Lab-...xlsx | Not reproduced | Same. |
| dist/main_app.exe, dist/new1.exe | Dropped | Build artefacts; reproducible from the specs. |
| sync.ffs_db (x2) | Dropped | FreeFileSync metadata, no value. |
| diagrams/firewallroom.png/svg/mmd, 2ndfloorserverroom.mmd | Dropped | Contained real hostnames/MACs; the generic render_mermaid.py utility is retained instead. |

## 10. Coverage summary

- Python modules in the original working tree: 28. Represented: 28 (24 ported/renamed on
  the critical path, 4 archived in legacy/ - three prototypes plus one file that was
  already truncated in the original repository).
- Additional Python experiments found under dist/: 2. Both archived in legacy/.
- Prompt files: 4. All ported.
- Build/packaging scripts: 4. 2 ported, 2 archived.
- Data trees and the database: all regenerated as synthetic.
- Real-world reports and exes: intentionally not reproduced (noted above).

Every original source file is therefore either on the critical path, archived with an
explanation, or explicitly dropped with a stated reason.

## 11. Package refactor mapping (flat layout -> netsurvey package)

The original working tree placed every module at the repository root. The public build
groups them into a package. Only import statements and the two path assumptions changed;
behaviour is otherwise preserved and revalidated end to end.

| Original flat module | New location |
| --- | --- |
| config.py, utils.py | netsurvey/config.py, netsurvey/utils.py |
| main_app.py, data_manager.py, ui_components.py | netsurvey/gui/ |
| create_db.py, create_log_folders.py, load_*.py | netsurvey/db/ |
| unified_processor.py, gemini.py, phase3_review_tool_auto_batch.py | netsurvey/llm/ |
| llm_prompt_*.txt | netsurvey/llm/prompts/ |
| network_diagram_generator.py, diagram_*.py, infer_moonids_from_topology.py | netsurvey/topology/ |
| export*.py, vendor_report.py, extract_unassigned_networks.py, generate_vendor_summary_from_raw_files.py | netsurvey/reporting/ |
| dbml.txt | docs/dbml.txt |
| main_app.py | root main_app.py (thin launcher) |

Commands changed accordingly, for example:

    python create_db.py            ->  python -m netsurvey.db.create_db
    python main_app.py             ->  python main_app.py   (or python -m netsurvey.gui.main_app)
