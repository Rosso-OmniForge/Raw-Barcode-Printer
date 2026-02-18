# Print Manager - Complete Implementation Guide

## Overview

This document describes the complete Print Manager for Bayt Al Emirati, including auto-generation from procurement, manual print requests, and the desktop printing application.

---

## System Components

### 1. Database Schema

**New Tables:**
- `label_print_requests` - Stores print job batches
- `label_print_request_items` - Individual label items within each request

**Key Features:**
- Tracks status (pending/completed/cancelled)
- Links to procurement receipts for auto-generated requests
- Stores snapshot of product data at print time
- Records who created the request and when

### 2. Backend API

**Location:** `backend/app/routes/label_printing.py`

**Admin UI Endpoints:**
- `GET /admin/label-printing` - Main management page
- `GET /admin/label-printing/search` - Search products for manual print
- `POST /admin/label-printing/add-product` - Add product to print queue
- `POST /admin/label-printing/request/{id}/cancel` - Cancel a pending request

**API Endpoints (for desktop app):**
- `GET /admin/api/label-printing/pending` - List all pending requests
- `GET /admin/api/label-printing/request/{id}` - Get request details with items
- `POST /admin/api/label-printing/complete` - Mark request as completed

**Authentication:**
- Desktop app uses API key authentication via `X-API-Key` header
- Default key: `BAE-PRINTER-2026-SECURE-KEY` (⚠️ CHANGE IN PRODUCTION)

### 3. Auto-Generation Logic

**Location:** Modified in `backend/app/routes/procurement.py`

**Rules:**

When procurement is submitted:

```python
if qty_added > 0:
    if price_changed:
        # Price changed: Print ALL labels (existing stock + new)
        qty_to_print = new_qty
    else:
        # Price unchanged: Print only NEW labels
        qty_to_print = qty_added
```

**How it works:**
1. During procurement submission, system tracks:
   - Quantity added
   - Whether selling price changed
2. Creates `LabelPrintRequest` with source="procurement"
3. Adds `LabelPrintRequestItem` for each variant with calculated qty
4. All data is snapshotted (title, price, barcode, etc.)

### 4. Desktop Printer Application

**Location:** `printer/bayt_printer_app.py`

**Technologies:**
- PyQt6 for modern GUI
- Requests library for HTTP API calls
- Direct USB printing via `/dev/usb/lp*`

**Features:**
- ✅ Auto-discovery of USB label printers
- ✅ Printer calibration with test labels
- ✅ Auto-refresh pending requests every 30 seconds
- ✅ Live printing progress bar
- ✅ Branded Bayt Al Emirati interface
- ✅ API connection testing
- ✅ Detailed print job preview

---

## Installation & Setup

### Backend Setup

1. **Run Database Migrations**
   ```bash
   cd backend
   # Migrations run automatically on startup
   # Or force with: python -c "from app.migrations import ensure_schema; from app.db import engine; ensure_schema(engine)"
   ```

2. **Verify Routes Registered**
   - Check `backend/app/main.py` includes `label_printing` router
   - Should see: `app.include_router(label_printing.router)`

3. **Access Admin UI**
   - Navigate to: http://localhost:8000/admin/label-printing
   - Check navigation menu for "🖨️ Label Printing" link

### Desktop App Setup

1. **System Requirements**
   ```bash
   # Debian 13 Trixie
   sudo apt-get update
   sudo apt-get install python3 python3-pip python3-venv python3-pyqt6 libusb-1.0-0
   ```

2. **Install Application**
   ```bash
   cd printer
   chmod +x install_printer_app.sh
   ./install_printer_app.sh
   ```

3. **Configure API Connection**
   - Edit `printer/bayt_printer_app.py` line 20-21:
     ```python
     API_BASE_URL = "http://your-server:8000"  # Update this
     API_KEY = "YOUR-SECURE-API-KEY"            # Update this
     ```
   
4. **Update Backend API Key**
   - Edit `backend/app/routes/label_printing.py` line 307:
     ```python
     PRINTER_API_KEY = "YOUR-SECURE-API-KEY"  # Must match desktop app
     ```

5. **Launch Application**
   ```bash
   ./launch_printer.sh
   ```

---

## Usage Workflows

### Scenario 1: Auto-Print from Procurement

1. **User adds stock via Procurement**
   - Adds products with variants
   - Sets quantities and prices
   - Submits procurement receipt

2. **System auto-creates print request**
   - If price changed → queues labels for ALL stock
   - If price same → queues labels for NEW stock only

3. **Desktop app picks up request**
   - Auto-refreshes every 30 seconds
   - Shows in "Pending Print Requests" table

4. **User prints labels**
   - Reviews request details
   - Clicks "🖨️ Print" button
   - Monitors progress bar
   - System auto-marks as completed

### Scenario 2: Manual Print for Damaged Labels

1. **Admin needs to replace damaged stickers**
   - Goes to Admin → Label Printing
   - Clicks "+ Add Manual Print"

2. **Search for product**
   - Enters search term (title, SKU, barcode, etc.)
   - Finds product in results

3. **Add to queue**
   - Clicks "Add All Variants to Queue"
   - Can specify quantities per variant
   - System creates manual print request

4. **Desktop app prints**
   - Same workflow as auto-generated requests

---

## Label Format

**Label Size:** 40mm x 30mm with 2mm gap

**Label Contents (top to bottom):**
1. Product title (truncated to 30 chars, font 3)
2. Variant label - color + size (font 2)
3. Code39 barcode - centered (60 dots high)
4. Price - large, centered (font 4, 2x scale)
5. SKU - small text at bottom (font 1)

**TSPL Commands Generated:**
```tspl
SIZE 40 mm, 30 mm
GAP 2 mm, 0 mm
DIRECTION 0
CLS
TEXT {x},10,"3",0,1,1,"{title}"
TEXT {x},40,"2",0,1,1,"{variant}"
BARCODE {x},70,"39",60,1,0,2,4,"{code39}"
TEXT {x},150,"4",0,2,2,"{price}"
TEXT {x},210,"1",0,1,1,"{sku}"
PRINT 1
```

---

## API Examples

### Fetch Pending Requests

```bash
curl -H "X-API-Key: BAE-PRINTER-2026-SECURE-KEY" \
     http://localhost:8000/admin/api/label-printing/pending
```

**Response:**
```json
[
  {
    "id": 1,
    "status": "pending",
    "source": "procurement",
    "created_by_username": "admin",
    "total_labels": 45,
    "labels_printed": 0,
    "note": "Auto-generated from procurement receipt #INV-001",
    "created_at": "2026-02-16T10:30:00Z"
  }
]
```

### Get Request Details

```bash
curl -H "X-API-Key: BAE-PRINTER-2026-SECURE-KEY" \
     http://localhost:8000/admin/api/label-printing/request/1
```

**Response:**
```json
{
  "request": {
    "id": 1,
    "status": "pending",
    "total_labels": 45,
    ...
  },
  "items": [
    {
      "id": 1,
      "sku": "BAE-001-BLK-M",
      "title": "Premium Cotton T-Shirt",
      "variant_label": "Black M",
      "price_cents": 15900,
      "currency": "ZAR",
      "code39": "BAE001BLKM",
      "barcode_type": "",
      "barcode_value": "",
      "qty_to_print": 5
    }
  ]
}
```

### Mark as Completed

```bash
curl -X POST \
     -H "X-API-Key: BAE-PRINTER-2026-SECURE-KEY" \
     -H "Content-Type: application/json" \
     -d '{"request_id": 1}' \
     http://localhost:8000/admin/api/label-printing/complete
```

---

## Troubleshooting

### Backend Issues

**Print requests not being created:**
- Check procurement submission completes successfully
- Verify migrations ran (`label_print_requests` table exists)
- Check logs for errors during procurement submit

**API returns 401 Unauthorized:**
- Verify API key matches between desktop app and backend
- Check `X-API-Key` header is being sent correctly

### Desktop App Issues

**Printer not found:**
```bash
# Check USB devices
ls -la /dev/usb/lp*

# Add user to lp group
sudo usermod -a -G lp $USER

# Reconnect printer and restart app
```

**Connection failed:**
- Verify backend server is running
- Test with curl: `curl http://your-server:8000/admin`
- Check firewall allows connections on port 8000
- Ensure API URL in app matches server

**Labels misaligned:**
- Run calibration: Click "Calibrate & Test Print"
- Verify label size is exactly 40mm x 30mm
- Check gap setting (should be 2mm)
- Adjust `horizontal_shift_dots` if needed (line 273 in app)

**PyQt6 not found:**
```bash
# Install system package
sudo apt-get install python3-pyqt6

# Or install via pip in venv
source venv/bin/activate
pip install PyQt6
```

---

## Security Recommendations

### Production Deployment

1. **Change API Key**
   ```bash
   # Generate secure key
   openssl rand -base64 32
   ```
   Update in both:
   - `backend/app/routes/label_printing.py`
   - `printer/bayt_printer_app.py`

2. **Use Environment Variables**
   ```python
   # In backend
   import os
   PRINTER_API_KEY = os.getenv("PRINTER_API_KEY", "default-key")
   
   # In desktop app
   API_KEY = os.getenv("BAE_PRINTER_API_KEY", "default-key")
   ```

3. **Enable HTTPS**
   - Use nginx/Apache reverse proxy
   - Install SSL certificate
   - Update desktop app URL to `https://`

4. **Restrict API Access**
   - Add IP whitelisting
   - Use VPN for remote printing
   - Implement rate limiting

---

## File Locations

### Backend Files
```
backend/app/
├── models.py                          # Added LabelPrintRequest models
├── migrations.py                      # Added table creation
├── main.py                            # Registered label_printing router
└── routes/
    ├── label_printing.py              # NEW: All label printing routes
    └── procurement.py                 # Modified: Auto-create print requests

backend/app/templates/
├── label_printing.html                # NEW: Main admin page
├── label_printing_search.html         # NEW: Product search page
└── layout.html                        # Modified: Added nav link
```

### Desktop App Files
```
printer/
├── bayt_printer_app.py               # NEW: Main PyQt6 application
├── requirements_app.txt              # NEW: Python dependencies
├── install_printer_app.sh            # NEW: Installation script
├── launch_printer.sh                 # NEW: Launch script
├── README_APP.md                     # NEW: App documentation
└── label_printer.py                  # Existing: Core print logic
```

---

## Testing Checklist

- [ ] Database migrations run successfully
- [ ] Backend starts without errors
- [ ] Admin UI accessible at `/admin/label-printing`
- [ ] Navigation link appears in sidebar
- [ ] Can search for products
- [ ] Manual print request creation works
- [ ] Procurement creates auto print requests
- [ ] Desktop app starts successfully
- [ ] Printer auto-discovery works
- [ ] Test calibration prints correctly
- [ ] API connection test succeeds
- [ ] Pending requests load in desktop app
- [ ] Print job executes successfully
- [ ] Request marked as completed after printing
- [ ] Labels print correctly formatted

---

## Future Enhancements

### Potential Improvements

1. **Batch Management**
   - Combine multiple requests into single print batch
   - Print queue prioritization

2. **Label Templates**
   - Multiple label sizes (30mm, 40mm, 50mm)
   - Custom templates per product type
   - Logo/brand images on labels

3. **Print History**
   - Detailed print logs
   - Reprint capability from history
   - Print analytics dashboard

4. **Multi-Printer Support**
   - Assign requests to specific printers
   - Load balancing across printers
   - Printer status monitoring

5. **Advanced Features**
   - QR code support
   - Multi-language labels
   - Dynamic pricing (sale stickers)
   - Shelf talkers/signage

6. **Mobile App**
   - React Native/Flutter app for tablets
   - Print from mobile device
   - Scan and reprint damaged labels

---

## Support

For issues or questions:
1. Check this documentation first
2. Review logs: `backend/app.log` and desktop app console
3. Test with curl commands to isolate issues
4. Contact Bayt Al Emirati IT team

---

**Version:** 1.0.0  
**Last Updated:** February 16, 2026  
**Author:** Bayt Al Emirati Development Team
