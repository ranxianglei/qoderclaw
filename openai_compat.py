"""
OpenAI 兼容 API 层

实现 /v1/chat/completions 和 /v1/models，
让任何 OpenAI 兼容前端（open-webui、lobe-chat 等）直接对接 QoderClaw。
"""
import asyncio
import base64
import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from bridge_core import BridgeCore, get_bridge_core
from qoder_manager import get_process_manager, QoderStatus

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic 模型（OpenAI 格式）
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str
    content: Any  # str 或 list[{"type": "text"/"image_url", ...}]
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: str = "qoder"
    messages: List[ChatMessage]
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _gen_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex[:12]}"


def _extract_content(messages: List[ChatMessage]) -> tuple[str, list]:
    """
    从 OpenAI messages 中提取最后一条用户消息的文本和图片。

    OpenAI 格式中 content 可以是：
    - 字符串: "Hello"
    - 数组: [{"type": "text", "text": "..."}, {"type": "image_url", "image_url": {"url": "data:..."}}]
    """
    text_parts = []
    media_parts = []

    # 取最后一条 user 消息
    last_user = None
    for msg in reversed(messages):
        if msg.role == "user":
            last_user = msg
            break

    if not last_user:
        return "", []

    content = last_user.content

    if isinstance(content, str):
        return content, []

    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
                elif part.get("type") == "image_url":
                    image_url = part.get("image_url", {})
                    url = image_url.get("url", "") if isinstance(image_url, dict) else ""
                    # 解析 data:image/png;base64,xxx 格式
                    match = re.match(r"data:(image/\w+);base64,(.+)", url, re.DOTALL)
                    if match:
                        mime = match.group(1)
                        b64_data = match.group(2)
                        try:
                            raw = base64.b64decode(b64_data)
                            media_parts.append({
                                "type": "image",
                                "data": raw,
                                "mime": mime,
                            })
                        except Exception as e:
                            logger.warning(f"[openai] base64 解码失败: {e}")

    return " ".join(text_parts), media_parts


def _compress_image_if_needed(data: bytes, mime: str, max_size: int = 51200) -> tuple[bytes, str]:
    """压缩大图片，复用 bridge_core 的逻辑"""
    if len(data) <= max_size:
        return data, mime
    try:
        from io import BytesIO
        from PIL import Image

        img = Image.open(BytesIO(data))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        max_dim = 1024
        if max(img.width, img.height) > max_dim:
            ratio = max_dim / max(img.width, img.height)
            img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)

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
        logger.info(f"[openai] 图片压缩: {len(data)} -> {len(result)} bytes")
        return result, "image/jpeg"
    except Exception as e:
        logger.warning(f"[openai] 图片压缩失败: {e}")
        return data, mime


# ---------------------------------------------------------------------------
# GET /v1/models
# ---------------------------------------------------------------------------

@router.get("/v1/models")
async def list_models():
    """返回可用模型列表"""
    pm = get_process_manager()
    models = []
    for name, client in pm.clients.items():
        models.append({
            "id": name,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "qoderclaw",
        })
    # 始终返回一个默认模型
    if not models:
        models.append({
            "id": "qoder",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "qoderclaw",
        })
    return {"object": "list", "data": models}


# ---------------------------------------------------------------------------
# POST /v1/chat/completions
# ---------------------------------------------------------------------------

@router.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest, request: Request):
    """OpenAI 兼容的 chat completions 接口"""
    pm = get_process_manager()

    # 选择 Qoder 实例
    model_name = req.model
    client = pm.get_client(model_name)
    if not client:
        # 回退到第一个可用实例
        client = next(iter(pm.clients.values()), None)
        if client:
            model_name = client.config.name

    if not client or client.status != QoderStatus.RUNNING:
        return _error_response(503, "No running Qoder instance available")

    # 从请求头获取 session ID（可选）
    session_key = request.headers.get("x-session-id", f"web-{uuid.uuid4().hex[:8]}")

    # 提取文本和图片
    text, media_parts = _extract_content(req.messages)
    if not text and not media_parts:
        return _error_response(400, "Empty message")

    # 压缩图片
    compressed_media = []
    for part in media_parts:
        data, mime = _compress_image_if_needed(part["data"], part["mime"])
        compressed_media.append({"type": "image", "data": data, "mime": mime})

    logger.info(
        f"[openai] 请求: session={session_key} text={text[:50]!r} "
        f"images={len(compressed_media)} stream={req.stream}"
    )

    completion_id = _gen_id()
    created = int(time.time())

    if req.stream:
        return StreamingResponse(
            _stream_response(
                client, session_key, text, compressed_media,
                completion_id, created, model_name,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        # 非流式：等待完整回复
        reply = await client.send_prompt(
            session_key, text, timeout=300,
            media_parts=compressed_media if compressed_media else None,
        )
        return {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": model_name,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": reply or "",
                },
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }


async def _stream_response(
    client, session_key: str, text: str, media_parts: list,
    completion_id: str, created: int, model: str,
):
    """生成 SSE 流式响应"""
    chunk_queue: asyncio.Queue = asyncio.Queue()
    done_event = asyncio.Event()

    def on_chunk(chunk_text: str):
        chunk_queue.put_nowait(chunk_text)

    # 在后台任务中发送 prompt
    async def _send():
        try:
            await client.send_prompt(
                session_key, text, timeout=300,
                on_chunk=on_chunk,
                media_parts=media_parts if media_parts else None,
            )
        except Exception as e:
            logger.error(f"[openai] stream prompt error: {e}")
        finally:
            done_event.set()

    task = asyncio.create_task(_send())

    # 发送 role chunk
    yield _sse_chunk(completion_id, created, model, {"role": "assistant"})

    # 流式输出文本
    while True:
        # 尝试从队列取 chunk
        try:
            chunk_text = await asyncio.wait_for(chunk_queue.get(), timeout=0.1)
            yield _sse_chunk(completion_id, created, model, {"content": chunk_text})
        except asyncio.TimeoutError:
            if done_event.is_set():
                # 排空队列
                while not chunk_queue.empty():
                    chunk_text = chunk_queue.get_nowait()
                    yield _sse_chunk(completion_id, created, model, {"content": chunk_text})
                break

    # 发送完成标记
    yield _sse_chunk(completion_id, created, model, {}, finish_reason="stop")
    yield "data: [DONE]\n\n"

    await task


def _sse_chunk(
    completion_id: str, created: int, model: str,
    delta: dict, finish_reason: Optional[str] = None,
) -> str:
    """构造 SSE 数据块"""
    chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{
            "index": 0,
            "delta": delta,
            "finish_reason": finish_reason,
        }],
    }
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


def _error_response(status_code: int, message: str):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": message,
                "type": "server_error",
                "code": status_code,
            }
        },
    )
