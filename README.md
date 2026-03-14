# Qoder Bridge

飞书机器人 ↔ Qoder AI 助手 双向桥接器。

**无需公网 IP**，使用飞书 WebSocket 长连接主动接收消息，和 OpenClaw 原理相同。

## 功能特性

- **双端接入**：飞书机器人 + Web 前端
- **流式输出**：实时显示 AI 回复，打字机效果
- **多模态支持**：
  - 图片：自动压缩后发送给 Qoder 识别
  - 语音：降级为文本提示（Qoder 暂不支持音频）
- **多实例管理**：每个飞书 Bot 对应独立的 Qoder 进程
- **控制命令**：`/help`、`/status`、`/restart`、`/forget` 等
- **OpenAI 兼容 API**：任何 OpenAI 兼容前端可直接对接

## 架构

```
                    飞书用户
                      ↕
                飞书服务器
                      ↕ WebSocket
┌─────────────────────────────────────────────────────────┐
│                    Qoder Bridge                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐ │
│  │ 飞书适配器   │    │ OpenAI API  │    │ 管理 API    │ │
│  │  (WebSocket)│    │  /v1/*      │    │  /api/*     │ │
│  └──────┬──────┘    └──────┬──────┘    └─────────────┘ │
│         │                  │                            │
│         └──────────────────┼─────────────────────────── │
│                            ↓                            │
│                    ┌───────────────┐                    │
│                    │  Qoder ACP    │                    │
│                    │  (stdin/stdout)│                   │
│                    └───────┬───────┘                    │
│                            ↓                            │
│                      Qoder 进程                         │
└─────────────────────────────────────────────────────────┘
                      ↕
                Web 前端 (NextChat)
                  http://localhost:3000
```

## 快速开始

### 1. 安装后端

```bash
cd /home/dog/qoder-bridge
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
    workdir: "/home/dog"
    cmd: "qodercli"
    auto_start: true
```

### 3. 启动后端

```bash
./venv/bin/python main.py --host 0.0.0.0 --port 8080
```

### 4. 安装并启动前端（可选）

使用 NextChat（推荐）：

```bash
# 克隆前端
git clone https://github.com/ChatGPTNextWeb/NextChat.git ~/frontend/nextchat
cd ~/frontend/nextchat

# 安装依赖
yarn install

# 配置环境变量（指向 Bridge）
cat > .env.local << 'EOF'
OPENAI_API_KEY=sk-qoder-bridge
BASE_URL=http://localhost:8080
HIDE_USER_API_KEY=1
CUSTOM_MODELS=+default-assistant
DEFAULT_MODEL=default-assistant
EOF

# 启动前端
PORT=3000 yarn dev
```

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
| `/health` | 健康检查 |

## 部署方案

### 方案一：仅飞书机器人（无需前端）

适合只需要在飞书中使用 Qoder 的场景。

```bash
# 只需启动 Bridge
./venv/bin/python main.py --host 0.0.0.0 --port 8080
```

### 方案二：仅 Web 前端（无需飞书）

适合只需要浏览器访问的场景，不需要飞书开放平台账号。

```bash
# 1. 启动 Bridge（config.yaml 中不配置 feishu_bots 即可）
./venv/bin/python main.py --host 0.0.0.0 --port 8080

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
# /etc/systemd/system/qoder-bridge.service
[Unit]
Description=Qoder Bridge
After=network.target

[Service]
Type=simple
User=dog
WorkingDirectory=/home/dog/qoder-bridge
ExecStart=/home/dog/qoder-bridge/venv/bin/python main.py --host 0.0.0.0 --port 8080
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

使用 Agent Client Protocol 与 Qoder 通信：
- 图片格式：`{"type": "image", "mimeType": "image/jpeg", "data": "<base64>"}`
- 文字格式：`{"type": "text", "text": "..."}`

## 文件结构

```
qoder-bridge/
├── adapters/
│   ├── base.py          # 平台抽象层、消息类型定义
│   └── feishu.py        # 飞书 WebSocket 适配器
├── bridge_core.py       # 消息路由、命令处理、图片压缩
├── qoder_manager.py     # Qoder ACP 进程管理
├── openai_compat.py     # OpenAI 兼容 API 层
├── main.py              # FastAPI 服务入口
├── config.yaml          # 运行时配置（示例）
├── requirements.txt     # Python 依赖
├── .gitignore           # Git 忽略配置
├── README.md            # 本文档
├── QUICKSTART.md        # 快速开始指南
├── ARCHITECTURE.md      # 架构设计文档
└── logs/                # 日志目录
```

## API 文档

服务启动后访问：http://localhost:8080/docs
