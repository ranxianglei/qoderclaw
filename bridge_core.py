"""
核心桥接器 - 连接 IM 机器人和 Qoder ACP 进程

负责：
- 消息路由：飞书消息 → ACP prompt → 收集回复 → 飞书回复
- 会话管理：飞书 conversation_id ↔ ACP session_id
- 控制命令解析（/help, /forget, /status 等）
"""
import asyncio
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from enum import Enum
import time
from loguru import logger

from adapters.base import (
    BaseBotAdapter,
    Message,
    MessageType,
    User,
    BotStatus,
)
from qoder_manager import QoderProcessManager, QoderAcpClient, QoderStatus


class CommandAction(Enum):
    """控制命令动作"""
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    FORGET = "forget"
    STATUS = "status"
    HELP = "help"
    LIST = "list"
    HEALTH = "health"


@dataclass
class Command:
    """控制命令对象"""
    action: CommandAction
    args: List[str] = field(default_factory=list)
    raw: str = ""


class BridgeCore:
    """
    桥接核心

    连接飞书机器人和 Qoder ACP 进程，处理双向消息流。
    """

    def __init__(self, process_manager: QoderProcessManager):
        self.process_manager = process_manager
        self.bots: Dict[str, BaseBotAdapter] = {}
        self.bot_to_qoder_map: Dict[str, str] = {}  # bot_id → qoder_instance name

        self.command_prefix = "/"
        self.commands_help = {
            "start": "启动 Qoder 实例",
            "stop": "停止 Qoder 实例",
            "restart": "重启 Qoder 实例",
            "forget": "清除当前会话记忆（开始新对话）",
            "status": "查看 Qoder 状态",
            "list": "列出所有实例",
            "health": "健康检查",
            "help": "显示帮助",
        }

    def register_bot(self, bot: BaseBotAdapter, qoder_instance: str) -> None:
        """注册机器人及其关联的 Qoder 实例"""
        self.bots[bot.bot_id] = bot
        self.bot_to_qoder_map[bot.bot_id] = qoder_instance

        bot.on_message(self._handle_incoming_message)
        bot.on_status_change(self._handle_bot_status_change)

        logger.info(f"Registered bot {bot.bot_id} -> Qoder {qoder_instance}")

    async def start(self) -> None:
        """启动所有机器人"""
        for bot in self.bots.values():
            try:
                await bot.start()
            except Exception as e:
                logger.error(f"Failed to start bot {bot.bot_id}: {e}")

    async def stop(self) -> None:
        """停止所有机器人"""
        for bot in self.bots.values():
            try:
                await bot.stop()
            except Exception as e:
                logger.error(f"Failed to stop bot {bot.bot_id}: {e}")

    # ------------------------------------------------------------------
    # 消息处理
    # ------------------------------------------------------------------

    async def _handle_incoming_message(self, message: Message) -> None:
        """处理收到的消息"""
        try:
            content = (message.content or "").strip()
            if not content:
                return

            logger.info(
                f"收到消息 [{message.conversation_id[:12]}] "
                f"from {message.sender.name or message.sender.id}: {content[:60]}"
            )

            # 获取关联的 Qoder 实例名
            qoder_name = self._get_qoder_name(message)
            if not qoder_name:
                logger.warning("未找到关联的 Qoder 实例")
                return

            # 控制命令
            if content.startswith(self.command_prefix):
                cmd = self._parse_command(content)
                if cmd:
                    await self._execute_command(cmd, message, qoder_name)
                    return

            # 普通消息 → 转发到 Qoder ACP
            await self._forward_to_qoder(message, qoder_name)

        except Exception as e:
            logger.error(f"处理消息异常: {e}", exc_info=True)

    def _handle_bot_status_change(self, new_status: BotStatus) -> None:
        logger.info(f"Bot status changed: {new_status}")

    def _get_qoder_name(self, message: Message) -> Optional[str]:
        """获取消息对应的 Qoder 实例名"""
        # 通过 bot_id 映射
        if self.bot_to_qoder_map:
            return list(self.bot_to_qoder_map.values())[0]
        return None

    # ------------------------------------------------------------------
    # 转发到 Qoder（核心逻辑）
    # ------------------------------------------------------------------

    async def _forward_to_qoder(self, message: Message, qoder_name: str) -> None:
        """
        转发消息到 Qoder ACP 进程，用卡片消息实现流式更新。

        策略：
        1. 发送卡片消息"正在思考..." → 获得 message_id
        2. 每累积一定字符 → PATCH 更新同一张卡片
        3. 完成后 → 最终 PATCH 完整内容
        """
        client = self.process_manager.get_client(qoder_name)
        if not client:
            await self._send_reply(message, f"Qoder 实例 {qoder_name} 不存在")
            return

        if client.status != QoderStatus.RUNNING:
            await self._send_reply(message, f"Qoder 实例 {qoder_name} 未运行 ({client.status.value})")
            return

        bot = list(self.bots.values())[0] if self.bots else None
        if not bot:
            return

        conv_key = message.conversation_id

        # 1. 发送卡片占位消息
        msg_id = await bot.send_card_message(
            content="*正在思考...*",
            conversation_id=message.conversation_id,
        )
        if not msg_id:
            logger.error("发送卡片占位消息失败，回退到普通消息")
            reply_text = await client.send_prompt(conv_key, message.content)
            if reply_text:
                await self._send_reply(message, reply_text)
            return

        # 2. 流式接收，定期更新卡片
        accumulated = [""]
        last_update_len = [0]
        update_interval = 8  # 每 8 字符更新一次，更流畅
        update_lock = asyncio.Lock()

        async def do_update(text: str):
            async with update_lock:
                await bot.update_card_message(msg_id, text + " ▌")

        def on_chunk(chunk: str):
            accumulated[0] += chunk
            new_len = len(accumulated[0])
            if new_len - last_update_len[0] >= update_interval:
                last_update_len[0] = new_len
                text = accumulated[0].strip()
                if text:
                    asyncio.create_task(do_update(text))

        # 3. 发送 prompt 并等待完成
        reply_text = await client.send_prompt(
            conv_key,
            message.content,
            on_chunk=on_chunk,
        )

        # 4. 最终更新为完整内容（去掉光标）
        if reply_text:
            await bot.update_card_message(msg_id, reply_text)
        else:
            await bot.update_card_message(msg_id, "（Qoder 未返回回复）")

    # ------------------------------------------------------------------
    # 控制命令
    # ------------------------------------------------------------------

    def _parse_command(self, content: str) -> Optional[Command]:
        """解析控制命令"""
        parts = content[len(self.command_prefix):].strip().split()
        if not parts:
            return None

        action_str = parts[0].lower()
        try:
            action = CommandAction(action_str)
        except ValueError:
            return None

        return Command(action=action, args=parts[1:], raw=content)

    async def _execute_command(self, cmd: Command, message: Message, qoder_name: str) -> None:
        """执行控制命令"""
        logger.info(f"执行命令: {cmd.action.value} {cmd.args}")

        response = ""
        try:
            if cmd.action == CommandAction.HELP:
                response = self._format_help()

            elif cmd.action == CommandAction.STATUS:
                target = cmd.args[0] if cmd.args else qoder_name
                response = self._cmd_status(target)

            elif cmd.action == CommandAction.START:
                target = cmd.args[0] if cmd.args else qoder_name
                ok = await self.process_manager.start_instance(target)
                response = "已启动" if ok else "启动失败"

            elif cmd.action == CommandAction.STOP:
                target = cmd.args[0] if cmd.args else qoder_name
                ok = await self.process_manager.stop_instance(target)
                response = "已停止" if ok else "停止失败"

            elif cmd.action == CommandAction.RESTART:
                target = cmd.args[0] if cmd.args else qoder_name
                ok = await self.process_manager.restart_instance(target)
                response = "已重启" if ok else "重启失败"

            elif cmd.action == CommandAction.FORGET:
                response = await self._cmd_forget(message, qoder_name)

            elif cmd.action == CommandAction.LIST:
                response = self._cmd_list()

            elif cmd.action == CommandAction.HEALTH:
                response = await self._cmd_health()

        except Exception as e:
            response = f"命令执行失败：{e}"

        if response:
            await self._send_reply(message, response)

    def _cmd_status(self, qoder_name: str) -> str:
        """状态命令"""
        client = self.process_manager.get_client(qoder_name)
        if not client:
            return f"实例不存在：{qoder_name}"

        stats = client.get_stats()
        lines = [f"[{qoder_name}] 状态：{client.status.value}"]

        if stats:
            lines.append(f"PID: {stats.pid}")
            lines.append(f"会话数: {stats.session_count}")
            if stats.uptime_seconds:
                lines.append(f"运行时间: {stats.uptime_seconds / 60:.1f} 分钟")
            lines.append(f"CPU: {stats.cpu_percent:.1f}%  内存: {stats.memory_mb:.1f}MB")

        return "\n".join(lines)

    async def _cmd_forget(self, message: Message, qoder_name: str) -> str:
        """清除会话记忆"""
        client = self.process_manager.get_client(qoder_name)
        if not client:
            return "实例不存在"

        conv_key = message.conversation_id
        ok = await client.destroy_session(conv_key)
        if ok:
            return "已清除会话记忆，下次对话将开始新会话"
        return "当前没有活跃会话"

    def _cmd_list(self) -> str:
        """列出所有实例"""
        lines = ["Qoder 实例列表:"]
        for name, client in self.process_manager.clients.items():
            icon = "[ON]" if client.status == QoderStatus.RUNNING else "[OFF]"
            sessions = len(client.sessions)
            lines.append(f"  {icon} {name} - {client.status.value} ({sessions} sessions)")
        return "\n".join(lines) if len(lines) > 1 else "暂无实例"

    async def _cmd_health(self) -> str:
        """健康检查"""
        results = await self.process_manager.health_check()
        lines = ["健康检查:"]
        for name, info in results.items():
            lines.append(
                f"  {name}: {info['status']} | "
                f"PID:{info['pid'] or 'N/A'} | "
                f"Sessions:{info['session_count']} | "
                f"CPU:{info['cpu_percent']:.1f}% MEM:{info['memory_mb']:.1f}MB"
            )
        return "\n".join(lines)

    def _format_help(self) -> str:
        """格式化帮助"""
        lines = ["Qoder Bridge 命令:", ""]
        for cmd, desc in self.commands_help.items():
            lines.append(f"  {self.command_prefix}{cmd} - {desc}")
        lines.extend(["", "直接发送文字消息即可与 Qoder 对话"])
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 回复消息
    # ------------------------------------------------------------------

    async def _send_reply(self, original: Message, text: str) -> None:
        """回复消息到飞书"""
        bot = list(self.bots.values())[0] if self.bots else None
        if not bot:
            logger.warning("没有可用的机器人发送回复")
            return

        reply = bot.create_text_message(
            content=text,
            conversation_id=original.conversation_id,
            reply_to=original.id,
        )
        await bot.send_message(reply)


# 全局桥接器实例
_bridge: Optional[BridgeCore] = None


def get_bridge_core() -> BridgeCore:
    global _bridge
    if _bridge is None:
        from qoder_manager import get_process_manager
        _bridge = BridgeCore(get_process_manager())
    return _bridge
