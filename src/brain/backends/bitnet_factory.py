"""
BitNet Factory - Backend Auto-Detection
Detects whether to use Local Binary or HTTP Service
"""
import json
import requests
from pathlib import Path
from typing import Optional, Union

from .bitnet_local import BitNetLocal
from .bitnet_service import BitNetService

class BitNetFactory:
  """Factory to get appropriate BitNet backend"""

  def __init__(self, data_dir: Path):
    self.config_path = data_dir / "models.json"
    self.config = self._load_config()

  def _load_config(self) -> dict:
    if self.config_path.exists():
      try:
        with open(self.config_path, 'r') as f:
          return json.load(f)
      except:
        pass
    return {}

  def get_backend(self) -> Optional[Union[BitNetLocal, BitNetService]]:
    """Get the active backend interface"""
    mode = self.config.get("bitnet_mode", "auto")

    # 1. Try Local if forced or auto
    if mode in ["local", "auto"]:
      binary_path = self.config.get("bitnet_binary_path")
      model_path = self.config.get("bitnet_model_path")

      if binary_path and model_path:
        local_backend = BitNetLocal(binary_path, model_path)
        if local_backend.check_health():
          print("[OK] BitNet: Using Local Binary")
          return local_backend

    # 2. Try HTTP if forced or auto (and local failed/skipped)
    if mode in ["http", "auto"]:
      service_url = self.config.get("bitnet_service_url", "http://localhost:11435")
      http_backend = BitNetService(service_url)
      if http_backend.check_health():
        print("[OK] BitNet: Using HTTP Service")
        return http_backend

    print("[WARN] BitNet: No backend available")
    return None
