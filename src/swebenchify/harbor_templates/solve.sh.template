#!/bin/bash
set -euo pipefail

cd /testbed

# Ensure git trusts the directory
git config --global --add safe.directory /testbed

# Apply the gold patch (the actual fix)
git apply --3way /solution/patch.diff || git apply /solution/patch.diff

# Some tests depend on git status
git add -A
git commit -m "Apply solution patch" --allow-empty 2>/dev/null || true
