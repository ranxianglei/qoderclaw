# Qoder Bridge

飞书机器人 ↔ Qoder AI 助手 双向桥接器。

**无需公网 IP**，使用飞书 WebSocket 长连接主动接收消息，和 OpenClaw 原理相同。

## 架构

```
飞书用户
   ↕  消息
飞书服务器
   ↕  WebSocket（本服务主动连接，无需公网 IP）
Qoder Bridge  ──────────────────────────────────
   ↕  stdin/stdout               REST API (8080)
Qoder 进程                    管理/健康检查/控制
```

多机器人场景：每个飞书 Bot 对应一个独立的 Qoder 进程，互不干扰。

## 快速开始

### 1. 安装

```bash
cd /home/dog/apps/qoder-bridge
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
    cmd: "qoder"
    auto_start: true
```

### 3. 启动

```bash
./start.sh
```

### 4. 在飞书中使用

直接给机器人发消息即可，支持控制命令：

| 命令 | 说明 |
|------|------|
| `/help` | 查看帮助 |
| `/status` | 查看 Qoder 状态 |
| `/restart <实例名>` | 重启 Qoder |
| `/forget` | 清除会话记忆 |
| `/list` | 列出所有实例 |
| `/health` | 健康检查 |

## 与 OpenClaw 的区别

| | OpenClaw | Qoder Bridge |
|---|---|---|
| 连接方式 | WebSocket 主动连接 | WebSocket 主动连接（相同） |
| 需要公网 IP | ❌ | ❌ |
| 多实例管理 | ❌ | ✅ |
| 进程自动重启 | 基础 | ✅ 完整 |
| REST API | ❌ | ✅ |
| 多平台支持 | 仅飞书 | 可扩展 |

## 文件结构

```
apps/qoder-bridge/       # 运行目录（不要直接编辑）
├── adapters/
│   ├── base.py          # 平台抽象层
│   └── feishu.py        # 飞书 WebSocket 适配器
├── bridge_core.py       # 消息路由 / 命令处理
├── qoder_manager.py     # Qoder 进程管理
├── main.py              # FastAPI 服务入口
├── config.yaml          # 运行时配置
├── venv/                # Python 虚拟环境
└── logs/                # 日志

qoder-bridge/            # 源码目录
└── ...                  # 同上，编辑这里然后同步
```

## API 文档

服务启动后访问：http://localhost:8080/docs
