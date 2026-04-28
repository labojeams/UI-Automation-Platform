# UI Automation Platform

> 基于 **Playwright + Flask + HTML** 的轻量级 UI 自动化测试平台
> 支持 **自然语言**编写用例，**关键词驱动 + LLM 兜底** 双层解析
> 按**用例集**分组管理，记录每个步骤的**执行步骤 / 预期结果 / 实际结果**

## ✨ 特性

- 🔍 **元素查找全封装**：by_text / by_role / by_placeholder / by_label / by_testid / by_css / by_xpath / **smart_find** 智能查找
- 🗣 **自然语言用例**：`在 搜索框 输入 Playwright` → 自动点击/填入/等待/断言
- 🤖 **关键词优先 + LLM 兜底**：20+ 内置关键词模板离线可用；匹配不上时调用 OpenAI 兼容接口
- 🗂 **用例集分组**：Suite → Case → Step，三层结构清晰可视化
- 📊 **实时执行面板**：运行日志、通过/失败统计、失败自动截图
- 🎨 **星空黑科技主题** 响应式前端

## 🚀 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt
playwright install chromium      # 首次需要下载浏览器

# 2. 启动后端（默认 5050 端口）
cd ui-automation-platform
python -m backend.app

# 3. 打开浏览器访问
#    http://127.0.0.1:5050
```

项目首次启动已内置 2 个示例用例集（百度搜索、表单操作），可直接点击 **▶ 运行整个用例集** 体验。

## 🏗 项目结构

```
ui-automation-platform/
├── backend/
│   ├── app.py                 # Flask 主入口 + REST API
│   ├── config.py              # 平台配置
│   ├── core/
│   │   ├── locators.py        # 元素查找封装（8种策略 + 智能查找）
│   │   ├── parser.py          # 关键词驱动解析器
│   │   ├── llm_parser.py      # LLM 兜底解析（OpenAI 兼容）
│   │   ├── actions.py         # 动作执行器（Playwright 调用）
│   │   ├── executor.py        # 用例集/用例 执行引擎
│   │   └── runner.py          # 后台任务调度与日志缓冲
│   ├── models/storage.py      # JSON 存储层
│   └── data/
│       ├── suites.json        # 用例集数据
│       └── reports/           # 执行报告 + 失败截图
├── frontend/
│   ├── index.html             # 主页面（三栏布局）
│   ├── css/style.css          # 星空黑主题
│   └── js/app.js              # 前端逻辑
├── examples/demo_suite.json   # 示例用例集
└── requirements.txt
```

## 📝 支持的自然语言关键词

| 分类 | 语法 | 示例 |
| --- | --- | --- |
| 导航 | `打开 <url>` / `跳转到 <url>` / `刷新` / `后退` / `前进` | `打开 https://www.baidu.com` |
| 点击 | `点击 <元素>` / `双击 <元素>` / `悬停 <元素>` | `点击 登录按钮` |
| 输入 | `在 <元素> 输入 <文本>` / `输入 <文本> 到 <元素>` | `在 搜索框 输入 Playwright` |
| 选择 | `选择 <选项> 从 <下拉框>` | `选择 北京 从 城市下拉` |
| 勾选 | `勾选 <元素>` / `取消勾选 <元素>` | `勾选 同意协议` |
| 按键 | `按下 <按键>` | `按下 Enter` |
| 等待 | `等待 <秒数> 秒` / `等待 <元素> 出现` | `等待 登录框 出现` |
| 断言 | `验证 <元素> 包含 <文本>` / `验证 <元素> 可见` / `验证 页面 包含 <文本>` / `验证 标题 包含 <文本>` | `验证 错误提示 包含 密码错误` |
| 其他 | `滚动到 <元素>` / `截图 <名称>` / `上传文件 <路径> 到 <元素>` | `截图 登录失败` |

> 💡 LLM 开启后，更灵活的口语化表述（如"点一下那个蓝色的登录按钮"）也能自动识别。

## 🔌 LLM 配置

打开页面右上角 ⚙ **配置** 按钮：

| 项 | 说明 |
| --- | --- |
| 启用LLM兜底 | 勾选后，关键词解析失败才会调用LLM |
| Base URL | OpenAI 兼容接口地址（支持自建模型、第三方中转）|
| API Key | Bearer Token |
| Model | 模型名，如 `gpt-4o-mini` / `qwen-plus` |

## 🔧 元素定位支持的前缀语法

在步骤中描述元素时可直接用前缀精确定位：

| 前缀 | 示例 |
| --- | --- |
| `css=` | `点击 css=button.submit` |
| `xpath=` | `点击 xpath=//button[@id="login"]` |
| `text=` | `点击 text=确认` |
| `placeholder=` | `在 placeholder=请输入手机号 输入 13800001111` |
| `label=` | `在 label=用户名 输入 admin` |
| `testid=` | `点击 testid=login-btn` |
| `role=button:登录` | 按钮角色 + 名称 |

无前缀时 `smart_find` 会自动尝试：角色关键词 → 文本 → placeholder → label → title → alt → test-id。

## 🧪 API 概览

| Method | Path | 说明 |
| --- | --- | --- |
| GET | `/api/suites` | 用例集列表 |
| POST | `/api/suites` | 新建用例集 |
| PUT | `/api/suites/<id>` | 更新用例集 |
| DELETE | `/api/suites/<id>` | 删除用例集 |
| POST | `/api/suites/<id>/run` | 异步执行用例集 |
| POST | `/api/cases/<id>/run` | 异步执行单条用例 |
| GET | `/api/runs/<run_id>` | 查询运行状态+日志 |
| GET/POST | `/api/config` | 读取/保存配置 |
| POST | `/api/parse` | 调试单步自然语言解析 |

## 🐛 失败排查

- **找不到元素**：换用更具体的角色关键词，例如 `登录按钮` 而不是 `登录`；或用 `css=` / `xpath=` 前缀精确定位
- **超时**：在配置中调大 `默认超时(ms)`，或执行前加 `等待 X 秒`
- **无头看不到效果**：配置里取消 `无头模式`，观察浏览器执行过程
- **playwright 未安装**：执行 `playwright install chromium`

## 📄 License

MIT