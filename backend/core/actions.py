"""
动作执行器：把标准 action 字典翻译为 Playwright 调用。
所有 action 调用统一返回 (ok: bool, message: str)。
"""
import os
import time
from typing import Dict, Any, Tuple

from .locators import ElementLocator
from ..config import SCREENSHOTS_DIR


class ActionExecutor:
    """对单条 action 执行 Playwright 动作"""

    def __init__(self, page, default_timeout: int = 10000):
        self.page = page
        self.locator = ElementLocator(page)
        self.timeout = default_timeout

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
        state = a.get("value") or "visible"
        el = self.locator.smart_find(a["target"])
        el.wait_for(state=state, timeout=self.timeout)
        return True, f"{a['target']} 已 {state}"

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