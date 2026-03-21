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

## Quick Start

### 1. Install

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

## API Docs

After starting the server, visit: http://localhost:8080/docs

## License

MIT
