# -*- coding: utf-8 -*-
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
from System.Collections.Generic import List
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
SERVER_NAME = u"Rhino-Grasshopperアプリ内部 MCPブリッジ・サーバー"
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
        "dataType": str(param.TypeName) if hasattr(param, 'TypeName') else None,
        "dataCount": param.VolatileDataCount if hasattr(param, 'VolatileDataCount') else 0
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
        return {"status": "error", "result": unicode(e)}

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
            return {"status": "error", "result": unicode(e)}
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
        return {"status": "error", "result": unicode(e)}

def update_script_with_code_reference(instance_guid, **kwargs):
    result_holder = {}
    def ui_action():
        result_holder["res"] = _update_code_ref_ui(instance_guid, kwargs.get("file_path"), kwargs.get("param_definitions"), kwargs.get("description"), kwargs.get("name"), kwargs.get("force_code_reference"))
    Rhino.RhinoApp.InvokeOnUiThread(Action(ui_action))
    return result_holder.get("res", {"status": "error", "result": "UI Action failed"})

# --- Extended Tool Helper Functions ---

def find_component_proxy(name):
    """Find a component proxy by name or nickname."""
    proxies = Grasshopper.Instances.ComponentServer.ObjectProxies
    # 1. Exact Name match
    for proxy in proxies:
        if proxy.Desc.Name == name: return proxy
    # 2. Case-insensitive Name match
    for proxy in proxies:
        if proxy.Desc.Name.lower() == name.lower(): return proxy
    # 3. Exact NickName match
    for proxy in proxies:
        if proxy.Desc.NickName == name: return proxy
    # 4. Case-insensitive NickName match
    for proxy in proxies:
        if proxy.Desc.NickName.lower() == name.lower(): return proxy
    # 5. Partial match (if unique?) - maybe too risky
    return None

def _create_component_ui(name, x, y):
    doc = get_active_gh_doc()
    if not doc: return {"status": "error", "result": "No active document"}
    
    proxy = find_component_proxy(name)
    if not proxy:
        return {"status": "error", "result": "Component '{}' not found".format(name)}
    
    obj = proxy.CreateInstance()
    if not obj:
        return {"status": "error", "result": "Failed to create instance of '{}'".format(name)}
    
    # Ensure attributes exist (fixes NoneType error for objects like Sliders)
    if obj.Attributes is None:
        obj.CreateAttributes()
        
    obj.Attributes.Pivot = System.Drawing.PointF(float(x), float(y))
    doc.AddObject(obj, False)
    
    # Auto-layout if it has params (optional, usually GH does this)
    obj.Attributes.ExpireLayout()
    
    return {"status": "success", "result": get_component_info(obj) if isinstance(obj, Grasshopper.Kernel.IGH_Component) else get_param_info(obj, is_input=False)}

def _connect_components_ui(source_id, source_param, target_id, target_param):
    doc = get_active_gh_doc()
    if not doc: return {"status": "error", "result": "No active document"}
    
    try:
        source_obj = doc.FindObject(Guid.Parse(source_id), False)
        target_obj = doc.FindObject(Guid.Parse(target_id), False)
        
        if not source_obj: return {"status": "error", "result": "Source object not found: " + str(source_id)}
        if not target_obj: return {"status": "error", "result": "Target object not found: " + str(target_id)}
        
        # Resolve Source Param (Output)
        src_p = None
        if isinstance(source_obj, Grasshopper.Kernel.IGH_Param):
            src_p = source_obj
        elif isinstance(source_obj, Grasshopper.Kernel.IGH_Component):
            # Try by name/nickname
            if source_param:
                for p in source_obj.Params.Output:
                    if p.Name == source_param or p.NickName == source_param:
                        src_p = p
                        break
            # Try by index
            if not src_p and str(source_param).isdigit():
                idx = int(source_param)
                if idx < source_obj.Params.Output.Count:
                    src_p = source_obj.Params.Output[idx]
            # Default to first
            if not src_p and source_obj.Params.Output.Count > 0:
                src_p = source_obj.Params.Output[0]
        
        if not src_p: return {"status": "error", "result": "Source parameter not found"}

        # Resolve Target Param (Input)
        tgt_p = None
        if isinstance(target_obj, Grasshopper.Kernel.IGH_Param):
            tgt_p = target_obj
        elif isinstance(target_obj, Grasshopper.Kernel.IGH_Component):
            if target_param:
                for p in target_obj.Params.Input:
                    if p.Name == target_param or p.NickName == target_param:
                        tgt_p = p
                        break
            if not tgt_p and str(target_param).isdigit():
                idx = int(target_param)
                if idx < target_obj.Params.Input.Count:
                    tgt_p = target_obj.Params.Input[idx]
            if not tgt_p and target_obj.Params.Input.Count > 0:
                tgt_p = target_obj.Params.Input[0]
        
        if not tgt_p: return {"status": "error", "result": "Target parameter not found"}
        
        # Connect
        tgt_p.AddSource(src_p)
        source_obj.ExpireSolution(True)
        target_obj.ExpireSolution(True)
        
        # Check for runtime messages on target object after connection
        runtime_messages = []
        try:
            if hasattr(target_obj, "RuntimeMessages") and hasattr(target_obj, "RuntimeMessageLevel"):
                messages = target_obj.RuntimeMessages(target_obj.RuntimeMessageLevel)
                runtime_messages = [str(m) for m in messages] if messages else []
        except:
            pass

        return {
            "status": "success", 
            "result": "Connected", 
            "target_runtime_messages": runtime_messages
        }
        
    except Exception as e:
        return {"status": "error", "result": unicode(e)}

def _disconnect_components_ui(target_id, target_param, source_id=None):
    doc = get_active_gh_doc()
    try:
        target_obj = doc.FindObject(Guid.Parse(target_id), False)
        if not target_obj: return {"status": "error", "result": "Target object not found"}

        tgt_p = None
        if isinstance(target_obj, Grasshopper.Kernel.IGH_Param):
            tgt_p = target_obj
        elif isinstance(target_obj, Grasshopper.Kernel.IGH_Component):
            if target_param:
                for p in target_obj.Params.Input:
                    if p.Name == target_param or p.NickName == target_param:
                        tgt_p = p
                        break
            if not tgt_p and str(target_param).isdigit():
                idx = int(target_param)
                if idx < target_obj.Params.Input.Count:
                    tgt_p = target_obj.Params.Input[idx]

        if not tgt_p: return {"status": "error", "result": "Target parameter not found"}

        if source_id:
            # Disconnect specific source
            # Need to find the source param guid to remove it, usually we iterate sources
            source_guid = Guid.Parse(source_id)
            sources_to_remove = []
            for src in tgt_p.Sources:
                # Source might be a param or a component's output param
                # Check if src is the param itself or belongs to the component
                if src.InstanceGuid == source_guid:
                    sources_to_remove.append(src.InstanceGuid)
                elif src.Attributes and src.Attributes.Parent and src.Attributes.Parent.InstanceGuid == source_guid:
                    sources_to_remove.append(src.InstanceGuid)
            
            if not sources_to_remove:
                return {"status": "error", "result": "Source connection not found"}
            
            for g in sources_to_remove:
                tgt_p.RemoveSource(g)
        else:
            # Disconnect all
            tgt_p.RemoveAllSources()

        tgt_p.ExpireSolution(True)
        return {"status": "success", "result": "Disconnected"}

    except Exception as e:
        return {"status": "error", "result": unicode(e)}

def _set_component_value_ui(instance_guid, value):
    doc = get_active_gh_doc()
    try:
        obj = doc.FindObject(Guid.Parse(instance_guid), False)
        if not obj: return {"status": "error", "result": "Object not found"}

        if isinstance(obj, Grasshopper.Kernel.Special.GH_NumberSlider):
            # Check if value is a dict or a JSON string representing a dict
            props = None
            if isinstance(value, dict):
                props = value
            elif isinstance(value, (str, unicode)):
                try:
                    import json
                    props = json.loads(value)
                    if not isinstance(props, dict): props = None
                except:
                    pass
            
            if props:
                # Advanced update: { "value": 10, "min": 0, "max": 100, "decimals": 0 }
                s = obj.Slider
                if "min" in props: s.Minimum = System.Decimal(float(props["min"]))
                if "max" in props: s.Maximum = System.Decimal(float(props["max"]))
                if "decimals" in props: s.DecimalPlaces = int(props["decimals"])
                if "value" in props: obj.SetSliderValue(System.Decimal(float(props["value"])))
            else:
                obj.SetSliderValue(System.Decimal(float(value)))
        elif isinstance(obj, Grasshopper.Kernel.Special.GH_Panel):
            obj.SetUserText(str(value))
        elif isinstance(obj, Grasshopper.Kernel.Special.GH_BooleanToggle):
            # Handle string "True"/"False" or bool
            val = value
            if isinstance(val, (str, unicode)):
                val = val.lower() == "true"
            obj.Value = bool(val)
        else:
            return {"status": "error", "result": "Setting value not supported for this type: " + str(type(obj))}
            
        obj.ExpireSolution(True)
        return {"status": "success", "result": "Value updated"}
    except Exception as e:
        return {"status": "error", "result": unicode(e)}

def _set_component_state_ui(instance_guid, preview, enabled, locked, wire_display):
    doc = get_active_gh_doc()
    try:
        obj = doc.FindObject(Guid.Parse(instance_guid), False)
        if not obj: return {"status": "error", "result": "Object not found"}

        if enabled is not None:
            if hasattr(obj, "Locked"): # In GH, Locked usually means "Disabled" in interaction, but "Enabled" usually means solving.
                # Actually IGH_ActiveObject has 'Locked' (Selection) and 'Enabled' (Solving) is separate?
                # Check API: IGH_ActiveObject has Locked (bool). 
                # There is also GH_DocumentObject.Attributes.Enabled ? No.
                # It's obj.Locked (Selection lock). 
                # Solvable is obj.Locked = False usually allows interaction.
                # For disabling solving: obj.Locked = False? No.
                # Component.Locked -> User cannot select it.
                # Component.Enabled -> Helper to set Locked=false?
                # Let's check common properties.
                # IGH_ActiveObject properties: Locked (bool), NickName (str).
                # To Disable (Grey out): It is usually `obj.Locked = False` ? No.
                # Disabling a component from solving: `obj.Locked` is about UI interaction.
                # `obj.Enabled` property exists on IGH_ActiveObject?
                pass
            
            # Use Attributes for Enable/Disable (Solving)?
            # Actually, `obj.Locked` is for locking selection.
            # `obj.MutableNickName` ...
            # To disable solving: `obj.ExpireSolution(False)` doesn't disable.
            # It seems `obj.Locked` is strictly for UI selection locking.
            # To disable (stop computing): `obj.Enabled` property exists on IGH_ActiveObject.
            if hasattr(obj, "Enabled"):
                obj.Enabled = bool(enabled)
        
        if locked is not None:
             if hasattr(obj, "Locked"):
                 obj.Locked = bool(locked)

        if preview is not None:
            if hasattr(obj, "Hidden"):
                obj.Hidden = not bool(preview)
                
        if wire_display is not None and hasattr(obj, "Attributes"):
            # wire_display: "default", "faint", "hidden"
            wd = str(wire_display).lower()
            if wd == "hidden": obj.Attributes.WireDisplay = Grasshopper.GUI.Canvas.GH_WireDisplay.hidden
            elif wd == "faint": obj.Attributes.WireDisplay = Grasshopper.GUI.Canvas.GH_WireDisplay.faint
            else: obj.Attributes.WireDisplay = Grasshopper.GUI.Canvas.GH_WireDisplay.default
            
        obj.ExpireSolution(True)
        return {"status": "success", "result": "State updated"}
    except Exception as e:
        return {"status": "error", "result": unicode(e)}

def _create_group_ui(component_ids, group_name):
    doc = get_active_gh_doc()
    try:
        group = Grasshopper.Kernel.Special.GH_Group()
        group.CreateAttributes()
        group.NickName = group_name
        
        for uid in component_ids:
            obj = doc.FindObject(Guid.Parse(uid), False)
            if obj:
                group.AddObject(obj.InstanceGuid)
        
        doc.AddObject(group, False)
        group.ExpireCaches()
        return {"status": "success", "result": str(group.InstanceGuid)}
    except Exception as e:
        return {"status": "error", "result": unicode(e)}

def _delete_objects_ui(object_ids):
    doc = get_active_gh_doc()
    try:
        count = 0
        for uid in object_ids:
            # Try to parse GUID, handle potential errors
            try:
                guid = Guid.Parse(str(uid))
            except:
                continue
                
            obj = doc.FindObject(guid, False)
            if obj:
                doc.RemoveObject(obj, False)
                count += 1
        return {"status": "success", "result": "Deleted {} objects".format(count)}
    except Exception as e:
        return {"status": "error", "result": unicode(e)}

def _clear_canvas_ui():
    doc = get_active_gh_doc()
    try:
        if doc:
            doc.SelectAll()
            doc.RemoveObjects(doc.SelectedObjects(), False)
            return {"status": "success", "result": "Canvas cleared"}
        return {"status": "error", "result": "No active document"}
    except Exception as e:
        return {"status": "error", "result": unicode(e)}

def _bake_objects_ui(object_ids):
    doc = get_active_gh_doc()
    rhino_doc = Rhino.RhinoDoc.ActiveDoc
    try:
        baked_ids = []
        for uid in object_ids:
            obj = doc.FindObject(Guid.Parse(uid), False)
            if not obj: continue
            
            params_to_bake = []
            if isinstance(obj, Grasshopper.Kernel.IGH_Param):
                params_to_bake.append(obj)
            elif isinstance(obj, Grasshopper.Kernel.IGH_Component):
                for out_param in obj.Params.Output:
                    params_to_bake.append(out_param)
            
            for p in params_to_bake:
                if p.VolatileDataCount == 0: continue
                try:
                    atts = rhino_doc.CreateDefaultAttributes()
                    new_ids = List[Guid]()
                    p.BakeGeometry(rhino_doc, atts, new_ids)
                    for gid in new_ids:
                        baked_ids.append(str(gid))
                except Exception as bake_err:
                    Rhino.RhinoApp.WriteLine("[MCP] Bake error for {}: {}".format(p.NickName, bake_err))
        
        if baked_ids:
            rhino_doc.Views.Redraw()
            
        return {"status": "success", "result": {"baked_count": len(baked_ids), "ids": baked_ids}}
    except Exception as e:
        return {"status": "error", "result": unicode(e)}

def get_gh_canvas_stats():
    doc = get_active_gh_doc()
    if not doc: return {"status": "error", "result": "No document"}
    
    return {"status": "success", "result": {
        "object_count": doc.ObjectCount,
        "selected_count": doc.SelectedCount,
        "file_name": doc.DisplayName,
        "document_id": str(doc.DocumentID)
    }}

def search_gh_components(query, limit=10):
    try:
        proxies = Grasshopper.Instances.ComponentServer.ObjectProxies
        results = []
        q = query.lower()
        count = 0
        for proxy in proxies:
            if not proxy.Desc: continue
            if q in proxy.Desc.Name.lower() or q in proxy.Desc.NickName.lower() or q in proxy.Desc.Description.lower():
                results.append({
                    "name": proxy.Desc.Name,
                    "nickname": proxy.Desc.NickName,
                    "description": proxy.Desc.Description,
                    "category": proxy.Desc.Category,
                    "guid": str(proxy.Guid)
                })
                count += 1
                if count >= limit: break
        return results
    except Exception as e:
        return []

# --- Command Processing ---
def process_command(cmd):
    ctype = cmd.get("type")
    
    # --- Helper to run UI action ---
    def run_ui(func, *args, **kwargs):
        res_container = {}
        # Wait event for synchronization
        evt = threading.Event()
        
        def _action():
            try:
                res_container["val"] = func(*args, **kwargs)
            except Exception as e:
                res_container["val"] = {"status": "error", "result": unicode(e)}
            finally:
                evt.set()
                
        Rhino.RhinoApp.InvokeOnUiThread(Action(_action))
        
        # Wait for UI thread to complete (timeout 5s)
        if not evt.wait(5.0):
             return {"status": "error", "result": "UI action timed out"}
             
        return res_container.get("val", {"status": "error", "result": "UI call failed"})

    if ctype == "test":
        return {"status": "success", "result": "Rhino-MCP Alive"}
    
    elif ctype == "get_context":
        doc = get_active_gh_doc()
        if not doc: return {"status": "error", "result": "No Active Document"}
        return {"status": "success", "result": get_all_relevant_objects_info(doc, simplified=cmd.get("simplified", False))}
    
    elif ctype == "expire_component":
        doc = get_active_gh_doc()
        def _exp():
             return expire_grasshopper_component(doc, cmd.get("instance_guid"))
        return run_ui(_exp) # expire needs UI thread? Safe to do so.
        
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
            return {"status": "error", "result": unicode(e)}

    # --- New Commands ---
    elif ctype == "create_component":
        return run_ui(_create_component_ui, cmd.get("name"), cmd.get("x", 0), cmd.get("y", 0))
        
    elif ctype == "connect_components":
        return run_ui(_connect_components_ui, cmd.get("source_id"), cmd.get("source_param"), cmd.get("target_id"), cmd.get("target_param"))
        
    elif ctype == "disconnect_components":
        return run_ui(_disconnect_components_ui, cmd.get("target_id"), cmd.get("target_param"), cmd.get("source_id"))
        
    elif ctype == "set_component_value":
        return run_ui(_set_component_value_ui, cmd.get("instance_guid"), cmd.get("value"))
        
    elif ctype == "set_component_state":
        return run_ui(_set_component_state_ui, cmd.get("instance_guid"), cmd.get("preview"), cmd.get("enabled"), cmd.get("locked"), cmd.get("wire_display"))
        
    elif ctype == "create_group":
        return run_ui(_create_group_ui, cmd.get("component_ids", []), cmd.get("group_name", "Group"))
        
    elif ctype == "delete_objects":
        return run_ui(_delete_objects_ui, cmd.get("object_ids", []))
        
    elif ctype == "clear_canvas":
        if cmd.get("confirm") is not True:
             return {"status": "error", "result": "Confirm must be True"}
        return run_ui(_clear_canvas_ui)
        
    elif ctype == "bake_objects":
        return run_ui(_bake_objects_ui, cmd.get("object_ids", []))
        
    elif ctype == "get_canvas_stats":
        return run_ui(get_gh_canvas_stats)
        
    elif ctype == "search_components":
        # Read-only, no UI thread needed strictly but safer
        # I need to implement search_gh_components helper in the block above
        return {"status": "success", "result": search_gh_components(cmd.get("query"), cmd.get("limit", 10))}

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
        body_bytes = body.encode('utf-8')
        req = "POST / HTTP/1.1\r\nContent-Length: {}\r\n\r\n".format(len(body_bytes))
        s.sendall(req.encode('utf-8') + body_bytes)
        
        # Read response
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk: break
            data += chunk
            if b"\r\n\r\n" in data:
                head, body_part = data.split(b"\r\n\r\n", 1)
                cl = 0
                for line in head.decode('utf-8').split("\r\n"):
                    if "content-length:" in line.lower():
                        cl = int(line.lower().split(":")[1].strip())
                while len(body_part) < cl:
                    body_part += s.recv(4096)
                data = body_part
                break
        
        try:
            res = json.loads(data.decode('utf-8'))
        except:
            return 0

        if res.get("headless"):
            # Rhino.RhinoApp.WriteLine("[MCP] Found headless zombie. Killing...")
            s.close()
            
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((HOST, PORT))
            body = json.dumps({"type": "stop_server"})
            body_bytes = body.encode('utf-8')
            req = "POST / HTTP/1.1\r\nContent-Length: {}\r\n\r\n".format(len(body_bytes))
            s.sendall(req.encode('utf-8') + body_bytes)
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
                                headers = head.decode('utf-8').lower()
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

                        try:
                            cmd = json.loads(data.decode('utf-8'))
                            res = process_command(cmd)
                        except Exception as process_err:
                            res = {"status": "error", "result": "Internal error in process_command: " + unicode(process_err)}
                            Rhino.RhinoApp.WriteLine("[MCP] Error in process_command: " + unicode(process_err))
                        
                        try:
                            res_json = json.dumps(res, cls=GHEncoder, ensure_ascii=False)
                            if not isinstance(res_json, unicode):
                                res_json = unicode(res_json)
                            res_bytes = res_json.encode('utf-8')
                            
                            http_header = u"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: {}\r\n\r\n".format(len(res_bytes))
                            conn.sendall(http_header.encode('utf-8') + res_bytes)
                        except Exception as send_err:
                            Rhino.RhinoApp.WriteLine(u"[MCP] Error sending response: " + unicode(send_err))
                        
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