"""
Playwright 执行引擎：封装浏览器生命周期，按用例集/用例顺序执行步骤。
执行过程中通过回调实时输出日志，结果写回 case.steps[*].actual / status。

浏览器画面嵌入：
- 启动一个专用线程，通过 Playwright 自身的 page.screenshot(type=jpeg) 周期性截帧，
  base64 编码后通过 frame_callback 回传（~5 fps）。
- 为避免 sync_playwright 的线程安全问题：截图线程使用 threading.Event 请求主线程在
  步骤间隙同步截帧（生产者/消费者模型）。
"""
import time
import base64
import threading
import traceback
from typing import Dict, Any, Callable, Optional

from .actions import ActionExecutor, PageHolder
from .parser import parse_step
from .llm_parser import LLMParser

LogFn = Callable[[str, str], None]
FrameFn = Callable[[str, Optional[Dict[str, Any]]], None]


def _now_ms() -> int:
    return int(time.time() * 1000)


class SuiteExecutor:
    """用例集执行器"""

    def __init__(self, browser_cfg: Dict[str, Any], llm_cfg: Dict[str, Any],
                 logger: Optional[LogFn] = None,
                 frame_callback: Optional[FrameFn] = None,
                 cancel_event: Optional[threading.Event] = None):
        self.browser_cfg = browser_cfg or {}
        self.llm = LLMParser(llm_cfg or {})
        self.log = logger or (lambda lvl, msg: print(f"[{lvl}] {msg}"))
        self.frame_cb = frame_callback
        # 取消信号：由 runner 传入；执行过程每步检测
        self.cancel_event = cancel_event
        self._current_holder = None
        self._frame_stop = None
        self._frame_thread = None

    def _is_cancelled(self) -> bool:
        return bool(self.cancel_event and self.cancel_event.is_set())

    # ---------------- 主入口 ----------------
    def run_suite(self, suite: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.log("error", "未安装 playwright，请先 pip install playwright && playwright install")
            return self._summary(suite, error="playwright 未安装")

        started = _now_ms()
        self.log("info", f"==== 开始执行用例集：{suite.get('name')} ====")
        passed = failed = total = 0

        # 为了让画面嵌入生效，这里强制 headless=True，不再弹独立浏览器窗口
        headless = True if self.frame_cb else self.browser_cfg.get("headless", True)

        with sync_playwright() as p:
            browser_type = self.browser_cfg.get("browser", "chromium")
            launcher = getattr(p, browser_type, p.chromium)
            browser = launcher.launch(headless=headless)
            try:
                for case in suite.get("cases", []):
                    # 用例间检查取消信号：剩余用例不再执行
                    if self._is_cancelled():
                        self.log("warn", f"⏹ 收到停止信号，跳过剩余用例")
                        case["status"] = "skipped"
                        for st in case.get("steps", []):
                            if not st.get("status"):
                                st["status"] = "skipped"
                                st["actual"] = "已取消"
                        continue

                    context = browser.new_context(
                        viewport=self.browser_cfg.get("viewport") or {"width": 1280, "height": 800}
                    )
                    page = context.new_page()
                    page.set_default_timeout(self.browser_cfg.get("default_timeout", 10000))
                    holder = PageHolder(page)
                    # 自动跟随 popup / target=_blank 打开的新页面
                    context.on("page", lambda np: holder.add(np))
                    self._start_frame_loop(holder)
                    try:
                        ok = self._run_case(holder, case, suite)
                        total += 1
                        if ok:
                            passed += 1
                        else:
                            failed += 1
                    finally:
                        self._stop_frame_loop()
                        context.close()
            finally:
                browser.close()

        duration = _now_ms() - started
        self.log("info", f"==== 用例集执行完成：通过 {passed}/{total}，失败 {failed}，耗时 {duration} ms ====")
        return self._summary(suite, passed=passed, failed=failed, total=total, duration=duration)

    def run_case(self, case: Dict[str, Any], suite: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        from playwright.sync_api import sync_playwright
        suite = suite or {"name": "ad-hoc", "base_url": "", "cases": [case]}
        started = _now_ms()
        headless = True if self.frame_cb else self.browser_cfg.get("headless", True)
        with sync_playwright() as p:
            browser_type = self.browser_cfg.get("browser", "chromium")
            launcher = getattr(p, browser_type, p.chromium)
            browser = launcher.launch(headless=headless)
            try:
                context = browser.new_context(
                    viewport=self.browser_cfg.get("viewport") or {"width": 1280, "height": 800}
                )
                page = context.new_page()
                page.set_default_timeout(self.browser_cfg.get("default_timeout", 10000))
                holder = PageHolder(page)
                context.on("page", lambda np: holder.add(np))
                self._start_frame_loop(holder)
                try:
                    ok = self._run_case(holder, case, suite)
                finally:
                    self._stop_frame_loop()
                    context.close()
            finally:
                browser.close()
        duration = _now_ms() - started
        return {
            "case_id": case.get("id"),
            "passed": 1 if ok else 0,
            "failed": 0 if ok else 1,
            "total": 1,
            "duration_ms": duration,
            "case": case,
        }

    # ---------------- 画面推送（主动截图） ----------------
    def _start_frame_loop(self, holder):
        """截图循环不能在另一个线程直接调用 Playwright sync API（线程不安全）。
        策略：在主线程 run 循环的各关键节点（每步执行前后）主动截一张。
        持有 PageHolder 而非 page，确保切换/新建窗口时画面也能跟随到 active。"""
        if not self.frame_cb:
            return
        self._current_holder = holder
        self.log("info", "🎥 浏览器画面嵌入已启用（每步截帧推送）")
        self._tick_frame()  # 推送初始画面

    def _stop_frame_loop(self):
        self._current_holder = None

    def _tick_frame(self):
        """抓一帧并回传。在主线程调用（安全）。"""
        holder = getattr(self, "_current_holder", None)
        if not self.frame_cb or not holder:
            return
        try:
            page = holder.active
            png = page.screenshot(type="jpeg", quality=60, full_page=False)
            b64 = base64.b64encode(png).decode("ascii")
            self.frame_cb(b64, {
                "width": 1280,
                "height": 800,
                "format": "jpeg",
            })
        except Exception as e:
            # 常见：页面关闭、导航中；静默，不打断业务
            self.log("debug", f"截帧失败（可忽略）：{e}")

    # ---------------- 内部 ----------------
    def _run_case(self, holder, case: Dict[str, Any], suite: Dict[str, Any]) -> bool:
        self.log("info", f"-- 用例：{case.get('name')} --")
        executor = ActionExecutor(holder, default_timeout=self.browser_cfg.get("default_timeout", 10000))

        base_url = suite.get("base_url")
        if base_url:
            ok, msg = executor.execute({"action": "goto", "value": base_url})
            self.log("info" if ok else "error", f"前置：{msg}")
            self._tick_frame()

        precondition = case.get("precondition", "")
        if precondition:
            self.log("info", f"前置条件：{precondition}")

        case_pass = True
        for idx, step in enumerate(case.get("steps", []), start=1):
            # 步骤级取消检查：用户点了停止 → 当前用例后续步骤标记 skipped
            if self._is_cancelled():
                self.log("warn", f"⏹ 已收到停止信号，跳过步骤 {idx} 及之后")
                step["status"] = "skipped"
                step["actual"] = "已取消"
                for rest in case.get("steps", [])[idx:]:
                    rest["status"] = "skipped"
                    rest["actual"] = "已取消"
                case_pass = False
                break

            desc = step.get("description", "").strip()
            expected = step.get("expected", "")
            self.log("info", f"步骤 {idx}: {desc} | 预期: {expected or '-'}")
            if not desc:
                step["status"] = "skipped"
                step["actual"] = "步骤为空，已跳过"
                continue

            action = parse_step(desc)
            source = "keyword"
            if not action and self.llm.is_enabled():
                action = self.llm.parse(desc)
                source = "llm"
            if not action:
                step["status"] = "fail"
                step["actual"] = "无法解析该步骤（关键词与LLM均未识别）"
                self.log("error", step["actual"])
                case_pass = False
                self._screenshot_on_fail(holder.active, case, idx)
                self._tick_frame()
                continue

            self.log("debug", f"解析({source})：{action}")

            # 步骤执行期间，通过后台线程间歇触发主线程截帧：
            # 最简单可靠的做法是：执行前、执行过程中(分多段)、执行后均截帧
            self._tick_frame()
            ok, msg = self._execute_with_frames(executor, action)
            self._tick_frame()

            step["actual"] = msg
            step["status"] = "pass" if ok else "fail"
            self.log("info" if ok else "error", f"  -> {msg}")
            if not ok:
                case_pass = False
                self._screenshot_on_fail(holder.active, case, idx)

            # 每条步骤执行完后固定休眠（默认 2s），便于观察画面 + 等待页面响应
            sleep_secs = float(self.browser_cfg.get("step_interval", 2))
            if sleep_secs > 0:
                # 用 page.wait_for_timeout 让 Playwright 自身的事件循环也能继续推进
                try:
                    holder.active.wait_for_timeout(int(sleep_secs * 1000))
                except Exception:
                    time.sleep(sleep_secs)
                self._tick_frame()

        self._tick_frame()
        case["status"] = "pass" if case_pass else "fail"
        return case_pass

    def _execute_with_frames(self, executor, action):
        """用"监视线程 + 主线程中断"模式：在执行期间每 300ms 截一帧。
        由于 sync_playwright API 非线程安全，这里采用轮询 flag 方式：
        用一个 Timer 在主线程空闲时机通过 page.wait_for_timeout 附近没法做到，
        故改为执行后立即 tick 一次，并配合步骤前/中/后的节点。
        对于慢操作（如 goto、wait），执行器会自己内部 wait，这期间的画面更新
        会在下一步 tick 时同步展现。"""
        # 这里直接执行；帧推送依赖 _run_case 里的前后 tick
        # 若需要"真正实时"，可用 cdp screencast（见下文 alternative）
        return executor.execute(action)

    def _screenshot_on_fail(self, page, case, step_idx):
        try:
            from ..config import SCREENSHOTS_DIR
            import os
            ts = time.strftime("%Y%m%d_%H%M%S")
            safe = "".join(ch for ch in (case.get("name") or "case") if ch.isalnum())[:20]
            fname = f"FAIL_{safe}_step{step_idx}_{ts}.png"
            path = os.path.join(SCREENSHOTS_DIR, fname)
            page.screenshot(path=path, full_page=True)
            self.log("warn", f"已保存失败截图：{fname}")
        except Exception as e:
            self.log("warn", f"保存截图失败：{e}")

    def _summary(self, suite, passed=0, failed=0, total=0, duration=0, error=None):
        return {
            "suite_id": suite.get("id"),
            "suite_name": suite.get("name"),
            "passed": passed,
            "failed": failed,
            "total": total,
            "duration_ms": duration,
            "error": error,
            "suite": suite,
        }