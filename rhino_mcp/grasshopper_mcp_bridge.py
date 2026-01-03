import scriptcontext as sc
import clr
import socket
import threading
import select
import Rhino
import Rhino.Geometry as rg
import json
import traceback
import time
import System
import os
import platform
import subprocess
from System import Guid, Action
from System.Drawing import RectangleF

# Explicitly add reference to Grasshopper assembly
try:
    clr.AddReference("Grasshopper")
except Exception:
    pass

import Grasshopper
import Grasshopper as gh
from Grasshopper.Kernel import GH_ParamAccess, IGH_Param, GH_RuntimeMessageLevel
from Grasshopper.Kernel.Parameters import (
    Param_GenericObject, Param_String, Param_Number,
    Param_Integer, Param_Boolean, Param_Guid, Param_Point,
    Param_Vector, Param_Curve, Param_Surface, Param_Brep, Param_Mesh
)

# --- Constants ---
HOST = "127.0.0.1"
PORT = 9999
SERVER_NAME = "Rhino-Grasshopperアプリ内部 MCPブリッジ・サーバー"
LANGUAGE = 'ja'  # 'en' for English, 'ja' for Japanese

MESSAGES = {
    'en': {
        'zombie_killed_socket': "[GH MCP] Detected zombie process (Headless Server) on port {0}. Stopped it successfully. Retrying bind...",
        'zombie_killed_os': "[GH MCP] Success: Force killed zombie Rhino.exe (PID: {1}) on port {0}. Restarting server...",
        'server_is_active_ui': "[GH MCP] Port {0} is held by an active Rhino instance (UI is visible). Grasshopper MCP Server start aborted.",
        'port_in_use_check': "[GH MCP] Port {0} is in use. Checking for zombie process...",
        'server_already_running': "[GH MCP] Server is already running",
        'port_in_use': "[GH MCP] Error: Port {0} is already in use!",
        'check_other_instance': "[GH MCP] Please check if another Rhino instance is running.",
        'server_started': "[GH MCP] Rhino-Grasshopper Internal MCP Bridge started on {0}:{1}",
        'start_failed': "[GH MCP] Failed to start server: {0}",
        'server_stopped': "[GH MCP] Rhino-Grasshopper Internal MCP Bridge Stopped"
    },
    'ja': {
        'zombie_killed_socket': u"[GH MCP] ポート{0}を使用中のゾンビプロセス（Headless）を検出・停止しました。再起動します...",
        'zombie_killed_os': u"[GH MCP] 正常：ポート{0}を使用中のゾンビアプリのRhino.exe（PID: {1}）を強制終了してサーバを再起動します...",
        'server_is_active_ui': u"[GH MCP] ポート{0}は現在使用中のRhino（UIあり）によって使用されています。Rhino-Grasshopperアプリ内部 MCPブリッジの起動を中止します。",
        'port_in_use_check': u"[GH MCP] ポート{0}は使用中です。ゾンビプロセスの確認中...",
        'server_already_running': u"[GH MCP] サーバーは既に起動しています",
        'port_in_use': u"[GH MCP] エラー: ポート {0} は既に使用されています！",
        'check_other_instance': u"[GH MCP] 他のRhinoが起動していないか確認してください（タスクマネージャー等）。",
        'server_started': u"[GH MCP] Rhino-Grasshopperアプリ内部 MCPブリッジを起動しました: {0}:{1}",
        'start_failed': u"[GH MCP] サーバーの起動に失敗しました: {0}",
        'server_stopped': u"[GH MCP] Rhino-Grasshopperアプリ内部 MCPブリッジを停止しました"
    }
}

def get_message(key, *args):
    """Get localized message"""
    lang = MESSAGES.get(LANGUAGE, MESSAGES['en'])
    msg = lang.get(key, MESSAGES['en'].get(key, key))
    if args:
        return msg.format(*args)
    return msg

# --- Helper: Get Active Document ---
def get_active_gh_doc():
    """Retrieves the currently active Grasshopper document safely."""
    if not Grasshopper.Instances.ActiveCanvas:
        return None
    return Grasshopper.Instances.ActiveCanvas.Document

# --- JSON Encoding ---
class GHEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, System.Guid):
            return str(obj)
        elif isinstance(obj, rg.Point3d):
            return {"x": float(obj.X), "y": float(obj.Y), "z": float(obj.Z)}
        elif isinstance(obj, RectangleF):
            return {"x": float(obj.X), "y": float(obj.Y), "width": float(obj.Width), "height": float(obj.Height)}
        try:
            return json.JSONEncoder.default(self, obj)
        except TypeError:
            return repr(obj)

# --- Script Context Sticky Management ---
default_sticky = {
    "gh_mcp_run_server": False,
    "gh_mcp_server_thread": None,
    "gh_mcp_status": "Server Off",
    "gh_mcp_last_error": None
}
for key, value in default_sticky.items():
    if key not in sc.sticky:
        sc.sticky[key] = value

# --- Helper Functions (Param Types) ---
def get_access_enum(access_str):
    if isinstance(access_str, str):
        s = access_str.lower()
        if s == "item": return GH_ParamAccess.item
        elif s == "tree": return GH_ParamAccess.tree
    return GH_ParamAccess.list

def get_access_string(gh_param_access):
    if gh_param_access == GH_ParamAccess.item: return "item"
    elif gh_param_access == GH_ParamAccess.tree: return "tree"
    return "list"

def create_gh_input_param(param_def, default_description="Input parameter"):
    name = param_def.get("name", "input")
    nick_name = param_def.get("nickName", name) or name
    hint = param_def.get("typehint", "generic").lower()
    description = param_def.get("description", default_description)
    access = get_access_enum(param_def.get("access", "list"))
    optional = param_def.get("optional", True)

    if hint == "str": param = Param_String()
    elif hint == "int": param = Param_Integer()
    elif hint == "float": param = Param_Number()
    elif hint == "bool": param = Param_Boolean()
    elif hint == "guid": param = Param_Guid()
    elif hint == "point": param = Param_Point()
    elif hint == "vector": param = Param_Vector()
    elif hint == "curve": param = Param_Curve()
    elif hint == "surface": param = Param_Surface()
    elif hint == "brep": param = Param_Brep()
    elif hint == "mesh": param = Param_Mesh()
    else: param = Param_GenericObject()

    param.Name = name
    param.NickName = nick_name
    param.Description = description
    param.Access = access
    param.Optional = optional
    return param

def create_gh_output_param(param_def, default_description="Output parameter"):
    name = param_def.get("name", "output")
    nick_name = param_def.get("nickName", name) or name
    description = param_def.get("description", default_description)
    param = Param_GenericObject()
    param.Name = name
    param.NickName = nick_name
    param.Description = description
    return param

# --- Grasshopper Object Info ---
def get_param_info(param, is_input=True, parent_instance_guid=None, is_selected=False, simplified=False):
    guid_str = str(param.InstanceGuid)
    parent_guid_str = str(parent_instance_guid) if parent_instance_guid else None
    nick_name = param.NickName or param.Name
    
    sources_list = []
    targets_list = []
    try:
        if hasattr(param, "Sources"):
            sources_list = [str(src.InstanceGuid) for src in param.Sources if src]
        if hasattr(param, "Recipients"):
            targets_list = [str(tgt.InstanceGuid) for tgt in param.Recipients if tgt]
        
        if parent_guid_str:
            if is_input:
                 if parent_guid_str not in targets_list: targets_list.append(parent_guid_str)
            else:
                 if parent_guid_str not in sources_list: sources_list.append(parent_guid_str)
    except Exception:
        pass

    if simplified:
        return {
            "instanceGuid": guid_str,
            "parentInstanceGuid": parent_guid_str,
            "name": param.Name,
            "nickName": nick_name,
            "kind": "parameter",
            "sources": sources_list,
            "targets": targets_list,
            "isSelected": is_selected,
            "isInput": is_input,
        }

    bounds_rect = {}
    pivot_pt = {}
    try:
        if hasattr(param, "Attributes") and param.Attributes:
            bounds = param.Attributes.Bounds
            bounds_rect = RectangleF(bounds.X, (bounds.Y * -1) - bounds.Height, bounds.Width, bounds.Height)
            pivot_pt = rg.Point3d(param.Attributes.Pivot.X, param.Attributes.Pivot.Y * -1, 0)
    except: pass

    param_info = {
        "instanceGuid": guid_str,
        "parentInstanceGuid": parent_guid_str,
        "bounds": bounds_rect,
        "pivot": pivot_pt,
        "name": param.Name,
        "nickName": nick_name,
        "description": param.Description,
        "kind": "parameter",
        "sources": sources_list,
        "targets": targets_list,
        "isSelected": is_selected,
        "isInput": is_input,
        "access": get_access_string(param.Access) if hasattr(param, 'Access') else None,
        "optional": param.Optional if hasattr(param, 'Optional') else None,
        "dataType": str(param.TypeName) if hasattr(param, 'TypeName') else None
    }

    if not parent_guid_str:
        if isinstance(param, Grasshopper.Kernel.Special.GH_NumberSlider):
            param_info["kind"] = "slider"
            try:
                param_info["slider"] = {
                    "min": float(param.Slider.Minimum),
                    "max": float(param.Slider.Maximum),
                    "value": float(param.Slider.Value),
                    "decimals": int(param.Slider.DecimalPlaces),
                    "type": str(param.Slider.Type)
                }
            except: pass
        elif isinstance(param, Grasshopper.Kernel.Special.GH_Panel):
            param_info["kind"] = "panel"
            try: param_info["panelContent"] = param.UserText
            except: pass

    return param_info

def get_component_info(comp, is_selected=False, simplified=False):
    guid_str = str(comp.InstanceGuid)
    nick_name = comp.NickName or comp.Name
    
    pivot_pt = {}
    aggregated_sources = set()
    aggregated_targets = set()
    runtime_messages = []
    param_guids = set()

    if hasattr(comp, "Attributes") and comp.Attributes:
        pivot_pt = rg.Point3d(comp.Attributes.Pivot.X, comp.Attributes.Pivot.Y * -1, 0)

    try:
        messages = comp.RuntimeMessages(comp.RuntimeMessageLevel)
        runtime_messages = [str(m) for m in messages] if messages else []
    except: pass

    if hasattr(comp, "Params"):
        if hasattr(comp.Params, "Input"):
            for p in comp.Params.Input:
                p_guid = str(p.InstanceGuid)
                param_guids.add(p_guid)
                param_info_temp = get_param_info(p, is_input=True, parent_instance_guid=comp.InstanceGuid, simplified=True)
                if param_info_temp: aggregated_sources.update(param_info_temp.get("sources", []))
        if hasattr(comp.Params, "Output"):
            for p in comp.Params.Output:
                p_guid = str(p.InstanceGuid)
                param_guids.add(p_guid)
                param_info_temp = get_param_info(p, is_input=False, parent_instance_guid=comp.InstanceGuid, simplified=True)
                if param_info_temp: aggregated_targets.update(param_info_temp.get("targets", []))

    final_sources = list(s for s in aggregated_sources if s != guid_str and s not in param_guids)
    final_targets = list(t for t in aggregated_targets if t != guid_str and t not in param_guids)

    kind = str(comp.Kind) if hasattr(comp, 'Kind') else str(comp.__class__.__name__)

    if simplified:
        return {
            "instanceGuid": guid_str,
            "name": comp.Name,
            "nickName": nick_name,
            "description": comp.Description,
            "kind": kind,
            "pivot": pivot_pt,
            "sources": final_sources,
            "targets": final_targets,
            "isSelected": is_selected,
            "runtimeMessages": runtime_messages
        }

    bounds_rect = {}
    if hasattr(comp, "Attributes") and comp.Attributes:
        bounds = comp.Attributes.Bounds
        bounds_rect = RectangleF(bounds.X, (bounds.Y * -1) - bounds.Height, bounds.Width, bounds.Height)

    comp_info = {
        "instanceGuid": guid_str,
        "name": comp.Name,
        "nickName": nick_name,
        "description": comp.Description,
        "kind": kind,
        "bounds": bounds_rect,
        "pivot": pivot_pt,
        "isSelected": is_selected,
        "runtimeMessages": runtime_messages,
        "Inputs": [],
        "Outputs": [],
        "sources": final_sources,
        "targets": final_targets,
    }

    if hasattr(comp, "Code"):
        comp_info["isScriptComponent"] = True
        comp_info["Code"] = comp.Code
        comp_info["codeReferenceFromFile"] = False
        comp_info["codeReferencePath"] = None
        if hasattr(comp, "InputIsPath"):
            comp_info["codeReferenceFromFile"] = comp.InputIsPath
            if comp.InputIsPath and hasattr(comp, "Params") and hasattr(comp.Params, "Input"):
                code_param = next((p for p in comp.Params.Input if (p.NickName or p.Name).lower() == "code"), None)
                if code_param and code_param.VolatileDataCount > 0:
                     path_data = code_param.VolatileData.get_Branch(0)
                     if path_data and len(path_data) > 0:
                        comp_info["codeReferencePath"] = str(path_data[0])

    if hasattr(comp, "Params"):
        if hasattr(comp.Params, "Input"):
            for p in comp.Params.Input:
                p_info = get_param_info(p, is_input=True, parent_instance_guid=comp.InstanceGuid, simplified=False)
                if p_info: comp_info["Inputs"].append(p_info)
        if hasattr(comp.Params, "Output"):
            for p in comp.Params.Output:
                p_info = get_param_info(p, is_input=False, parent_instance_guid=comp.InstanceGuid, simplified=False)
                if p_info: comp_info["Outputs"].append(p_info)

    return comp_info

# --- Document Traversal ---
def get_all_relevant_objects_info(doc, selected_guids_set=None, simplified=False):
    graph = {}
    if selected_guids_set is None: selected_guids_set = set()
    for obj in doc.Objects:
        if not hasattr(obj, "InstanceGuid"): continue
        guid_str = str(obj.InstanceGuid)
        is_selected = guid_str in selected_guids_set
        info = None
        if isinstance(obj, Grasshopper.Kernel.IGH_Component):
            info = get_component_info(obj, is_selected=is_selected, simplified=simplified)
        elif isinstance(obj, Grasshopper.Kernel.IGH_Param):
            parent_comp = obj.Attributes.Parent if hasattr(obj, "Attributes") and obj.Attributes else None
            if not parent_comp:
                info = get_param_info(obj, is_input=False, parent_instance_guid=None, is_selected=is_selected, simplified=simplified)
        if info: graph[guid_str] = info
    return graph

def get_objects_with_context(target_guids, context_depth=0, simplified=False):
    doc = get_active_gh_doc()
    if not doc: return {}
    target_guids_set = set(str(g) for g in target_guids)
    all_objects_info = get_all_relevant_objects_info(doc, selected_guids_set=target_guids_set, simplified=simplified)
    
    result_graph = {}
    guids_to_include = set()

    for guid_str in target_guids_set:
        if guid_str in all_objects_info:
            guids_to_include.add(guid_str)
        else:
            # Try finding if it's a child param
            obj = doc.FindObject(Guid.Parse(guid_str), True)
            if obj and isinstance(obj, IGH_Param):
                parent = obj.Attributes.Parent
                if parent and str(parent.InstanceGuid) in all_objects_info:
                    p_guid = str(parent.InstanceGuid)
                    guids_to_include.add(p_guid)
                    if not all_objects_info[p_guid]['isSelected']: all_objects_info[p_guid]['isSelected'] = True

    if context_depth > 0 and guids_to_include:
        max_depth = min(int(context_depth), 3)
        current_level = set(guids_to_include)
        visited = set(guids_to_include)
        for _ in range(max_depth):
            next_level = set()
            for guid in current_level:
                if guid not in all_objects_info: continue
                node = all_objects_info[guid]
                neighbors = set(node.get("sources", [])) | set(node.get("targets", []))
                for n_guid in neighbors:
                    if n_guid in all_objects_info and n_guid not in visited:
                        next_level.add(n_guid)
                        visited.add(n_guid)
                        guids_to_include.add(n_guid)
            if not next_level: break
            current_level = next_level

    for guid in guids_to_include:
        if guid in all_objects_info:
            result_graph[guid] = all_objects_info[guid]
    return result_graph

# --- Operations ---
def expire_grasshopper_component(doc, instance_guid_str):
    if not doc: return {"status": "error", "result": "No document"}
    try:
        target_guid = System.Guid(instance_guid_str)
        obj = doc.FindObject(target_guid, True)
        if not obj: return {"status": "error", "result": "Object not found"}
        obj.ExpireSolution(True)
        if isinstance(obj, Grasshopper.Kernel.IGH_Component):
            return {"status": "success", "result": get_component_info(obj)}
        elif isinstance(obj, Grasshopper.Kernel.IGH_Param):
            return {"status": "success", "result": get_param_info(obj, is_input=False)}
        return {"status": "success", "result": "Expired"}
    except Exception as e:
        return {"status": "error", "result": str(e)}

def _update_script_component_on_ui_thread(instance_guid_str, code, description, message_to_user, param_definitions):
    doc = get_active_gh_doc()
    if not doc: return {"status": "error", "result": "No active GH document"}
    
    try:
        comp = doc.FindObject(Guid.Parse(instance_guid_str), False)
        if not comp or not hasattr(comp, "Code"):
            return {"status": "error", "result": "Target not found or not a script component"}

        # Store connections
        old_input_conn = {}
        old_output_conn = {}
        if hasattr(comp.Params, "Input"):
            for p in comp.Params.Input:
                if p.Sources: old_input_conn[p.NickName or p.Name] = [s for s in p.Sources if s]
        if hasattr(comp.Params, "Output"):
            for p in comp.Params.Output:
                if p.Recipients: old_output_conn[p.NickName or p.Name] = [r for r in p.Recipients if r]

        canvas = gh.Instances.ActiveCanvas
        if canvas: canvas.Document.Enabled = False
        
        new_inputs = {}
        new_outputs = {}
        params_updated = False

        try:
            if param_definitions:
                # Update Params Logic (Simplified for brevity but functionally same as source)
                # 1. Register Dummies
                d_in = create_gh_input_param({"name": "_d_in"})
                d_out = create_gh_output_param({"name": "_d_out"})
                comp.Params.RegisterInputParam(d_in)
                comp.Params.RegisterOutputParam(d_out)
                
                # 2. Remove others
                for p in [x for x in comp.Params.Input if x.InstanceGuid != d_in.InstanceGuid]: comp.Params.UnregisterInputParameter(p)
                for p in [x for x in comp.Params.Output if x.InstanceGuid != d_out.InstanceGuid]: comp.Params.UnregisterOutputParameter(p)

                # 3. Add New
                for p_def in param_definitions:
                    ptype = p_def.get("type", "").lower()
                    if ptype == "input":
                        p = create_gh_input_param(p_def)
                        comp.Params.RegisterInputParam(p)
                        new_inputs[p.NickName or p.Name] = p
                    elif ptype == "output":
                        p = create_gh_output_param(p_def)
                        comp.Params.RegisterOutputParam(p)
                        new_outputs[p.NickName or p.Name] = p
                
                # Ensure 'output'
                if "output" not in new_outputs:
                    p = create_gh_output_param({"name": "output"})
                    comp.Params.RegisterOutputParam(p)
                    new_outputs["output"] = p

                # 4. Remove Dummies
                comp.Params.UnregisterInputParameter(d_in)
                comp.Params.UnregisterOutputParameter(d_out)
                comp.Params.OnParametersChanged()
                params_updated = True

            # Restore Connections
            if params_updated:
                for name, p in new_inputs.items():
                    if name in old_input_conn:
                        for src in old_input_conn[name]: p.AddSource(src)
                for name, p in new_outputs.items():
                    if name in old_output_conn:
                        for rec in old_output_conn[name]: rec.AddSource(p)

            if code is not None: comp.Code = str(code)
            if description is not None: comp.Description = str(description)
            if message_to_user:
                out_p = next((p for p in comp.Params.Output if (p.NickName or p.Name) == "output"), None)
                if out_p:
                    out_p.ClearData()
                    out_p.AddVolatileData(Grasshopper.Kernel.Data.GH_Path(0), 0, str(message_to_user))

            if hasattr(comp, "Attributes"): comp.Attributes.ExpireLayout()
            comp.ExpireSolution(True)
            return {"status": "success", "result": "Updated successfully"}

        except Exception as e:
            return {"status": "error", "result": str(e)}
        finally:
            if canvas: 
                canvas.Document.Enabled = True
                canvas.Refresh()

    except Exception as e:
        return {"status": "error", "result": traceback.format_exc()}

def update_script_component(instance_guid, **kwargs):
    result_holder = {}
    def ui_action():
        result_holder["res"] = _update_script_component_on_ui_thread(instance_guid, kwargs.get("code"), kwargs.get("description"), kwargs.get("message_to_user"), kwargs.get("param_definitions"))
    Rhino.RhinoApp.InvokeOnUiThread(Action(ui_action))
    return result_holder.get("res", {"status": "error", "result": "UI Action failed"})

def _update_code_ref_ui(instance_guid_str, file_path, param_definitions, description, name, force):
    doc = get_active_gh_doc()
    if not doc: return {"status": "error", "result": "No active doc"}
    
    try:
        comp = doc.FindObject(Guid.Parse(instance_guid_str), False)
        if not comp: return {"status": "error", "result": "Component not found"}
        
        # Save connections logic (same as above, simplified)
        old_input_conn = {}
        old_output_conn = {}
        if hasattr(comp.Params, "Input"):
            for p in comp.Params.Input:
                 if p.Sources: old_input_conn[p.NickName or p.Name] = [s for s in p.Sources if s]
        if hasattr(comp.Params, "Output"):
            for p in comp.Params.Output:
                 if p.Recipients: old_output_conn[p.NickName or p.Name] = [r for r in p.Recipients if r]

        canvas = gh.Instances.ActiveCanvas
        if canvas: canvas.Document.Enabled = False
        
        try:
            code_param = next((p for p in comp.Params.Input if (p.NickName or p.Name).lower() == "code"), None)
            
            if force or file_path:
                if not comp.InputIsPath: comp.InputIsPath = True
                if not code_param:
                    if hasattr(comp, "ConstructCodeInputParameter"):
                        code_param = comp.ConstructCodeInputParameter()
                        code_param.NickName = "code"; code_param.Name = "code"
                        comp.Params.RegisterInputParam(code_param)
            
            # Update Params
            new_inputs = {}; new_outputs = {}
            if param_definitions:
                d_in = create_gh_input_param({"name": "_d"})
                d_out = create_gh_output_param({"name": "_d"})
                comp.Params.RegisterInputParam(d_in); comp.Params.RegisterOutputParam(d_out)
                
                code_guid = code_param.InstanceGuid if code_param else None
                
                for p in [x for x in comp.Params.Input if x.InstanceGuid != d_in.InstanceGuid and x.InstanceGuid != code_guid]: comp.Params.UnregisterInputParameter(p)
                for p in [x for x in comp.Params.Output if x.InstanceGuid != d_out.InstanceGuid]: comp.Params.UnregisterOutputParameter(p)
                
                for p_def in param_definitions:
                    p_name = p_def.get("nickName", p_def.get("name", "")).lower()
                    if p_name == "code": continue
                    if p_def.get("type") == "input":
                        p = create_gh_input_param(p_def)
                        comp.Params.RegisterInputParam(p)
                        new_inputs[p.NickName or p.Name] = p
                    elif p_def.get("type") == "output":
                        p = create_gh_output_param(p_def)
                        comp.Params.RegisterOutputParam(p)
                        new_outputs[p.NickName or p.Name] = p
                
                if "output" not in new_outputs:
                     p = create_gh_output_param({"name": "output"})
                     comp.Params.RegisterOutputParam(p)
                     new_outputs["output"] = p
                     
                comp.Params.UnregisterInputParameter(d_in); comp.Params.UnregisterOutputParameter(d_out)
                comp.Params.OnParametersChanged()

                # Restore connections
                for name, p in new_inputs.items():
                    if name in old_input_conn:
                        for src in old_input_conn[name]: p.AddSource(src)
                for name, p in new_outputs.items():
                    if name in old_output_conn:
                        for rec in old_output_conn[name]: rec.AddSource(p)
            
            if description: comp.Description = str(description)
            if name: comp.NickName = str(name)
            
            if file_path:
                if not code_param: code_param = next((p for p in comp.Params.Input if (p.NickName or p.Name).lower() == "code"), None)
                if code_param:
                    comp.InputIsPath = True
                    code_param.ClearData()
                    code_param.AddVolatileData(Grasshopper.Kernel.Data.GH_Path(0), 0, str(file_path))
            
            if hasattr(comp, "Attributes"): comp.Attributes.ExpireLayout()
            comp.ExpireSolution(True)
            return {"status": "success", "result": "Updated Ref"}
            
        finally:
            if canvas: canvas.Document.Enabled = True; canvas.Refresh()
            
    except Exception as e:
        return {"status": "error", "result": str(e)}

def update_script_with_code_reference(instance_guid, **kwargs):
    result_holder = {}
    def ui_action():
        result_holder["res"] = _update_code_ref_ui(instance_guid, kwargs.get("file_path"), kwargs.get("param_definitions"), kwargs.get("description"), kwargs.get("name"), kwargs.get("force_code_reference"))
    Rhino.RhinoApp.InvokeOnUiThread(Action(ui_action))
    return result_holder.get("res", {"status": "error", "result": "UI Action failed"})

# --- Command Processing ---
def process_command(cmd):
    ctype = cmd.get("type")
    if ctype == "test":
        return {"status": "success", "result": "Rhino-MCP Alive"}
    
    elif ctype == "get_context":
        doc = get_active_gh_doc()
        if not doc: return {"status": "error", "result": "No Active Document"}
        return {"status": "success", "result": get_all_relevant_objects_info(doc, simplified=cmd.get("simplified", False))}
    
    elif ctype == "expire_component":
        doc = get_active_gh_doc()
        return expire_grasshopper_component(doc, cmd.get("instance_guid"))
        
    elif ctype == "get_objects":
        return {"status": "success", "result": get_objects_with_context(cmd.get("instance_guids", []), cmd.get("context_depth", 0), cmd.get("simplified", False))}
        
    elif ctype == "get_selected":
        doc = get_active_gh_doc()
        if not doc: return {"status": "error", "result": "No Doc"}
        selected = [str(o.InstanceGuid) for o in doc.Objects if o.Attributes.Selected]
        return {"status": "success", "result": get_objects_with_context(selected, cmd.get("context_depth", 0), cmd.get("simplified", False))}
        
    elif ctype == "update_script":
        return update_script_component(**cmd)
        
    elif ctype == "update_script_with_code_reference":
        return update_script_with_code_reference(**cmd)
        
    elif ctype == "execute_code":
        try:
            loc = {}
            exec(cmd.get("code", ""), globals(), loc)
            return {"status": "success", "result": str(loc.get("result", "Executed"))}
        except Exception as e:
            return {"status": "error", "result": str(e)}

    elif ctype == "get_server_status":
        is_headless = False
        try:
            is_headless = Rhino.RhinoApp.IsRunningHeadless
        except:
            pass
        return {
            "status": "success", 
            "headless": is_headless,
            "pid": os.getpid()
        }

    elif ctype == "stop_server":
        # Schedule stop
        def stop_action():
            sc.sticky["gh_mcp_run_server"] = False
        Rhino.RhinoApp.InvokeOnUiThread(Action(stop_action))
        return {"status": "success", "message": "Server stopping..."}
            
    return {"status": "error", "result": "Unknown command"}

# --- Server Loop ---
def _try_kill_zombie_server():
    """
    Returns: 0=Error/NoConnect, 1=Killed(Headless), 2=Alive(UI)
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect((HOST, PORT))
        
        body = json.dumps({"type": "get_server_status"})
        req = "POST / HTTP/1.1\r\nContent-Length: {}\r\n\r\n{}".format(len(body), body)
        s.sendall(req.encode())
        
        # Read response
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk: break
            data += chunk
            if b"\r\n\r\n" in data:
                head, body_part = data.split(b"\r\n\r\n", 1)
                cl = 0
                for line in head.decode().split("\r\n"):
                    if "content-length:" in line.lower():
                        cl = int(line.lower().split(":")[1].strip())
                while len(body_part) < cl:
                    body_part += s.recv(4096)
                data = body_part
                break
        
        try:
            res = json.loads(data.decode())
        except:
            return 0

        if res.get("headless"):
            # Rhino.RhinoApp.WriteLine("[MCP] Found headless zombie. Killing...")
            s.close()
            
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((HOST, PORT))
            body = json.dumps({"type": "stop_server"})
            req = "POST / HTTP/1.1\r\nContent-Length: {}\r\n\r\n{}".format(len(body), body)
            s.sendall(req.encode())
            s.close()
            return 1
        else:
            Rhino.RhinoApp.WriteLine(get_message('server_is_active_ui', PORT))
            s.close()
            return 2

    except Exception as e:
        # Rhino.RhinoApp.WriteLine("[MCP] Zombie check failed: {}".format(e))
        return 0

def _force_kill_port_holder():
    """
    Returns: (bool killed, str pid)
    """
    try:
        if platform.system() != "Windows":
            return False, None

        cmd = 'netstat -ano | findstr :{}'.format(PORT)
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, _ = proc.communicate()
        
        if not stdout:
            return False, None

        lines = stdout.strip().split('\n')
        target_pid = None
        for line in lines:
            parts = line.split()
            if len(parts) > 1 and str(PORT) in parts[1]:
                target_pid = parts[-1]
                break
        
        if not target_pid:
            return False, None

        cmd = 'tasklist /FI "PID eq {}" /FO CSV /NH'.format(target_pid)
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, _ = proc.communicate()
        
        if not stdout:
            return False, None

        process_info = stdout.strip()
        is_rhino = "rhino" in process_info.lower()
        
        if is_rhino:
            subprocess.call('taskkill /F /PID {}'.format(target_pid), shell=True)
            return True, target_pid
        else:
            Rhino.RhinoApp.WriteLine("Port {} is held by non-Rhino process (PID: {}). Skipping kill.".format(PORT, target_pid))
            return False, target_pid

    except Exception as e:
        Rhino.RhinoApp.WriteLine("Error in force kill: {}".format(e))
        return False, None

def server_loop():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if platform.system() != "Windows":
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        try:
            server.bind((HOST, PORT))
        except socket.error:
            # Rhino.RhinoApp.WriteLine(get_message('port_in_use_check', PORT))
            
            killed = False
            zombie_status = _try_kill_zombie_server()
            
            if zombie_status == 1:
                killed = True
                Rhino.RhinoApp.WriteLine(get_message('zombie_killed_socket', PORT))
            elif zombie_status == 2:
                # Alive UI - abort
                pass
            else:
                # Force kill
                killed_os, pid = _force_kill_port_holder()
                if killed_os:
                    killed = True
                    Rhino.RhinoApp.WriteLine(get_message('zombie_killed_os', PORT, pid))

            if killed:
                time.sleep(1.0)
                try:
                    server.bind((HOST, PORT))
                except:
                    Rhino.RhinoApp.WriteLine("[MCP] Failed to bind after kill.")
                    sc.sticky["gh_mcp_run_server"] = False
                    return
            else:
                if zombie_status != 1 and zombie_status != 2:
                    Rhino.RhinoApp.WriteLine(get_message('port_in_use', PORT))
                
                if zombie_status == 2:
                    pass
                else:
                    Rhino.RhinoApp.WriteLine(get_message('check_other_instance'))
                sc.sticky["gh_mcp_run_server"] = False
                return

        server.listen(5)
        server.setblocking(0)
        Rhino.RhinoApp.WriteLine(get_message('server_started', HOST, PORT))
        
        while sc.sticky["gh_mcp_run_server"]:
            try:
                readable, _, _ = select.select([server], [], [], 1.0)
                if server in readable:
                    conn, addr = server.accept()
                    try:
                        conn.settimeout(5.0)
                        data = b""
                        while True:
                            chunk = conn.recv(4096)
                            if not chunk: break
                            data += chunk
                            if b"\r\n\r\n" in data: # Header end
                                head, body_rest = data.split(b"\r\n\r\n", 1)
                                headers = head.decode().lower()
                                clen = 0
                                for line in headers.split("\r\n"):
                                    if "content-length:" in line:
                                        clen = int(line.split(":")[1].strip())
                                while len(body_rest) < clen:
                                    body_rest += conn.recv(4096)
                                data = body_rest
                                break
                        
                        # Handle OPTIONS
                        if "OPTIONS" in str(head):
                             resp = b"HTTP/1.1 200 OK\r\nAccess-Control-Allow-Origin: *\r\nAccess-Control-Allow-Methods: POST\r\nAccess-Control-Allow-Headers: Content-Type\r\nContent-Length: 0\r\n\r\n"
                             conn.sendall(resp)
                             conn.close()
                             continue

                        cmd = json.loads(data.decode())
                        res = process_command(cmd)
                        
                        res_json = json.dumps(res, cls=GHEncoder)
                        http = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: {}\r\n\r\n{}".format(len(res_json), res_json)
                        conn.sendall(http.encode())
                        
                    except Exception as e:
                        Rhino.RhinoApp.WriteLine("[MCP] Error handling req: {}".format(e))
                    finally:
                        conn.close()
            except Exception:
                continue
                
    except Exception as e:
        Rhino.RhinoApp.WriteLine("[GH MCP] Server Fatal Error: {}".format(e))
    finally:
        server.close()
        # 実際に稼働していた（sc.stickyがTrueだった）場合のみ停止メッセージを出す
        if sc.sticky["gh_mcp_run_server"]:
            Rhino.RhinoApp.WriteLine(get_message('server_stopped'))
        sc.sticky["gh_mcp_run_server"] = False

# --- Main Entry Point (Toggle) ---
if __name__ == "__main__":
    if sc.sticky["gh_mcp_run_server"]:
        # Stop
        sc.sticky["gh_mcp_run_server"] = False
        Rhino.RhinoApp.WriteLine("[GH MCP] Stopping Server (wait for loop to exit)...")
    else:
        # Start
        sc.sticky["gh_mcp_run_server"] = True
        t = threading.Thread(target=server_loop)
        t.daemon = True
        t.start()
        sc.sticky["gh_mcp_server_thread"] = t
        # Rhino.RhinoApp.WriteLine("[GH MCP] Starting Server Thread...")