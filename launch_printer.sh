#!/bin/bash
#
# Bayt Al Emirati Label Printer - Launcher Script
#

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Please run install_printer_app.sh first."
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Run the application
python3 bayt_printer_app.py

# Deactivate when done
deactivate
