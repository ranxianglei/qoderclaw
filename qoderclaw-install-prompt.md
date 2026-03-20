# QoderClaw 安装助手提示词

请将以下提示词提供给 AI 助手来安装 QoderClaw：

---

## 安装任务提示词

```
请帮我安装 QoderClaw（Qoder AI 助手的多平台桥接服务）及其前端 Open WebUI。

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
  - 如果已安装，记录路径（如 `/home/ubuntu/.local/bin/qodercli`）

- **检查 Docker 是否已安装**：
  ```bash
  docker --version || echo "未安装"
  ```
  - 如果未安装，提示用户安装 Docker：
    ```
    ❌ 未检测到 Docker，Open WebUI 前端需要 Docker 运行。
    请参考 https://docs.docker.com/engine/install/ 安装 Docker。
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
- `<USER_PROJECT_PATH>` 替换为用户指定的项目路径（如 `/home/ubuntu/projects/my-app`）
- `<QODERCLI_PATH>` 替换为检测到的 qodercli 路径（如 `qodercli` 或完整路径）
- **不要配置任何飞书机器人**
- `host` 必须是 `127.0.0.1`（只允许本地访问）

#### 4. 部署前端（Open WebUI）

使用 Docker 部署 Open WebUI（QoderClaw 集成版）：

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

#### 5. 启动服务

**启动后端**：
```bash
cd ~/mysoft/qoderclaw
./venv/bin/python main.py --host 127.0.0.1 --port 8080 &
echo $! > /tmp/qoderclaw-backend.pid
```

**前端已通过 Docker 自动启动**，无需额外操作。

#### 6. 验证安装

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
  前端地址：http://127.0.0.1:3001
  API 文档：http://127.0.0.1:8080/docs

  Qoder 工作目录：<USER_PROJECT_PATH>
  qodercli 路径：<QODERCLI_PATH>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  使用说明
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. 在浏览器中打开：http://127.0.0.1:3001
  2. 首次访问需要创建管理员账号
  3. 开始与 Qoder AI 对话

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  管理命令
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  查看状态：
    ps aux | grep main.py
    docker ps | grep open-webui

  停止服务：
    kill $(cat /tmp/qoderclaw-backend.pid)
    docker stop open-webui

  重启后端：
    cd ~/mysoft/qoderclaw && ./venv/bin/python main.py --host 127.0.0.1 --port 8080 &

  重启前端：
    docker restart open-webui
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 注意事项

1. **安全要求**：
   - QoderClaw 只监听 `127.0.0.1`（localhost）
   - Open WebUI 通过 Docker 端口映射到 `127.0.0.1:3001`
   - 不配置任何外部 API 密钥（飞书、OpenAI 等）

2. **Docker 要求**：
   - Open WebUI 前端通过 Docker 容器运行
   - 数据持久化通过 Docker volume `open-webui-data`

3. **qodercli 依赖**：
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
