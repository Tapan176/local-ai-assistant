import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

class ChatLogger:
    """Logs chat conversations daily in JSON format."""
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.chats_dir = self.data_dir / "chats"
        self.chats_dir.mkdir(parents=True, exist_ok=True)
        
    def _get_today_path(self) -> Path:
        """Get path for today's log file"""
        today = datetime.now().strftime("%Y-%m-%d")
        return self.chats_dir / f"{today}.json"
        
    def log_turn(self, user: str, assistant: str, entities: List[str] = None):
        """Log a single conversation turn"""
        path = self._get_today_path()
        
        # Load existing
        logs = []
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
            except:
                logs = []
        
        # Append new
        entry = {
            "timestamp": datetime.now().isoformat(),
            "user": user,
            "assistant": assistant,
            "entities": entities or []
        }
        logs.append(entry)
        
        # Save
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)
            
    def get_logs(self, date_str: str = None) -> List[Dict]:
        """Get logs for a specific date (YYYY-MM-DD or None for today)"""
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
            
        path = self.chats_dir / f"{date_str}.json"
        if not path.exists():
            return []
            
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []
            
    def get_recent_history(self, days: int = 3) -> List[Dict]:
        """Get logs from the last N days (flattened)"""
        history = []
        # Simple glob approach - in a real app would strictly parse dates
        # Sorting by filename (date) ensures chronological order
        files = sorted(list(self.chats_dir.glob("*.json")))
        
        target_files = files[-days:] if len(files) > days else files
        
        for p in target_files:
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    day_logs = json.load(f)
                    # Add date context
                    date_str = p.stem
                    for log in day_logs:
                        log['date'] = date_str
                    history.extend(day_logs)
            except:
                continue
                
        return history
