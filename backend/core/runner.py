"""
运行任务调度：在后台线程执行用例集/用例，
保存运行日志、报告，对外提供 run_id 查询。
同时维护 run_id -> 最新 screencast 帧缓存 与 订阅者队列，供 WebSocket 使用。
"""
import os
import json
import time
import uuid
import queue
import threading
from typing import Dict, Any, Optional, List

from .executor import SuiteExecutor
from ..models import storage
from ..config import REPORTS_DIR

_runs: Dict[str, Dict[str, Any]] = {}     # run_id -> run state
_lock = threading.Lock()

# screencast 相关
_latest_frame: Dict[str, Dict[str, Any]] = {}       # run_id -> {"data": b64, "ts": ms}
_subscribers: Dict[str, List[queue.Queue]] = {}      # run_id -> [queue,...]
_frame_lock = threading.Lock()


def _new_run_id() -> str:
    return f"run_{int(time.time())}_{uuid.uuid4().hex[:6]}"


def _make_state(scope: str, target_name: str) -> Dict[str, Any]:
    return {
        "id": _new_run_id(),
        "scope": scope,
        "target_name": target_name,
        "status": "running",
        "logs": [],
        "summary": None,
        "started_at": int(time.time() * 1000),
        "finished_at": None,
    }


def _logger(state):
    def _log(level, msg):
        entry = {"ts": int(time.time() * 1000), "level": level, "msg": msg}
        with _lock:
            state["logs"].append(entry)
        print(f"[{level}] {msg}")
    return _log


# ---------------- screencast 接口 ----------------
def _make_frame_callback(run_id: str):
    """返回一个 frame 回调：executor 每收到一帧就调用 (base64_png, extra)"""
    def _cb(b64_data: str, extra: Optional[Dict[str, Any]] = None):
        frame = {"data": b64_data, "ts": int(time.time() * 1000)}
        if extra:
            frame.update(extra)
        with _frame_lock:
            _latest_frame[run_id] = frame
            subs = list(_subscribers.get(run_id, []))
        # 广播给所有订阅者（非阻塞）
        for q in subs:
            try:
                q.put_nowait(frame)
            except queue.Full:
                pass
    return _cb


def subscribe_frames(run_id: str) -> queue.Queue:
    """WebSocket 处理器订阅某 run 的帧流"""
    q: queue.Queue = queue.Queue(maxsize=64)
    with _frame_lock:
        _subscribers.setdefault(run_id, []).append(q)
        # 立即推送最新一帧（若有）
        last = _latest_frame.get(run_id)
    if last:
        try:
            q.put_nowait(last)
        except queue.Full:
            pass
    return q


def unsubscribe_frames(run_id: str, q: queue.Queue):
    with _frame_lock:
        lst = _subscribers.get(run_id, [])
        if q in lst:
            lst.remove(q)


def get_latest_frame(run_id: str) -> Optional[Dict[str, Any]]:
    with _frame_lock:
        return _latest_frame.get(run_id)


def _clear_frames(run_id: str):
    """任务结束后清理（保留最后一帧便于回看一段时间）"""
    with _frame_lock:
        _subscribers.pop(run_id, None)
        # 最后一帧保留不清理，便于回看


# ---------------- 持久化 ----------------
def _save_report(state):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    path = os.path.join(REPORTS_DIR, f"{state['id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _persist_case_results(state):
    summary = state.get("summary") or {}
    suite = summary.get("suite")
    if not suite:
        return
    storage.update_suite(suite["id"], suite)


# ---------------- 异步执行 ----------------
def run_suite_async(suite_id: str) -> Optional[Dict[str, Any]]:
    suite = storage.get_suite(suite_id)
    if not suite:
        return None
    cfg = storage.load_config()
    state = _make_state("suite", suite.get("name", ""))
    with _lock:
        _runs[state["id"]] = state

    frame_cb = _make_frame_callback(state["id"])

    def _worker():
        try:
            ex = SuiteExecutor(cfg["browser"], cfg["llm"],
                               logger=_logger(state),
                               frame_callback=frame_cb)
            summary = ex.run_suite(suite)
            state["summary"] = summary
            state["status"] = "done"
        except Exception as e:
            state["status"] = "error"
            state["logs"].append({"ts": int(time.time()*1000), "level": "error", "msg": str(e)})
        finally:
            state["finished_at"] = int(time.time() * 1000)
            _persist_case_results(state)
            _save_report(state)
            _clear_frames(state["id"])

    threading.Thread(target=_worker, daemon=True).start()
    return state


def run_case_async(case_id: str) -> Optional[Dict[str, Any]]:
    suite, case = storage.find_case(case_id)
    if not case:
        return None
    cfg = storage.load_config()
    state = _make_state("case", case.get("name", ""))
    with _lock:
        _runs[state["id"]] = state

    frame_cb = _make_frame_callback(state["id"])

    def _worker():
        try:
            ex = SuiteExecutor(cfg["browser"], cfg["llm"],
                               logger=_logger(state),
                               frame_callback=frame_cb)
            summary = ex.run_case(case, suite)
            summary["suite"] = {"id": suite["id"], "name": suite["name"],
                                 "base_url": suite.get("base_url", ""),
                                 "description": suite.get("description", ""),
                                 "tags": suite.get("tags", []),
                                 "cases": [c if c["id"] != case["id"] else summary["case"]
                                           for c in suite.get("cases", [])]}
            state["summary"] = summary
            state["status"] = "done"
        except Exception as e:
            state["status"] = "error"
            state["logs"].append({"ts": int(time.time()*1000), "level": "error", "msg": str(e)})
        finally:
            state["finished_at"] = int(time.time() * 1000)
            _persist_case_results(state)
            _save_report(state)
            _clear_frames(state["id"])

    threading.Thread(target=_worker, daemon=True).start()
    return state


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        return _runs.get(run_id)


def list_runs():
    with _lock:
        return [
            {k: v for k, v in r.items() if k != "logs"}
            for r in _runs.values()
        ]