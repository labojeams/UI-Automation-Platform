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


def _row_xpath(btn_text: str, anchor_text: str) -> str:
    """生成「同时包含 btn_text 和 anchor_text 的最小公共祖先」内的按钮 XPath。

    解决场景：列表/卡片结构下，按钮文字相同，需要用行内其它唯一文字（如公司名）锚定行。
    例：_row_xpath("新增接待", "SHJ成都分公司") ->
        xpath=(//*[.//*[normalize-space(.)="SHJ成都分公司"] and
                   .//*[normalize-space(.)="新增接待"]]
              [not(.//*[.//*[normalize-space(.)="SHJ成都分公司"] and
                        .//*[normalize-space(.)="新增接待"]])])[1]
              //*[normalize-space(.)="新增接待"][self::button or self::a or @role="button"
                                                or ancestor::button or ancestor::a]

    思路：
      1. 找同时含两段文字的所有祖先元素
      2. 用 [not(.//*[同条件])] 过滤「后代仍满足条件」的祖先 → 只剩最小行容器
      3. [1] 双保险
      4. 末尾锁定到真正可点击的 button/a（含 span 文字嵌套场景）
    """
    # XPath 里同时支持单双引号文本。用 concat 规避内部引号冲突
    def _xp_literal(s: str) -> str:
        if '"' not in s:
            return f'"{s}"'
        if "'" not in s:
            return f"'{s}'"
        # 两种引号都有，拆分后用 concat
        parts = s.split('"')
        return "concat(" + ", '\"', ".join(f'"{p}"' for p in parts) + ")"

    a_lit = _xp_literal(anchor_text)
    b_lit = _xp_literal(btn_text)
    cond = f".//*[normalize-space(.)={a_lit}] and .//*[normalize-space(.)={b_lit}]"
    xp = (
        f'(//*[{cond}][not(.//*[{cond}])])[1]'
        f'//*[normalize-space(.)={b_lit}]'
        f'[self::button or self::a or @role="button" or ancestor::button[1] or ancestor::a[1]]'
    )
    return "xpath=" + xp


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

    # ===== 通用「软分隔」片段（容忍空格 / 中英文逗号 / 顿号） =====
    # \s*[,，、]?\s* 表示"可有可无的逗号/顿号"，避免「点击 A，直到 B」类写法落空
    #
    # 行级精定位 + 点击重试：
    #   「点击 新增接待 在 SHJ成都分公司 的 卡片 直到 价格明细 出现 最多 5 次」
    # 当列表里有多条同名按钮时，用「在 X 的 行/卡片」锚定唯一行内文字。
    # 必须放在通用 click_until 之前，才能拦截「点击 A 直到 B」。
    (r"^\s*(?:重试点击|点击重试|click_until|点击)\s+(.+?)\s+(?:在|within|of)\s+(.+?)\s+(?:的)?\s*"
     r"(?:卡片|行|那一行|那一项|区域|card|row)"
     r"\s*[,，、]?\s*(?:直到|until)\s+(.+?)\s*[,，、]?\s*(?:出现|显示|可见|visible|appear)"
     r"(?:\s*[,，、]?\s*(?:最多|max|超时|至多|重试)\s*(\d+)\s*(?:次|times)?)?\s*$",
     lambda m: _action("click_until",
                       target=_row_xpath(m.group(1).strip(), m.group(2).strip()),
                       value=m.group(3).strip(),
                       max_retries=int(m.group(4)) if m.group(4) else 3)),

    # 行级精定位 普通点击：「点击 新增接待 在 SHJ成都分公司 的 卡片」
    # 必须放在通用 click_until / 通用 click 之前
    (r"^\s*(?:点击|点一下|单击|click|tap)\s+(.+?)\s+(?:在|within|of)\s+(.+?)\s+(?:的)?\s*"
     r"(?:卡片|行|那一行|那一项|区域|card|row)\s*$",
     lambda m: _action("click",
                       target=_row_xpath(m.group(1).strip(), m.group(2).strip()))),

    # 点击-重试型：「点击 A 直到 B 出现」/「重试点击 A 直到 B 出现 最多 N 次」
    # 用于异步加载场景：点击触发请求 → 若 loading 超时，自动重试点击直到目标元素可见
    # 中文逗号「，」也作为合法分隔：「点击 A，直到 B 出现」
    (r"^\s*(?:重试点击|点击重试|click_until|点击)\s+(.+?)"
     r"\s*[,，、]?\s*(?:直到|until)\s+(.+?)\s*[,，、]?\s*(?:出现|显示|可见|visible|appear)"
     r"(?:\s*[,，、]?\s*(?:最多|max|超时|至多|重试)\s*(\d+)\s*(?:次|times)?)?\s*$",
     lambda m: _action("click_until",
                       target=m.group(1).rstrip(" ,，、").strip(),
                       value=m.group(2).rstrip(" ,，、").strip(),
                       max_retries=int(m.group(3)) if m.group(3) else 3)),

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

    # 多窗口 / 标签页 控制
    (r"^\s*(?:切换到?|跳到?|switch\s*to)\s*(?:新|最新)\s*(?:窗口|标签页|页面|tab|window)\s*$",
     lambda m: _action("switch_window", value="latest")),
    (r"^\s*(?:切换到?|跳到?|switch\s*to)\s*(?:原|首|主|第一个|main|first)\s*(?:窗口|标签页|页面|tab|window)\s*$",
     lambda m: _action("switch_window", value="main")),
    (r"^\s*(?:切换到?|跳到?|switch\s*to)\s*(?:窗口|标签页|页面|tab|window)\s*(\d+)\s*$",
     lambda m: _action("switch_window", value=m.group(1))),
    (r"^\s*(?:关闭当前(?:窗口|标签页|页面)?|关闭(?:窗口|标签页|页面)|close\s*(?:current\s*)?(?:tab|window|page)?)\s*$",
     lambda m: _action("close_window")),
]


def _normalize(text: str) -> str:
    """
    把人类常用的全角符号 / 装饰引号转为半角空格，便于关键词正则匹配。

    例：`点击"密码登录"按钮` -> `点击 密码登录 按钮`
        `点击"账号"输入框，输入8040094` -> `点击 账号 输入框, 输入8040094`

    【特殊保护】当文本里包含显式定位前缀（css=/xpath=/text=/role=/
    placeholder=/label=/testid=/title=/alt=）时，认为用户在写选择器，
    引号是合法语法（如 xpath=//*[text()="登录"]），仅做全角→半角，
    不再把 ASCII 引号替换成空格，避免破坏选择器语义。
    """
    if not text:
        return text
    # 检测是否含选择器前缀：含 "xx=" 且 xx 在白名单内
    selector_prefixes = ("css=", "xpath=", "text=", "role=",
                         "placeholder=", "label=", "testid=",
                         "title=", "alt=")
    has_selector = any(p in text.lower() for p in selector_prefixes) \
        or text.lstrip().startswith(("//", "(/", "#", ".", "["))

    if has_selector:
        # 仅做装饰性中文引号 → 空格，保留 ASCII " ' `
        quote_chars = "\u201c\u201d\u2018\u2019\u300a\u300b\u300c\u300d\u300e\u300f\u3010\u3011"
    else:
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
            "切换到新窗口  /  切换到原窗口  /  切换到窗口 N  /  关闭当前窗口\n"
            "上传文件 <本地路径> 到 <元素>"
        )


_parser = KeywordParser()


def parse_step(sentence: str) -> Optional[Dict[str, Any]]:
    return _parser.parse(sentence)


def get_keyword_help() -> str:
    return _parser.describe_actions()