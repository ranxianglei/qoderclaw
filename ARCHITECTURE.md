# Qoder Bridge 架构设计文档

## 1. 系统概述

Qoder Bridge 是一个双向桥接器，用于连接 IM 平台（飞书、钉钉等）与本地 Qoder AI 助手进程。

### 设计目标

1. **平台无关性**：抽象层设计支持多种 IM 平台
2. **多实例隔离**：每个机器人对应独立的 Qoder 进程
3. **高可用性**：自动重启、健康检查、断线重连
4. **易扩展性**：模块化设计，易于添加新平台和新功能

---

## 2. 架构分层

```
┌─────────────────────────────────────────────────────────┐
│                    API Layer                             │
│  FastAPI Web Server + WebSocket Handler                  │
├─────────────────────────────────────────────────────────┤
│               Platform Adapter Layer                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ Feishu   │  │DingTalk  │  │ Telegram │  (Future)    │
│  │ Adapter  │  │ Adapter  │  │ Adapter  │              │
│  └──────────┘  └──────────┘  └──────────┘              │
├─────────────────────────────────────────────────────────┤
│                  Bridge Core                             │
│  - Message Router    - Session Manager                   │
│  - Command Handler   - Context Tracker                   │
├─────────────────────────────────────────────────────────┤
│             Qoder Process Manager                        │
│  - Lifecycle Mgmt    - Health Check                      │
│  - Auto Restart      - Resource Monitor                  │
├─────────────────────────────────────────────────────────┤
│                Qoder Instances                           │
│  [Qoder #1]  [Qoder #2]  [Qoder #3]  ...                │
└─────────────────────────────────────────────────────────┘
```

---

## 3. 核心模块

### 3.1 Platform Adapter Layer (`adapters/`)

**职责**：屏蔽不同 IM 平台的差异，提供统一接口

**关键类**：
- `BaseBotAdapter` - 适配器基类（抽象接口）
- `BasePlatformManager` - 平台管理器基类
- `FeishuBotAdapter` - 飞书适配器实现

**核心方法**：
```python
async def start() -> None           # 启动连接
async def stop() -> None            # 停止连接
async def send_message(msg) -> bool # 发送消息
async def get_health_status()       # 健康检查
```

**参考实现**：OpenClaw的 `@larksuite/openclaw-lark-tools`

---

### 3.2 Bridge Core (`bridge_core.py`)

**职责**：消息路由、会话管理、命令处理

**核心组件**：

#### Message Router
- 根据 bot_id 映射到对应的 Qoder 实例
- 处理消息格式转换
- 消息去重（参考 OpenClaw 的 `MessageDedup`）

#### Session Manager
```python
class Session:
    id: str              # platform:bot_id:conversation_id
    platform: str
    bot_id: str
    conversation_id: str
    user: User
    qoder_instance: str
    message_count: int
    context: Dict        # 会话上下文
```

#### Command Handler
支持的命令：
- `/start <instance>` - 启动实例
- `/stop <instance>` - 停止实例
- `/restart <instance>` - 重启实例
- `/forget` - 清除会话
- `/status <instance>` - 查看状态
- `/list` - 列出实例
- `/health` - 健康检查

---

### 3.3 Qoder Process Manager (`qoder_manager.py`)

**职责**：管理 Qoder 进程的生命周期

**核心功能**：

#### 进程生命周期
```python
async def start_instance(name: str) -> bool
async def stop_instance(name: str) -> bool
async def restart_instance(name: str) -> bool
```

#### 健康检查
- 定期检查进程状态（每 30 秒）
- 监控 CPU、内存使用
- 检测进程崩溃并自动重启

#### 重启策略
- 最大重启次数限制（默认 3 次）
- 重启延迟（默认 5 秒）
- 失败计数追踪

---

### 3.4 Web Service (`main.py`)

**职责**：提供 HTTP API 和 WebSocket 端点

**API 端点**：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/bots` | POST | 创建机器人 |
| `/api/bots` | GET | 列出机器人 |
| `/api/bots/{id}` | DELETE | 删除机器人 |
| `/api/qoder` | POST | 创建 Qoder 实例 |
| `/api/qoder` | GET | 列出 Qoder 实例 |
| `/api/qoder/{name}/start` | POST | 启动实例 |
| `/api/qoder/{name}/stop` | POST | 停止实例 |
| `/api/qoder/{name}/restart` | POST | 重启实例 |
| `/health` | GET | 健康检查 |
| `/ws/feishu/{bot_id}` | WebSocket | 飞书事件推送 |

---

## 4. 数据流

### 4.1 消息接收流程

```
飞书用户发送消息
    ↓
飞书开放平台推送事件
    ↓
WebSocket: /ws/feishu/{bot_id}
    ↓
FeishuBotAdapter.parse_feishu_message()
    ↓
BridgeCore._handle_incoming_message()
    ↓
[检查是否是控制命令]
    ├─→ 是命令 → CommandHandler.execute()
    └─→ 否 → _forward_to_qoder()
              ↓
         写入 Qoder 进程 stdin
```

### 4.2 消息发送流程

```
Qoder 进程输出 stdout
    ↓
ProcessManager._read_process_output()
    ↓
BridgeCore._notify_message()
    ↓
根据 session 找到对应的 bot
    ↓
FeishuBotAdapter.send_message()
    ↓
调用飞书 API 发送消息
    ↓
飞书用户收到回复
```

---

## 5. 会话管理

### 会话 ID 生成规则

```
session_id = "{platform}:{bot_id}:{conversation_id}"
```

示例：
- `feishu:bot-research:oc_123456789`
- `dingtalk:bot-coding:dt_987654321`

### 会话超时策略

- 默认超时：3600 秒（1 小时）
- 每次活动更新 `last_activity` 时间戳
- 定期清理过期会话

### 消息去重

参考 OpenClaw 的 `MessageDedup` 实现：
- FIFO 队列存储消息 ID
- TTL：12 小时
- 容量限制：5000 条记录
- 定期清理过期记录

---

## 6. 容错设计

### 6.1 断线重连

**场景**：WebSocket 连接断开

**处理**：
1. 检测到连接关闭
2. 等待 5 秒后尝试重连
3. 重连失败则指数退避（5s, 10s, 20s, 40s...）
4. 最大重试 10 次后标记为 ERROR 状态

### 6.2 进程崩溃恢复

**场景**：Qoder 进程意外退出

**处理**：
1. 监控进程退出码
2. 非零退出码触发自动重启
3. 检查重启次数是否超限
4. 重启前延迟等待（避免频繁重启）

### 6.3 消息丢失防护

**场景**：服务重启导致消息丢失

**处理**：
1. 飞书事件持久化（TODO：Redis）
2. 会话状态持久化
3. 重启后恢复未完成的会话

---

## 7. 扩展性设计

### 7.1 添加新 IM 平台

步骤：

1. 创建适配器类：
```python
# adapters/dingtalk.py
from adapters.base import BaseBotAdapter

class DingTalkBotAdapter(BaseBotAdapter):
    async def start(self) -> None:
        # 实现钉钉连接逻辑
        pass
    
    async def send_message(self, message: Message) -> bool:
        # 实现钉钉消息发送
        pass
```

2. 创建平台管理器：
```python
class DingTalkPlatformManager(BasePlatformManager):
    async def register_bot(self, config: BotConfig) -> BaseBotAdapter:
        # 注册逻辑
        pass
```

3. 更新配置文件
4. 在 BridgeCore 中注册

### 7.2 添加新控制命令

步骤：

1. 定义命令枚举：
```python
class CommandAction(Enum):
    MY_NEW_COMMAND = "mycmd"
```

2. 实现命令处理：
```python
async def _execute_command(self, command: Command, message: Message):
    if command.action == CommandAction.MY_NEW_COMMAND:
        # 实现命令逻辑
        response = await self._cmd_my_new_command(command, message)
        await self._send_response(message, response)
```

3. 添加到帮助信息：
```python
self.commands_help["mycmd"] = "新命令说明"
```

---

## 8. 性能优化

### 8.1 并发处理

- 使用 asyncio 异步 IO
- 每个 bot 的消息处理独立协程
- 进程监控使用后台任务

### 8.2 资源限制

```yaml
system:
  max_message_length: 4000     # 单条消息最大长度
  session_timeout: 3600        # 会话超时
  health_check_interval: 30    # 健康检查间隔
```

### 8.3 缓存策略

- Access Token 缓存（飞书）
- 用户信息缓存
- 会话状态缓存（TODO: Redis）

---

## 9. 安全考虑

### 9.1 凭证管理

- App Secret 存储在配置文件
- 支持环境变量覆盖
- 不记录敏感信息到日志

### 9.2 签名验证

飞书事件推送需要验证签名：
```python
def verify_signature(timestamp, nonce, signature, body):
    # 使用 verification_token 验证
    pass
```

### 9.3 访问控制

- API 端点需要认证（TODO）
- WebSocket 连接需要验证 bot_id
- 控制命令权限检查（TODO）

---

## 10. 监控与日志

### 10.1 日志级别

```yaml
system:
  log_level: "INFO"  # DEBUG/INFO/WARNING/ERROR
```

### 10.2 关键日志点

- 机器人启动/停止
- 消息收发
- 命令执行
- 进程状态变化
- 健康检查结果

### 10.3 监控指标（TODO）

- Prometheus 指标导出
- Grafana 仪表盘
- 告警规则配置

---

## 11. 部署方案

### 11.1 本地部署

```bash
./install.sh
./start.sh
```

### 11.2 Docker 部署（TODO）

```dockerfile
FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

### 11.3 云服务器部署

- 需要公网 IP 接收飞书事件
- 配置 HTTPS（Nginx 反向代理）
- 使用 systemd 管理进程

---

## 12. 与 OpenClaw 对比

| 特性 | OpenClaw | Qoder Bridge |
|------|----------|--------------|
| 定位 | 单机器人框架 | 多机器人管理平台 |
| 架构 | 单体应用 | 微服务架构 |
| 多实例 | ❌ | ✅ |
| 平台抽象 | ❌ | ✅ |
| 进程管理 | 基础 | 完整（重启/监控） |
| API | CLI | REST + WebSocket |
| 部署 | 本地 | 本地/云端 |

---

## 13. 未来规划

### Phase 2
- [ ] 钉钉平台适配器
- [ ] Redis 会话存储
- [ ] Prometheus 监控
- [ ] Docker 容器化

### Phase 3
- [ ] Telegram 适配器
- [ ] Web 管理界面
- [ ] 插件系统
- [ ] 负载均衡

### Phase 4
- [ ] Kubernetes 部署
- [ ] 分布式消息队列
- [ ] 多租户支持
- [ ] AI 模型热切换

---

## 14. 参考资料

- [飞书开放平台文档](https://open.feishu.cn/document/)
- [OpenClaw 源码](https://github.com/openclaw/openclaw)
- [FastAPI 文档](https://fastapi.tiangolo.com/)
- [Asyncio 最佳实践](https://docs.python.org/3/library/asyncio.html)
