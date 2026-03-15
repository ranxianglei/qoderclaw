#!/bin/bash
# QoderClaw 启动脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "❌ 虚拟环境不存在，请先运行：./install.sh"
    exit 1
fi

# 激活虚拟环境
source venv/bin/activate

# 检查配置文件
if [ ! -f "config.yaml" ]; then
    echo "❌ 配置文件不存在，请复制 config.example.yaml 并修改"
    exit 1
fi

# 创建日志目录
mkdir -p logs

# 启动服务
echo "======================================"
echo "启动 QoderClaw"
echo "======================================"
echo ""

python main.py "$@"
