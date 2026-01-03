#!/usr/bin/env python3
"""
RhinoMCP - Main entry point

This script serves as a convenience wrapper to start the RhinoMCP server.
"""
import sys
import os

# Add src directory to path to allow direct execution
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from rhino_mcp.server import main

if __name__ == "__main__":
    main()
