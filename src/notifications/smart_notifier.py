"""
Phase 18: Smart Notifications
Intelligent interruption management based on user context and priority.
"""
from typing import Dict, List, Optional
from datetime import datetime, time, timedelta

class SmartNotifier:
  """
  Decides if and when to notify the user based on priority and context.
  """
  
  def __init__(self, user_profile):
    self.profile = user_profile
    self.notification_history: List[Dict] = []
    
    # Simple learning: When does user accept interruptions?
    # Placeholder for now
    self.optimal_times: List[time] = []

  def should_notify(self, notification_type: str, priority: str = "medium") -> bool:
    """
    Decide if we should interrupt the user NOW.
    
    Args:
        notification_type: routine, finance, health, system
        priority: critical, high, medium, low
    
    Returns:
        bool: True if safe to notify
    """
    context = self.profile.get_current_context()
    
    # 1. Critical always gets through
    if priority == "critical":
      return True
      
    # 2. Quiet Hours (Night) -> Only High/Critical
    if context.get("time_of_day") == "night":
      return priority in ["high", "critical"]
      
    # 3. Busy Context (Working/Meeting) -> Only High/Critical
    activity = context.get("current_activity", "unknown")
    if activity in ["working", "meeting", "deep_work"]:
      return priority in ["high", "critical"]
      
    # 4. Recent notification fatigue (don't spam)
    if self._is_spamming():
      return priority in ["high", "critical"]
      
    # 5. Low priority -> batch for later? (Not implemented, just deny)
    if priority == "low":
      # Only notify if user is "relaxing" or "idle"
      if activity in ["relaxing", "idle", "browsing"]:
        return True
      return False

    # Default allowance for Medium
    return True

  def _is_spamming(self, window_minutes: int = 15, max_count: int = 3) -> bool:
    """Check if we sent too many notifications recently."""
    now = datetime.now()
    recent = [
      n for n in self.notification_history 
      if (now - n["timestamp"]).total_seconds() < window_minutes * 60
    ]
    return len(recent) >= max_count

  def log_notification(self, type: str, priority: str):
    """Log that a notification was sent."""
    self.notification_history.append({
      "type": type,
      "priority": priority,
      "timestamp": datetime.now()
    })
    # Keep history bounded
    if len(self.notification_history) > 100:
      self.notification_history.pop(0)

  def get_optimal_time(self) -> str:
    """Return best time to notify (placeholder)."""
    # In future, return learned time like "10:00"
    return "now"
