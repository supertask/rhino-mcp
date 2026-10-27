"""Tools for interacting with Rhino through socket connection."""
from mcp.server.fastmcp import FastMCP, Context, Image
import logging
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Optional, Union
import json
import select
import socket
import threading
import time
import base64
import io
from PIL import Image as PILImage


# Configure logging
logger = logging.getLogger("RhinoTools")

# Commands that never change the Rhino document. Only these are re-sent
# automatically when the connection breaks after the command was sent.
READ_ONLY_COMMANDS = frozenset([
    "get_server_status",
    "get_scene_info",
    "get_layers",
    "get_objects_with_metadata",
])


class RhinoConnectionError(Exception):
    """The command was not delivered to Rhino (safe to try again)."""


class RhinoResultUnknownError(Exception):
    """The connection broke after the command was sent; Rhino may have run it."""


class RhinoCommandError(Exception):
    """Rhino received the command and reported an error."""


class RhinoConnection:
    def __init__(self, host='localhost', port=9876):
        self.host = host
        self.port = port
        self.socket = None
        self.timeout = 30.0  # 30 second timeout
        self.buffer_size = 14485760  # 10MB buffer size for handling large images
        self._lock = threading.Lock()

    def connect(self):
        """Connect to the Rhino script's socket server"""
        if self.socket is None:
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(self.timeout)
                self.socket.connect((self.host, self.port))
                logger.info("Connected to Rhino script")
            except Exception as e:
                logger.error("Failed to connect to Rhino script: {0}".format(str(e)))
                self.disconnect()
                raise

    def disconnect(self):
        """Disconnect from the Rhino script"""
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None

    def _is_stale(self) -> bool:
        """Check, without sending anything, whether the open socket is unusable.

        A connection opened before Rhino was restarted is readable (EOF or a
        reset) while no command is pending. Any unexpected data also means the
        stream is out of sync, so the socket must not be reused.
        """
        try:
            readable, _, _ = select.select([self.socket], [], [], 0)
            if not readable:
                return False
            self.socket.recv(1, socket.MSG_PEEK)
            return True
        except (OSError, ValueError):
            return True

    def _ensure_connected(self):
        """Make sure a usable socket exists. Nothing is sent to Rhino here."""
        if self.socket is not None and self._is_stale():
            logger.info("Existing connection to Rhino is no longer valid; reconnecting")
            self.disconnect()
        if self.socket is None:
            try:
                self.connect()
            except OSError as e:
                raise RhinoConnectionError(
                    "Rhinoに接続できません（{0}:{1}）。Rhinoが起動していて rhino_mcp_bridge.py が実行されているか確認してください。詳細: {2}".format(
                        self.host, self.port, e)) from e

    def _receive_response(self) -> Dict[str, Any]:
        """Read one JSON response. Raises OSError / socket.timeout on connection problems."""
        buffer = b''
        deadline = time.time() + self.timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise socket.timeout("Response timeout after {0} seconds".format(self.timeout))
            self.socket.settimeout(remaining)
            data = self.socket.recv(self.buffer_size)
            if not data:
                raise ConnectionAbortedError("Connection closed by Rhino script")
            buffer += data
            logger.debug("Received {0} bytes of data".format(len(data)))
            try:
                # ValueError covers both incomplete JSON and a split UTF-8 sequence
                return json.loads(buffer.decode('utf-8'))
            except ValueError:
                continue

    def _send_command_once(self, command_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_connected()

        command_json = json.dumps({
            "type": command_type,
            "params": params or {}
        })
        logger.info("Sending command: {0}".format(command_json))
        try:
            self.socket.settimeout(self.timeout)
            self.socket.sendall(command_json.encode('utf-8'))
            response = self._receive_response()
        except (OSError, ValueError) as e:
            # The stream can no longer be trusted (a late response would be
            # read as the answer to the next command), so always drop it.
            self.disconnect()
            raise RhinoResultUnknownError(str(e)) from e

        logger.info("Received complete response: {0}".format(response))
        if isinstance(response, dict) and response.get("status") == "error":
            raise RhinoCommandError(response.get("message", "Unknown error from Rhino"))
        return response

    def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send a command to the Rhino script and wait for response.

        A command is re-sent automatically only when it is read-only. For
        commands that may change the model, a broken connection after sending
        is reported as "result unknown" so the command is never run twice.
        """
        with self._lock:
            try:
                return self._send_command_once(command_type, params)
            except RhinoResultUnknownError as e:
                if command_type not in READ_ONLY_COMMANDS:
                    logger.error("Connection lost after sending {0}; not retrying: {1}".format(command_type, e))
                    raise RhinoResultUnknownError(
                        "Rhinoとの通信が処理の途中で切れました（{0}）。コマンド「{1}」がRhinoで実行されたかは不明です。"
                        "二重実行を防ぐため自動では再送していません。シーンの状態を確認してから、必要な場合だけ再実行してください。".format(
                            e, command_type)) from e
                logger.warning("Connection lost during read-only command {0}; retrying once: {1}".format(command_type, e))
            try:
                return self._send_command_once(command_type, params)
            except RhinoResultUnknownError as e:
                raise RhinoResultUnknownError(
                    "Rhinoとの通信に再接続後も失敗しました（{0}）。Rhinoの状態を確認してください。".format(e)) from e

# Global connection instance
_rhino_connection = None

def get_rhino_connection() -> RhinoConnection:
    """Get or create the Rhino connection"""
    global _rhino_connection
    if _rhino_connection is None:
        _rhino_connection = RhinoConnection()
    return _rhino_connection

class RhinoTools:
    """Collection of tools for interacting with Rhino."""
    
    def __init__(self, app):
        self.app = app
        self._register_tools()
    
    def _register_tools(self):
        """Register all Rhino tools with the MCP server."""
        self.app.tool()(self.get_scene_info)
        self.app.tool()(self.get_layers)
        self.app.tool()(self.get_scene_objects_with_metadata)
        self.app.tool()(self.capture_viewport)
        self.app.tool()(self.execute_rhino_code)
    
    def get_scene_info(self, ctx: Context) -> str:
        """Get basic information about the current Rhino scene.
        
        This is a lightweight function that returns basic scene information:
        - List of all layers with basic information about the layer and 5 sample objects with their metadata 
        - No metadata or detailed properties
        - Use this for quick scene overview or when you only need basic object information
        
        Returns:
            JSON string containing basic scene information
        """
        try:
            connection = get_rhino_connection()
            result = connection.send_command("get_scene_info")
            return json.dumps(result, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("Error getting scene info from Rhino: {0}".format(str(e)))
            return "Error getting scene info: {0}".format(str(e))

    def get_layers(self, ctx: Context) -> str:
        """Get list of layers in Rhino"""
        try:
            connection = get_rhino_connection()
            result = connection.send_command("get_layers")
            return json.dumps(result, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("Error getting layers from Rhino: {0}".format(str(e)))
            return "Error getting layers: {0}".format(str(e))

    def get_scene_objects_with_metadata(self, ctx: Context, filters: Optional[Dict[str, Any]] = None, metadata_fields: Optional[List[str]] = None) -> str:
        """Get detailed information about objects in the scene with their metadata.
        
        This is a CORE FUNCTION for scene context awareness. It provides:
        1. Full metadata for each object we created via this mcp connection including:
           - short_id (DDHHMMSS format), can be dispalyed in the viewport when using capture_viewport, can help yo uto visually identify the a object and find it with this function
           - created_at timestamp
           - layer  - layer path
           - type - geometry type 
           - bbox - the bounding box as lsit of points
           - name - the name you assigned 
           - description - description yo uasigned 
        
        2. Advanced filtering capabilities:
           - layer: Filter by layer name (supports wildcards, e.g., "Layer*")
           - name: Filter by object name (supports wildcards, e.g., "Cube*")
           - short_id: Filter by exact short ID match
        
        3. Field selection:
           - Can specify which metadata fields to return
           - Useful for reducing response size when only certain fields are needed
        
        Args:
            filters: Optional dictionary of filters to apply
            metadata_fields: Optional list of specific metadata fields to return
        
        Returns:
            JSON string containing filtered objects with their metadata
        """
        try:
            connection = get_rhino_connection()
            result = connection.send_command("get_objects_with_metadata", {
                "filters": filters or {},
                "metadata_fields": metadata_fields
            })
            return json.dumps(result, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("Error getting objects with metadata: {0}".format(str(e)))
            return "Error getting objects with metadata: {0}".format(str(e))

    def capture_viewport(self, ctx: Context, layer: Optional[str] = None, show_annotations: bool = True, max_size: int = 800, view: Optional[Union[str, List[str]]] = None, zoom_extents: bool = True) -> list:
        """Capture the current viewport as an image.
        
        Args:
            layer: Optional layer name to filter annotations
            show_annotations: Whether to show object annotations, this will display the short_id of the object in the viewport you can use the short_id to select specific objects with the get_objects_with_metadata function
            view: Optional view name(s) to capture. Can be a single string (e.g. "Top", "Active"), a list of strings, or "All" for 7-view capture. Defaults to 4-view capture (Perspective, Top, Front, Right).
            zoom_extents: Whether to perform Zoom Extents before capturing to fit all objects in view. Defaults to True.
        
        Returns:
            A list of MCP Image objects containing the viewport capture(s)
        """
        try:
            # Handle "All" shortcut for 7-side capture
            target_view = view
            if isinstance(view, str) and view.lower() == "all":
                # Order matters: Top->Bottom (reuses Top), Front->Back (reuses Front), Right->Left (reuses Right), then Perspective
                target_view = ["Top", "Bottom", "Front", "Back", "Right", "Left", "Perspective"]
            
            connection = get_rhino_connection()
            result = connection.send_command("capture_viewport", {
                "layer": layer,
                "show_annotations": show_annotations,
                "max_size": max_size,
                "view": target_view,
                "zoom_extents": zoom_extents
            })
            
            output_images = []
            
            # Handle single image response (backward compatibility)
            if result.get("type") == "image":
                base64_data = result["source"]["data"]
                output_images.append(self._process_image_data(base64_data))
                
            # Handle multi-image response
            elif result.get("type") == "multi_image":
                for img_data in result.get("images", []):
                    base64_data = img_data["data"]
                    # We could also use img_data["label"] if needed
                    output_images.append(self._process_image_data(base64_data))
            
            elif result.get("type") == "error":
                 raise Exception(result.get("message", "Unknown error"))
            
            if not output_images:
                raise Exception(result.get("text", "Failed to capture viewport"))
                
            return output_images
                
        except Exception as e:
            logger.error("Error capturing viewport: {0}".format(str(e)))
            raise

    def _process_image_data(self, base64_data: str) -> Image:
        """Helper to convert base64 data to MCP Image"""
        # Convert base64 to bytes
        image_bytes = base64.b64decode(base64_data)
        
        # Return as MCP Image object in JPEG format (smaller size for VLM efficiency)
        return Image(data=image_bytes, format="jpeg")

    def execute_rhino_code(self, ctx: Context, code: str) -> str:
        """Execute arbitrary Python code in Rhino.
        
        IMPORTANT NOTES FOR CODE EXECUTION:
        0. DONT FORGET NO f-strings! No f-strings, No f-strings!
        1. This is Rhino 7 with IronPython 2.7 - no f-strings or modern Python features
        3. When creating objects, ALWAYS call add_object_metadata(name, description) after creation
        4. For user interaction, you can use RhinoCommon syntax (selected_objects = rs.GetObjects("Please select some objects") etc.) prompted the suer what to do 
           but prefer automated solutions unless user interaction is specifically requested
        
        The add_object_metadata() function is provided in the code context and must be called
        after creating any object. It adds standardized metadata including:
        - name (provided by you)
        - description (provided by you)
        The metadata helps you to identify and select objects later in the scene and stay organised.

        Common Syntax Errors to Avoid:
        2. No walrus operator (:=)
        3. No type hints
        4. No modern Python features (match/case, etc.)
        5. No list/dict comprehensions with multiple for clauses
        6. No assignment expressions in if/while conditions

        Example of proper object creation:
        <<<python
        # Create geometry
        cube_id = rs.AddBox(rs.WorldXYPlane(), 5, 5, 5)
            # Add metadata - ALWAYS do this after creating an object
        add_object_metadata(cube_id, "My Cube", "A test cube created via MCP")

        >>>

        DONT FORGET NO f-strings! No f-strings, No f-strings!
        """
        try:
            code_template = """
import rhinoscriptsyntax as rs
import scriptcontext as sc
import json
import time
from datetime import datetime

def add_object_metadata(obj_id, name=None, description=None):
    \"\"\"Add standardized metadata to an object\"\"\"
    try:
        # Generate short ID
        short_id = datetime.now().strftime("%d%H%M%S")
        
        # Get bounding box
        bbox = rs.BoundingBox(obj_id)
        bbox_data = [[p.X, p.Y, p.Z] for p in bbox] if bbox else []
        
        # Get object type
        obj = sc.doc.Objects.Find(obj_id)
        obj_type = obj.Geometry.GetType().Name if obj else "Unknown"
        
        # Standard metadata
        metadata = {
            "short_id": short_id,
            "created_at": time.time(),
            "layer": rs.ObjectLayer(obj_id),
            "type": obj_type,
            "bbox": bbox_data
        }
        
        # User-provided metadata
        if name:
            rs.ObjectName(obj_id, name)
            metadata["name"] = name
        else:
            auto_name = "{0}_{1}".format(obj_type, short_id)
            rs.ObjectName(obj_id, auto_name)
            metadata["name"] = auto_name
            
        if description:
            metadata["description"] = description
            
        # Store metadata as user text
        user_text_data = metadata.copy()
        user_text_data["bbox"] = json.dumps(bbox_data)
        
        for key, value in user_text_data.items():
            rs.SetUserText(obj_id, key, str(value))
            
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

""" + code
            logger.info("Sending code execution request to Rhino")
            connection = get_rhino_connection()
            result = connection.send_command("execute_code", {"code": code_template})
            
            logger.info("Received response from Rhino: {0}".format(result))
            
            # Simplified error handling
            if result.get("status") == "error":
                error_msg = "Error: {0}".format(result.get("message", "Unknown error"))
                logger.error("Code execution error: {0}".format(error_msg))
                return error_msg
            else:
                response = result.get("result", "Code executed successfully")
                logger.info("Code execution successful: {0}".format(response))
                return response
                
        except Exception as e:
            error_msg = "Error executing code: {0}".format(str(e))
            logger.error(error_msg)
            return error_msg