"""
Flask 主入口：提供 REST API 与前端静态文件服务。

启动方式（在仓库根目录）::

    python -m ui-automation-platform.backend.app
    # 或
    cd ui-automation-platform && python -m backend.app
"""
import os
import sys

# Windows 控制台默认 GBK，emoji（如 🎥）会触发 UnicodeEncodeError，
# 在最早期把 stdout/stderr 切成 UTF-8 并对不可编码字符做替换，避免后台日志崩溃。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from flask import Flask, jsonify, request, send_from_directory, abort

# 兼容 "python backend/app.py" 与 "python -m backend.app"
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from backend.models import storage
    from backend.core import runner
    from backend.core.parser import parse_step, get_keyword_help
    from backend.core.llm_parser import LLMParser
    from backend.config import SCREENSHOTS_DIR
else:
    from .models import storage
    from .core import runner
    from .core.parser import parse_step, get_keyword_help
    from .core.llm_parser import LLMParser
    from .config import SCREENSHOTS_DIR

try:
    from flask_cors import CORS
except ImportError:
    CORS = None

try:
    from flask_sock import Sock
except ImportError:
    Sock = None

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

app = Flask(__name__, static_folder=None)
if CORS:
    CORS(app)

sock = Sock(app) if Sock else None


# -------------------- 静态前端 --------------------
@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/<path:path>")
def static_file(path):
    full = os.path.join(FRONTEND_DIR, path)
    if os.path.isfile(full):
        return send_from_directory(FRONTEND_DIR, path)
    abort(404)


# -------------------- 截图访问 --------------------
@app.route("/api/screenshots/<path:fname>")
def screenshot(fname):
    return send_from_directory(SCREENSHOTS_DIR, fname)


@app.route("/api/screenshots")
def list_screenshots():
    if not os.path.isdir(SCREENSHOTS_DIR):
        return jsonify([])
    files = sorted(
        [f for f in os.listdir(SCREENSHOTS_DIR) if f.lower().endswith(".png")],
        reverse=True,
    )
    return jsonify(files)


# -------------------- 用例集 CRUD --------------------
@app.route("/api/suites", methods=["GET"])
def api_list_suites():
    return jsonify(storage.list_suites())


@app.route("/api/suites", methods=["POST"])
def api_create_suite():
    payload = request.get_json(force=True) or {}
    suite = storage.create_suite(payload)
    return jsonify(suite), 201


@app.route("/api/suites/<suite_id>", methods=["GET"])
def api_get_suite(suite_id):
    s = storage.get_suite(suite_id)
    if not s:
        abort(404)
    return jsonify(s)


@app.route("/api/suites/<suite_id>", methods=["PUT"])
def api_update_suite(suite_id):
    payload = request.get_json(force=True) or {}
    s = storage.update_suite(suite_id, payload)
    if not s:
        abort(404)
    return jsonify(s)


@app.route("/api/suites/<suite_id>", methods=["DELETE"])
def api_delete_suite(suite_id):
    ok = storage.delete_suite(suite_id)
    return jsonify({"ok": ok})


# -------------------- 执行 --------------------
@app.route("/api/suites/<suite_id>/run", methods=["POST"])
def api_run_suite(suite_id):
    state = runner.run_suite_async(suite_id)
    if not state:
        abort(404)
    return jsonify({"run_id": state["id"], "status": state["status"]})


@app.route("/api/cases/<case_id>/run", methods=["POST"])
def api_run_case(case_id):
    state = runner.run_case_async(case_id)
    if not state:
        abort(404)
    return jsonify({"run_id": state["id"], "status": state["status"]})


@app.route("/api/runs/<run_id>", methods=["GET"])
def api_get_run(run_id):
    state = runner.get_run(run_id)
    if not state:
        abort(404)
    return jsonify(state)


@app.route("/api/runs", methods=["GET"])
def api_list_runs():
    return jsonify(runner.list_runs())


# -------------------- 浏览器画面流 --------------------
@app.route("/api/runs/<run_id>/frame", methods=["GET"])
def api_latest_frame(run_id):
    """HTTP 兜底：返回最新一帧(JSON: {data, ts, width, height, format})"""
    frame = runner.get_latest_frame(run_id)
    if not frame:
        return jsonify({"data": None})
    return jsonify(frame)


if sock is not None:
    @sock.route("/ws/screencast/<run_id>")
    def ws_screencast(ws, run_id):
        """WebSocket 实时推送浏览器画面帧（每条消息是 JSON: {data: base64, ts, width, height}）"""
        import json as _json
        import queue as _queue
        q = runner.subscribe_frames(run_id)
        try:
            while True:
                try:
                    frame = q.get(timeout=30)
                except _queue.Empty:
                    # 发送心跳
                    try:
                        ws.send(_json.dumps({"type": "ping"}))
                    except Exception:
                        break
                    continue
                try:
                    ws.send(_json.dumps({"type": "frame", **frame}))
                except Exception:
                    break
        finally:
            runner.unsubscribe_frames(run_id, q)


# -------------------- 配置 --------------------
@app.route("/api/config", methods=["GET"])
def api_get_config():
    cfg = storage.load_config()
    # 屏蔽 api_key 中段
    api_key = cfg["llm"].get("api_key", "")
    if api_key:
        cfg["llm"]["api_key_masked"] = api_key[:4] + "***" + api_key[-4:] if len(api_key) > 8 else "***"
    return jsonify(cfg)


@app.route("/api/config", methods=["POST"])
def api_set_config():
    payload = request.get_json(force=True) or {}
    cfg = storage.save_config(payload)
    return jsonify(cfg)


# -------------------- 解析调试 --------------------
@app.route("/api/parse", methods=["POST"])
def api_parse():
    payload = request.get_json(force=True) or {}
    sentence = payload.get("sentence", "")
    action = parse_step(sentence)
    source = "keyword"
    if not action:
        cfg = storage.load_config()
        llm = LLMParser(cfg["llm"])
        if llm.is_enabled():
            action = llm.parse(sentence)
            source = "llm" if action else "none"
        else:
            source = "none"
    return jsonify({"action": action, "source": source})


@app.route("/api/keywords", methods=["GET"])
def api_keywords():
    return jsonify({"help": get_keyword_help()})


# -------------------- 启动 --------------------
def main():
    print("=" * 50)
    print("  UI 自动化平台启动中...")
    print(f"  前端目录: {FRONTEND_DIR}")
    print(f"  访问地址: http://127.0.0.1:5050")
    print(f"  浏览器画面: {'WebSocket 已启用 /ws/screencast/<run_id>' if sock else 'flask-sock 未安装，仅 HTTP 轮询可用'}")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)


if __name__ == "__main__":
    main()