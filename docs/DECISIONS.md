# Decision Log

This project was built incrementally over several months while the requirements were
still being discovered. That is normal for a first-of-its-kind survey tool, but it means
the code grew in layers rather than from one clean design. This log reconstructs the
significant decisions from the evidence in the repository (code, prompts, schema,
legacy files and commit history).

Each entry follows a light ADR shape: Context, Decision, Consequences, Evidence.

---

## ADR-001 - Guide field capture with a desktop GUI

**Context.** Survey metadata was being recorded by different people in different ways,
which made downstream matching and reconciliation slow.

**Decision.** Build a Tkinter application that walks the surveyor through location,
device and wave selection and validates input before saving.

**Consequences.** Consistent, machine-readable metadata and far less rework. The cost is
a GUI dependency (Tk), packaging, and a form that must track the data model.

**Evidence.** netsurvey/gui/main_app.py, netsurvey/gui/ui_components.py,
netsurvey/gui/data_manager.py.

---

## ADR-002 - Deterministic log-folder convention

**Context.** Hundreds of console logs needed to be matched back to the right device with
no central index and no chance to enforce a naming scheme by hand.

**Decision.** Pre-create one folder per location using the segment
<building>-<floor>-<wing>-<area>, with __NoWing__ and __NoArea__ placeholders, and make
the GUI tell each surveyor the exact path to save into.

**Consequences.** The backend can find every log from metadata alone. The naming logic
must stay identical across the GUI, the folder creator and the processor - a coupling
that later caused edge-case bugs.

**Evidence.** netsurvey/db/create_log_folders.py,
netsurvey/utils.py (format_location_log_folder_segment),
netsurvey/llm/unified_processor.py (get_target_paths_for_switch).

---

## ADR-003 - Capture the survey in two waves

**Context.** Some information (serial, model, location) is cheap to capture at the desk;
the full CLI transcript needs a console cable and may be deferred.

**Decision.** Split capture into Wave 1 (metadata) and Wave 2 (CLI logs), with a
completion tracker so the team could see what remained.

**Consequences.** The survey could be paused and resumed, and progress was visible. It
also meant records could be incomplete, which every later stage had to tolerate.

**Evidence.** *-WAVE1.meta.json, *-WAVE1.txt / *-WAVE2.txt, wave2_completion_status.json,
data_manager Wave 2 methods.

---

## ADR-004 - Use SQLite as the warehouse

**Context.** The analysis needed joins across devices, interfaces, MAC tables, ARP,
routes and neighbours, which spreadsheets could not express safely.

**Decision.** A single-file SQLite database with a normalised 16-table schema, foreign
keys, cascade deletes and purposeful indexes.

**Consequences.** Portable, zero-administration, and fast enough for local analysis. It is
effectively single-writer, which is fine for a periodic batch load.

**Evidence.** netsurvey/db/create_db.py, docs/dbml.txt (schema v2.16.0).

---

## ADR-005 - Parse logs with an LLM instead of TextFSM templates

**Context.** The estate is multi-vendor (Cisco, HP, D-Link, Huawei, Aruba) and even
same-vendor devices were captured with different commands.

**Decision.** Use a large language model to extract structured data, rather than maintain
per-vendor regular expressions or TextFSM templates.

**Consequences.** Far better coverage of messy, real logs. The trade-off is
non-determinism, API cost, and the need for validation and review.

**Evidence.** legacy/extract_macs.py and legacy/extract_arps.py (abandoned TextFSM
experiments), netsurvey/llm/gemini.py.

---

## ADR-006 - Split extraction into three stages

**Context.** A single mega-prompt over a full CLI dump was unreliable and exceeded
practical context limits, especially for MAC tables with hundreds of rows.

**Decision.** Stage 1A (simpler fields), Stage 1B (MOONID association), Stage 2 (MAC
table, chunked into batches).

**Consequences.** Each stage has a smaller, testable contract and its own retry; total
API calls increase. MAC chunking (target 100 rows, cap 50 iterations) keeps each request
bounded.

**Evidence.** netsurvey/llm/prompts/llm_prompt_stage1a.txt, stage1b.txt, stage2_mac.txt;
gemini.py constants MAC_BATCH_TARGET_SIZE, MAX_MAC_BATCH_ITERATIONS.

---

## ADR-007 - Validate every model response with Pydantic

**Context.** An LLM will occasionally return plausible-looking output with the wrong
shape; a bad row must never reach the database silently.

**Decision.** Define the full output contract as Pydantic v2 models and validate each
stage before it is accepted.

**Consequences.** Malformed output fails loudly and can be retried or reviewed. The
schema must be kept in step with the prompts.

**Evidence.** 14 Pydantic models in netsurvey/llm/gemini.py (plus RootModel for MAC
lists), ValidationError handling.

---

## ADR-008 - Turn model uncertainty into a human work queue

**Context.** The model is right far more often than a regex, but not always, and a wrong
port or subnet has real consequences.

**Decision.** Require the model to emit items_for_review entries with a severity, and
provide a batch review tool that walks them.

**Consequences.** Review is targeted rather than exhaustive, and quality has a clear
owner. It adds a manual phase to the pipeline.

**Evidence.** ItemForReview model, netsurvey/llm/phase3_review_tool_auto_batch.py.

---

## ADR-009 - Batch with a small process pool

**Context.** Hundreds of devices had to be processed, but the API has rate limits and the
free/standard tiers punish bursts.

**Decision.** Use ProcessPoolExecutor with a deliberately low worker count and a small
pre-submission delay, with one retry per device.

**Consequences.** Throughput is bounded but predictable, and one bad device does not sink
the batch. A higher worker count would be faster on paid tiers.

**Evidence.** netsurvey/llm/unified_processor.py (MAX_WORKERS_FOR_POOL,
PRE_SUBMISSION_DELAY_SECONDS, retry logic).

---

## ADR-010 - Infer topology from partial discovery data

**Context.** The survey could not see every link. Some switches sit behind unmanaged
hops, and many external devices never give a hostname.

**Decision.** Reconstruct the topology heuristically: infer switch roles from graph
centrality, infer switch-to-switch links from shared MAC tables (Jaccard similarity), and
link access points by exact MAC match with a systematic last-octet variation fallback.

**Consequences.** Usable diagrams and uplink reports from imperfect data. Heuristics are
tunable and can be wrong, so thresholds are centralised.

**Evidence.** netsurvey/topology/diagram_inference_engine.py,
netsurvey/topology/diagram_graph_builder.py,
netsurvey/topology/diagram_config_utils.py.

---

## ADR-011 - Anchor analysis on the Floor Access Switch (FAS)

**Context.** Without an anchor, role classification and subnet propagation are ambiguous
at the edges of a scope.

**Decision.** Let the surveyor supply the FAS serial number; use it to measure distance,
steer role inference, and seed MOONID propagation top-down.

**Consequences.** Much more accurate local analysis. It depends on the surveyor knowing
the FAS, and diagrams degrade gracefully when it is not supplied.

**Evidence.** infer_switch_roles (FAS-aware branch),
netsurvey/topology/infer_moonids_from_topology.py.

---

## ADR-012 - De-duplicate external neighbours across identifier forms

**Context.** The same external device appears as a system name in one log, a MAC in
another and a management IP in a third, producing phantom nodes.

**Decision.** Resolve and cache neighbours on a prioritised set of identifiers (system
name + management IP, system name, normalised MAC, management IP, raw id).

**Consequences.** Cleaner diagrams and correct edge counts. The cache is per run, so
cross-run identity is still approximate.

**Evidence.** resolve_lldp_cdp_remote_node in netsurvey/topology/diagram_graph_builder.py.

---

## ADR-013 - Render diagrams with Graphviz/Pydot, clustered by role

**Context.** A static export needed to be readable by non-engineers and produced
repeatedly for many scopes.

**Decision.** Generate Pydot graphs clustered by inferred role, with legends, colours by
lab area, and an accompanying uplink JSON sidecar.

**Consequences.** Repeatable, scriptable diagrams and a machine-readable sidecar for
reporting. Layout quality depends on Graphviz, and large graphs need tuning.

**Evidence.** netsurvey/topology/network_diagram_generator.py,
network_diagrams_pydot_final/ (diagrams + *_uplinks.json).

---

## ADR-014 - Keep a separate human-reviewed JSON stage

**Context.** Review changes to validated data were being lost when the LLM re-ran.

**Decision.** Keep validated output and reviewed output as distinct artefacts, so the
reviewed version is the one loaded.

**Consequences.** A clear provenance chain and safe re-runs. It adds a directory and a
tool to the workflow.

**Evidence.** *_validated.json vs *_reviewed.json, phase3_review_tool_auto_batch.py.

---

## ADR-015 - Sanitise the project for public release

**Context.** The original data included employer identifiers, internal IP ranges,
production hostnames, captured device credentials and a hard-coded API key.

**Decision.** Build a synthetic data generator, move the API key to an environment
variable, use only reserved IP ranges and reserved domains, replace internal terminology,
and archive the real data outside the repository.

**Consequences.** The work can be shown publicly with no employer or personal data. The
demo data is fabricated, which must be stated clearly wherever it is shown.

**Evidence.** tools/generate_synthetic_data.py, .env.example, docs/TRACEABILITY.md,
README Data and privacy section.

---

## ADR-016 - Refactor the flat tree into the netsurvey package

**Context.** The incremental build left ~28 modules flat at the repository root, with
prototypes, loaders, analysis and exporters mixed together.

**Decision.** Group modules into netsurvey/ subpackages (gui, db, llm, topology,
reporting), move prototypes to legacy/, rewrite imports, and revalidate the pipeline.

**Consequences.** The tree now communicates intent and the demo still runs end to end.
The archived prototypes intentionally keep the old root-level imports.

**Evidence.** netsurvey/ package tree, docs/TRACEABILITY.md section 11, git history.

---

## How to read this log

None of these decisions were made in a single planning session. Several were corrections
of earlier ones (ADR-005 replaced the TextFSM experiments; ADR-016 replaced the flat
layout). That is the honest shape of the project: a working system built under changing
requirements, now documented as a sequence of decisions rather than pretending it was
designed perfectly up front.
