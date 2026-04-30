"""
存储层（SQLite + SQLAlchemy 实现）。

对外保留与旧 JSON 版本完全一致的函数签名，
让 runner.py / app.py 无感切换：

    用例集： list_suites / get_suite / create_suite / update_suite / delete_suite / find_case
    配置：   load_config / save_config
    运行：   save_run / list_runs_db / get_run_db
"""
import uuid
from typing import List, Dict, Any, Optional

from sqlalchemy import select, delete

from ..config import DEFAULT_LLM_CONFIG, DEFAULT_BROWSER_CONFIG
from .db import session_scope
from .entities import Suite, Case, Step, Run, RunLog, StepResult, KVConfig


# ============================================================
# 内部转换：ORM <-> dict
# ============================================================
def _step_to_dict(s: Step) -> Dict[str, Any]:
    return {
        "id": s.id,
        "description": s.description or "",
        "expected": s.expected or "",
        "actual": s.actual or "",
        "status": s.status or "pending",
    }


def _case_to_dict(c: Case) -> Dict[str, Any]:
    return {
        "id": c.id,
        "name": c.name,
        "precondition": c.precondition or "",
        "status": c.status or "",
        "steps": [_step_to_dict(s) for s in c.steps],
    }


def _suite_to_dict(s: Suite) -> Dict[str, Any]:
    return {
        "id": s.id,
        "name": s.name,
        "description": s.description or "",
        "base_url": s.base_url or "",
        "tags": list(s.tags or []),
        "cases": [_case_to_dict(c) for c in s.cases],
    }


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# ============================================================
# 配置：KV 表
# ============================================================
_LLM_KEY = "llm"
_BROWSER_KEY = "browser"


def _get_kv(s, key: str) -> Optional[Dict[str, Any]]:
    row = s.get(KVConfig, key)
    return dict(row.value) if row and row.value else None


def _set_kv(s, key: str, value: Dict[str, Any]):
    row = s.get(KVConfig, key)
    if row:
        row.value = value
    else:
        s.add(KVConfig(key=key, value=value))


def load_config() -> Dict[str, Any]:
    with session_scope() as s:
        llm = _get_kv(s, _LLM_KEY) or {}
        browser = _get_kv(s, _BROWSER_KEY) or {}
    return {
        "llm": {**DEFAULT_LLM_CONFIG, **llm},
        "browser": {**DEFAULT_BROWSER_CONFIG, **browser},
    }


def save_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    current = load_config()
    if "llm" in cfg:
        current["llm"].update(cfg["llm"])
    if "browser" in cfg:
        current["browser"].update(cfg["browser"])
    with session_scope() as s:
        _set_kv(s, _LLM_KEY, current["llm"])
        _set_kv(s, _BROWSER_KEY, current["browser"])
    return current


# ============================================================
# 用例集 CRUD
# ============================================================
def list_suites() -> List[Dict[str, Any]]:
    with session_scope() as s:
        rows = s.execute(select(Suite).order_by(Suite.created_at)).scalars().all()
        return [_suite_to_dict(x) for x in rows]


def get_suite(suite_id: str) -> Optional[Dict[str, Any]]:
    with session_scope() as s:
        row = s.get(Suite, suite_id)
        return _suite_to_dict(row) if row else None


def create_suite(payload: Dict[str, Any]) -> Dict[str, Any]:
    suite_id = payload.get("id") or _gen_id("suite")
    with session_scope() as s:
        suite = Suite(
            id=suite_id,
            name=payload.get("name", "新建用例集"),
            description=payload.get("description", ""),
            base_url=payload.get("base_url", ""),
            tags=list(payload.get("tags") or []),
        )
        _build_cases(suite, payload.get("cases", []))
        s.add(suite)
        s.flush()
        return _suite_to_dict(suite)


def update_suite(suite_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    with session_scope() as s:
        suite = s.get(Suite, suite_id)
        if not suite:
            return None
        suite.name = payload.get("name", suite.name)
        suite.description = payload.get("description", suite.description or "")
        suite.base_url = payload.get("base_url", suite.base_url or "")
        suite.tags = list(payload.get("tags", suite.tags or []))

        if "cases" in payload:
            # 用 incoming 数据全量覆盖（保留 id 以避免 step_results 外键悬空）
            existing_cases = {c.id: c for c in suite.cases}
            existing_steps = {st.id: st for c in suite.cases for st in c.steps}
            new_case_ids = set()
            new_step_ids = set()

            for ci, c_in in enumerate(payload.get("cases") or []):
                cid = c_in.get("id") or _gen_id("case")
                new_case_ids.add(cid)
                case = existing_cases.get(cid)
                if not case:
                    case = Case(id=cid, suite_id=suite.id)
                    suite.cases.append(case)
                case.name = c_in.get("name", "未命名用例")
                case.precondition = c_in.get("precondition", "")
                case.order_no = ci
                if "status" in c_in:
                    case.status = c_in.get("status") or ""

                for si, st_in in enumerate(c_in.get("steps") or []):
                    sid = st_in.get("id") or _gen_id("step")
                    new_step_ids.add(sid)
                    step = existing_steps.get(sid)
                    if not step or step.case_id != case.id:
                        step = Step(id=sid, case_id=case.id)
                        case.steps.append(step)
                    step.description = st_in.get("description", "")
                    step.expected = st_in.get("expected", "")
                    step.actual = st_in.get("actual", step.actual or "")
                    step.status = st_in.get("status", step.status or "pending")
                    step.order_no = si

            # 删除 incoming 中不存在的旧 case/step
            for cid, case in list(existing_cases.items()):
                if cid not in new_case_ids:
                    s.delete(case)
                else:
                    for sid, step in list({st.id: st for st in case.steps}.items()):
                        if sid not in new_step_ids:
                            s.delete(step)

        s.flush()
        return _suite_to_dict(suite)


def delete_suite(suite_id: str) -> bool:
    with session_scope() as s:
        row = s.get(Suite, suite_id)
        if not row:
            return False
        s.delete(row)
        return True


def find_case(case_id: str):
    """返回 (suite_dict, case_dict)；找不到返回 (None, None)"""
    with session_scope() as s:
        case = s.get(Case, case_id)
        if not case:
            return None, None
        return _suite_to_dict(case.suite), _case_to_dict(case)


def _build_cases(suite: Suite, cases_in: List[Dict[str, Any]]):
    """新建 suite 时构造 cases/steps 子树。"""
    for ci, c in enumerate(cases_in or []):
        case = Case(
            id=c.get("id") or _gen_id("case"),
            suite_id=suite.id,
            name=c.get("name", "新用例"),
            precondition=c.get("precondition", ""),
            order_no=ci,
        )
        for si, st in enumerate(c.get("steps") or []):
            case.steps.append(Step(
                id=st.get("id") or _gen_id("step"),
                case_id=case.id,
                description=st.get("description", ""),
                expected=st.get("expected", ""),
                actual=st.get("actual", ""),
                status=st.get("status", "pending"),
                order_no=si,
            ))
        suite.cases.append(case)


# ============================================================
# 运行记录持久化
# ============================================================
def save_run(state: Dict[str, Any]):
    """
    把内存 run state 落库（结束时一次性写入）。

    state 结构与 runner._make_state 对齐：
      id, scope, target_name, status, logs[], summary, started_at, finished_at
    summary 可能含 suite/case 全量树，这里只取轻量 summary 字段；
    每个步骤的明细另存到 step_results 表。
    """
    summary = state.get("summary") or {}
    light_summary = {
        k: summary.get(k)
        for k in ("suite_name", "case_name", "passed", "failed", "skipped",
                  "total", "duration_ms", "error")
        if k in summary
    }

    with session_scope() as s:
        run = Run(
            id=state["id"],
            scope=state.get("scope", ""),
            target_id=(summary.get("suite") or {}).get("id")
                       or (summary.get("case") or {}).get("id"),
            target_name=state.get("target_name", ""),
            status=state.get("status", "done"),
            started_at=state.get("started_at"),
            finished_at=state.get("finished_at"),
            summary=light_summary,
        )
        s.add(run)

        # 日志
        for log in state.get("logs") or []:
            s.add(RunLog(run_id=run.id, ts=log.get("ts"),
                         level=log.get("level", "info"), msg=log.get("msg", "")))

        # 步骤结果（从 summary.suite.cases[].steps 或 summary.case.steps 提取）
        cases = []
        if summary.get("suite") and summary["suite"].get("cases"):
            cases = summary["suite"]["cases"]
        elif summary.get("case"):
            cases = [summary["case"]]

        idx = 0
        for c in cases:
            for st in c.get("steps") or []:
                s.add(StepResult(
                    run_id=run.id,
                    case_id=c.get("id"),
                    step_id=st.get("id"),
                    idx=idx,
                    description=st.get("description", ""),
                    expected=st.get("expected", ""),
                    actual=st.get("actual", ""),
                    status=st.get("status", ""),
                    ts=state.get("finished_at"),
                ))
                idx += 1


def list_runs_db(limit: int = 50) -> List[Dict[str, Any]]:
    """运行历史（最近 N 条，按开始时间倒序）。"""
    with session_scope() as s:
        rows = s.execute(
            select(Run).order_by(Run.started_at.desc()).limit(limit)
        ).scalars().all()
        return [{
            "id": r.id,
            "scope": r.scope,
            "target_id": r.target_id,
            "target_name": r.target_name,
            "status": r.status,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "summary": r.summary or {},
        } for r in rows]


def get_run_db(run_id: str) -> Optional[Dict[str, Any]]:
    """从库里获取单次运行（含日志 + 步骤结果）。"""
    with session_scope() as s:
        r = s.get(Run, run_id)
        if not r:
            return None
        return {
            "id": r.id,
            "scope": r.scope,
            "target_id": r.target_id,
            "target_name": r.target_name,
            "status": r.status,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "summary": r.summary or {},
            "logs": [{"ts": x.ts, "level": x.level, "msg": x.msg}
                     for x in sorted(r.logs, key=lambda x: x.ts or 0)],
            "step_results": [{
                "case_id": x.case_id, "step_id": x.step_id, "idx": x.idx,
                "description": x.description, "expected": x.expected,
                "actual": x.actual, "status": x.status, "ts": x.ts,
            } for x in sorted(r.step_results, key=lambda x: x.idx or 0)],
        }