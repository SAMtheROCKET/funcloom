#!/usr/bin/env bash
# Build/verify local artifacts on Linux; no package or repository uploads.
set -euo pipefail
PROJECT_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
ARTIFACT_DIR="${2:-}"
CHECK_DIR="${3:-$PROJECT_DIR/reports/linux-release-$(date +%Y%m%d-%H%M%S)}"
TOOLS_DIR="$(mktemp -d -t funcloom-release-tools-XXXXXXXX)"
printf 'Release tools environment: %s\n' "$TOOLS_DIR"
python3 -m venv --without-pip "$TOOLS_DIR"
curl --fail --silent --show-error --max-time 60 \
    https://bootstrap.pypa.io/get-pip.py -o "$TOOLS_DIR/get-pip.py"
"$TOOLS_DIR/bin/python" "$TOOLS_DIR/get-pip.py" --quiet
"$TOOLS_DIR/bin/python" -m pip install --quiet \
    'build>=1.2,<2' 'twine>=6,<7' 'setuptools>=77.0.3'
if [ -n "$ARTIFACT_DIR" ]; then
    "$TOOLS_DIR/bin/python" "$PROJECT_DIR/scripts/release_check.py" \
        --artifacts "$ARTIFACT_DIR" --output "$CHECK_DIR"
else
    "$TOOLS_DIR/bin/python" "$PROJECT_DIR/scripts/release_check.py" \
        --output "$CHECK_DIR"
fi
