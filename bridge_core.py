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
            has_media = bool(message.media)
            if not content and not has_media:
                return

            logger.info(
                f"收到消息 [{message.conversation_id[:12]}] "
                f"from {message.sender.name or message.sender.id}: "
                f"{content[:60]}"
                f"{' +' + str(len(message.media)) + ' media' if has_media else ''}"
            )

            # 获取关联的 Qoder 实例名
            qoder_name = self._get_qoder_name(message)
            if not qoder_name:
                logger.warning("未找到关联的 Qoder 实例")
                return

            # 控制命令（只处理纯文本命令，忽略带媒体的消息）
            if content and not has_media and content.startswith(self.command_prefix):
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

        # 处理媒体附件：下载并构建多模态 prompt
        media_parts = []
        unsupported_media = []
        if message.media:
            for media in message.media:
                try:
                    if media.type == "audio":
                        # Qoder ACP 不支持音频，降级为文本提示
                        duration_info = f"，时长 {media.duration}ms" if media.duration else ""
                        unsupported_media.append(f"[用户发送了一条语音消息{duration_info}，当前不支持语音识别]")
                        logger.info(f"[bridge] 语音消息降级为文本提示 (duration={media.duration})")
                        continue

                    # 下载媒体数据
                    resource_type = "image" if media.type == "image" else "file"
                    data = await bot.download_message_resource(
                        message.id,
                        media.file_key,
                        resource_type,
                    )
                    if data:
                        if media.type == "image":
                            # 推断图片 MIME 类型
                            mime = "image/png"  # default
                            if data[:8] == b'\x89PNG\r\n\x1a\n':
                                mime = "image/png"
                            elif data[:2] == b'\xff\xd8':
                                mime = "image/jpeg"
                            elif data[:4] == b'GIF8':
                                mime = "image/gif"
                            elif data[:4] == b'RIFF':
                                mime = "image/webp"

                            # 压缩图片（避免大图片导致 Qoder 超时）
                            compressed_data = self._compress_image(data, mime)
                            if compressed_data:
                                data = compressed_data
                                mime = "image/jpeg"  # 压缩后统一为 JPEG

                            media_parts.append({
                                "type": "image",
                                "data": data,
                                "mime": mime,
                            })
                            logger.info(f"[bridge] 下载图片成功: {mime} {len(data)} bytes (压缩后)")
                        else:
                            # 非图片、非音频的其他文件，Qoder 也不支持
                            unsupported_media.append(f"[用户发送了一个文件: {media.filename or 'unknown'}]")
                            logger.info(f"[bridge] 不支持的文件类型: {media.type}")
                except Exception as e:
                    logger.error(f"[bridge] 下载媒体失败: {e}")

        # 将不支持的媒体信息附加到文本内容
        text_content = message.content or ""
        if unsupported_media:
            text_content = "\n".join(unsupported_media) + "\n" + text_content

        # 1. 发送卡片占位消息
        placeholder = "*正在思考...*"
        if media_parts:
            placeholder = f"*正在处理 {len(media_parts)} 个媒体文件...*"
        msg_id = await bot.send_card_message(
            content=placeholder,
            conversation_id=message.conversation_id,
        )
        if not msg_id:
            logger.error("发送卡片占位消息失败，回退到普通消息")
            reply_text = await client.send_prompt(conv_key, text_content, media_parts=media_parts if media_parts else None)
            if reply_text:
                await self._send_reply(message, reply_text)
            return

        # 2. 流式接收，定期更新卡片
        accumulated = [""]
        last_patch_len = [0]  # 上一次 PATCH 实际发送的长度
        update_interval = 8  # 每 8 字符触发一次更新
        update_lock = asyncio.Lock()
        stream_start = [time.time()]
        update_count = [0]
        final_sent = [False]
        update_pending = [False]  # 是否有 PATCH 任务排队中
        stream_end_timer = [None]

        async def do_update(is_final: bool = False):
            """发送 PATCH 更新，始终使用最新累积内容"""
            async with update_lock:
                if final_sent[0]:
                    return
                # 获取当前最新内容
                text = accumulated[0].strip()
                if not text:
                    return
                cur_len = len(text)
                # 如果内容没有变化，跳过（除非是最终更新）
                if cur_len == last_patch_len[0] and not is_final:
                    update_pending[0] = False
                    return

                update_count[0] += 1
                elapsed = time.time() - stream_start[0]

                if is_final:
                    # 临时方案：先发一次完整内容（当做"倒数第二批"）
                    logger.debug(
                        f"[bridge] PATCH #{update_count[0]} @{elapsed:.2f}s "
                        f"len={cur_len} final-content"
                    )
                    await bot.update_card_message(msg_id, text)
                    last_patch_len[0] = cur_len
                    final_sent[0] = True
                    if stream_end_timer[0]:
                        stream_end_timer[0].cancel()
                        stream_end_timer[0] = None
                    # 再 fire-and-forget 发一次带尾缀的 dummy PATCH（这个可能卡住，但无所谓）
                    async def _dummy_patch():
                        try:
                            await asyncio.sleep(0.1)
                            await bot.update_card_message(msg_id, text + "\n")
                            logger.debug("[bridge] dummy PATCH 完成")
                        except Exception:
                            pass
                    asyncio.create_task(_dummy_patch())
                else:
                    display = text + " ▌"
                    logger.debug(
                        f"[bridge] PATCH #{update_count[0]} @{elapsed:.2f}s "
                        f"len={cur_len} final=False"
                    )
                    await bot.update_card_message(msg_id, display)
                    last_patch_len[0] = cur_len

                update_pending[0] = False

        def schedule_final_update():
            """如果一段时间没有新 chunk，发送最终更新"""
            async def _send_final():
                await asyncio.sleep(0.8)
                if final_sent[0]:
                    return
                text = accumulated[0].strip()
                if text:
                    logger.debug(f"[bridge] 检测到流结束，自动发送最终更新")
                    await do_update(is_final=True)

            stream_end_timer[0] = asyncio.create_task(_send_final())

        def on_chunk(chunk: str):
            accumulated[0] += chunk
            new_len = len(accumulated[0])

            # 重置流结束检测
            if stream_end_timer[0]:
                stream_end_timer[0].cancel()
            schedule_final_update()

            # 每 8 字符触发一次更新（如果没有排队中的更新）
            if new_len - last_patch_len[0] >= update_interval or new_len <= 2:
                if not update_pending[0]:
                    update_pending[0] = True
                    asyncio.create_task(do_update())

        # 3. 发送 prompt 并等待完成
        reply_text = await client.send_prompt(
            conv_key,
            text_content,
            on_chunk=on_chunk,
            media_parts=media_parts if media_parts else None,
        )

        # 4. 最终更新为完整内容（去掉光标）
        # 如果已经发送过最终更新（final_sent=True），则跳过
        elapsed = time.time() - stream_start[0]
        logger.debug(
            f"[bridge] send_prompt 返回，长度: {len(reply_text) if reply_text else 0}，"
            f"总耗时: {elapsed:.2f}s，中间更新: {update_count[0]} 次，已发最终: {final_sent[0]}"
        )
        if reply_text and not final_sent[0]:
            await do_update(is_final=True)
        elif final_sent[0]:
            logger.debug("[bridge] 最终更新已发送，跳过")
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
        lines = ["QoderClaw 命令:", ""]
        for cmd, desc in self.commands_help.items():
            lines.append(f"  {self.command_prefix}{cmd} - {desc}")
        lines.extend(["", "直接发送文字消息即可与 Qoder 对话"])
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 图片处理
    # ------------------------------------------------------------------

    def _compress_image(self, data: bytes, mime: str, max_size: int = 51200) -> Optional[bytes]:
        """
        压缩图片以避免 Qoder 处理超时。

        Args:
            data: 原始图片数据
            mime: MIME 类型
            max_size: 最大目标大小（字节），默认 50KB

        Returns:
            压缩后的 JPEG 数据，如果无需压缩或失败返回 None
        """
        try:
            # 如果已经足够小，不压缩
            if len(data) <= max_size:
                logger.debug(f"[bridge] 图片无需压缩: {len(data)} bytes <= {max_size}")
                return None

            from io import BytesIO
            from PIL import Image

            # 打开图片
            img = Image.open(BytesIO(data))

            # 转换为 RGB（处理 PNG 透明通道等）
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            # 缩小尺寸（如果太大）
            max_dimension = 1024
            if max(img.width, img.height) > max_dimension:
                ratio = max_dimension / max(img.width, img.height)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)
                logger.debug(f"[bridge] 图片缩放: {img.width}x{img.height}")

            # 逐步降低质量直到满足大小要求
            output = BytesIO()
            quality = 85
            while quality >= 30:
                output.seek(0)
                output.truncate()
                img.save(output, format="JPEG", quality=quality)
                if output.tell() <= max_size:
                    break
                quality -= 10

            result = output.getvalue()
            logger.info(
                f"[bridge] 图片压缩: {len(data)} -> {len(result)} bytes "
                f"(quality={quality}, size={img.width}x{img.height})"
            )
            return result

        except Exception as e:
            logger.warning(f"[bridge] 图片压缩失败，使用原图: {e}")
            return None

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
