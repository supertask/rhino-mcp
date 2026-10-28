# -*- coding: utf-8 -*-
"""Stand-ins for modules that only exist inside Rhino or are optional.

- `use_src()` makes `import rhino_mcp` load the code under src/.
- `install_optional_stubs()` replaces mcp / PIL with minimal fakes when they
  are not installed, so the MCP-side tests also run without `uv sync`.
- `load_bridge()` loads a script from rhino_scripts/ in CPython with
  Rhino/.NET/Grasshopper replaced by mocks. Nothing is started at import time,
  and the code that force-kills processes holding a port is disabled.
"""
import builtins
import contextlib
import logging
import os
import sys
import types
from unittest import mock

# The tools log every command; keep test output readable unless asked for
if os.environ.get("RHINO_MCP_TEST_LOGS") != "1":
    logging.disable(logging.CRITICAL)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "src")
RHINO_SCRIPTS = os.path.join(ROOT, "rhino_scripts")

RHINO_MODULES = ["System", "System.Drawing", "System.Drawing.Imaging", "System.IO",
                 "System.Collections", "System.Collections.Generic",
                 "Rhino", "Rhino.Geometry", "rhinoscriptsyntax", "clr"]
GRASSHOPPER_MODULES = ["Grasshopper", "Grasshopper.Kernel", "Grasshopper.Kernel.Parameters",
                       "Grasshopper.Kernel.Special"]


def use_src():
    if SRC not in sys.path:
        sys.path.insert(0, SRC)


class StubImage(object):
    """Replacement for mcp.server.fastmcp.Image that keeps what it was given."""

    def __init__(self, data=None, format=None, **kwargs):
        self.data = data
        self.format = format


class StubFastMCP(object):
    def __init__(self, *args, **kwargs):
        self.tools = []

    def tool(self):
        def register(fn):
            self.tools.append(fn)
            return fn
        return register


def install_optional_stubs():
    """Use the real packages when installed; otherwise install small fakes."""
    try:
        import mcp.server.fastmcp  # noqa: F401
    except Exception:
        for name in [n for n in sys.modules if n == "mcp" or n.startswith("mcp.")]:
            del sys.modules[name]
        fastmcp = types.ModuleType("mcp.server.fastmcp")
        fastmcp.FastMCP = StubFastMCP
        fastmcp.Context = object
        fastmcp.Image = StubImage
        sys.modules["mcp"] = types.ModuleType("mcp")
        sys.modules["mcp.server"] = types.ModuleType("mcp.server")
        sys.modules["mcp.server.fastmcp"] = fastmcp
    try:
        import PIL.Image  # noqa: F401
    except Exception:
        pil = types.ModuleType("PIL")
        pil.Image = types.ModuleType("PIL.Image")
        sys.modules["PIL"] = pil
        sys.modules["PIL.Image"] = pil.Image


def new_app():
    """An MCP app object for registering tools in tests."""
    from mcp.server.fastmcp import FastMCP
    return FastMCP("rhino-mcp-test")


@contextlib.contextmanager
def py2_builtins():
    """The bridges are IronPython 2.7 code and use `unicode`."""
    with mock.patch.object(builtins, "unicode", str, create=True):
        yield


def load_bridge(filename, log_dir=None, cut_marker=None, grasshopper=False):
    """Load rhino_scripts/<filename> with Rhino modules mocked.

    cut_marker: source after this line is dropped (used to skip auto-start code).
    """
    path = os.path.join(RHINO_SCRIPTS, filename)
    names = RHINO_MODULES + (GRASSHOPPER_MODULES if grasshopper else [])
    stubs = dict((name, mock.MagicMock(name=name)) for name in names)
    scriptcontext = types.ModuleType("scriptcontext")
    scriptcontext.sticky = {}
    scriptcontext.doc = mock.MagicMock(name="scriptcontext.doc")
    stubs["scriptcontext"] = scriptcontext
    with open(path, "rb") as f:
        source = f.read().decode("utf-8-sig")   # grasshopper_mcp_bridge.py has a BOM
    if cut_marker:
        source = source.split(cut_marker)[0]
    module = types.ModuleType(os.path.splitext(filename)[0] + "_under_test")
    module.__file__ = path
    with mock.patch.dict(sys.modules, stubs):
        exec(compile(source, path, "exec"), module.__dict__)

    # Never write to the user's RhinoMCP log folder
    if log_dir is not None and hasattr(module, "get_log_dir"):
        module.get_log_dir = lambda: log_dir
    # Never kill processes or contact a real bridge from a test
    if hasattr(module, "_force_kill_port_holder"):
        module._force_kill_port_holder = lambda: (False, None)
    if hasattr(module, "_try_kill_zombie_server"):
        module._try_kill_zombie_server = lambda: 0
    server_class = getattr(module, "RhinoMCPServer", None)
    if server_class is not None:
        server_class._force_kill_port_holder = lambda self: (False, None)
        server_class._try_kill_zombie_server = lambda self: 0
    return module


def ironpython_json():
    """A `json` module that fails like IronPython 2.7's on text with characters 0x80-0xFF.

    With ensure_ascii=True (the default), IronPython's json treats such text as UTF-8
    bytes and decodes it, which fails for the multiplication sign, the degree sign and
    so on (and for any text mixing them with Japanese). Patch it over a bridge's `json`.
    """
    import json as real

    def dumps(obj, *args, **kwargs):
        if kwargs.get("ensure_ascii", True):
            text = real.dumps(obj, ensure_ascii=False, cls=kwargs.get("cls"))
            if any(0x80 <= ord(ch) <= 0xFF for ch in text):
                raise UnicodeDecodeError("unknown", b"\xd7", 0, 1, "emulated IronPython 2.7 json")
        return real.dumps(obj, *args, **kwargs)

    return types.SimpleNamespace(dumps=dumps, loads=real.loads, JSONEncoder=real.JSONEncoder)


def rhino_lines(module):
    """Lines the bridge printed to Rhino's command line."""
    return [str(c.args[0]) for c in module.Rhino.RhinoApp.WriteLine.call_args_list]
