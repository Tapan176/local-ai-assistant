from pathlib import Path
from datetime import datetime

class Logger:
    """Simple logger for TAPAN_AI activities"""
    
    def __init__(self, log_dir=None):
        if log_dir is None:
            base_dir = Path(__file__).parent.parent.parent.resolve()
            log_dir = base_dir / "data"
        else:
            log_dir = Path(log_dir)
        
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = log_dir / "activity.log"
    
    def log(self, command, result, status="SUCCESS"):
        """Log an activity
        
        Args:
            command: The command that was executed
            result: The result or description
            status: SUCCESS, ERROR, or INFO
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] {status} | {command} | {result}\n"
        
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    
    def info(self, message):
        """Log an info message"""
        self.log("INFO", message, "INFO")
    
    def error(self, command, error):
        """Log an error"""
        self.log(command, str(error), "ERROR")
    
    def success(self, command, result):
        """Log a successful operation"""
        self.log(command, result, "SUCCESS")
