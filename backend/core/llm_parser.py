"""
LLM 兜底解析器：当关键词解析失败时，调用 OpenAI 兼容接口将自然语言转换为标准动作。

支持的标准动作类型与 parser.py 保持一致。
"""
import json
import re
import requests
from typing import Optional, Dict, Any, List

from .parser import get_keyword_help

SYSTEM_PROMPT = """你是一名UI自动化测试助手。把用户提供的中文自然语言"测试步骤"翻译成一条标准JSON动作。
只允许使用以下动作名(action)，必须从中选择一个：
goto, click, dblclick, hover, fill, press, select, check, uncheck,
wait, wait_for, assert_text, assert_visible, assert_hidden,
assert_title, assert_url, assert_page_text,
screenshot, reload, back, forward, scroll_to, scroll_page, upload

输出严格 JSON，格式: {"action":"xxx","target":"元素描述或null","value":"值或null"}
- target: 元素的自然语言描述（如 "登录按钮"、"用户名输入框"），或CSS/XPath选择器；没有目标时为 null
- value:  动作需要的值（文本、URL、秒数、断言文案等）；没有时为 null
- 不要输出解释，不要输出 markdown 代码块，仅输出一行 JSON。

参考关键词语法：
""" + get_keyword_help()

OPTIMIZE_PROMPT = """你是一名UI自动化测试用例优化专家。
请将用户提供的"测试步骤"描述优化为符合以下语法格式的标准描述：

【支持的语法格式】
1. 打开/跳转：打开 <url> 或 跳转到 <url>
   例：打开 https://www.baidu.com
   
2. 输入操作：在 <元素> 输入 <文本> 或 输入 <文本> 到 <元素>
   例：在 搜索框 输入 Playwright
   
3. 点击操作：点击 <元素>
   例：点击 登录按钮
   例：点击 百度一下
   
4. 等待操作：等待 <秒数> 秒 或 等待 <元素> 出现 或 等待 <元素> 消失
   例：等待 3 秒
   例：等待 登录成功 出现
   
5. 验证操作：验证 <元素> 包含 <文本> 或 验证 <元素> 可见 或 验证 页面 包含 <文本>
   例：验证 欢迎信息 包含 登录成功
   例：验证 提交按钮 可见
   
6. 其他操作：选择 <选项> 从 <下拉框>、勾选 <元素>、取消勾选 <元素>、
   按下 <按键>、截图、刷新、后退、前进、滚动到 <元素>、滚动到 页面底部

【优化规则】
1. 自动修正格式错误的描述
2. 将复合动作拆分为标准格式
3. 确保使用正确的动词和分隔空格
4. 保留用户描述的核心语义
5. 如果无法理解，返回原描述

请直接输出优化后的描述，只输出一行文本，不要解释，不要加引号。"""


class LLMParser:
    """OpenAI 兼容接口客户端"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}

    def is_enabled(self) -> bool:
        return bool(self.config.get("enabled")) and bool(self.config.get("api_key"))

    def parse(self, sentence: str) -> Optional[Dict[str, Any]]:
        if not self.is_enabled():
            return None
        try:
            content = self._call_llm(SYSTEM_PROMPT, sentence, max_tokens=256)
            parsed = self._extract_json(content)
            if not parsed:
                return None
            return self._normalize(parsed)
        except Exception as e:
            print(f"[LLMParser] 解析调用失败: {e}")
            return None

    def optimize(self, sentence: str) -> Optional[str]:
        """优化测试步骤描述为标准格式"""
        if not self.is_enabled():
            return None
        try:
            content = self._call_llm(OPTIMIZE_PROMPT, sentence, max_tokens=200)
            optimized = content.strip().strip('"').strip("'")
            return optimized if optimized else sentence
        except Exception as e:
            import traceback
            print(f"[LLMParser] 优化调用失败: {e}")
            print(traceback.format_exc())
            return None

    def _call_llm(self, system_prompt: str, user_content: str, max_tokens: int = 256) -> str:
        base_url = self.config.get("base_url", "").rstrip("/")
        if not base_url:
            base_url = "https://api.openai.com/v1"
        url = f"{base_url}/chat/completions"
        
        api_key = self.config.get("api_key", "")
        model = self.config.get("model", "gpt-4o-mini")
        
        print(f"[LLMParser] 调用: {base_url}, 模型: {model}")
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        resp = requests.post(
            url, headers=headers, json=payload,
            timeout=self.config.get("timeout", 30),
        )
        print(f"[LLMParser] 响应状态码: {resp.status_code}")
        if resp.status_code != 200:
            print(f"[LLMParser] 响应内容: {resp.text[:500]}")
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict[str, Any]]:
        # 去除 ``` 包裹
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        # 尝试直接解析
        try:
            return json.loads(text)
        except Exception:
            pass
        # 截取第一个 { ... }
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
        return None

    @staticmethod
    def _normalize(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        action = data.get("action")
        if not action or not isinstance(action, str):
            return None
        result = {
            "action": action.lower().strip(),
            "target": data.get("target") if data.get("target") not in ("", "null", None) else None,
            "value": data.get("value") if data.get("value") not in ("", "null", None) else None,
        }
        return result


def llm_parse(sentence: str, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return LLMParser(config).parse(sentence)