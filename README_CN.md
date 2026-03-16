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

- **双端接入**：飞书机器人 + Web 前端（NextChat 等 OpenAI 兼容客户端）
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
             飞书用户                 Web 用户 (NextChat)
               ↕                       ↕ HTTP
          飞书服务器                 localhost:3000
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

### 4. 安装并启动前端（可选）

使用 nextchat-qoder（推荐，已集成 QoderClaw）：

```bash
# 克隆前端
git clone https://github.com/ranxianglei/nextchat-qoder.git ~/frontend/nextchat
cd ~/frontend/nextchat

# 安装依赖
yarn install

# 配置环境变量（指向 Bridge）
cat > .env.local << 'EOF'
OPENAI_API_KEY=sk-qoderclaw
BASE_URL=http://localhost:8080
HIDE_USER_API_KEY=1
CUSTOM_MODELS=+default-assistant
DEFAULT_MODEL=default-assistant
EOF

# 开发模式（支持热重载，首次加载较慢）
PORT=3000 yarn dev

# 或生产模式（更快，推荐部署使用）
yarn build
PORT=3000 yarn start
```

浏览器访问 http://localhost:3000 即可使用。

**提示：** 生产模式启动更快（约 500ms），开发模式首次访问需要编译较慢。开发时用 `yarn dev`，部署时用 `yarn build && yarn start`。

浏览器访问 http://localhost:3000 即可使用。

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
# 只需启动 Bridge
./venv/bin/python main.py --host 127.0.0.1 --port 8080
```

### 方案二：仅 Web 前端（无需飞书）

适合只需要浏览器访问的场景，不需要飞书开放平台账号。

```bash
# 1. 启动 Bridge（config.yaml 中不配置 feishu_bots 即可）
./venv/bin/python main.py --host 127.0.0.1 --port 8080

# 2. 启动 NextChat 前端
cd ~/frontend/nextchat
PORT=3000 yarn dev
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
1. Bridge (`:8080`)
2. NextChat (`:3000`)

### 生产部署建议

**使用 systemd 管理 Bridge：**

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

[Install]
WantedBy=multi-user.target
```

**使用 PM2 管理前端：**

```bash
cd ~/frontend/nextchat
yarn build
pm2 start "PORT=3000 yarn start" --name nextchat
```

## 技术细节

### OpenAI 兼容 API

Bridge 实现了 OpenAI 兼容的 REST API：

| 端点 | 说明 |
|------|------|
| `GET /v1/models` | 列出可用模型 |
| `POST /v1/chat/completions` | 聊天补全（支持 SSE 流式）|

请求示例：
```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
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
- 工具事件：Bridge 解析 ACP 的 `tool_call` / `tool_call_update` 通知，通过 SSE 流转发给前端

### 会话管理

- **飞书端**：基于 `open_id`（单聊）/ `chat_id`（群聊）自动隔离会话
- **飞书多会话**：通过交互式卡片（`/sessions`）创建、切换、管理多个独立会话
- **Web 端**：通过 `qoder_session` Cookie 路由到对应 Qoder 会话
- **会话同步**：Web 前端可加载 CLI 中已有的 Qoder 会话，实现跨端共享上下文
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
