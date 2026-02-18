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
    QPushButton, QLabel, QMessageBox, QFrame,
    QProgressBar, QTextEdit, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy, QStatusBar,
    QScrollArea
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QFont, QIcon, QPalette, QColor, QPixmap

import requests


# Configuration
API_BASE_URL = "https://store.baytalemirati.co.za"  # Change to production URL
API_KEY = "BAE-PRINTER-2026-SECURE-KEY"  # Should match backend
APP_CONFIG_FILE = Path.home() / ".config" / "bayt_printer" / "settings.json"


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
        self.last_selected_printer: Optional[str] = None
        self.auto_connect_on_startup = True
        self.calibration_job: Optional[PrintJob] = None
        self.print_job: Optional[PrintJob] = None

        self.load_settings()
        
        self.init_ui()
        self.setup_auto_refresh()
        
        # Auto-scan for printers on startup
        self.scan_for_printers()
        QTimer.singleShot(1200, self.auto_connect_to_api)

    def load_settings(self):
        """Load persisted app settings."""
        try:
            if not APP_CONFIG_FILE.exists():
                return

            with open(APP_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.api_base_url = (data.get("api_base_url") or self.api_base_url).strip()
            self.last_selected_printer = data.get("label_printer_device") or None
            self.auto_connect_on_startup = bool(data.get("auto_connect_on_startup", True))
        except Exception as e:
            print(f"Warning: failed to load settings: {e}")

    def save_settings(self):
        """Persist app settings."""
        try:
            APP_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "api_base_url": self.api_base_url,
                "label_printer_device": self.last_selected_printer,
                "auto_connect_on_startup": self.auto_connect_on_startup,
                "printer_roles": {
                    "label": self.last_selected_printer,
                    "pos_slip": None,
                },
            }
            with open(APP_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Warning: failed to save settings: {e}")

    def _set_connection_status(self, connected: bool, status_code: Optional[int] = None):
        """Update API connection indicators in the UI."""
        if connected:
            self.connection_status.setText("Connected")
            self.connection_status.setStyleSheet(
                f"background:#0f2a1a; color:{self.C_GREEN}; border:1px solid #1a5a2a;"
                f"border-radius:12px; font-size:11px; font-weight:600; padding:4px 10px;"
            )
            self.header_connection_status.setText("● Connected")
            self.header_connection_status.setStyleSheet(
                f"color:{self.C_GREEN}; font-size:10px; font-weight:600;"
            )
            return

        err_label = f"Error {status_code}" if status_code is not None else "Disconnected"
        self.connection_status.setText(err_label)
        self.connection_status.setStyleSheet(
            f"background:#2a1a1a; color:{self.C_RED}; border:1px solid #5a2a2a;"
            f"border-radius:12px; font-size:11px; font-weight:600; padding:4px 10px;"
        )
        self.header_connection_status.setText("● Disconnected")
        self.header_connection_status.setStyleSheet(
            f"color:{self.C_RED}; font-size:10px; font-weight:600;"
        )

    def check_api_connection(self, show_dialogs: bool = True, fetch_queue_on_success: bool = True) -> bool:
        """Check API connectivity and update status indicators."""
        try:
            headers = {"X-API-Key": self.api_key}
            response = requests.get(
                f"{self.api_base_url}/admin/api/label-printing/pending",
                headers=headers,
                timeout=5
            )

            if response.status_code == 200:
                self._set_connection_status(True)
                if fetch_queue_on_success:
                    self.pending_requests = response.json()
                    self.update_requests_table()
                    self.status_bar.showMessage(f"Loaded {len(self.pending_requests)} pending request(s)")
                if show_dialogs:
                    QMessageBox.information(self, "Connection Success", "Successfully connected to API server!")
                return True

            self._set_connection_status(False, status_code=response.status_code)
            if show_dialogs:
                QMessageBox.warning(self, "Connection Error", f"Server returned: {response.status_code}")
            return False

        except Exception as e:
            self._set_connection_status(False)
            if show_dialogs:
                QMessageBox.critical(self, "Connection Failed", f"Failed to connect: {e}")
            return False

    def auto_connect_to_api(self):
        """Attempt API connection on startup without interrupting users."""
        if not self.auto_connect_on_startup:
            return
        if not self.api_base_url:
            return
        self.check_api_connection(show_dialogs=False, fetch_queue_on_success=True)
    
    # ─────────────────────────────────────────────────────────────
    # Shared style constants
    # ─────────────────────────────────────────────────────────────
    C_BG        = "#111318"   # window background
    C_SURFACE   = "#1c1f26"   # card / panel surface
    C_SURFACE2  = "#242830"   # slightly lighter surface
    C_BORDER    = "#2e3340"   # subtle border
    C_GOLD      = "#c9a84c"   # primary accent
    C_GOLD_HI   = "#e0c06a"   # hover accent
    C_GOLD_DIM  = "#7a6128"   # pressed / dim accent
    C_TEXT      = "#e8e8e8"   # primary text
    C_TEXT_DIM  = "#7a7f8e"   # secondary / muted text
    C_GREEN     = "#4caf7d"   # success
    C_RED       = "#e05252"   # error
    C_ORANGE    = "#e09a2a"   # warning
    C_SIDEBAR   = "#13161c"   # sidebar

    SIDEBAR_W   = 220         # fixed sidebar width px

    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("Bayt Al Emirati · Print Manager")
        self.setMinimumSize(1100, 700)
        self.resize(1340, 820)

        logo_path = Path(__file__).parent / "assets" / "logo.png"
        if logo_path.exists():
            self.setWindowIcon(QIcon(str(logo_path)))

        # ── Global palette ──────────────────────────────────────
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Window,         QColor(self.C_BG))
        pal.setColor(QPalette.ColorRole.WindowText,     QColor(self.C_TEXT))
        pal.setColor(QPalette.ColorRole.Base,           QColor(self.C_SURFACE))
        pal.setColor(QPalette.ColorRole.AlternateBase,  QColor(self.C_SURFACE2))
        pal.setColor(QPalette.ColorRole.Text,           QColor(self.C_TEXT))
        pal.setColor(QPalette.ColorRole.Button,         QColor(self.C_SURFACE2))
        pal.setColor(QPalette.ColorRole.ButtonText,     QColor(self.C_TEXT))
        pal.setColor(QPalette.ColorRole.Highlight,      QColor(self.C_GOLD))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#000000"))
        self.setPalette(pal)

        # ── Root layout: sidebar | content ──────────────────────
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = self._build_sidebar()
        root_layout.addWidget(sidebar)

        # thin separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background:{self.C_BORDER};")
        root_layout.addWidget(sep)

        content = self._build_content()
        root_layout.addWidget(content, stretch=1)

        # ── Status bar ──────────────────────────────────────────
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet(
            f"QStatusBar {{ background:{self.C_SURFACE}; color:{self.C_TEXT_DIM};"
            f" border-top:1px solid {self.C_BORDER}; font-size:11px; padding:2px 10px; }}"
        )
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    # ── Stylesheet helpers ────────────────────────────────────────
    def _btn_primary(self) -> str:
        return (
            f"QPushButton {{"
            f"  background:{self.C_GOLD}; color:#000; border:none;"
            f"  border-radius:6px; padding:9px 16px;"
            f"  font-size:12px; font-weight:700; letter-spacing:0.3px;"
            f"}} "
            f"QPushButton:hover {{ background:{self.C_GOLD_HI}; }} "
            f"QPushButton:pressed {{ background:{self.C_GOLD_DIM}; color:#000; }}"
        )

    def _btn_secondary(self) -> str:
        return (
            f"QPushButton {{"
            f"  background:{self.C_SURFACE2}; color:{self.C_GOLD};"
            f"  border:1px solid {self.C_BORDER};"
            f"  border-radius:6px; padding:8px 16px;"
            f"  font-size:12px; font-weight:600;"
            f"}} "
            f"QPushButton:hover {{ border-color:{self.C_GOLD}; background:{self.C_SURFACE2}; color:{self.C_GOLD_HI}; }} "
            f"QPushButton:pressed {{ background:{self.C_BG}; }}"
        )

    def _card_style(self, radius: int = 10) -> str:
        return (
            f"background:{self.C_SURFACE};"
            f"border:1px solid {self.C_BORDER};"
            f"border-radius:{radius}px;"
        )

    def _label_style(self, small: bool = False) -> str:
        size = 10 if small else 12
        return f"color:{self.C_TEXT_DIM}; font-size:{size}px; font-weight:600; letter-spacing:0.6px;"

    def _input_style(self) -> str:
        return (
            f"QLineEdit, QComboBox {{"
            f"  background:{self.C_SURFACE2}; color:{self.C_TEXT};"
            f"  border:1px solid {self.C_BORDER}; border-radius:6px;"
            f"  padding:7px 10px; font-size:12px;"
            f"}} "
            f"QLineEdit:focus, QComboBox:focus {{ border-color:{self.C_GOLD}; }} "
            f"QComboBox::drop-down {{ border:none; width:24px; }} "
            f"QComboBox::down-arrow {{ width:10px; height:10px; }}"
        )

    # ── Sidebar ───────────────────────────────────────────────────
    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setFixedWidth(self.SIDEBAR_W)
        sidebar.setStyleSheet(f"QWidget {{ background:{self.C_SIDEBAR}; }}")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Stacked logos ─────────────────────────────────────────
        logo_container = QWidget()
        logo_container.setStyleSheet(
            f"background:{self.C_SIDEBAR};"
            f"border-bottom:1px solid {self.C_BORDER};"
        )
        logo_layout = QVBoxLayout(logo_container)
        logo_layout.setContentsMargins(18, 24, 18, 20)
        logo_layout.setSpacing(10)
        logo_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        assets = Path(__file__).parent / "assets"
        logo_w = self.SIDEBAR_W - 36   # constant inner width for both images

        def _make_logo_label(img_path: Path) -> QLabel:
            lbl = QLabel()
            lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            lbl.setStyleSheet("background:transparent; border:none;")
            if img_path.exists():
                px = QPixmap(str(img_path))
                lbl.setPixmap(
                    px.scaledToWidth(logo_w, Qt.TransformationMode.SmoothTransformation)
                )
            return lbl

        logo_layout.addWidget(_make_logo_label(assets / "logo.png"))
        logo_layout.addWidget(_make_logo_label(assets / "text_logo.png"))
        layout.addWidget(logo_container)

        # ── Config section ────────────────────────────────────────
        config_scroll = QScrollArea()
        config_scroll.setWidgetResizable(True)
        config_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        config_scroll.setStyleSheet(
            "QScrollArea { border:none; background:transparent; }"
            "QScrollBar:vertical { width:4px; background:transparent; }"
            f"QScrollBar::handle:vertical {{ background:{self.C_BORDER}; border-radius:2px; }}"
        )

        config_inner = QWidget()
        config_inner.setStyleSheet(f"background:{self.C_SIDEBAR};")
        config_layout = QVBoxLayout(config_inner)
        config_layout.setContentsMargins(16, 16, 16, 16)
        config_layout.setSpacing(16)

        # ── Printer card ────────────────────────────────
        config_layout.addWidget(self._section_heading("PRINTER"))

        printer_card = QWidget()
        printer_card.setStyleSheet(self._card_style(8))
        pc_layout = QVBoxLayout(printer_card)
        pc_layout.setContentsMargins(12, 12, 12, 12)
        pc_layout.setSpacing(8)

        self.printer_combo = QComboBox()
        self.printer_combo.addItem("No printer detected")
        self.printer_combo.currentIndexChanged.connect(self.on_printer_selected)
        self.printer_combo.setStyleSheet(self._input_style())

        # calibration status pill
        self.calibration_status = QLabel("Not calibrated")
        self.calibration_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.calibration_status.setStyleSheet(
            f"background:#2a1a1a; color:{self.C_RED}; border:1px solid #5a2a2a;"
            f"border-radius:12px; font-size:11px; font-weight:600; padding:4px 10px;"
        )

        scan_btn = QPushButton("Scan for Printers")
        scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        scan_btn.setStyleSheet(self._btn_secondary())
        scan_btn.clicked.connect(self.scan_for_printers)

        calibrate_btn = QPushButton("Calibrate Printer")
        calibrate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        calibrate_btn.setStyleSheet(self._btn_primary())
        calibrate_btn.clicked.connect(self.calibrate_printer)

        pc_layout.addWidget(self.printer_combo)
        pc_layout.addWidget(self.calibration_status)
        pc_layout.addWidget(scan_btn)
        pc_layout.addWidget(calibrate_btn)
        config_layout.addWidget(printer_card)

        # ── Connection card ─────────────────────────────
        config_layout.addWidget(self._section_heading("API CONNECTION"))

        conn_card = QWidget()
        conn_card.setStyleSheet(self._card_style(8))
        cc_layout = QVBoxLayout(conn_card)
        cc_layout.setContentsMargins(12, 12, 12, 12)
        cc_layout.setSpacing(8)

        # connection status pill
        self.connection_status = QLabel("Disconnected")
        self.connection_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.connection_status.setStyleSheet(
            f"background:#2a1a1a; color:{self.C_RED}; border:1px solid #5a2a2a;"
            f"border-radius:12px; font-size:11px; font-weight:600; padding:4px 10px;"
        )

        url_lbl = QLabel("SERVER URL")
        url_lbl.setStyleSheet(self._label_style(small=True))
        self.api_url_input = QLineEdit(self.api_base_url)
        self.api_url_input.setPlaceholderText("https://example.com")
        self.api_url_input.setStyleSheet(self._input_style())
        self.api_url_input.textChanged.connect(self.on_api_url_changed)

        connect_btn = QPushButton("Test Connection")
        connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        connect_btn.setStyleSheet(self._btn_secondary())
        connect_btn.clicked.connect(self.test_api_connection)

        cc_layout.addWidget(self.connection_status)
        cc_layout.addWidget(url_lbl)
        cc_layout.addWidget(self.api_url_input)
        cc_layout.addWidget(connect_btn)
        config_layout.addWidget(conn_card)

        config_layout.addStretch()
        config_scroll.setWidget(config_inner)
        layout.addWidget(config_scroll, stretch=1)

        # ── Bottom status strip ───────────────────────────────────
        status_strip = QWidget()
        status_strip.setFixedHeight(44)
        status_strip.setStyleSheet(
            f"background:{self.C_SURFACE}; border-top:1px solid {self.C_BORDER};"
        )
        ss_layout = QVBoxLayout(status_strip)
        ss_layout.setContentsMargins(14, 0, 14, 0)
        ss_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.header_connection_status = QLabel("● Disconnected")
        self.header_connection_status.setStyleSheet(
            f"color:{self.C_RED}; font-size:10px; font-weight:600;"
        )
        self.header_printer_status = QLabel("⬡  No printer")
        self.header_printer_status.setStyleSheet(
            f"color:{self.C_TEXT_DIM}; font-size:10px;"
        )

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        status_row.addWidget(self.header_connection_status)
        status_row.addStretch()
        status_row.addWidget(self.header_printer_status)
        ss_layout.addLayout(status_row)
        layout.addWidget(status_strip)

        return sidebar

    def _section_heading(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color:{self.C_TEXT_DIM}; font-size:9px; font-weight:700;"
            f"letter-spacing:1.2px; background:transparent; border:none;"
        )
        return lbl

    # ── Main content area ─────────────────────────────────────────
    def _build_content(self) -> QWidget:
        content = QWidget()
        content.setStyleSheet(f"background:{self.C_BG};")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(14)

        # ── Top bar ──────────────────────────────────────────────
        top_bar = self._build_top_bar()
        layout.addWidget(top_bar)

        # thin divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setFixedHeight(1)
        div.setStyleSheet(f"background:{self.C_BORDER}; border:none;")
        layout.addWidget(div)

        # ── Queue panel ──────────────────────────────────────────
        layout.addWidget(self._build_queue_panel(), stretch=1)

        return content

    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet("background:transparent;")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(10)

        title = QLabel("Print Queue")
        title.setStyleSheet(
            f"color:{self.C_TEXT}; font-size:20px; font-weight:700; background:transparent;"
        )
        bar_layout.addWidget(title)
        bar_layout.addStretch()

        refresh_btn = QPushButton("↻   Refresh")
        refresh_btn.setFixedSize(110, 36)
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setStyleSheet(self._btn_secondary())
        refresh_btn.clicked.connect(self.fetch_pending_requests)
        bar_layout.addWidget(refresh_btn)

        return bar
    
    # (create_header removed — replaced by _build_sidebar / _build_top_bar)
    
    # (create_printer_panel removed — replaced by _build_sidebar)
    
    def _build_queue_panel(self) -> QWidget:
        """Build the print queue panel (right / main content area)."""
        panel = QWidget()
        panel.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # ── Table ────────────────────────────────────────────────
        self.requests_table = QTableWidget()
        self.requests_table.setColumnCount(6)
        self.requests_table.setHorizontalHeaderLabels(
            ["ID", "Source", "Created By", "Labels", "Created At", ""]
        )
        hdr = self.requests_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.requests_table.setColumnWidth(0, 52)
        self.requests_table.setColumnWidth(3, 70)
        self.requests_table.setColumnWidth(4, 155)
        self.requests_table.setColumnWidth(5, 110)
        self.requests_table.verticalHeader().setVisible(False)
        self.requests_table.setShowGrid(False)
        self.requests_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.requests_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.requests_table.setAlternatingRowColors(False)
        self.requests_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.requests_table.verticalHeader().setDefaultSectionSize(46)
        self.requests_table.setStyleSheet(f"""
            QTableWidget {{
                background:{self.C_SURFACE};
                border:1px solid {self.C_BORDER};
                border-radius:8px;
                color:{self.C_TEXT};
                font-size:12px;
                outline:none;
                gridline-color:transparent;
            }}
            QTableWidget::item {{
                padding:0 12px;
                border-bottom:1px solid {self.C_BORDER};
            }}
            QTableWidget::item:selected {{
                background:{self.C_SURFACE2};
                color:{self.C_GOLD};
            }}
            QHeaderView::section {{
                background:{self.C_SURFACE};
                color:{self.C_TEXT_DIM};
                font-size:10px; font-weight:700;
                letter-spacing:0.8px;
                padding:10px 12px;
                border:none;
                border-bottom:1px solid {self.C_BORDER};
            }}
            QScrollBar:vertical {{
                width:6px; background:transparent;
            }}
            QScrollBar::handle:vertical {{
                background:{self.C_BORDER}; border-radius:3px;
            }}
        """)
        layout.addWidget(self.requests_table, stretch=1)

        # ── Detail card ──────────────────────────────────────────
        detail_card = QWidget()
        detail_card.setFixedHeight(130)
        detail_card.setStyleSheet(
            f"background:{self.C_SURFACE}; border:1px solid {self.C_BORDER}; border-radius:8px;"
        )
        dc_layout = QVBoxLayout(detail_card)
        dc_layout.setContentsMargins(14, 10, 14, 10)
        dc_layout.setSpacing(4)

        detail_heading = QLabel("REQUEST DETAILS")
        detail_heading.setStyleSheet(
            f"color:{self.C_TEXT_DIM}; font-size:9px; font-weight:700;"
            f"letter-spacing:1.1px; background:transparent; border:none;"
        )
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setFrameShape(QFrame.Shape.NoFrame)
        self.details_text.setStyleSheet(
            f"background:transparent; color:{self.C_TEXT_DIM};"
            f"font-family:'Courier New',monospace; font-size:11px; border:none;"
        )
        dc_layout.addWidget(detail_heading)
        dc_layout.addWidget(self.details_text)
        layout.addWidget(detail_card)

        # ── Progress bar ─────────────────────────────────────────
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background:{self.C_SURFACE2};
                border:none; border-radius:3px;
            }}
            QProgressBar::chunk {{
                background:{self.C_GOLD}; border-radius:3px;
            }}
        """)
        layout.addWidget(self.progress_bar)

        return panel
    
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

            if self.last_selected_printer and self.last_selected_printer in printers:
                index = self.printer_combo.findText(self.last_selected_printer)
                if index >= 0:
                    self.printer_combo.setCurrentIndex(index)
    
    def on_printer_selected(self, index: int):
        """Handle printer selection."""
        if index > 0:  # Skip placeholder
            self.selected_printer = self.printer_combo.currentText()
            self.last_selected_printer = self.selected_printer
            self.save_settings()
            self.status_bar.showMessage(f"Selected printer: {self.selected_printer}")
            self.printer_calibrated = False
            self.calibration_status.setText("Not calibrated")
            self.calibration_status.setStyleSheet(
                f"background:#2a1a1a; color:{self.C_RED}; border:1px solid #5a2a2a;"
                f"border-radius:12px; font-size:11px; font-weight:600; padding:4px 10px;"
            )
            self.header_printer_status.setText(
                f"⬡  {self.selected_printer.split('/')[-1].upper()}"
            )
            self.header_printer_status.setStyleSheet(
                f"color:{self.C_ORANGE}; font-size:10px;"
            )
        else:
            self.selected_printer = None
            self.header_printer_status.setText("⬡  No printer")
            self.header_printer_status.setStyleSheet(
                f"color:{self.C_TEXT_DIM}; font-size:10px;"
            )
    
    def calibrate_printer(self):
        """Calibrate printer and print test label."""
        if not self.selected_printer:
            QMessageBox.warning(self, "No Printer", "Please select a printer first.")
            return

        if self.calibration_job and self.calibration_job.isRunning():
            QMessageBox.information(self, "Calibration In Progress", "Calibration is already running.")
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
            
            self.calibration_job = PrintJob(self.selected_printer, [test_item])
            self.calibration_job.finished.connect(self.on_test_print_finished)
            self.calibration_job.start()
            
            self.status_bar.showMessage("Calibrating printer...")
            
        except Exception as e:
            QMessageBox.critical(self, "Calibration Error", f"Failed to calibrate: {e}")
    
    def on_test_print_finished(self, success: bool, message: str):
        """Handle test print completion."""
        self.calibration_job = None
        if success:
            reply = QMessageBox.question(
                self,
                "Test Print",
                "Test label printed. Does it look correct?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.printer_calibrated = True
                self.calibration_status.setText("Calibrated")
                self.calibration_status.setStyleSheet(
                    f"background:#0f2a1a; color:{self.C_GREEN}; border:1px solid #1a5a2a;"
                    f"border-radius:12px; font-size:11px; font-weight:600; padding:4px 10px;"
                )
                self.status_bar.showMessage("Printer calibrated successfully")
                self.header_printer_status.setText(
                    f"✓  {self.selected_printer.split('/')[-1].upper()}"
                )
                self.header_printer_status.setStyleSheet(
                    f"color:{self.C_GREEN}; font-size:10px;"
                )
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
        self.check_api_connection(show_dialogs=True, fetch_queue_on_success=True)
    
    def on_api_url_changed(self, text: str):
        """Handle API URL change."""
        self.api_base_url = text.strip()
        self.save_settings()
    
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
            def _cell(text: str, align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft) -> QTableWidgetItem:
                item = QTableWidgetItem(text)
                item.setTextAlignment(align)
                return item

            self.requests_table.setItem(row, 0, _cell(
                str(request.get("id", "")),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
            ))
            source = request.get("source", "").replace("_", " ").title()
            self.requests_table.setItem(row, 1, _cell(source))
            self.requests_table.setItem(row, 2, _cell(request.get("created_by_username", "")))
            self.requests_table.setItem(row, 3, _cell(
                str(request.get("total_labels", 0)),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
            ))

            created_at = request.get("created_at", "")
            if created_at:
                try:
                    dt_obj = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    created_at = dt_obj.strftime("%d %b %Y  %H:%M")
                except Exception:
                    pass
            self.requests_table.setItem(row, 4, _cell(created_at))

            print_btn = QPushButton("Print")
            print_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            print_btn.setStyleSheet(self._btn_primary())
            print_btn.clicked.connect(lambda checked, r=request: self.print_request(r))
            # Wrap in a widget so padding looks right
            btn_wrap = QWidget()
            btn_wrap.setStyleSheet(f"background:{self.C_SURFACE};")
            bw_layout = QHBoxLayout(btn_wrap)
            bw_layout.setContentsMargins(8, 5, 8, 5)
            bw_layout.addWidget(print_btn)
            self.requests_table.setCellWidget(row, 5, btn_wrap)

        if self.pending_requests:
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
    app.setStyle("Fusion")

    # Inter / system sans-serif fallback chain
    font = QFont("Inter")
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setPointSize(10)
    app.setFont(font)

    window = BaytAlEmiratiPrinterApp()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
