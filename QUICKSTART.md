# QoderClaw 快速开始指南

## 🎯 10 分钟快速上手

### 第一步：安装依赖（2 分钟）

```bash
cd qoderclaw

# 运行安装脚本
./install.sh
```

安装脚本会自动：
- ✅ 创建 Python 虚拟环境
- ✅ 安装所有依赖包
- ✅ 创建日志目录
- ✅ 复制配置文件示例

---

### 第二步：配置飞书开放平台（5 分钟）

#### 2.1 创建飞书应用

1. 访问 [飞书开放平台](https://open.feishu.cn/)
2. 点击"控制台" → "企业自建应用" → "创建应用"
3. 填写应用信息：
   - 应用名称：Qoder Assistant
   - 图标：选择一个机器人图标
   - 描述：AI 助手机器人

#### 2.2 获取凭证

在应用详情页获取：
- **App ID** (cli_xxxxxxxxx)
- **App Secret** (xxxxxxxxxx)
- **Verification Token** (用于事件订阅验证)

#### 2.3 配置权限

在"权限管理"页面添加以下权限：
- `im:message` - 发送和接收消息
- `bot:bot_as_user` - 以用户身份发送消息

#### 2.4 配置事件订阅

1. 进入"事件与回调"
2. 订阅事件：`im.message.receive_v1`
3. 配置请求 URL：
   ```
   https://your-domain.com/ws/feishu/bot-research
   ```
   
   > ⚠️ **注意**：需要公网可访问的 URL
   > 
   > 本地测试可使用 ngrok：
   > ```bash
   > ngrok http 8080
   > # 得到：https://xxx.ngrok.io
   > ```

4. 填入 Verification Token

#### 2.5 发布应用

点击"版本管理与发布" → "发布应用"

---

### 第三步：配置 QoderClaw（1 分钟）

编辑 `config.yaml`：

```yaml
# 飞书机器人配置
feishu_bots:
  bot-research:
    app_id: "cli_你的 APP_ID"
    app_secret: "你的 APP_SECRET"
    verification_token: "你的 VERIFICATION_TOKEN"
    qoder_instance: "research-assistant"
    enabled: true

# Qoder 实例配置
qoder_instances:
  research-assistant:
    name: "research-assistant"
    workdir: "/path/to/your-project"
    cmd: "qoder"
    auto_start: true
```

---

### 第四步：启动服务（1 分钟）

```bash
# 启动服务
./start.sh
```

看到以下日志表示成功：

```
======================================
启动 QoderClaw
======================================
INFO:     Starting QoderClaw on 0.0.0.0:8080
INFO:     Application startup complete.
```

---

### 第五步：验证部署（1 分钟）

#### 检查健康状态

```bash
curl http://localhost:8080/health
```

预期响应：

```json
{
  "status": "healthy",
  "qoder_instances": {
    "research-assistant": {
      "status": "running",
      "pid": 12345,
      "cpu_percent": 1.2,
      "memory_mb": 150.5
    }
  },
  "bots": {
    "bot-research": {
      "status": "online",
      "error": null
    }
  }
}
```

#### 查看 API 文档

浏览器访问：http://localhost:8080/docs

---

### 第六步：在飞书中测试（1 分钟）

1. 在飞书中找到你创建的机器人
2. 发送消息：`你好`
3. 机器人应该回复（来自 Qoder）

#### 测试控制命令

发送以下命令测试：

```
/help          # 查看帮助
/status research-assistant  # 查看状态
/list          # 列出实例
/health        # 健康检查
```

---

## 🔧 故障排查

### 问题 1：机器人不回复消息

**检查清单**：
- [ ] 飞书开放平台的事件订阅 URL 是否正确
- [ ] 服务器是否公网可访问
- [ ] Verification Token 是否匹配
- [ ] 查看日志：`tail -f logs/qoderclaw.log`

### 问题 2：Qoder 进程启动失败

**解决方法**：
```bash
# 检查 qoder 命令是否存在
which qoder

# 手动测试启动
cd /path/to/your-project
qoder

# 如果失败，检查 Qoder 安装
pip install -U qoder
```

### 问题 3：WebSocket 连接断开

**查看日志**：
```bash
grep "WebSocket" logs/qoderclaw.log
```

**可能的原因**：
- 网络不稳定
- 飞书服务器问题
- 防火墙阻止连接

---

## 📚 下一步学习

完成快速开始后，你可以：

1. **阅读完整文档**：
   - [README.md](README.md) - 项目总览
   - [ARCHITECTURE.md](ARCHITECTURE.md) - 架构设计

2. **配置多个机器人**：
   ```yaml
   feishu_bots:
     bot-research:
       app_id: "..."
       qoder_instance: "research-assistant"
     
     bot-coding:
       app_id: "..."
       qoder_instance: "coding-assistant"
   ```

3. **自定义控制命令**：
   - 参考 ARCHITECTURE.md 第 7.2 节

4. **集成到其他平台**：
   - 钉钉适配器开发指南
   - Telegram 适配器开发指南

---

## 🆘 获取帮助

- **文档问题**：查看 README.md 或 ARCHITECTURE.md
- **Bug 报告**：提交 Issue
- **功能建议**：提交 Feature Request
- **社区讨论**：加入 Discord/Slack

---

## ✅ 检查清单

完成以下检查确保一切正常：

- [ ] 安装脚本成功运行
- [ ] 飞书应用创建完成
- [ ] 凭证配置正确
- [ ] 事件订阅配置完成
- [ ] 服务启动成功
- [ ] 健康检查通过
- [ ] 飞书机器人能收到消息
- [ ] 控制命令能正常执行

全部完成后，你就可以享受强大的 QoderClaw 了！🎉
