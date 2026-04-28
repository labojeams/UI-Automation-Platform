"""
自然语言用例解析器（关键词模板层）
将一行自然语言描述解析为标准动作 Action 字典。
解析失败返回 None，由上层选择是否调用 LLM 兜底。

标准动作格式::

    {"action": "click", "target": "登录按钮", "value": None}

支持的动作类型:
    goto / click / dblclick / fill / press / select / wait / wait_for /
    assert_text / assert_visible / assert_hidden / screenshot /
    reload / back / forward / hover / scroll_to / check / uncheck / upload
"""
import re
from typing import Optional, Dict, Any

# 规则列表：(正则, 处理函数)
# 处理函数接收 re.Match 返回标准 action dict

def _action(action: str, target: str = None, value: Any = None, **extra) -> Dict[str, Any]:
    data = {"action": action, "target": target, "value": value}
    data.update(extra)
    return data


RULES = [
    # 打开网址 / 跳转
    (r"^\s*(?:打开|访问|跳转到?|go\s*to|open)\s+(?:网址\s*)?(.+?)\s*$",
     lambda m: _action("goto", value=m.group(1))),

    # 刷新 / 后退 / 前进
    (r"^\s*(?:刷新|reload|refresh)\s*(?:页面)?\s*$",
     lambda m: _action("reload")),
    (r"^\s*(?:后退|返回上一页|back)\s*$",
     lambda m: _action("back")),
    (r"^\s*(?:前进|forward)\s*$",
     lambda m: _action("forward")),

    # 输入：在 X 输入 Y  /  输入 Y 到 X  /  在 X 中输入 Y
    (r"^\s*(?:在|于)\s*(.+?)\s*(?:中|里)?\s*(?:输入|填写|填入|type|fill)\s+(.+?)\s*$",
     lambda m: _action("fill", target=m.group(1).strip(), value=m.group(2).strip())),
    (r"^\s*(?:输入|填写|填入|type|fill)\s+(.+?)\s+(?:到|into|at)\s+(.+?)\s*$",
     lambda m: _action("fill", target=m.group(2).strip(), value=m.group(1).strip())),

    # 点击 / 双击 / 悬停 / 勾选
    (r"^\s*(?:双击|double\s*click)\s+(.+?)\s*$",
     lambda m: _action("dblclick", target=m.group(1).strip())),
    (r"^\s*(?:点击|点一下|单击|click|tap)\s+(.+?)\s*$",
     lambda m: _action("click", target=m.group(1).strip())),
    (r"^\s*(?:鼠标悬停|悬停|hover)(?:\s*在)?\s+(.+?)\s*$",
     lambda m: _action("hover", target=m.group(1).strip())),
    (r"^\s*(?:勾选|check)\s+(.+?)\s*$",
     lambda m: _action("check", target=m.group(1).strip())),
    (r"^\s*(?:取消勾选|uncheck)\s+(.+?)\s*$",
     lambda m: _action("uncheck", target=m.group(1).strip())),

    # 选择下拉
    (r"^\s*(?:选择|select)\s+(.+?)\s+(?:从|from|在)\s+(.+?)\s*$",
     lambda m: _action("select", target=m.group(2).strip(), value=m.group(1).strip())),
    (r"^\s*(?:在|从)\s+(.+?)\s+(?:选择|选中|select)\s+(.+?)\s*$",
     lambda m: _action("select", target=m.group(1).strip(), value=m.group(2).strip())),

    # 按键
    (r"^\s*(?:按下|按键|press)\s+(.+?)\s*$",
     lambda m: _action("press", value=m.group(1).strip())),

    # 等待数秒 / 等待元素出现 / 等待元素消失
    (r"^\s*(?:等待|sleep|wait)\s+(\d+(?:\.\d+)?)\s*(?:秒|s|seconds?)?\s*$",
     lambda m: _action("wait", value=float(m.group(1)))),
    (r"^\s*(?:等待)\s+(.+?)\s+(?:出现|显示|可见|visible|appear)\s*$",
     lambda m: _action("wait_for", target=m.group(1).strip(), value="visible")),
    (r"^\s*(?:等待)\s+(.+?)\s+(?:消失|隐藏|hidden|disappear)\s*$",
     lambda m: _action("wait_for", target=m.group(1).strip(), value="hidden")),

    # 验证 / 断言
    # 注意：page_text 必须放在 url 之前；url 仅匹配 "URL/地址/链接"
    (r"^\s*(?:验证|断言|assert|期望|expect)\s+(?:页面|当前页|当前页面)\s+(?:包含|contains|有|显示)\s+(.+?)\s*$",
     lambda m: _action("assert_page_text", value=m.group(1).strip())),
    (r"^\s*(?:验证|断言|assert|期望|expect)\s+(?:url|地址|链接|网址)\s+(?:包含|contains)\s+(.+?)\s*$",
     lambda m: _action("assert_url", value=m.group(1).strip())),
    (r"^\s*(?:验证|断言|assert|期望|expect)\s+(?:标题|title)\s+(?:包含|contains|是|等于)\s+(.+?)\s*$",
     lambda m: _action("assert_title", value=m.group(1).strip())),
    (r"^\s*(?:验证|断言|assert|期望|expect)\s+(.+?)\s+(?:包含|contains|显示|有文本)\s+(.+?)\s*$",
     lambda m: _action("assert_text", target=m.group(1).strip(), value=m.group(2).strip())),
    (r"^\s*(?:验证|断言|assert|期望|expect)\s+(.+?)\s+(?:可见|显示|visible)\s*$",
     lambda m: _action("assert_visible", target=m.group(1).strip())),
    (r"^\s*(?:验证|断言|assert|期望|expect)\s+(.+?)\s+(?:不可见|隐藏|不显示|hidden)\s*$",
     lambda m: _action("assert_hidden", target=m.group(1).strip())),

    # 截图
    (r"^\s*(?:截图|screenshot)\s*(.*?)\s*$",
     lambda m: _action("screenshot", value=(m.group(1).strip() or "screenshot"))),

    # 滚动
    (r"^\s*(?:滚动到|scroll\s*to)\s+(?:页面)?(顶部|底部|top|bottom)\s*$",
     lambda m: _action("scroll_page", value=m.group(1).strip())),
    (r"^\s*(?:滚动到|scroll\s*to)\s+(.+?)\s*$",
     lambda m: _action("scroll_to", target=m.group(1).strip())),

    # 上传文件
    (r"^\s*(?:上传文件|upload)\s+(.+?)\s+(?:到|至|to)\s+(.+?)\s*$",
     lambda m: _action("upload", target=m.group(2).strip(), value=m.group(1).strip())),
]


def _normalize(text: str) -> str:
    """
    把人类常用的全角符号 / 装饰引号转为半角空格，便于关键词正则匹配。

    例：`点击"密码登录"按钮` -> `点击 密码登录 按钮`
        `点击"账号"输入框，输入8040094` -> `点击 账号 输入框, 输入8040094`
    """
    if not text:
        return text
    # 引号类装饰符号 → 空格（中文/英文/单引号/书名号/方括号）
    quote_chars = "\u201c\u201d\u2018\u2019\u300a\u300b\u300c\u300d\u300e\u300f\u3010\u3011\"'`"
    out = []
    for ch in text:
        if ch in quote_chars:
            out.append(" ")
        else:
            out.append(ch)
    text = "".join(out)
    # 全角空格 / 全角逗号、冒号、分号、括号 → 半角
    trans = str.maketrans({
        "\u3000": " ",  # 全角空格
        "\uff0c": ",",  # ，
        "\uff1a": ":",  # ：
        "\uff1b": ";",  # ；
        "\uff08": "(", "\uff09": ")",
        "\uff01": "!", "\uff1f": "?",
    })
    text = text.translate(trans)
    # 合并多余空白
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _split_compound(text: str):
    """
    把"点击 X 输入框, 输入 Y"这种复合句切分为两条原子句。
    返回切分结果列表（≥1 条）；若无明显复合特征则返回单元素列表。
    """
    # 仅当句子里出现"逗号 + 动词"模式时才拆分，避免误切元素描述
    # 注意：中文字符不属于 \w，不能用 \b 做边界，改用 lookahead 直接匹配动词
    parts = re.split(r"\s*[,]\s*(?=(?:输入|填写|填入|点击|双击|按下|选择|勾选|取消勾选|验证|断言|截图|等待|滚动到|上传文件))", text)
    return [p for p in parts if p and p.strip()]


class KeywordParser:
    """关键词模板解析器"""

    def parse(self, sentence: str) -> Optional[Dict[str, Any]]:
        """解析单行自然语言，返回标准 action 字典；匹配失败返回 None"""
        if not sentence or not sentence.strip():
            return None
        text = _normalize(sentence)
        # 去除结尾句号
        text = re.sub(r"[。.!！]+$", "", text)

        # 复合句优先：例如"点击 账号 输入框, 输入 8040094"
        # 解析时只关心"输入"那一段，因为"点击 X 输入框"本质是给输入框获得焦点，
        # 真正的语义就是 fill。这里直接选含"输入/填写/填入"的子句。
        sub_parts = _split_compound(text)
        if len(sub_parts) > 1:
            for part in sub_parts:
                if re.search(r"^\s*(?:输入|填写|填入|fill|type)", part, re.IGNORECASE):
                    # 找到形如「输入 8040094」，需把上一段作为目标
                    # 前一段通常是"点击 账号 输入框" → target = "账号 输入框" 去掉点击动词
                    head = sub_parts[0]
                    head_target = re.sub(r"^\s*(?:点击|点一下|单击|click|tap)\s*", "", head, flags=re.IGNORECASE).strip()
                    val = re.sub(r"^\s*(?:输入|填写|填入|fill|type)\s*", "", part, flags=re.IGNORECASE).strip()
                    if head_target and val:
                        return _action("fill", target=head_target, value=val)

        for pattern, handler in RULES:
            m = re.match(pattern, text, flags=re.IGNORECASE)
            if m:
                try:
                    return handler(m)
                except Exception:
                    continue
        return None

    def describe_actions(self) -> str:
        """返回关键词表（供前端/LLM 提示用）"""
        return (
            "打开 <url> / 跳转到 <url>\n"
            "点击 <元素>  /  双击 <元素>  /  悬停 <元素>\n"
            "在 <元素> 输入 <文本>  /  输入 <文本> 到 <元素>\n"
            "选择 <选项> 从 <下拉框>\n"
            "勾选 <元素> / 取消勾选 <元素>\n"
            "按下 <按键>（Enter/Tab/Escape 等）\n"
            "等待 <秒数> 秒  /  等待 <元素> 出现  /  等待 <元素> 消失\n"
            "验证 <元素> 包含 <文本>  /  验证 <元素> 可见  /  验证 页面 包含 <文本>\n"
            "验证 标题 包含 <文本>  /  验证 页面 包含 <url片段>\n"
            "滚动到 <元素>  /  滚动到 页面底部\n"
            "截图 <名称>  /  刷新  /  后退  /  前进\n"
            "上传文件 <本地路径> 到 <元素>"
        )


_parser = KeywordParser()


def parse_step(sentence: str) -> Optional[Dict[str, Any]]:
    return _parser.parse(sentence)


def get_keyword_help() -> str:
    return _parser.describe_actions()