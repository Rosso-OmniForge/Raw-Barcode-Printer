# Label Alignment Fix - Summary

## Problem
Labels were printing misaligned (sliding off) and skipping labels during printing.

## Root Cause
Missing critical TSPL printer calibration commands:
- **DIRECTION** - Tells printer the orientation
- **REFERENCE** - Sets the label reference point for alignment

Without these commands, the printer can lose track of:
1. Where each label starts
2. The gap between labels
3. Proper alignment of content on the label

## Solution Applied

### 1. Added Calibration Commands to All Labels
Every label now includes:
```tspl
SIZE 40 mm,30 mm
GAP 2 mm,0
DIRECTION 0      ← NEW: Sets print direction
REFERENCE 0,0    ← NEW: Sets reference point
CLS
[rest of label content]
PRINT 1
```

### 2. Added `calibrate_printer()` Method
New function that sends calibration sequence to printer before printing batches.

### 3. Added Manual Calibration Option
Main menu now includes option 7 to manually calibrate the printer when needed.

### 4. Auto-Calibration on First Batch
The printer automatically calibrates when starting the first batch of labels.

## Testing Instructions

1. **Run the program:**
   ```bash
   python3 label_printer.py
   ```

2. **Manual calibration test:**
   - Select option 7 (Calibrate printer)
   - Wait for confirmation
   - Select option 1 (Print single test label)
   - Check if label is properly aligned

3. **Full test:**
   - Select option 2 (Print test batch)
   - Check if all 5 labels + stock count label align properly
   - Verify no labels are skipped

4. **If alignment is still off:**
   - Check label roll is properly loaded
   - Ensure gap sensor is clean
   - Verify label size is exactly 40mm x 30mm
   - Make sure gap is 2mm between labels

## Files Modified
- `label_printer.py` - Updated TSPL generation and added calibration

## Files Created
- `test_diagnostics.py` - CSV parsing diagnostic tool
- `test_tspl_output.py` - TSPL command comparison tool

## Next Steps
Test with actual printer to confirm alignment is fixed. If issues persist, may need to adjust:
- GAP value (if gap between labels is different)
- REFERENCE coordinates (if content needs shifting)
- Add OFFSET command if persistent misalignment occurs
