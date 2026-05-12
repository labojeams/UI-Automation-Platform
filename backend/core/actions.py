"""
动作执行器：把标准 action 字典翻译为 Playwright 调用。
所有 action 调用统一返回 (ok: bool, message: str)。
"""
import os
import time
from typing import Dict, Any, Tuple, Union

from .locators import ElementLocator
from ..config import SCREENSHOTS_DIR


class PageHolder:
    """共享的"当前页面"持有者。

    用例执行期间页面可能因点击产生新窗口/新标签 (popup)；
    通过 context.on("page") 钩子把新 page 推到这里，ActionExecutor 通过
    holder.active 读取最新页面，做到自动跟随。

    pages: 所有 page 列表（按打开顺序，0 为主页面）
    active_index: 当前活动 page 的索引；动作执行时优先用此 page
    """

    def __init__(self, main_page):
        self.pages = [main_page]
        self.active_index = 0

    @property
    def active(self):
        # 自动跳过已关闭页面
        if not self.pages:
            return None
        # 容错：active_index 越界则回退
        if self.active_index >= len(self.pages):
            self.active_index = len(self.pages) - 1
        page = self.pages[self.active_index]
        if getattr(page, "is_closed", lambda: False)():
            # 当前页已关闭，退到上一个未关闭页
            for i in range(len(self.pages) - 1, -1, -1):
                if not self.pages[i].is_closed():
                    self.active_index = i
                    return self.pages[i]
            return None
        return page

    @property
    def main(self):
        return self.pages[0] if self.pages else None

    def add(self, page):
        """新窗口打开时由钩子调用：加入 list 并切换为活动。"""
        if page in self.pages:
            return
        self.pages.append(page)
        self.active_index = len(self.pages) - 1

    def switch_to_latest(self):
        """切到最近打开的未关闭 page。"""
        for i in range(len(self.pages) - 1, -1, -1):
            if not self.pages[i].is_closed():
                self.active_index = i
                return self.pages[i]
        return None

    def switch_to_main(self):
        """切回主页面。"""
        if self.pages and not self.pages[0].is_closed():
            self.active_index = 0
            return self.pages[0]
        return None

    def close_active(self):
        """关闭当前 page 并自动切回前一个。"""
        if len(self.pages) <= 1:
            return None
        cur = self.active
        if cur and not cur.is_closed():
            try:
                cur.close()
            except Exception:
                pass
        # 移除已关闭项 + 退一格
        self.pages = [p for p in self.pages if not p.is_closed()]
        self.active_index = max(0, len(self.pages) - 1)
        return self.active


class ActionExecutor:
    """对单条 action 执行 Playwright 动作"""

    def __init__(self, page_or_holder: Union[PageHolder, Any], default_timeout: int = 10000):
        # 兼容老调用：传 page 也行（自动包成 PageHolder）
        if isinstance(page_or_holder, PageHolder):
            self.holder = page_or_holder
        else:
            self.holder = PageHolder(page_or_holder)
        self.timeout = default_timeout

    @property
    def page(self):
        """当前活动 page（动态获取，自动跟随新窗口）"""
        return self.holder.active

    @property
    def locator(self) -> ElementLocator:
        """每次调用基于最新 page 构造定位器"""
        return ElementLocator(self.page)

    def execute(self, action: Dict[str, Any]) -> Tuple[bool, str]:
        """执行一个动作，返回 (是否成功, 消息)"""
        if not action or "action" not in action:
            return False, "无效动作（解析失败）"
        name = action["action"]
        method = getattr(self, f"_do_{name}", None)
        if not method:
            return False, f"不支持的动作: {name}"
        try:
            return method(action)
        except Exception as e:
            return False, f"{name} 执行失败: {e}"

    # ===================== 导航类 =====================
    def _do_goto(self, a):
        url = a.get("value")
        if url and not url.startswith(("http://", "https://", "file://", "about:")):
            url = "https://" + url
        self.page.goto(url, timeout=self.timeout)
        return True, f"已打开 {url}"

    def _do_reload(self, a):
        self.page.reload()
        return True, "页面已刷新"

    def _do_back(self, a):
        self.page.go_back()
        return True, "已返回上一页"

    def _do_forward(self, a):
        self.page.go_forward()
        return True, "已前进"

    # ===================== 交互类 =====================
    def _do_click(self, a):
        el = self.locator.smart_find(a["target"])
        try:
            el.click(timeout=self.timeout)
        except Exception as e1:
            # 不可见/被遮挡时，尝试 force 点击；再不行用 JS click
            try:
                el.click(timeout=self.timeout, force=True)
                return True, f"已点击 {a['target']}（force）"
            except Exception:
                try:
                    el.evaluate("el => el.click()")
                    return True, f"已点击 {a['target']}（JS）"
                except Exception:
                    raise e1
        return True, f"已点击 {a['target']}"

    def _do_click_until(self, a):
        """点击 target，等 value 描述的元素出现；若超时则重试点击。

        action 结构::
            {"action":"click_until", "target":"价格明细", "value":"价格明细 标题",
             "extra":{"max_retries":3, "per_wait":5000}}

        约定：
        - target  ：要点击的元素描述
        - value   ：点击后期望出现的元素描述（同 wait_for 的 target 语法）
        - max_retries ：最大重试次数（默认 3）
        - per_wait    ：每次点击后等待目标出现的毫秒数（默认 self.timeout）
        """
        target = a.get("target")
        wait_target = a.get("value")
        if not target or not wait_target:
            return False, "click_until 需要 target 与 value（期望出现的元素）"

        max_retries = int(a.get("max_retries") or a.get("extra", {}).get("max_retries") or 3)
        per_wait = int(a.get("per_wait") or a.get("extra", {}).get("per_wait") or self.timeout)

        last_err = None
        for attempt in range(1, max_retries + 1):
            # 1. 点击
            try:
                el = self.locator.smart_find(target)
                try:
                    el.click(timeout=self.timeout)
                except Exception:
                    try:
                        el.click(timeout=self.timeout, force=True)
                    except Exception:
                        el.evaluate("el => el.click()")
            except Exception as e:
                last_err = f"第{attempt}次点击失败: {e}"
                continue

            # 2. 等待目标出现
            try:
                candidates, _ = self.locator.build_candidates(wait_target)
                per_per = max(800, int(per_wait / max(1, len(candidates))))
                appeared = False
                for c in candidates:
                    try:
                        c.first.wait_for(state="visible", timeout=per_per)
                        appeared = True
                        break
                    except Exception:
                        continue
                if appeared:
                    return True, f"已点击「{target}」，第{attempt}次出现「{wait_target}」"
                last_err = f"第{attempt}次等待「{wait_target}」超时"
            except Exception as e:
                last_err = f"第{attempt}次等待异常: {e}"

        return False, f"click_until 失败：{last_err}（共重试 {max_retries} 次）"

    def _do_dblclick(self, a):
        el = self.locator.smart_find(a["target"])
        try:
            el.dblclick(timeout=self.timeout)
        except Exception:
            el.dblclick(timeout=self.timeout, force=True)
        return True, f"已双击 {a['target']}"

    def _do_hover(self, a):
        el = self.locator.smart_find(a["target"])
        try:
            el.hover(timeout=self.timeout)
        except Exception:
            el.hover(timeout=self.timeout, force=True)
        return True, f"已悬停 {a['target']}"

    def _do_fill(self, a):
        el = self.locator.smart_find(a["target"])
        value = "" if a.get("value") is None else str(a.get("value"))
        # 0) 校正：若命中元素不是 input/textarea/select/contenteditable，
        #    尝试定位它内部 / 紧邻其后的真实输入控件
        try:
            info = el.evaluate(
                "e => ({ tag: (e && e.tagName ? e.tagName.toLowerCase() : ''), "
                "editable: !!(e && e.isContentEditable) })"
            ) or {}
            tag = (info.get("tag") or "").lower()
            editable = bool(info.get("editable"))
        except Exception:
            tag, editable = "", False
        if tag and tag not in ("input", "textarea", "select") and not editable:
            replaced = False
            # 优先在该元素内部找
            try:
                inner = el.locator("input, textarea, select")
                if inner.count() > 0:
                    el = inner.first
                    replaced = True
            except Exception:
                pass
            if not replaced:
                # 再找它后面紧邻的输入控件
                try:
                    after = el.locator(
                        "xpath=following::*[self::input or self::textarea or self::select][1]"
                    )
                    if after.count() > 0:
                        el = after.first
                except Exception:
                    pass
        # 1) 标准 fill（最快，且会触发完整事件链）
        try:
            el.fill(value, timeout=self.timeout)
            return True, f"在 {a['target']} 输入了「{value}」"
        except Exception as e1:
            pass
        # 2) 强制 fill（绕过可见性检查）
        try:
            el.fill(value, timeout=self.timeout, force=True)
            return True, f"在 {a['target']} 输入了「{value}」（force）"
        except Exception:
            pass
        # 3) 键盘逐字符输入（适用于联想/富文本 input，事件最贴近真实用户）
        try:
            try:
                el.click(timeout=self.timeout, force=True)
            except Exception:
                try:
                    el.evaluate("el => el.focus && el.focus()")
                except Exception:
                    pass
            # 先清空已有内容
            try:
                self.page.keyboard.press("Control+A")
                self.page.keyboard.press("Delete")
            except Exception:
                pass
            self.page.keyboard.type(value, delay=20)
            # 校验值是否真的写入；写入失败则继续 JS 兜底
            try:
                actual = el.evaluate("el => el.value")
            except Exception:
                actual = None
            if actual == value:
                return True, f"在 {a['target']} 输入了「{value}」（keyboard）"
        except Exception:
            pass
        # 4) JS 赋值 + 触发 input/change（最终兜底）
        try:
            el.evaluate(
                "(el, v) => { el.focus(); el.value = v; "
                "el.dispatchEvent(new Event('input', {bubbles:true})); "
                "el.dispatchEvent(new Event('change', {bubbles:true})); }",
                value,
            )
            return True, f"在 {a['target']} 输入了「{value}」（JS）"
        except Exception as e:
            return False, f"输入失败: {e}"

    def _do_press(self, a):
        key = str(a.get("value", "")).strip()
        if a.get("target"):
            el = self.locator.smart_find(a["target"])
            try:
                el.press(key, timeout=self.timeout)
            except Exception:
                # 隐藏元素：用键盘全局按键
                self.page.keyboard.press(key)
        else:
            self.page.keyboard.press(key)
        return True, f"已按下按键 {key}"

    def _do_select(self, a):
        el = self.locator.smart_find(a["target"])
        val = a.get("value")
        try:
            el.select_option(label=val, timeout=self.timeout)
        except Exception:
            el.select_option(value=val, timeout=self.timeout)
        return True, f"已在 {a['target']} 选择 {val}"

    def _do_check(self, a):
        el = self.locator.smart_find(a["target"])
        try:
            el.check(timeout=self.timeout)
        except Exception:
            el.check(timeout=self.timeout, force=True)
        return True, f"已勾选 {a['target']}"

    def _do_uncheck(self, a):
        el = self.locator.smart_find(a["target"])
        try:
            el.uncheck(timeout=self.timeout)
        except Exception:
            el.uncheck(timeout=self.timeout, force=True)
        return True, f"已取消勾选 {a['target']}"

    def _do_upload(self, a):
        el = self.locator.smart_find(a["target"])
        el.set_input_files(a["value"])
        return True, f"已上传文件 {a['value']} 到 {a['target']}"

    # ===================== 等待 =====================
    def _do_wait(self, a):
        secs = float(a.get("value") or 1)
        time.sleep(secs)
        return True, f"等待 {secs} 秒"

    def _do_wait_for(self, a):
        """等待元素到达指定状态。

        与其他动作不同，wait_for 的语义本身就是"现在没有，等它出现"，
        因此不能像 click/fill 那样要求 smart_find 在调用时就立刻命中。
        策略：
          1. 用 build_candidates 拿到候选 locator 列表（**不做存在性校验**）
          2. 顺序对每个候选调用 Playwright Locator.wait_for(state, timeout)
          3. 任意一个等到即成功；全部超时才报错
          4. 平均分摊总超时，避免单个候选占满
        """
        state = a.get("value") or "visible"
        target = a["target"]
        candidates, _ = self.locator.build_candidates(target)
        if not candidates:
            raise LookupError(f"未能为「{target}」生成等待候选定位器")

        # 平均分摊（最少 1.5s，最多 self.timeout）
        per = max(1500, int(self.timeout / max(1, len(candidates))))
        last_err = None
        for c in candidates:
            try:
                c.first.wait_for(state=state, timeout=per)
                return True, f"{target} 已 {state}"
            except Exception as e:
                last_err = e
                continue
        raise TimeoutError(
            f"等待「{target}」{state} 超时（已尝试 {len(candidates)} 个候选定位器）。"
            f"最后错误：{last_err}"
        )

    # ===================== 滚动 / 截图 =====================
    def _do_scroll_to(self, a):
        el = self.locator.smart_find(a["target"])
        el.scroll_into_view_if_needed(timeout=self.timeout)
        return True, f"已滚动到 {a['target']}"

    def _do_scroll_page(self, a):
        target = (a.get("value") or "").lower()
        if target in ("底部", "bottom"):
            self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            return True, "已滚动到页面底部"
        self.page.evaluate("window.scrollTo(0, 0)")
        return True, "已滚动到页面顶部"

    def _do_screenshot(self, a):
        name = (a.get("value") or "screenshot").strip()
        safe = "".join(c for c in name if c.isalnum() or c in "-_") or "screenshot"
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(SCREENSHOTS_DIR, f"{safe}_{ts}.png")
        self.page.screenshot(path=path, full_page=True)
        return True, f"截图已保存: {os.path.basename(path)}"

    # ===================== 多窗口控制 =====================
    def _do_switch_window(self, a):
        """切换 page。
        value: "new" / "latest" / "main" / "原" / 数字索引（0 起）
        默认 latest。
        """
        target = (a.get("value") or "latest").strip().lower()
        page = None
        if target in ("main", "原", "原窗口", "first", "0"):
            page = self.holder.switch_to_main()
            label = "主窗口"
        elif target.isdigit():
            idx = int(target)
            if 0 <= idx < len(self.holder.pages):
                self.holder.active_index = idx
                page = self.holder.active
                label = f"#{idx} 窗口"
            else:
                return False, f"窗口索引越界: {idx}（共 {len(self.holder.pages)} 个）"
        else:
            page = self.holder.switch_to_latest()
            label = "最新窗口"
        if not page:
            return False, "无可切换的窗口"
        try:
            page.bring_to_front()
        except Exception:
            pass
        try:
            url = page.url
        except Exception:
            url = "?"
        return True, f"已切换到{label}（{url}）"

    def _do_close_window(self, a):
        """关闭当前 page，并自动切回前一个。"""
        if len(self.holder.pages) <= 1:
            return False, "仅剩主窗口，不允许关闭"
        page = self.holder.close_active()
        if not page:
            return False, "关闭后无可用窗口"
        try:
            url = page.url
        except Exception:
            url = "?"
        return True, f"已关闭当前窗口，回到（{url}）"

    # ===================== 断言 =====================
    def _do_assert_text(self, a):
        el = self.locator.smart_find(a["target"])
        actual = el.inner_text(timeout=self.timeout)
        expected = str(a.get("value", ""))
        if expected in actual:
            return True, f"✓ {a['target']} 包含「{expected}」"
        return False, f"✗ {a['target']} 实际文本「{actual}」不包含「{expected}」"

    def _do_assert_visible(self, a):
        el = self.locator.smart_find(a["target"])
        if el.is_visible(timeout=self.timeout):
            return True, f"✓ {a['target']} 可见"
        return False, f"✗ {a['target']} 不可见"

    def _do_assert_hidden(self, a):
        el = self.locator.smart_find(a["target"])
        if not el.is_visible(timeout=self.timeout):
            return True, f"✓ {a['target']} 已隐藏"
        return False, f"✗ {a['target']} 仍然可见"

    def _do_assert_title(self, a):
        title = self.page.title()
        expected = str(a.get("value", ""))
        if expected in title:
            return True, f"✓ 标题包含「{expected}」（实际: {title}）"
        return False, f"✗ 标题「{title}」不包含「{expected}」"

    def _do_assert_url(self, a):
        url = self.page.url
        expected = str(a.get("value", ""))
        if expected in url:
            return True, f"✓ URL 包含「{expected}」"
        return False, f"✗ URL「{url}」不包含「{expected}」"

    def _do_assert_page_text(self, a):
        expected = str(a.get("value", ""))
        # 优先用 body.innerText；若拿不到再回退到 documentElement
        try:
            body_text = self.page.inner_text("body", timeout=self.timeout)
        except Exception:
            body_text = ""
        if expected not in body_text:
            # 二次兜底：读取整个 HTML 文本内容（对异步渲染更鲁棒）
            try:
                body_text = self.page.evaluate(
                    "() => document.documentElement.innerText || document.body.innerText || ''"
                ) or body_text
            except Exception:
                pass
        if expected in body_text:
            return True, f"✓ 页面包含「{expected}」"
        return False, f"✗ 页面未找到「{expected}」"