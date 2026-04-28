"""JSON 文件存储层，管理用例集与运行配置"""
import json
import os
import uuid
import threading
from typing import List, Dict, Any, Optional

from ..config import SUITES_FILE, CONFIG_FILE, DEFAULT_LLM_CONFIG, DEFAULT_BROWSER_CONFIG

_LOCK = threading.Lock()


def _read_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: str, data: Any):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ======================= 配置 =======================
def load_config() -> Dict[str, Any]:
    cfg = _read_json(CONFIG_FILE, {})
    merged = {
        "llm": {**DEFAULT_LLM_CONFIG, **(cfg.get("llm") or {})},
        "browser": {**DEFAULT_BROWSER_CONFIG, **(cfg.get("browser") or {})},
    }
    return merged


def save_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    current = load_config()
    if "llm" in cfg:
        current["llm"].update(cfg["llm"])
    if "browser" in cfg:
        current["browser"].update(cfg["browser"])
    _write_json(CONFIG_FILE, current)
    return current


# ======================= 用例集 =======================
def list_suites() -> List[Dict[str, Any]]:
    with _LOCK:
        return _read_json(SUITES_FILE, [])


def get_suite(suite_id: str) -> Optional[Dict[str, Any]]:
    for s in list_suites():
        if s.get("id") == suite_id:
            return s
    return None


def save_suites(suites: List[Dict[str, Any]]):
    with _LOCK:
        _write_json(SUITES_FILE, suites)


def create_suite(payload: Dict[str, Any]) -> Dict[str, Any]:
    suites = list_suites()
    suite = {
        "id": payload.get("id") or _gen_id("suite"),
        "name": payload.get("name", "新建用例集"),
        "description": payload.get("description", ""),
        "base_url": payload.get("base_url", ""),
        "tags": payload.get("tags", []),
        "cases": _normalize_cases(payload.get("cases", [])),
    }
    suites.append(suite)
    save_suites(suites)
    return suite


def update_suite(suite_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    suites = list_suites()
    for idx, s in enumerate(suites):
        if s["id"] == suite_id:
            s.update({
                "name": payload.get("name", s.get("name")),
                "description": payload.get("description", s.get("description", "")),
                "base_url": payload.get("base_url", s.get("base_url", "")),
                "tags": payload.get("tags", s.get("tags", [])),
                "cases": _normalize_cases(payload.get("cases", s.get("cases", []))),
            })
            suites[idx] = s
            save_suites(suites)
            return s
    return None


def delete_suite(suite_id: str) -> bool:
    suites = list_suites()
    new = [s for s in suites if s["id"] != suite_id]
    if len(new) == len(suites):
        return False
    save_suites(new)
    return True


def find_case(case_id: str):
    """返回 (suite, case) 二元组，找不到返回 (None, None)"""
    for s in list_suites():
        for c in s.get("cases", []):
            if c.get("id") == case_id:
                return s, c
    return None, None


def _normalize_cases(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    for c in cases or []:
        steps = []
        for st in c.get("steps", []) or []:
            steps.append({
                "id": st.get("id") or _gen_id("step"),
                "description": st.get("description", ""),
                "expected": st.get("expected", ""),
                "actual": st.get("actual", ""),
                "status": st.get("status", "pending"),
            })
        result.append({
            "id": c.get("id") or _gen_id("case"),
            "name": c.get("name", "新用例"),
            "precondition": c.get("precondition", ""),
            "steps": steps,
        })
    return result


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"