"""
TAPAN_AI - Personal AI Assistant Package
"""

__version__ = "0.1.0"
__author__ = "Tapan"

# Core exports for easier imports
from pathlib import Path

# Package root
PACKAGE_ROOT = Path(__file__).parent.resolve()
PROJECT_ROOT = PACKAGE_ROOT.parent
DATA_DIR = PROJECT_ROOT / "data"
