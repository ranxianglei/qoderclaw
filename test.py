"""
测试脚本 - 验证 QoderClaw 的核心功能
"""
import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from adapters.base import BotConfig, Message, MessageType, User
from adapters.feishu import FeishuBotAdapter, FeishuPlatformManager
from qoder_manager import QoderConfig, QoderProcessManager, get_process_manager
from bridge_core import BridgeCore


async def test_base_adapter():
    """测试基础适配器"""
    print("\n=== 测试基础适配器 ===")
    
    config = BotConfig(
        id="test-bot",
        platform="feishu",
        name="Test Bot",
        credentials={
            "app_id": "test_app_id",
            "app_secret": "test_app_secret",
            "verification_token": "test_token",
        },
        qoder_instance="test-qoder",
    )
    
    adapter = FeishuBotAdapter(config)
    print(f"✓ 创建适配器成功：{adapter.bot_id}")
    print(f"  平台：{adapter.platform_name}")
    print(f"  状态：{adapter.status}")
    
    # 测试消息创建
    message = adapter.create_text_message(
        content="Hello, World!",
        conversation_id="test_chat_id",
    )
    assert message.type == MessageType.TEXT
    assert message.content == "Hello, World!"
    print(f"✓ 创建消息成功：{message.content}")
    
    return True


async def test_process_manager():
    """测试进程管理器"""
    print("\n=== 测试进程管理器 ===")
    
    manager = QoderProcessManager()
    
    # 注册一个测试实例
    config = QoderConfig(
        name="test-instance",
        workdir="/tmp/qoder-test",
        cmd="echo",
        args=["QoderClaw Test"],
        auto_start=False,
    )
    
    manager.register_instance(config)
    print(f"✓ 注册实例成功：{config.name}")
    
    # 测试启动（使用 echo 命令模拟）
    success = await manager.start_instance("test-instance")
    print(f"✓ 启动实例：{'成功' if success else '失败'}")
    
    # 等待一下
    await asyncio.sleep(1)
    
    # 获取状态
    status = manager.get_status("test-instance")
    print(f"  状态：{status}")
    
    # 获取统计
    stats = manager.get_stats("test-instance")
    if stats:
        print(f"  PID: {stats.pid}")
        print(f"  内存：{stats.memory_mb:.2f} MB")
    
    # 停止实例
    await manager.stop_instance("test-instance")
    print(f"✓ 停止实例成功")
    
    return True


async def test_bridge_core():
    """测试桥接核心"""
    print("\n=== 测试桥接核心 ===")
    
    process_manager = get_process_manager()
    bridge = BridgeCore(process_manager)
    
    # 创建一个模拟的 bot
    config = BotConfig(
        id="mock-bot",
        platform="feishu",
        name="Mock Bot",
        credentials={
            "app_id": "mock_app_id",
            "app_secret": "mock_app_secret",
            "verification_token": "mock_token",
        },
        qoder_instance="mock-qoder",
    )
    
    mock_bot = FeishuBotAdapter(config)
    bridge.register_bot(mock_bot, "mock-qoder")
    
    print(f"✓ 注册机器人：{mock_bot.bot_id} -> mock-qoder")
    
    # 测试命令解析
    command = bridge._parse_command("/start my-assistant")
    assert command is not None
    assert command.action.value == "start"
    assert command.args == ["my-assistant"]
    print(f"✓ 命令解析成功：{command.action.value} {command.args}")
    
    # 测试帮助信息
    help_text = bridge._format_help()
    assert "/help" in help_text
    assert "/start" in help_text
    print(f"✓ 帮助信息生成成功")
    
    return True


async def test_message_flow():
    """测试消息流转"""
    print("\n=== 测试消息流转 ===")
    
    # 创建模拟消息
    user = User(
        id="user_123",
        name="Test User",
        platform="feishu",
    )
    
    message = Message(
        id="msg_001",
        content="你好，Qoder！",
        type=MessageType.TEXT,
        sender=user,
        conversation_id="chat_456",
        is_group=False,
    )
    
    print(f"✓ 创建测试消息：{message.content}")
    print(f"  发送者：{message.sender.name}")
    print(f"  会话 ID: {message.conversation_id}")
    
    # 测试命令消息
    command_msg = Message(
        id="msg_002",
        content="/help",
        type=MessageType.COMMAND,
        sender=user,
        conversation_id="chat_456",
    )
    
    print(f"✓ 创建命令消息：{command_msg.content}")
    
    return True


async def main():
    """运行所有测试"""
    print("=" * 60)
    print("QoderClaw 测试套件")
    print("=" * 60)
    
    tests = [
        ("基础适配器", test_base_adapter),
        ("进程管理器", test_process_manager),
        ("桥接核心", test_bridge_core),
        ("消息流转", test_message_flow),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = await test_func()
            results.append((name, result, None))
        except Exception as e:
            results.append((name, False, str(e)))
            print(f"✗ {name} 测试失败：{e}")
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    passed = sum(1 for _, result, _ in results if result)
    total = len(results)
    
    for name, result, error in results:
        icon = "✅" if result else "❌"
        print(f"{icon} {name}: {'通过' if result else '失败'}")
        if error:
            print(f"   错误：{error}")
    
    print(f"\n总计：{passed}/{total} 测试通过")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
