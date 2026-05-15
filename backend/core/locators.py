"""
元素查找封装层 (Locator Layer)
统一封装 Playwright 查找元素的所有方式，对外提供简洁稳定的接口。
所有方法都会返回 Playwright 的 Locator 对象，调用方再调用 click/fill 等动作。

【精确匹配原则】
- 所有按文本/角色/placeholder/label/title/alt 的查找均使用 exact=True
- 不进行模糊（子串）匹配，避免「登录」误中「京东登录」
- 找不到时直接抛 LookupError，绝不静默兜底
- 仍支持显式前缀（css=/xpath=/text=/role=/placeholder=/label=/testid=/title=/alt=）
  以及 # / . / [ / // 开头的 CSS/XPath 选择器，这些被视为用户主动给出的精确语法
"""
import re
from typing import Optional


class ElementLocator:
    """统一元素查找封装（精确匹配版）。

    使用方式::

        locator = ElementLocator(page)
        el = locator.smart_find("登录 按钮")  # 精确匹配 role=button & name=='登录'
        el.click()
    """

    def __init__(self, page):
        self.page = page

    # ========== 基础查找方法 ==========
    def by_text(self, text: str, exact: bool = True):
        """按可见文本查找（默认精确匹配）"""
        return self.page.get_by_text(text, exact=exact)

    def by_role(self, role: str, name: Optional[str] = None, exact: bool = True):
        """按 ARIA 角色查找（默认精确匹配，避免子串误命中）"""
        if name:
            return self.page.get_by_role(role, name=name, exact=exact)
        return self.page.get_by_role(role)

    def by_placeholder(self, placeholder: str, exact: bool = True):
        """按 input 占位符查找（默认精确匹配）"""
        return self.page.get_by_placeholder(placeholder, exact=exact)

    def by_label(self, label: str, exact: bool = True):
        """按表单 label 查找（默认精确匹配）"""
        return self.page.get_by_label(label, exact=exact)

    def by_title(self, title: str, exact: bool = True):
        """按 title 属性查找（默认精确匹配）"""
        return self.page.get_by_title(title, exact=exact)

    def by_alt_text(self, alt: str, exact: bool = True):
        """按图片 alt 属性查找（默认精确匹配）"""
        return self.page.get_by_alt_text(alt, exact=exact)

    def by_test_id(self, test_id: str):
        """按 data-testid 查找（test-id 本身即精确匹配）"""
        return self.page.get_by_test_id(test_id)

    def by_css(self, selector: str):
        """CSS 选择器（用户显式给出，视为精确）"""
        return self.page.locator(selector)

    def by_xpath(self, xpath: str):
        """XPath 选择器（用户显式给出，视为精确）"""
        if not xpath.startswith("xpath="):
            xpath = "xpath=" + xpath
        return self.page.locator(xpath)

    # ========== 候选构造（不做存在校验，wait_for 等场景使用） ==========
    def build_candidates(self, description: str):
        """根据描述生成候选 locator 列表（**不校验是否存在**）。

        与 smart_find 共享同一套候选规则，但允许调用方对每个 locator
        自行调用 Playwright 的 wait_for(state=...)，避免 wait_for
        语义被精确匹配的早期校验破坏。

        返回 (candidates: List[Locator], description: str)
        candidates 至少 1 个；若描述为空则抛 ValueError。
        """
        desc = description.strip()
        if not desc:
            raise ValueError("元素描述不能为空")

        # 1. 显式前缀
        prefix_map = {
            "css=": self.by_css,
            "xpath=": self.by_xpath,
            "text=": lambda v: self.by_text(v, exact=True),
            "placeholder=": lambda v: self.by_placeholder(v, exact=True),
            "label=": lambda v: self.by_label(v, exact=True),
            "testid=": self.by_test_id,
            "title=": lambda v: self.by_title(v, exact=True),
            "alt=": lambda v: self.by_alt_text(v, exact=True),
        }
        for prefix, fn in prefix_map.items():
            if desc.lower().startswith(prefix):
                return [fn(desc[len(prefix):])], desc
        if desc.lower().startswith("role="):
            body = desc[5:]
            if ":" in body:
                role, name = body.split(":", 1)
                return [self.by_role(role.strip(), name.strip(), exact=True)], desc
            return [self.by_role(body.strip())], desc

        # 2. CSS / XPath 选择器特征
        if desc.startswith(("//", "(/")):
            return [self.by_xpath(desc)], desc
        if desc.startswith(("#", ".", "[")):
            return [self.by_css(desc)], desc

        # 3. 角色关键词识别
        role_keywords = [
            ("搜索框", "searchbox"),
            ("搜索栏", "searchbox"),
            ("输入框", "textbox"),
            ("文本框", "textbox"),
            ("文本域", "textbox"),
            ("按钮", "button"),
            ("链接", "link"),
            ("复选框", "checkbox"),
            ("单选框", "radio"),
            ("单选按钮", "radio"),
            ("下拉框", "combobox"),
            ("下拉", "combobox"),
            ("图片", "img"),
            ("图像", "img"),
        ]
        clean = desc
        matched_role = None
        for kw, role in role_keywords:
            if desc.endswith(kw):
                matched_role = role
                clean = desc[:-len(kw)].strip()
                break

        candidates = []

        if matched_role:
            if clean:
                candidates.append(self.by_role(matched_role, clean, exact=True))
                if matched_role == "button":
                    candidates.append(self.by_role("link", clean, exact=True))
                    candidates.append(self.by_role("tab", clean, exact=True))
                    candidates.append(self.by_role("menuitem", clean, exact=True))
                    candidates.append(self.by_text(clean, exact=True))

                if matched_role in ("textbox", "searchbox", "combobox"):
                    candidates.append(self.by_placeholder(clean, exact=True))
                    candidates.append(self.by_label(clean, exact=True))
                    safe = clean.replace('"', '\\"')
                    near_xpath = (
                        f"//*[normalize-space(text())=\"{safe}\"]"
                        f"/following::*[self::input or self::textarea or self::select][1]"
                    )
                    candidates.append(self.by_xpath(near_xpath))
                    container_xpath = (
                        f"//*[normalize-space(text())=\"{safe}\"]"
                        f"/ancestor::*[.//input or .//textarea or .//select][1]"
                        f"//*[self::input or self::textarea or self::select][1]"
                    )
                    candidates.append(self.by_xpath(container_xpath))

                if matched_role in ("button", "link", "tab", "menuitem"):
                    spaced = r"\s*".join(re.escape(ch) for ch in clean)
                    strict_pattern = re.compile(r"^\s*" + spaced + r"\s*$")
                    try:
                        candidates.append(self.page.get_by_text(strict_pattern))
                    except Exception:
                        pass
                    try:
                        candidates.append(self.by_role("button", strict_pattern, exact=False))
                    except Exception:
                        pass
                    try:
                        candidates.append(self.by_role("link", strict_pattern, exact=False))
                    except Exception:
                        pass
            else:
                if matched_role == "searchbox":
                    candidates.append(self.by_css(
                        "input[type=search], input#kw, input[name=wd], "
                        "input[name=q], input[name=query]"
                    ))
                elif matched_role == "textbox":
                    candidates.append(self.by_css(
                        "input[type=text]:not([hidden]), input[type=search], "
                        "input[type=email], input[type=tel], input[type=password], "
                        "input[type=url], input[type=number], "
                        "input:not([type]):not([hidden]), textarea"
                    ))
                elif matched_role == "button":
                    candidates.append(self.by_css(
                        "button, input[type=button], input[type=submit], [role=button]"
                    ))
                else:
                    candidates.append(self.by_role(matched_role))

        # 4. 无角色关键词：精确文本/属性
        target = clean or desc
        if not matched_role:
            candidates.extend([
                self.by_text(target, exact=True),
                self.by_role("button", target, exact=True),
                self.by_role("link", target, exact=True),
                self.by_role("menuitem", target, exact=True),
                self.by_role("tab", target, exact=True),
                self.by_placeholder(target, exact=True),
                self.by_label(target, exact=True),
                self.by_title(target, exact=True),
                self.by_alt_text(target, exact=True),
                self.by_test_id(target),
            ])

        # 5. 兜底（专为 wait_for 等"等出现"场景）：部分文本匹配 + :has-text CSS
        # 现实业务里「工程总造价」往往作为「工程总造价：12345」这种带后缀的文本出现，
        # 精确匹配命不中，此处追加宽松候选，仅在前面所有精确候选都未命中时才会被使用。
        if target:
            try:
                # 部分匹配（exact=False，等价于子串包含）
                candidates.append(self.by_text(target, exact=False))
            except Exception:
                pass
            try:
                # CSS :has-text 兜底，覆盖元素 textContent 含目标文本的所有节点
                safe = target.replace("\\", "\\\\").replace('"', '\\"')
                candidates.append(self.by_css(f':has-text("{safe}")'))
            except Exception:
                pass

        return candidates, desc

    # ========== 智能查找（仅精确匹配） ==========
    def smart_find(self, description: str):
        """智能查找：根据自然语言描述按多策略级联尝试，**全部使用精确匹配**。

        策略顺序由 build_candidates 决定（任一命中即返回，未命中直接抛 LookupError）。
        """
        candidates, desc = self.build_candidates(description)

        # 候选遍历：命中即返回；命中多个时取首个 visible
        for c in candidates:
            try:
                cnt = c.count()
            except Exception:
                continue
            if cnt <= 0:
                continue
            return self._pick_visible(c)

        raise LookupError(
            f"未找到精确匹配的元素：「{description}」。"
            f"请检查名称是否准确，或使用 css=/xpath=/role=/text= 等前缀显式定位。"
        )

    # ========== 内部工具 ==========
    @staticmethod
    def _must_hit(locator, desc: str):
        """显式语法的元素必须命中，否则报错"""
        try:
            cnt = locator.count()
        except Exception:
            cnt = 0
        if cnt <= 0:
            raise LookupError(f"未找到元素：「{desc}」")

    @staticmethod
    def _pick_visible(locator):
        """命中多个时优先返回首个可见元素，全部不可见则返回 first"""
        try:
            cnt = locator.count()
        except Exception:
            return locator.first
        if cnt <= 1:
            return locator.first
        for i in range(min(cnt, 10)):
            item = locator.nth(i)
            try:
                if item.is_visible():
                    return item
            except Exception:
                continue
        return locator.first


def get_locator(page) -> ElementLocator:
    """工厂函数"""
    return ElementLocator(page)