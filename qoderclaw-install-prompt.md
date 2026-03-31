# QoderClaw 安装助手提示词

请将以下提示词提供给 AI 助手来安装 QoderClaw：

---

## 安装任务提示词

```
请帮我安装 QoderClaw（Qoder AI 助手的多平台桥接服务），用于接入 Opencode 或 Open WebUI。

### 安装要求

#### 1. 前置检查
- **检查 qodercli 是否已安装**：
  ```bash
  which qodercli || echo "未安装"
  ```
  - 如果未安装，**停止并提示用户**：
    ```
    ❌ 未检测到 qodercli，请先安装 Qoder CLI：
    
    方式 1: 使用官方安装脚本
    curl -fsSL https://raw.githubusercontent.com/qoder-ai/qoder/main/install.sh | bash
    
    方式 2: 从 GitHub 下载
    https://github.com/qoder-ai/qoder/releases
    
    安装完成后重新运行此脚本。
    ```
  - 如果已安装，记录路径（如 `~/.local/bin/qodercli`）

- **检查 Docker 是否已安装**：
  ```bash
  docker --version || echo "未安装"
  ```
  - 如果未安装，提示用户（Opencode 无需 Docker，只有 Open WebUI 需要）：
    ```
    ⚠️ 未检测到 Docker。
    
    如果你计划使用 Open WebUI 前端，需要安装 Docker：
    参考 https://docs.docker.com/engine/install/
    
    如果只用 Opencode，可以跳过 Docker 安装。
    ```

#### 2. 安装后端（QoderClaw）

```bash
# 克隆仓库到 ~/mysoft
cd ~/mysoft
git clone https://github.com/ranxianglei/qoderclaw.git
cd qoderclaw

# 创建 Python 虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 创建日志目录
mkdir -p logs
```

#### 3. 配置后端（跳过飞书）

创建简化的配置文件 `config.yaml`，**不包含任何飞书机器人配置**：

```yaml
# QoderClaw 配置文件 - 仅 Web 模式

system:
  host: "127.0.0.1"  # 只监听 localhost
  port: 8080
  
  log_level: "INFO"
  log_file: "logs/qoderclaw.log"

# Qoder 实例配置
qoder_instances:
  default-assistant:
    name: "default-assistant"
    workdir: "<USER_PROJECT_PATH>"  # 替换为用户的项目路径
    cmd: "<QODERCLI_PATH>"          # 替换为 qodercli 的实际路径
    args: []
    auto_start: true
    max_restarts: 3

# 飞书机器人配置 - 留空
feishu_bots: {}
```

**重要**：
- `<USER_PROJECT_PATH>` 替换为用户指定的项目路径（如 `~/projects/my-app`）
- `<QODERCLI_PATH>` 替换为检测到的 qodercli 路径（如 `qodercli` 或完整路径）
- **不要配置任何飞书机器人**
- `host` 必须是 `127.0.0.1`（只允许本地访问）

#### 4. 自动检测 Opencode 端口

**AI 助手执行以下步骤自动扫描 Opencode API**：

```bash
# 尝试检测 Opencode 端口（默认 3000，但也可能是其他端口）
OPENCODE_PORT=""

# 检查常见端口
for port in 3000 3001 3002 8080 8081; do
    if curl -s "http://127.0.0.1:$port/session" > /dev/null 2>&1; then
        OPENCODE_PORT="$port"
        echo "✅ 检测到 Opencode 运行在端口: $port"
        break
    fi
done

# 如果自动检测失败，询问用户
if [ -z "$OPENCODE_PORT" ]; then
    echo "⚠️ 无法自动检测 Opencode 端口"
    echo "请确认 Opencode 是否已启动，或手动输入端口"
    # 询问用户输入
    read -p "Opencode 端口号 (默认 3000): " user_port
    OPENCODE_PORT="${user_port:-3000}"
fi

# 验证端口是否可用
if curl -s "http://127.0.0.1:$OPENCODE_PORT/session" > /dev/null 2>&1; then
    export OPENCODE_API_BASE="http://127.0.0.1:$OPENCODE_PORT"
    echo "✅ Opencode API 配置成功: $OPENCODE_API_BASE"
else
    echo "⚠️ 警告: 无法连接到 Opencode API (端口: $OPENCODE_PORT)"
    echo "   QoderClaw 将无法自动获取工作目录"
    echo "   用户需要手动使用 /cd 命令切换目录"
    export OPENCODE_API_BASE="http://127.0.0.1:$OPENCODE_PORT"
fi
```

**如果自动检测失败**：
- 询问用户 Opencode 运行的端口号
- 或者询问用户 Opencode 的完整 API 地址（如 `http://192.168.1.100:3000`）
- 如果用户不确定，使用默认 `http://127.0.0.1:3000` 并显示警告

#### 5. 部署前端（可选 - Open WebUI）

如果你需要 Web 界面（而非使用 Opencode），可以用 Docker 部署 Open WebUI：

```bash
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

等待容器启动（约 10-15 秒），然后验证：

```bash
# 等待启动
sleep 15

# 检查容器状态
docker ps | grep open-webui
```

#### 6. 启动服务

**启动后端**（确保 Opencode 端口已配置）：
```bash
cd ~/mysoft/qoderclaw

# 设置 Opencode API 地址（如果自动检测已设置，可跳过）
export OPENCODE_API_BASE="http://127.0.0.1:3000"

# 启动 QoderClaw
./venv/bin/python main.py --host 127.0.0.1 --port 8080 &
echo $! > /var/tmp/qoderclaw-backend.pid
```
**前端（如已部署 Open WebUI）已通过 Docker 自动启动**，无需额外操作。

#### 7. 验证安装

```bash
# 等待服务启动
sleep 10

# 检查后端健康状态
curl -s http://127.0.0.1:8080/health | jq

# 检查前端是否可访问
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3001

# 测试聊天 API
curl -s -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-qoderclaw" \
  -d '{
    "model": "default-assistant",
    "messages": [{"role": "user", "content": "Hello"}]
  }' | jq
```

### 最终输出

安装完成后，向用户显示：

```
✅ QoderClaw 安装完成！

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  服务信息
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  后端地址：http://127.0.0.1:8080
  API 文档：http://127.0.0.1:8080/docs

  Qoder 工作目录：<USER_PROJECT_PATH>
  qodercli 路径：<QODERCLI_PATH>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  推荐：接入 Opencode（无需 Docker）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  前置要求：
  1. 安装 Opencode 应用：https://github.com/sst/opencode
  2. 确保 Opencode Web UI 运行在 http://localhost:3000
     （QoderClaw 需要通过此端口查询会话信息）

  配置步骤：
  1. 打开 Opencode 应用
  2. 按 Ctrl/Cmd + , 打开设置
  3. 进入 AI → 添加提供商
  4. 配置参数：
     - 名称：QoderClaw
     - Base URL：http://localhost:8080/v1
     - API Key：sk-qoderclaw
     - 模型：default-assistant
  5. 开始使用！

  💡 提示：如果切换项目后工作目录不对，使用 /cd 命令：
     /cd <USER_PROJECT_PATH>

  ⚠️ 已知 Bug（待修复）：
     切换工作目录后，需要重启 Opencode Web UI 才能生效。
     操作步骤：
     1. 在 Opencode 中切换项目
     2. 完全退出 Opencode（Cmd+Q / Ctrl+Q）
     3. 重新打开 Opencode
     4. 继续对话

     或者使用 /cd 命令手动设置目录（无需重启）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  可选：部署 Open WebUI（需要 Docker）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  如需 Web 界面，运行以下命令：

  docker run -d \\
    --name open-webui \\
    --restart always \\
    -p 3001:8080 \\
    -e OPENAI_API_BASE_URL=http://host.docker.internal:8080/v1 \\
    -e OPENAI_API_KEY=sk-qoderclaw \\
    -e DEFAULT_MODEL=default-assistant \\
    -v open-webui-data:/app/backend/data \\
    --add-host=host.docker.internal:host-gateway \\
    ghcr.io/open-webui/open-webui:main

  然后访问：http://127.0.0.1:3001

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  管理命令
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  查看状态：
    ps aux | grep main.py
    docker ps | grep open-webui

  停止后端：
    kill $(cat /var/tmp/qoderclaw-backend.pid)

  停止 Open WebUI（如已部署）：
    docker stop open-webui

  重启后端：
    cd ~/mysoft/qoderclaw && ./venv/bin/python main.py --host 127.0.0.1 --port 8080 &
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 注意事项

1. **安全要求**：
   - QoderClaw 只监听 `127.0.0.1`（localhost）
   - 不配置任何外部 API 密钥（飞书、OpenAI 等）

2. **推荐方案（Opencode）**：
   - 无需 Docker，直接接入 Opencode 应用
   - 支持项目级工作目录（使用 /cd 命令切换）
   - 轻量级，资源占用低

3. **可选方案（Open WebUI）**：
   - 需要 Docker 运行
   - 提供更完整的 Web 界面
   - 数据持久化通过 Docker volume `open-webui-data`

4. **qodercli 依赖**：
   - 必须先检测 qodercli 是否存在
   - 不存在时明确提示用户先安装，不要尝试自动安装

4. **配置灵活性**：
   - 工作目录由用户指定
   - qodercli 路径自动检测或由用户指定
```

---

## 使用方法

将上面的提示词复制给 AI 助手，AI 会按照步骤自动完成安装和配置。

### 自定义选项

如果需要自定义，可以修改以下参数：

- **安装目录**：将所有的 `~/mysoft` 改为你想要的路径
- **项目路径**：`<USER_PROJECT_PATH>` 改为你的实际项目路径
- **前端端口**：将 `-p 3001:8080` 中的 `3001` 改为你想要的端口
