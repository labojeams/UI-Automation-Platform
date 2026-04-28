"""
LLM 兜底解析器：当关键词解析失败时，调用 OpenAI 兼容接口将自然语言转换为标准动作。

支持的标准动作类型与 parser.py 保持一致。
"""
import json
import re
import requests
from typing import Optional, Dict, Any

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
            return self._call(sentence)
        except Exception as e:
            print(f"[LLMParser] 调用失败: {e}")
            return None

    def _call(self, sentence: str) -> Optional[Dict[str, Any]]:
        base_url = self.config.get("base_url", "").rstrip("/")
        url = f"{base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.get('api_key','')}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.config.get("model", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": sentence},
            ],
            "temperature": 0,
            "max_tokens": 256,
        }
        resp = requests.post(
            url, headers=headers, json=payload,
            timeout=self.config.get("timeout", 30),
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        parsed = self._extract_json(content)
        if not parsed:
            return None
        return self._normalize(parsed)

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