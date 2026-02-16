"""
Phase 18: Predictive Intelligence
Forecasts user needs, spending, and mood based on history.
"""
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import statistics
from pathlib import Path

class PredictiveIntelligence:
  """
  Predicts future user actions and states.
  """
  
  def __init__(self, data_dir: Path, user_profile):
    self.data_dir = data_dir
    self.profile = user_profile

  def predict_next_action(self) -> List[Dict]:
    """
    Predict what the user is likely to do next.
    Returns sorted list of predictions with confidence.
    """
    predictions = []
    context = self.profile.get_current_context()
    
    # 1. Routine-based predictions (from UserProfile patterns)
    # We use a 2-hour window lookahead
    try:
      routines = self.profile.get_upcoming_routines(hours_ahead=2)
      for routine in routines:
        # Calculate time until routine
        # (Assuming routine has 'time_of_day')
        # This part relies on UserProfile's routine structure
        conf = getattr(routine, "frequency", 0.5)
        predictions.append({
          "type": "routine",
          "action": getattr(routine, "action", "unknown"),
          "confidence": conf,
          "reason": f"Routine: {getattr(routine, 'name', 'pattern')}"
        })
    except Exception:
      pass

    # 2. Context-based heuristics
    # Evening + Weekday -> Log day
    if context.get("day_type") == "weekday" and context.get("time_of_day") == "evening":
        predictions.append({
          "type": "pattern",
          "action": "log_experience",
          "confidence": 0.7,
          "reason": "You usually log your day in the evening"
        })

    # Morning + Weekday -> Check agenda
    if context.get("day_type") == "weekday" and context.get("time_of_day") == "morning":
        predictions.append({
          "type": "pattern",
          "action": "check_agenda",
          "confidence": 0.8,
          "reason": "Morning briefing"
        })

    # Sort by confidence
    return sorted(predictions, key=lambda p: p["confidence"], reverse=True)

  def predict_spending(self, category: str = "all", days: int = 7) -> float:
    """
    Predict spending for the next N days based on recent history.
    Uses simple moving average for now.
    """
    # This requires accessing FinanceTool or Finance DB directly.
    # For now, we returns a placeholder or needs to be injected with FinanceTool.
    # We'll use a safe fallback if DB access isn't readily available here,
    # or arguably this should query the DB.
    # Given 'data_dir', we can query finance.db
    import sqlite3
    db_path = self.data_dir / "finance.db"
    if not db_path.exists():
      return 0.0

    try:
      conn = sqlite3.connect(db_path)
      cursor = conn.cursor()
      
      # Get last 30 days expenses
      since = (datetime.now() - timedelta(days=30)).isoformat()
      query = "SELECT amount FROM transactions WHERE type='expense' AND date >= ?"
      params = [since]
      
      if category != "all":
        query += " AND category = ?"
        params.append(category)
        
      cursor.execute(query, tuple(params))
      rows = cursor.fetchall()
      conn.close()
      
      if not rows:
        return 0.0
        
      amounts = [r[0] for r in rows]
      daily_avg = sum(amounts) / 30.0
      return daily_avg * days
      
    except Exception:
      return 0.0

  def predict_mood(self) -> str:
    """
    Predict user's likely mood based on recent history and time.
    """
    # Simply return UserProfile's inferred mood for now, 
    # but could add trend analysis (e.g. "Grumpy on Mondays")
    ctx = self.profile.get_current_context()
    return ctx.get("mood", "neutral")
