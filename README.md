# QoderClaw

[中文文档](README_CN.md)

Multi-platform bridge for [Qoder](https://qoder.com) AI assistant. Connect Qoder to Lark/Feishu bots, web UIs, or any OpenAI-compatible client.

**No public IP required** - Lark/Feishu uses WebSocket for message delivery.

## Features

- **Dual access** - Lark/Feishu bot + Web frontend (NextChat or any OpenAI-compatible client)
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
          Lark/Feishu User            Web User (NextChat)
               |                          | HTTP
          Lark Server                localhost:3000
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
./venv/bin/python main.py --host 0.0.0.0 --port 8080
```

### 4. Connect a Web Frontend (Optional)

Using [nextchat-qoder](https://github.com/ranxianglei/nextchat-qoder) (NextChat fork with QoderClaw integration):

```bash
git clone https://github.com/ranxianglei/nextchat-qoder.git ~/frontend/nextchat
cd ~/frontend/nextchat
yarn install

cat > .env.local << 'EOF'
OPENAI_API_KEY=sk-qoderclaw
BASE_URL=http://localhost:8080
HIDE_USER_API_KEY=1
CUSTOM_MODELS=+default-assistant
DEFAULT_MODEL=default-assistant
EOF

PORT=3000 yarn dev
```

Open http://localhost:3000 in your browser.

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
./venv/bin/python main.py --host 0.0.0.0 --port 8080
```

### Option B: Web Frontend Only (No Lark)

Skip `feishu_bots` in config, then start the server and frontend.

### Option C: Both

Configure both `feishu_bots` and `qoder_instances`, start the server, then the frontend. Both share the same Qoder instance.

### Production Deployment

**systemd service:**

```ini
# /etc/systemd/system/qoderclaw.service
[Unit]
Description=QoderClaw
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/qoderclaw
ExecStart=/path/to/qoderclaw/venv/bin/python main.py --host 0.0.0.0 --port 8080
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
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
  -d '{
    "model": "default-assistant",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

### ACP Protocol

Communicates with Qoder via Agent Client Protocol (ACP) over stdin/stdout:
- Text: `{"type": "text", "text": "..."}`
- Image: `{"type": "image", "mimeType": "image/jpeg", "data": "<base64>"}`
- Tool events: Parses `tool_call` / `tool_call_update` notifications and forwards them to the frontend via SSE

### Session Management

- **Lark/Feishu**: Auto-isolated by `open_id` (DM) / `chat_id` (group chat)
- **Multi-session**: Create, switch, and manage multiple sessions via interactive cards (`/sessions`)
- **Web**: Routed via `qoder_session` cookie to the corresponding Qoder session
- **Cross-platform sync**: Web frontend can load sessions from CLI, enabling shared context
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
