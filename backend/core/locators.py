"""
元素查找封装层 (Locator Layer)
统一封装 Playwright 查找元素的所有方式，对外提供简洁稳定的接口。
所有方法都会返回 Playwright 的 Locator 对象，调用方再调用 click/fill 等动作。
"""
from typing import Optional


class ElementLocator:
    """统一元素查找封装。

    使用方式::

        locator = ElementLocator(page)
        el = locator.smart_find("登录按钮")
        el.click()
    """

    def __init__(self, page):
        self.page = page

    # ========== 基础查找方法 ==========
    def by_text(self, text: str, exact: bool = False):
        """按可见文本查找"""
        return self.page.get_by_text(text, exact=exact)

    def by_role(self, role: str, name: Optional[str] = None):
        """按 ARIA 角色查找：button/link/textbox/checkbox/radio 等"""
        if name:
            return self.page.get_by_role(role, name=name)
        return self.page.get_by_role(role)

    def by_placeholder(self, placeholder: str):
        """按 input 占位符查找"""
        return self.page.get_by_placeholder(placeholder)

    def by_label(self, label: str):
        """按表单 label 查找"""
        return self.page.get_by_label(label)

    def by_title(self, title: str):
        """按 title 属性查找"""
        return self.page.get_by_title(title)

    def by_alt_text(self, alt: str):
        """按图片 alt 属性查找"""
        return self.page.get_by_alt_text(alt)

    def by_test_id(self, test_id: str):
        """按 data-testid 查找"""
        return self.page.get_by_test_id(test_id)

    def by_css(self, selector: str):
        """CSS 选择器"""
        return self.page.locator(selector)

    def by_xpath(self, xpath: str):
        """XPath 选择器"""
        if not xpath.startswith("xpath="):
            xpath = "xpath=" + xpath
        return self.page.locator(xpath)

    # ========== 智能查找 ==========
    def smart_find(self, description: str):
        """智能查找：根据自然语言描述按多策略级联尝试。

        策略顺序：
            1. 显式语法（css= / xpath= / text= / role= / testid= / placeholder= / label=）
            2. 形如 #id / .class / [attr=...] 直接当 CSS
            3. 角色关键词识别（按钮/链接/输入框/复选框/单选框/搜索框）
                - 对"搜索框/输入框/文本框"额外加入通用 CSS 兜底
            4. 按文本模糊匹配
            5. 按 placeholder 匹配
            6. 按 label 匹配
            7. 按 title / alt 匹配
        返回首个 count > 0 的 Locator；若都找不到，返回按文本匹配的 Locator。
        """
        desc = description.strip()
        if not desc:
            raise ValueError("元素描述不能为空")

        # 1. 显式前缀
        prefix_map = {
            "css=": self.by_css,
            "xpath=": self.by_xpath,
            "text=": self.by_text,
            "placeholder=": self.by_placeholder,
            "label=": self.by_label,
            "testid=": self.by_test_id,
            "title=": self.by_title,
            "alt=": self.by_alt_text,
        }
        for prefix, fn in prefix_map.items():
            if desc.lower().startswith(prefix):
                return fn(desc[len(prefix):])
        if desc.lower().startswith("role="):
            body = desc[5:]
            if ":" in body:
                role, name = body.split(":", 1)
                return self.by_role(role.strip(), name.strip())
            return self.by_role(body.strip())

        # 2. CSS / XPath 选择器特征
        if desc.startswith(("//", "(/")):
            return self.by_xpath(desc)
        if desc.startswith(("#", ".", "[")):
            return self.by_css(desc)

        # 3. 角色关键词识别
        # 注意："搜索框" 要单独处理（标准 ARIA role 为 searchbox，同时也常见于 input[type=search]）
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

        # 3.1 角色 + 名称
        if matched_role:
            if clean:
                candidates.append(self.by_role(matched_role, clean))
                # 对 textbox/searchbox 再尝试按 placeholder/label 匹配 clean
                if matched_role in ("textbox", "searchbox"):
                    candidates.append(self.by_placeholder(clean))
                    candidates.append(self.by_label(clean))
            candidates.append(self.by_role(matched_role))

            # 3.2 通用输入类 CSS 兜底（百度搜索框这类未标准 ARIA 的元素）
            if matched_role == "searchbox":
                candidates.append(self.by_css(
                    "input[type=search], input#kw, input[name=wd], "
                    "input[name=q], input[name=query], input[placeholder*=搜索], "
                    "input[aria-label*=搜索]"
                ))
                # 再兜底到通用 text 输入
                candidates.append(self.by_css(
                    "input[type=text]:not([hidden]), input:not([type]):not([hidden])"
                ))
            elif matched_role == "textbox":
                candidates.append(self.by_css(
                    "input[type=text]:not([hidden]), input[type=search], "
                    "input[type=email], input[type=tel], input[type=password], "
                    "input[type=url], input[type=number], input:not([type]):not([hidden]), "
                    "textarea"
                ))
            elif matched_role == "button":
                candidates.append(self.by_css(
                    "button, input[type=button], input[type=submit], [role=button]"
                ))

        # 4-7. 多策略匹配
        target = clean or desc
        candidates.extend([
            self.by_text(target),
            self.by_placeholder(target),
            self.by_label(target),
            self.by_title(target),
            self.by_alt_text(target),
            self.by_test_id(target),
        ])

        for c in candidates:
            try:
                if c.count() > 0:
                    return c.first
            except Exception:
                continue

        # 兜底：返回文本匹配（执行时会抛出明确错误）
        return self.by_text(target)


def get_locator(page) -> ElementLocator:
    """工厂函数"""
    return ElementLocator(page)