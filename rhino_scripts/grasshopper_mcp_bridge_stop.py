# -*- coding: utf-8 -*-
# Stops the Grasshopper MCP bridge started by grasshopper_mcp_bridge.py
# (running that script again no longer stops it)
import scriptcontext as sc
import Rhino

if sc.sticky.get("gh_mcp_run_server"):
    sc.sticky["gh_mcp_run_server"] = False
    Rhino.RhinoApp.WriteLine("[GH MCP] Stopping Server (wait for loop to exit)...")
else:
    Rhino.RhinoApp.WriteLine("[GH MCP] Server is not running")
