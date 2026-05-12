"""临时验证脚本：测试新增关键词规则解析正确性。"""
import json
from backend.core.parser import parse_step

cases = [
    "点击 新增接待 在 SHJ成都分公司 的 卡片",
    "点击 新增接待 在 SHJ成都分公司 的 卡片 直到 接待详情 出现 最多 5 次",
    # 用户实际写法：中文逗号
    '点击 价格明细，直到 css=*:has-text("工程总造价") 出现 最多 5 次',
    '点击 价格明细， 直到 css=*:has-text("工程总造价") 出现',
    "点击 价格明细 直到 工程总造价 出现 最多 3 次",
    "点击 登录按钮",
    # 行级 + 中文逗号
    "点击 新增接待 在 SHJ成都分公司 的 卡片，直到 接待详情 出现 最多 5 次",
]

for s in cases:
    print("---")
    print("input :", s)
    r = parse_step(s)
    print("parsed:", json.dumps(r, ensure_ascii=False, indent=2))