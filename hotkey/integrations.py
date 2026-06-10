"""FastAPI integration client for Palimind hotkey capture."""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class PalimindAPIClient:
    """Client for communicating with Palimind FastAPI server."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        """
        Initialize API client.
        
        Args:
            base_url: Base URL of FastAPI server
        """
        if not HAS_REQUESTS:
            raise ImportError(
                "requests not installed. Install with: pip install -e '.[hotkey]'"
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = 5

    def get_fields(self) -> list[dict]:
        """
        Get available fields from server.
        
        Returns:
            List of field paths, or empty list if error
        """
        try:
            response = requests.get(
                f"{self.base_url}/api/fields",
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("fields", [])
        except Exception as e:
            print(f"⚠️  Error fetching fields: {e}")
            return []

    def update_field(self, field_path: str) -> bool:
        """
        Trigger index update for a field.
        
        Args:
            field_path: Path to field directory
            
        Returns:
            True if update triggered, False otherwise
        """
        try:
            # First set it as active
            response = requests.post(
                f"{self.base_url}/api/fields/set_active",
                json={"path": field_path},
                timeout=self.timeout,
            )
            response.raise_for_status()
            
            # Then trigger update
            response = requests.post(
                f"{self.base_url}/api/update",
                timeout=self.timeout,
            )
            response.raise_for_status()
            
            result = response.json()
            print(f"✓ Updated field: {result.get('indexed_files', 0)} files indexed")
            return True
        except Exception as e:
            print(f"⚠️  Error updating field: {e}")
            return False


class CaptureFileWriter:
    """Handle saving captured text to field directory."""

    @staticmethod
    def save_capture(field_path: str, text: str) -> Optional[Path]:
        """
        Save captured text as timestamped file in field's captures directory.
        
        Args:
            field_path: Path to field directory
            text: Text to save
            
        Returns:
            Path to saved file, or None if error
        """
        try:
            field = Path(field_path)
            if not field.is_dir():
                print(f"⚠️  Field directory not found: {field_path}")
                return None

            # Create captures directory
            captures_dir = field / ".palimind" / "captures"
            captures_dir.mkdir(parents=True, exist_ok=True)

            # Generate timestamped filename
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"{timestamp}_capture.txt"
            file_path = captures_dir / filename

            # Ensure unique filename if it already exists
            counter = 1
            while file_path.exists():
                filename = f"{timestamp}_capture_{counter}.txt"
                file_path = captures_dir / filename
                counter += 1

            # Save file
            file_path.write_text(text, encoding="utf-8")
            print(f"✓ Saved capture: {file_path}")
            
            return file_path

        except Exception as e:
            print(f"⚠️  Error saving capture: {e}")
            return None


class CaptureProcessor:
    """
    Orchestrate capture saving and indexing.
    
    Workflow:
    1. Save capture text to field/captures/
    2. Trigger API update to index new file
    """

    def __init__(self, api_base_url: str = "http://localhost:8000"):
        """
        Initialize capture processor.
        
        Args:
            api_base_url: Base URL of FastAPI server
        """
        self.api = PalimindAPIClient(api_base_url)
        self.writer = CaptureFileWriter()

    def process_capture(self, field_path: str, text: str) -> bool:
        """
        Process a text capture: save file and trigger indexing.
        
        Args:
            field_path: Path to target field
            text: Text to capture
            
        Returns:
            True if successful, False otherwise
        """
        print(f"\n📝 Processing capture...")
        print(f"   Field: {Path(field_path).name}")
        print(f"   Text length: {len(text)} chars")

        # Step 1: Save capture file
        saved_path = self.writer.save_capture(field_path, text)
        if not saved_path:
            return False

        # Step 2: Trigger field update
        print(f"🔄 Triggering index update...")
        success = self.api.update_field(field_path)

        if success:
            print(f"✨ Capture successfully indexed!")
        else:
            print(f"⚠️  Capture saved but indexing failed (will update manually)")

        return True


def get_capture_processor(api_base_url: str = "http://localhost:8000") -> CaptureProcessor:
    """Get a capture processor instance."""
    return CaptureProcessor(api_base_url)
