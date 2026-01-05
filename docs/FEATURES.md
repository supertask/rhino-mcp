# RhinoMCP Features

This document details the available MCP tools for both Rhino and Grasshopper.

## 🦏 Rhino MCP Tools

### Scene Inspection
- `get_scene_info`: Retrieve high-level information about the current scene (layers, object samples).
- `get_scene_objects_with_metadata`: Fetch detailed information about objects, including custom metadata.
- `capture_viewport`: Capture the current Rhino viewport as an image.

### Object Manipulation
- `execute_rhino_code`: Run arbitrary IronPython 2.7 code within Rhino to create or modify geometry.
- `add_object_metadata`: (Internal helper) Assign custom names and descriptions to objects.

### Layer Management
- `get_layers`: List all layers in the current document.

---

## 🦗 Grasshopper MCP Tools

### Canvas Inspection
- `get_canvas_stats`: Get quick statistics about the current canvas (object count, etc.).
- `get_gh_context`: Retrieve the entire component graph and its state.
- `get_objects`: Get detailed information about specific components by GUID.
- `get_selected`: Get information about currently selected components.
- `search_components`: Search for available components by name or keyword.

### Component Management
- `create_component`: Add a new component to the canvas.
- `connect_components`: Create wires between component parameters.
- `disconnect_components`: Remove wires from a component's input.
- `delete_objects`: Delete specified objects from the canvas.
- `clear_canvas`: Remove all objects from the active document.
- `set_component_value`: Update values for Sliders, Panels, or Toggles.
- `set_component_state`: Manage Preview, Enabled, or Locked states.
- `create_group`: Group selected components.

### Scripting & Execution
- `update_script`: Modify Python code and parameters of a GhPython component.
- `update_script_with_code_reference`: Link a GhPython component to an external Python file.
- `expire_and_get_info`: Force a recompute and retrieve updated state/errors.
- `execute_code_in_gh`: Run arbitrary Python code within the Grasshopper environment.

### Integration
- `bake_objects`: Send Grasshopper geometry to the Rhino document.

---
**[ Back to README ](../README.md)**

