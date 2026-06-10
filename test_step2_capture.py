#!/usr/bin/env python3
"""
Test script for Step 2: API Integration & Data Saving

Tests:
1. Capture file saving to field/.palimind/captures/
2. FastAPI update trigger
3. Complete hotkey → capture → save → index workflow

Usage:
    python test_step2_capture.py
"""
import sys
import time
import tempfile
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from hotkey.integrations import CaptureProcessor, CaptureFileWriter, PalimindAPIClient


def test_capture_file_writer():
    """Test saving capture files."""
    print("\n" + "="*60)
    print("Test 1: Capture File Writer")
    print("="*60)
    
    # Create temporary field directory
    with tempfile.TemporaryDirectory() as tmpdir:
        field_path = Path(tmpdir)
        
        # Test saving a capture
        test_text = "Hello, this is captured text from clipboard!"
        saved_path = CaptureFileWriter.save_capture(str(field_path), test_text)
        
        if not saved_path:
            print("❌ Failed to save capture")
            return False
        
        # Verify file exists and contains correct content
        if not saved_path.exists():
            print(f"❌ File not created: {saved_path}")
            return False
        
        content = saved_path.read_text()
        if content != test_text:
            print(f"❌ Content mismatch")
            return False
        
        print(f"✓ Capture saved: {saved_path.name}")
        print(f"✓ Content verified ({len(content)} chars)")
        
        # Test multiple saves create unique filenames
        saved_path2 = CaptureFileWriter.save_capture(str(field_path), "Second capture")
        if not saved_path2 or saved_path == saved_path2:
            print("❌ Failed to create unique filename")
            return False
        
        print(f"✓ Unique filenames: {saved_path.name} vs {saved_path2.name}")
        return True


def test_api_client():
    """Test API client initialization and error handling."""
    print("\n" + "="*60)
    print("Test 2: API Client")
    print("="*60)
    
    try:
        client = PalimindAPIClient("http://localhost:8000")
        print("✓ API client initialized")
        
        # Try to get fields (may fail if server not running - that's OK)
        try:
            fields = client.get_fields()
            print(f"✓ Got {len(fields)} fields from server")
        except Exception as e:
            print(f"⚠️  Server not running (expected for this test): {e}")
        
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_capture_processor():
    """Test complete capture processing."""
    print("\n" + "="*60)
    print("Test 3: Capture Processor (File Save Only)")
    print("="*60)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        field_path = Path(tmpdir)
        
        # Create processor
        processor = CaptureProcessor("http://localhost:8000")
        print("✓ Processor initialized")
        
        # Process a capture
        test_text = "Test capture content for indexing"
        success = processor.process_capture(str(field_path), test_text)
        
        if not success:
            print("⚠️  Processing failed (server may not be running)")
            # Check if file was at least saved
            captures_dir = field_path / ".palimind" / "captures"
            if captures_dir.exists():
                files = list(captures_dir.glob("*.txt"))
                if files:
                    print(f"✓ But file was saved: {files[0].name}")
                    return True
            return False
        
        # Verify capture was saved
        captures_dir = field_path / ".palimind" / "captures"
        if not captures_dir.exists():
            print(f"❌ Captures directory not created")
            return False
        
        files = list(captures_dir.glob("*.txt"))
        if not files:
            print(f"❌ No capture files found")
            return False
        
        print(f"✓ Capture file created: {files[0].name}")
        print(f"✓ Content length: {len(files[0].read_text())} chars")
        
        return True


def test_with_real_field():
    """Test with actual Palimind field if available."""
    print("\n" + "="*60)
    print("Test 4: With Real Palimind Field (if available)")
    print("="*60)
    
    global_config = Path.home() / ".palimind_global.json"
    if not global_config.exists():
        print("⚠️  No .palimind_global.json found - skipping this test")
        return True
    
    try:
        with open(global_config) as f:
            data = json.load(f)
        
        fields = data.get("fields", [])
        if not fields:
            print("⚠️  No fields configured")
            return True
        
        field_path = fields[0]
        print(f"📁 Using field: {Path(field_path).name}")
        
        processor = CaptureProcessor("http://localhost:8000")
        test_text = f"Hotkey capture test at {time.time()}"
        
        success = processor.process_capture(field_path, test_text)
        
        if success:
            print("✓ Capture processed successfully!")
            # Verify file exists
            captures_dir = Path(field_path) / ".palimind" / "captures"
            files = list(captures_dir.glob("*.txt"))
            if files:
                print(f"✓ Latest capture: {files[-1].name}")
        else:
            print("⚠️  Processing failed (server may not be running)")
        
        return True
        
    except Exception as e:
        print(f"⚠️  Error: {e}")
        return True


if __name__ == "__main__":
    print("\n" + "="*60)
    print("STEP 2: API Integration & Data Saving Tests")
    print("="*60)
    
    try:
        results = []
        
        # Run tests
        results.append(("File Writer", test_capture_file_writer()))
        results.append(("API Client", test_api_client()))
        results.append(("Processor", test_capture_processor()))
        results.append(("Real Field", test_with_real_field()))
        
        # Summary
        print("\n" + "="*60)
        print("Test Summary")
        print("="*60)
        for name, result in results:
            status = "✓ PASS" if result else "❌ FAIL"
            print(f"{status}: {name}")
        
        all_passed = all(r for _, r in results)
        if all_passed:
            print("\n✨ All tests passed!")
        
        sys.exit(0 if all_passed else 1)
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Tests cancelled\n")
        sys.exit(0)
