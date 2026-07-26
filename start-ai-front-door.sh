#!/bin/bash
# Shell runner for Front Door AI Person Detection service
LOG_FILE="logs/front_door_ai.log"
mkdir -p logs

echo "$(date) - 🚪 Starting Front Door AI Person Check..." | tee -a "$LOG_FILE"

# Check python availability
if command -v python3 &>/dev/null; then
    PYTHON_BIN="python3"
elif command -v python &>/dev/null; then
    PYTHON_BIN="python"
else
    echo "$(date) - ❌ Python is not installed. Aborting AI check." | tee -a "$LOG_FILE"
    exit 1
fi

# Run AI person detector with optional arguments passed to script
$PYTHON_BIN front_door_ai.py "$@" 2>&1 | tee -a "$LOG_FILE"
