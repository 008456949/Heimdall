#!/usr/bin/env bash
# Heimdall.command
# Double-click this file in Finder to launch Heimdall.
# macOS will open a Terminal window and run this script.

# Move to the directory where this script lives (the repo root)
cd "$(dirname "$0")" || exit 1

# Use venv if it exists, fall back to system python
if [[ -f ".venv/bin/python3" ]]; then
    PYTHON=".venv/bin/python3"
else
    PYTHON="python3"
fi

# Check python is available
if ! command -v "$PYTHON" &>/dev/null; then
    echo "❌  Python not found. Install from python.org or via: brew install python@3.12"
    read -r -p "Press Enter to close…"
    exit 1
fi

# Check setup has been run
if [[ ! -f ".venv/bin/python3" ]]; then
    echo "⚠  Virtual environment not found. Running setup first…"
    echo ""
    bash scripts/setup.sh || {
        echo "❌  Setup failed. See errors above."
        read -r -p "Press Enter to close…"
        exit 1
    }
    PYTHON=".venv/bin/python3"
fi

echo ""
echo "  ⬡  Starting Heimdall…"
echo "  Logs: ~/.heimdall/daemon.log"
echo "  DB:   ~/.heimdall/dashboard.db"
echo ""

exec "$PYTHON" run.py
