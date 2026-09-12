# Sanitisation Notice

This repository is a **heavily sanitised version** of an internal tool, prepared so that
the engineering work can be shared and showcased publicly. It is a de-identified,
synthetic reconstruction: the architecture, code, prompts, schema, algorithms and
methodology are preserved, but nothing that identifies the employer, its customers, its
people or its real network is present.

## What was removed or replaced

**Employer identity**
- Company name and any reference to it: removed entirely (zero occurrences).
- Internal site identifiers, building codes and business-group names: removed or
  replaced with generic values (SITE-A..D, BLD-1/2, GROUP-01..12).

**Internal process terminology**
- The original network-segment identifier was renamed to MOONID.
- The original business-group field was renamed to business_group.
- The original location identifier was renamed to campus_id.
- The original filenames that contained those terms were renamed too.

**Network data**
- Hostnames and domains: replaced with the reserved domain lab.example.com.
- MAC addresses: replaced with locally-administered addresses (02:00:00:..).
- IP addresses: replaced with reserved ranges only - RFC 5737 documentation blocks
  (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24) and the RFC 2544 benchmarking range
  (198.18.0.0/15).
- Serial numbers: replaced with fabricated SYN-prefixed values.
- Real survey output, logs, database and reports: replaced by a synthetic generator.

**Credentials and secrets**
- A hard-coded API key was removed; the key is now read from the GEMINI_API_KEY
  environment variable.
- Captured device configurations, password hashes and SNMP community strings are not
  present anywhere. Synthesised console logs contain operational show output only.

**Personal data**
- Names, e-mail addresses and employee identifiers: removed entirely.

## What was preserved

- The seven-phase methodology and the workflow design.
- The application code: GUI, loaders, LLM orchestration, diagram engine, reporting.
- The LLM prompt set and the Pydantic validation schema.
- The database schema (16 tables) and the topology-inference algorithms.
- The honest development history, including the archived prototypes in legacy/.

## How to verify

- Every data artefact is reproducible: run tools/generate_synthetic_data.py.
- The repository contains a scripted scan for employer identifiers; a clean run returns
  zero across all source, documentation and generated data.
- The original runbook is kept as docs/TECHNICAL_REFERENCE.md with a layout note.

## Licensing

Copyright (c) 2025 Sreeram K R. Distributed under the PolyForm Noncommercial License
1.0.0 - see LICENSE. Commercial use is prohibited.
