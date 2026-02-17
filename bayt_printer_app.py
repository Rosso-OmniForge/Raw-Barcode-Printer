#!/usr/bin/env python3
"""
Bayt Al Emirati Label Printer Desktop Application
Modern PyQt6 GUI for managing and printing label requests
"""

import sys
import json
import subprocess
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QProgressBar, QGroupBox, QTextEdit, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QSplitter, QStatusBar
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QFont, QIcon, QPalette, QColor, QPixmap

import requests


# Configuration
API_BASE_URL = "http://localhost:8000"  # Change to production URL
API_KEY = "BAE-PRINTER-2026-SECURE-KEY"  # Should match backend


class PrinterScanner(QThread):
    """Background thread to scan for USB printers."""
    
    printers_found = pyqtSignal(list)
    
    def run(self):
        """Scan for available USB printers."""
        printers = []
        try:
            usb_path = Path("/dev/usb")
            if usb_path.exists():
                printers = sorted([str(p) for p in usb_path.glob("lp*")])
        except Exception as e:
            print(f"Error scanning for printers: {e}")
        
        self.printers_found.emit(printers)


class PrintJob(QThread):
    """Background thread for printing labels."""
    
    progress = pyqtSignal(int, int)  # current, total
    finished = pyqtSignal(bool, str)  # success, message
    
    def __init__(self, printer_device: str, items: List[Dict[str, Any]]):
        super().__init__()
        self.printer_device = printer_device
        self.items = items
        self.label_width_dots = 320
        self.horizontal_shift_dots = 16
    
    def _tspl_escape(self, s: str) -> str:
        """Escape a string for TSPL commands."""
        return (s or "").replace('\\', '\\\\').replace('"', '\\"')
    
    def _center_x_for_text(self, text: str, font: str = "4", xmul: int = 1) -> int:
        """Calculate centered X position for text."""
        font_char_width = {
            '1': 8, '2': 12, '3': 16, '4': 24, '5': 32,
            '6': 14, '7': 14, '8': 14,
        }
        char_w = font_char_width.get(str(font), 8) * max(1, int(xmul))
        width = len(text or "") * char_w
        x = int((self.label_width_dots - width) / 2)
        return max(0, x) + self.horizontal_shift_dots
    
    def _center_x_for_code39(self, data: str, narrow: int = 2, wide: int = 4) -> int:
        """Calculate centered X position for Code39 barcode."""
        n = max(1, int(narrow))
        w = max(n, int(wide))
        char_count = len(data or "") + 2
        per_char_modules = (3 * w) + (6 * n)
        inter_gap = n
        width = (char_count * per_char_modules) + ((char_count - 1) * inter_gap)
        x = int((self.label_width_dots - width) / 2)
        return max(0, x) + self.horizontal_shift_dots
    
    def _format_price(self, price_cents: int, currency: str = "ZAR") -> str:
        """Format price for display."""
        if currency == "ZAR":
            symbol = "R"
        else:
            symbol = currency
        
        price = price_cents / 100
        return f"{symbol}{price:.2f}"
    
    def _generate_label_tspl(self, item: Dict[str, Any]) -> str:
        """Generate TSPL commands for a single label."""
        title = (item.get("title") or "")[:30]  # Truncate if too long
        variant_label = item.get("variant_label") or ""
        sku = item.get("sku") or ""
        code39 = item.get("code39") or sku
        price = self._format_price(item.get("price_cents", 0), item.get("currency", "ZAR"))
        
        # Build TSPL command
        tspl = []
        tspl.append("SIZE 40 mm, 30 mm")
        tspl.append("GAP 2 mm, 0 mm")
        tspl.append("DIRECTION 0")
        tspl.append("REFERENCE 0, 0")
        tspl.append("OFFSET 0 mm")
        tspl.append("SET PEEL OFF")
        tspl.append("SET CUTTER OFF")
        tspl.append("SET PARTIAL_CUTTER OFF")
        tspl.append("SET TEAR ON")
        tspl.append("CLS")
        
        # Title (top)
        title_x = self._center_x_for_text(title, "3")
        tspl.append(f'TEXT {title_x},10,"3",0,1,1,"{self._tspl_escape(title)}"')
        
        # Variant label (below title)
        if variant_label:
            variant_x = self._center_x_for_text(variant_label, "2")
            tspl.append(f'TEXT {variant_x},40,"2",0,1,1,"{self._tspl_escape(variant_label)}"')
        
        # Code39 barcode (center)
        bc_x = self._center_x_for_code39(code39, narrow=2, wide=4)
        tspl.append(f'BARCODE {bc_x},70,"39",60,1,0,2,4,"{self._tspl_escape(code39)}"')
        
        # Price (bottom)
        price_x = self._center_x_for_text(price, "4", xmul=2)
        tspl.append(f'TEXT {price_x},150,"4",0,2,2,"{self._tspl_escape(price)}"')
        
        # SKU (very bottom, small)
        sku_x = self._center_x_for_text(sku, "1")
        tspl.append(f'TEXT {sku_x},210,"1",0,1,1,"{self._tspl_escape(sku)}"')
        
        tspl.append("PRINT 1")
        
        return "\n".join(tspl) + "\n"
    
    def run(self):
        """Execute print job."""
        try:
            total = sum(item.get("qty_to_print", 0) for item in self.items)
            current = 0
            
            for item in self.items:
                qty = item.get("qty_to_print", 0)
                
                for i in range(qty):
                    # Generate label
                    tspl = self._generate_label_tspl(item)
                    
                    # Send to printer
                    try:
                        with open(self.printer_device, 'wb') as printer:
                            printer.write(tspl.encode('utf-8'))
                    except Exception as e:
                        self.finished.emit(False, f"Printer error: {e}")
                        return
                    
                    current += 1
                    self.progress.emit(current, total)
                    
                    # Small delay between labels
                    time.sleep(0.2)
            
            self.finished.emit(True, f"Successfully printed {total} labels")
            
        except Exception as e:
            self.finished.emit(False, f"Print job failed: {e}")


class BaytAlEmiratiPrinterApp(QMainWindow):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        
        self.api_base_url = API_BASE_URL
        self.api_key = API_KEY
        self.selected_printer = None
        self.printer_calibrated = False
        self.pending_requests: List[Dict[str, Any]] = []
        
        self.init_ui()
        self.setup_auto_refresh()
        
        # Auto-scan for printers on startup
        self.scan_for_printers()
    
    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("Bayt Al Emirati - Label Printer")
        self.setGeometry(100, 100, 1200, 800)
        
        # Set window icon
        logo_path = Path(__file__).parent / "assets" / "logo.png"
        if logo_path.exists():
            self.setWindowIcon(QIcon(str(logo_path)))
        
        # Set modern color scheme
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#1a1a1a"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#2d2d2d"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#353535"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#ffffff"))
        self.setPalette(palette)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Header
        header = self.create_header()
        main_layout.addWidget(header)
        
        # Splitter for printer config and print queue
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel - Printer configuration
        printer_panel = self.create_printer_panel()
        splitter.addWidget(printer_panel)
        
        # Right panel - Print queue
        queue_panel = self.create_queue_panel()
        splitter.addWidget(queue_panel)
        
        splitter.setSizes([400, 800])
        main_layout.addWidget(splitter)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
    
    def create_header(self) -> QWidget:
        """Create application header."""
        header = QWidget()
        header.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1a1a1a, stop:1 #2d2d2d);
                border-radius: 12px;
                padding: 15px;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(15, 15, 15, 15)
        
        # Logo Image
        logo_path = Path(__file__).parent / "assets" / "text_logo.png"
        if logo_path.exists():
            logo_label = QLabel()
            pixmap = QPixmap(str(logo_path))
            # Scale logo to reasonable size while maintaining aspect ratio
            scaled_pixmap = pixmap.scaledToHeight(60, Qt.TransformationMode.SmoothTransformation)
            logo_label.setPixmap(scaled_pixmap)
            header_layout.addWidget(logo_label)
        else:
            # Fallback to text if logo not found
            title = QLabel("🏪 Bayt Al Emirati")
            title_font = QFont("Arial", 24, QFont.Weight.Bold)
            title.setFont(title_font)
            title.setStyleSheet("color: #d4af37;")
            header_layout.addWidget(title)
        
        # Subtitle
        subtitle_container = QVBoxLayout()
        subtitle_container.addStretch()
        
        subtitle = QLabel("Label Printing System")
        subtitle_font = QFont("Arial", 14, QFont.Weight.Bold)
        subtitle.setFont(subtitle_font)
        subtitle.setStyleSheet("color: #d4af37; margin-left: 15px;")
        subtitle_container.addWidget(subtitle)
        
        version_label = QLabel("v1.0.0")
        version_label.setFont(QFont("Arial", 9))
        version_label.setStyleSheet("color: #888; margin-left: 15px;")
        subtitle_container.addWidget(version_label)
        subtitle_container.addStretch()
        
        header_layout.addLayout(subtitle_container)
        header_layout.addStretch()
        
        # Status badges container
        status_container = QVBoxLayout()
        status_container.addStretch()
        
        # Connection status indicator
        self.header_connection_status = QLabel("● Disconnected")
        self.header_connection_status.setFont(QFont("Arial", 9))
        self.header_connection_status.setStyleSheet("color: #ff5555; margin-right: 10px;")
        status_container.addWidget(self.header_connection_status)
        
        # Printer status indicator
        self.header_printer_status = QLabel("⚠ No Printer")
        self.header_printer_status.setFont(QFont("Arial", 9))
        self.header_printer_status.setStyleSheet("color: #ff9800; margin-right: 10px;")
        status_container.addWidget(self.header_printer_status)
        
        status_container.addStretch()
        header_layout.addLayout(status_container)
        
        # Refresh button
        refresh_btn = QPushButton("🔄 Refresh Queue")
        refresh_btn.setFixedSize(150, 50)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #d4af37, stop:1 #b8941f);
                color: #000;
                border: none;
                border-radius: 8px;
                font-size: 13px;
                font-weight: bold;
                padding: 5px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #e5c048, stop:1 #d4af37);
            }
            QPushButton:pressed {
                background: #b8941f;
            }
        """)
        refresh_btn.clicked.connect(self.fetch_pending_requests)
        header_layout.addWidget(refresh_btn)
        
        return header
        
        # Refresh button
        refresh_btn = QPushButton("🔄 Refresh Queue")
        refresh_btn.setFixedSize(150, 40)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        refresh_btn.clicked.connect(self.fetch_pending_requests)
        header_layout.addWidget(refresh_btn)
        
        return header
    
    def create_printer_panel(self) -> QWidget:
        """Create printer configuration panel."""
        group = QGroupBox("Printer Configuration")
        group.setStyleSheet("""
            QGroupBox {
                font-size: 15px;
                font-weight: bold;
                color: #d4af37;
                border: 2px solid #d4af37;
                border-radius: 12px;
                margin-top: 15px;
                padding-top: 25px;
                background-color: #2d2d2d;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
                background-color: #2d2d2d;
            }
            QLabel {
                color: #ffffff;
            }
        """)
        
        layout = QVBoxLayout(group)
        layout.setSpacing(15)
        
        # Printer selection
        printer_label = QLabel("Select Printer:")
        self.printer_combo = QComboBox()
        self.printer_combo.addItem("No printer selected")
        self.printer_combo.currentIndexChanged.connect(self.on_printer_selected)
        
        scan_btn = QPushButton("Scan for Printers")
        scan_btn.clicked.connect(self.scan_for_printers)
        scan_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3d3d3d, stop:1 #2d2d2d);
                color: #d4af37;
                border: 1px solid #d4af37;
                border-radius: 6px;
                padding: 10px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4d4d4d, stop:1 #3d3d3d);
                border: 1px solid #e5c048;
            }
            QPushButton:pressed {
                background: #1d1d1d;
            }
        """)
        
        layout.addWidget(printer_label)
        layout.addWidget(self.printer_combo)
        layout.addWidget(scan_btn)
        
        # Calibration status
        self.calibration_status = QLabel("❌ Not Calibrated")
        
        calibrate_btn = QPushButton("⚙️ Calibrate Printer")
        calibrate_btn.clicked.connect(self.calibrate_printer)
        calibrate_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #d4af37, stop:1 #b8941f);
                color: #000;
                border: none;
                border-radius: 6px;
                padding: 12px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #e5c048, stop:1 #d4af37);
            }
            QPushButton:pressed {
                background: #b8941f;
            }
        """)
        
        layout.addWidget(QLabel("Calibration:"))
        layout.addWidget(self.calibration_status)
        layout.addWidget(calibrate_btn)
        
        # Connection status
        self.connection_status = QLabel("🔴 Not Connected")
        self.connection_status.setStyleSheet("font-size: 14px; padding: 10px; background-color: #2d2d2d; border: 1px solid #ff5555; border-radius: 5px; color: #ff5555;")
        
        test_connection_btn = QPushButton("Test API Connection")
        test_connection_btn.clicked.connect(self.test_api_connection)
        test_connection_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3d3d3d, stop:1 #2d2d2d);
                color: #d4af37;
                border: 1px solid #d4af37;
                border-radius: 6px;
                padding: 10px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4d4d4d, stop:1 #3d3d3d);
                border: 1px solid #e5c048;
            }
            QPushButton:pressed {
                background: #1d1d1d;
            }
        """)
        
        layout.addWidget(QLabel("API Connection:"))
        layout.addWidget(self.connection_status)
        layout.addWidget(test_connection_btn)
        
        # API Configuration
        api_label = QLabel("API Server URL:")
        self.api_url_input = QLineEdit(self.api_base_url)
        self.api_url_input.textChanged.connect(self.on_api_url_changed)
        
        layout.addWidget(api_label)
        layout.addWidget(self.api_url_input)
        
        layout.addStretch()
        
        return group
    
    def create_queue_panel(self) -> QWidget:
        """Create print queue panel."""
        group = QGroupBox("Print Queue")
        group.setStyleSheet("""
            QGroupBox {
                font-size: 15px;
                font-weight: bold;
                color: #d4af37;
                border: 2px solid #d4af37;
                border-radius: 12px;
                margin-top: 15px;
                padding-top: 25px;
                background-color: #2d2d2d;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
                background-color: #2d2d2d;
            }
            QLabel {
                color: #ffffff;
            }
        """)
        
        layout = QVBoxLayout(group)
        layout.setSpacing(10)
        
        # Pending requests table
        self.requests_table = QTableWidget()
        self.requests_table.setColumnCount(6)
        self.requests_table.setHorizontalHeaderLabels([
            "ID", "Source", "Created By", "Total Labels", "Created At", "Action"
        ])
        self.requests_table.horizontalHeader().setStretchLastSection(False)
        self.requests_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.requests_table.setColumnWidth(0, 50)
        self.requests_table.setColumnWidth(1, 120)
        self.requests_table.setColumnWidth(2, 150)
        self.requests_table.setColumnWidth(3, 100)
        self.requests_table.setColumnWidth(4, 180)
        self.requests_table.setColumnWidth(5, 150)
        
        self.requests_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.requests_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.requests_table.setAlternatingRowColors(True)
        self.requests_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #d4af37;
                border-radius: 8px;
                background-color: #1a1a1a;
                color: #ffffff;
                gridline-color: #3d3d3d;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #3d3d3d;
            }
            QTableWidget::item:selected {
                background-color: #d4af37;
                color: #000;
            }
            QTableWidget::item:hover {
                background-color: #3d3d3d;
            }
            QHeaderView::section {
                background-color: #2d2d2d;
                color: #d4af37;
                padding: 10px;
                border: none;
                border-bottom: 2px solid #d4af37;
                font-weight: bold;
                font-size: 12px;
            }
        """)
        
        layout.addWidget(self.requests_table)
        
        # Print details
        details_label = QLabel("Print Details:")
        self.details_text = QTextEdit()
        self.details_text.setMaximumHeight(150)
        self.details_text.setReadOnly(True)
        self.details_text.setStyleSheet("""
            QTextEdit {
                border: 1px solid #d4af37;
                border-radius: 8px;
                background-color: #1a1a1a;
                color: #d4af37;
                font-family: 'Courier New', monospace;
                font-size: 11px;
                padding: 10px;
            }
        """)
        
        layout.addWidget(details_label)
        layout.addWidget(self.details_text)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #d4af37;
                border-radius: 8px;
                text-align: center;
                height: 30px;
                background-color: #1a1a1a;
                color: #d4af37;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #d4af37, stop:1 #e5c048);
                border-radius: 6px;
            }
        """)
        layout.addWidget(self.progress_bar)
        
        return group
    
    def setup_auto_refresh(self):
        """Setup automatic refresh timer."""
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.fetch_pending_requests)
        self.refresh_timer.start(30000)  # Refresh every 30 seconds
    
    def scan_for_printers(self):
        """Scan for available USB printers."""
        self.status_bar.showMessage("Scanning for printers...")
        self.scanner = PrinterScanner()
        self.scanner.printers_found.connect(self.on_printers_found)
        self.scanner.start()
    
    def on_printers_found(self, printers: List[str]):
        """Handle printer scan results."""
        self.printer_combo.clear()
        
        if not printers:
            self.printer_combo.addItem("No printers found")
            self.status_bar.showMessage("No printers found")
        else:
            self.printer_combo.addItem("Select a printer...")
            for printer in printers:
                self.printer_combo.addItem(printer)
            self.status_bar.showMessage(f"Found {len(printers)} printer(s)")
    
    def on_printer_selected(self, index: int):
        """Handle printer selection."""
        if index > 0:  # Skip "Select a printer..."
            self.selected_printer = self.printer_combo.currentText()
            self.status_bar.showMessage(f"Selected printer: {self.selected_printer}")
            self.printer_calibrated = False
            self.calibration_status.setText("❌ Not Calibrated")
            self.calibration_status.setStyleSheet("font-size: 14px; color: #f44336;")
            # Update header status
            self.header_printer_status.setText("⚠ Not Calibrated")
            self.header_printer_status.setStyleSheet("color: #ff9800; margin-right: 10px;")
        else:
            self.selected_printer = None
            self.header_printer_status.setText("⚠ No Printer")
            self.header_printer_status.setStyleSheet("color: #ff5555; margin-right: 10px;")
    
    def calibrate_printer(self):
        """Calibrate printer and print test label."""
        if not self.selected_printer:
            QMessageBox.warning(self, "No Printer", "Please select a printer first.")
            return
        
        try:
            # Send calibration command
            calibration_tspl = "SIZE 40 mm, 30 mm\nGAP 2 mm, 0 mm\n"
            
            with open(self.selected_printer, 'wb') as printer:
                printer.write(calibration_tspl.encode('utf-8'))
            
            # Print test label
            test_item = {
                "title": "TEST LABEL",
                "variant_label": "Calibration Test",
                "sku": "TEST-001",
                "code39": "TEST001",
                "price_cents": 9999,
                "currency": "ZAR"
            }
            
            test_job = PrintJob(self.selected_printer, [test_item])
            test_job.finished.connect(self.on_test_print_finished)
            test_job.start()
            
            self.status_bar.showMessage("Calibrating printer...")
            
        except Exception as e:
            QMessageBox.critical(self, "Calibration Error", f"Failed to calibrate: {e}")
    
    def on_test_print_finished(self, success: bool, message: str):
        """Handle test print completion."""
        if success:
            reply = QMessageBox.question(
                self,
                "Test Print",
                "Test label printed. Does it look correct?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.printer_calibrated = True
                self.calibration_status.setText("✅ Calibrated")
                self.calibration_status.setStyleSheet("font-size: 14px; color: #4CAF50;")
                self.status_bar.showMessage("Printer calibrated successfully")
                # Update header status
                self.header_printer_status.setText("✓ Printer Ready")
                self.header_printer_status.setStyleSheet("color: #4CAF50; margin-right: 10px;")
            else:
                QMessageBox.information(
                    self,
                    "Calibration Help",
                    "Please check:\n"
                    "- Label size is 40mm x 30mm\n"
                    "- Gap is 2mm\n"
                    "- Printer alignment settings\n\n"
                    "Try calibrating again or adjust printer settings."
                )
        else:
            QMessageBox.critical(self, "Test Print Failed", message)
    
    def test_api_connection(self):
        """Test connection to backend API."""
        try:
            headers = {"X-API-Key": self.api_key}
            response = requests.get(
                f"{self.api_base_url}/admin/api/label-printing/pending",
                headers=headers,
                timeout=5
            )
            
            if response.status_code == 200:
                self.connection_status.setText("🟢 Connected")
                self.connection_status.setStyleSheet(
                    "font-size: 14px; padding: 10px; background-color: #2d2d2d; border: 1px solid #4CAF50; border-radius: 5px; color: #4CAF50;"
                )
                # Update header status
                self.header_connection_status.setText("● Connected")
                self.header_connection_status.setStyleSheet("color: #4CAF50; margin-right: 10px;")
                QMessageBox.information(self, "Connection Success", "Successfully connected to API server!")
                self.fetch_pending_requests()
            else:
                self.connection_status.setText(f"🔴 Error ({response.status_code})")
                self.connection_status.setStyleSheet(
                    "font-size: 14px; padding: 10px; background-color: #2d2d2d; border: 1px solid #ff5555; border-radius: 5px; color: #ff5555;"
                )
                # Update header status
                self.header_connection_status.setText("● Error")
                self.header_connection_status.setStyleSheet("color: #ff5555; margin-right: 10px;")
                QMessageBox.warning(self, "Connection Error", f"Server returned: {response.status_code}")
                
        except Exception as e:
            self.connection_status.setText("🔴 Not Connected")
            self.connection_status.setStyleSheet(
                "font-size: 14px; padding: 10px; background-color: #2d2d2d; border: 1px solid #ff5555; border-radius: 5px; color: #ff5555;"
            )
            # Update header status
            self.header_connection_status.setText("● Disconnected")
            self.header_connection_status.setStyleSheet("color: #ff5555; margin-right: 10px;")
            QMessageBox.critical(self, "Connection Failed", f"Failed to connect: {e}")
    
    def on_api_url_changed(self, text: str):
        """Handle API URL change."""
        self.api_base_url = text.strip()
    
    def fetch_pending_requests(self):
        """Fetch pending print requests from API."""
        try:
            headers = {"X-API-Key": self.api_key}
            response = requests.get(
                f"{self.api_base_url}/admin/api/label-printing/pending",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                self.pending_requests = response.json()
                self.update_requests_table()
                self.status_bar.showMessage(f"Loaded {len(self.pending_requests)} pending request(s)")
            else:
                self.status_bar.showMessage(f"Failed to fetch requests: {response.status_code}")
                
        except Exception as e:
            self.status_bar.showMessage(f"Error fetching requests: {e}")
    
    def update_requests_table(self):
        """Update the requests table with pending requests."""
        self.requests_table.setRowCount(len(self.pending_requests))
        
        for row, request in enumerate(self.pending_requests):
            # ID
            self.requests_table.setItem(row, 0, QTableWidgetItem(str(request.get("id", ""))))
            
            # Source
            source = request.get("source", "").replace("_", " ").title()
            self.requests_table.setItem(row, 1, QTableWidgetItem(source))
            
            # Created by
            self.requests_table.setItem(row, 2, QTableWidgetItem(request.get("created_by_username", "")))
            
            # Total labels
            self.requests_table.setItem(row, 3, QTableWidgetItem(str(request.get("total_labels", 0))))
            
            # Created at
            created_at = request.get("created_at", "")
            if created_at:
                # Format datetime
                try:
                    dt_obj = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    created_at = dt_obj.strftime("%Y-%m-%d %H:%M")
                except:
                    pass
            self.requests_table.setItem(row, 4, QTableWidgetItem(created_at))
            
            # Print button
            print_btn = QPushButton("🖨️ Print")
            print_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #d4af37, stop:1 #b8941f);
                    color: #000;
                    border: 1px solid #e5c048;
                    border-radius: 6px;
                    padding: 8px 15px;
                    font-weight: bold;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #e5c048, stop:1 #d4af37);
                    border: 1px solid #f5d058;
                }
                QPushButton:pressed {
                    background: #b8941f;
                }
            """)
            print_btn.clicked.connect(lambda checked, r=request: self.print_request(r))
            self.requests_table.setCellWidget(row, 5, print_btn)
        
        # Select first row if available
        if len(self.pending_requests) > 0:
            self.requests_table.selectRow(0)
            self.show_request_details(self.pending_requests[0])
    
    def show_request_details(self, request: Dict[str, Any]):
        """Show details of selected request."""
        try:
            headers = {"X-API-Key": self.api_key}
            response = requests.get(
                f"{self.api_base_url}/admin/api/label-printing/request/{request['id']}",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                items = data.get("items", [])
                
                details = f"Request ID: {request['id']}\n"
                details += f"Source: {request.get('source', '')}\n"
                details += f"Note: {request.get('note', '')}\n"
                details += f"Total Labels: {request.get('total_labels', 0)}\n\n"
                details += "Items:\n"
                details += "-" * 50 + "\n"
                
                for item in items:
                    details += f"• {item.get('title', '')} - {item.get('variant_label', '')}\n"
                    details += f"  SKU: {item.get('sku', '')} | Qty: {item.get('qty_to_print', 0)}\n"
                
                self.details_text.setText(details)
            
        except Exception as e:
            self.details_text.setText(f"Error loading details: {e}")
    
    def print_request(self, request: Dict[str, Any]):
        """Print labels for a specific request."""
        if not self.selected_printer:
            QMessageBox.warning(self, "No Printer", "Please select a printer first.")
            return
        
        if not self.printer_calibrated:
            reply = QMessageBox.question(
                self,
                "Printer Not Calibrated",
                "Printer has not been calibrated. Print anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        
        try:
            # Fetch request details
            headers = {"X-API-Key": self.api_key}
            response = requests.get(
                f"{self.api_base_url}/admin/api/label-printing/request/{request['id']}",
                headers=headers,
                timeout=10
            )
            
            if response.status_code != 200:
                QMessageBox.critical(self, "Error", "Failed to fetch print job details")
                return
            
            data = response.json()
            items = data.get("items", [])
            
            if not items:
                QMessageBox.warning(self, "No Items", "This request has no items to print.")
                return
            
            # Start print job
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            
            self.print_job = PrintJob(self.selected_printer, items)
            self.print_job.progress.connect(self.on_print_progress)
            self.print_job.finished.connect(lambda s, m: self.on_print_finished(s, m, request['id']))
            self.print_job.start()
            
            self.status_bar.showMessage(f"Printing request #{request['id']}...")
            
        except Exception as e:
            QMessageBox.critical(self, "Print Error", f"Failed to start print job: {e}")
            self.progress_bar.setVisible(False)
    
    def on_print_progress(self, current: int, total: int):
        """Update progress bar."""
        if total > 0:
            percentage = int((current / total) * 100)
            self.progress_bar.setValue(percentage)
            self.status_bar.showMessage(f"Printing: {current}/{total} labels")
    
    def on_print_finished(self, success: bool, message: str, request_id: int):
        """Handle print job completion."""
        self.progress_bar.setVisible(False)
        
        if success:
            # Mark as completed on server
            try:
                headers = {"X-API-Key": self.api_key, "Content-Type": "application/json"}
                response = requests.post(
                    f"{self.api_base_url}/admin/api/label-printing/complete",
                    headers=headers,
                    json={"request_id": request_id},
                    timeout=10
                )
                
                if response.status_code == 200:
                    QMessageBox.information(self, "Success", message)
                    self.fetch_pending_requests()  # Refresh list
                else:
                    QMessageBox.warning(
                        self,
                        "Print Complete",
                        f"{message}\n\nWarning: Failed to mark as completed on server."
                    )
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Print Complete",
                    f"{message}\n\nWarning: Failed to communicate with server: {e}"
                )
        else:
            QMessageBox.critical(self, "Print Failed", message)
        
        self.status_bar.showMessage("Ready")


def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # Modern look
    
    # Set application-wide font
    font = QFont("Arial", 10)
    app.setFont(font)
    
    window = BaytAlEmiratiPrinterApp()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
