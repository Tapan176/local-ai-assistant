"""
Verification Script for Voice Integration.
Mocks VoiceInterface and Orchestrator to verify speak() is called.
"""
import sys
import threading
import time
import queue
from unittest.mock import MagicMock

# Add src to path
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from src.service.background_service import BackgroundService

def test_voice_integration():
    print("\n[Voice Integration Test]")
    
    # Mock Orchestrator
    mock_orch = MagicMock()
    mock_orch.process.return_value = "This is a spoken response."
    
    # Mock Voice Interface
    mock_voice = MagicMock()
    
    # Mock Input Provider
    input_queue = queue.Queue()
    input_queue.put("Hello")
    
    def mock_input_provider():
        try:
            return input_queue.get(timeout=1)
        except queue.Empty:
            time.sleep(1) # Prevent busy loop in input thread
            return None

    # Initialize Service with Voice
    service = BackgroundService(mock_orch, mock_input_provider, voice_interface=mock_voice)
    
    # Inject input directly into service queue to bypass input thread timing issues
    service.input_queue.put("Hello")
    
    # Run one tick
    print("  Running tick...")
    service.tick()
    
    # Verify
    print(f"  Orchestrator called: {mock_orch.process.called}")
    print(f"  Voice speak called: {mock_voice.speak.called}")
    
    if mock_voice.speak.called:
        args = mock_voice.speak.call_args[0]
        print(f"  Spoken text: '{args[0]}'")
        if args[0] == "This is a spoken response.":
            print("  ✅ Voice output verified.")
        else:
            print("  ❌ Wrong text spoken.")
    else:
        print("  ❌ Voice speak NOT called.")

if __name__ == "__main__":
    test_voice_integration()
