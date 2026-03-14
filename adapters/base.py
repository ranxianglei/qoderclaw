"""
平台抽象层 - 定义统一的机器人接口

所有 IM 平台适配器都需要实现这些接口
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from enum import Enum
import time
import uuid


class MessageType(Enum):
    """消息类型枚举"""
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    FILE = "file"
    LINK = "link"
    CARD = "card"  # 富文本卡片
    COMMAND = "command"  # 控制命令


class BotStatus(Enum):
    """机器人状态"""
    ONLINE = "online"
    OFFLINE = "offline"
    CONNECTING = "connecting"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class User:
    """用户对象"""
    id: str
    name: str
    platform: str
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MediaAttachment:
    """媒体附件"""
    type: str  # "image", "audio", "file"
    file_key: str  # 飞书的 file_key 或 image_key
    data: Optional[bytes] = None  # 下载后的二进制数据
    content_type: Optional[str] = None  # MIME 类型
    filename: Optional[str] = None
    duration: Optional[int] = None  # 音频时长（毫秒）


@dataclass
class Message:
    """统一消息对象"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    type: MessageType = MessageType.TEXT
    sender: Optional[User] = None
    receiver: Optional[User] = None
    conversation_id: str = ""  # 会话 ID（群聊或私聊）
    timestamp: float = field(default_factory=time.time)
    raw_data: Dict[str, Any] = field(default_factory=dict)

    # 元数据
    is_group: bool = False
    mentions: List[str] = field(default_factory=list)
    reply_to: Optional[str] = None  # 回复的消息 ID

    # 媒体附件
    media: List[MediaAttachment] = field(default_factory=list)

    # 扩展字段（用于传递平台特定信息）
    extras: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BotConfig:
    """机器人配置"""
    id: str
    platform: str
    name: str
    credentials: Dict[str, Any]
    enabled: bool = True
    qoder_instance: Optional[str] = None


@dataclass
class HealthStatus:
    """健康状态"""
    status: BotStatus
    last_heartbeat: float = field(default_factory=time.time)
    error_message: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


class BaseBotAdapter(ABC):
    """
    机器人适配器基类
    
    所有平台适配器都需要继承此类并实现抽象方法
    """
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.bot_id = config.id
        self.platform_name = config.platform
        self._status = BotStatus.OFFLINE
        self._message_handler: Optional[Callable[[Message], None]] = None
        self._status_handler: Optional[Callable[[BotStatus], None]] = None
    
    @abstractmethod
    async def start(self) -> None:
        """启动机器人连接"""
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """停止机器人连接"""
        pass
    
    @abstractmethod
    async def send_message(self, message: Message) -> bool:
        """发送消息"""
        pass
    
    @abstractmethod
    async def get_health_status(self) -> HealthStatus:
        """获取健康状态"""
        pass
    
    @property
    def status(self) -> BotStatus:
        """获取当前状态"""
        return self._status
    
    @status.setter
    def status(self, value: BotStatus):
        """设置状态并触发回调"""
        old_status = self._status
        self._status = value
        if self._status_handler and old_status != value:
            self._status_handler(value)
    
    def on_message(self, handler: Callable[[Message], None]) -> None:
        """注册消息处理器"""
        self._message_handler = handler
    
    def on_status_change(self, handler: Callable[[BotStatus], None]) -> None:
        """注册状态变化回调"""
        self._status_handler = handler
    
    async def handle_incoming_message(self, message: Message) -> None:
        """处理接收到的消息（由子类调用）"""
        if self._message_handler:
            await self._message_handler(message)
    
    def create_text_message(
        self,
        content: str,
        conversation_id: str,
        reply_to: Optional[str] = None
    ) -> Message:
        """创建文本消息"""
        return Message(
            content=content,
            type=MessageType.TEXT,
            conversation_id=conversation_id,
            reply_to=reply_to
        )
    
    def create_command_message(
        self,
        command: str,
        args: List[str],
        conversation_id: str
    ) -> Message:
        """创建命令消息"""
        return Message(
            content=f"{command} {' '.join(args)}",
            type=MessageType.COMMAND,
            conversation_id=conversation_id,
            extras={"command": command, "args": args}
        )


class BasePlatformManager(ABC):
    """
    平台管理器基类
    
    负责管理某个平台的所有机器人实例
    """
    
    def __init__(self):
        self.bots: Dict[str, BaseBotAdapter] = {}
    
    @abstractmethod
    async def register_bot(self, config: BotConfig) -> BaseBotAdapter:
        """注册一个新的机器人"""
        pass
    
    @abstractmethod
    async def unregister_bot(self, bot_id: str) -> bool:
        """注销一个机器人"""
        pass
    
    def get_bot(self, bot_id: str) -> Optional[BaseBotAdapter]:
        """获取机器人实例"""
        return self.bots.get(bot_id)
    
    def list_bots(self) -> List[str]:
        """列出所有机器人 ID"""
        return list(self.bots.keys())
