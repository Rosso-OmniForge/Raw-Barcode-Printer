#!/bin/bash
#
# Bayt Al Emirati Label Printer - Installation Script
# For Debian 13 Trixie
#

set -e

echo "================================================"
echo "  Bayt Al Emirati Label Printer Installation"
echo "================================================"
echo ""

# Check if running on Debian
if [ ! -f /etc/debian_version ]; then
    echo "Warning: This script is designed for Debian systems."
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Update package list
echo "Updating package list..."
sudo apt-get update

# Install system dependencies
echo ""
echo "Installing system dependencies..."
sudo apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-pyqt6 \
    libusb-1.0-0 \
    cups

# Create virtual environment
echo ""
echo "Creating Python virtual environment..."
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install Python dependencies
echo ""
echo "Installing Python packages..."
pip install --upgrade pip
pip install -r requirements_app.txt

# Make app executable
chmod +x bayt_printer_app.py

echo ""
echo "================================================"
echo "  Installation Complete!"
echo "================================================"
echo ""
echo "To run the application:"
echo "  1. Activate virtual environment: source venv/bin/activate"
echo "  2. Run: python3 bayt_printer_app.py"
echo ""
echo "Or use the launcher script: ./launch_printer.sh"
echo ""
