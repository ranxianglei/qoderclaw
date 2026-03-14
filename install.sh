#!/bin/bash
# Qoder Bridge 快速启动脚本

set -e

echo "======================================"
echo "Qoder Bridge 安装向导"
echo "======================================"

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误：未找到 Python3"
    exit 1
fi

PYTHON_VERSION=$(python3 --version)
echo "✓ 检测到 $PYTHON_VERSION"

# 创建虚拟环境
if [ ! -d "venv" ]; then
    echo "正在创建虚拟环境..."
    python3 -m venv venv
    echo "✓ 虚拟环境创建成功"
else
    echo "✓ 虚拟环境已存在"
fi

# 激活虚拟环境
echo "激活虚拟环境..."
source venv/bin/activate

# 安装依赖
echo "正在安装依赖..."
pip install --upgrade pip
pip install -r requirements.txt
echo "✓ 依赖安装完成"

# 创建日志目录
mkdir -p logs
echo "✓ 日志目录已创建"

# 检查配置文件
if [ ! -f "config.yaml" ]; then
    echo "复制配置文件示例..."
    cp config.example.yaml config.yaml
    echo "⚠️  请编辑 config.yaml 填入你的配置"
else
    echo "✓ 配置文件已存在"
fi

echo ""
echo "======================================"
echo "安装完成！"
echo "======================================"
echo ""
echo "下一步："
echo "1. 编辑 config.yaml 填入飞书凭证和 Qoder 配置"
echo "2. 在飞书开放平台配置事件订阅 URL"
echo "3. 运行：./start.sh"
echo ""
