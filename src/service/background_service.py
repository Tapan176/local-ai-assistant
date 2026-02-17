"""
Phase 18: Background Service (Event Loop)
Manages the main event loop for TAPAN_AI, handling both user input and autonomous tasks.
Ensures ALL database operations happen on the MAIN THREAD to prevent SQLite locking.
"""
import time
import queue
import threading
import traceback
from typing import Optional, Callable
from datetime import datetime, timedelta

class BackgroundService:
  """
  Single-Threaded Event Loop for Jarvis-like autonomy.
  - User Input: Pushed to queue via daemon thread.
  - Autonomous Tasks: Polled in main loop.
  """
  
  def __init__(self, orchestrator, input_provider: Callable[[], str], voice_interface=None):
    self.orch = orchestrator
    self.input_provider = input_provider
    self.voice = voice_interface
    self.input_queue = queue.Queue()
    self.running = False
    self.stop_event = threading.Event()
    
    # Task Timers (last run time)
    self.timers = {
      "reminders": 0,      # Every 60s
      "system": 0,         # Every 5m
      "predictions": 0,    # Every 30m
      "patterns": 0        # Every 1h
    }
    
    # Intervals (in seconds)
    self.intervals = {
      "reminders": 60,
      "system": 300,
      "predictions": 1800,
      "patterns": 3600
    }

  def start(self):
    """Start the event loop (BLOCKING)."""
    self.running = True
    self.stop_event.clear()
    
    # Start Input Thread (Keyboard)
    input_thread = threading.Thread(target=self._input_loop, daemon=True)
    input_thread.start()
    
    # Start Voice Thread (if enabled)
    if self.voice:
      print("[INFO] Voice Interface Active")
      voice_thread = threading.Thread(
        target=self.voice.listen_loop,
        args=(self.input_queue.put, self.stop_event),
        daemon=True
      )
      voice_thread.start()

    print("[INFO] TAPAN_AI Event Loop Started")
    print("   - Input: Thread-safe queue")
    print("   - Tasks: Main thread polling")

    try:
      while self.running:
        self.tick()
        time.sleep(0.1)  # Prevent CPU hogging
    except KeyboardInterrupt:
      print("\n[INFO] Stopping...")
    except Exception as e:
      print(f"\nCRITICAL ERROR in Event Loop: {e}")
      traceback.print_exc()
    finally:
      self.stop_event.set()

  def stop(self):
    self.running = False
    self.stop_event.set()

  def tick(self):
    """One cycle of the event loop."""
    # 1. Process User Input (if any)
    try:
      while not self.input_queue.empty():
        item = self.input_queue.get_nowait()

        # Item can be a dict with {"text": ..., "source": ...} or just a string
        if isinstance(item, dict):
          text = item.get("text", "")
          source = item.get("source", "text")
        else:
          text = item
          source = "text"

        if text:
          source_marker = "[Voice] " if source == "voice" else ""
          print(f"\n[YOU {source_marker}]: {text}")
          response = self.orch.process(text, source=source)
          print(f"[JARVIS]: {response}")

          # Speak response if voice enabled
          if self.voice:
             self.voice.speak(response)

    except queue.Empty:
      pass

    # 2. Run Autonomous Tasks
    now = time.time()
    
    # Reminders
    if now - self.timers["reminders"] > self.intervals["reminders"]:
      self._check_reminders()
      self.timers["reminders"] = now
      
    # System Monitor
    if now - self.timers["system"] > self.intervals["system"]:
      self._monitor_system()
      self.timers["system"] = now
      
    # Predictions
    if now - self.timers["predictions"] > self.intervals["predictions"]:
      self._run_predictions()
      self.timers["predictions"] = now

    # Patterns
    if now - self.timers["patterns"] > self.intervals["patterns"]:
      self._detect_patterns()
      self.timers["patterns"] = now

  def _input_loop(self):
    """Daemon thread for blocking input."""
    while self.running:
      try:
        # Blocking call to input provider
        text = self.input_provider()
        if text:
          self.input_queue.put(text)
      except EOFError:
        self.running = False
        break
      except Exception:
        # Log error but don't crash thread
        pass

  # --- Autonomous Tasks ---

  def _check_reminders(self):
    """Check for due reminders via ProactiveEngine."""
    try:
      # We access ProactiveEngine via Orchestrator if possible,
      # or directly if we had the instance.
      # Orchestrator lazy loads ProactiveEngine.
      # We can simply call 'suggestions' command silently to get active items?
      # Better: use the engine directly if exposed.

      # For now, let's use the Orchestrator's internal accessor if available
      # or rely on a new method in Orchestrator `autonomous_check`
      if hasattr(self.orch, "autonomous_check"):
        notifications = self.orch.autonomous_check("reminders")
        for note in notifications:
          print(f"\n[REMINDER] {note}")
    except Exception as e:
      print(f"Error checking reminders: {e}")

  def _monitor_system(self):
    """Check system health."""
    try:
      if hasattr(self.orch, "autonomous_check"):
        alert = self.orch.autonomous_check("system")
        if alert:
          print(f"\n[ALERT] System: {alert}")
    except Exception:
      pass

  def _run_predictions(self):
    """Generate predictive insights."""
    try:
        if hasattr(self.orch, "autonomous_check"):
            pred = self.orch.autonomous_check("prediction")
            if pred:
                 print(f"\n🔮 Prediction: {pred}")
    except Exception:
        pass

  def _detect_patterns(self):
    """Trigger pattern detection in UserProfile."""
    try:
        # Fire and forget (it updates DB internal state)
        if hasattr(self.orch, "autonomous_check"):
            self.orch.autonomous_check("patterns")
    except Exception:
        pass
