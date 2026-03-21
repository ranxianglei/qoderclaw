#!/bin/bash

# =============================================================================
# QoderClaw 自动化部署脚本
# 支持 Linux/macOS，混合模式（配置文件 + 交互式）
# =============================================================================

set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 全局变量
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/deploy-config.json"
LOG_FILE="$SCRIPT_DIR/logs/deploy.log"
TEMP_DIR="/tmp/qoderclaw-deploy-$$"

# 默认配置
DEFAULT_BACKEND_PORT=8080
DEFAULT_FRONTEND_PORT=3001
DEFAULT_HOST="127.0.0.1"
DEFAULT_WORKDIR="$HOME"
DEFAULT_QODERCLAW_DIR="$HOME/mysoft/qoderclaw"
DEFAULT_USE_SYSTEMD=false

# =============================================================================
# 工具函数
# =============================================================================

log() {
    echo -e "${BLUE}[INFO]${NC} $*" | tee -a "$LOG_FILE"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $*" | tee -a "$LOG_FILE"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*" | tee -a "$LOG_FILE" >&2
}

die() {
    log_error "$*"
    exit 1
}

# 检测操作系统
detect_os() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        OS="macos"
        PKG_MANAGER="brew"
        HAS_SYSTEMD=false
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        OS="linux"
        if command -v apt-get &>/dev/null; then
            PKG_MANAGER="apt"
        elif command -v yum &>/dev/null; then
            PKG_MANAGER="yum"
        else
            PKG_MANAGER="unknown"
        fi
        # 检测是否支持 systemd
        if command -v systemctl &>/dev/null && [[ -d /run/systemd/system || -d /var/run/systemd/system ]]; then
            HAS_SYSTEMD=true
        else
            HAS_SYSTEMD=false
        fi
    else
        die "不支持的操作系统: $OSTYPE"
    fi
    log "检测到操作系统: $OS ($PKG_MANAGER)"
    if [[ "$HAS_SYSTEMD" == "true" ]]; then
        log "检测到 systemd 支持"
    fi
}

# 检查命令是否存在
check_command() {
    local cmd="$1"
    local install_hint="${2:-}"
    
    if ! command -v "$cmd" &>/dev/null; then
        log_error "未找到命令: $cmd"
        if [[ -n "$install_hint" ]]; then
            log "安装建议: $install_hint"
        fi
        return 1
    fi
    return 0
}

# =============================================================================
# 依赖检测
# =============================================================================

check_dependencies() {
    log "正在检查系统依赖..."
    
    # 检查基础工具
    check_command "curl" || die "请安装 curl"
    check_command "git" || die "请安装 git"
    check_command "python3" || die "请安装 Python 3.8+"
    
    # 检查 qodercli
    if ! command -v qodercli &>/dev/null; then
        log_warn "未找到 qodercli"
        read -p "请输入 qodercli 的完整路径（或按 Enter 跳过）: " QODERCLI_PATH
        if [[ -z "$QODERCLI_PATH" ]]; then
            die "必须安装 qodercli 才能继续。请先运行：curl -fsSL https://raw.githubusercontent.com/qoder-ai/qoder/main/install.sh | bash"
        fi
        if [[ ! -x "$QODERCLI_PATH" ]]; then
            die "无效的 qodercli 路径: $QODERCLI_PATH"
        fi
        QODERCLI_CMD="$QODERCLI_PATH"
    else
        QODERCLI_CMD="qodercli"
        log_success "找到 qodercli: $(which qodercli)"
    fi
    
    # 检查 Docker
    if ! command -v docker &>/dev/null; then
        log_warn "未找到 Docker"
        if [[ "$OS" == "macos" ]]; then
            die "请先安装 Docker Desktop: https://www.docker.com/products/docker-desktop/"
        else
            die "请先安装 Docker: https://docs.docker.com/engine/install/"
        fi
    fi
    
    # 检查 Docker daemon 是否运行
    if ! docker info &>/dev/null; then
        die "Docker daemon 未运行，请启动 Docker 服务"
    fi
    
    log_success "所有依赖检查通过"
}

# =============================================================================
# 配置管理
# =============================================================================

load_or_create_config() {
    if [[ -f "$CONFIG_FILE" ]]; then
        log "发现现有配置文件: $CONFIG_FILE"
        # 验证 JSON 格式
        if python3 -m json.tool "$CONFIG_FILE" &>/dev/null; then
            log_success "配置文件格式正确"
            # 从配置文件读取值（如果用户没在命令行指定）
            [[ -z "${BACKEND_PORT:-}" ]] && BACKEND_PORT=$(jq -r '.backend_port // empty' "$CONFIG_FILE")
            [[ -z "${FRONTEND_PORT:-}" ]] && FRONTEND_PORT=$(jq -r '.frontend_port // empty' "$CONFIG_FILE")
            [[ -z "${HOST:-}" ]] && HOST=$(jq -r '.host // empty' "$CONFIG_FILE")
            [[ -z "${WORKDIR:-}" ]] && WORKDIR=$(jq -r '.workdir // empty' "$CONFIG_FILE")
            [[ -z "${QODERCLAW_DIR:-}" ]] && QODERCLAW_DIR=$(jq -r '.qoderclaw_dir // empty' "$CONFIG_FILE")
            [[ -z "${API_KEY:-}" ]] && API_KEY=$(jq -r '.api_key // empty' "$CONFIG_FILE")
            [[ -z "${USE_SYSTEMD:-}" ]] && USE_SYSTEMD=$(jq -r '.use_systemd // false' "$CONFIG_FILE")
        else
            log_warn "配置文件格式错误，将重新创建"
            rm -f "$CONFIG_FILE"
        fi
    fi
    
    # 如果配置文件不存在或某些值为空，则交互式收集
    collect_missing_configs
    save_config
}

collect_missing_configs() {
    log "收集部署配置..."
    
    # 后端端口
    if [[ -z "${BACKEND_PORT:-}" ]]; then
        read -p "后端端口 [$DEFAULT_BACKEND_PORT]: " BACKEND_PORT
        BACKEND_PORT=${BACKEND_PORT:-$DEFAULT_BACKEND_PORT}
    fi
    
    # 前端端口
    if [[ -z "${FRONTEND_PORT:-}" ]]; then
        read -p "前端端口 [$DEFAULT_FRONTEND_PORT]: " FRONTEND_PORT
        FRONTEND_PORT=${FRONTEND_PORT:-$DEFAULT_FRONTEND_PORT}
    fi
    
    # 监听地址
    if [[ -z "${HOST:-}" ]]; then
        read -p "监听地址 [$DEFAULT_HOST]: " HOST
        HOST=${HOST:-$DEFAULT_HOST}
    fi
    
    # 工作目录
    if [[ -z "${WORKDIR:-}" ]]; then
        read -p "Qoder 工作目录 [$DEFAULT_WORKDIR]: " WORKDIR
        WORKDIR=${WORKDIR:-$DEFAULT_WORKDIR}
    fi
    
    # QoderClaw 安装目录
    if [[ -z "${QODERCLAW_DIR:-}" ]]; then
        read -p "QoderClaw 安装目录 [$DEFAULT_QODERCLAW_DIR]: " QODERCLAW_DIR
        QODERCLAW_DIR=${QODERCLAW_DIR:-$DEFAULT_QODERCLAW_DIR}
    fi
    
    # API Key（可选）
    if [[ -z "${API_KEY:-}" ]]; then
        read -p "API Key（可选，默认随机生成）: " API_KEY
        if [[ -z "$API_KEY" ]]; then
            API_KEY="sk-qoderclaw-$(openssl rand -hex 16 2>/dev/null || echo "$(date +%s)")"
        fi
    fi
    
    # 是否使用 systemd（仅限 Linux）
    if [[ -z "${USE_SYSTEMD:-}" ]] && [[ "$HAS_SYSTEMD" == "true" ]]; then
        read -p "使用 systemd 管理服务? [y/N]: " USE_SYSTEMD_INPUT
        if [[ "$USE_SYSTEMD_INPUT" =~ ^[Yy]$ ]]; then
            USE_SYSTEMD=true
        else
            USE_SYSTEMD=false
        fi
    fi
}

save_config() {
    mkdir -p "$(dirname "$CONFIG_FILE")"
    cat > "$CONFIG_FILE" <<EOF
{
    "backend_port": $BACKEND_PORT,
    "frontend_port": $FRONTEND_PORT,
    "host": "$HOST",
    "workdir": "$WORKDIR",
    "qoderclaw_dir": "$QODERCLAW_DIR",
    "api_key": "$API_KEY",
    "use_systemd": ${USE_SYSTEMD:-false},
    "created_at": "$(date -Iseconds)"
}
EOF
    log_success "配置已保存到: $CONFIG_FILE"
}

# =============================================================================
# 后端部署
# =============================================================================

deploy_backend() {
    log "开始部署 QoderClaw 后端..."
    
    # 创建目录
    mkdir -p "$QODERCLAW_DIR"
    cd "$QODERCLAW_DIR"
    
    # 克隆仓库（如果不存在）
    if [[ ! -d ".git" ]]; then
        log "克隆 QoderClaw 仓库..."
        git clone https://github.com/ranxianglei/qoderclaw.git .
    else
        log "更新现有仓库..."
        git pull
    fi
    
    # 创建虚拟环境
    if [[ ! -d "venv" ]]; then
        log "创建 Python 虚拟环境..."
        python3 -m venv venv
    fi
    
    # 激活环境并安装依赖
    source venv/bin/activate
    log "安装 Python 依赖..."
    pip install -r requirements.txt
    
    # 创建日志目录
    mkdir -p logs
    
    # 生成配置文件
    cat > config.yaml <<EOF
system:
  host: "$HOST"
  port: $BACKEND_PORT
  log_level: "INFO"
  log_file: "logs/qoderclaw.log"

qoder_instances:
  default-assistant:
    name: "default-assistant"
    workdir: "$WORKDIR"
    cmd: "$QODERCLI_CMD"
    args: []
    auto_start: true
    max_restarts: 3

feishu_bots: {}
EOF
    
    log_success "后端配置完成"
}

# =============================================================================
# 前端部署
# =============================================================================

deploy_frontend() {
    log "开始部署 Open WebUI 前端..."
    
    local IMAGE_NAME="qoderclaw-webui:latest"
    
    # 构建自定义镜像（包含 QoderClaw 集成）
    log "构建 QoderClaw Open WebUI 镜像..."
    docker build -f "$QODERCLAW_DIR/Dockerfile.openwebui" -t "$IMAGE_NAME" "$QODERCLAW_DIR"
    
    # 停止已有容器
    if docker ps -a --format '{{.Names}}' | grep -q "^open-webui$"; then
        log "停止现有容器..."
        docker stop open-webui 2>/dev/null || true
        docker rm open-webui 2>/dev/null || true
    fi
    
    # 启动新容器
    log "启动 Open WebUI 容器..."
    docker run -d \
        --name open-webui \
        --restart always \
        -p "$FRONTEND_PORT:8080" \
        -e ENABLE_SIGNUP=true \
        -e DEFAULT_USER_ROLE=user \
        -e OPENAI_API_BASE_URL="http://host.docker.internal:$BACKEND_PORT/v1" \
        -e OPENAI_API_KEY="$API_KEY" \
        -e DEFAULT_MODEL=default-assistant \
        -e ENABLE_OLLAMA_API=false \
        -e ENABLE_FORWARD_USER_INFO_HEADERS=true \
        -v open-webui-data:/app/backend/data \
        --add-host=host.docker.internal:host-gateway \
        "$IMAGE_NAME"
    
    # 等待启动
    log "等待前端启动..."
    for i in {1..60}; do
        if curl -sf "http://127.0.0.1:$FRONTEND_PORT" &>/dev/null; then
            log_success "前端启动成功"
            return 0
        fi
        sleep 2
    done
    
    log_error "前端启动超时"
    return 1
}

# =============================================================================
# Systemd 服务管理
# =============================================================================

install_systemd_service() {
    log "安装 systemd 服务..."
    
    local SERVICE_NAME="qoderclaw"
    local SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
    
    # 检查权限
    if [[ $EUID -ne 0 ]]; then
        log_warn "需要 root 权限安装 systemd 服务，尝试使用 sudo..."
        if ! sudo -n true 2>/dev/null; then
            log_warn "无 sudo 权限，跳过 systemd 安装，使用普通进程启动"
            USE_SYSTEMD=false
            return 0
        fi
    fi
    
    # 创建服务文件
    local SERVICE_CONTENT="[Unit]
Description=QoderClaw Multi-platform Bridge Service
After=network.target

[Service]
Type=simple
User=$USER
Group=$USER
WorkingDirectory=$QODERCLAW_DIR
Environment=\"QODERCLAW_API_KEY=$API_KEY\"
Environment=\"PATH=$QODERCLAW_DIR/venv/bin:/home/$USER/.local/bin:/usr/local/bin:/usr/bin:/bin\"
ExecStart=$QODERCLAW_DIR/venv/bin/python main.py --host $HOST --port $BACKEND_PORT
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=qoderclaw

[Install]
WantedBy=multi-user.target
"
    
    # 写入服务文件
    if [[ $EUID -eq 0 ]]; then
        echo "$SERVICE_CONTENT" > "$SERVICE_FILE"
    else
        echo "$SERVICE_CONTENT" | sudo tee "$SERVICE_FILE" > /dev/null
    fi
    
    # 重载 systemd
    if [[ $EUID -eq 0 ]]; then
        systemctl daemon-reload
        systemctl enable "$SERVICE_NAME"
    else
        sudo systemctl daemon-reload
        sudo systemctl enable "$SERVICE_NAME"
    fi
    
    log_success "systemd 服务已安装: $SERVICE_NAME"
    log "管理命令:"
    log "  sudo systemctl start $SERVICE_NAME   # 启动"
    log "  sudo systemctl stop $SERVICE_NAME    # 停止"
    log "  sudo systemctl restart $SERVICE_NAME # 重启"
    log "  sudo systemctl status $SERVICE_NAME  # 查看状态"
    log "  sudo journalctl -u $SERVICE_NAME -f  # 查看日志"
}

start_backend() {
    log "启动 QoderClaw 后端..."
    cd "$QODERCLAW_DIR"
    source venv/bin/activate
    
    # 设置环境变量
    export QODERCLAW_API_KEY="$API_KEY"
    
    if [[ "${USE_SYSTEMD:-false}" == "true" ]] && [[ "$HAS_SYSTEMD" == "true" ]]; then
        # 使用 systemd 启动
        if [[ $EUID -eq 0 ]]; then
            systemctl start qoderclaw
        else
            sudo systemctl start qoderclaw
        fi
        
        # 等待启动
        log "等待后端启动..."
        for i in {1..30}; do
            if systemctl is-active --quiet qoderclaw 2>/dev/null; then
                log_success "后端启动成功 (systemd)"
                return 0
            fi
            sleep 1
        done
        
        log_error "后端启动超时，请查看日志: sudo journalctl -u qoderclaw -n 50"
        return 1
    else
        # 普通进程启动
        nohup ./venv/bin/python main.py --host "$HOST" --port "$BACKEND_PORT" > logs/server.log 2>&1 &
        echo $! > /tmp/qoderclaw-backend.pid
        
        # 等待启动
        log "等待后端启动..."
        for i in {1..30}; do
            if curl -sf "http://127.0.0.1:$BACKEND_PORT/health" &>/dev/null; then
                log_success "后端启动成功"
                return 0
            fi
            sleep 1
        done
        
        log_error "后端启动超时，请查看日志: $QODERCLAW_DIR/logs/server.log"
        return 1
    fi
}

stop_backend() {
    if [[ "${USE_SYSTEMD:-false}" == "true" ]] && [[ "$HAS_SYSTEMD" == "true" ]]; then
        if [[ $EUID -eq 0 ]]; then
            systemctl stop qoderclaw 2>/dev/null || true
        else
            sudo systemctl stop qoderclaw 2>/dev/null || true
        fi
    else
        # 停止普通进程
        if [[ -f /tmp/qoderclaw-backend.pid ]]; then
            local PID
            PID=$(cat /tmp/qoderclaw-backend.pid)
            if kill -0 "$PID" 2>/dev/null; then
                kill "$PID" 2>/dev/null || true
            fi
            rm -f /tmp/qoderclaw-backend.pid
        fi
    fi
}

# =============================================================================
# 验证部署
# =============================================================================

validate_deployment() {
    log "验证部署..."
    
    # 检查后端健康
    if curl -sf "http://127.0.0.1:$BACKEND_PORT/health" &>/dev/null; then
        log_success "✓ 后端健康检查通过"
    else
        log_error "✗ 后端健康检查失败"
        return 1
    fi
    
    # 检查前端可访问
    if curl -sf "http://127.0.0.1:$FRONTEND_PORT" &>/dev/null; then
        log_success "✓ 前端可访问"
    else
        log_error "✗ 前端无法访问"
        return 1
    fi
    
    # 测试 API（可选）
    log "测试 OpenAI 兼容 API..."
    RESPONSE=$(curl -sf -X POST "http://127.0.0.1:$BACKEND_PORT/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $API_KEY" \
        -d '{"model":"default-assistant","messages":[{"role":"user","content":"ping"}]}' || echo "ERROR")
    
    if [[ "$RESPONSE" != "ERROR" ]] && echo "$RESPONSE" | grep -q "choices"; then
        log_success "✓ API 测试通过"
    else
        log_warn "⚠ API 测试失败（可能是正常现象，Qoder 可能还没准备好）"
    fi
    
    return 0
}

# =============================================================================
# 服务管理
# =============================================================================

show_status() {
    echo
    echo "=== QoderClaw 部署状态 ==="
    echo
    
    # 后端状态
    if [[ "${USE_SYSTEMD:-false}" == "true" ]] && [[ "$HAS_SYSTEMD" == "true" ]]; then
        if systemctl is-active --quiet qoderclaw 2>/dev/null; then
            echo "后端: ${GREEN}运行中${NC} (systemd)"
            echo "      地址: http://$HOST:$BACKEND_PORT"
        else
            echo "后端: ${RED}未运行${NC} (systemd)"
        fi
    else
        if [[ -f /tmp/qoderclaw-backend.pid ]] && kill -0 "$(cat /tmp/qoderclaw-backend.pid)" 2>/dev/null; then
            echo "后端: ${GREEN}运行中${NC} (PID: $(cat /tmp/qoderclaw-backend.pid))"
            echo "      地址: http://$HOST:$BACKEND_PORT"
        else
            echo "后端: ${RED}未运行${NC}"
        fi
    fi
    
    # 前端状态
    if docker ps --format '{{.Names}}' | grep -q "^open-webui$"; then
        PORT_MAP=$(docker port open-webui 8080/tcp | cut -d: -f2)
        echo "前端: ${GREEN}运行中${NC} (端口: $PORT_MAP)"
        echo "      地址: http://127.0.0.1:$FRONTEND_PORT"
    else
        echo "前端: ${RED}未运行${NC}"
    fi
    
    echo
    echo "=== 使用说明 ==="
    echo "1. 访问前端: http://127.0.0.1:$FRONTEND_PORT"
    echo "2. 首次使用需创建管理员账号"
    echo "3. API 文档: http://$HOST:$BACKEND_PORT/docs"
    echo
    echo "=== 管理命令 ==="
    if [[ "${USE_SYSTEMD:-false}" == "true" ]] && [[ "$HAS_SYSTEMD" == "true" ]]; then
        echo "查看日志: sudo journalctl -u qoderclaw -f"
        echo "停止服务: sudo systemctl stop qoderclaw"
        echo "重启服务: sudo systemctl restart qoderclaw"
    else
        echo "查看日志: tail -f $QODERCLAW_DIR/logs/server.log"
        echo "停止服务: $0 stop"
        echo "重启服务: $0 restart"
    fi
}

stop_services() {
    log "停止服务..."
    
    # 停止后端
    stop_backend
    log_success "后端已停止"
    
    # 停止前端
    if docker ps -a --format '{{.Names}}' | grep -q "^open-webui$"; then
        docker stop open-webui &>/dev/null
        docker rm open-webui &>/dev/null
        log_success "前端已停止"
    fi
}

# =============================================================================
# 主程序
# =============================================================================

main() {
    # 创建日志目录
    mkdir -p "$(dirname "$LOG_FILE")"
    
    # 解析命令行参数
    ACTION="deploy"
    while [[ $# -gt 0 ]]; do
        case $1 in
            start)   ACTION="start" ;;
            stop)    ACTION="stop" ;;
            restart) ACTION="restart" ;;
            status)  ACTION="status" ;;
            --backend-port) BACKEND_PORT="$2"; shift ;;
            --frontend-port) FRONTEND_PORT="$2"; shift ;;
            --host) HOST="$2"; shift ;;
            --workdir) WORKDIR="$2"; shift ;;
            --qoderclaw-dir) QODERCLAW_DIR="$2"; shift ;;
            --api-key) API_KEY="$2"; shift ;;
            -h|--help)
                echo "用法: $0 [start|stop|restart|status] [选项]"
                echo
                echo "选项:"
                echo "  --backend-port PORT    后端端口 (默认: 8080)"
                echo "  --frontend-port PORT   前端端口 (默认: 3001)"
                echo "  --host ADDRESS         监听地址 (默认: 127.0.0.1)"
                echo "  --workdir PATH         Qoder 工作目录"
                echo "  --qoderclaw-dir PATH   QoderClaw 安装目录"
                echo "  --api-key KEY          API Key"
                echo
                echo "示例:"
                echo "  $0                      # 首次部署"
                echo "  $0 start               # 启动服务"
                echo "  $0 stop                # 停止服务"
                echo "  $0 status              # 查看状态"
                exit 0
                ;;
        esac
        shift
    done
    
    # 执行对应动作
    case "$ACTION" in
        deploy)
            log "开始自动化部署..."
            detect_os
            check_dependencies
            load_or_create_config
            deploy_backend
            
            # 安装 systemd 服务（如果用户选择）
            if [[ "${USE_SYSTEMD:-false}" == "true" ]] && [[ "$HAS_SYSTEMD" == "true" ]]; then
                install_systemd_service
            fi
            
            start_backend
            deploy_frontend
            if validate_deployment; then
                log_success "🎉 部署完成！"
                show_status
            else
                log_error "部署验证失败"
                exit 1
            fi
            ;;
        
        start)
            load_or_create_config
            start_backend
            # 前端通过 Docker restart 启动
            docker start open-webui 2>/dev/null || deploy_frontend
            show_status
            ;;
        
        stop)
            stop_services
            ;;
        
        restart)
            stop_services
            sleep 2
            load_or_create_config
            start_backend
            docker restart open-webui
            show_status
            ;;
        
        status)
            show_status
            ;;
    esac
}

# 确保脚本被直接执行
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi