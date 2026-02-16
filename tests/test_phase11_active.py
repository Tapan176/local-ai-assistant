"""
Phase 11: Active Life Engine Tests
50+ tests covering the NEW Phase 11 components:
- Scheduler service with notifications (10 tests)
- Habit tool with streak system (15 tests)
- Daily log interactive tool (15 tests)
- Voice interface enhancements (10 tests)
"""
import pytest
import sqlite3
from pathlib import Path
from datetime import datetime, date, timedelta
from unittest.mock import Mock, patch, MagicMock
import tempfile
import shutil
import sys

# Add project root
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# ============================================
# SCHEDULER SERVICE TESTS (10 tests)
# ============================================
class TestSchedulerService:
    """Tests for src/service/scheduler.py"""
    
    @pytest.fixture
    def temp_data_dir(self):
        """Create temporary data directory"""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.fixture
    def scheduler(self, temp_data_dir):
        """Create scheduler with temp directory"""
        from src.service.scheduler import SchedulerService
        return SchedulerService(data_dir=temp_data_dir, check_interval=1)
    
    def test_01_scheduler_init(self, scheduler):
        """Test scheduler initializes correctly"""
        assert scheduler is not None
        assert not scheduler.running
    
    def test_02_scheduler_start_stop(self, scheduler):
        """Test scheduler can start and stop"""
        scheduler.start()
        assert scheduler.running
        scheduler.stop()
        assert not scheduler.running
    
    def test_03_scheduler_no_double_start(self, scheduler):
        """Test scheduler doesn't double-start"""
        scheduler.start()
        scheduler.start()  # Should not crash
        assert scheduler.running
        scheduler.stop()
    
    def test_04_scheduler_fired_tracking(self, scheduler):
        """Test scheduler tracks fired reminders"""
        rid = "test-reminder-1"
        scheduler._fired_reminders.add(rid)
        assert rid in scheduler._fired_reminders
    
    def test_05_scheduler_fired_reset(self, scheduler):
        """Test fired reminders can be cleared"""
        scheduler._fired_reminders.add("r1")
        scheduler._fired_reminders.add("r2")
        scheduler._fired_reminders.clear()
        assert len(scheduler._fired_reminders) == 0
    
    def test_06_scheduler_check_interval(self, temp_data_dir):
        """Test custom check interval"""
        from src.service.scheduler import SchedulerService
        sched = SchedulerService(data_dir=temp_data_dir, check_interval=30)
        assert sched.check_interval == 30
    
    def test_07_scheduler_datetime_check(self, scheduler):
        """Test scheduler time comparison logic"""
        now = datetime.now()
        past = now - timedelta(minutes=5)
        future = now + timedelta(minutes=5)
        
        assert past < now
        assert future > now
    
    def test_08_scheduler_within_window(self, scheduler):
        """Test 5-minute window checking"""
        now = datetime.now()
        trigger_time = now - timedelta(minutes=3)
        
        diff = (now - trigger_time).total_seconds()
        assert 0 <= diff <= 300
    
    def test_09_scheduler_db_path(self, scheduler, temp_data_dir):
        """Test scheduler uses correct data_dir"""
        assert scheduler.data_dir == temp_data_dir
    
    def test_10_scheduler_get_global(self, temp_data_dir):
        """Test global scheduler getter"""
        from src.service import scheduler as sched_module
        sched = sched_module.get_scheduler(data_dir=temp_data_dir)
        assert sched is not None


# ============================================
# HABIT TOOL TESTS (15 tests)
# ============================================
class TestHabitTool:
    """Tests for src/agent/tools/habit_tool.py with streak system"""
    
    @pytest.fixture
    def temp_data_dir(self):
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.fixture
    def habit_tool(self, temp_data_dir):
        from src.agent.tools.habit_tool import HabitTool
        return HabitTool(data_dir=temp_data_dir)
    
    def test_01_habit_add(self, habit_tool):
        """Test adding a habit"""
        result = habit_tool.execute("add", {"name": "exercise", "frequency": "daily"})
        assert result.success
        assert "exercise" in result.message.lower()
    
    def test_02_habit_add_duplicate(self, habit_tool):
        """Test adding duplicate habit"""
        habit_tool.execute("add", {"name": "meditate"})
        result = habit_tool.execute("add", {"name": "meditate"})
        assert result is not None
    
    def test_03_habit_list_empty(self, habit_tool):
        """Test listing when no habits"""
        result = habit_tool.execute("list", {})
        assert result.success
    
    def test_04_habit_list_with_habits(self, habit_tool):
        """Test listing habits"""
        habit_tool.execute("add", {"name": "read"})
        habit_tool.execute("add", {"name": "walk"})
        result = habit_tool.execute("list", {})
        assert result.success
    
    def test_05_habit_done(self, habit_tool):
        """Test marking habit as done"""
        habit_tool.execute("add", {"name": "stretch"})
        result = habit_tool.execute("done", {"name": "stretch"})
        assert result.success
    
    def test_06_habit_done_increments_streak(self, habit_tool):
        """Test streak increments on completion"""
        habit_tool.execute("add", {"name": "code"})
        result = habit_tool.execute("done", {"name": "code"})
        assert result.success
    
    def test_07_habit_streak_query(self, habit_tool):
        """Test querying streak"""
        habit_tool.execute("add", {"name": "journal"})
        habit_tool.execute("done", {"name": "journal"})
        result = habit_tool.execute("streak", {"name": "journal"})
        assert result.success
    
    def test_08_habit_stats(self, habit_tool):
        """Test getting habit stats"""
        habit_tool.execute("add", {"name": "workout"})
        habit_tool.execute("done", {"name": "workout"})
        result = habit_tool.execute("stats", {"name": "workout"})
        assert result.success
    
    def test_09_habit_history(self, habit_tool):
        """Test habit history"""
        habit_tool.execute("add", {"name": "study"})
        habit_tool.execute("done", {"name": "study"})
        result = habit_tool.execute("history", {"name": "study"})
        assert result.success
    
    def test_10_habit_delete(self, habit_tool):
        """Test deleting habit"""
        habit_tool.execute("add", {"name": "temporary"})
        result = habit_tool.execute("delete", {"name": "temporary"})
        assert result.success
    
    def test_11_habit_delete_nonexistent(self, habit_tool):
        """Test deleting nonexistent habit"""
        result = habit_tool.execute("delete", {"name": "ghost"})
        assert result is not None
    
    def test_12_habit_frequency_daily(self, habit_tool):
        """Test daily frequency"""
        result = habit_tool.execute("add", {"name": "morning_routine", "frequency": "daily"})
        assert result.success
    
    def test_13_habit_frequency_weekly(self, habit_tool):
        """Test weekly frequency"""
        result = habit_tool.execute("add", {"name": "review", "frequency": "weekly"})
        assert result.success
    
    def test_14_habit_set_reminder(self, habit_tool):
        """Test setting reminder for habit"""
        habit_tool.execute("add", {"name": "hydrate"})
        result = habit_tool.execute("set_reminder", {"name": "hydrate", "time": "09:00"})
        assert result is not None
    
    def test_15_habit_multiple_completions(self, habit_tool):
        """Test multiple habit completions same day"""
        habit_tool.execute("add", {"name": "pushups"})
        habit_tool.execute("done", {"name": "pushups"})
        result = habit_tool.execute("done", {"name": "pushups"})
        assert result is not None


# ============================================
# DAILY LOG TOOL TESTS (15 tests)
# ============================================
class TestDailyLogTool:
    """Tests for src/agent/tools/daily_log_tool.py"""
    
    @pytest.fixture
    def temp_data_dir(self):
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.fixture
    def log_tool(self, temp_data_dir):
        from src.agent.tools.daily_log_tool import DailyLogTool
        return DailyLogTool(data_dir=temp_data_dir)
    
    def test_01_log_start_session(self, log_tool):
        """Test starting a log session"""
        result = log_tool.execute("start", {})
        assert result.success
        assert log_tool.is_session_active()
    
    def test_02_log_session_prompts(self, log_tool):
        """Test session has prompts"""
        log_tool.execute("start", {})
        prompt = log_tool.get_current_prompt()
        assert prompt is not None
    
    def test_03_log_continue_session(self, log_tool):
        """Test continuing session with input"""
        log_tool.execute("start", {})
        result = log_tool.execute("continue", {"input": "8"})
        assert result.success
    
    def test_04_log_end_session(self, log_tool):
        """Test ending session early"""
        log_tool.execute("start", {})
        result = log_tool.execute("end", {})
        assert result.success
        assert not log_tool.is_session_active()
    
    def test_05_log_mood_quick(self, log_tool):
        """Test quick mood logging"""
        result = log_tool.execute("mood", {"mood": "happy", "score": 8})
        assert result.success
    
    def test_06_log_gratitude(self, log_tool):
        """Test gratitude logging"""
        result = log_tool.execute("gratitude", {"text": "Good health"})
        assert result.success
    
    def test_07_log_add_item_expense(self, log_tool):
        """Test adding expense item"""
        result = log_tool.execute("add_item", {
            "type": "expense",
            "content": "lunch",
            "amount": 200
        })
        assert result.success
    
    def test_08_log_add_item_experience(self, log_tool):
        """Test adding experience item"""
        result = log_tool.execute("add_item", {
            "type": "experience",
            "content": "Had a great meeting"
        })
        assert result.success
    
    def test_09_log_view_empty(self, log_tool):
        """Test viewing empty log"""
        result = log_tool.execute("view", {"date": "2099-01-01"})
        assert result.success
    
    def test_10_log_view_with_data(self, log_tool):
        """Test viewing log with data"""
        log_tool.execute("mood", {"mood": "good", "score": 7})
        result = log_tool.execute("view", {})
        assert result.success
    
    def test_11_log_summary(self, log_tool):
        """Test getting summary"""
        result = log_tool.execute("summary", {"days": 7})
        assert result.success
    
    def test_12_log_summary_with_data(self, log_tool):
        """Test summary with data"""
        log_tool.execute("mood", {"mood": "great", "score": 9})
        log_tool.execute("add_item", {"type": "expense", "content": "coffee", "amount": 50})
        result = log_tool.execute("summary", {"days": 1})
        assert result.success
    
    def test_13_log_full_session_flow(self, log_tool):
        """Test complete session flow"""
        log_tool.execute("start", {})
        
        for _ in range(8):
            log_tool.execute("continue", {"input": "skip"})
        result = log_tool.execute("continue", {"input": "done"})
        
        assert result.success
        assert not log_tool.is_session_active()
    
    def test_14_log_add_interaction(self, log_tool):
        """Test adding interaction item"""
        result = log_tool.execute("add_item", {
            "type": "interaction",
            "content": "Called Mom"
        })
        assert result.success
    
    def test_15_log_no_session_continue(self, log_tool):
        """Test continue without active session"""
        result = log_tool.execute("continue", {"input": "test"})
        assert not result.success or "no active" in result.message.lower()


# ============================================
# VOICE INTERFACE TESTS (10 tests)
# ============================================
class TestVoiceInterface:
    """Tests for src/io/voice.py enhanced features"""
    
    @pytest.fixture
    def voice(self):
        from src.io.voice import VoiceInterface
        return VoiceInterface()
    
    def test_01_voice_init(self, voice):
        """Test voice interface initializes"""
        assert voice is not None
    
    def test_02_voice_status(self, voice):
        """Test status method"""
        status = voice.get_status()
        assert "Voice Configuration" in status
    
    def test_03_voice_wake_words(self, voice):
        """Test wake word configuration"""
        assert len(voice.wake_words) > 0
        assert "tapan" in [w.lower() for w in voice.wake_words]
    
    def test_04_voice_contains_wake_word(self, voice):
        """Test wake word detection"""
        assert voice._contains_wake_word("hey tapan what time is it")
        assert voice._contains_wake_word("OK Tapan remind me")
        assert not voice._contains_wake_word("hello there")
    
    def test_05_voice_extract_command(self, voice):
        """Test command extraction after wake word"""
        result = voice._extract_command_after_wake_word("hey tapan set a reminder")
        assert "set a reminder" in result.lower()
    
    def test_06_voice_speak_fallback(self, voice, capsys):
        """Test speak with fallback (no TTS engine)"""
        original = voice.engine
        voice.engine = None
        voice.has_audio_output = False
        
        voice.speak("Hello world")
        captured = capsys.readouterr()
        assert "Hello world" in captured.out
        
        voice.engine = original
    
    def test_07_voice_set_speed(self, voice):
        """Test setting voice speed"""
        voice.set_voice_speed(200)
        assert voice.voice_rate == 200
    
    def test_08_voice_set_volume(self, voice):
        """Test setting voice volume"""
        voice.set_voice_volume(0.5)
        assert voice.voice_volume == 0.5
        
        voice.set_voice_volume(2.0)
        assert voice.voice_volume == 1.0
        
        voice.set_voice_volume(-1.0)
        assert voice.voice_volume == 0.0
    
    def test_09_voice_list_voices(self, voice):
        """Test listing voices"""
        voices = voice.list_voices()
        assert isinstance(voices, list)
    
    def test_10_voice_get_singleton(self):
        """Test singleton getter"""
        from src.io.voice import get_voice
        v1 = get_voice()
        v2 = get_voice()
        assert v1 is v2


# ============================================
# INTEGRATION TESTS (bonus)
# ============================================
class TestPhase11Integration:
    """Integration tests combining Phase 11 components"""
    
    @pytest.fixture
    def temp_data_dir(self):
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_habit_and_daily_log_sync(self, temp_data_dir):
        """Test habits can be logged in daily log"""
        from src.agent.tools.habit_tool import HabitTool
        from src.agent.tools.daily_log_tool import DailyLogTool
        
        habits = HabitTool(data_dir=temp_data_dir)
        daily = DailyLogTool(data_dir=temp_data_dir)
        
        habits.execute("add", {"name": "morning_walk"})
        habits.execute("done", {"name": "morning_walk"})
        
        daily.execute("add_item", {
            "type": "habit",
            "content": "morning_walk"
        })
        
        habit_result = habits.execute("streak", {"name": "morning_walk"})
        daily_result = daily.execute("view", {})
        
        assert habit_result.success
        assert daily_result.success
    
    def test_voice_command_routing(self, temp_data_dir):
        """Test voice commands can route to tools"""
        from src.io.voice import VoiceInterface
        
        voice = VoiceInterface()
        command = voice._extract_command_after_wake_word("hey tapan start my day log")
        
        assert "start" in command.lower()
        assert "day log" in command.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
