# RhinoMCP 機能詳細

このドキュメントでは、Rhino および Grasshopper で利用可能な MCP ツールの詳細について説明します。

## 🦏 Rhino MCP ツール

### シーンの検査
- `get_scene_info`: 現在のシーンの概要（レイヤー、オブジェクトのサンプルなど）を取得します。
- `get_scene_objects_with_metadata`: カスタムメタデータを含むオブジェクトの詳細情報を取得します。
- `capture_viewport`: 現在の Rhino ビューポートを画像としてキャプチャします。

### オブジェクト操作
- `execute_rhino_code`: Rhino 内で任意の IronPython 2.7 コードを実行し、ジオメトリを作成または変更します。
- `add_object_metadata`: (内部ヘルパー) オブジェクトにカスタムの名前と説明を割り当てます。

### レイヤー管理
- `get_layers`: 現在のドキュメント内の全レイヤーを取得します。

---

## 🦗 Grasshopper MCP ツール

### キャンバスの検査
- `get_canvas_stats`: 現在のキャンバスの統計情報（オブジェクト数など）を素早く取得します。
- `get_gh_context`: コンポーネントグラフ全体とその状態を取得します。
- `get_objects`: GUID を指定して特定のコンポーネントの詳細情報を取得します。
- `get_selected`: 現在選択されているコンポーネントの情報を取得します。
- `search_components`: 名前やキーワードで利用可能なコンポーネントを検索します。

### コンポーネント管理
- `create_component`: キャンバスに新しいコンポーネントを追加します。
- `connect_components`: コンポーネントのパラメータ間にワイヤーを作成します。
- `disconnect_components`: コンポーネントの入力からワイヤーを削除します。
- `delete_objects`: キャンバスから指定したオブジェクトを削除します。
- `clear_canvas`: アクティブなドキュメントからすべてのオブジェクトを削除します。
- `set_component_value`: スライダー、パネル、トグルの値を更新します。
- `set_component_state`: プレビュー、有効化、ロック状態を管理します。
- `create_group`: 選択したコンポーネントをグループ化します。

### スクリプティングと実行
- `update_script`: GhPython コンポーネントの Python コードとパラメータを変更します。
- `update_script_with_code_reference`: GhPython コンポーネントを外部 Python ファイルにリンクします。
- `expire_and_get_info`: 再計算を強制し、更新された状態やエラーを取得します。
- `execute_code_in_gh`: Grasshopper 環境内で任意の Python コードを実行します。

### 統合
- `bake_objects`: Grasshopper のジオメトリを Rhino ドキュメントにベイク（書き出し）します。

---
**[ README に戻る ]](../README_JP.md)**

