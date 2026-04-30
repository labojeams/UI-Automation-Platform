"""平台全局配置"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SUITES_FILE = os.path.join(DATA_DIR, "suites.json")        # 兼容旧 JSON 备份
REPORTS_DIR = os.path.join(DATA_DIR, "reports")
SCREENSHOTS_DIR = os.path.join(REPORTS_DIR, "screenshots")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")        # 兼容旧 JSON 备份
DB_FILE = os.path.join(DATA_DIR, "platform.db")            # SQLite 数据库
DB_URL = f"sqlite:///{DB_FILE.replace(os.sep, '/')}"

# 默认 LLM 配置（OpenAI 兼容）
DEFAULT_LLM_CONFIG = {
    "enabled": False,
    "base_url": "https://api.openai.com/v1",
    "api_key": "",
    "model": "gpt-4o-mini",
    "timeout": 30,
}

# Playwright 默认配置
DEFAULT_BROWSER_CONFIG = {
    "headless": True,
    "browser": "chromium",   # chromium / firefox / webkit
    "viewport": {"width": 1280, "height": 800},
    "default_timeout": 10000,
    "step_interval": 2,      # 每步执行后休眠秒数（0 = 不休眠）
}

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)