#!/usr/bin/env python3
"""
Test script for Step 1: Core Hotkey Infrastructure

Tests:
1. Platform bindings work (clipboard + hotkey registration)
2. Field selector popup works
3. Manager orchestrates capture → popup → callback

Usage:
    python test_step1_hotkey.py
    
Then:
1. Copy some text to clipboard (Ctrl+C)
2. Press Ctrl+Shift+E (the hotkey)
3. Field selector popup should appear
4. Select a field
5. Check console output for success messages
"""
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from hotkey.manager import HotkeyManager, HotkeyConfig
from hotkey.models import HotkeyEvent


def test_hotkey_capture():
    """Test the complete hotkey → capture → popup workflow."""
    
    print("\n" + "="*60)
    print("STEP 1: Core Hotkey Infrastructure Test")
    print("="*60)
    
    print("\n📋 Instructions:")
    print("1. Copy some text to your clipboard (e.g., 'Hello World')")
    print("2. Press Ctrl+Shift+E (the hotkey)")
    print("3. A popup should appear - select a field")
    print("4. Watch for success output below\n")
    
    # Create config
    config = HotkeyConfig(
        hotkey_combo="ctrl+shift+e",
        api_base_url="http://localhost:8000"
    )
    
    # Create manager
    manager = HotkeyManager(config)
    
    # Set up callback
    captured_events = []
    
    def on_event(event: HotkeyEvent):
        """Callback when hotkey + field selection completes."""
        print(f"\n✅ SUCCESS! Captured event:")
        print(f"   Text: {event.selected_text[:100]}..." if len(event.selected_text) > 100 else f"   Text: {event.selected_text}")
        print(f"   Field: {event.selected_field.name} ({event.selected_field.path})")
        captured_events.append(event)
    
    # Start listening
    print("🚀 Starting hotkey listener...\n")
    try:
        manager.start(on_event)
        
        # Listen for 60 seconds
        print("⏰ Waiting for hotkey (60 second timeout)...\n")
        for i in range(60):
            time.sleep(1)
            if captured_events:
                print("\n✨ Test PASSED! Hotkey system working correctly.\n")
                return True
        
        print("⏱️  Timeout - no hotkey press detected.")
        return False
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        return False
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        manager.stop()


def test_platform_bindings():
    """Test platform bindings setup."""
    print("\n" + "="*60)
    print("Testing Platform Bindings...")
    print("="*60)
    
    try:
        from hotkey.platform_bindings import get_platform_bindings
        bindings = get_platform_bindings()
        bindings.ensure_setup()
        print("✓ Platform bindings initialized\n")
        return True
    except ImportError as e:
        print(f"❌ Import error (missing dependencies?): {e}")
        print("\nInstall with: pip install -e '.[hotkey]'\n")
        return False
    except Exception as e:
        print(f"❌ Error: {e}\n")
        return False


def test_field_loader():
    """Test field loading from config."""
    print("\n" + "="*60)
    print("Testing Field Loader...")
    print("="*60)
    
    try:
        from hotkey.popup_ui import FieldInfoLoader
        fields = FieldInfoLoader.load_fields()
        print(f"✓ Loaded {len(fields)} fields:")
        for field in fields:
            status = " (active)" if field.is_active else ""
            print(f"  - {field.name}{status}")
        print()
        return True
    except Exception as e:
        print(f"⚠️  Warning: {e}")
        print("  (This is OK if no fields exist yet)\n")
        return True


if __name__ == "__main__":
    try:
        # Test 1: Platform bindings
        if not test_platform_bindings():
            print("❌ Cannot proceed without platform bindings.\n")
            sys.exit(1)
        
        # Test 2: Field loader
        test_field_loader()
        
        # Test 3: Main hotkey capture test
        success = test_hotkey_capture()
        
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Test cancelled\n")
        sys.exit(0)
