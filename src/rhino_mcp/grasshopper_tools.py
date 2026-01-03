"""Tools for interacting with Grasshopper through socket connection."""
from mcp.server.fastmcp import FastMCP, Context, Image
import logging
from typing import Dict, Any, List, Optional, Union
import json
import socket
import time
import base64
import io
from PIL import Image as PILImage
import requests
import re
from urllib3.exceptions import InsecureRequestWarning
import urllib3

# Disable insecure HTTPS warnings
urllib3.disable_warnings(InsecureRequestWarning)

# Configure logging
logger = logging.getLogger("GrasshopperTools")

# Patterns Knowledge Base (Ported from C# ComponentKnowledgeBase.json)
GH_PATTERNS = {
  "components": [
    {
      "name": "Point",
      "category": "Params",
      "subcategory": "Geometry",
      "description": "Creates a point at the specified coordinates",
      "inputs": [
        {"name": "X", "type": "Number", "description": "X coordinate"},
        {"name": "Y", "type": "Number", "description": "Y coordinate"},
        {"name": "Z", "type": "Number", "description": "Z coordinate"}
      ],
      "outputs": [
        {"name": "Pt", "type": "Point", "description": "Point"}
      ]
    },
    {
      "name": "XY Plane",
      "category": "Vector",
      "subcategory": "Plane",
      "description": "Creates an XY plane at the world origin or at a specified point",
      "inputs": [
        {"name": "Origin", "type": "Point", "description": "Origin point", "optional": True}
      ],
      "outputs": [
        {"name": "Plane", "type": "Plane", "description": "XY plane"}
      ]
    },
    {
      "name": "Box",
      "category": "Surface",
      "subcategory": "Primitive",
      "description": "Creates a box from a base plane and dimensions",
      "inputs": [
        {"name": "Base", "type": "Plane", "description": "Base plane"},
        {"name": "X Size", "type": "Number", "description": "Size in X direction"},
        {"name": "Y Size", "type": "Number", "description": "Size in Y direction"},
        {"name": "Z Size", "type": "Number", "description": "Size in Z direction"}
      ],
      "outputs": [
        {"name": "Box", "type": "Brep", "description": "Box geometry"}
      ]
    },
    {
      "name": "Circle",
      "category": "Curve",
      "subcategory": "Primitive",
      "description": "Creates a circle from a plane and radius",
      "inputs": [
        {"name": "Plane", "type": "Plane", "description": "Circle plane"},
        {"name": "Radius", "type": "Number", "description": "Circle radius"}
      ],
      "outputs": [
        {"name": "Circle", "type": "Curve", "description": "Circle curve"}
      ]
    },
    {
      "name": "Number Slider",
      "category": "Params",
      "subcategory": "Input",
      "description": "Slider for numeric input",
      "inputs": [],
      "outputs": [
        {"name": "Number", "type": "Number", "description": "Slider value"}
      ],
      "defaultSettings": {
        "min": 0,
        "max": 10,
        "value": 5
      }
    },
    {
      "name": "Panel",
      "category": "Params",
      "subcategory": "Input",
      "description": "Text panel for input or output",
      "inputs": [
        {"name": "Input", "type": "Any", "description": "Any input", "optional": True}
      ],
      "outputs": [
        {"name": "Output", "type": "Text", "description": "Panel text"}
      ]
    },
    {
      "name": "Voronoi",
      "category": "Surface",
      "subcategory": "Triangulation",
      "description": "Creates a Voronoi diagram from points",
      "inputs": [
        {"name": "Points", "type": "Point", "description": "Input points"},
        {"name": "Radius", "type": "Number", "description": "Cell radius", "optional": True},
        {"name": "Plane", "type": "Plane", "description": "Base plane", "optional": True}
      ],
      "outputs": [
        {"name": "Cells", "type": "Curve", "description": "Voronoi cells"},
        {"name": "Vertices", "type": "Point", "description": "Voronoi vertices"}
      ]
    },
    {
      "name": "Populate 3D",
      "category": "Vector",
      "subcategory": "Grid",
      "description": "Creates a 3D grid of points",
      "inputs": [
        {"name": "Base", "type": "Plane", "description": "Base plane"},
        {"name": "Size X", "type": "Number", "description": "Size in X direction"},
        {"name": "Size Y", "type": "Number", "description": "Size in Y direction"},
        {"name": "Size Z", "type": "Number", "description": "Size in Z direction"},
        {"name": "Count X", "type": "Integer", "description": "Count in X direction"},
        {"name": "Count Y", "type": "Integer", "description": "Count in Y direction"},
        {"name": "Count Z", "type": "Integer", "description": "Count in Z direction"}
      ],
      "outputs": [
        {"name": "Points", "type": "Point", "description": "3D grid of points"}
      ]
    },
    {
      "name": "Boundary Surfaces",
      "category": "Surface",
      "subcategory": "Freeform",
      "description": "Creates boundary surfaces from curves",
      "inputs": [
        {"name": "Curves", "type": "Curve", "description": "Input curves"}
      ],
      "outputs": [
        {"name": "Surfaces", "type": "Surface", "description": "Boundary surfaces"}
      ]
    },
    {
      "name": "Extrude",
      "category": "Surface",
      "subcategory": "Freeform",
      "description": "Extrudes curves or surfaces",
      "inputs": [
        {"name": "Base", "type": "Geometry", "description": "Base geometry"},
        {"name": "Direction", "type": "Vector", "description": "Extrusion direction"},
        {"name": "Distance", "type": "Number", "description": "Extrusion distance"}
      ],
      "outputs": [
        {"name": "Result", "type": "Brep", "description": "Extruded geometry"}
      ]
    }
  ],
  "patterns": [
    {
      "name": "3D Box",
      "description": "Creates a simple 3D box",
      "components": [
        {"type": "XY Plane", "x": 100, "y": 100, "id": "plane"},
        {"type": "Number Slider", "x": 100, "y": 200, "id": "sliderX", "settings": {"min": 0, "max": 50, "value": 20}},
        {"type": "Number Slider", "x": 100, "y": 250, "id": "sliderY", "settings": {"min": 0, "max": 50, "value": 20}},
        {"type": "Number Slider", "x": 100, "y": 300, "id": "sliderZ", "settings": {"min": 0, "max": 50, "value": 20}},
        {"type": "Box", "x": 400, "y": 200, "id": "box"}
      ],
      "connections": [
        {"source": "plane", "sourceParam": "Plane", "target": "box", "targetParam": "Base"},
        {"source": "sliderX", "sourceParam": "Number", "target": "box", "targetParam": "X Size"},
        {"source": "sliderY", "sourceParam": "Number", "target": "box", "targetParam": "Y Size"},
        {"source": "sliderZ", "sourceParam": "Number", "target": "box", "targetParam": "Z Size"}
      ]
    },
    {
      "name": "3D Voronoi",
      "description": "Creates a 3D Voronoi pattern within a box",
      "components": [
        {"type": "XY Plane", "x": 100, "y": 100, "id": "plane"},
        {"type": "Number Slider", "x": 100, "y": 200, "id": "sizeX", "settings": {"min": 0, "max": 100, "value": 50}},
        {"type": "Number Slider", "x": 100, "y": 250, "id": "sizeY", "settings": {"min": 0, "max": 100, "value": 50}},
        {"type": "Number Slider", "x": 100, "y": 300, "id": "sizeZ", "settings": {"min": 0, "max": 100, "value": 50}},
        {"type": "Number Slider", "x": 100, "y": 350, "id": "countX", "settings": {"min": 1, "max": 20, "value": 10}},
        {"type": "Number Slider", "x": 100, "y": 400, "id": "countY", "settings": {"min": 1, "max": 20, "value": 10}},
        {"type": "Number Slider", "x": 100, "y": 450, "id": "countZ", "settings": {"min": 1, "max": 20, "value": 10}},
        {"type": "Populate 3D", "x": 400, "y": 250, "id": "populate"},
        {"type": "Voronoi", "x": 600, "y": 250, "id": "voronoi"}
      ],
      "connections": [
        {"source": "plane", "sourceParam": "Plane", "target": "populate", "targetParam": "Base"},
        {"source": "sizeX", "sourceParam": "Number", "target": "populate", "targetParam": "Size X"},
        {"source": "sizeY", "sourceParam": "Number", "target": "populate", "targetParam": "Size Y"},
        {"source": "sizeZ", "sourceParam": "Number", "target": "populate", "targetParam": "Size Z"},
        {"source": "countX", "sourceParam": "Number", "target": "populate", "targetParam": "Count X"},
        {"source": "countY", "sourceParam": "Number", "target": "populate", "targetParam": "Count Y"},
        {"source": "countZ", "sourceParam": "Number", "target": "populate", "targetParam": "Count Z"},
        {"source": "populate", "sourceParam": "Points", "target": "voronoi", "targetParam": "Points"}
      ]
    },
    {
      "name": "Circle",
      "description": "Creates a simple circle",
      "components": [
        {"type": "XY Plane", "x": 100, "y": 100, "id": "plane"},
        {"type": "Number Slider", "x": 100, "y": 200, "id": "radius", "settings": {"min": 0, "max": 50, "value": 10}},
        {"type": "Circle", "x": 400, "y": 150, "id": "circle"}
      ],
      "connections": [
        {"source": "plane", "sourceParam": "Plane", "target": "circle", "targetParam": "Plane"},
        {"source": "radius", "sourceParam": "Number", "target": "circle", "targetParam": "Radius"}
      ]
    }
  ]
}

# Add a preprocessing function for LLM inputs
def preprocess_llm_input(input_str: str) -> str:
    """
    Preprocess a potentially malformed JSON string from an LLM.
    This handles common issues before attempting JSON parsing.

    Args:
        input_str: Raw string from LLM that may contain malformed JSON

    Returns:
        Preprocessed string that should be easier to parse
    """
    if not isinstance(input_str, str):
        return input_str

    # Replace backtick delimiters with proper double quotes for the entire JSON object
    if input_str.strip().startswith('`{') and input_str.strip().endswith('}`'):
        input_str = input_str.strip()[1:-1]  # Remove the outer backticks

    # Handle backtick-delimited field names and string values
    # This is a basic approach - first convert all standalone backtick pairs to double quotes
    result = ""
    in_string = False
    last_char = None
    i = 0
    
    while i < len(input_str):
        char = input_str[i]
        
        # Handle backtick as quote
        if char == '`' and (last_char is None or last_char != '\\'):
            in_string = not in_string
            result += '"'
        else:
            result += char
            
        last_char = char
        i += 1

    # Fix boolean values
    result = re.sub(r':\s*True\b', ': true', result)
    result = re.sub(r':\s*False\b', ': false', result)
    result = re.sub(r':\s*None\b', ': null', result)
    
    return result

def extract_payload_fields(raw_input: str) -> Dict[str, Any]:
    """
    Extract fields from a payload that might be malformed.
    Works with raw LLM output directly.
    
    Args:
        raw_input: Raw string input from LLM
        
    Returns:
        Dictionary of extracted fields
    """
    if not isinstance(raw_input, str):
        return {}
    
    # First attempt: try the standard JSON sanitizer
    payload = sanitize_json(raw_input)
    if payload:
        return payload
    
    # Second attempt: special handling for backtick-delimited code
    if '`code`' in raw_input or '"code"' in raw_input:
        # Find the code section
        code_match = re.search(r'[`"]code[`"]\s*:\s*[`"](.*?)[`"](?=\s*,|\s*\})', raw_input, re.DOTALL)
        instance_guid_match = re.search(r'[`"]instance_guid[`"]\s*:\s*[`"](.*?)[`"]', raw_input)
        message_match = re.search(r'[`"]message_to_user[`"]\s*:\s*[`"](.*?)[`"]', raw_input)
        
        result = {}
        
        if instance_guid_match:
            result["instance_guid"] = instance_guid_match.group(1)
            
        if code_match:
            result["code"] = code_match.group(1)
            
        if message_match:
            result["message_to_user"] = message_match.group(1)
            
        return result
        
    return {}

# Update the sanitize_json function to use the preprocessor
def sanitize_json(json_str_or_dict: Union[str, Dict]) -> Dict[str, Any]:
    """
    Sanitize and validate JSON input, which might come from an LLM.
    
    Args:
        json_str_or_dict: Either a JSON string or dictionary that might need sanitizing
        
    Returns:
        A properly formatted dictionary
    """
    # If it's already a dictionary, return it
    if isinstance(json_str_or_dict, dict):
        return json_str_or_dict.copy()
    
    # If it's a string, try to fix common issues
    if isinstance(json_str_or_dict, str):
        # Apply preprocessing for LLM input
        json_str = preprocess_llm_input(json_str_or_dict)
        
        # Remove markdown JSON code block markers if present
        json_str = re.sub(r'^```json\s*', '', json_str)
        json_str = re.sub(r'\s*```$', '', json_str)
        
        # Try to parse the JSON
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON after preprocessing: {e}")
            logger.error(f"Preprocessed JSON string: {json_str}")
            
            # Try another approach - remove all newlines from outside code sections
            try:
                # Find code sections
                if '"code"' in json_str:
                    parts = []
                    last_end = 0
                    
                    # Find all code sections
                    for match in re.finditer(r'"code"\s*:\s*"(.*?)"(?=\s*,|\s*\})', json_str, re.DOTALL):
                        # Add the part before code with newlines removed
                        before_code = json_str[last_end:match.start()]
                        before_code = re.sub(r'\s+', ' ', before_code)
                        parts.append(before_code)
                        
                        # Add the code section as is
                        code_section = match.group(0)
                        parts.append(code_section)
                        
                        last_end = match.end()
                    
                    # Add the remaining part
                    remaining = json_str[last_end:]
                    remaining = re.sub(r'\s+', ' ', remaining)
                    parts.append(remaining)
                    
                    # Combine all parts
                    json_str = ''.join(parts)
                    
                    return json.loads(json_str)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse JSON with alternative method")
            
            # Return empty dict as fallback
            return {}
    
    # If it's neither a dict nor string, return empty dict
    return {}

class GrasshopperConnection:
    def __init__(self, host='localhost', port=9999):  # Using port 9999 to match grasshopper_mcp_bridge.py
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.timeout = 30.0  # 30 second timeout
    
    def check_server_available(self) -> bool:
        """Check if the Grasshopper server is running and available.
        
        Returns:
            bool: True if the server is available, False otherwise
        """
        try:
            # Use POST with test command instead of GET
            data = {"type": "test", "message": "health_check"}
            response = requests.post(
                self.base_url, 
                json=data,
                timeout=2.0,
                headers={'Content-Type': 'application/json'}
            )
            response.raise_for_status()
            result = response.json()
            # Check if response indicates success
            if result.get("status") == "success":
                logger.info("Grasshopper server is available at {0}".format(self.base_url))
                return True
            else:
                logger.warning("Grasshopper server responded but with error status")
                return False
        except Exception as e:
            logger.warning("Grasshopper server is not available: {0}".format(str(e)))
            return False
    
    def connect(self):
        """Connect to the Grasshopper script's HTTP server"""
        # Check if server is available
        if not self.check_server_available():
            raise Exception("Grasshopper server not available at {0}. Make sure the GHPython component is running and the toggle is set to True.".format(self.base_url))
        logger.info("Connected to Grasshopper server")
    
    def disconnect(self):
        """No need to disconnect for HTTP connections"""
        pass
    
    def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send a command to the Grasshopper script and wait for response"""
        try:
            data = {
                "type": command_type,
                **(params or {})
            }

            logger.info(f"Sending command to Grasshopper server: type={command_type}")
            
            # Use a session to handle connection properly
            with requests.Session() as session:
                response = session.post(
                    self.base_url,
                    json=data,
                    timeout=self.timeout,
                    headers={'Content-Type': 'application/json'},
                    stream=True
                )
                response.raise_for_status()
                
                # Read the response content and return it directly
                return response.json()
                    
        except requests.exceptions.RequestException as req_err:
            error_content = ""
            if hasattr(req_err, 'response') and req_err.response is not None:
                try:
                    error_content = req_err.response.text
                except:
                    pass
                
            error_msg = f"HTTP request error: {str(req_err)}. Response: {error_content}"
            logger.error(error_msg)
            return {"status": "error", "result": error_msg}
            
        except Exception as e:
            error_msg = f"Error communicating with Grasshopper script: {str(e)}"
            logger.error(error_msg)
            return {"status": "error", "result": error_msg}

# Global connection instance
_grasshopper_connection = None

def get_grasshopper_connection() -> GrasshopperConnection:
    """Get or create the Grasshopper connection"""
    global _grasshopper_connection
    if _grasshopper_connection is None:
        _grasshopper_connection = GrasshopperConnection()
    return _grasshopper_connection

class GrasshopperTools:
    """Collection of tools for interacting with Grasshopper."""
    
    def __init__(self, app):
        self.app = app
        self._register_tools()
    
    def _register_tools(self):
        """Register all Grasshopper tools with the MCP server."""
        self.app.tool()(self.is_server_available)
        self.app.tool()(self.execute_code_in_gh)
        self.app.tool()(self.get_gh_context)
        self.app.tool()(self.get_objects)
        self.app.tool()(self.get_selected)
        self.app.tool()(self.update_script)
        self.app.tool()(self.update_script_with_code_reference)
        self.app.tool()(self.expire_and_get_info)
        self.app.tool()(self.create_component)
        self.app.tool()(self.search_components)
        self.app.tool()(self.connect_components)
        self.app.tool()(self.disconnect_components)
        self.app.tool()(self.set_component_value)
        self.app.tool()(self.set_component_state)
        self.app.tool()(self.create_group)
        self.app.tool()(self.delete_objects)
        self.app.tool()(self.clear_canvas)
        self.app.tool()(self.get_canvas_stats)
        self.app.tool()(self.bake_objects)
        self.app.tool()(self.get_available_patterns)
    
    def is_server_available(self, ctx: Context) -> bool:
        """Grasshopper: Check if the Grasshopper server is available.
        
        This is a quick check to see if the Grasshopper socket server is running
        and available for connections.
        
        Returns:
            bool: True if the server is available, False otherwise
        """
        try:
            connection = get_grasshopper_connection()
            return connection.check_server_available()
        except Exception as e:
            logger.error("Error checking Grasshopper server availability: {0}".format(str(e)))
            return False
    
    def execute_code_in_gh(self, ctx: Context, code: str) -> str:
        """Grasshopper: Execute arbitrary Python code in Grasshopper.
        
        IMPORTANT: 
        - Uses IronPython 2.7 - no f-strings or modern Python features
        - Always include ALL required imports in your code
        - Use 'result = value' to return data (don't use return statements)

        Example - Adding components to canvas:
        ```python
        import scriptcontext as sc
        import clr
        import Rhino
        import System.Drawing as sd
        import Grasshopper
        import Grasshopper.Kernel.Special as GHSpecial

        doc = ghenv.Component.OnPingDocument()
        
        # Create and position a Pipeline
        pipe = GHSpecial.GH_GeometryPipeline()
        if pipe.Attributes is None: pipe.CreateAttributes()
        pipe.Attributes.Pivot = sd.PointF(100, 100)
        doc.AddObject(pipe, False)

        # Create and connect a Panel
        pan = GHSpecial.GH_Panel()
        if pan.Attributes is None: pan.CreateAttributes()
        pan.Attributes.Pivot = sd.PointF(300, 100)
        doc.AddObject(pan, False)
        pan.AddSource(pipe)
        
        result = "Components created successfully"
        ```
        
        You can also provide the code as part of a JSON object with a "code" field.
        
        Args:
            code: The Python code to execute, or a JSON object with a "code" field
        
        Returns:
            The result of the code execution
        """
        try:
            # Check if the input might be a JSON payload
            if isinstance(code, str) and (
                code.strip().startswith('{') or 
                code.strip().startswith('`{') or
                '`code`' in code or 
                '"code"' in code
            ):
                # Try direct extraction for speed and reliability
                payload = extract_payload_fields(code)
                if payload and "code" in payload:
                    code = payload["code"]
            
            # Validate that we have code to execute
            if not code or not isinstance(code, str):
                return "Error: No valid code provided. Please provide Python code to execute."
            
            # Make sure code ends with a result variable if it doesn't have one
            if "result =" not in code and "result=" not in code:
                # Extract the last line if it starts with "return"
                lines = code.strip().split("\n")
                if lines and lines[-1].strip().startswith("return "):
                    return_value = lines[-1].strip()[7:].strip() # Remove "return " prefix
                    # Replace the return with a result assignment
                    lines[-1] = "result = " + return_value
                    code = "\n".join(lines)
                else:
                    # Append a default result if no return or result is present
                    code += "\n\n# Auto-added result assignment\nresult = \"Code executed successfully\""
            
            logger.info(f"Sending code execution request to Grasshopper")
            connection = get_grasshopper_connection()
            
            result = connection.send_command("execute_code", {
                "code": code
            })
            
            # Simply return result info with error prefix if needed
            if result.get("status") == "error":
                return f"Error: {result.get('result', 'Unknown error')}"
            return result.get("result", "Code executed successfully")
                
        except Exception as e:
            return f"Error executing code: {str(e)}"

    def get_gh_context(self, ctx: Context, simplified: bool = False) -> str:
        """Grasshopper: Get current Grasshopper document state and definition graph, sorted by execution order.
        
        Returns a JSON string containing:
        - Component graph (connections between components)
        - Component info (guid, name, type)
        - Component properties and parameters
        
        Args:
            simplified: When true, returns minimal component info without detailed properties
        
        Returns:
            JSON string with grasshopper definition graph
        """
        try:
            logger.info("Getting Grasshopper context with simplified={0}".format(simplified))
            connection = get_grasshopper_connection()
            result = connection.send_command("get_context", {
                "simplified": simplified
            })
            
            if result.get("status") == "error":
                return f"Error: {result.get('result', 'Unknown error')}"
            return json.dumps(result.get("result", {}), indent=2)
                
        except Exception as e:
            return f"Error getting context: {str(e)}"

    def get_objects(self, ctx: Context, instance_guids: List[str], simplified: bool = False, context_depth: int = 0) -> str:
        """Grasshopper: Get information about specific components by their GUIDs.
        
        Args:
            instance_guids: List of component GUIDs to retrieve
            simplified: When true, returns minimal component info
            context_depth: How many levels of connected components to include (0-3), try to keep it small
        
        Returns:
            JSON string with component information and optional context
        """
        try:
            logger.info("Getting objects with GUIDs: {0}".format(instance_guids))
            connection = get_grasshopper_connection()
            result = connection.send_command("get_objects", {
                "instance_guids": instance_guids,
                "simplified": simplified,
                "context_depth": context_depth
            })
            
            if result.get("status") == "error":
                return f"Error: {result.get('result', 'Unknown error')}"
            return json.dumps(result.get("result", {}), indent=2)
                
        except Exception as e:
            return f"Error getting objects: {str(e)}"

    def get_selected(self, ctx: Context, simplified: bool = False, context_depth: int = 0) -> str:
        """Grasshopper: Get information about currently selected components.
        
        Args:
            simplified: When true, returns minimal component info
            context_depth: How many levels of connected components to include (0-3)
        
        Returns:
            JSON string with selected component information and optional context
        """
        try:
            logger.info("Getting selected components")
            connection = get_grasshopper_connection()
            result = connection.send_command("get_selected", {
                "simplified": simplified,
                "context_depth": context_depth
            })
            
            if result.get("status") == "error":
                return f"Error: {result.get('result', 'Unknown error')}"
            return json.dumps(result.get("result", {}), indent=2)
                
        except Exception as e:
            return f"Error getting selected components: {str(e)}"

    def update_script(self, ctx: Context, instance_guid: str = None, code: str = None, description: str = None, 
                     message_to_user: str = None, param_definitions: List[Dict[str, Any]] = None) -> str:
        """Grasshopper: Update a script component with new code, description, user feedback message, and optionally redefine its parameters.
        
        IMPORTANT NOTES:
        0. the output param "output" is reserved for the "message_to_user", name output params with a meaningful name if you create new ones
        1. The code must be valid Python 2.7 / IronPython code (no f-strings!)
        2. When updating existing code:
           - If NOT changing parameters, ensure to keep the same input/output variable names!
           - Know their datatypes and access methods (list, datatree, item) before modifying
           - The script may be part of a larger definition - maintain input/output structure
        3. When changing input and outputparameters:
           - You must provide ALL input/output parameters, even existing ones you want to keep
           - The component will be completely reconfigured with the new parameter set
           - Existing connections may be lost if parameter names change
        
        Example:
        ```json
        {
            "instance_guid": "a1b2c3d4-e5f6-4a5b-9c8d-7e6f5d4c3b2a",
            "code": "import Rhino.Geometry as rg\\n\\n# Create circle from radius\\norigin = rg.Point3d(0, 0, 0)\\ncircle = rg.Circle(origin, radius)\\n\\n# Set outputs\\nresult = circle\\ncircle_center = circle.Center\\ncircle_area = circle.Area",
            "description": "Creates a circle and outputs its geometry, center point, and area",
            "message_to_user": "Circle component updated with new outputs for center point and area calculation",
            "param_definitions": [
                {
                    "type": "input",
                    "name": "radius",
                    "access": "item",
                    "typehint": "float",
                    "description": "Circle radius",
                    "optional": false,
                    "default": 1.0
                },
                {
                    "type": "output",
                    "name": "circle",
                    "description": "Generated circle geometry"
                },
                {
                    "type": "output",
                    "name": "center",
                    "description": "Center point of the circle"
                },
                {
                    "type": "output",
                    "name": "output",
                    "description": "Used to display messages to the user"
                }
            ]
        }
        ```
        
        Args:
            instance_guid: The GUID of the script component to update
            code: Optional new Python code for the component
            description: Optional new description for the component
            message_to_user: Optional feedback message that should include a change summary and/or suggestions
            param_definitions: Optional list of parameter definitions. If provided, ALL parameters will be redefined.
                Each definition must be a dictionary with:
                Required keys:
                    - "type": "input" or "output"
                    - "name": Parameter name (string)
                Optional keys for inputs:
                    - "access": "item", "list", or "tree" (default "list")
                    - "typehint": e.g. "str", "int", "float", "bool" (determines parameter type)
                    - "description": Parameter description
                    - "optional": bool, default True
                    - "default": Default value (not persistent)
        
        Returns:
            Success status with summary of which elements were updated
        """
        try:
            # Log initial input for debugging
            if isinstance(instance_guid, str) and len(instance_guid) > 200:
                logger.info(f"Received long payload as instance_guid parameter: first 100 chars: {instance_guid[:100]}...")
            else:
                logger.info(f"Initial parameters: instance_guid={instance_guid}, code length={len(code) if code else 0}, "
                          f"description={'provided' if description else 'None'}, "
                          f"message_to_user={'provided' if message_to_user else 'None'}, "
                          f"param_definitions={'provided' if param_definitions else 'None'}")
            
            # Check if the first argument is a string that looks like a JSON payload
            if isinstance(instance_guid, str) and (
                instance_guid.strip().startswith('{') or 
                instance_guid.strip().startswith('`{') or 
                '`instance_guid`' in instance_guid or 
                '"instance_guid"' in instance_guid
            ):
                logger.info("Detected JSON-like payload in instance_guid parameter, extracting fields")
                # More robust extraction for complex payloads
                payload = extract_payload_fields(instance_guid)
                if payload and "instance_guid" in payload:
                    # Log what was extracted
                    logger.info(f"Extracted fields from payload: {sorted(payload.keys())}")
                    
                    instance_guid = payload.get("instance_guid")
                    code = payload.get("code", code)
                    description = payload.get("description", description)
                    message_to_user = payload.get("message_to_user", message_to_user)
                    param_definitions = payload.get("param_definitions", param_definitions)
                    
                    logger.info(f"After extraction: instance_guid={instance_guid}, code length={len(code) if code else 0}")
                else:
                    logger.warning("Failed to extract instance_guid from payload")
            
            # Ensure we have a valid instance_guid
            if not instance_guid:
                logger.error("No instance_guid provided")
                return "Error: No instance_guid provided. Please specify the GUID of the script component to update."
            
            logger.info(f"Updating script component {instance_guid}")
            logger.info(f"Parameter details: code={bool(code)}, description={bool(description)}, "
                      f"message_to_user={bool(message_to_user)}, param_definitions type={type(param_definitions) if param_definitions else None}")
                      
            connection = get_grasshopper_connection()
            
            # Sanitize param_definitions if provided
            if param_definitions is not None and isinstance(param_definitions, list):
                # Create new sanitized list
                sanitized_params = []
                for param in param_definitions:
                    if isinstance(param, dict):
                        sanitized_params.append(param.copy())
                    else:
                        # Try to parse if it's a string
                        try:
                            if isinstance(param, str):
                                param_dict = json.loads(preprocess_llm_input(param))
                                sanitized_params.append(param_dict)
                        except:
                            logger.warning(f"Could not parse parameter definition: {param}")
                
                param_definitions = sanitized_params
            
            # Prepare the command payload - log it before sending
            command_payload = {
                "instance_guid": instance_guid,
                "code": code,
                "description": description,
                "message_to_user": message_to_user,
                "param_definitions": param_definitions
            }
            
            logger.info(f"Sending command with payload keys: {sorted(command_payload.keys())}")
            if code:
                logger.info(f"Code snippet (first 50 chars): {code[:50]}...")
            
            # Always use "update_script" as the command type
            result = connection.send_command("update_script", command_payload)
            
            if result.get("status") == "error":
                return f"Error: {result.get('result', 'Unknown error')}"
            return json.dumps(result.get("result", {}), indent=2)
                
        except Exception as e:
            return f"Error updating script: {str(e)}"

    def update_script_with_code_reference(self, ctx: Context, instance_guid: str = None, file_path: str = None, 
                                        param_definitions: List[Dict[str, Any]] = None, description: str = None, 
                                        name: str = None, force_code_reference: bool = False) -> str:
        """Grasshopper: Update a script component to use code from an external Python file.
        This tool allows you to modify a GHPython script component to use code from an external Python file 
        instead of embedded code. This enables better code organization, version control, and reuse across 
        multiple components. Moreove, you can add and remove input/ output paramters.
        
        important notes:
        1. Only use when working in/with curser or another IDE
        2. First, check the grasshopper script component using  "get_objects" tool
        3. Second, check if a python file is already referenced by the component AND if it exists in the cursor project
            ALWAYS add the component instance_guid to the file name (e.g. cirler_creator_a1b2c3d4-e5f6-4a5b-9c8d-7e6f5d4c3b2a.py)
        4. write code im the file and save it, update the file path with this tool
        5. Once referenced, future updates on the code file will automatically be reflected in the component (no need to use this tool)
        6. you can use get_objects tool to get potential error messages from the component for debugging (runtimeMessages)

        Args:
            instance_guid: The GUID of the target GHPython component to modify.
            file_path: Path to the external Python file that contains the code.
            param_definitions: List of dictionaries defining input/output parameters.
            description: New description for the component.
            name: New nickname for the component.
            force_code_reference: When True, converts/sets a component to use referenced code mode.

        Returns:
            Success status with summary of which elements were updated and component instance_guid
        
        Example:
        ```json
        {
            "instance_guid": "a1b2c3d4-e5f6-4a5b-9c8d-7e6f5d4c3b2a",
            "file_path": "/scripts/cirler_creator_a1b2c3d4-e5f6-4a5b-9c8d-7e6f5d4c3b2a.py"
            "name":"CircleTool"
            "description": "Creates a circle and outputs its geometry, center point, and area",
            "message_to_user": "Circle, add one radius slider as input",
            force_code_reference = True, 
            "param_definitions": [
                {
                    "type": "input",
                    "name": "radius",
                    "access": "item",
                    "typehint": "float",
                    "description": "Circle radius",
                    "optional": false,
                    "default": 1.0
                },
                {
                    "type": "output",
                    "name": "circle",
                    "description": "Generated circle geometry"
                }
            ]
        }
        ```
        """
        try:
            # Ensure we have a valid instance_guid
            if not instance_guid:
                return "Error: No instance_guid provided. Please specify the GUID of the script component to update."
            
            connection = get_grasshopper_connection()
            
            # Prepare the command payload
            command_payload = {
                "instance_guid": instance_guid,
                "file_path": file_path,
                "param_definitions": param_definitions,
                "description": description,
                "name": name,
                "force_code_reference": force_code_reference
            }
            
            # Send command and get result
            result = connection.send_command("update_script_with_code_reference", command_payload)
            
            if result.get("status") == "error":
                return f"Error: {result.get('result', 'Unknown error')}"
            return json.dumps(result.get("result", {}), indent=2)
                
        except Exception as e:
            return f"Error updating script with code reference: {str(e)}"

    def expire_and_get_info(self, ctx: Context, instance_guid: str) -> str:
        """Grasshopper: Expire a specific component and get its updated information.

        This is useful after updating a component's code, especially via a referenced file,
        to force a recompute and retrieve the latest state, including potential errors or messages.

        Args:
            instance_guid: The GUID of the component to expire and query.

        Returns:
            JSON string with the component's updated information after expiration.
        """
        try:
            if not instance_guid:
                return "Error: No instance_guid provided. Please specify the GUID of the component to expire."

            logger.info(f"Expiring component and getting info for GUID: {instance_guid}")
            connection = get_grasshopper_connection()
            result = connection.send_command("expire_component", {
                "instance_guid": instance_guid
            })

            if result.get("status") == "error":
                return f"Error: {result.get('result', 'Unknown error')}"
            # The server side already returns component info after expiring
            return json.dumps(result.get("result", {}), indent=2)

        except Exception as e:
            return f"Error expiring component: {str(e)}"

    def create_component(self, ctx: Context, name: str, x: float = 0, y: float = 0) -> str:
        """Grasshopper: Create a new component by name on the canvas.
        
        The name matching attempts to find exact matches first, then nickname matches, then partial matches.
        
        Args:
            name: Name of the component (e.g., "Sphere", "Move", "Voronoi", "Panel", "Slider")
            x: X coordinate on canvas (default 0)
            y: Y coordinate on canvas (default 0)
            
        Returns:
            JSON string with details of the created component (including instanceGuid)
        """
        try:
            connection = get_grasshopper_connection()
            result = connection.send_command("create_component", {
                "name": name,
                "x": x,
                "y": y
            })
            if result.get("status") == "error":
                return f"Error: {result.get('result', 'Unknown error')}"
            return json.dumps(result.get("result", {}), indent=2)
        except Exception as e:
            return f"Error creating component: {str(e)}"

    def search_components(self, ctx: Context, query: str, limit: int = 10) -> str:
        """Grasshopper: Search for available components by name or keyword.
        
        Useful when you don't know the exact name of a component.
        
        Args:
            query: Search keyword
            limit: Max results (default 10)
            
        Returns:
            JSON list of matching components with names and categories
        """
        try:
            connection = get_grasshopper_connection()
            result = connection.send_command("search_components", {
                "query": query,
                "limit": limit
            })
            if result.get("status") == "error":
                return f"Error: {result.get('result', 'Unknown error')}"
            return json.dumps(result.get("result", []), indent=2)
        except Exception as e:
            return f"Error searching components: {str(e)}"

    def connect_components(self, ctx: Context, source_id: str, source_param: str, target_id: str, target_param: str) -> str:
        """Grasshopper: Connect two components.
        
        Connects an output parameter of the source component to an input parameter of the target component.
        
        Args:
            source_id: Instance GUID of the source component
            source_param: Name (or NickName) of the output parameter on source (e.g. "Result", "C", "Output"). Can also be an index string "0".
            target_id: Instance GUID of the target component
            target_param: Name (or NickName) of the input parameter on target (e.g. "Radius", "A", "Input"). Can also be an index string "0".
            
        Returns:
            Result message indicating success or failure
        """
        try:
            connection = get_grasshopper_connection()
            result = connection.send_command("connect_components", {
                "source_id": source_id,
                "source_param": source_param,
                "target_id": target_id,
                "target_param": target_param
            })
            if result.get("status") == "error":
                return f"Error: {result.get('result', 'Unknown error')}"
            
            # Check for runtime messages (added feature)
            msg = result.get("result", "Connected")
            runtime_msgs = result.get("target_runtime_messages", [])
            if runtime_msgs:
                msg += f". Warning/Errors: {', '.join(runtime_msgs)}"
            
            return msg
        except Exception as e:
            return f"Error connecting components: {str(e)}"

    def disconnect_components(self, ctx: Context, target_id: str, target_param: str, source_id: str = None) -> str:
        """Grasshopper: Disconnect wires from a component's input.
        
        Args:
            target_id: Instance GUID of the component to disconnect from
            target_param: Name or index of the input parameter to disconnect
            source_id: Optional. If provided, only disconnects the wire from this specific source. If omitted, disconnects ALL wires from the target param.
            
        Returns:
            Result message
        """
        try:
            connection = get_grasshopper_connection()
            result = connection.send_command("disconnect_components", {
                "target_id": target_id,
                "target_param": target_param,
                "source_id": source_id
            })
            if result.get("status") == "error":
                return f"Error: {result.get('result', 'Unknown error')}"
            return result.get("result", "Disconnected")
        except Exception as e:
            return f"Error disconnecting: {str(e)}"

    def set_component_value(self, ctx: Context, instance_guid: str, value: Any) -> str:
        """Grasshopper: Set a value for a specific component (Slider, Panel, Toggle).
        
        For Sliders, you can pass a single number or a dictionary/JSON string to set range:
        {"value": 10, "min": 0, "max": 100, "decimals": 0}
        
        Args:
            instance_guid: The GUID of the component
            value: The value to set (string, number, or property dict)
            
        Returns:
            Result message
        """
        try:
            connection = get_grasshopper_connection()
            result = connection.send_command("set_component_value", {
                "instance_guid": instance_guid,
                "value": value
            })
            if result.get("status") == "error":
                return f"Error: {result.get('result', 'Unknown error')}"
            return result.get("result", "Value set")
        except Exception as e:
            return f"Error setting value: {str(e)}"

    def set_component_state(self, ctx: Context, instance_guid: str, preview: bool = None, enabled: bool = None, locked: bool = None, wire_display: str = None) -> str:
        """Grasshopper: Set state (Preview, Enabled, Locked) for a component.
        
        Args:
            instance_guid: The GUID of the component
            preview: Set preview visibility (True/False)
            enabled: Set enabled state (True/False)
            locked: Set locked state (True/False). Locked components cannot be selected/modified in UI.
            wire_display: Wire display style ("default", "faint", "hidden")
            
        Returns:
            Result message
        """
        try:
            connection = get_grasshopper_connection()
            result = connection.send_command("set_component_state", {
                "instance_guid": instance_guid,
                "preview": preview,
                "enabled": enabled,
                "locked": locked,
                "wire_display": wire_display
            })
            if result.get("status") == "error":
                return f"Error: {result.get('result', 'Unknown error')}"
            return result.get("result", "State updated")
        except Exception as e:
            return f"Error setting state: {str(e)}"

    def create_group(self, ctx: Context, component_ids: List[str], group_name: str = "Group") -> str:
        """Grasshopper: Group selected components.
        
        Args:
            component_ids: List of component GUIDs to group
            group_name: Name/Label for the group
            
        Returns:
            GUID of the created group
        """
        try:
            connection = get_grasshopper_connection()
            result = connection.send_command("create_group", {
                "component_ids": component_ids,
                "group_name": group_name
            })
            if result.get("status") == "error":
                return f"Error: {result.get('result', 'Unknown error')}"
            return result.get("result", "Group created")
        except Exception as e:
            return f"Error creating group: {str(e)}"

    def delete_objects(self, ctx: Context, object_ids: List[str]) -> str:
        """Grasshopper: Delete specified objects from canvas.
        
        Args:
            object_ids: List of GUIDs to delete
            
        Returns:
            Result summary
        """
        try:
            connection = get_grasshopper_connection()
            result = connection.send_command("delete_objects", {
                "object_ids": object_ids
            })
            if result.get("status") == "error":
                return f"Error: {result.get('result', 'Unknown error')}"
            return result.get("result", "Deleted")
        except Exception as e:
            return f"Error deleting objects: {str(e)}"

    def clear_canvas(self, ctx: Context, confirm: bool = False) -> str:
        """Grasshopper: Clear all objects from the current canvas.
        
        Use with caution! This removes all components from the active document.
        
        Args:
            confirm: Must be set to True to execute
            
        Returns:
            Result message
        """
        if not confirm:
            return "Error: You must set confirm=True to clear the canvas."
            
        try:
            connection = get_grasshopper_connection()
            result = connection.send_command("clear_canvas", {
                "confirm": confirm
            })
            if result.get("status") == "error":
                return f"Error: {result.get('result', 'Unknown error')}"
            return result.get("result", "Canvas cleared")
        except Exception as e:
            return f"Error clearing canvas: {str(e)}"

    def get_canvas_stats(self, ctx: Context) -> str:
        """Grasshopper: Get statistics about the current canvas (object count, etc).
        
        Useful for a quick overview before getting full context.
        
        Returns:
            JSON string with canvas statistics
        """
        try:
            connection = get_grasshopper_connection()
            result = connection.send_command("get_canvas_stats", {})
            if result.get("status") == "error":
                return f"Error: {result.get('result', 'Unknown error')}"
            return json.dumps(result.get("result", {}), indent=2)
        except Exception as e:
            return f"Error getting stats: {str(e)}"

    def bake_objects(self, ctx: Context, object_ids: List[str]) -> str:
        """Grasshopper: Bake geometry from specified components to Rhino.
        
        Args:
            object_ids: List of component/parameter GUIDs to bake
            
        Returns:
            Result summary
        """
        try:
            connection = get_grasshopper_connection()
            result = connection.send_command("bake_objects", {
                "object_ids": object_ids
            })
            if result.get("status") == "error":
                return f"Error: {result.get('result', 'Unknown error')}"
            
            # If the result is a dictionary (new format), convert to string description
            res_val = result.get("result", "Bake completed")
            if isinstance(res_val, dict):
                return f"Bake completed. Count: {res_val.get('baked_count', 0)}, IDs: {res_val.get('ids', [])}"
            return str(res_val)
        except Exception as e:
            return f"Error baking objects: {str(e)}"

    def get_available_patterns(self, ctx: Context) -> str:
        """Grasshopper: Get a list of available patterns (recipes) for creating common Grasshopper definitions.
        
        These patterns provide templates for creating complex component networks.
        Each pattern includes a list of components and their connections.
        
        Returns:
            JSON string containing available patterns
        """
        return json.dumps(GH_PATTERNS, indent=2)
