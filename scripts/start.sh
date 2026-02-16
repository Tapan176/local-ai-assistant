#!/bin/bash
# Startup script for TAPAN-AI on Linux/Raspberry Pi

# Navigate to project root
cd "$(dirname "$0")/.."

# Activate virtual environment if it exists
if [ -d "venv" ]; then
  echo "Starting TAPAN-AI (venv)..."
  source venv/bin/activate
else
  echo "Starting TAPAN-AI (system python)..."
fi

# Run the application
python3 start.py
