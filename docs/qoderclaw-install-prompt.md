# QoderClaw 安装助手提示词

请将以下提示词提供给 AI 助手来安装 QoderClaw：

---

## 安装任务提示词

```
请帮我安装 QoderClaw（Qoder AI 助手的多平台桥接服务）及其前端 NextChat-Qoder。

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

- **检查 Node.js 和 npm 版本**：
  ```bash
  node --version
  npm --version
  ```
  - 检查 npm 是否有更新版本：`npm view npm version`
  - 如果当前版本不是最新，**不要升级系统 npm**，而是在 `~/mysoft` 目录下安装最新的 Node.js：
    ```bash
    # 下载最新版 Node.js
    cd ~/mysoft
    curl -fsSLO https://nodejs.org/dist/latest-v20.x/node-v20.x.x-linux-x64.tar.xz
    tar -xf node-v20.x.x-linux-x64.tar.xz
    rm node-v20.x.x-linux-x64.tar.xz
    
    # 更新环境变量（添加到 ~/.bashrc）
    echo 'export PATH=$HOME/mysoft/node-v20.x.x-linux-x64/bin:$PATH' >> ~/.bashrc
    source ~/.bashrc
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
  
  # Redis 配置（可选，不需要可注释）
  # redis_host: "localhost"
  # redis_port: 6379
  # redis_db: 0
  
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

#### 4. 安装前端（NextChat-Qoder）

```bash
# 克隆前端到 ~/mysoft/frontend
cd ~/mysoft
mkdir -p frontend
cd frontend
git clone https://github.com/ranxianglei/nextchat-qoder.git nextchat
cd nextchat

# 安装依赖
npm install

# 创建环境配置文件
cat > .env.local << 'EOF'
OPENAI_API_KEY=sk-qoderclaw
BASE_URL=http://127.0.0.1:8080
HIDE_USER_API_KEY=1
CUSTOM_MODELS=+default-assistant
DEFAULT_MODEL=default-assistant
EOF
```

#### 5. 启动服务

**启动后端**：
```bash
cd ~/mysoft/qoderclaw
./venv/bin/python main.py --host 127.0.0.1 --port 8080 &
echo $! > /tmp/qoderclaw-backend.pid
```

**启动前端**：
```bash
cd ~/mysoft/frontend/nextchat
HOSTNAME=127.0.0.1 npm run start &
echo $! > /tmp/qoderclaw-frontend.pid
```

#### 6. 验证安装

```bash
# 等待 10 秒让服务启动
sleep 10

# 检查后端健康状态
curl -s http://127.0.0.1:8080/health | jq

# 检查前端是否可访问
curl -s http://127.0.0.1:3000 | head -5

# 测试聊天 API
curl -s -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
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
  前端地址：http://127.0.0.1:3000
  API 文档：http://127.0.0.1:8080/docs

  Qoder 工作目录：<USER_PROJECT_PATH>
  qodercli 路径：<QODERCLI_PATH>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  使用说明
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. 在浏览器中打开：http://127.0.0.1:3000
  2. 开始与 Qoder AI 对话

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  管理命令
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  查看状态：
    ps aux | grep -E "main.py|next"

  停止服务：
    kill $(cat /tmp/qoderclaw-backend.pid)
    kill $(cat /tmp/qoderclaw-frontend.pid)

  重启后端：
    cd ~/mysoft/qoderclaw && ./venv/bin/python main.py --host 127.0.0.1 --port 8080 &

  重启前端：
    cd ~/mysoft/frontend/nextchat && HOSTNAME=127.0.0.1 npm run start &
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 注意事项

1. **安全要求**：
   - 所有服务必须只监听 `127.0.0.1`（localhost）
   - 不允许绑定到 `0.0.0.0` 或公网 IP
   - 不配置任何外部 API 密钥（飞书、OpenAI 等）

2. **npm 处理**：
   - 如果系统 npm 不是最新，在 `~/mysoft` 下安装独立的 Node.js
   - 不要修改系统的 npm/node

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
- **Node.js 版本**：将 `latest-v20.x` 改为你需要的版本
