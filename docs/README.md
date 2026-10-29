# RhinoMCP - Rhino Model Context Protocol Integration

**[ 日本語 (Japanese) ](README_JP.md)**

RhinoMCP connects Rhino, Grasshopper and more to AI Agents through the Model Context Protocol (MCP), allowing them to directly interact with and control Rhino + Grasshopper. If you provide a replicate.com api key you can also AI render images. This integration enables prompt-assisted 3D modeling, scene creation, and manipulation. (inspired by [blender_mcp](https://github.com/ahujasid/blender-mcp))

## Features

### 🦏 Rhino Features
- `get_scene_info`: Get scene overview and layers.
- `capture_viewport`: Capture viewports as images.
- `execute_rhino_code`: Run Python code to create/modify objects.
- **[View All Rhino Tools](FEATURES.md#rhino-mcp-tools)**

### 🦗 Grasshopper Features
- `get_gh_context`: Explore the full component graph.
- `update_script`: Modify component code in real-time.
- `bake_objects`: Transfer geometry to Rhino.
- **[View All Grasshopper Tools](FEATURES.md#grasshopper-mcp-tools)**

### 🤖 Replicate Integration
- **AI Rendering**: Generate high-quality renders using Stable Diffusion models via Replicate API.

## Project Structure

The project follows a standard `src` layout:

- `src/rhino_mcp/`: **MCP Server Code** (Python 3.x). Implements the MCP protocol and communicates with Rhino/Grasshopper.
- `rhino_scripts/`: **Bridge Scripts** (IronPython 2.7). Scripts that run inside Rhino and Grasshopper to handle commands.
  - `rhino_mcp_bridge.py`: For Rhino integration.
  - `grasshopper_mcp_bridge.py`: For Grasshopper integration.

## Installation

### Prerequisites

- Rhino 7 or newer (also confirmed to work on the early Rhino 7.1 release; updating is not required)
- Python 3.10–3.13 (with `uv`, Python 3.12 is installed automatically as set in `.python-version`)
- `uv` (Recommended) or `pip`

### Setting up the Python Environment

We recommend using `uv` for fast and reliable dependency management.

1. Clone this repository. On Windows, if you have no particular preference, we recommend placing it in `%USERPROFILE%\InstalledModules\rhino-mcp`.

2. Create a virtual environment and install dependencies:
   ```bash
   # Create virtual environment
   python -m venv .venv
   
   # Activate environment (Windows)
   .venv\Scripts\activate
   # Activate environment (Mac/Linux)
   source .venv/bin/activate
   
   # Install package in editable mode
   pip install -e .
   ```
   
   Or using `uv` directly:
   ```bash
   uv sync
   ```

   **When an AI app (such as the Claude desktop app) does the setup on Windows**, set the Python location outside AppData before `uv sync`. The Claude desktop app redirects writes to AppData, so without this the setup stops with `Missing expected target directory for Python minor version link`.
   ```powershell
   $env:UV_PYTHON_INSTALL_DIR = "$env:USERPROFILE\.uv-python"
   uv sync
   ```
   In that case, give the same `UV_PYTHON_INSTALL_DIR` when registering the MCP server (see below).

   If downloads fail with `invalid peer certificate: UnknownIssuer` (for example behind company security software), use `uv sync --system-certs` to use the Windows certificate store.

### Automating MCP Bridge Startup on Rhino Launch

To avoid running the scripts manually every time you start Rhino, you can add them to the Rhino startup commands:

1. Open Rhino.
2. Go to **Tools** -> **Options** -> **General** (You can also access this from **File** -> **Properties** -> **General**).
3. Under **Command Lists**, find the box labeled **Run these commands every time Rhino starts:**. Add the following commands, replacing `C:\path\to\rhino-mcp` with the absolute path to your project folder:

   For ANSI/ISO keyboard
   ```
   _-RunPythonScript "C:\\path\\to\\rhino-mcp\\rhino_scripts\\rhino_mcp_bridge.py"
   _-RunPythonScript "C:\\path\\to\\rhino-mcp\\rhino_scripts\\grasshopper_mcp_bridge.py"
   ```

   For JIS keyboard
   ```
   _-RunPythonScript "C:¥¥path¥¥to¥¥rhino-mcp¥¥rhino_scripts¥¥rhino_mcp_bridge.py"
   _-RunPythonScript "C:¥¥path¥¥to¥rhino-mcp¥¥rhino_scripts¥¥grasshopper_mcp_bridge.py"
   ```


4. Click **OK** and restart Rhino.

![Rhino Startup Settings](images/rhino_python_command_setting.png)

- When an AI does the setup, set this box **by pasting into this dialog** as well. Early Rhino 7 releases have no way for a script to change it.
- Running a bridge script again does not start a second copy (it only prints "already running").
- To stop the Grasshopper bridge, run `rhino_scripts\grasshopper_mcp_bridge_stop.py`.

## Configuration

### Claude Code Integration (including the Code tab of the Claude desktop app)

This one command registers the server for use from any folder (existing MCP registrations are kept). Replace `C:\path\to\rhino-mcp` with your clone location.

```powershell
claude mcp add --scope user rhino -e UV_PYTHON_INSTALL_DIR=$env:USERPROFILE\.uv-python -- uv run --directory C:\path\to\rhino-mcp -m rhino_mcp.server
```

- Put the name (`rhino`) before `-e`; the other way round fails with `Invalid environment variable format`.
- `UV_PYTHON_INSTALL_DIR` is needed when you ran `uv sync` with that setting (see "When an AI app does the setup" above).
- Check the registration with `claude mcp get rhino`. It is available in new chats opened after registering (no app restart needed).

### Claude Desktop Integration

1. Go to Claude Desktop > Settings > Developer > Edit Config 
2. Open the `claude_desktop_config.json` file and add the following configuration:

**Windows (Example):**
```json
{
    "mcpServers": {
        "rhino": {
            "command": "uv",
            "args": [
                "run",
                "--directory",
                "C:\\path\\to\\rhino-mcp",
                "-m",
                "rhino_mcp.server"
            ]
        }
    }
}
```

**Mac/Linux (Example):**
```json
{
    "mcpServers": {
        "rhino": {
            "command": "uv",
            "args": [
                "run",
                "--directory",
                "/path/to/rhino-mcp",
                "-m",
                "rhino_mcp.server"
            ]
        }
    }
}
```

### ChatGPT Desktop / Codex Integration

For ChatGPT desktop / Codex clients with local MCP support, add the following to `~/.codex/config.toml` (Windows: `%USERPROFILE%\.codex\config.toml`). This does not apply to ChatGPT web.

```toml
[mcp_servers.rhino]
command = "uv"
args = [
    "run",
    "--directory",
    'C:\path\to\rhino-mcp',
    "-m",
    "rhino_mcp.server"
]
```

Replace the path with your clone location, save, and restart your app / Codex. This single configuration connects to both Rhino and Grasshopper. Follow the bridge startup steps above in Rhino.

Reference: [Official OpenAI MCP configuration documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)

### Cursor IDE Integration

1. Locate or create the file `~/.cursor/mcp.json` (or project specific `.cursor/mcp.json`)
2. Add the same configuration as above.

## Usage

Once configured, the MCP server will start automatically when you open Claude Desktop or Cursor.
Make sure the **Rhino bridge script** is running in Rhino before attempting to use the tools.

### Example Prompts

- "Get information about the current Rhino scene"
- "Create a cube at the origin"
- "Grasshopperでシンプルなパラメトリックタワーを作って" (Create a simple parametric tower in Grasshopper)

## Troubleshooting

- **Connection issues**: 
  - Make sure the Rhino script is running (check Python Editor output)
  - Verify port 9876 (Rhino) or 9999 (Grasshopper) is not in use.
- **Path errors**:
  - Ensure `claude_desktop_config.json` points to the correct project root directory (where `pyproject.toml` is located).
- **`uv sync` stops with `Missing expected target directory for Python minor version link`**:
  - This happens when it runs inside an AI app. Set `UV_PYTHON_INSTALL_DIR` as described in "Setting up the Python Environment" and run it again.
- **It stopped connecting after reopening Rhino**:
  - Check that the startup commands from "Automating MCP Bridge Startup on Rhino Launch" are set. Without them, the bridge scripts must be run each time Rhino starts.
- **AI commands never finish or end with "timed out"**:
  - While a settings dialog such as Options or Document Properties is open in Rhino, Rhino holds commands from outside until the dialog is closed. Close the dialog and run the command again.

## License

This project is open source and available under the MIT License.

