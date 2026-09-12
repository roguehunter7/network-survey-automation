#!/usr/bin/env bash
# End-to-end demo of the whole pipeline on fully synthetic data.
# Usage: ./run_demo.sh [small|full]   (default: small)
set -euo pipefail
cd "$(dirname "$0")"

PROFILE="$1"
if [ -z "$PROFILE" ]; then PROFILE=small; fi
PY="$PYTHON"
if [ -z "$PY" ]; then PY=python3; fi

echo "==> 1/6  Generating synthetic dataset (profile: $PROFILE)"
"$PY" tools/generate_synthetic_data.py --profile "$PROFILE"

echo "==> 2/6  Creating database schema and reference tables"
"$PY" -m netsurvey.db.create_db

echo "==> 3/6  Loading unmanaged / other devices"
"$PY" -m netsurvey.db.load_other_devices_json_to_db

echo "==> 4/6  Loading validated managed-switch JSON"
"$PY" -m netsurvey.db.load_validated_json_to_db

echo "==> 5/6  Generating topology diagrams"
if "$PY" -c "import networkx, pydot" >/dev/null 2>&1; then
    "$PY" tools/generate_demo_diagrams.py
else
    echo "    skipped - install networkx and pydot to enable diagram generation"
fi

echo "==> 6/6  Building the unassigned-networks report"
"$PY" -m netsurvey.reporting.extract_unassigned_networks

echo
echo "Demo build complete."
echo "  Database : network_survey.db"
echo "  Diagrams : network_diagrams_pydot_final/"
echo "  Report   : unassigned_networks_GROUPED_REPORT.csv"
