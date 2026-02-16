"""
Phase 18 Comprehensive Tests: Jarvis E2E
Tests the Event Loop, Predictive Intelligence, Smart Notifier, and Enhanced Voice.
"""
import pytest
import time
import shutil
import tempfile
import sys
import queue
from pathlib import Path
from unittest.mock import MagicMock, patch

# Adjust path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.orchestrator import Orchestrator
from src.service.background_service import BackgroundService
from src.intelligence.predictor import PredictiveIntelligence
from src.notifications.smart_notifier import SmartNotifier
from src.io.enhanced_voice import EnhancedVoiceInterface

@pytest.fixture
def test_env():
    """Setup temp data dir and orchestrator."""
    temp_dir = tempfile.mkdtemp()
    data_dir = Path(temp_dir)
    
    # Create dummy files if needed
    (data_dir / "user_profile.json").write_text("{}")
    
    orch = Orchestrator(data_dir)
    
    yield data_dir, orch
    
    shutil.rmtree(temp_dir)

class TestPredictiveIntelligence:
    def test_predict_next_action(self, test_env):
        data_dir, orch = test_env
        profile_mock = MagicMock()
        profile_mock.get_current_context.return_value = {
            "day_type": "weekday",
            "time_of_day": "evening"
        }
        profile_mock.get_upcoming_routines.return_value = []
        
        predictor = PredictiveIntelligence(data_dir, profile_mock)
        preds = predictor.predict_next_action()
        
        assert len(preds) > 0
        assert preds[0]["action"] == "log_experience"
        assert preds[0]["type"] == "pattern"

class TestSmartNotifier:
    def test_should_notify(self, test_env):
        data_dir, orch = test_env
        profile_mock = MagicMock()
        notifier = SmartNotifier(profile_mock)
        
        # 1. Critical always passes
        profile_mock.get_current_context.return_value = {"time_of_day": "night"}
        assert notifier.should_notify("system", "critical") is True
        
        # 2. Night filters low priority
        assert notifier.should_notify("finance", "low") is False
        
        # 3. Busy filters medium
        profile_mock.get_current_context.return_value = {
            "time_of_day": "day",
            "current_activity": "working"
        }
        assert notifier.should_notify("routine", "medium") is False
        assert notifier.should_notify("routine", "high") is True

class TestEnhancedVoice:
    def test_emotion_detection(self):
        voice = EnhancedVoiceInterface()
        assert voice.detector.detect("I am so happy!") == "happy"
        assert voice.detector.detect("This is terrible error") == "sad"
        assert voice.detector.detect("I am stressed and busy") == "stressed"
        assert voice.detector.detect("What is the time?") == "curious"

    def test_speak_personality(self):
        voice = EnhancedVoiceInterface()
        # We can't easily check engine properties on mock, but we verified code logic.
        # Just ensure no crash
        voice.speak_with_personality("Hello", "happy")

class TestBackgroundServiceEventLoop:
    def test_event_loop_processing(self, test_env):
        data_dir, orch = test_env
        
        # Mock input provider
        input_queue = ["hello", "profile stats"]
        def mock_input():
            if input_queue:
                return input_queue.pop(0)
            return None # Simulated EOF/End
            
        service = BackgroundService(orch, mock_input)
        
        # We don't want to start the separate thread as it blocks or races in test.
        # We will manually inject into queue and call tick()
        
        service.input_queue.put("test_command")
        
        # Mock Orchestrator.process
        with patch.object(orch, 'process', return_value="Response") as mock_process:
            service.tick()
            mock_process.assert_called_with("test_command")

    def test_autonomous_tasks_trigger(self, test_env):
        data_dir, orch = test_env
        service = BackgroundService(orch, lambda: None)
        
        # Mock Orchestrator.autonomous_check
        with patch.object(orch, 'autonomous_check') as mock_check:
            # Force trigger reminders
            service.timers["reminders"] = 0
            service.intervals["reminders"] = 0 # Immediate
            
            # Force trigger predictions
            service.timers["predictions"] = 0
            service.intervals["predictions"] = 0
            
            service.tick()
            
            # Should have called check for reminders and predictions
            # Note: tick calls all checks if interval passed.
            # checks are sequential.
            
            # Verify calls
            calls = [c[0][0] for c in mock_check.call_args_list]
            assert "reminders" in calls
            assert "prediction" in calls
            assert "patterns" in calls

class TestStressJarvis:
    def test_stress_iteration(self, test_env):
        """Simulate 1000 event loop ticks with mixed inputs."""
        data_dir, orch = test_env
        service = BackgroundService(orch, lambda: None)
        
        # Mock checks to avoid print spam / detailed logic overhead
        with patch.object(orch, 'autonomous_check', return_value=None), \
             patch.object(orch, 'process', return_value="OK"):
             
            start = time.time()
            for i in range(1000):
                # Every 10 ticks, add input
                if i % 10 == 0:
                    service.input_queue.put(f"command_{i}")
                
                # Tick (advances autonomous logic)
                service.tick()
                
            duration = time.time() - start
            # Should be fast since mocks are fast
            print(f"1000 ticks took {duration:.4f}s")
            assert duration < 5.0 # Performance check (approx 5ms per tick)

if __name__ == "__main__":
    pytest.main([__file__])
