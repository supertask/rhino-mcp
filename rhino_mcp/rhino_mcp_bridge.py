# -*- coding: utf-8 -*-
"""
Rhino MCP - Rhino-side Script
Handles communication with external MCP server and executes Rhino commands.
"""

import socket
import threading
import json
import time
import System
import Rhino
import scriptcontext as sc
import rhinoscriptsyntax as rs
import os
import platform
import traceback
import sys
import base64
import subprocess
from System.Drawing import Bitmap
from System.Drawing.Imaging import ImageFormat
from System.IO import MemoryStream
from datetime import datetime

# Configuration
HOST = 'localhost'
PORT = 9876
LANGUAGE = 'ja'  # 'en' for English, 'ja' for Japanese

# Add constant for annotation layer
ANNOTATION_LAYER = "MCP_Annotations"

MESSAGES = {
    'en': {
        'zombie_killed_socket': "[Rhino MCP] Detected zombie process (Headless Server) on port {0}. Stopped it successfully. Retrying bind...",
        'zombie_killed_os': "[Rhino MCP] Success: Force killed zombie Rhino.exe (PID: {1}) on port {0}. Restarting server...",
        'server_is_active_ui': "[Rhino MCP] Port {0} is held by an active Rhino instance (UI is visible).  Rhino MCP Server start aborted.",
        'port_in_use_check': "[Rhino MCP] Port {0} is in use. Checking for zombie process...",
        'server_already_running': "[Rhino MCP] Server is already running",
        'port_in_use': "[Rhino MCP] Error: Port {0} is already in use!",
        'check_other_instance': "[Rhino MCP] Please check if another Rhino instance is running.",
        'server_started': "[Rhino MCP] Rhino Internal MCP Bridge started on {0}:{1}",
        'start_failed': "[Rhino MCP] Failed to start server: {0}",
        'server_stopped': "[Rhino MCP] Rhino Internal MCP Bridge stopped",
        'scene_info_start': "[Rhino MCP] Getting simplified scene info...",
        'scene_info_success': "[Rhino MCP] Simplified scene info collected successfully",
        'script_loaded': "[Rhino MCP] RhinoMCP script loaded. Server started automatically.",
        'stop_instruction': "[Rhino MCP] To stop the server, run: stop_server()"
    },
    'ja': {
        'zombie_killed_socket': u"[Rhino MCP] ポート{0}を使用中のゾンビプロセス（Headless）を検出・停止しました。再起動します...",
        'zombie_killed_os': u"[Rhino MCP] 正常：ポート{0}を使用中のゾンビアプリのRhino.exe（PID: {1}）を強制終了してサーバを再起動します...",
        'server_is_active_ui': u"[Rhino MCP] ポート{0}は現在使用中のRhino（UIあり）によって使用されています。Rhinoアプリ内部 MCPブリッジの起動を中止します。",
        'port_in_use_check': u"[Rhino MCP] ポート{0}は使用中です。ゾンビプロセスの確認中...",
        'server_already_running': u"[Rhino MCP] サーバーは既に起動しています",
        'port_in_use': u"[Rhino MCP] エラー: ポート {0} は既に使用されています！",
        'check_other_instance': u"[Rhino MCP] 他のRhinoが起動していないか確認してください（タスクマネージャー等）。",
        'server_started': u"[Rhino MCP] Rhinoアプリ内部 MCPブリッジを起動しました: {0}:{1}",
        'start_failed': u"[Rhino MCP] サーバーの起動に失敗しました: {0}",
        'server_stopped': u"[Rhino MCP] Rhinoアプリ内部 MCPブリッジを停止しました",
        'scene_info_start': u"[Rhino MCP] シーン情報を取得中...",
        'scene_info_success': u"[Rhino MCP] シーン情報の取得に成功しました",
        'script_loaded': u"[Rhino MCP] RhinoMCPスクリプトが読み込まれました。サーバーは自動的に起動しました。",
        'stop_instruction': u"[Rhino MCP] サーバーを停止するには、次を実行してください: stop_server()"
    }
}

def get_message(key, *args):
    """Get localized message"""
    lang = MESSAGES.get(LANGUAGE, MESSAGES['en'])
    msg = lang.get(key, MESSAGES['en'].get(key, key))
    if args:
        return msg.format(*args)
    return msg

VALID_METADATA_FIELDS = {
    'required': ['id', 'name', 'type', 'layer'],
    'optional': [
        'short_id',      # Short identifier (DDHHMMSS format)
        'created_at',    # Timestamp of creation
        'bbox',          # Bounding box coordinates
        'description',   # Object description
        'user_text'      # All user text key-value pairs
    ]
}

def get_log_dir():
    """Get the appropriate log directory based on the platform"""
    home_dir = os.path.expanduser("~")
    
    # Platform-specific log directory
    if platform.system() == "Darwin":  # macOS
        log_dir = os.path.join(home_dir, "Library", "Application Support", "RhinoMCP", "logs")
    elif platform.system() == "Windows":
        log_dir = os.path.join(home_dir, "AppData", "Local", "RhinoMCP", "logs")
    else:  # Linux and others
        log_dir = os.path.join(home_dir, ".rhino_mcp", "logs")
    
    return log_dir

def log_message(message):
    """Log a message to both Rhino's command line and log file"""
    # Print to Rhino's command line
    Rhino.RhinoApp.WriteLine(message)
    
    # Log to file
    try:
        log_dir = get_log_dir()
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        log_file = os.path.join(log_dir, "rhino_mcp.log")
        
        # Log platform info on first run
        if not os.path.exists(log_file):
            with open(log_file, "w") as f:
                f.write("=== RhinoMCP Log ===\n")
                f.write("Platform: {0}\n".format(platform.system()))
                f.write("Python Version: {0}\n".format(sys.version))
                f.write("Rhino Version: {0}\n".format(Rhino.RhinoApp.Version))
                f.write("==================\n\n")
        
        with open(log_file, "a") as f:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            # Encode message to UTF-8 before writing to file
            if isinstance(message, unicode):
                message = message.encode('utf-8')
            f.write("[{0}] {1}\n".format(timestamp, message))
    except Exception as e:
        Rhino.RhinoApp.WriteLine("Failed to write to log file: {0}".format(str(e)))

class RhinoMCPServer:
    def __init__(self, host='localhost', port=9876):
        self.host = host
        self.port = port
        self.running = False
        self.socket = None
        self.server_thread = None
    
    def start(self):
        if self.running:
            # log_message(get_message('server_already_running'))
            return
            
        self.running = True
        
        try:
            # Create socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            
            # Windowsの場合、SO_REUSEADDR（ポートの再利用）を設定しないことで
            # 重複起動時にしっかりとエラーが出るようにします
            if platform.system() != "Windows":
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            try:
                self.socket.bind((self.host, self.port))
            except socket.error as e:
                # ポートが使用中の場合、ゾンビ（デーモン）サーバーか確認してキルを試みる
                # log_message(get_message('port_in_use', self.port))
                
                killed = False
                
                # Zombie check
                # Returns: 0=Error/NoConnect, 1=Killed(Headless), 2=Alive(UI)
                zombie_status = self._try_kill_zombie_server()
                
                if zombie_status == 1:
                    killed = True
                    log_message(get_message('zombie_killed_socket', self.port))
                elif zombie_status == 2:
                    # Alive UI - Do not touch
                    pass
                else:
                    # Connection failed -> Force kill check
                    killed_os, pid = self._force_kill_port_holder()
                    if killed_os:
                        killed = True
                        log_message(get_message('zombie_killed_os', self.port, pid))

                if killed:
                    time.sleep(1.0) # ポート解放待ち
                    try:
                        self.socket.bind((self.host, self.port))
                    except socket.error:
                        log_message("Failed to bind even after killing zombie.")
                        self.running = False
                        self.socket = None
                        return
                else:
                    if zombie_status != 1 and zombie_status != 2: # Only show if we didn't identify it
                         log_message(get_message('port_in_use', self.port))
                    
                if zombie_status == 2:
                    pass
                else:
                    log_message(get_message('check_other_instance'))
                
                # エラーを再送出してサーバー起動を中断させます
                self.running = False
                self.socket = None
                return

            self.socket.listen(1)
            
            # Start server thread
            self.server_thread = threading.Thread(target=self._server_loop)
            self.server_thread.daemon = True
            self.server_thread.start()
            
            log_message(get_message('server_started', self.host, self.port))
        except Exception as e:
            log_message(get_message('start_failed', str(e)))
            self.stop()
            
    def _force_kill_port_holder(self):
        """
        ポートを使用しているプロセスを特定し、RhinoであればOSレベルで強制終了する
        Returns: (bool killed, str pid)
        """
        try:
            # Windows only for now
            if platform.system() != "Windows":
                return False, None

            # 1. netstatでPIDを特定
            # cmd: netstat -ano | findstr :9876
            cmd = 'netstat -ano | findstr :{}'.format(self.port)
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, _ = proc.communicate()
            
            if not stdout:
                return False, None # ポート使用者は見つからなかった

            # 行を解析してPIDを取得 (TCP 127.0.0.1:9876 ... LISTENING 1234)
            lines = stdout.strip().split('\n')
            target_pid = None
            for line in lines:
                parts = line.split()
                # アドレス部分が :PORT で終わるかチェック
                if len(parts) > 1 and str(self.port) in parts[1]:
                    target_pid = parts[-1] # 最後の要素がPID
                    break
            
            if not target_pid:
                return False, None

            # 2. tasklistでプロセス名を確認
            # cmd: tasklist /FI "PID eq 1234" /FO CSV /NH
            cmd = 'tasklist /FI "PID eq {}" /FO CSV /NH'.format(target_pid)
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, _ = proc.communicate()
            
            if not stdout:
                return False, None

            # 出力例: "Rhino.exe","1234","Console","1","150,000 K"
            process_info = stdout.strip()
            # プロセス名が Rhino 関連かチェック
            is_rhino = "rhino" in process_info.lower()
            
            if is_rhino:
                # log_message("Found Rhino process (PID: {}) holding port {}. Force killing...".format(target_pid, self.port))
                # 3. taskkillで強制終了
                subprocess.call('taskkill /F /PID {}'.format(target_pid), shell=True)
                return True, target_pid
            else:
                log_message("Port {} is held by non-Rhino process (PID: {}). Skipping kill.".format(self.port, target_pid))
                return False, target_pid

        except Exception as e:
            log_message("Error in force kill: {}".format(e))
            return False, None

    def _try_kill_zombie_server(self):
        """
        既知のポートに接続し、サーバーがHeadless（デーモン）であれば停止させる
        Returns: 0=Error/NoConnect, 1=Killed(Headless), 2=Alive(UI)
        """
        try:
            temp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            temp_socket.settimeout(2.0)
            temp_socket.connect((self.host, self.port))
            
            # ステータス確認コマンド送信
            cmd = json.dumps({"type": "get_server_status"})
            temp_socket.sendall(cmd.encode('utf-8'))
            
            # 応答待機
            data = temp_socket.recv(4096)
            if not data:
                return 0
                
            response = json.loads(data.decode('utf-8'))
            is_headless = response.get("headless", False)
            
            if is_headless:
                # log_message("Found headless server. Sending stop command...")
                # 停止コマンド送信
                stop_cmd = json.dumps({"type": "stop_server"})
                temp_socket.sendall(stop_cmd.encode('utf-8'))
                temp_socket.close()
                return 1
            else:
                log_message(get_message('server_is_active_ui', self.port))
                temp_socket.close()
                return 2
                
        except Exception as e:
            # log_message("Could not contact existing server: {0}".format(str(e)))
            return 0
            
    def stop(self):
        # 既に停止していれば何もしない
        if not self.running:
            return

        self.running = False
        
        # Close socket
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        
        # Wait for thread to finish
        if self.server_thread:
            try:
                if self.server_thread.is_alive():
                    self.server_thread.join(timeout=1.0)
            except:
                pass
            self.server_thread = None
        
        log_message(get_message('server_stopped'))
    
    def _server_loop(self):
        """Main server loop that accepts connections"""
        while self.running:
            try:
                client, addr = self.socket.accept()
                # log_message(get_message('client_connected', addr[0], addr[1]))
                
                # Handle client in a new thread
                client_thread = threading.Thread(target=self._handle_client, args=(client,))
                client_thread.daemon = True
                client_thread.start()
                
            except Exception as e:
                if self.running:
                    log_message("[Rhino MCP] Error accepting connection: {0}".format(str(e)))
                    time.sleep(0.5)
    
    def _handle_client(self, client):
        """Handle a client connection"""
        try:
            # Set socket buffer size
            client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 14485760)  # 10MB
            client.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 14485760)  # 10MB
            
            while self.running:
                # Receive command with larger buffer
                data = client.recv(14485760)  # 10MB buffer
                if not data:
                    # log_message(get_message('client_disconnected'))
                    break
                    
                try:
                    command = json.loads(data.decode('utf-8'))
                    cmd_type = command.get("type", "unknown")
                    # ステータス確認などの頻繁なログは抑制
                    if cmd_type != "get_server_status":
                        log_message("[Rhino MCP] コマンド受信: {0}".format(cmd_type))
                    
                    # Create a closure to capture the client connection
                    def execute_wrapper():
                        try:
                            response = self.execute_command(command)
                            response_json = json.dumps(response)
                            # Split large responses into chunks if needed
                            chunk_size = 14485760  # 10MB chunks
                            response_bytes = response_json.encode('utf-8')
                            for i in range(0, len(response_bytes), chunk_size):
                                chunk = response_bytes[i:i + chunk_size]
                                client.sendall(chunk)
                            # log_message(get_message('response_sent'))
                        except Exception as e:
                            log_message("[Rhino MCP] Error executing command: {0}".format(str(e)))
                            traceback.print_exc()
                            error_response = {
                                "status": "error",
                                "message": str(e)
                            }
                            try:
                                client.sendall(json.dumps(error_response).encode('utf-8'))
                            except Exception as e:
                                log_message("[Rhino MCP] Failed to send error response: {0}".format(str(e)))
                                return False  # Signal connection should be closed
                        return True  # Signal connection should stay open
                    
                    # Use RhinoApp.Idle event for IronPython 2.7 compatibility
                    def idle_handler(sender, e):
                        if not execute_wrapper():
                            # If execute_wrapper returns False, close the connection
                            try:
                                client.close()
                            except:
                                pass
                        # Remove the handler after execution
                        Rhino.RhinoApp.Idle -= idle_handler
                    
                    Rhino.RhinoApp.Idle += idle_handler
                    
                except ValueError as e:
                    # Handle JSON decode error (IronPython 2.7)
                    log_message("Invalid JSON received: {0}".format(str(e)))
                    error_response = {
                        "status": "error",
                        "message": "Invalid JSON format"
                    }
                    try:
                        client.sendall(json.dumps(error_response).encode('utf-8'))
                    except:
                        break  # Close connection on send error
                
        except Exception as e:
            log_message("Error handling client: {0}".format(str(e)))
            traceback.print_exc()
        finally:
            try:
                client.close()
            except:
                pass
    
    def execute_command(self, command):
        """Execute a command received from the client"""
        try:
            command_type = command.get("type")
            params = command.get("params", {})
            
            if command_type == "get_server_status":
                is_headless = False
                try:
                    # Rhino 7以降のプロパティ。古いバージョンではAttributeErrorになるため保護
                    is_headless = Rhino.RhinoApp.IsRunningHeadless
                except:
                    pass
                return {
                    "status": "success",
                    "headless": is_headless,
                    "pid": os.getpid()
                }
                
            elif command_type == "stop_server":
                log_message("Received stop_server command.")
                # 自身の停止処理を別スレッド（またはアイドル後）に予約
                def stop_action():
                    self.stop()
                    # 必要であればここでRhino自体を終了する処理も書けるが、
                    # あくまでサーバー停止にとどめるのが無難
                Rhino.RhinoApp.InvokeOnUiThread(System.Action(stop_action))
                return {"status": "success", "message": "Server stopping..."}
            
            elif command_type == "get_scene_info":
                return self._get_scene_info(params)
            elif command_type == "create_cube":
                return self._create_cube(params)
            elif command_type == "get_layers":
                return self._get_layers()
            elif command_type == "execute_code":
                return self._execute_code(params)
            elif command_type == "get_objects_with_metadata":
                return self._get_objects_with_metadata(params)
            elif command_type == "capture_viewport":
                return self._capture_viewport(params)
            elif command_type == "add_metadata":
                return self._add_object_metadata(
                    params.get("object_id"), 
                    params.get("name"), 
                    params.get("description")
                )
            else:
                return {"status": "error", "message": "Unknown command type"}
                
        except Exception as e:
            log_message("Error executing command: {0}".format(str(e)))
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    
    def _get_scene_info(self, params=None):
        """Get simplified scene information focusing on layers and example objects"""
        try:
            doc = sc.doc
            if not doc:
                return {
                    "status": "error",
                    "message": "No active document"
                }
            
            log_message(get_message('scene_info_start'))
            layers_info = []
            
            for layer in doc.Layers:
                layer_objects = [obj for obj in doc.Objects if obj.Attributes.LayerIndex == layer.Index]
                example_objects = []
                
                for obj in layer_objects[:5]:  # Limit to 5 example objects per layer
                    try:
                        # Convert NameValueCollection to dictionary
                        user_strings = {}
                        if obj.Attributes.GetUserStrings():
                            for key in obj.Attributes.GetUserStrings():
                                user_strings[key] = obj.Attributes.GetUserString(key)
                        
                        obj_info = {
                            "id": str(obj.Id),
                            "name": obj.Name or "Unnamed",
                            "type": obj.Geometry.GetType().Name if obj.Geometry else "Unknown",
                            "metadata": user_strings  # Now using the converted dictionary
                        }
                        example_objects.append(obj_info)
                    except Exception as e:
                        log_message("Error processing object: {0}".format(str(e)))
                        continue
                
                layer_info = {
                    "full_path": layer.FullPath,
                    "object_count": len(layer_objects),
                    "is_visible": layer.IsVisible,
                    "is_locked": layer.IsLocked,
                    "example_objects": example_objects
                }
                layers_info.append(layer_info)
            
            response = {
                "status": "success",
                "layers": layers_info
            }
            
            log_message(get_message('scene_info_success'))
            return response
            
        except Exception as e:
            log_message("Error getting simplified scene info: {0}".format(str(e)))
            return {
                "status": "error",
                "message": str(e),
                "layers": []
            }
    
    def _create_cube(self, params):
        """Create a cube in the scene"""
        try:
            size = float(params.get("size", 1.0))
            location = params.get("location", [0, 0, 0])
            name = params.get("name", "Cube")
            
            # Create cube using RhinoCommon
            box = Rhino.Geometry.Box(
                Rhino.Geometry.Plane.WorldXY,
                Rhino.Geometry.Interval(0, size),
                Rhino.Geometry.Interval(0, size),
                Rhino.Geometry.Interval(0, size)
            )
            
            # Move to specified location
            transform = Rhino.Geometry.Transform.Translation(
                location[0] - box.Center.X,
                location[1] - box.Center.Y,
                location[2] - box.Center.Z
            )
            box.Transform(transform)
            
            # Add to document
            id = sc.doc.Objects.AddBox(box)
            if id != System.Guid.Empty:
                obj = sc.doc.Objects.Find(id)
                if obj:
                    obj.Name = name
                    sc.doc.Views.Redraw()
                    return {
                        "status": "success",
                        "message": "Created cube with size {0}".format(size),
                        "id": str(id)
                    }
            
            return {"status": "error", "message": "Failed to create cube"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def _get_layers(self):
        """Get information about all layers"""
        try:
            doc = sc.doc
            layers = []
            
            for layer in doc.Layers:
                layers.append({
                    "id": layer.Index,
                    "name": layer.Name,
                    "object_count": layer.ObjectCount,
                    "is_visible": layer.IsVisible,
                    "is_locked": layer.IsLocked
                })
            
            return {
                "status": "success",
                "layers": layers
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def _execute_code(self, params):
        """Execute arbitrary Python code"""
        try:
            code = params.get("code", "")
            if not code:
                return {"status": "error", "message": "No code provided"}
            
            log_message("Executing code: {0}".format(code))
            
            # Create a new scope for code execution
            local_dict = {}
            
            try:
                # Execute the code
                exec(code, globals(), local_dict)
                
                # Get result from local_dict or use a default message
                result = local_dict.get("result", "Code executed successfully")
                log_message("Code execution completed. Result: {0}".format(result))
                
                response = {
                    "status": "success",
                    "result": str(result),
                    "variables": {k: str(v) for k, v in local_dict.items() if not k.startswith('__')}
                }
                
                log_message("Sending response: {0}".format(json.dumps(response)))
                return response
                
            except Exception as e:
                hint = "Did you use f-string formatting? You have to use IronPython here that doesn't support this."
                error_response = {
                    "status": "error",
                    "message": "{0} {1}".format(hint, str(e)),
                }
                log_message("Error: {0}".format(error_response))
                return error_response
                
        except Exception as e:
            hint = "Did you use f-string formatting? You have to use IronPython here that doesn't support this."
            error_response = {
                "status": "error",
                "message": "{0} {1}".format(hint, str(e)),
            }
            log_message("System error: {0}".format(error_response))
            return error_response

    def _add_object_metadata(self, obj_id, name=None, description=None):
        """Add standardized metadata to an object"""
        try:
            import json
            import time
            from datetime import datetime
            
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
                # Auto-generate name if none provided
                auto_name = "{0}_{1}".format(obj_type, short_id)
                rs.ObjectName(obj_id, auto_name)
                metadata["name"] = auto_name
                
            if description:
                metadata["description"] = description
                
            # Store metadata as user text (convert bbox to string for storage)
            user_text_data = metadata.copy()
            user_text_data["bbox"] = json.dumps(bbox_data)
            
            # Add all metadata as user text
            for key, value in user_text_data.items():
                rs.SetUserText(obj_id, key, str(value))
                
            return {"status": "success"}
        except Exception as e:
            log_message("Error adding metadata: " + str(e))
            return {"status": "error", "message": str(e)}

    def _get_objects_with_metadata(self, params):
        """Get objects with their metadata, with optional filtering"""
        try:
            import re
            import json
            
            filters = params.get("filters", {})
            metadata_fields = params.get("metadata_fields")
            layer_filter = filters.get("layer")
            name_filter = filters.get("name")
            id_filter = filters.get("short_id")
            
            # Validate metadata fields
            all_fields = VALID_METADATA_FIELDS['required'] + VALID_METADATA_FIELDS['optional']
            if metadata_fields:
                invalid_fields = [f for f in metadata_fields if f not in all_fields]
                if invalid_fields:
                    return {
                        "status": "error",
                        "message": "Invalid metadata fields: " + ", ".join(invalid_fields),
                        "available_fields": all_fields
                    }
            
            objects = []
            
            for obj in sc.doc.Objects:
                obj_id = obj.Id
                
                # Apply filters
                if layer_filter:
                    layer = rs.ObjectLayer(obj_id)
                    pattern = "^" + layer_filter.replace("*", ".*") + "$"
                    if not re.match(pattern, layer, re.IGNORECASE):
                        continue
                    
                if name_filter:
                    name = obj.Name or ""
                    pattern = "^" + name_filter.replace("*", ".*") + "$"
                    if not re.match(pattern, name, re.IGNORECASE):
                        continue
                    
                if id_filter:
                    short_id = rs.GetUserText(obj_id, "short_id") or ""
                    if short_id != id_filter:
                        continue
                    
                # Build base object data with required fields
                obj_data = {
                    "id": str(obj_id),
                    "name": obj.Name or "Unnamed",
                    "type": obj.Geometry.GetType().Name,
                    "layer": rs.ObjectLayer(obj_id)
                }
                
                # Get user text data and parse stored values
                stored_data = {}
                for key in rs.GetUserText(obj_id):
                    value = rs.GetUserText(obj_id, key)
                    if key == "bbox":
                        try:
                            value = json.loads(value)
                        except:
                            value = []
                    elif key == "created_at":
                        try:
                            value = float(value)
                        except:
                            value = 0
                    stored_data[key] = value
                
                # Build metadata based on requested fields
                if metadata_fields:
                    metadata = {k: stored_data[k] for k in metadata_fields if k in stored_data}
                else:
                    metadata = {k: v for k, v in stored_data.items() 
                              if k not in VALID_METADATA_FIELDS['required']}
                
                # Only include user_text if specifically requested
                if not metadata_fields or 'user_text' in metadata_fields:
                    user_text = {k: v for k, v in stored_data.items() 
                               if k not in metadata}
                    if user_text:
                        obj_data["user_text"] = user_text
                
                # Add metadata if we have any
                if metadata:
                    obj_data["metadata"] = metadata
                    
                objects.append(obj_data)
            
            return {
                "status": "success",
                "count": len(objects),
                "objects": objects,
                "available_fields": all_fields
            }
            
        except Exception as e:
            log_message("Error filtering objects: " + str(e))
            return {
                "status": "error",
                "message": str(e),
                "available_fields": all_fields
            }

    def _capture_single_view(self, view_name, max_size, should_zoom_extents, show_annotations, layer_name, temp_dots_created=False):
        """Helper to capture a single view. Assumes setup (layers etc) is done."""
        original_view = None
        pushed_projection = False
        active_viewport = sc.doc.Views.ActiveView.ActiveViewport
        
        try:
            # Handle view switching
            if view_name:
                # First, try to find an existing view with the given name
                target_view = sc.doc.Views.Find(view_name, False)
                if target_view:
                    # If found, switch to it
                    if sc.doc.Views.ActiveView.MainViewport.Id != target_view.MainViewport.Id:
                        if original_view is None:
                            original_view = sc.doc.Views.ActiveView
                        sc.doc.Views.ActiveView = target_view
                    active_viewport = sc.doc.Views.ActiveView.ActiveViewport
                else:
                    # If not found, use camera manipulation on the active view (fallback)
                    tv_lower = view_name.lower()
                    is_standard_view = False
                    
                    # Setup camera vectors based on view
                    cam_loc = None
                    cam_target = Rhino.Geometry.Point3d.Origin
                    cam_up = Rhino.Geometry.Vector3d.ZAxis
                    target_projection_mode = 1 # 1=Parallel, 2=Perspective
                    
                    if tv_lower == "top":
                        cam_loc = Rhino.Geometry.Point3d(0, 0, 100)
                        cam_up = Rhino.Geometry.Vector3d.YAxis
                        is_standard_view = True
                    elif tv_lower == "bottom":
                        cam_loc = Rhino.Geometry.Point3d(0, 0, -100)
                        cam_up = Rhino.Geometry.Vector3d.YAxis
                        is_standard_view = True
                    elif tv_lower == "right":
                        cam_loc = Rhino.Geometry.Point3d(100, 0, 0)
                        is_standard_view = True
                    elif tv_lower == "left":
                        cam_loc = Rhino.Geometry.Point3d(-100, 0, 0)
                        is_standard_view = True
                    elif tv_lower == "front":
                        cam_loc = Rhino.Geometry.Point3d(0, -100, 0)
                        is_standard_view = True
                    elif tv_lower == "back":
                        cam_loc = Rhino.Geometry.Point3d(0, 100, 0)
                        is_standard_view = True
                    elif tv_lower == "perspective":
                        # 右斜め手前上空からのアングル (Right-Front-Top)
                        # 右45度、上45度（仰角45度）からの俯瞰
                        # XY距離(sqrt(100^2 + 100^2) ≈ 141.4)と同じ高さをZに設定することで45度になる
                        cam_loc = Rhino.Geometry.Point3d(100, -100, 142)
                        target_projection_mode = 2
                        is_standard_view = True

                    if is_standard_view:
                        # Save current state and switch projection
                        if not pushed_projection:
                            active_viewport.PushViewProjection()
                            pushed_projection = True
                        
                        # Special handling for Perspective to ensure correct angle relative to object
                        if tv_lower == "perspective" and should_zoom_extents:
                            # 1. Zoom Extents first to center on objects (without changing angle yet)
                            selected_objects = rs.SelectedObjects()
                            if selected_objects:
                                active_viewport.ZoomBoundingBox(rs.BoundingBox(selected_objects))
                            else:
                                active_viewport.ZoomExtents()
                            
                            # 2. Get new target (center of view/object)
                            target = active_viewport.CameraTarget
                            
                            # 3. Calculate new camera location relative to target
                            # Right 45, Up 45 -> Vector (1, -1, sqrt(2)) normalized * distance
                            dist = target.DistanceTo(active_viewport.CameraLocation)
                            if dist < 100: dist = 200 # Minimum distance if too close
                            
                            # Direction: X=1, Y=-1, Z=1.414 (tan(45deg)=1, so Z should equal XY-dist. XY-dist of (1,1) is sqrt(2)=1.414. So Z=1.414)
                            offset = Rhino.Geometry.Vector3d(1, -1, 1.4142)
                            offset.Unitize()
                            offset *= dist
                            
                            new_loc = target + offset
                            
                            try:
                                rs.ViewProjection(None, 2) # Perspective
                                rs.ViewCameraTarget(None, new_loc, target)
                                rs.ViewCameraUp(None, Rhino.Geometry.Vector3d.ZAxis)
                            except Exception as e:
                                log_message("Error setting perspective camera: " + str(e))
                            
                            # Disable standard zoom extents as we handled it
                            should_zoom_extents = False 
                            
                        else:
                            # Apply view settings using rhinoscriptsyntax for safety
                            try:
                                # Force projection mode first
                                rs.ViewProjection(None, target_projection_mode)
                                
                                # Then set camera
                                rs.ViewCameraTarget(None, cam_loc, cam_target)
                                rs.ViewCameraUp(None, cam_up)
                                
                            except Exception as e:
                                 log_message("Error setting camera: " + str(e))
                             
                    else:
                        log_message("Warning: View '{0}' not found. Using active view.".format(view_name))

            # Handle Zoom Extents
            if should_zoom_extents:
                if not pushed_projection:
                    active_viewport.PushViewProjection()
                    pushed_projection = True
                
                # Check if objects are selected
                selected_objects = rs.SelectedObjects()
                if selected_objects:
                    active_viewport.ZoomBoundingBox(rs.BoundingBox(selected_objects))
                else:
                    active_viewport.ZoomExtents()
                    # After ZoomExtents, check if any objects were actually in view.
                    # Sometimes ZoomExtents fails quietly or does weird things if no objects are visible/exist.
                    pass 


            # Apply changes
            if pushed_projection or original_view:
                sc.doc.Views.Redraw()
            
            # Capture
            view = sc.doc.Views.ActiveView
            memory_stream = MemoryStream()
            
            bitmap = view.CaptureToBitmap()
            
            width, height = bitmap.Width, bitmap.Height
            if width > height:
                new_width = max_size
                new_height = int(height * (max_size / width))
            else:
                new_height = max_size
                new_width = int(width * (max_size / height))
            
            resized_bitmap = Bitmap(bitmap, new_width, new_height)
            resized_bitmap.Save(memory_stream, ImageFormat.Jpeg)
            
            bytes_array = memory_stream.ToArray()
            image_data = base64.b64encode(bytes(bytearray(bytes_array))).decode('utf-8')
            
            bitmap.Dispose()
            resized_bitmap.Dispose()
            memory_stream.Dispose()
            
            return {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": image_data,
                "label": view_name or "Active"
            }
            
        finally:
            # Restore view state
            if pushed_projection:
                vp = sc.doc.Views.ActiveView.ActiveViewport
                vp.PopViewProjection()
                sc.doc.Views.Redraw()

            if original_view and original_view != sc.doc.Views.ActiveView:
                sc.doc.Views.ActiveView = original_view

    def _capture_viewport(self, params):
        """Capture viewport(s) with optional annotations and layer filtering"""
        original_layer_name = rs.CurrentLayer()
        temp_dots = []
        
        try:
            layer_name = params.get("layer")
            show_annotations = params.get("show_annotations", True)
            max_size = params.get("max_size", 800)
            target_view = params.get("view")
            should_zoom_extents = params.get("zoom_extents", True)
            
            # Setup annotations (once for all views)
            if show_annotations:
                if not rs.IsLayer(ANNOTATION_LAYER):
                    rs.AddLayer(ANNOTATION_LAYER, color=(255, 0, 0))
                rs.CurrentLayer(ANNOTATION_LAYER)
                
                # Iterate over all objects in the document
                all_objects = sc.doc.Objects
                if all_objects:
                     for obj in all_objects:
                        if layer_name and rs.ObjectLayer(obj.Id) != layer_name:
                            continue
                        
                        # Only annotate if selected or if nothing is selected (show all)
                        if rs.SelectedObjects() and not rs.IsObjectSelected(obj.Id):
                            continue

                        bbox = rs.BoundingBox(obj.Id)
                        if bbox:
                            pt = bbox[1]
                            short_id = rs.GetUserText(obj.Id, "short_id")
                            if not short_id:
                                short_id = datetime.now().strftime("%d%H%M%S")
                                rs.SetUserText(obj.Id, "short_id", short_id)
                            
                            name = rs.ObjectName(obj.Id) or "Unnamed"
                            text = "{0}\\n{1}".format(name, short_id)
                            
                            dot_id = rs.AddTextDot(text, pt)
                            rs.TextDotHeight(dot_id, 8)
                            temp_dots.append(dot_id)

            # Determine views to capture
            views_to_capture = []
            # Ensure target_view is a list of strings if it's not None
            if isinstance(target_view, list):
                # Convert all elements to string just in case
                views_to_capture = [str(v) for v in target_view]
            elif target_view:
                # "Active" keyword to capture only the current active view
                if str(target_view).lower() == "active":
                    views_to_capture = [None]
                else:
                    views_to_capture = [str(target_view)]
            else:
                # Default to standard 4-view layout if no view is specified
                views_to_capture = ["Perspective", "Top", "Front", "Right"]

            images = []
            for v_name in views_to_capture:
                # Pre-switch active view for specific standard views to ensure correct base viewport is used
                # This prevents e.g. "Left" being captured using "Top" viewport, which might leave "Top" viewport in a weird state
                # The _capture_single_view function restores the active view to what it was when called.
                if v_name:
                    v_lower = v_name.lower()
                    base_view = None
                    if v_lower == "bottom":
                        base_view = sc.doc.Views.Find("Top", False)
                    elif v_lower == "back":
                        base_view = sc.doc.Views.Find("Front", False)
                    elif v_lower == "left":
                        base_view = sc.doc.Views.Find("Right", False)
                    
                    if base_view:
                        sc.doc.Views.ActiveView = base_view

                img_data = self._capture_single_view(
                    v_name, max_size, should_zoom_extents, 
                    show_annotations, layer_name, temp_dots_created=True
                )
                images.append(img_data)
            
            return {
                "type": "multi_image",
                "images": images
            }
            
        except Exception as e:
            log_message("Error capturing viewport: " + str(e))
            return {
                "type": "error",
                "message": "Error capturing viewport: " + str(e)
            }
            
        finally:
            if temp_dots:
                rs.DeleteObjects(temp_dots)
            
            try:
                if original_layer_name and rs.IsLayer(original_layer_name):
                    rs.CurrentLayer(original_layer_name)
            except:
                pass

# Create and start server
server = RhinoMCPServer(HOST, PORT)
# server.start() # Removed duplicate call

# Add commands to Rhino
def start_server():
    """Start the RhinoMCP server"""
    server.start()

def stop_server():
    """Stop the RhinoMCP server"""
    server.stop()

# Automatically start the server when this script is loaded
start_server()
# log_message(get_message('script_loaded'))
# log_message(get_message('stop_instruction')) 