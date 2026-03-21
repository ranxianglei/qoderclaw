# QoderClaw

Qoder AI 助手的多平台桥接器，支持飞书（Lark）机器人和 Web 前端。

**无需公网 IP**，飞书端使用 WebSocket 长连接主动接收消息。

---

## 🤖 AI 安装（推荐）

**让 AI 帮你安装！** 将 [`qoderclaw-install-prompt.md`](qoderclaw-install-prompt.md) 中的提示词复制给任意 AI 助手，它会自动：

✅ 检测 qodercli 是否已安装  
✅ 检查并更新 npm/Node.js（如需）  
✅ 跳过飞书配置（仅 Web 模式）  
✅ 配置安全的 localhost 访问（127.0.0.1）  
✅ 完成所有安装和配置步骤  

**只需将此提示词粘贴给你的 AI 助手：**

```
详见：qoderclaw-install-prompt.md
```

---

## 手动安装

如果你想手动安装，请继续查看下面的步骤。

## 功能特性

- **双端接入**：飞书机器人 + Web 前端（Open WebUI 等 OpenAI 兼容客户端）
- **流式输出**：实时显示 AI 回复，打字机效果
- **多模态支持**：
  - 图片：自动压缩后发送给 Qoder 识别
  - 语音：降级为文本提示（Qoder 暂不支持音频）
- **多实例管理**：支持多个独立 Qoder 进程
- **多会话管理**：飞书端支持创建/切换/管理多个会话（交互式卡片）
- **会话同步**：Web 前端可加载并续用 CLI/飞书中的 Qoder 会话
- **工具调用可视化**：Web 前端实时显示 Bash/文件操作等工具执行状态
- **控制命令**：`/help`、`/status`、`/restart`、`/forget`、`/sessions` 等
- **OpenAI 兼容 API**：任何 OpenAI 兼容前端可直接对接

## 架构

```
             飞书用户                 Web 用户 (Open WebUI)
               ↕                       ↕ HTTP
          飞书服务器                 localhost:3001
               ↕ WebSocket              ↕
┌──────────────────────────────────────────────────────────┐
│                     QoderClaw (:8080)                     │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ 飞书适配器    │  │ OpenAI API   │  │  管理 API    │   │
│  │ (WebSocket)  │  │ /v1/*        │  │  /api/*      │   │
│  └──────┬───────┘  └──────┬───────┘  └──────────────┘   │
│         │                 │                              │
│         └─────────────────┤                              │
│                           ↓                              │
│              ┌────────────────────┐                      │
│              │  会话管理 + ACP    │                      │
│              │  (多会话隔离)      │                      │
│              └────────┬───────────┘                      │
│                       ↓                                  │
│                 Qoder 进程                                │
│              (stdin/stdout ACP)                           │
└──────────────────────────────────────────────────────────┘
```

## 快速开始

### 1. 安装后端

```bash
cd qoderclaw
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置后端

编辑 `config.yaml`，填入飞书凭证（可选，不需要飞书可跳过）：

```yaml
feishu_bots:
  bot-default:
    app_id: "cli_xxx"
    app_secret: "xxx"
    verification_token: "xxx"
    qoder_instance: "default-assistant"

qoder_instances:
  default-assistant:
    name: "default-assistant"
    workdir: "/path/to/your/project"
    cmd: "qodercli"
    auto_start: true
```

### 3. 启动后端

```bash
# 使用 CLI 管理脚本（推荐）
./qoderclaw start      # 启动服务
./qoderclaw stop       # 停止服务
./qoderclaw status     # 查看状态
./qoderclaw restart    # 重启服务

# 或直接运行
./venv/bin/python main.py --host 127.0.0.1 --port 8080
```

### 4. 部署 Open WebUI 前端（可选）

QoderClaw 集成了 [Open WebUI](https://github.com/ranxianglei/open-webui) 作为 Web 前端，提供完整的会话管理和跨平台同步功能。

#### Docker 部署（推荐）

```bash
# 克隆 QoderClaw 集成版（指定分支）
git clone -b main https://github.com/ranxianglei/open-webui.git
cd open-webui

# Docker 运行（--add-host 让容器能访问宿主机上的 QoderClaw）
docker run -d \
  --name open-webui \
  --restart always \
  -p 3001:8080 \
  -e ENABLE_SIGNUP=true \
  -e DEFAULT_USER_ROLE=user \
  -e OPENAI_API_BASE_URL=http://host.docker.internal:8080/v1 \
  -e OPENAI_API_KEY=sk-qoderclaw \
  -e DEFAULT_MODEL=default-assistant \
  -e ENABLE_OLLAMA_API=false \
  -v open-webui-data:/app/backend/data \
  --add-host=host.docker.internal:host-gateway \
  ghcr.io/open-webui/open-webui:main
```

**重要：** Docker 部署时，QoderClaw 必须监听 `0.0.0.0`（不能是 `127.0.0.1`）：

```bash
# 启动 QoderClaw 并设置 API Key（Open WebUI 集成必需）
QODERCLAW_API_KEY=sk-qoderclaw ./venv/bin/python main.py --host 0.0.0.0 --port 8080
```

#### 从源码部署

```bash
# 克隆 QoderClaw 集成版
git clone https://github.com/ranxianglei/open-webui.git
cd open-webui
git checkout main

# 后端
cd backend
pip install -r requirements.txt

# 前端
cd ..
npm install
npm run build

# 启动
./start.sh
```

#### 配置 Open WebUI 连接

1. 浏览器打开 http://localhost:3001
2. 首次访问创建管理员账号
3. 进入 **设置** → **连接**
4. 添加 OpenAI API 连接：
   - **API 地址**：`http://localhost:8080/v1`（或你的 QoderClaw 地址）
   - **API Key**：`sk-qoderclaw`（或通过 `QODERCLAW_API_KEY` 环境变量配置的值）
5. 确认模型列表中出现 `default-assistant`

#### 会话管理功能

- **Qoder 会话列表**：访问 `/static/qoder-sessions.html` 查看所有 QoderClaw 会话及消息数
- **继续会话**：点击"继续会话"按钮将 QoderClaw 会话导入 Open WebUI，保留完整上下文
- **跨平台同步**：飞书/CLI 创建的会话可在 Web 端继续使用

### 5. 在飞书中使用（可选）

直接给机器人发消息即可：

| 消息类型 | 支持情况 |
|----------|----------|
| 文字 | ✅ 完全支持 |
| 图片 | ✅ 自动压缩后识别 |
| 语音 | ⚠️ 降级为文本提示 |
| 文件 | ⚠️ 降级为文本提示 |

控制命令：

| 命令 | 说明 |
|------|------|
| `/help` | 查看帮助 |
| `/status` | 查看 Qoder 状态 |
| `/restart <实例名>` | 重启 Qoder |
| `/forget` | 清除会话记忆 |
| `/list` | 列出所有实例 |
| `/sessions` | 列出所有会话（飞书交互式卡片）|
| `/health` | 健康检查 |

## 部署方案

### 方案一：仅飞书机器人（无需前端）

适合只需要在飞书中使用 Qoder 的场景。

```bash
# 只需启动 QoderClaw
./venv/bin/python main.py --host 127.0.0.1 --port 8080
```

### 方案二：仅 Web 前端（无需飞书）

适合只需要浏览器访问的场景，不需要飞书开放平台账号。

```bash
# 1. 启动 QoderClaw（config.yaml 中不配置 feishu_bots 即可）
./venv/bin/python main.py --host 127.0.0.1 --port 8080

# 2. 启动 Open WebUI（Docker 方式）
docker run -d --name open-webui --restart always \
  -p 3001:8080 \
  -e OPENAI_API_BASE_URL=http://host.docker.internal:8080/v1 \
  -e OPENAI_API_KEY=sk-qoderclaw \
  -e DEFAULT_MODEL=default-assistant \
  -e ENABLE_OLLAMA_API=false \
  -v open-webui-data:/app/backend/data \
  --add-host=host.docker.internal:host-gateway \
  ghcr.io/open-webui/open-webui:main
```

### 方案三：双端同时使用

飞书机器人和 Web 前端同时可用，共享同一个 Qoder 实例。

```yaml
# config.yaml 配置飞书机器人
feishu_bots:
  bot-default:
    app_id: "cli_xxx"
    ...

qoder_instances:
  default-assistant:
    name: "default-assistant"
    ...
```

启动顺序：
1. QoderClaw (`:8080`)
2. Open WebUI (`:3001`)

### 生产部署建议

**使用 systemd 管理 QoderClaw：**

```ini
# /etc/systemd/system/qoderclaw.service
[Unit]
Description=QoderClaw
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/qoderclaw
ExecStart=/path/to/qoderclaw/venv/bin/python main.py --host 127.0.0.1 --port 8080
Restart=always
RestartSec=5
Environment="QODERCLAW_API_KEY=your-secure-api-key"

[Install]
WantedBy=multi-user.target
```

**Open WebUI Docker Compose：**

```yaml
version: '3.8'

services:
  open-webui:
    image: ghcr.io/open-webui/open-webui:main
    container_name: open-webui
    restart: always
    ports:
      - "3001:8080"
    environment:
      - ENABLE_SIGNUP=true
      - DEFAULT_USER_ROLE=user
      - OPENAI_API_BASE_URL=http://host.docker.internal:8080/v1
      - OPENAI_API_KEY=sk-qoderclaw
      - DEFAULT_MODEL=default-assistant
      - ENABLE_OLLAMA_API=false
    volumes:
      - open-webui-data:/app/backend/data
    extra_hosts:
      - "host.docker.internal:host-gateway"

volumes:
  open-webui-data:
```

## 技术细节

### OpenAI 兼容 API

QoderClaw 实现了 OpenAI 兼容的 REST API：

| 端点 | 说明 |
|------|------|
| `GET /v1/models` | 列出可用模型 |
| `POST /v1/chat/completions` | 聊天补全（支持 SSE 流式）|

请求示例：
```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-qoderclaw" \
  -d '{
    "model": "default-assistant",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

### 图片处理

- 自动压缩大于 50KB 的图片
- 缩放到最大 1024px
- 转换为 JPEG 格式，质量自适应
- 支持格式：PNG, JPEG, GIF, WebP

### ACP 协议

使用 Agent Client Protocol (ACP) 与 Qoder 通信：
- 文字格式：`{"type": "text", "text": "..."}`
- 图片格式：`{"type": "image", "mimeType": "image/jpeg", "data": "<base64>"}`
- 工具事件：解析 ACP 的 `tool_call` / `tool_call_update` 通知，通过 SSE 流转发给前端

### 会话管理

- **飞书端**：基于 `open_id`（单聊）/ `chat_id`（群聊）自动隔离会话
- **飞书多会话**：通过交互式卡片（`/sessions`）创建、切换、管理多个独立会话
- **Web 端**：通过 `x-session-id` 头或 `qoder_session` Cookie 路由到对应 Qoder 会话
- **会话同步**：Open WebUI 可加载 CLI/飞书中已有的 Qoder 会话，实现跨端共享上下文
- **会话持久化**：会话数据存储在 `~/.qoder/projects/` 目录

### 工具调用可视化

SSE 流中携带工具事件，前端可实时显示：
- 工具类型（Bash、Read、Write、Edit 等）
- 执行状态（pending / in_progress / completed / error）
- 工具输入参数摘要

## 文件结构

```
qoderclaw/
├── adapters/
│   ├── base.py            # 平台抽象层、消息类型定义
│   └── feishu.py          # 飞书 WebSocket 适配器（含多会话卡片）
├── bridge_core.py         # 消息路由、命令处理、图片压缩
├── qoder_manager.py       # Qoder ACP 进程管理、会话生命周期
├── openai_compat.py       # OpenAI 兼容 API 层（含工具事件 SSE）
├── main.py                # FastAPI 服务入口
├── config.py              # 配置模型定义
├── config.example.yaml    # 配置文件示例
├── requirements.txt       # Python 依赖
├── install.sh             # 安装脚本
├── start.sh               # 启动脚本
└── .gitignore             # Git 忽略规则
```

## API 文档

服务启动后访问：http://localhost:8080/docs

## License

MIT
