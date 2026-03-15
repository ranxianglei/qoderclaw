# 飞书机器人多会话对接方案

## 方案概述

本方案实现**单机器人 + 多会话隔离**架构，完全符合飞书官方推荐做法。

### 核心设计

```
┌─────────────────────────────────────────────────────────┐
│                    飞书开放平台                           │
│                  (单个自建应用机器人)                      │
└─────────────────────────┬───────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
     用户A单聊        用户B单聊        群聊C
     open_id=A       open_id=B       chat_id=C
          │               │               │
          └───────────────┴───────────────┘
                          ▼
              ┌─────────────────────┐
              │   Qoder Bridge      │
              │  ┌───────────────┐  │
              │  │ Session管理器  │  │
              │  │  - A的上下文   │  │
              │  │  - B的上下文   │  │
              │  │  - C的上下文   │  │
              │  └───────────────┘  │
              └─────────────────────┘
```

### 会话隔离机制

| 场景 | 会话标识 | 说明 |
|------|----------|------|
| 单聊 | `open_id` | 每个用户的唯一标识 |
| 群聊 | `chat_id` | 每个群组的唯一标识 |

**关键代码**（`adapters/feishu.py`）:

```python
# 生成会话唯一 ID：单聊用 open_id，群聊用 chat_id
chat_type = getattr(msg, 'chat_type', 'p2p')
if chat_type == "group":
    conversation_id = msg.chat_id or ""
    is_group = True
else:
    # 单聊：使用发送者的 open_id 作为会话标识
    conversation_id = sender_open_id
    is_group = False
```

## 飞书平台配置

### 1. 创建飞书应用

1. 访问 [飞书开放平台](https://open.feishu.cn/)
2. 点击"创建企业自建应用"
3. 填写应用名称和描述
4. 进入应用管理后台

### 2. 获取凭证

在"凭证与基础信息"页面获取：

- **App ID**: `cli_xxxxxxxx`
- **App Secret**: 点击显示获取
- **Verification Token**: 在"事件与回调"页面

### 3. 配置权限

在"权限管理"中添加以下权限：

```
im:chat:readonly          # 获取群组信息
im:message:readonly       # 读取消息
im:message:send           # 发送消息
im:message.group_at_msg   # 接收群聊@消息
im:message.p2p_msg        # 接收单聊消息
```

### 4. 配置事件订阅

在"事件与回调"页面：

**请求地址配置**（WebSocket 模式不需要，但保留文档）：
- 如果使用 WebSocket 模式：无需配置
- 如果使用 HTTP 回调模式：配置你的公网地址

**订阅事件**：
```
im.message.receive_v1     # 接收消息事件（核心）
```

### 5. 发布应用

1. 进入"版本管理与发布"
2. 点击"创建版本"
3. 填写版本信息
4. 提交审核（企业内部应用自动通过）

## Bridge 服务配置

### 配置文件 (`config.yaml`)

```yaml
# 系统配置
system:
  host: "0.0.0.0"
  port: 8080
  log_level: "INFO"
  log_file: "logs/qoder_bridge.log"
  health_check_interval: 30
  heartbeat_timeout: 120
  session_timeout: 3600
  max_message_length: 4000

# Qoder 实例配置
qoder_instances:
  default-assistant:
    name: "default-assistant"
    workdir: "/path/to/your/project"
    cmd: "qodercli"
    args: []
    auto_start: true
    max_restarts: 3

# 飞书机器人配置
feishu_bots:
  bot-default:
    app_id: "cli_xxxxxxxx"                    # 你的 App ID
    app_secret: "xxxxxxxx"                   # 你的 App Secret
    verification_token: "xxxxxxxx"           # 你的 Verification Token
    encrypt_key: null                        # 加密密钥（可选）
    qoder_instance: "default-assistant"      # 关联的 Qoder 实例
    enabled: true
```

### 多机器人配置示例

```yaml
# 多个 Qoder 实例
qoder_instances:
  coding-assistant:
    name: "coding-assistant"
    workdir: "/path/to/projects"
    cmd: "qodercli"
    args: ["--mode", "architect"]
    auto_start: true

  writing-assistant:
    name: "writing-assistant"
    workdir: "/path/to/documents"
    cmd: "qodercli"
    args: ["--mode", "writer"]
    auto_start: true

# 多个飞书机器人（复用同一个应用，或不同应用）
feishu_bots:
  bot-coding:
    app_id: "cli_xxx"
    app_secret: "xxx"
    verification_token: "xxx"
    qoder_instance: "coding-assistant"
    enabled: true

  bot-writing:
    app_id: "cli_yyy"  # 可以是同一个应用
    app_secret: "yyy"
    verification_token: "yyy"
    qoder_instance: "writing-assistant"
    enabled: true
```

## 启动服务

### 安装依赖

```bash
cd qoder-bridge
pip install -r requirements.txt
```

### 启动服务

```bash
# 方式1：直接启动
python main.py

# 方式2：使用启动脚本
./start.sh

# 方式3：后台运行
nohup python main.py > logs/bridge.log 2>&1 &
```

### 验证启动

```bash
# 查看日志
tail -f logs/qoder_bridge.log

# 预期输出：
# [INFO] 飞书 WebSocket 连接成功
# [INFO] 机器人信息：YourBot (ou_xxx)
# [INFO] Qoder Bridge 启动完成
```

## 使用说明

### 单聊场景

1. 在飞书搜索你的机器人
2. 点击进入单聊窗口
3. 直接发送消息
4. 每个用户的对话上下文完全隔离

### 群聊场景

1. 将机器人添加到群组
2. @机器人发送消息
3. 群内所有用户共享同一个会话上下文
4. 不同群组之间上下文隔离

### 控制命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/status` | 查看 Qoder 状态 |
| `/forget` | 清除当前会话记忆 |
| `/restart` | 重启 Qoder 实例 |

## 架构优势

### 1. 官方推荐
- 使用飞书标准 `open_id` / `chat_id` 机制
- 符合飞书开放平台最佳实践

### 2. 资源高效
- 单个机器人应用服务多用户
- 无需为每个会话创建独立应用

### 3. 会话隔离
- 单聊：基于 `open_id` 隔离
- 群聊：基于 `chat_id` 隔离
- 不同会话上下文完全独立

### 4. 扩展性
- 支持多个 Qoder 实例
- 支持多个飞书机器人
- 灵活的路由配置

## 故障排查

### 机器人收不到消息

1. 检查事件订阅是否配置正确
2. 确认权限是否已申请并发布
3. 查看日志是否有连接成功信息

### 会话没有隔离

1. 检查日志中的 `会话=` 字段
2. 确认单聊使用 `open_id`，群聊使用 `chat_id`
3. 检查 `is_group` 标志是否正确

### 消息发送失败

1. 检查 `app_secret` 是否正确
2. 确认机器人是否还在群组中
3. 查看飞书开放平台错误日志

## 参考文档

- [飞书开放平台 - 机器人开发](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)
- [飞书开放平台 - 接收消息事件](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/events/receive)
- [飞书开放平台 - 发送消息](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/create)
