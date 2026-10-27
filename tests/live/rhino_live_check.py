# -*- coding: utf-8 -*-
"""本物の Rhino を使った手動確認（自動テストでは実行されません）

使い方（リポジトリのフォルダで）:
    uv run python tests/live/rhino_live_check.py            # Enter で 1 項目ずつ進む
    uv run python tests/live/rhino_live_check.py --yes      # 止まらずに全部実行

前提:
- Rhino 7 の起動時に rhino_mcp_bridge.py が自動で実行される設定になっていること
  （なっていなければ --run-bridge を付ける）
- Rhino を閉じた状態で実行すること。Rhino が起動していたら何もせずに終了します。
- Rhino は新規の空ドキュメントで起動し、作ったものは保存せずに閉じます。

詳しくは tests/live/README.md を参照してください。
"""
import argparse
import collections
import importlib.metadata
import json
import logging
import os
import socket
import struct
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

from mcp.server.fastmcp import FastMCP  # noqa: E402
import rhino_mcp.rhino_tools as rhino_tools  # noqa: E402
from rhino_mcp.rhino_tools import (RhinoCommandError, RhinoConnection,  # noqa: E402
                                   RhinoConnectionError, RhinoTools)

DEFAULT_RHINO_EXE = r"C:\Program Files\Rhino 7\System\Rhino.exe"
BRIDGE = os.path.join(ROOT, "rhino_scripts", "rhino_mcp_bridge.py")
LOG = os.path.join(os.path.expanduser("~"), "AppData", "Local", "RhinoMCP", "logs", "rhino_mcp.log")
LAYER = u"MCP確認_日本語"
ERROR_WORDS = ("Error", "error", u"エラー", "10022", "10053", "10054")

results = []   # (name, status) status: "pass" / "fail" / "known"
options = None


# ------------------------------------------------------------------ 表示

def title(n, text):
    print()
    print("=" * 70)
    print(u"【確認 {0}】{1}".format(n, text))
    print("=" * 70)


def wait_enter(msg=u"Enter を押すと実行します..."):
    if options.yes:
        return
    try:
        input(msg)
    except EOFError:
        pass


def judge(name, ok, detail="", known_issue=False):
    if ok:
        status, mark = "pass", u"✔ 合格"
    elif known_issue:
        status, mark = "known", u"△ 既知の問題"
    else:
        status, mark = "fail", u"✖ 不合格"
    print(u"  → {0}: {1} {2}".format(mark, name, detail))
    results.append((name, status))


# ------------------------------------------------------------------ Rhino 操作

def rhino_running():
    # Compare bytes: tasklist prints in the console code page (cp932 on Japanese
    # Windows), which fails to decode when Python runs in UTF-8 mode
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Rhino.exe", "/NH"],
                         capture_output=True).stdout
    return b"rhino.exe" in out.lower()


def port_open():
    try:
        socket.create_connection(("127.0.0.1", 9876), timeout=1).close()
        return True
    except OSError:
        return False


def start_rhino():
    args = [options.rhino_exe, "/nosplash"]
    if options.run_bridge:
        args.append('/runscript=_-RunPythonScript "{0}"'.format(BRIDGE))
    subprocess.Popen(args)
    for _ in range(90):
        time.sleep(1)
        if port_open():
            time.sleep(1)
            return True
    return False


def exit_rhino():
    """Close the Rhino this script started, without saving."""
    c = RhinoConnection()
    try:
        c.send_command("execute_code", {"code": "import Rhino, scriptcontext as sc\n"
                                                 "sc.doc.Modified = False\nRhino.RhinoApp.Exit()"})
    except Exception:
        pass   # Rhino may close before it answers
    c.disconnect()
    for _ in range(30):
        time.sleep(1)
        if not port_open():
            return True
    return False


def run(conn, code):
    return conn.send_command("execute_code", {"code": code})["result"]


def history(conn):
    return run(conn, "import Rhino\nresult = Rhino.RhinoApp.CommandHistoryWindowText").splitlines()


def new_error_lines(before, after):
    """Error-looking lines that appeared on Rhino's command line."""
    added = collections.Counter(after) - collections.Counter(before)
    return [l for l in added.elements()
            if any(w in l for w in ERROR_WORDS)
            and not l.startswith(("Executing code:", "Sending response:", "Error: {'status'"))]


def count_objects(conn):
    return int(run(conn, u"import rhinoscriptsyntax as rs\n"
                         u"ids = rs.ObjectsByLayer(u'%s') if rs.IsLayer(u'%s') else []\n"
                         u"result = len(ids or [])" % (LAYER, LAYER)))


def on_layer(statement):
    return (u"import rhinoscriptsyntax as rs\n"
            u"if not rs.IsLayer(u'%s'): rs.AddLayer(u'%s', (255, 0, 0))\n"
            u"rs.CurrentLayer(u'%s')\n%s\n" % (LAYER, LAYER, LAYER, statement))


def hard_reset(sock):
    """Close with RST, as when Codex kills its MCP server process."""
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    sock.close()


def log_lines_since(t0, keyword):
    if not os.path.exists(LOG):
        return []
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0))
    out = []
    with open(LOG, "rb") as f:
        for raw in f:
            line = raw.decode("utf-8", "replace").rstrip()
            if len(line) < 400 and line[1:20] >= stamp and keyword in line:
                out.append(line)
    return out


def new_tools(timeout=None):
    rhino_tools._rhino_connection = RhinoConnection()
    if timeout:
        rhino_tools._rhino_connection.timeout = timeout
    return RhinoTools(FastMCP("rhino-live-check"))


# ------------------------------------------------------------------ 確認項目

def check_disconnect(conn):
    title(1, u"接続が切れても 10022 などのエラーが画面に出ない")
    print(u"確認: Rhino に接続 → 何もせずに強制切断（Codex が MCP を終了したのと同じ）を 3 回行います。")
    print(u"見る所: Rhino のコマンドラインにエラーが増えないこと。")
    wait_enter()
    before = history(conn)
    t0 = time.time() - 1
    for _ in range(3):
        hard_reset(socket.create_connection(("127.0.0.1", 9876), timeout=10))
        time.sleep(0.3)
    time.sleep(1)
    errors = new_error_lines(before, history(conn))
    for l in errors:
        print(u"    | " + l)
    judge(u"切断で画面にエラーが出ない", not errors, u"（増えたエラー行: {0}）".format(len(errors)))
    logged = log_lines_since(t0, "Client connection closed")
    print(u"  ログファイルにだけ記録された行: {0} 行（{1}）".format(len(logged), LOG))
    judge(u"切断はログファイルにだけ記録される", len(logged) >= 3)


def check_restart(conn):
    title(2, u"Rhino を再起動しても、最初の操作が失敗しない")
    print(u"確認: 今の接続を持ったまま Rhino を終了 → 再起動 → 古い接続のまま「球を 1 つ作る」を送ります。")
    wait_enter(u"Enter で Rhino を終了して再起動します（保存しません）...")
    old_pid = conn.send_command("get_server_status")["pid"]
    exit_rhino()
    if not start_rhino():
        judge(u"Rhino の再起動", False, u"（ブリッジが 90 秒以内に応答しませんでした）")
        return False
    try:
        r = run(conn, on_layer(u"rs.AddSphere((0, 0, 0), 5)\nrs.ZoomExtents()\nresult = u'球を作りました'"))
        ok = r == u"球を作りました"
    except Exception as e:
        print(u"  エラー: {0}".format(e))
        ok = False
    new_pid = conn.send_command("get_server_status")["pid"]
    judge(u"再起動後の最初の操作が 1 回で成功", ok and new_pid != old_pid,
          u"（PID {0} → {1}）".format(old_pid, new_pid))
    n = count_objects(conn)
    judge(u"球は 1 つだけ（二重に作られていない）", n == 1, u"（{0} 個）".format(n))
    return True


def check_no_double_execution(conn):
    title(3, u"通信が途中で切れても、同じ操作が二重に実行されない")
    print(u"確認 3-a: 「2 秒待って点を 1 つ作る」を送り、処理中に強制切断します。")
    wait_enter()
    before_n = count_objects(conn)
    before = history(conn)
    s = socket.create_connection(("127.0.0.1", 9876), timeout=10)
    s.sendall(json.dumps({"type": "execute_code", "params": {"code": on_layer(
        u"import time\ntime.sleep(2)\nrs.AddPoint((10, 0, 0))")}}).encode("utf-8"))
    time.sleep(0.3)
    hard_reset(s)
    time.sleep(3)
    after_n = count_objects(conn)
    added = list((collections.Counter(history(conn)) - collections.Counter(before)).elements())
    notices = [l for l in added if u"結果を返せませんでした" in l]
    judge(u"切断されても点は 1 つだけ", after_n == before_n + 1, u"（{0} → {1}）".format(before_n, after_n))
    judge(u"「結果を返せませんでした」が 1 行だけ出る", len(notices) == 1)

    print()
    print(u"確認 3-b: 待ち時間を 1 秒にして「3 秒待って点を 1 つ作る」を送ります（タイムアウト）。")
    wait_enter()
    before_n = count_objects(conn)
    text = new_tools(timeout=1.0).execute_rhino_code(
        None, on_layer(u"import time\ntime.sleep(3)\nrs.AddPoint((20, 0, 0))"))
    print(u"  Codex（AI）に返る文章: " + text)
    time.sleep(4)
    after_n = count_objects(conn)
    judge(u"「再送していません」と返る", u"自動では再送していません" in text)
    judge(u"点は 1 つだけ（二重実行なし）", after_n == before_n + 1, u"（{0} → {1}）".format(before_n, after_n))
    rhino_tools._rhino_connection.disconnect()


def check_tools(conn):
    title(4, u"Rhino の各ツールが動く（日本語を含む）")
    print(u"確認: Codex が使う 5 つのツールを 1 回ずつ実行します。")
    wait_enter()
    tools = new_tools()
    out = tools.execute_rhino_code(None, on_layer(
        u"pid = rs.AddPoint((30, 0, 0))\nadd_object_metadata(pid, u'確認用の点', u'説明')\nresult = u'作成しました'"))
    judge(u"execute_rhino_code（日本語の結果）", out == u"作成しました", u"（{0}）".format(out))

    out = tools.get_scene_info(None)
    judge(u"get_scene_info（日本語のレイヤー名がそのまま読める）", LAYER in out and "\\u30" not in out)

    out = tools.get_layers(None)
    try:
        layer_counts = dict((l["name"], l["object_count"]) for l in json.loads(out)["layers"])
    except ValueError:
        layer_counts = {}
    expected = count_objects(conn)
    judge(u"get_layers（日本語のレイヤーのオブジェクト数が合う）", layer_counts.get(LAYER) == expected,
          u"（{0} 個 / 実際 {1} 個）".format(layer_counts.get(LAYER), expected) if layer_counts else u"（{0}）".format(out[:80]))

    out = json.loads(tools.get_scene_objects_with_metadata(None, filters={"name": u"確認用*"}))
    meta = out["objects"][0].get("metadata", {}) if out.get("objects") else {}
    judge(u"get_scene_objects_with_metadata（メタデータ付きで見つかる）",
          out.get("count") == 1 and "short_id" in meta)

    images = tools.capture_viewport(None, view="Top", max_size=300)
    judge(u"capture_viewport（画像が返る）", len(images) == 1 and len(images[0].data) > 1000)
    rhino_tools._rhino_connection.disconnect()


def check_errors(conn):
    title(5, u"想定外のエラーやおかしな入力でも止まらない")
    wait_enter()
    try:
        run(conn, u"raise ValueError(u'わざと起こしたエラー')")
        judge(u"エラーの内容が日本語で返る", False)
    except RhinoCommandError as e:
        judge(u"エラーの内容が日本語で返る", u"わざと起こしたエラー" in str(e))
    s = socket.create_connection(("127.0.0.1", 9876), timeout=10)
    s.sendall(b"[1, 2, 3]")
    reply = s.recv(4096).decode("utf-8")
    s.close()
    judge(u"おかしな入力にはエラーで応答", '"status": "error"' in reply)
    judge(u"そのあとも普通に操作できる", run(conn, u"result = u'まだ動いています'") == u"まだ動いています")


def check_mcp_version():
    title(6, u"MCP ライブラリのバージョン")
    version = importlib.metadata.version("mcp")
    judge(u"mcp は 1 系（2 系では起動できない）", version.startswith("1."), u"（mcp {0}）".format(version))


def check_rhino_closed():
    title(7, u"Rhino を閉じているときは分かりやすいメッセージが出る")
    wait_enter(u"Enter で Rhino を終了します（保存しません）...")
    exit_rhino()
    try:
        RhinoConnection().send_command("execute_code", {"code": "pass"})
        judge(u"「Rhinoに接続できません…」と表示される", False)
    except RhinoConnectionError as e:
        print(u"  表示されるメッセージ: " + str(e))
        judge(u"「Rhinoに接続できません…」と表示される", u"Rhinoに接続できません" in str(e))


# ------------------------------------------------------------------ main

def main():
    global options
    parser = argparse.ArgumentParser(description=u"本物の Rhino を使った rhino-mcp の確認")
    parser.add_argument("--yes", action="store_true", help=u"Enter を待たずに全部実行する")
    parser.add_argument("--rhino-exe", default=os.environ.get("RHINO_EXE", DEFAULT_RHINO_EXE))
    parser.add_argument("--run-bridge", action="store_true",
                        help=u"起動時に rhino_mcp_bridge.py を実行させる（自動実行を設定していない場合）")
    parser.add_argument("--verbose", action="store_true", help=u"MCP 側の動作ログも表示する")
    options = parser.parse_args()
    if not options.verbose:
        logging.disable(logging.CRITICAL)

    print(u"rhino-mcp の実機確認を始めます。")
    if rhino_running():
        print(u"Rhino が起動しています。作業中のデータを守るため、Rhino を閉じてから実行してください。")
        return 2
    if not os.path.exists(options.rhino_exe):
        print(u"Rhino が見つかりません: {0}（--rhino-exe で指定できます）".format(options.rhino_exe))
        return 2
    print(u"Rhino を新規の空ドキュメントで起動します。作ったものは保存しません。")
    wait_enter(u"Enter で Rhino を起動します...")
    if not start_rhino():
        print(u"Rhino のブリッジが 90 秒以内に応答しませんでした。"
              u"起動時の自動実行を設定していない場合は --run-bridge を付けてください。")
        return 1

    conn = RhinoConnection()
    try:
        check_disconnect(conn)
        if check_restart(conn):
            check_no_double_execution(conn)
            check_tools(conn)
            check_errors(conn)
        check_mcp_version()
        check_rhino_closed()
    finally:
        conn.disconnect()
        if port_open():
            exit_rhino()

    print()
    print("=" * 70)
    passed = sum(1 for _, s in results if s == "pass")
    failed = [n for n, s in results if s == "fail"]
    known = [n for n, s in results if s == "known"]
    print(u"まとめ: {0} 項目中 合格 {1} / 不合格 {2} / 既知の問題 {3}".format(
        len(results), passed, len(failed), len(known)))
    for name, status in results:
        print(u"  {0} {1}".format({"pass": u"✔", "fail": u"✖", "known": u"△"}[status], name))
    print("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
