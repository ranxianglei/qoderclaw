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
        self._initialized = False
        self._lock = asyncio.Lock()  # 保证写入 stdin 的串行化
        self._next_id = 1
        self._pending: Dict[int, asyncio.Future] = {}  # req_id → Future[result]
        self._prompt_texts: Dict[int, list] = {}  # req_id → [text_chunks]
        self._prompt_callbacks: Dict[int, Callable[[str], None]] = {}  # req_id → chunk callback
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

            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(workdir),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
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

    async def get_or_create_session(self, conversation_key: str) -> Optional[str]:
        """获取或创建 ACP 会话，返回 session_id"""
        if conversation_key in self.sessions:
            return self.sessions[conversation_key]

        resp = await self._rpc_call("session/new", {
            "cwd": self.config.workdir,
        })

        if resp is None:
            logger.error(f"[{self.config.name}] 创建会话失败: {conversation_key}")
            return None

        session_id = resp.get("sessionId")
        if not session_id:
            logger.error(f"[{self.config.name}] 响应中无 sessionId: {resp}")
            return None

        self.sessions[conversation_key] = session_id
        logger.info(f"[{self.config.name}] 新建会话: {conversation_key} → {session_id}")
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
    # 发送消息
    # ------------------------------------------------------------------

    async def send_prompt(
        self,
        conversation_key: str,
        text: str,
        timeout: float = 120,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> Optional[str]:
        """
        向指定会话发送消息并等待完整回复。

        Args:
            on_chunk: 可选回调，每收到一个文本块立即调用（用于流式输出）

        返回 AI 的完整文本回复，超时或失败返回 None。
        """
        session_id = await self.get_or_create_session(conversation_key)
        if not session_id:
            return None

        req_id = self._next_id
        self._prompt_texts[req_id] = []
        if on_chunk:
            self._prompt_callbacks[req_id] = on_chunk

        try:
            resp = await self._rpc_call("session/prompt", {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": text}],
            }, timeout=timeout)

            self._prompt_callbacks.pop(req_id, None)

            # 收集所有文本块
            chunks = self._prompt_texts.pop(req_id, [])
            full_text = "".join(chunks).strip()

            if resp is not None and full_text:
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
            loop = asyncio.get_event_loop()
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

                # JSON-RPC 响应（有 id 字段）
                if "id" in msg and msg["id"] is not None:
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
                if "method" in msg:
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

    def _handle_notification(self, msg: dict) -> None:
        """处理 ACP 通知消息"""
        method = msg.get("method", "")
        params = msg.get("params", {})

        if method == "session/update":
            update = params.get("update", {})
            update_type = update.get("sessionUpdate", "")

            # 收集文本流
            if update_type == "agent_message_chunk":
                content = update.get("content", {})
                if isinstance(content, dict) and content.get("type") == "text":
                    chunk_text = content.get("text", "")
                    if chunk_text:
                        # 找到正在等待的 prompt 请求，追加文本并调用回调
                        for req_id in list(self._prompt_texts.keys()):
                            self._prompt_texts[req_id].append(chunk_text)
                            callback = self._prompt_callbacks.get(req_id)
                            if callback:
                                try:
                                    callback(chunk_text)
                                except Exception as e:
                                    logger.error(f"[{self.config.name}] chunk callback error: {e}")
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
