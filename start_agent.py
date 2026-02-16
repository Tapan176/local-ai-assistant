#!/usr/bin/env python3
"""
TAPAN_AI Entry Point
Redirects to src.cli.app
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.resolve()
sys.path.insert(0, str(project_root))

from src.cli.app import main

if __name__ == "__main__":
    main()
