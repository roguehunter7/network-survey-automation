# Running this project

This page states exactly what you need to run each part, and what has actually been
verified versus what is expected to work.

## Quick start (the demo)

Three commands from a fresh clone:

    git clone https://github.com/roguehunter7/network-survey-automation
    cd network-survey-automation
    ./run_demo.sh          (Windows: run_demo.bat)

That builds the synthetic dataset, the SQLite database, the topology diagrams and the
unassigned-networks report. It needs no API key and no network access.

## Verified environment

| Item | Verified | Notes |
| --- | --- | --- |
| Operating system | Linux | Windows/macOS expected to work (all paths use os.path); not verified here |
| Python | 3.14, requires 3.10+ | fresh virtual environment |
| pip install -r requirements.txt | exit 0 | pydantic, google-genai, networkx, pydot, pandas, openpyxl all resolved |
| Demo (run_demo.sh) | exit 0 | data + DB + 43 diagrams + report |
| Reporting scripts | 5 of 5 exit 0 | produced 4 xlsx and 2 csv |
| Survey GUI | not run (headless host) | needs tkinter and a display |
| Live LLM extraction | not run (no key) | needs GEMINI_API_KEY |

## Requirements by component

| Component | Needs |
| --- | --- |
| Synthetic data, database, report | Python 3.10+ only (standard library) |
| Topology diagrams | networkx, pydot, and Graphviz dot on PATH |
| Reporting exports (xlsx) | pandas, openpyxl |
| Survey GUI | tkinter and a graphical display |
| Live LLM extraction | GEMINI_API_KEY, google-genai, pydantic |

A key point: the demo, the database and the report use only the standard library. Only
the diagrams and the exports need pip packages, and only the live LLM path needs a key.

## Step by step

1. Clone the repository and enter it.

2. Create a virtual environment and install the Python dependencies:

       python3 -m venv .venv
       source .venv/bin/activate          (Windows: .venv\Scripts\activate)
       pip install -r requirements.txt

3. Install Graphviz (a system package, not pip):

   - Windows / macOS: installer from graphviz.org
   - Debian / Ubuntu: sudo apt install graphviz
   - Fedora: sudo dnf install graphviz
   - macOS (Homebrew): brew install graphviz

4. Run the demo:

       ./run_demo.sh                      (Windows: run_demo.bat)
       ./run_demo.sh full                 optional larger synthetic profile

## Phase-by-phase commands

| Phase | Command | Extra setup |
| --- | --- | --- |
| Generate synthetic data | python tools/generate_synthetic_data.py --profile small | none |
| Create database schema | python -m netsurvey.db.create_db | none |
| Load other devices | python -m netsurvey.db.load_other_devices_json_to_db | none |
| Load validated JSON | python -m netsurvey.db.load_validated_json_to_db | none |
| Topology diagrams | python tools/generate_demo_diagrams.py | networkx, pydot, Graphviz |
| Unassigned-networks report | python -m netsurvey.reporting.extract_unassigned_networks | none |
| Survey GUI | python main_app.py | tkinter and a display |
| Live LLM extraction | python -m netsurvey.llm.unified_processor | GEMINI_API_KEY |

## Viewing the workbook and diagrams

- Online: use the GitHub Pages URL in the repository homepage.
- Locally: open docs/workbook.html in a browser. For the interactive viewers and the
  sample image to load, serve the repository root rather than opening the file directly:

      python -m http.server 8000

  then open http://localhost:8000/docs/workbook.html

## The live LLM pipeline

The live extraction is the only part that calls an external service. Copy .env.example
to .env and set GEMINI_API_KEY. The model can be overridden with GEMINI_MODEL.

The committed demo does not call the LLM: tools/generate_synthetic_data.py writes the
already-structured validated JSON directly, so the demo is fully offline.

## Troubleshooting

- Diagrams skipped or "dot not found": install Graphviz and make sure dot is on PATH.
  The demo still completes; only diagram generation is skipped.
- tkinter missing (Linux): install the python3-tk package. On Windows and macOS tkinter
  ships with Python.
- The GUI closes immediately: it requires a graphical display and will not run in a
  headless shell or over plain SSH without X forwarding.
- Live LLM errors: confirm GEMINI_API_KEY is set and the model name is valid.
- pip resolution problems: use a virtual environment and Python 3.10 or newer.
- mac-vendor-lookup is optional. If the OUI list cannot be refreshed, vendor names for
  external devices fall back to blank and the run continues.

## What is not required

- No database server: SQLite is a single file.
- No API key, no credentials and no internet connection for the demo, diagrams or reports.
- No employer, customer or personal data is present anywhere in this repository.
