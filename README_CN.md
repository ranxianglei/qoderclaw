# QoderClaw

Qoder AI 助手的多平台桥接器。

**核心特性：**
- **Opencode 集成**（推荐）- 无缝的 AI 编程助手体验
- **OpenAI 兼容 API** - 开箱即用，支持所有 OpenAI 兼容客户端

**无需公网 IP** - Opencode 直接通过本地连接，无需网络配置。

---

## 🤖 AI 安装（推荐）

**让 AI 帮你安装！** 将 [`qoderclaw-install-prompt.md`](qoderclaw-install-prompt.md) 中的提示词复制给任意 AI 助手，它会自动：

✅ 检测 qodercli 是否已安装  
✅ 自动检测 Opencode 端口并配置连接  
✅ 配置 QoderClaw 后端与 Opencode 集成  
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

- **Opencode 集成**（推荐）- 原生 AI 编程助手，自动检测工作目录
- **OpenAI 兼容 API** - 支持所有 OpenAI 兼容客户端（Opencode、Open WebUI 等）
- **流式输出**：实时显示 AI 回复，打字机效果
- **多模态支持**：
  - 图片：自动压缩后发送给 Qoder 识别
  - 语音：降级为文本提示（Qoder 暂不支持音频）
- **多实例管理**：支持多个独立 Qoder 进程
- **多会话管理**：创建/切换/管理多个会话
- **工具调用可视化**：实时显示 Bash/文件操作等工具执行状态
- **控制命令**：`/help`、`/status`、`/restart`、`/forget`、`/sessions`、`/cd` 等
- **任务取消**：用户发送新消息时自动取消正在进行的任务
- **长任务支持**：可配置超时时间，最长 360 分钟

## 架构

```
    Opencode 用户          飞书用户              Web 用户 (Open WebUI)
         ↓                    ↓                      ↓ HTTP
    localhost:3000       飞书服务器              localhost:3001
         ↓                    ↓ WebSocket            ↓
         ↓                    ↓                      ↓
┌────────|────────────────────|──────────────────────|──────────┐
│        |              QoderClaw (:8080)                     │
│        |                                                     │
│  ┌─────v─────┐  ┌──────────────┐  ┌──────────────┐  ┌──────┐│
│  │ Opencode  │  │  飞书适配器   │  │ OpenAI API   │  │ 管理 ││
│  │ API 客户端 │  │ (WebSocket)  │  │ /v1/*        │  │ API  ││
│  └─────┬─────┘  └──────┬───────┘  └──────┬───────┘  └──────┘│
│        │               │                 │                   │
│        └───────────────┴─────────────────┘                   │
│                                │                             │
│                       ┌────────v─────────┐                   │
│                       │   会话管理 + ACP  │                   │
│                       │   (多会话隔离)    │                   │
│                       └────────┬─────────┘                   │
│                                ↓                             │
│                          Qoder 进程                           │
│                       (stdin/stdout ACP)                      │
└──────────────────────────────────────────────────────────────┘
```

## 快速开始

### 1. 自动化部署（推荐）

使用自动化部署脚本一键安装：

```bash
# 下载并运行部署脚本
curl -fsSL https://raw.githubusercontent.com/ranxianglei/qoderclaw/main/deploy-auto.sh -o deploy-auto.sh
chmod +x deploy-auto.sh
./deploy-auto.sh
```

该脚本将：
- ✅ 自动检测系统依赖（qodercli、Docker 等）
- ✅ 交互式收集配置（端口、路径、API 密钥）
- ✅ 可选择使用 systemd 管理后端服务
- ✅ 部署后端（QoderClaw）和前端（Open WebUI）
- ✅ 启动服务并验证部署
- ✅ 生成配置文件供后续使用

**交互式部署示例：**
```
$ ./deploy-auto.sh
[INFO] 检测到操作系统: linux (apt)
[INFO] 检测到 systemd 支持
[INFO] 正在检查系统依赖...
[SUCCESS] 所有依赖检查通过
[INFO] 发现现有配置文件: /path/to/deploy-config.json
[INFO] 使用 systemd 管理服务? [y/N]: y
[INFO] 开始部署 QoderClaw 后端...
[SUCCESS] 后端配置完成
[INFO] 安装 systemd 服务...
[SUCCESS] systemd 服务已安装: qoderclaw
[INFO] 启动 QoderClaw 后端...
[SUCCESS] 后端启动成功 (systemd)
[INFO] 开始部署 Open WebUI 前端...
[SUCCESS] 前端启动成功
[SUCCESS] 🎉 部署完成！

=== QoderClaw 部署状态 ===

后端: 运行中 (systemd)
      地址: http://127.0.0.1:8080
前端: 运行中 (端口: 3001)
      地址: http://127.0.0.1:3001
```

**管理命令：**
```bash
# 服务管理
./deploy-auto.sh start    # 启动服务
./deploy-auto.sh stop     # 停止服务
./deploy-auto.sh restart  # 重启服务
./deploy-auto.sh status   # 查看状态

# 使用 systemd（仅后端）
sudo systemctl start qoderclaw    # 启动后端
sudo systemctl stop qoderclaw     # 停止后端
sudo systemctl restart qoderclaw  # 重启后端
sudo systemctl status qoderclaw   # 查看后端状态
sudo journalctl -u qoderclaw -f   # 查看后端日志

# 前端管理（Docker 管理）
docker start open-webui    # 启动前端
docker stop open-webui     # 停止前端
docker restart open-webui  # 重启前端
docker logs open-webui -f  # 查看前端日志
```

### 配置选项

脚本会生成 `deploy-config.json` 配置文件：

```json
{
    "backend_port": 8080,
    "frontend_port": 3001,
    "host": "127.0.0.1",
    "workdir": "/path/to/your/projects",
    "qoderclaw_dir": "/path/to/qoderclaw",
    "api_key": "sk-qoderclaw-abcdef123456",
    "use_systemd": true,
    "created_at": "2026-03-21T10:30:00+00:00"
}
```

**命令行参数覆盖：**
```bash
./deploy-auto.sh --backend-port 8080 --frontend-port 3001 \
                 --workdir /path/to/project --api-key sk-custom-key
```

### 系统要求

- **Linux**: 建议支持 systemd（Ubuntu 16.04+、CentOS 7+）
- **macOS**: 标准进程管理（无 systemd）
- **Docker**: Open WebUI 前端必需
- **Python 3.8+**: QoderClaw 后端必需
- **qodercli**: 需单独安装

### 安全说明

- 后端默认监听 `127.0.0.1`（仅本地）
- 启用 API Key 鉴权
- 配置中不包含外部 API 密钥
- Docker 容器网络隔离（除非特别配置）

### 2. 安装后端

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

### 4. 接入 Opencode（推荐）

QoderClaw 可以无缝接入 [Opencode](https://github.com/sst/opencode) 作为自定义 AI 提供商。这是**推荐**的使用方式。

#### 前置要求

- 安装并运行 Opencode 应用：https://github.com/sst/opencode
- QoderClaw 后端必须已启动（见第 3 步）
- **Opencode Web UI 必须可访问**（默认：http://localhost:3000），以便 QoderClaw 查询会话信息

#### 配置 QoderClaw 以支持 Opencode

设置 Opencode API 地址（如果不使用默认的 localhost:3000）：

```bash
export OPENCODE_API_BASE="http://127.0.0.1:3000"
```

或添加到启动脚本（`start.sh`）：

```bash
# Opencode API 配置（用于获取工作目录）
export OPENCODE_API_BASE="${OPENCODE_API_BASE:-http://127.0.0.1:3000}"
```

#### 配置 Opencode

1. 打开 Opencode 应用
2. 按 Ctrl/Cmd + , 打开设置
3. 进入 **AI** → **添加提供商**
4. 配置 OpenAI 兼容提供商：
   - **名称**：`QoderClaw`
   - **Base URL**：`http://localhost:8080/v1`
   - **API Key**：`sk-qoderclaw`（或你配置的密钥）
   - **模型**：`default-assistant`
5. 开始使用！

#### 已知限制

⚠️ **工作目录问题**：由于 Opencode 的 Session API 设计限制，切换项目时 QoderClaw 可能无法正确识别当前项目的实际路径。

**临时解决方案**：使用 `/cd` 命令手动设置工作目录：
```
/cd /path/to/your/project
```

⚠️ **Bug - 需要重启**：在 Opencode 中切换项目后，需要**重启 Opencode Web UI** 才能使新的工作目录生效。

**操作步骤**：
1. 在 Opencode 中切换项目
2. 完全退出 Opencode（Cmd+Q / Ctrl+Q）
3. 重新打开 Opencode
4. 继续对话

或者使用 `/cd` 命令手动设置目录（无需重启）。

详细技术分析见 [TODO-OPENCODE.md](TODO-OPENCODE.md)。

### 5. 接入 Open WebUI（可选）

如需功能更完善的 Web 界面和会话管理，可以选择部署 Open WebUI。

#### 部署 Open WebUI

```bash
# 克隆 QoderClaw 集成版
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

#### 配置 Open WebUI 连接（可选）

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

### 6. 在飞书中使用（可选）

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

## 故障排除

### 部署问题

#### 1. qoder-sessions.html 显示 "Failed to load sessions"

**问题**：qoder-sessions 页面显示需要认证或加载失败。

**原因**：Open WebUI 需要用户认证。qoder-sessions 是静态文件，需要有效会话。

**解决方案**：
1. 先登录 Open WebUI：`http://localhost:3001`
2. 创建账户或登录
3. 然后访问：`http://localhost:3001/static/qoder-sessions.html`

#### 2. Docker 挂载权限问题

**问题**：挂载目录时文件被删除或权限错误。

**原因**：Docker 容器默认以 root 运行，可能修改主机文件。

**解决方案**：使用自定义 Docker 镜像（`Dockerfile.openwebui`）代替目录挂载。该镜像：
- 在构建时复制集成文件
- 避免绑定挂载权限问题
- 静态文件放在 `/app/build/static/`（而非 `/app/backend/open_webui/static/`）

#### 3. 容器重启后静态文件 404

**问题**：qoder-sessions.html 之前正常，重启后返回 404。

**原因**：Open WebUI 的 `config.py` 启动时会从 `FRONTEND_BUILD_DIR` 删除并重新创建静态文件。

**解决方案**：文件必须复制到 `/app/build/static/`（FRONTEND_BUILD_DIR），而不是直接放到 static 目录。

#### 4. qoder_sessions 路由未注册

**问题**：API 端点返回 404。

**原因**：FastAPI 路由器未正确导入和注册到 `main.py`。

**解决方案**：自定义 Dockerfile 在构建时使用 `sed` 注入导入和注册：
```dockerfile
RUN sed -i 's/from open_webui.routers import (/from open_webui.routers import (\n    qoder_sessions,/' ...
```

### 构建问题

#### Docker 构建失败，提示 "sed: no such file"

**问题**：Docker 构建时 sed 命令失败。

**原因**：官方 Open WebUI 镜像的文件结构可能已更改。

**解决方案**：检查官方 Open WebUI 镜像结构，调整 `Dockerfile.openwebui` 中的 sed 模式。

### API 问题

#### 后端 API 返回 401 Unauthorized

**问题**：API 调用返回认证错误。

**解决方案**：确保 Docker 容器中正确设置了 `OPENAI_API_KEY` 环境变量。该密钥应与 QoderClaw 后端配置的密钥匹配。

## API 文档

服务启动后访问：http://localhost:8080/docs

## License

MIT
