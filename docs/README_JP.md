# RhinoMCP - Rhino Model Context Protocol Integration

**[ English ](README.md)**

RhinoMCP は、Model Context Protocol (MCP) を通じて Rhino、Grasshopper などを AI エージェントに接続し、AI が Rhino + Grasshopper を直接操作および制御できるようにします。Replicate.com の API キーを提供すれば、AI 画像レンダリングも可能です。この統合により、プロンプト支援型の3Dモデリング、シーン作成、および操作が可能になります。(inspired by [blender_mcp](https://github.com/ahujasid/blender-mcp))

## 機能

### 🦏 Rhino の機能
- `get_scene_info`: シーンの概要とレイヤーを取得します。
- `capture_viewport`: ビューポートを画像としてキャプチャします。
- `execute_rhino_code`: Python コードを実行してオブジェクトを作成・変更します。
- **[すべての Rhino ツールを見る](FEATURES_JP.md#rhino-mcp-ツール)**

### 🦗 Grasshopper の機能
- `get_gh_context`: コンポーネントグラフ全体を探索します。
- `update_script`: コンポーネントのコードをリアルタイムで変更します。
- `bake_objects`: ジオメトリを Rhino に転送します。
- **[すべての Grasshopper ツールを見る](FEATURES_JP.md#grasshopper-mcp-ツール)**

### 🤖 Replicate 統合
- **AI レンダリング**: Replicate API を通じて Stable Diffusion モデルを使用し、高品質なレンダリングを生成します。

## プロジェクト構造

このプロジェクトは標準的な `src` レイアウトに従っています：

- `src/rhino_mcp/`: **MCP サーバーコード** (Python 3.x)。MCP プロトコルを実装し、Rhino/Grasshopper と通信します。
- `rhino_scripts/`: **ブリッジスクリプト** (IronPython 2.7)。コマンドを処理するために Rhino および Grasshopper 内部で実行されるスクリプトです。
  - `rhino_mcp_bridge.py`: Rhino 統合用
  - `grasshopper_mcp_bridge.py`: Grasshopper 統合用

## インストール

### 前提条件

- Rhino 7 以降
- Python 3.10 以降
- `uv` (推奨) または `pip`

### Python 環境のセットアップ

依存関係の管理には、高速で信頼性の高い `uv` の使用を推奨します。

1. このリポジトリをクローンします。

2. 仮想環境を作成し、依存関係をインストールします：
   ```bash
   # 仮想環境の作成
   python -m venv .venv
   
   # 環境のアクティベート (Windows)
   .venv\Scripts\activate
   # 環境のアクティベート (Mac/Linux)
   source .venv/bin/activate
   
   # 編集可能モードでパッケージをインストール
   pip install -e .
   ```
   
   または `uv` を直接使用する場合：
   ```bash
   uv sync
   ```

### Rhinoアプリ起動時にMCPブリッジ自動起動させる

Rhino を起動するたびにスクリプトを手動で実行する手間を省くために、以下の手順で自動起動を設定できます：

1. Rhino を開きます。
2. **Tools**（ツール）→ **Options**（オプション）→ **General**（全般）に移動します（または **ファイル**→**プロパティ**→**全般**からもアクセス可能）。
3. **Command Lists**（コマンドリスト）の **Run these commands every time Rhino starts:**（Rhinoを開始するたびにこれらのコマンドを実行する）ボックスに以下を追加します。 `C:\path\to\rhino-mcp` の部分を、実際のプロジェクトフォルダの絶対パスに置き換えてください：
For ANSI/ISO keyboard
   ```
   _-RunPythonScript "C:\path\to\rhino-mcp\rhino_scripts\rhino_mcp_bridge.py"
   _-RunPythonScript "C:\path\to\rhino-mcp\rhino_scripts\grasshopper_mcp_bridge.py"
   ```

For JIS keyboard
   ```
   _-RunPythonScript "C:¥path¥to¥rhino-mcp¥rhino_scripts¥rhino_mcp_bridge.py"
   _-RunPythonScript "C:¥path¥to¥rhino-mcp¥rhino_scripts¥grasshopper_mcp_bridge.py"
   ```
4. **OK** をクリックし、Rhino を再起動します。

![Rhino 起動設定](images/rhino_python_command_setting.png)

## 設定

### Claude Desktop 統合

1. Claude Desktop > Settings > Developer > Edit Config に移動します。
2. `claude_desktop_config.json` ファイルを開き、以下の設定を追加します：

**Windows (例):**
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

**Mac/Linux (例):**
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

### Cursor IDE 統合

1. `~/.cursor/mcp.json`（またはプロジェクト固有の `.cursor/mcp.json`）を見つけるか作成します。
2. 上記と同じ設定を追加します。

## 使用方法

設定が完了すると、Claude Desktop や Cursor を開いたときに MCP サーバーが自動的に起動します。
ツールを使用する前に、**Rhino/Grasshopper ブリッジスクリプト**が Rhino で実行されていることを確認してください。

### プロンプト例

- "Get information about the current Rhino scene" (現在の Rhino シーンに関する情報を取得して)
- "Create a cube at the origin" (原点に立方体を作成して)
- "Grasshopperでシンプルなパラメトリックタワーを作って"

## トラブルシューティング

- **接続の問題**: 
  - Rhino スクリプトが実行されていることを確認してください（Python Editor の出力を確認）。
  - ポート 9876 (Rhino) または 9999 (Grasshopper) が他のアプリケーションによって使用されていないことを確認してください。
- **パスエラー**:
  - `claude_desktop_config.json` が正しいプロジェクトルートディレクトリ（`pyproject.toml` がある場所）を指していることを確認してください。

## ライセンス

このプロジェクトはオープンソースであり、MIT ライセンスの下で利用可能です。

