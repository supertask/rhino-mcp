# Rhino-MCP テストシナリオ

このドキュメントは、RhinoおよびGrasshopperのMCPツールを網羅的にテストするためのプロンプト集です。
各セクションのプロンプトをチャット欄に入力して、動作を確認してください。

## 1. 接続と基本情報の確認 (Connectivity & Basics)

**目的**: サーバーが正常に動作し、Rhino/Grasshopperと通信できているか確認する。

*   **Prompt 1 (Rhino基本情報)**:
    `Rhinoのシーン情報とレイヤー一覧を取得して。`
    *(期待される動作: `get_scene_info`, `get_layers` が呼ばれ、現在のRhinoの状態が表示される)*

*   **Prompt 2 (Grasshopper接続確認)**:
    `Grasshopperサーバーが利用可能か確認し、現在のキャンバスの統計情報（コンポーネント数など）を教えて。`
    *(期待される動作: `is_server_available`, `get_canvas_stats` が呼ばれる)*

## 2. Rhino操作 (Rhino Operations)

**目的**: Rhino側でのオブジェクト作成、メタデータ付与、ビューポートキャプチャを確認する。

*   **Prompt 3 (オブジェクト作成とメタデータ)**:
    `Rhinoで原点に10x10x10のボックスを作成し、「TestBox」という名前と説明を付けてメタデータを登録して。その後、シーン内のオブジェクトをメタデータ付きでリストアップして確認して。`
    *(期待される動作: `execute_rhino_code` でボックス作成と `add_object_metadata` 実行、その後 `get_scene_objects_with_metadata` で確認)*

*   **Prompt 4 (ビューポートキャプチャ)**:
    `現在のRhinoビューポートのキャプチャ画像を撮って表示して。注釈(annotations)も表示して。`
    *(期待される動作: `capture_viewport` が呼ばれ、画像が表示される)*

## 3. Grasshopper キャンバス操作 (Canvas Operations)

**目的**: コンポーネントの作成、検索、削除、キャンバスクリアを確認する。

*   **Prompt 5 (キャンバスクリーンアップ)**:
    `一度Grasshopperキャンバスを完全にクリアして。`
    *(期待される動作: `clear_canvas` が `confirm=True` で呼ばれる)*

*   **Prompt 6 (コンポーネント検索と作成)**:
    `"Slider"という名前を含むコンポーネントを検索して。その後、キャンバスの(0,0)に「Number Slider」を、(200,0)に「Panel」を作成して。`
    *(期待される動作: `search_components` -> `create_component` x2)*

*   **Prompt 7 (グループ化と削除)**:
    `今作ったSliderとPanelをグループ化して「TestGroup」という名前にして。その後、グループとコンポーネントを全て削除して。`
    *(期待される動作: `create_group` -> `delete_objects`)*

## 4. ノード接続とパラメータ操作 (Nodes & Connections)

**目的**: コンポーネント間の接続、値の設定、状態変更を確認する。

*   **Prompt 8 (基本接続テスト)**:
    `以下の手順を実行して：
    1. キャンバスをクリア
    2. (0,0)に「Number Slider」、(300,0)に「Panel」を作成
    3. Sliderの値を 10.5 に設定（最小0、最大20、小数1桁）
    4. Sliderの出力をPanelの入力に接続
    5. Panelの表示状態(Preview)をOFFにする`
    *(期待される動作: `clear_canvas`, `create_component`, `set_component_value`, `connect_components`, `set_component_state`)*

## 5. 高度なGrasshopper操作 (Advanced GH)

**目的**: スクリプトコンポーネントの操作、外部コード参照、Bake、パターン利用を確認する。

*   **Prompt 9 (Pythonスクリプト作成)**:
    `GhPython Scriptコンポーネントを作成し、そのコードを「xとyを入力として受け取り、x+yをresultとして出力する」簡単な計算スクリプトに更新して。パラメータもx, y (float) に定義し直して。`
    *(期待される動作: `create_component` -> `update_script`)*

*   **Prompt 10 (外部ファイル参照)**:
    `今作成したGhPythonコンポーネントを、外部ファイル「test_script.py」を参照するように変更して。`
    *(期待される動作: `update_script_with_code_reference`)*

*   **Prompt 11 (Bake)**:
    `(0,0)に「Sphere」コンポーネントを作成し、半径を10に設定して。その後、その球体をRhinoにBake(焼き付け)して、BakeされたオブジェクトのIDを教えて。`
    *(期待される動作: `create_component` -> `set_component_value` -> `bake_objects`)*

*   **Prompt 12 (ナレッジベース/パターン利用)**:
    `利用可能なGrasshopperのパターン(レシピ)の一覧を教えて。`
    *(期待される動作: `get_available_patterns`)*

## 6. 総合テスト (End-to-End)

**目的**: 複数のツールを組み合わせて意味のあるモデルを作成する。

*   **Prompt 13 (パラメトリックタワー)**:
    `Grasshopperでシンプルなパラメトリックタワーを作って。
    1. XY平面に円を作成（半径はスライダーで制御）
    2. その円をZ方向にシリーズ(Series)で複製（階数と高さをスライダーで制御）
    3. 複製した円をLoftで繋いでサーフェス化
    4. 最後にBakeする
    これらを順次実行し、都度Rhinoのビューポートで確認したい。`

