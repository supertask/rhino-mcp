# RhinoMCP - Rhino Model Context Protocol Integration

**[ English ](README.md)**

RhinoMCP は、Model Context Protocol (MCP) を通じて Rhino、Grasshopper などを AI エージェントに接続し、AI が Rhino + Grasshopper を直接操作および制御できるようにします。Replicate.com の API キーを提供すれば、AI 画像レンダリングも可能です。この統合により、プロンプト支援型の3Dモデリング、シーン作成、および操作が可能になります。(inspired by [blender_mcp](https://github.com/ahujasid/blender-mcp))

## 機能

#### Rhino
- **双方向通信**: ソケットベースのサーバーを通じて AI を Rhino に接続
- **オブジェクト操作と管理**: メタデータを含む Rhino 内の 3D オブジェクトの作成と変更
- **レイヤー管理**: Rhino レイヤーの表示と操作
- **シーン検査**: 現在の Rhino シーンに関する詳細情報の取得（スクリーンキャプチャを含む）
- **コード実行**: AI から Rhino 内で任意の Python コードを実行

#### Grasshopper
- **コード実行**: AI から Grasshopper 内で任意の Python コードを実行（GH コンポーネントの生成を含む）
- **GH キャンバス検査**: コンポーネントグラフやパラメータを含む Grasshopper 定義の詳細情報の取得
- **コンポーネント管理**: スクリプトコンポーネントの更新、パラメータ変更、コード参照の管理
- **外部コード統合**: より良いコード構成のためにスクリプトコンポーネントを外部 Python ファイルにリンク
- **リアルタイムフィードバック**: コンポーネントの状態、エラーメッセージ、ランタイム情報の取得
- **ノンブロッキング通信**: HTTP サーバーを介した安定した双方向通信

#### Replicate
- **AI モデル**: Replicate は API 経由で数千の AI モデルを提供します。ここでは Stable Diffusion のバリアントを実装しています。

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

### Rhino 側スクリプトのインストール

1. Rhino 7 を開きます。
2. Python Editor を開きます：
   - "Tools" (ツール) メニューをクリック
   - "Python Script" -> "Run.." (実行) を選択
   - このプロジェクトフォルダ内の `rhino_scripts/rhino_mcp_bridge.py` に移動して選択します。
3. スクリプトが自動的に開始され、Python Editor に以下のメッセージが表示されます：
   ```
   RhinoMCP script loaded. Server started automatically.
   To stop the server, run: stop_server()
   ```

### Grasshopper 側スクリプトのインストール

1. Grasshopper を開きます。
2. キャンバスに **GhPython Script** コンポーネントを配置します。
3. コンポーネントを右クリック -> "Open Editor" (エディタを開く)。
4. `rhino_scripts/grasshopper_mcp_bridge.py` の内容をコピーしてエディタに貼り付けます。
   *あるいは、ファイルを直接リンクしたい場合（開発用に推奨）、GhPython コンポーネントの `code input` パラメータを使用してファイルを読み込んでください。*
5. コンポーネントが実行されていることを確認します（Toggle を True に設定）。

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
ツールを使用する前に、**Rhino ブリッジスクリプト**が Rhino で実行されていることを確認してください。

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

