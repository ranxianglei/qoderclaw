# QoderClaw

[中文文档](README_CN.md)

Multi-platform bridge for [Qoder](https://qoder.com) AI assistant. Connect Qoder to Lark/Feishu bots, web UIs, or any OpenAI-compatible client.

**No public IP required** - Lark/Feishu uses WebSocket for message delivery.

---

## 🤖 AI Installation (Recommended)

**Let AI install it for you!** Copy the prompt from [`qoderclaw-install-prompt.md`](qoderclaw-install-prompt.md) to any AI assistant, and it will:

✅ Auto-check qodercli installation  
✅ Detect and update npm/Node.js if needed  
✅ Skip Feishu/Lark configuration (web-only mode)  
✅ Configure secure localhost-only access (127.0.0.1)  
✅ Set up everything automatically  

**Just paste this prompt to your AI assistant:**

```
See: qoderclaw-install-prompt.md
```

---

## Manual Installation

If you prefer to install manually, follow the steps below.

## Features

- **Dual access** - Lark/Feishu bot + Web frontend (Open WebUI or any OpenAI-compatible client)
- **Streaming output** - Real-time AI responses with typewriter effect
- **Multimodal** - Image recognition (auto-compressed), voice/file graceful degradation
- **Multi-instance** - Run multiple independent Qoder processes
- **Multi-session** - Create, switch, and manage sessions via interactive Lark cards
- **Session sync** - Web frontend can load and continue CLI/Lark sessions
- **Tool call visualization** - Real-time display of Bash, file operations, and other tool executions in the web UI
- **Control commands** - `/help`, `/status`, `/restart`, `/forget`, `/sessions`, etc.
- **OpenAI-compatible API** - Any OpenAI-compatible frontend works out of the box

## Architecture

```
          Lark/Feishu User            Web User (Open WebUI)
               |                          | HTTP
          Lark Server                localhost:3001
               | WebSocket                |
+---------------------------------------------------------+
|                    QoderClaw (:8080)                     |
|                                                         |
|  +-------------+  +-------------+  +--------------+    |
|  | Lark Adapter |  | OpenAI API  |  | Management   |    |
|  | (WebSocket)  |  | /v1/*       |  | API /api/*   |    |
|  +------+-------+  +------+------+  +--------------+    |
|         |                 |                              |
|         +-----------------+                              |
|                  |                                       |
|         +--------v----------+                            |
|         | Session Manager   |                            |
|         | + ACP Protocol    |                            |
|         +--------+----------+                            |
|                  |                                       |
|            Qoder Process                                 |
|          (stdin/stdout ACP)                               |
+---------------------------------------------------------+
```

## Project Structure

```
qoderclaw/
├── main.py                          # QoderClaw Backend (FastAPI)
├── openai_compat.py                 # OpenAI-compatible API
├── qoder_manager.py                 # qodercli process management
├── deploy-auto.sh                   # Automated deployment script
├── Dockerfile.openwebui             # Build custom Open WebUI image
├── openwebui-integration/           # Open WebUI extension
│   ├── qoder_sessions.py            # API routes for /api/v1/qoder/*
│   ├── qoder-sessions.html          # Session list page
│   └── qoder-session.html           # Session detail page
└── ...
```

**Two services are required:**

| Service | Port | Description |
|---------|------|-------------|
| **QoderClaw Backend** | 8080 | Core AI service, manages qodercli processes |
| **Open WebUI Frontend** | 3001 | Web interface (official image + our extension) |

**Building the WebUI image:**
```bash
# Build custom Open WebUI with QoderClaw integration
docker build -f Dockerfile.openwebui -t qoderclaw-webui:latest .

# Run the container
docker run -d \
    --name open-webui \
    -p 3001:8080 \
    -e OPENAI_API_BASE_URL="http://host.docker.internal:8080/v1" \
    -e ENABLE_FORWARD_USER_INFO_HEADERS=true \
    qoderclaw-webui:latest
```

The `openwebui-integration/` directory contains extensions that are **copied into** the official Open WebUI image via `Dockerfile.openwebui`. It cannot run standalone.

## Quick Start

### 1. Automated Deployment (Recommended)

Use the automated deployment script for one-click setup:

```bash
# Download and run the deployment script
curl -fsSL https://raw.githubusercontent.com/ranxianglei/qoderclaw/main/deploy-auto.sh -o deploy-auto.sh
chmod +x deploy-auto.sh
./deploy-auto.sh
```

The script will:
- ✅ Automatically detect system dependencies (qodercli, Docker, etc.)
- ✅ Interactively collect configuration (ports, paths, API keys)
- ✅ Optionally install systemd service for backend management
- ✅ Deploy both backend (QoderClaw) and frontend (Open WebUI)
- ✅ Start services and verify deployment
- ✅ Generate configuration file for future use

**Interactive deployment example:**
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

**Management commands:**
```bash
# Service management
./deploy-auto.sh start    # Start services
./deploy-auto.sh stop     # Stop services
./deploy-auto.sh restart  # Restart services
./deploy-auto.sh status   # Show service status

# With systemd (backend only)
sudo systemctl start qoderclaw    # Start backend
sudo systemctl stop qoderclaw     # Stop backend
sudo systemctl restart qoderclaw  # Restart backend
sudo systemctl status qoderclaw   # Check backend status
sudo journalctl -u qoderclaw -f   # View backend logs

# Frontend (Docker managed)
docker start open-webui    # Start frontend
docker stop open-webui     # Stop frontend
docker restart open-webui  # Restart frontend
docker logs open-webui -f  # View frontend logs
```

### Configuration Options

The script generates `deploy-config.json` for repeatable deployments:

```json
{
    "backend_port": 8080,
    "frontend_port": 3001,
    "host": "127.0.0.1",
    "workdir": "/home/ubuntu/projects",
    "qoderclaw_dir": "/home/ubuntu/mysoft/qoderclaw",
    "api_key": "sk-qoderclaw-abcdef123456",
    "use_systemd": true,
    "created_at": "2026-03-21T10:30:00+00:00"
}
```

**Command-line override:**
```bash
./deploy-auto.sh --backend-port 8080 --frontend-port 3001 \
                 --workdir /path/to/project --api-key sk-custom-key
```

### System Requirements

- **Linux**: systemd support recommended (Ubuntu 16.04+, CentOS 7+)
- **macOS**: Standard process management (no systemd)
- **Docker**: Required for Open WebUI frontend
- **Python 3.8+**: Required for QoderClaw backend
- **qodercli**: Must be installed separately

### Security Notes

- Backend listens on `127.0.0.1` by default (localhost only)
- API Key authentication enabled
- No external API keys required in configuration
- Docker container isolated from host network (unless configured otherwise)

### 1. Manual Installation

```bash
cd qoderclaw
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Or use the install script:

```bash
./install.sh
```

### 2. Configure

Copy and edit the config file:

```bash
cp config.example.yaml config.yaml
```

Minimal configuration (Lark is optional):

```yaml
qoder_instances:
  default-assistant:
    name: "default-assistant"
    workdir: "/path/to/your/project"
    cmd: "qodercli"
    auto_start: true

# Optional: Lark/Feishu bot
feishu_bots:
  bot-default:
    app_id: "cli_xxx"
    app_secret: "xxx"
    verification_token: "xxx"
    qoder_instance: "default-assistant"
    enabled: true
```

### 3. Start the Server

```bash
# Using the CLI management script (recommended)
./qoderclaw start      # Start service
./qoderclaw stop       # Stop service
./qoderclaw status     # Show status
./qoderclaw restart    # Restart service

# Or run directly
./venv/bin/python main.py --host 127.0.0.1 --port 8080
```

### 4. Connect Open WebUI (Optional)

QoderClaw integrates with [Open WebUI](https://github.com/ranxianglei/open-webui) for a full-featured web interface with session management.

#### Deploy Open WebUI with QoderClaw Integration

```bash
# Clone the QoderClaw-integrated fork
git clone -b main https://github.com/ranxianglei/open-webui.git
cd open-webui

# Run with Docker (recommended)
# Note: --add-host allows container to access QoderClaw on host
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

**Important:** For Docker deployment, QoderClaw must listen on `0.0.0.0` (not `127.0.0.1`):

```bash
# Start QoderClaw with API key (required for Open WebUI integration)
QODERCLAW_API_KEY=sk-qoderclaw ./venv/bin/python main.py --host 0.0.0.0 --port 8080
```

Or run from source:

```bash
# Backend setup
cd backend
pip install -r requirements.txt

# Frontend setup (requires Node.js 18+)
cd ..
npm install
npm run build

# Start the server
./start.sh
```

#### Configure Open WebUI Connection

1. Open http://localhost:3001
2. Create an admin account
3. Go to **Settings** → **Connections**
4. Add OpenAI API connection:
   - **API URL**: `http://localhost:8080/v1` (or your QoderClaw host)
   - **API Key**: `sk-qoderclaw` (or any value, QoderClaw validates via `QODERCLAW_API_KEY` env)
5. Verify the model `default-assistant` appears in the model list

#### Session Management Features

With the QoderClaw integration, Open WebUI provides:

- **Qoder Sessions Page**: Access at `/static/qoder-sessions.html`
  - View all QoderClaw sessions with message counts
  - Click "Continue Session" to import any session into Open WebUI

- **Cross-Platform Session Sync**:
  - Sessions created in Lark/Feishu appear in the sessions list
  - Continue CLI sessions in the web UI with full context
  - Messages persist across platforms

- **Session Import Flow**:
  1. Visit `/static/qoder-sessions.html` to see all QoderClaw sessions
  2. Click "Continue Session" on any session
  3. Session is imported into Open WebUI with same ID
  4. Continue chatting - new messages sync to QoderClaw transcript

### 5. Use via Lark/Feishu (Optional)

Send messages directly to your bot:

| Message Type | Support |
|-------------|---------|
| Text | Full support |
| Image | Auto-compressed + recognized |
| Voice | Graceful degradation to text |
| File | Graceful degradation to text |

Control commands:

| Command | Description |
|---------|-------------|
| `/help` | Show help |
| `/status` | View Qoder status |
| `/restart <instance>` | Restart Qoder |
| `/forget` | Clear session memory |
| `/list` | List all instances |
| `/sessions` | List all sessions (interactive card) |
| `/health` | Health check |

## Deployment

### Option A: Lark Bot Only

```bash
./venv/bin/python main.py --host 127.0.0.1 --port 8080
```

### Option B: Open WebUI Only (No Lark)

Skip `feishu_bots` in config, then start the server and Open WebUI.

### Option C: Full Stack (Lark + Open WebUI)

Configure both `feishu_bots` and `qoder_instances`, start QoderClaw, then deploy Open WebUI. All platforms share the same Qoder instances and sessions.

### Production Deployment

**QoderClaw systemd service:**

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

**Open WebUI Docker Compose:**

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

## Technical Details

### OpenAI-Compatible API

| Endpoint | Description |
|----------|-------------|
| `GET /v1/models` | List available models |
| `POST /v1/chat/completions` | Chat completion (supports SSE streaming) |

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

### QoderClaw Management API

| Endpoint | Description |
|----------|-------------|
| `GET /api/sessions` | List all QoderClaw sessions |
| `GET /api/sessions/{id}/transcript` | Get session message transcript |
| `POST /api/sessions/{id}/continue` | Import session for web UI continuation |

### ACP Protocol

Communicates with Qoder via Agent Client Protocol (ACP) over stdin/stdout:
- Text: `{"type": "text", "text": "..."}`
- Image: `{"type": "image", "mimeType": "image/jpeg", "data": "<base64>"}`
- Tool events: Parses `tool_call` / `tool_call_update` notifications and forwards them to the frontend via SSE

### Session Management

- **Lark/Feishu**: Auto-isolated by `open_id` (DM) / `chat_id` (group chat)
- **Multi-session**: Create, switch, and manage multiple sessions via interactive cards (`/sessions`)
- **Web**: Routed via `qoder_session` cookie or `x-session-id` header to the corresponding Qoder session
- **Cross-platform sync**: Open WebUI can load and continue sessions from CLI/Lark via import API
- **Persistence**: Session data stored in `~/.qoder/projects/`

### Tool Call Visualization

SSE stream includes tool events for real-time frontend display:
- Tool type (Bash, Read, Write, Edit, etc.)
- Execution status (pending / in_progress / completed / error)
- Input parameter summaries

## Project Structure

```
qoderclaw/
├── adapters/
│   ├── base.py            # Platform abstraction layer
│   └── feishu.py          # Lark/Feishu WebSocket adapter (multi-session cards)
├── bridge_core.py         # Message routing, command processing, image compression
├── qoder_manager.py       # Qoder ACP process management, session lifecycle
├── openai_compat.py       # OpenAI-compatible API layer (with tool event SSE)
├── main.py                # FastAPI server entry point
├── config.py              # Configuration models
├── config.example.yaml    # Example configuration
├── requirements.txt       # Python dependencies
├── install.sh             # Installation script
├── start.sh               # Start script
└── .gitignore             # Git ignore rules
```

## Troubleshooting

### Deployment Issues

#### 1. qoder-sessions.html returns "Failed to load sessions"

**Problem**: The qoder-sessions page shows "Authentication required" or fails to load.

**Cause**: Open WebUI requires user authentication. The qoder-sessions page is a static file that needs a valid session.

**Solution**:
1. First login to Open WebUI at `http://localhost:3001`
2. Create an account or login
3. Then access `http://localhost:3001/static/qoder-sessions.html`

#### 2. Docker mount permission issues

**Problem**: When mounting directories, files get deleted or permissions are wrong.

**Cause**: Docker containers run as root by default, which can modify host files.

**Solution**: Use the custom Docker image (`Dockerfile.openwebui`) instead of mounting directories. The image:
- Copies integration files at build time
- Avoids bind mount permission issues
- Static files are placed in `/app/build/static/` (not `/app/backend/open_webui/static/`)

#### 3. Static files 404 after container restart

**Problem**: qoder-sessions.html was working but returns 404 after restart.

**Cause**: Open WebUI's `config.py` deletes and recreates static files from `FRONTEND_BUILD_DIR` on startup.

**Solution**: Files must be copied to `/app/build/static/` (FRONTEND_BUILD_DIR), not directly to the static directory.

#### 4. qoder_sessions router not registered

**Problem**: API endpoints return 404.

**Cause**: The FastAPI router wasn't properly imported and registered in `main.py`.

**Solution**: The custom Dockerfile uses `sed` to inject the import and registration during build:
```dockerfile
RUN sed -i 's/from open_webui.routers import (/from open_webui.routers import (\n    qoder_sessions,/' ...
```

### Build Issues

#### Docker build fails with "sed: no such file"

**Problem**: The sed command fails during Docker build.

**Cause**: The base image file structure may have changed.

**Solution**: Check the official Open WebUI image structure and adjust the sed patterns in `Dockerfile.openwebui`.

### API Issues

#### Backend API returns 401 Unauthorized

**Problem**: API calls fail with authentication errors.

**Solution**: Ensure `OPENAI_API_KEY` environment variable is set correctly in the Docker container. The key should match the one configured in QoderClaw backend.

## API Docs

After starting the server, visit: http://localhost:8080/docs

## License

MIT
