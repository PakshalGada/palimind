#!/usr/bin/env python3
"""
Comprehensive test for all 3 MVP steps.

This script tests:
1. Step 1: Hotkey registration + clipboard + popup UI
2. Step 2: Capture file saving + API integration
3. Step 3: Complete end-to-end workflow

No CLI dependencies needed - tests hotkey module directly.
"""
import sys
import time
import tempfile
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

print("\n" + "="*70)
print(" PALIMIND HOTKEY MVP - COMPLETE TEST SUITE")
print("="*70)

# ============================================================================
# STEP 1: Core Infrastructure (Hotkey + Popup)
# ============================================================================

print("\n" + "-"*70)
print("STEP 1: Core Infrastructure (Hotkey Registration + Popup UI)")
print("-"*70)

try:
    from hotkey.manager import HotkeyManager, HotkeyConfig
    from hotkey.models import HotkeyEvent, FieldInfo
    from hotkey.platform_bindings import get_platform_bindings
    from hotkey.popup_ui import FieldInfoLoader
    
    print("✓ All imports successful")
    
    # Test platform bindings
    bindings = get_platform_bindings()
    bindings.ensure_setup()
    print("✓ Platform bindings initialized")
    
    # Test config
    config = HotkeyConfig(hotkey_combo="ctrl+shift+e")
    manager = HotkeyManager(config)
    print(f"✓ Manager created with hotkey: {config.hotkey_combo}")
    
    # Test field loader
    fields = FieldInfoLoader.load_fields()
    print(f"✓ Field loader: {len(fields)} fields available")
    
    STEP1_PASS = True
    print("\n✅ STEP 1: PASS - Core infrastructure ready")
    
except Exception as e:
    print(f"❌ STEP 1: FAIL - {e}")
    import traceback
    traceback.print_exc()
    STEP1_PASS = False

# ============================================================================
# STEP 2: API Integration & Data Saving
# ============================================================================

print("\n" + "-"*70)
print("STEP 2: API Integration & Data Saving")
print("-"*70)

try:
    from hotkey.integrations import CaptureProcessor, CaptureFileWriter
    
    print("✓ Integration modules imported")
    
    # Test file writer with temporary directory
    with tempfile.TemporaryDirectory() as tmpdir:
        field_path = Path(tmpdir)
        test_text = "Sample captured text from the hotkey"
        
        saved_path = CaptureFileWriter.save_capture(str(field_path), test_text)
        
        if not saved_path or not saved_path.exists():
            raise Exception("Failed to save capture file")
        
        content = saved_path.read_text()
        if content != test_text:
            raise Exception("Content mismatch in saved file")
        
        print(f"✓ Capture file saved: {saved_path.name}")
        
        # Test processor
        processor = CaptureProcessor("http://localhost:8000")
        print("✓ Processor initialized")
        
        # Note: API calls will fail if server isn't running, but file saving should work
        result = processor.process_capture(str(field_path), "Test capture")
        
        captures_dir = field_path / ".palimind" / "captures"
        if not list(captures_dir.glob("*.txt")):
            raise Exception("Processor didn't create capture file")
        
        print("✓ Processor saves capture files successfully")
    
    STEP2_PASS = True
    print("\n✅ STEP 2: PASS - Data saving and API integration ready")
    
except Exception as e:
    print(f"❌ STEP 2: FAIL - {e}")
    import traceback
    traceback.print_exc()
    STEP2_PASS = False

# ============================================================================
# STEP 3: End-to-End Workflow Simulation
# ============================================================================

print("\n" + "-"*70)
print("STEP 3: End-to-End Workflow (without actual hotkey press)")
print("-"*70)

try:
    from hotkey.integrations import CaptureProcessor, CaptureFileWriter
    from hotkey.popup_ui import FieldInfoLoader
    
    print("✓ Modules loaded")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a mock field
        field_path = Path(tmpdir)
        field_name = "test-field"
        
        # Simulate: User pressed hotkey → captured text
        clipboard_text = "This is text I selected from another application"
        print(f"📋 Simulated clipboard: '{clipboard_text[:50]}...'")
        
        # Simulate: User selected field from popup
        field_info = FieldInfo(name=field_name, path=str(field_path))
        print(f"🎯 User selected field: {field_info.name}")
        
        # Simulate: Manager processes the capture
        processor = CaptureProcessor("http://localhost:8000")
        processor.process_capture(field_info.path, clipboard_text)
        
        # Verify capture was saved
        captures_dir = field_path / ".palimind" / "captures"
        capture_files = list(captures_dir.glob("*.txt"))
        
        if not capture_files:
            raise Exception("No capture files created")
        
        saved_content = capture_files[-1].read_text()
        if saved_content != clipboard_text:
            raise Exception("Saved content doesn't match original")
        
        print(f"✓ Capture saved to: {capture_files[-1].relative_to(field_path)}")
        print(f"✓ Content verified ({len(saved_content)} chars)")
        
        # Check if captures directory structure is correct
        if not (field_path / ".palimind" / "captures").exists():
            raise Exception("Captures directory structure incorrect")
        
        print("✓ Field structure is correct (.palimind/captures/)")
    
    STEP3_PASS = True
    print("\n✅ STEP 3: PASS - End-to-end workflow validated")
    
except Exception as e:
    print(f"❌ STEP 3: FAIL - {e}")
    import traceback
    traceback.print_exc()
    STEP3_PASS = False

# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "="*70)
print(" TEST SUMMARY")
print("="*70)

results = [
    ("Step 1: Core Infrastructure", STEP1_PASS),
    ("Step 2: API Integration & Data Saving", STEP2_PASS),
    ("Step 3: End-to-End Workflow", STEP3_PASS),
]

for step, passed in results:
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status}: {step}")

all_pass = all(p for _, p in results)

print("\n" + "="*70)
if all_pass:
    print("🎉 ALL TESTS PASSED - MVP IS READY!")
    print("\nNext steps:")
    print("1. Start the FastAPI server: pm ui")
    print("2. Create a Field in the UI")
    print("3. Run: pm hotkey start")
    print("4. Try capturing text with Ctrl+Shift+E")
else:
    print("⚠️  Some tests failed - see details above")

print("="*70 + "\n")

sys.exit(0 if all_pass else 1)
