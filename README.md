# Qoder Bridge

飞书机器人 ↔ Qoder AI 助手 双向桥接器。

**无需公网 IP**，使用飞书 WebSocket 长连接主动接收消息，和 OpenClaw 原理相同。

## 功能特性

- **流式输出**：实时显示 AI 回复，打字机效果
- **多模态支持**：
  - 图片：自动压缩后发送给 Qoder 识别
  - 语音：降级为文本提示（Qoder 暂不支持音频）
- **多实例管理**：每个飞书 Bot 对应独立的 Qoder 进程
- **控制命令**：`/help`、`/status`、`/restart`、`/forget` 等

## 架构

```
飞书用户
   ↕  消息（文字/图片/语音）
飞书服务器
   ↕  WebSocket（本服务主动连接，无需公网 IP）
Qoder Bridge  ──────────────────────────────────
   ↕  stdin/stdout (ACP协议)      REST API (8080)
Qoder 进程                       管理/健康检查/控制
```

## 快速开始

### 1. 安装

```bash
cd /home/dog/qoder-bridge
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置

编辑 `config.yaml`，填入飞书凭证（App ID / App Secret 来自飞书开放平台，
无需再配置 Webhook URL，也不需要公网 IP）：

```yaml
feishu_bots:
  bot-default:
    app_id: "cli_xxx"
    app_secret: "xxx"
    verification_token: "xxx"  # 飞书开放平台 → 事件与回调 → Verification Token
    qoder_instance: "default-assistant"

qoder_instances:
  default-assistant:
    name: "default-assistant"
    workdir: "/home/dog"
    cmd: "qodercli"
    auto_start: true
```

### 3. 启动

```bash
./venv/bin/python main.py --host 0.0.0.0 --port 8080
```

### 4. 在飞书中使用

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

## 技术细节

### 图片处理

- 自动压缩大于 50KB 的图片
- 缩放到最大 1024px
- 转换为 JPEG 格式，质量自适应

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
├── main.py              # FastAPI 服务入口
├── config.yaml          # 运行时配置
├── requirements.txt     # Python 依赖
└── logs/                # 日志
```

## API 文档

服务启动后访问：http://localhost:8080/docs
