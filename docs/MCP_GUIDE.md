# Rhino-Grasshopper MCP 統合ガイド

このドキュメントでは、Rhino-Grasshopper Model Context Protocol (MCP) 統合のアーキテクチャ、機能、および開発ガイドラインについて概説します。

## 1. アーキテクチャ概要

システムは、ローカルソケット接続を介して通信する2つの主要コンポーネントで構成されています：

1.  **内部ブリッジサーバー (`grasshopper_mcp_bridge.py`)**:
    *   Rhino/Grasshopper の **内部** (IronPython 2.7 環境) で実行されます。
    *   サーバーとして機能し、ポート `9999` (デフォルト) でリッスンします。
    *   実際の Rhino/Grasshopper API 呼び出し (`RhinoCommon`, `Grasshopper.Kernel`) を実行します。
    *   安全なキャンバス操作のために UI スレッドの同期を処理します。

2.  **MCP クライアントサーバー (`rhino_mcp/grasshopper_tools.py`)**:
    *   Rhino の **外部** (標準 Python 3.x 環境) で実行されます。
    *   MCP サーバーとして機能し、AI エージェントにツールを提供します。
    *   内部ブリッジサーバーに接続してコマンドを転送します。
    *   データのフォーマット、パターンナレッジベース、エラー報告を処理します。

## 2. 主な機能

### コンポーネント操作
*   **作成**: `create_component` (名前/ニックネーム検索をサポート)。
*   **接続**: `connect_components` (出力を入力にリンク)。
*   **値の設定**: `set_component_value` (スライダー、パネル、トグルをサポート)。
*   **状態設定**: `set_component_state` (プレビュー、有効/無効、ロック)。

### スクリプティングとロジック
*   **Python スクリプト**: `update_script` により、`GhPython` コンポーネントに Python コードを注入できます。
*   **コード参照**: `update_script_with_code_reference` により、外部 `.py` ファイルをコンポーネントにリンクし、バージョン管理を容易にします。
*   **直接実行**: `execute_code_in_gh` は、ワンオフのタスクのために任意の Python コードを実行します。

### キャンバス管理
*   **検査**: `get_gh_context` は、完全なグラフ構造（接続、タイプ）を返します。
*   **クリーンアップ**: `clear_canvas`, `delete_objects`。
*   **Bake (焼き付け)**: `bake_objects` は、Grasshopper ジオメトリを Rhino オブジェクトに変換します。

## 3. 高度な機能 (最近の拡張)

### ⚡ スマートエラー検知
`connect_components` ツールが強化され、接続を即座に検証するようになりました。
*   **動作**: ワイヤー接続後、ターゲットコンポーネントの `RuntimeMessages` をチェックします。
*   **メリット**: 型の不一致（例：Number -> Box）が発生した場合、AI はツール結果で即座に警告/エラーを受け取り、自己修正が可能になります。

### 📚 パターンナレッジベース
`get_available_patterns` ツールは、一般的な Grasshopper 定義の「レシピ」を提供します。
*   **内容**: `grasshopper_tools.py` 内の `GH_PATTERNS` で定義されています。
*   **用途**: AI はこれらのパターンをリクエストすることで、正しいパラメータ名と接続を持つ複雑な構造（例：「3D Voronoi」、「パラメトリック Box」）の構築方法を理解できます。

## 4. 開発ガイドライン

### 再起動ルール
システムは2つの環境にまたがるため、更新には特定の再起動アクションが必要です：

| 変更されたコンポーネント | ファイルの場所 | 必要なアクション |
| :--- | :--- | :--- |
| **ブリッジサーバー** | `grasshopper_mcp_bridge.py` | **Rhino アプリの再起動**。サーバースクリプトは Rhino 起動時/GH ロード時にロードされます。 |
| **MCP ツール** | `rhino_mcp/grasshopper_tools.py` | **MCP サーバーの再起動** (例: Claude Desktop や MCP サーバーを実行しているターミナルの再起動)。 |

### トラブルシューティング
*   **ポート競合**: ポート 9999 が使用中の場合、ブリッジサーバーはゾンビプロセスのキルを試みます。失敗した場合は、タスクマネージャーでスタックしている `Rhino.exe` プロセスを確認してください。
*   **UI スレッド**: すべてのキャンバス変更は、メイン UI スレッドで実行する必要があります。ブリッジは `Rhino.RhinoApp.InvokeOnUiThread` を使用してスレッドの安全性を確保しています。
*   **データ型**: Grasshopper の型 (Guid, Point3d) は、ブリッジスクリプト内の `GHEncoder` クラスでカスタムシリアライズされます。

## 5. ファイル構成
*   `rhino-mcp/rhino_scripts/grasshopper_mcp_bridge.py`: **サーバーコード** (IronPython)。GH キャンバス操作のロジック。
*   `rhino-mcp/src/rhino_mcp/grasshopper_tools.py`: **クライアントコード** (Python 3)。MCP ツール定義とソケットクライアント。
