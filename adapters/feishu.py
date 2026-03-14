"""
飞书平台适配器 - WebSocket 主动连接模式

使用飞书官方 SDK 的 WebSocket 长连接，无需公网 IP。
机器人主动连飞书服务器，和 OpenClaw 相同的原理。
"""
import asyncio
import json
import time
import threading
from typing import Optional, Dict, Any, Callable

import httpx
import lark_oapi as lark
from lark_oapi.ws import Client as LarkWSClient
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
from loguru import logger

from adapters.base import (
    BaseBotAdapter,
    BasePlatformManager,
    BotConfig,
    Message,
    MessageType,
    User,
    BotStatus,
    HealthStatus,
    MediaAttachment,
)


class FeishuBotAdapter(BaseBotAdapter):
    """
    飞书机器人适配器 - WebSocket 主动连接模式

    不需要公网 IP。由本服务主动连飞书 WebSocket 服务器接收事件，
    与 OpenClaw 使用相同的原理。
    """

    def __init__(self, config: BotConfig):
        super().__init__(config)
        self.app_id = config.credentials["app_id"]
        self.app_secret = config.credentials["app_secret"]
        self.verification_token = config.credentials.get("verification_token", "")
        self.encrypt_key = config.credentials.get("encrypt_key", "")

        self._ws_client: Optional[LarkWSClient] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._access_token: Optional[str] = None
        self._token_expire_at: float = 0
        self._bot_open_id: Optional[str] = None
        self._bot_name: Optional[str] = None
        self._last_heartbeat: float = time.time()

        # 消息去重：FIFO + TTL，参考 OpenClaw 的 MessageDedup
        self._seen_messages: Dict[str, float] = {}
        self._dedup_ttl_ms = 12 * 60 * 60 * 1000  # 12 小时

        # 持久化 HTTP 客户端（避免每次请求创建新连接）
        self._http_client: Optional[httpx.AsyncClient] = None

        # 主事件循环引用（用于从 WebSocket 线程投递消息）
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None

    # -------------------------------------------------------------------------
    # 生命周期
    # -------------------------------------------------------------------------

    async def start(self) -> None:
        """启动机器人 - 主动连接飞书 WebSocket 服务器"""
        try:
            self.status = BotStatus.CONNECTING
            logger.info(f"[{self.bot_id}] 正在启动飞书 WebSocket 连接...")

            # 记录主事件循环，后续从 WS 线程投递消息时使用
            self._main_loop = asyncio.get_running_loop()

            # 获取 access token，同时验证凭证是否正确
            await self._refresh_access_token()

            # 探测机器人身份
            await self._probe_bot_info()

            # 构建事件处理器
            handler = (
                EventDispatcherHandler.builder(
                    self.verification_token,
                    self.encrypt_key or "",
                )
                .register_p2_im_message_receive_v1(self._on_message_received_sdk)
                .build()
            )

            # 创建 WebSocket 客户端（auto_reconnect=True 自动重连）
            self._ws_client = LarkWSClient(
                app_id=self.app_id,
                app_secret=self.app_secret,
                event_handler=handler,
                auto_reconnect=True,
            )

            # 在独立线程中运行 WebSocket（SDK 使用同步阻塞 API）
            self._ws_thread = threading.Thread(
                target=self._run_ws,
                name=f"feishu-ws-{self.bot_id}",
                daemon=True,
            )
            self._ws_thread.start()

            # 稍等确认连接已建立
            await asyncio.sleep(2)

            self.status = BotStatus.ONLINE
            logger.info(
                f"[{self.bot_id}] 飞书 WebSocket 连接成功 "
                f"| 机器人：{self._bot_name} ({self._bot_open_id})"
            )

        except Exception as e:
            logger.error(f"[{self.bot_id}] 启动失败：{e}")
            self.status = BotStatus.ERROR
            raise

    def _run_ws(self):
        """在后台线程运行 WebSocket 客户端（阻塞）"""
        try:
            logger.info(f"[{self.bot_id}] WebSocket 线程启动")
            self._ws_client.start()
        except Exception as e:
            logger.error(f"[{self.bot_id}] WebSocket 线程异常：{e}")
            self.status = BotStatus.ERROR

    async def stop(self) -> None:
        """停止机器人"""
        logger.info(f"[{self.bot_id}] 正在停止...")
        self.status = BotStatus.STOPPED
        if self._ws_client:
            try:
                self._ws_client.stop()
            except Exception:
                pass
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        logger.info(f"[{self.bot_id}] 已停止")

    # -------------------------------------------------------------------------
    # 消息发送
    # -------------------------------------------------------------------------

    async def send_message(self, message: Message) -> Optional[str]:
        """发送消息到飞书，返回 message_id"""
        try:
            await self._ensure_access_token()

            # 分段发送超长消息
            content = message.content
            chunks = self._split_message(content)

            msg_id = None
            for chunk in chunks:
                msg_id = await self._send_chunk(
                    chunk,
                    message.conversation_id,
                    message.reply_to,
                )
                if not msg_id:
                    return None
                if len(chunks) > 1:
                    await asyncio.sleep(0.3)

            return msg_id

        except Exception as e:
            logger.error(f"[{self.bot_id}] 发送消息失败：{e}")
            return None

    async def _send_chunk(
        self,
        content: str,
        conversation_id: str,
        reply_to: Optional[str] = None,
    ) -> Optional[str]:
        """发送单段消息，返回 message_id"""
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "receive_id": conversation_id,
            "msg_type": "text",
            "content": json.dumps({"text": content}),
        }
        # 判断是 chat_id 还是 open_id
        if conversation_id.startswith("oc_"):
            params = {"receive_id_type": "chat_id"}
        else:
            params = {"receive_id_type": "open_id"}

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers=headers, json=payload, params=params)
            result = resp.json()

        if result.get("code") == 0:
            return result.get("data", {}).get("message_id")
        else:
            logger.error(f"[{self.bot_id}] 飞书 API 错误：{result}")
            return None

    async def send_card_message(
        self,
        content: str,
        conversation_id: str,
        title: str = "",
    ) -> Optional[str]:
        """发送卡片消息，返回 message_id（支持后续 PATCH 更新）"""
        try:
            await self._ensure_access_token()

            card = self._build_card(content, title)
            url = "https://open.feishu.cn/open-apis/im/v1/messages"
            headers = {
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            }
            payload = {
                "receive_id": conversation_id,
                "msg_type": "interactive",
                "content": json.dumps(card),
            }
            if conversation_id.startswith("oc_"):
                params = {"receive_id_type": "chat_id"}
            else:
                params = {"receive_id_type": "open_id"}

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, headers=headers, json=payload, params=params)
                result = resp.json()

            if result.get("code") == 0:
                return result.get("data", {}).get("message_id")
            else:
                logger.error(f"[{self.bot_id}] 发送卡片失败：{result}")
                return None

        except Exception as e:
            logger.error(f"[{self.bot_id}] 发送卡片异常：{e}")
            return None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """获取或创建持久化 HTTP 客户端"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=5)
        return self._http_client

    async def download_message_resource(
        self,
        message_id: str,
        file_key: str,
        resource_type: str = "file",
    ) -> Optional[bytes]:
        """
        下载飞书消息资源（图片、语音、文件等）

        Args:
            message_id: 消息 ID
            file_key: 资源 key（image_key 或 file_key）
            resource_type: "image" 或 "file"

        Returns:
            资源的二进制数据，失败返回 None
        """
        try:
            await self._ensure_access_token()

            url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/resources/{file_key}"
            headers = {
                "Authorization": f"Bearer {self._access_token}",
            }
            params = {"type": resource_type}

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code == 200:
                    return resp.content
                else:
                    logger.error(f"[{self.bot_id}] 下载资源失败: {resp.status_code} {resp.text[:200]}")
                    return None

        except Exception as e:
            logger.error(f"[{self.bot_id}] 下载资源异常: {e}")
            return None

    async def update_card_message(self, message_id: str, content: str, title: str = "") -> bool:
        """更新卡片消息内容（用于流式输出）"""
        try:
            await self._ensure_access_token()

            card = self._build_card(content, title)
            url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}"
            headers = {
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            }
            payload = {
                "msg_type": "interactive",
                "content": json.dumps(card),
            }

            logger.debug(f"[{self.bot_id}] PATCH 开始请求 len={len(content)}")
            client = await self._get_http_client()
            resp = await client.patch(url, headers=headers, json=payload)
            result = resp.json()

            if result.get("code") == 0:
                logger.debug(f"[{self.bot_id}] PATCH 成功 len={len(content)}")
                return True
            else:
                logger.warning(f"[{self.bot_id}] PATCH 失败：code={result.get('code')} msg={result.get('msg')} len={len(content)}")
                return False

        except Exception as e:
            logger.error(f"[{self.bot_id}] 更新卡片异常：{e}")
            # 客户端可能坏了，重置
            if self._http_client:
                try:
                    await self._http_client.aclose()
                except Exception:
                    pass
                self._http_client = None
            return False

    def _build_card(self, content: str, title: str = "") -> dict:
        """构建飞书卡片 JSON"""
        elements = [
            {
                "tag": "markdown",
                "content": content,
            }
        ]
        card = {
            "elements": elements,
        }
        if title:
            card["header"] = {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            }
        return card

    async def update_message(self, message_id: str, content: str) -> bool:
        """更新已发送消息的内容（用于流式输出）"""
        try:
            await self._ensure_access_token()

            url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}"
            headers = {
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            }
            payload = {
                "msg_type": "text",
                "content": json.dumps({"text": content}),
            }

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.patch(url, headers=headers, json=payload)
                result = resp.json()

            if result.get("code") == 0:
                return True
            else:
                logger.debug(f"[{self.bot_id}] 更新消息失败：{result.get('msg')}")
                return False

        except Exception as e:
            logger.error(f"[{self.bot_id}] 更新消息异常：{e}")
            return False

    def _split_message(self, content: str, max_len: int = 3000) -> list:
        """将超长消息拆分为多段"""
        if len(content) <= max_len:
            return [content]
        chunks = []
        while content:
            chunks.append(content[:max_len])
            content = content[max_len:]
        return chunks

    # -------------------------------------------------------------------------
    # 健康状态
    # -------------------------------------------------------------------------

    async def get_health_status(self) -> HealthStatus:
        """获取健康状态"""
        ws_alive = (
            self._ws_thread is not None and self._ws_thread.is_alive()
        )
        current_status = BotStatus.ONLINE if ws_alive else BotStatus.OFFLINE

        return HealthStatus(
            status=current_status,
            last_heartbeat=self._last_heartbeat,
            details={
                "bot_name": self._bot_name,
                "bot_open_id": self._bot_open_id,
                "ws_thread_alive": ws_alive,
                "app_id": self.app_id,
            },
        )

    # -------------------------------------------------------------------------
    # 消息接收回调
    # -------------------------------------------------------------------------

    def _on_message_received_sdk(self, event) -> None:
        """
        飞书 SDK 消息事件回调（在 WebSocket 线程中调用，只有一个参数 event）
        把事件桥接到 asyncio 事件循环处理
        """
        try:
            self._last_heartbeat = time.time()

            msg = event.event.message
            sender = event.event.sender

            msg_id = msg.message_id
            if not msg_id:
                return

            # 去重检查
            if self._is_duplicate(msg_id):
                logger.debug(f"[{self.bot_id}] 重复消息，跳过：{msg_id}")
                return

            # 过期检查（30 分钟内的消息才处理，防止重连后重放旧消息）
            create_time = int(msg.create_time or 0)
            if create_time and (time.time() * 1000 - create_time) > 30 * 60 * 1000:
                logger.debug(f"[{self.bot_id}] 消息已过期，跳过：{msg_id}")
                return

            # 解析消息内容和类型
            # 飞书 SDK 使用 message_type 属性
            msg_type = getattr(msg, 'message_type', None)
            if msg_type is None:
                # 尝试从 content JSON 推断
                try:
                    content_json = json.loads(msg.content or "{}")
                    # 飞书消息类型可能通过 content 结构推断
                    if 'image_key' in content_json:
                        msg_type = 'image'
                    elif 'file_key' in content_json and 'duration' in content_json:
                        msg_type = 'audio'
                    elif 'file_key' in content_json:
                        msg_type = 'media'
                    else:
                        msg_type = 'text'
                except Exception:
                    msg_type = 'text'

            content_json = {}
            text = ""
            media_list = []

            try:
                content_json = json.loads(msg.content or "{}")
            except Exception:
                pass

            # 根据消息类型解析
            if msg_type == "text":
                text = content_json.get("text", "").strip()
                # 去掉 @机器人 的部分
                if "@" in text:
                    import re
                    text = re.sub(r"@\S+\s*", "", text).strip()

            elif msg_type == "image":
                # 图片消息
                image_key = content_json.get("image_key", "")
                if image_key:
                    text = "[图片]"
                    media_list.append(MediaAttachment(
                        type="image",
                        file_key=image_key,
                    ))
                else:
                    text = "[图片]"

            elif msg_type == "audio":
                # 语音消息
                file_key = content_json.get("file_key", "")
                duration = content_json.get("duration", 0)
                if file_key:
                    text = f"[语音 {duration // 1000}秒]"
                    media_list.append(MediaAttachment(
                        type="audio",
                        file_key=file_key,
                        duration=duration,
                    ))
                else:
                    text = "[语音]"

            elif msg_type == "media":
                # 文件/视频消息
                file_key = content_json.get("file_key", "")
                file_name = content_json.get("file_name", "")
                if file_key:
                    text = f"[文件: {file_name}]" if file_name else "[文件]"
                    media_list.append(MediaAttachment(
                        type="file",
                        file_key=file_key,
                        filename=file_name,
                    ))
                else:
                    text = "[文件]"

            else:
                # 其他类型，尝试提取文本
                text = content_json.get("text", "").strip()
                if not text:
                    text = f"[{msg_type}]"

            if not text and not media_list:
                return

            # 构建统一消息对象
            user = User(
                id=sender.sender_id.open_id if sender.sender_id else "",
                name="",
                platform="feishu",
            )

            # 确定消息类型
            if media_list:
                if media_list[0].type == "image":
                    msg_type_enum = MessageType.IMAGE
                elif media_list[0].type == "audio":
                    msg_type_enum = MessageType.AUDIO
                else:
                    msg_type_enum = MessageType.FILE
            else:
                msg_type_enum = MessageType.TEXT

            unified_message = Message(
                id=msg_id,
                content=text,
                type=msg_type_enum,
                sender=user,
                conversation_id=msg.chat_id or "",
                timestamp=create_time / 1000 if create_time else time.time(),
                is_group=msg.chat_type == "group",
                raw_data={"event": str(event)},
                media=media_list,
            )

            logger.info(
                f"[{self.bot_id}] 收到消息 | "
                f"chat={unified_message.conversation_id} | "
                f"type={msg_type} | "
                f"text={text[:50]!r} | "
                f"media={len(media_list)}"
            )

            # 把消息投递到 asyncio 事件循环
            if self._main_loop and self._main_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.handle_incoming_message(unified_message), self._main_loop
                )
            else:
                logger.warning(f"[{self.bot_id}] 主事件循环不可用，无法投递消息")

        except Exception as e:
            logger.error(f"[{self.bot_id}] 处理消息事件异常：{e}", exc_info=True)

    # -------------------------------------------------------------------------
    # 辅助方法
    # -------------------------------------------------------------------------

    async def _refresh_access_token(self) -> None:
        """刷新 tenant_access_token"""
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url,
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
        result = resp.json()
        if result.get("code") != 0:
            raise RuntimeError(f"获取 access token 失败：{result}")
        self._access_token = result["tenant_access_token"]
        self._token_expire_at = time.time() + result["expire"] - 60
        logger.debug(f"[{self.bot_id}] access token 已刷新")

    async def _ensure_access_token(self) -> None:
        """确保 access token 有效"""
        if not self._access_token or time.time() > self._token_expire_at:
            await self._refresh_access_token()

    async def _probe_bot_info(self) -> None:
        """获取机器人自身信息"""
        url = "https://open.feishu.cn/open-apis/bot/v3/info"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {self._access_token}"},
            )
        result = resp.json()
        if result.get("code") == 0:
            bot = result.get("bot", {})
            self._bot_open_id = bot.get("open_id")
            self._bot_name = bot.get("app_name")
            logger.info(
                f"[{self.bot_id}] 机器人信息：{self._bot_name} ({self._bot_open_id})"
            )

    def _is_duplicate(self, msg_id: str) -> bool:
        """消息去重（FIFO + TTL，参考 OpenClaw MessageDedup）"""
        now_ms = time.time() * 1000
        # 清理过期记录
        cutoff = now_ms - self._dedup_ttl_ms
        expired = [k for k, v in self._seen_messages.items() if v < cutoff]
        for k in expired:
            del self._seen_messages[k]
        # 最多保留 5000 条
        if len(self._seen_messages) >= 5000:
            oldest = next(iter(self._seen_messages))
            del self._seen_messages[oldest]
        if msg_id in self._seen_messages:
            return True
        self._seen_messages[msg_id] = now_ms
        return False


# ---------------------------------------------------------------------------
# Platform Manager
# ---------------------------------------------------------------------------

class FeishuPlatformManager(BasePlatformManager):
    """飞书平台管理器"""

    def __init__(self):
        super().__init__()
        self.platform_name = "feishu"

    async def register_bot(self, config: BotConfig) -> BaseBotAdapter:
        adapter = FeishuBotAdapter(config)
        self.bots[config.id] = adapter
        logger.info(f"已注册飞书机器人：{config.id}")
        return adapter

    async def unregister_bot(self, bot_id: str) -> bool:
        if bot_id not in self.bots:
            return False
        await self.bots[bot_id].stop()
        del self.bots[bot_id]
        logger.info(f"已注销飞书机器人：{bot_id}")
        return True
