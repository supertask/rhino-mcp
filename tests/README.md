# テスト

rhino-mcp のテストは 3 段階に分かれています。①と②は Rhino がなくても数秒〜数十秒で終わり、③だけが本物の Rhino を使います。

| 段階 | ファイル | 内容 | Rhino |
|---|---|---|---|
| ① MCP 側 | `test_rhino_connection.py` | Rhino への接続・再接続・二重実行の防止 | 不要 |
| | `test_rhino_tools.py` | Rhino の各ツールが送るコマンドと、返す結果 | 不要 |
| | `test_grasshopper_tools.py` | Grasshopper の各ツールが送るリクエストと、返す結果 | 不要 |
| | `test_grasshopper_input.py` | AI が書いた崩れた JSON を直す関数 | 不要 |
| ② ブリッジ | `test_rhino_bridge_client.py` | Rhino 側ブリッジの通信処理（切断・分割受信など） | 不要 |
| | `test_grasshopper_bridge_http.py` | Grasshopper 側ブリッジの HTTP 処理とコマンド処理の共通部分 | 不要 |
| ③ 実機 | `live/rhino_live_check.py` | 本物の Rhino で通信まわりと各ツールを確認 | **必要** |

## ①②の実行

リポジトリのフォルダで実行します。

```bash
uv run python -m unittest discover -s tests -v
```

- 偽の Rhino / Grasshopper を、空いている別のポートで動かして確認します。実際のポート 9876 / 9999 は使いません。
- ブリッジのスクリプトは、Rhino / .NET / Grasshopper の部分を差し替えて読み込みます。ポートを使用中のプロセスを強制終了する処理は、テストでは必ず無効にしています。
- ログは、ユーザーの `RhinoMCP` ログフォルダではなく一時フォルダに書き込みます。
- `mcp` や `Pillow` が入っていない環境では、最小限の代用品を使って動きます。Grasshopper のテストには `requests` が必要です。

### 「既知の問題」のテスト

`test_known_issue_...` という名前のテストは、**今の動きが望ましくないこと**を記録したものです。`unittest.expectedFailure` を付けてあるので、失敗しても全体は合格（`expected failures` として表示）になります。コードを直してこのテストが通るようになったら、`unexpected success` と表示されます。その時点で `expectedFailure` を外してください。

## ③の実行

[live/README.md](live/README.md) を参照してください。

## 限界

- ブリッジは Rhino 内の IronPython 2.7 で動きますが、①②は CPython 3 で実行しています。IronPython 特有の動き（たとえば `recv()` の失敗がすべて errno 10022 になること）は、③でしか確認できません。
- Grasshopper 本体の API を使う部分（部品の作成や配線など）は、①②では確認していません。
