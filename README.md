# VPS OSINT Agent

OSINT 情报查询系统，基于 **Fact-Intent Graph** 与 **Blackboard Architecture** 的智能推理引擎。

## 项目结构

```
vps/
├── src/osint_agent/           # 主程序包
│   ├── server/                 # FastAPI Web 服务器
│   │   ├── app.py              # 应用入口
│   │   ├── routes.py           # API 路由
│   │   ├── events.py           # 事件系统
│   │   └── static/             # Web UI 静态资源
│   ├── dispatcher/             # 核心调度器 (OODA 循环)
│   │   ├── loop.py             # 调度循环
│   │   ├── config.py           # 配置管理
│   │   ├── llm.py              # LLM 客户端
│   │   ├── prompting.py        # Prompt 模板
│   │   └── prompts/            # Bootstrap/Reason/Explore Prompt
│   ├── graph/                  # Fact-Intent 图存储
│   │   ├── models.py           # 数据模型 (Fact/Intent/Hint/Project)
│   │   ├── store.py            # 项目持久化
│   │   └── export.py           # 导出功能 (JSON/Mermaid/YAML)
│   └── tools/                  # 工具集
│       ├── registry.py         # 工具注册表
│       ├── web_search.py       # Web 搜索
│       └── search_scraper.py   # 搜索结果抓取
├── ip-vps-demo/                # IP/VPS 溯源工具
│   ├── cli.py                  # 溯源命令行入口
│   ├── orchestrator.py         # 编排引擎
│   ├── whois_tool.py           # WHOIS 查询
│   ├── hunter_tool.py          # Hunter 资产测绘
│   └── threatbook_tool.py      # 微步安全情报
├── cli.py                      # vpsctl 统一入口
├── config.yaml                 # 配置文件
└── pyproject.toml              # 项目配置
```

## 核心概念

### Fact-Intent Graph

| 概念 | 说明 |
|------|------|
| **Fact** | 已确认的客观发现，图中的节点 |
| **Intent** | 已声明的探索方向，从 Fact 指向新 Fact 的边 |
| **Hint** | 外部注入的判断，Agent 下次读图时吸收 |

### OODA 循环

```
Observe (读图) → Orient (理解状态) → Decide (选择任务) → Act (执行探索)
```

### 三类任务

| 任务 | 说明 |
|------|------|
| **Bootstrap** | 初始分析，从目标出发生成首批 Intents |
| **Reason** | 进度评估，分析当前图状态，决定下一步 |
| **Explore** | 执行探索，调用工具收集信息，生成新 Facts |

## 安装

```bash
# 安装 osint-agent
pip install -e .

# 安装 ipvps (可选)
cd ip-vps-demo && pip install -e .
```

## 使用方法

### osint-agent

```bash
# 运行交互式推理
osint-agent run "目标描述" --goal "情报目标"

# 指定配置文件
osint-agent run "目标描述" --config config.yaml

# 指定 LLM Provider 和模型
osint-agent run "目标描述" --provider deepseek --model deepseek-chat --api-key sk-xxx

# 交互模式（每轮显示图状态）
osint-agent run "目标描述" --interactive

# 分步模式（每轮暂停等待确认）
osint-agent run "目标描述" --step

# 详细输出
osint-agent run "目标描述" --verbose

# 启动 Web UI
osint-agent run "目标描述" --web --port 8080

# 详细输出并开启web
osint-agent run "目标描述" --goal "找出安全相关人员情报" -i -v --web


# 列出所有项目
osint-agent list-projects

# 查看项目图状态
osint-agent graph <project_id>

# 向项目中注入提示
osint-agent hint "提示内容" --project-id <project_id>

# 继续已中断的项目
osint-agent resume <project_id> --step --verbose

# 导出项目图
osint-agent export <project_id> --format json --output result.json
osint-agent export <project_id> --format yaml
osint-agent export <project_id> --format mermaid

# 查看当前配置
osint-agent show-config
osint-agent show-config --config config.yaml

# 删除项目
osint-agent delete <project_id> --force

# 启动 Web UI（无需运行 agent，查看已有项目）
osint-agent serve --port 8080
```
<img width="1190" height="494" alt="image" src="https://github.com/user-attachments/assets/f772aa6d-4eb8-4824-99ca-e811cdc76da8" />



### ipvps

```bash
# IP 溯源（完整流程）
ipvps trace 120.27.154.229

# 仅显示阶段1（基础信息）
ipvps trace 120.27.154.229 --phase 1

# 仅显示阶段2（云平台）
ipvps trace 120.27.154.229 --phase 2

# JSON 输出
ipvps trace 120.27.154.229 --json

# 不保存报告
ipvps trace 120.27.154.229 --no-save

# 微步认证
ipvps auth login                    # OAuth 扫码登录微步
ipvps auth status                   # 查看所有 API 认证状态

# 报告管理
ipvps report list                   # 列出所有历史报告
ipvps report view <report_id>       # 查看指定报告详情
ipvps report delete <report_id>     # 删除指定报告
```
<img width="1209" height="459" alt="image" src="https://github.com/user-attachments/assets/66984833-b31f-4fcf-8797-fedfcc6aeb82" />

### vpsctl (统一入口)

```bash
# 透传调用 ipvps
vpsctl ipvps trace 120.27.154.229 --json

# 透传调用 osint-agent
vpsctl osint run "目标描述" --goal "情报目标"

# 执行完整管道: IP溯源 → OSINT查询
vpsctl pipeline 120.27.154.229

# 指定情报目标
vpsctl pipeline 120.27.154.229 --goal "找出安全相关人员情报"

# 关闭 Web UI
vpsctl pipeline 120.27.154.229 --no-web

# 指定 Web UI 端口
vpsctl pipeline 120.27.154.229 --port 9000

# osint-agent 详细输出
vpsctl pipeline 120.27.154.229 --verbose

# osint-agent 分步模式
vpsctl pipeline 120.27.154.229 --step
```


<img width="964" height="299" alt="image" src="https://github.com/user-attachments/assets/102cc0fb-6533-4235-b778-91e84e659d51" />



```
python cli.py pipeline 120.27.154.229 --goal "找出安全相关人员情报"
```

<img width="978" height="510" alt="image" src="https://github.com/user-attachments/assets/6fdcb22f-5984-474f-bde2-24a2760dcad2" />

<img width="1885" height="891" alt="image" src="https://github.com/user-attachments/assets/21835d3a-24fb-47c6-8e28-ce4b44969b81" />



## API

### WebSocket 事件

| 事件 | 说明 |
|------|------|
| `loop_start` | OODA 循环开始 |
| `task_decided` | 任务已选定 |
| `task_result` | 任务执行结果 |
| `complete` | 项目完成 |

### REST API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/projects` | GET | 获取所有项目 |
| `/api/projects/{id}` | GET | 获取项目详情 |
| `/api/projects/{id}/events` | WebSocket | 订阅项目事件 |

## 配置

`config.yaml` 示例:

```yaml
llm:
  provider: deepseek
  model: deepseek-chat
  api_key: your-api-key

runtime:
  interval: 3
  max_loops: 50

tasks:
  bootstrap:
    timeout: 300
  reason:
    timeout: 300
  explore:
    timeout: 300

store:
  db_path: ~/.osint-agent/projects.db
```

## 技术栈

- **Web**: FastAPI, WebSocket, 原生 HTML/JS/CSS
- **LLM**: OpenAI, DeepSeek, Ollama
- **数据**: Pydantic, SQLite
- **CLI**: Typer
