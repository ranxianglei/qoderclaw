"""
Qoder ACP 进程管理器

通过 ACP (Agent Client Protocol) 管理 Qoder 实例。
每个实例是一个 `qodercli --acp` 常驻进程，通过 stdin/stdout JSON-RPC 通信。
一个进程可以管理多个会话（session），无需为每条消息重启进程。
"""
import asyncio
import json
import os
import subprocess
from typing import Optional, Dict, List, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import time
from pathlib import Path
from loguru import logger
import uuid
from datetime import datetime


class QoderStatus(Enum):
    """Qoder 进程状态"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"
    RESTARTING = "restarting"
    CRASHED = "crashed"


@dataclass
class QoderConfig:
    """Qoder 实例配置"""
    name: str
    workdir: str
    cmd: str = "qodercli"
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    auto_start: bool = False
    max_restarts: int = 3
    restart_delay: float = 5.0


@dataclass
class ProcessStats:
    """进程统计信息"""
    pid: Optional[int] = None
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    status: str = "unknown"
    create_time: Optional[float] = None
    uptime_seconds: Optional[float] = None
    session_count: int = 0


class QoderAcpClient:
    """
    ACP 协议客户端 — 管理单个 qodercli --acp 常驻进程。

    协议流程：
    1. initialize → 协议握手
    2. session/new → 创建会话（每个飞书对话对应一个）
    3. session/prompt → 发送消息，流式收集响应
    4. session/cancel → 取消进行中的请求
    """

    def __init__(self, config: QoderConfig):
        self.config = config
        self.process: Optional[asyncio.subprocess.Process] = None
        self.sessions: Dict[str, str] = {}  # conversation_key → acp session_id
        self.cwd_map: Dict[str, str] = {}  # conversation_key → custom cwd
        self._initialized = False
        self._lock = asyncio.Lock()  # 保证写入 stdin 的串行化
        self._next_id = 1
        self._pending: Dict[int, asyncio.Future] = {}  # req_id → Future[result]
        self._prompt_texts: Dict[int, list] = {}  # req_id → [text_chunks]
        self._prompt_callbacks: Dict[int, Callable[[str], None]] = {}  # req_id → chunk callback
        self._seen_tool_calls: set = set()  # 去重 tool_call 通知
        self._reader_task: Optional[asyncio.Task] = None
        self._status = QoderStatus.STOPPED
        self._start_time: Optional[float] = None
        self._restart_count = 0

    @property
    def status(self) -> QoderStatus:
        return self._status

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> bool:
        """启动 qodercli --acp 进程并完成协议握手"""
        if self.process is not None and self.process.returncode is None:
            logger.warning(f"[{self.config.name}] 进程已在运行")
            return True

        try:
            self._status = QoderStatus.STARTING

            workdir = Path(self.config.workdir)
            workdir.mkdir(parents=True, exist_ok=True)

            cmd = [self.config.cmd] + self.config.args + ["--acp"]
            env = os.environ.copy()
            env.update(self.config.env)

            logger.info(f"[{self.config.name}] 启动 ACP 进程: {' '.join(cmd)}")

            # 使用超大 buffer size 避免大型 JSON 响应超过限制
            # asyncio StreamReader 的 limit 参数定义了 readline() 的单行最大字节数
            # 当 Qoder 返回大型工具调用结果时，JSON 可能非常长
            # 设置为 1GB (1024^3) 基本可以处理所有实际场景
            # 内存影响：这只是上限，实际只使用需要的内存
            BUFFER_SIZE = 1024 * 1024 * 1024  # 1GB
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(workdir),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=BUFFER_SIZE,
            )

            self._start_time = time.time()

            # 启动 stdout 读取协程
            self._reader_task = asyncio.create_task(self._read_stdout())

            # 启动 stderr 日志协程
            asyncio.create_task(self._read_stderr())

            # 协议握手
            resp = await self._rpc_call("initialize", {
                "protocolVersion": 1,
                "clientCapabilities": {},
            })

            if resp is None:
                logger.error(f"[{self.config.name}] ACP 握手失败")
                await self.stop()
                self._status = QoderStatus.ERROR
                return False

            self._initialized = True
            self._status = QoderStatus.RUNNING
            logger.info(
                f"[{self.config.name}] ACP 握手成功 | PID={self.process.pid} | "
                f"capabilities={json.dumps(resp.get('agentCapabilities', {}), ensure_ascii=False)[:100]}"
            )
            return True

        except Exception as e:
            logger.error(f"[{self.config.name}] 启动失败: {e}")
            self._status = QoderStatus.ERROR
            return False

    async def stop(self) -> bool:
        """停止 ACP 进程"""
        if self.process is None:
            self._status = QoderStatus.STOPPED
            return True

        try:
            logger.info(f"[{self.config.name}] 正在停止 ACP 进程 (PID={self.process.pid})")

            # 关闭 stdin 触发进程优雅退出
            if self.process.stdin and not self.process.stdin.is_closing():
                self.process.stdin.close()

            try:
                await asyncio.wait_for(self.process.wait(), timeout=10)
            except asyncio.TimeoutError:
                logger.warning(f"[{self.config.name}] 进程未响应，强制终止")
                self.process.kill()
                await self.process.wait()

            # 取消所有等待中的请求
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(RuntimeError("ACP process stopped"))
            self._pending.clear()
            self._prompt_texts.clear()

            if self._reader_task and not self._reader_task.done():
                self._reader_task.cancel()

            self.process = None
            self._initialized = False
            self.sessions.clear()
            self._status = QoderStatus.STOPPED
            logger.info(f"[{self.config.name}] 已停止")
            return True

        except Exception as e:
            logger.error(f"[{self.config.name}] 停止失败: {e}")
            return False

    async def restart(self) -> bool:
        """重启 ACP 进程"""
        self._restart_count += 1
        if self._restart_count > self.config.max_restarts:
            logger.error(f"[{self.config.name}] 已超过最大重启次数 ({self.config.max_restarts})")
            self._status = QoderStatus.CRASHED
            return False

        self._status = QoderStatus.RESTARTING
        await self.stop()
        await asyncio.sleep(self.config.restart_delay)
        return await self.start()

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------

    async def get_or_create_session(self, conversation_key: str, cwd: str = None) -> Optional[str]:
        """获取或创建 ACP 会话，返回 session_id
        
        Args:
            conversation_key: 会话标识符
            cwd: 工作目录，如果提供则覆盖配置中的默认目录
        """
        if conversation_key in self.sessions:
            return self.sessions[conversation_key]

        # 优先级: 传入的 cwd > cwd_map 中保存的 > 配置的默认值
        workdir = cwd or self.cwd_map.get(conversation_key) or self.config.workdir
        
        resp = await self._rpc_call("session/new", {
            "cwd": workdir,
        })

        if resp is None:
            logger.error(f"[{self.config.name}] 创建会话失败: {conversation_key}")
            return None

        session_id = resp.get("sessionId")
        if not session_id:
            logger.error(f"[{self.config.name}] 响应中无 sessionId: {resp}")
            return None

        self.sessions[conversation_key] = session_id
        logger.info(f"[{self.config.name}] 新建会话: {conversation_key} → {session_id} (cwd={workdir})")
        return session_id

    async def destroy_session(self, conversation_key: str) -> bool:
        """销毁会话（用于 /forget 命令）"""
        session_id = self.sessions.pop(conversation_key, None)
        if not session_id:
            return False
        # ACP 没有显式的 session destroy 方法，只需从映射中移除
        # 下次该 conversation 来消息时会创建新会话
        logger.info(f"[{self.config.name}] 已销毁会话: {conversation_key} ({session_id})")
        return True

    # ------------------------------------------------------------------
    # 命令处理
    # ------------------------------------------------------------------

    async def _handle_command(self, conversation_key: str, text: str) -> Optional[str]:
        """
        处理命令。支持两种方式：
        1. 斜杠命令：/model lite, /mode architect, /forget, /help, /cd /path
        2. 自然语言：切换模型为lite, 使用lite模型, switch to lite model

        返回命令执行结果，如果不是命令则返回 None。
        """
        # 去除 OpenClaw 的 sender metadata 前缀
        clean_text = self._strip_openclaw_metadata(text).strip()
        if not clean_text:
            return None

        # 尝试斜杠命令
        if clean_text.startswith("/"):
            return await self._handle_slash_command(conversation_key, clean_text)

        # 尝试自然语言命令
        return await self._handle_natural_command(conversation_key, clean_text)

    @staticmethod
    def _strip_openclaw_metadata(text: str) -> str:
        """去除 OpenClaw 在消息前注入的 'Sender (untrusted metadata):\n```json\n{...}\n```\n' 前缀"""
        import re
        # 匹配 OpenClaw 的 metadata 块：Sender (...):```json{...}```
        pattern = r'^Sender\s*\(.*?\):\s*```json\s*\{[^}]*\}\s*```\s*'
        cleaned = re.sub(pattern, '', text, count=1, flags=re.DOTALL)
        return cleaned

    async def _handle_slash_command(self, conversation_key: str, text: str) -> Optional[str]:
        """处理 / 开头的命令"""
        parts = text.split(None, 1)
        command = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""

        # 获取 session_id（可能不存在）
        session_id = self.sessions.get(conversation_key)

        if command == "/model":
            return await self._do_switch_model(session_id, args)
        elif command == "/mode":
            return await self._do_switch_mode(session_id, args)
        elif command == "/forget":
            return self._do_forget(conversation_key)
        elif command == "/cd":
            return self._do_cd(conversation_key, args)
        elif command == "/help":
            return self._do_help()
        else:
            return f"未知命令: {command}\n输入 /help 查看可用命令"

    async def _handle_natural_command(self, conversation_key: str, text: str) -> Optional[str]:
        """处理自然语言命令。返回 None 表示不是命令，交给 AI 处理。"""
        import re
        t = text.lower().strip()
        session_id = self.sessions.get(conversation_key)

        # 模型切换：匹配 "切换模型为lite" / "使用lite模型" / "switch to lite" 等
        model_patterns = [
            r'(?:切换|更换|换|改|设置|使用|选择).*?模型.*?(?:为|到|成|用)?\s*(\w+)',
            r'(?:switch|change|set|use)\s+(?:model\s+(?:to\s+)?)?(\w+)\s*(?:model)?',
            r'(?:模型|model)\s*(?:切换|换|改|设置|to|=|:)\s*(\w+)',
            r'(?:用|使用|切换到?)\s*(\w+)\s*模型',
        ]
        valid_models = {'lite', 'efficient', 'performance', 'ultimate', 'auto',
                        'gmodel', 'kmodel', 'mmodel', 'qmodel', 'q35model'}
        for pattern in model_patterns:
            m = re.search(pattern, t)
            if m:
                model_id = m.group(1).strip()
                if model_id in valid_models:
                    return await self._do_switch_model(session_id, model_id)

        # 模式切换
        mode_patterns = [
            r'(?:切换|更换|换|改|设置|使用).*?模式.*?(?:为|到|成|用)?\s*(\w+)',
            r'(?:switch|change|set|use)\s+(?:mode\s+(?:to\s+)?)?(\w+)\s*mode',
            r'(?:用|使用|切换到?)\s*(\w+)\s*模式',
        ]
        for pattern in mode_patterns:
            m = re.search(pattern, t)
            if m:
                mode_id = m.group(1).strip()
                if mode_id and len(mode_id) < 30:
                    return await self._do_switch_mode(session_id, mode_id)

        # 清除历史
        if re.search(r'清[除空].*?(?:会话|历史|记录|对话)|(?:forget|clear|reset)\s*(?:session|history|chat)', t):
            return self._do_forget(conversation_key)

        return None

    async def _do_switch_model(self, session_id: str, model_id: str) -> str:
        if not model_id:
            return "用法: /model <modelId>\n可用模型: lite, efficient, performance, ultimate, auto"
        resp = await self._rpc_call("session/set_model", {
            "sessionId": session_id,
            "modelId": model_id,
        }, timeout=10)
        if resp is not None:
            logger.info(f"[{self.config.name}] 模型已切换: {model_id}")
            return f"模型已切换为: {model_id}"
        return "切换模型失败"

    async def _do_switch_mode(self, session_id: str, mode_id: str) -> str:
        if not mode_id:
            return "用法: /mode <modeId>"
        resp = await self._rpc_call("session/set_mode", {
            "sessionId": session_id,
            "modeId": mode_id,
        }, timeout=10)
        if resp is not None:
            logger.info(f"[{self.config.name}] 模式已切换: {mode_id}")
            return f"模式已切换为: {mode_id}"
        return "切换模式失败"

    def _do_forget(self, conversation_key: str) -> str:
        self.sessions.pop(conversation_key, None)
        self.cwd_map.pop(conversation_key, None)
        return "会话历史已清除，下次发消息将开启新会话"

    def _do_cd(self, conversation_key: str, path: str) -> str:
        """切换工作目录。下次发消息时创建新 session 使用新目录"""
        if not path:
            current = self.cwd_map.get(conversation_key) or self.config.workdir
            return f"当前工作目录: {current}"

        expanded = os.path.expanduser(path)
        expanded = os.path.abspath(expanded)

        if not os.path.isdir(expanded):
            return f"目录不存在: {expanded}"

        # 保存新 cwd，并销毁旧 session（下次会用新目录创建新 session）
        self.cwd_map[conversation_key] = expanded
        self.sessions.pop(conversation_key, None)
        logger.info(f"[{self.config.name}] 工作目录切换: {conversation_key} → {expanded}")
        return f"工作目录已切换为: {expanded}\n（已重置会话，下次消息将在新目录中开启新会话）"

    @staticmethod
    def _do_help() -> str:
        return """可用命令（斜杠或自然语言均可）:

/model <modelId> - 切换模型
  可用: lite, efficient, performance, ultimate, auto
  或直接说: 切换模型为lite / switch to lite model

/mode <modeId> - 切换模式

/cd <path> - 切换工作目录（下次消息生效）
  例如: /cd /home/ubuntu/myproject

/forget - 清除当前会话历史
  或直接说: 清除会话历史 / clear history

/help - 显示此帮助"""

    # ------------------------------------------------------------------
    # 发送消息
    # ------------------------------------------------------------------

    def _get_project_session_path(self, conversation_key: str) -> Path:
        """获取会话对应的 jsonl 文件路径"""
        # 使用 conversation_key 作为项目标识符
        project_name = conversation_key.replace("/", "_").replace("\\", "_")
        projects_dir = Path.home() / ".qoder" / "projects"
        session_file = projects_dir / project_name / f"{conversation_key}.jsonl"
        session_file.parent.mkdir(parents=True, exist_ok=True)
        return session_file

    def _write_message_to_transcript(self, conversation_key: str, role: str, content: str, 
                                   message_id: Optional[str] = None, parent_id: Optional[str] = None):
        """将消息写入 jsonl 转录文件"""
        try:
            session_file = self._get_project_session_path(conversation_key)
            
            # 生成消息元数据
            timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            msg_uuid = str(uuid.uuid4())
            
            # 构造消息内容
            message_content = []
            if isinstance(content, str):
                message_content = [{"type": "text", "text": content}]
            elif isinstance(content, list):
                message_content = content
            else:
                message_content = [{"type": "text", "text": str(content)}]
            
            # 构造完整的消息对象
            message_obj = {
                "uuid": msg_uuid,
                "parentUuid": parent_id or "",
                "isSidechain": False,
                "userType": "external",
                "cwd": str(Path.cwd()),
                "sessionId": conversation_key,  # 使用 conversation_key 作为 session ID
                "version": "0.1.32",  # 匹配 worktree 模式版本
                "agentId": "75a2f788",  # 示例 agent ID
                "type": role,
                "timestamp": timestamp,
                "message": {
                    "role": role,
                    "content": message_content,
                    "id": message_id or str(uuid.uuid4())
                },
                "isMeta": False
            }
            
            # 写入 jsonl 文件
            with open(session_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(message_obj, ensure_ascii=False) + '\n')
                
            logger.debug(f"[{self.config.name}] 消息已写入转录: {session_file} | {role}: {content[:50]}...")
            
        except Exception as e:
            logger.warning(f"[{self.config.name}] 写入转录失败: {e}")


    async def cancel_task(self, conversation_key: str) -> bool:
        """取消指定会话的正在运行的任务。
        
        Args:
            conversation_key: 会话标识
            
        Returns:
            bool: 是否成功取消
        """
        session_id = self.sessions.get(conversation_key)
        
        # 如果 session 还在创建中，等待一下再试
        if not session_id:
            logger.debug(f"[{self.config.name}] 会话不在缓存中，尝试直接取消：{conversation_key}")
            # 给一点时间让 send_prompt 完成 session 创建
            await asyncio.sleep(0.5)
            session_id = self.sessions.get(conversation_key)
            
            if not session_id:
                # 仍然不存在，可能是并发问题或者 session 已经结束
                logger.info(f"[{self.config.name}] 会话仍未找到，跳过取消：{conversation_key}")
                return False
        
        logger.info(f"[{self.config.name}] 取消任务：{conversation_key} (session={session_id})")
        
        try:
            # 发送 ACP session/cancel 请求
            resp = await self._rpc_call("session/cancel", {
                "sessionId": session_id
            }, timeout=30)
            
            if resp is not None:
                logger.info(f"[{self.config.name}] 任务已取消：{conversation_key}")
                return True
            else:
                logger.warning(f"[{self.config.name}] 取消失败：{conversation_key}")
                return False
                
        except asyncio.TimeoutError:
            logger.error(f"[{self.config.name}] 取消超时：{conversation_key}")
            return False
        except Exception as e:
            logger.error(f"[{self.config.name}] 取消异常：{e}")
            return False

    async def send_prompt(
        self,
        conversation_key: str,
        text: str,
        timeout: float = 21600,
        on_chunk: Optional[Callable[[str], None]] = None,
        media_parts: Optional[List[dict]] = None,
        cwd: str = None,  # 新增参数
    ) -> Optional[str]:
        """
        向指定会话发送消息并等待完整回复。

        Args:
            text: 文本内容
            on_chunk: 可选回调，每收到一个文本块立即调用（用于流式输出）
            media_parts: 可选的多模态内容块列表，格式如 [{"type": "image", "data": bytes, "mime": "image/png"}, ...]
            cwd: 工作目录，如果提供则在创建会话时使用

        返回 AI 的完整文本回复，超时或失败返回 None。
        """
        session_id = await self.get_or_create_session(conversation_key, cwd)
        if not session_id:
            return None

        # 解析并处理特殊命令（以 / 开头）
        command_result = await self._handle_command(conversation_key, text)
        if command_result is not None:
            # 命令已被处理，返回结果
            return command_result

        # 写入用户消息到转录文件
        user_msg_id = str(uuid.uuid4())
        self._write_message_to_transcript(conversation_key, "user", text, user_msg_id)

        req_id = self._next_id
        self._prompt_texts[req_id] = []
        if on_chunk:
            self._prompt_callbacks[req_id] = on_chunk

        # 构建 prompt 内容
        prompt_content = []

        # 添加多模态内容（ACP 扁平格式）
        if media_parts:
            import base64
            for part in media_parts:
                if part.get("type") == "image" and part.get("data"):
                    b64_data = base64.b64encode(part["data"]).decode("utf-8")
                    mime = part.get("mime", "image/png")
                    prompt_content.append({
                        "type": "image",
                        "mimeType": mime,
                        "data": b64_data,
                    })
                    logger.debug(
                        f"[{self.config.name}] 图片已编码: "
                        f"mime={mime} raw={len(part['data'])}B b64={len(b64_data)}B"
                    )

        # 添加文本内容
        if text:
            prompt_content.append({"type": "text", "text": text})

        try:
            resp = await self._rpc_call("session/prompt", {
                "sessionId": session_id,
                "prompt": prompt_content,
                "cwd": cwd or self.config.workdir,  # 传入 cwd
            }, timeout=timeout)

            self._prompt_callbacks.pop(req_id, None)

            # 收集所有文本块
            chunks = self._prompt_texts.pop(req_id, [])
            full_text = "".join(chunks).strip()

            if resp is not None and full_text:
                # 写入助手回复到转录文件
                assistant_msg_id = str(uuid.uuid4())
                self._write_message_to_transcript(conversation_key, "assistant", full_text, 
                                                assistant_msg_id, user_msg_id)
                
                logger.debug(
                    f"[{self.config.name}] 回复 ({conversation_key}): "
                    f"{full_text[:80]}{'...' if len(full_text) > 80 else ''}"
                )
                return full_text

            if resp is not None and not full_text:
                logger.warning(f"[{self.config.name}] 回复为空 ({conversation_key})")
                return None

            return None

        except asyncio.TimeoutError:
            logger.error(f"[{self.config.name}] 请求超时 ({timeout}s): {conversation_key}")
            self._prompt_texts.pop(req_id, None)
            self._prompt_callbacks.pop(req_id, None)
            return None
        except Exception as e:
            logger.error(f"[{self.config.name}] 请求失败: {e}")
            self._prompt_texts.pop(req_id, None)
            self._prompt_callbacks.pop(req_id, None)
            return None

    # ------------------------------------------------------------------
    # JSON-RPC 底层通信
    # ------------------------------------------------------------------

    async def _rpc_call(self, method: str, params: dict, timeout: float = 120) -> Optional[dict]:
        """发送 JSON-RPC 请求并等待响应"""
        if not self.process or self.process.returncode is not None:
            logger.error(f"[{self.config.name}] 进程未运行，无法调用 {method}")
            return None

        async with self._lock:
            req_id = self._next_id
            self._next_id += 1

            msg = json.dumps({
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params,
            }, ensure_ascii=False)

            # 创建 Future
            loop = asyncio.get_running_loop()
            future = loop.create_future()
            self._pending[req_id] = future

            # 写入 stdin
            try:
                self.process.stdin.write((msg + "\n").encode("utf-8"))
                await self.process.stdin.drain()
            except Exception as e:
                self._pending.pop(req_id, None)
                logger.error(f"[{self.config.name}] 写入失败: {e}")
                return None

        # 等待响应（在 lock 外等待，避免死锁）
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise
        except Exception as e:
            self._pending.pop(req_id, None)
            raise

    async def _read_stdout(self) -> None:
        """持续读取 stdout，分发 JSON-RPC 响应和通知"""
        try:
            while self.process and self.process.returncode is None:
                line = await self.process.stdout.readline()
                if not line:
                    break

                text = line.decode("utf-8", errors="ignore").strip()
                if not text:
                    continue

                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    logger.debug(f"[{self.config.name}] 非JSON输出: {text[:100]}")
                    continue

                # 区分三种消息类型：
                # 1. 来自 Qoder 的请求（有 id + method）→ 需要回复
                # 2. 我方请求的响应（有 id，无 method）→ 匹配 pending future
                # 3. 通知（无 id，有 method）→ 处理通知
                has_id = "id" in msg and msg["id"] is not None
                has_method = "method" in msg

                # 来自 Qoder 的请求（如 session/request_permission）
                if has_id and has_method:
                    await self._handle_incoming_request(msg)
                    continue

                # JSON-RPC 响应（有 id 字段，无 method）
                if has_id:
                    req_id = msg["id"]
                    future = self._pending.pop(req_id, None)
                    if future and not future.done():
                        if "error" in msg:
                            future.set_exception(
                                RuntimeError(f"ACP error: {msg['error'].get('message', msg['error'])}")
                            )
                        else:
                            future.set_result(msg.get("result", {}))
                    continue

                # JSON-RPC 通知（无 id，有 method）
                if has_method:
                    self._handle_notification(msg)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[{self.config.name}] stdout 读取异常: {e}")

        # 进程退出后处理
        if self._status == QoderStatus.RUNNING:
            logger.warning(f"[{self.config.name}] ACP 进程意外退出")
            self._status = QoderStatus.CRASHED
            # 通知所有等待中的请求
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(RuntimeError("ACP process crashed"))
            self._pending.clear()

    async def _read_stderr(self) -> None:
        """读取 stderr 日志"""
        try:
            while self.process and self.process.returncode is None:
                line = await self.process.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="ignore").strip()
                if text:
                    logger.debug(f"[{self.config.name}|stderr] {text}")
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _handle_incoming_request(self, msg: dict) -> None:
        """处理来自 Qoder 的 JSON-RPC 请求（如权限确认）"""
        method = msg.get("method", "")
        req_id = msg["id"]
        params = msg.get("params", {})

        if method == "session/request_permission":
            # 自动批准所有工具执行请求（类似 --yolo 模式）
            tool_call = params.get("toolCall", {})
            title = tool_call.get("title", "unknown")
            tool_name = params.get("_meta", {}).get("ai-coding/tool-name", "unknown")

            logger.info(
                f"[{self.config.name}] 自动批准工具执行: "
                f"{tool_name} - {title}"
            )

            # 回复 allow_always，让本会话内后续同类工具不再询问
            # ACP schema 要求 outcome 包装：outcome.outcome="selected" + outcome.optionId
            await self._send_rpc_response(req_id, {
                "outcome": {
                    "outcome": "selected",
                    "optionId": "allow_always",
                },
            })
        else:
            logger.warning(
                f"[{self.config.name}] 收到未知请求: {method} (id={req_id})"
            )

    async def _send_rpc_response(self, req_id: int, result: dict) -> None:
        """向 Qoder 发送 JSON-RPC 响应"""
        if not self.process or self.process.returncode is not None:
            logger.error(f"[{self.config.name}] 进程未运行，无法发送响应")
            return

        msg = json.dumps({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result,
        }, ensure_ascii=False)

        async with self._lock:
            try:
                self.process.stdin.write((msg + "\n").encode("utf-8"))
                await self.process.stdin.drain()
                logger.debug(f"[{self.config.name}] 已发送响应: id={req_id}")
            except Exception as e:
                logger.error(f"[{self.config.name}] 发送响应失败: {e}")

    def _handle_notification(self, msg: dict) -> None:
        """处理 ACP 通知消息"""
        method = msg.get("method", "")
        params = msg.get("params", {})

        if method == "session/update":
            update = params.get("update", {})
            update_type = update.get("sessionUpdate", "")

            # 记录所有 update 类型用于调试
            logger.debug(f"[{self.config.name}] session/update type={update_type}")

            # 收集文本流
            if update_type == "agent_message_chunk":
                content = update.get("content", {})
                if isinstance(content, dict) and content.get("type") == "text":
                    chunk_text = content.get("text", "")
                    if chunk_text:
                        chunk_time = time.time()
                        # 找到正在等待的 prompt 请求，追加文本并调用回调
                        for req_id in list(self._prompt_texts.keys()):
                            self._prompt_texts[req_id].append(chunk_text)
                            total = "".join(self._prompt_texts[req_id])
                            logger.debug(
                                f"[{self.config.name}] chunk @{chunk_time:.3f} "
                                f"len={len(chunk_text)} total={len(total)} "
                                f"text={chunk_text!r}"
                            )
                            callback = self._prompt_callbacks.get(req_id)
                            if callback:
                                try:
                                    callback(chunk_text)
                                except Exception as e:
                                    logger.error(f"[{self.config.name}] chunk callback error: {e}")

            # 工具调用事件 → 格式化为文本推送给前端
            elif update_type == "tool_call":
                tool_call_id = update.get("toolCallId", "")
                dedup_key = f"call:{tool_call_id}"
                if dedup_key in self._seen_tool_calls:
                    return  # 去重
                self._seen_tool_calls.add(dedup_key)
                # ACP 格式: title="`echo hello`", rawInput={command:..., description:...}, kind="execute"
                title = update.get("title", "")
                raw_input = update.get("rawInput", {})
                # 从 rawInput 推断工具名称
                tool_name = "Bash" if "command" in raw_input else \
                            "Edit" if "file_path" in raw_input and "old_string" in raw_input else \
                            "Read" if "file_path" in raw_input and "old_string" not in raw_input else \
                            "Write" if "content" in raw_input and "file_path" in raw_input else \
                            "Grep" if "pattern" in raw_input else \
                            "Glob" if "pattern" in raw_input and "glob" in str(raw_input).lower() else \
                            title or "Tool"
                formatted = f"\n\n🛠️ **Tool**: `{tool_name}`\n```json\n{json.dumps(raw_input, ensure_ascii=False, indent=2)}\n```\n\n"
                for req_id in list(self._prompt_texts.keys()):
                    self._prompt_texts[req_id].append(formatted)
                    callback = self._prompt_callbacks.get(req_id)
                    if callback:
                        try:
                            callback(formatted)
                        except Exception as e:
                            logger.error(f"[{self.config.name}] tool_call callback error: {e}")

            elif update_type == "tool_call_update":
                tool_call_id = update.get("toolCallId", "")
                dedup_key = f"update:{tool_call_id}"
                if dedup_key in self._seen_tool_calls:
                    return  # 去重
                self._seen_tool_calls.add(dedup_key)
                # ACP 格式: rawOutput=[{content: "...", exitCode: 0, ...}], content=[{content:{text:...}}]
                result_text = ""
                # 优先从 rawOutput 获取（更原始）
                raw_output = update.get("rawOutput", [])
                if isinstance(raw_output, list) and raw_output:
                    parts = []
                    for item in raw_output:
                        if isinstance(item, dict) and item.get("content"):
                            parts.append(str(item["content"]))
                    result_text = "\n".join(parts)
                # 回退到 content 字段
                if not result_text:
                    content_list = update.get("content", [])
                    if isinstance(content_list, list):
                        for item in content_list:
                            if isinstance(item, dict):
                                inner = item.get("content", {})
                                if isinstance(inner, dict) and inner.get("text"):
                                    result_text = inner["text"]
                                    break
                if result_text:
                    if len(result_text) > 2000:
                        result_text = result_text[:2000] + "\n...(truncated)"
                    formatted = f"\n\n📤 **Result**:\n```\n{result_text}\n```\n\n"
                    for req_id in list(self._prompt_texts.keys()):
                        self._prompt_texts[req_id].append(formatted)
                        callback = self._prompt_callbacks.get(req_id)
                        if callback:
                            try:
                                callback(formatted)
                            except Exception as e:
                                logger.error(f"[{self.config.name}] tool_call_update callback error: {e}")
        # 其他通知类型静默忽略

    def get_stats(self) -> Optional[ProcessStats]:
        """获取进程统计"""
        if not self.process or self.process.returncode is not None:
            return None

        try:
            import psutil
            ps = psutil.Process(self.process.pid)
            ct = ps.create_time()
            return ProcessStats(
                pid=self.process.pid,
                cpu_percent=ps.cpu_percent(),
                memory_mb=ps.memory_info().rss / 1024 / 1024,
                status=ps.status(),
                create_time=ct,
                uptime_seconds=time.time() - ct,
                session_count=len(self.sessions),
            )
        except Exception:
            return ProcessStats(
                pid=self.process.pid,
                session_count=len(self.sessions),
            )


class QoderProcessManager:
    """
    Qoder 进程管理器（ACP 模式）

    管理多个 QoderAcpClient 实例，每个对应一个 qodercli --acp 常驻进程。
    """

    def __init__(self):
        self.configs: Dict[str, QoderConfig] = {}
        self.clients: Dict[str, QoderAcpClient] = {}

    def register_instance(self, config: QoderConfig) -> None:
        """注册 Qoder 实例"""
        self.configs[config.name] = config
        self.clients[config.name] = QoderAcpClient(config)
        logger.info(f"Registered Qoder instance: {config.name}")

    def get_client(self, name: str) -> Optional[QoderAcpClient]:
        """获取 ACP 客户端"""
        return self.clients.get(name)

    def get_status(self, name: str) -> Optional[QoderStatus]:
        """获取实例状态"""
        client = self.clients.get(name)
        return client.status if client else None

    def get_stats(self, name: str) -> Optional[ProcessStats]:
        """获取进程统计"""
        client = self.clients.get(name)
        return client.get_stats() if client else None

    async def start_instance(self, name: str) -> bool:
        """启动实例"""
        client = self.clients.get(name)
        if not client:
            logger.error(f"Qoder instance not found: {name}")
            return False
        return await client.start()

    async def stop_instance(self, name: str) -> bool:
        """停止实例"""
        client = self.clients.get(name)
        if not client:
            return False
        return await client.stop()

    async def restart_instance(self, name: str) -> bool:
        """重启实例"""
        client = self.clients.get(name)
        if not client:
            return False
        return await client.restart()

    async def start_all(self) -> None:
        """启动所有自动启动的实例"""
        for name, config in self.configs.items():
            if config.auto_start:
                await self.start_instance(name)

    async def stop_all(self) -> None:
        """停止所有实例"""
        tasks = [client.stop() for client in self.clients.values()]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def health_check(self) -> Dict[str, Dict[str, Any]]:
        """健康检查"""
        results = {}
        for name, client in self.clients.items():
            stats = client.get_stats()
            results[name] = {
                "status": client.status.value,
                "pid": stats.pid if stats else None,
                "cpu_percent": stats.cpu_percent if stats else 0,
                "memory_mb": stats.memory_mb if stats else 0,
                "uptime_seconds": stats.uptime_seconds if stats else 0,
                "session_count": stats.session_count if stats else 0,
                "restart_count": client._restart_count,
            }
        return results


# 全局管理器实例
_manager: Optional[QoderProcessManager] = None


def get_process_manager() -> QoderProcessManager:
    global _manager
    if _manager is None:
        _manager = QoderProcessManager()
    return _manager
