"""
主服务 - QoderClaw

- 启动时从 config.yaml 自动加载所有机器人和 Qoder 实例
- 飞书使用 WebSocket 长连接，无需公网 IP
- 提供 REST API 用于运行时管理
"""
import asyncio
import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from contextlib import asynccontextmanager

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from loguru import logger
import uvicorn

from adapters.base import BotConfig, BotStatus
from adapters.feishu import FeishuBotAdapter, FeishuPlatformManager
from qoder_manager import QoderConfig, get_process_manager, QoderStatus
from bridge_core import BridgeCore, get_bridge_core
from openai_compat import router as openai_router


# -----------------------------------------------------------------------------
# 从 config.yaml 加载配置并初始化
# -----------------------------------------------------------------------------

def load_yaml_config(path: str = "config.yaml") -> dict:
    if not os.path.exists(path):
        logger.warning(f"配置文件 {path} 不存在，使用空配置")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


async def init_from_config(bridge: BridgeCore) -> None:
    """从 config.yaml 注册所有 Qoder 实例和飞书机器人"""
    cfg = load_yaml_config()

    process_manager = get_process_manager()
    feishu_manager = FeishuPlatformManager()

    # 注册 Qoder 实例
    for name, raw in (cfg.get("qoder_instances") or {}).items():
        qcfg = QoderConfig(
            name=name,
            workdir=raw.get("workdir", os.path.expanduser("~")),
            cmd=raw.get("cmd", "qoder"),
            args=raw.get("args", []),
            auto_start=raw.get("auto_start", False),
            max_restarts=raw.get("max_restarts", 3),
        )
        process_manager.register_instance(qcfg)
        logger.info(f"已注册 Qoder 实例：{name}")

    # 启动标记 auto_start 的实例
    await process_manager.start_all()

    # 注册飞书机器人
    for bot_id, raw in (cfg.get("feishu_bots") or {}).items():
        if not raw.get("enabled", True):
            logger.info(f"跳过已禁用的机器人：{bot_id}")
            continue

        bot_cfg = BotConfig(
            id=bot_id,
            platform="feishu",
            name=bot_id,
            credentials={
                "app_id": raw["app_id"],
                "app_secret": raw["app_secret"],
                "verification_token": raw.get("verification_token", ""),
                "encrypt_key": raw.get("encrypt_key") or "",
            },
            enabled=True,
            qoder_instance=raw.get("qoder_instance", ""),
        )

        bot = await feishu_manager.register_bot(bot_cfg)
        bridge.register_bot(bot, raw.get("qoder_instance", ""))
        logger.info(
            f"已注册飞书机器人：{bot_id} → Qoder 实例：{raw.get('qoder_instance')}"
        )


# -----------------------------------------------------------------------------
# 应用生命周期
# -----------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("  QoderClaw 启动中...")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    bridge = get_bridge_core()

    # 加载配置并注册所有实例/机器人
    await init_from_config(bridge)

    # 启动所有机器人（建立飞书 WebSocket 连接）
    await bridge.start()

    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("  QoderClaw 启动完成 ✅")
    logger.info("  飞书机器人已主动连接到飞书服务器（无需公网 IP）")
    logger.info("  API 文档: http://localhost:8080/docs")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    yield

    logger.info("QoderClaw 正在关闭...")
    await bridge.stop()
    await get_process_manager().stop_all()


# -----------------------------------------------------------------------------
# FastAPI
# -----------------------------------------------------------------------------

app = FastAPI(
    title="QoderClaw",
    description="飞书机器人 ↔ Qoder 双向桥接器（WebSocket 模式，无需公网 IP）+ OpenAI 兼容 API",
    version="2.1.0",
    lifespan=lifespan,
)

# 注册 OpenAI 兼容路由
app.include_router(openai_router, tags=["OpenAI Compatible"])

# CORS（允许前端跨域访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------------
# Pydantic 模型
# -----------------------------------------------------------------------------

class CreateBotRequest(BaseModel):
    bot_id: str
    platform: str = "feishu"
    name: str
    app_id: str
    app_secret: str
    verification_token: str
    encrypt_key: Optional[str] = None
    qoder_instance: str


class CreateQoderRequest(BaseModel):
    name: str
    workdir: str
    cmd: str = "qoder"
    args: List[str] = []
    auto_start: bool = False


# -----------------------------------------------------------------------------
# 路由 - 状态
# -----------------------------------------------------------------------------

@app.get("/", summary="服务信息")
async def root():
    return {
        "service": "QoderClaw",
        "version": "2.0.0",
        "mode": "WebSocket（无需公网 IP）",
        "docs": "/docs",
    }


@app.get("/health", summary="健康检查")
async def health_check():
    process_manager = get_process_manager()
    bridge = get_bridge_core()

    qoder_health = await process_manager.health_check()

    bot_health = {}
    for bot_id, bot in bridge.bots.items():
        h = await bot.get_health_status()
        bot_health[bot_id] = {
            "status": h.status.value,
            "error": h.error_message,
            "details": h.details,
        }

    overall = "healthy"
    if any(b["status"] not in ("online",) for b in bot_health.values()):
        overall = "degraded"

    return {
        "status": overall,
        "qoder_instances": qoder_health,
        "bots": bot_health,
    }


# -----------------------------------------------------------------------------
# 路由 - 机器人管理
# -----------------------------------------------------------------------------

@app.get("/api/bots", summary="列出所有机器人")
async def list_bots():
    bridge = get_bridge_core()
    result = []
    for bot_id, bot in bridge.bots.items():
        h = await bot.get_health_status()
        result.append({
            "bot_id": bot_id,
            "platform": bot.platform_name,
            "status": h.status.value,
            "qoder_instance": bridge.bot_to_qoder_map.get(bot_id),
            "details": h.details,
        })
    return {"bots": result}


@app.delete("/api/bots/{bot_id}", summary="删除机器人")
async def delete_bot(bot_id: str):
    bridge = get_bridge_core()
    if bot_id not in bridge.bots:
        raise HTTPException(status_code=404, detail="Bot not found")
    await bridge.bots[bot_id].stop()
    del bridge.bots[bot_id]
    del bridge.bot_to_qoder_map[bot_id]
    return {"message": f"Bot {bot_id} deleted"}


# -----------------------------------------------------------------------------
# 路由 - Qoder 实例管理
# -----------------------------------------------------------------------------

@app.get("/api/qoder", summary="列出所有 Qoder 实例")
async def list_qoder():
    pm = get_process_manager()
    instances = []
    for name in pm.configs:
        status = pm.get_status(name)
        stats = pm.get_stats(name)
        instances.append({
            "name": name,
            "status": status.value if status else "unknown",
            "pid": stats.pid if stats else None,
            "cpu_percent": stats.cpu_percent if stats else 0,
            "memory_mb": stats.memory_mb if stats else 0,
            "uptime_seconds": stats.uptime_seconds if stats else None,
            "restart_count": pm.restart_counts.get(name, 0),
        })
    return {"instances": instances}


@app.post("/api/qoder/{name}/start", summary="启动 Qoder 实例")
async def start_qoder(name: str):
    pm = get_process_manager()
    if not await pm.start_instance(name):
        raise HTTPException(status_code=500, detail="Failed to start")
    return {"message": f"{name} started"}


@app.post("/api/qoder/{name}/stop", summary="停止 Qoder 实例")
async def stop_qoder(name: str):
    pm = get_process_manager()
    if not await pm.stop_instance(name):
        raise HTTPException(status_code=500, detail="Failed to stop")
    return {"message": f"{name} stopped"}


@app.post("/api/qoder/{name}/restart", summary="重启 Qoder 实例")
async def restart_qoder(name: str):
    pm = get_process_manager()
    if not await pm.restart_instance(name):
        raise HTTPException(status_code=500, detail="Failed to restart")
    return {"message": f"{name} restarted"}


# -----------------------------------------------------------------------------
# Qoder Sessions API（用于前端同步）
# -----------------------------------------------------------------------------

@app.get("/api/qoder-sessions", summary="列出所有 Qoder 会话")
async def list_qoder_sessions():
    """从 ~/.qoder/projects 目录读取所有会话"""
    sessions = []
    qoder_projects = Path.home() / ".qoder" / "projects"
    
    if not qoder_projects.exists():
        return {"sessions": sessions}
    
    for project_dir in qoder_projects.iterdir():
        if not project_dir.is_dir():
            continue
        for session_file in project_dir.glob("*-session.json"):
            try:
                with open(session_file, "r") as f:
                    data = json.load(f)
                session_id = session_file.stem.replace("-session", "")
                
                # 读取 jsonl 文件获取消息数量
                jsonl_file = project_dir / f"{session_id}.jsonl"
                message_count = 0
                if jsonl_file.exists():
                    with open(jsonl_file, "r") as f:
                        message_count = sum(1 for _ in f)
                
                sessions.append({
                    "id": session_id,
                    "title": data.get("title", "Untitled"),
                    "created_at": data.get("created_at", 0),
                    "updated_at": data.get("updated_at", 0),
                    "message_count": message_count,
                    "working_dir": data.get("working_dir", ""),
                    "has_transcript": jsonl_file.exists(),
                })
            except Exception as e:
                logger.warning(f"Failed to read session {session_file}: {e}")
    
    # 按更新时间倒序排序
    sessions.sort(key=lambda x: x["updated_at"], reverse=True)
    return {"sessions": sessions}


@app.get("/api/qoder-sessions/{session_id}/transcript", summary="获取会话消息历史")
async def get_qoder_transcript(session_id: str, limit: int = 0, offset: int = 0):
    """读取会话的 jsonl 文件，返回消息列表
    
    Args:
        session_id: 会话 ID
        limit: 限制返回数量，0 表示返回全部，负数表示返回最后 N 条
        offset: 跳过前 N 条消息（用于增量获取新消息）
    """
    qoder_projects = Path.home() / ".qoder" / "projects"
    
    for project_dir in qoder_projects.iterdir():
        if not project_dir.is_dir():
            continue
        jsonl_file = project_dir / f"{session_id}.jsonl"
        if jsonl_file.exists():
            break
    else:
        raise HTTPException(status_code=404, detail="Session not found")
    
    messages = []
    with open(jsonl_file, "r") as f:
        for line in f:
            try:
                data = json.loads(line)
                # 只提取用户和助手的文本消息
                if data.get("type") in ("user", "assistant"):
                    msg = data.get("message", {})
                    content = msg.get("content", "")
                    # 处理多部分内容
                    if isinstance(content, list):
                        text_parts = []
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                text_parts.append(part.get("text", ""))
                            elif isinstance(part, dict) and part.get("type") == "image":
                                # 将图片 base64 数据转为 data URL，嵌入 markdown
                                source = part.get("source", {})
                                b64_data = source.get("data", "")
                                media_type = source.get("media_type", "image/png")
                                if b64_data:
                                    data_url = f"data:{media_type};base64,{b64_data}"
                                    text_parts.append(f"![image]({data_url})")
                            elif isinstance(part, dict) and part.get("type") == "tool_use":
                                # 显示工具调用
                                tool_name = part.get("name", "unknown")
                                tool_input = part.get("input", {})
                                tool_desc = f"🛠️ **Tool**: `{tool_name}`"
                                if tool_input:
                                    tool_desc += f"\n```json\n{json.dumps(tool_input, ensure_ascii=False, indent=2)}\n```"
                                text_parts.append(tool_desc)
                            elif isinstance(part, dict) and part.get("type") == "tool_result":
                                # 显示工具结果
                                result_content = part.get("content", [])
                                if isinstance(result_content, list) and result_content:
                                    # 提取结果中的文本
                                    result_texts = []
                                    for rc in result_content:
                                        if isinstance(rc, dict) and rc.get("type") == "text":
                                            result_texts.append(rc.get("text", ""))
                                    if result_texts:
                                        text_parts.append("📤 **Result**:\n" + "\n".join(result_texts))
                                elif isinstance(result_content, str):
                                    text_parts.append(f"📤 **Result**: {result_content}")
                            elif isinstance(part, str):
                                text_parts.append(part)
                        content = "\n\n".join(text_parts)
                    
                    if content:
                        messages.append({
                            "role": msg.get("role", data["type"]),
                            "content": content,
                            "timestamp": data.get("timestamp", 0),
                        })
            except json.JSONDecodeError:
                continue
    
    total = len(messages)
    
    # offset 处理：跳过前 N 条，返回增量消息
    if offset > 0:
        messages = messages[offset:]
    
    # limit 处理
    if limit < 0:
        messages = messages[limit:]  # 最后 N 条
    elif limit > 0:
        messages = messages[:limit] if len(messages) > limit else messages
    
    return {"messages": messages, "total": total}


@app.delete("/api/qoder-sessions/{session_id}", summary="删除会话")
async def delete_qoder_session(session_id: str):
    """删除会话文件"""
    qoder_projects = Path.home() / ".qoder" / "projects"
    
    deleted = False
    for project_dir in qoder_projects.iterdir():
        if not project_dir.is_dir():
            continue
        for ext in ["-session.json", ".jsonl", ""]:
            if ext:
                file_path = project_dir / f"{session_id}{ext}"
            else:
                # 删除会话目录
                file_path = project_dir / session_id
            if file_path.exists():
                try:
                    if file_path.is_dir():
                        import shutil
                        shutil.rmtree(file_path)
                    else:
                        file_path.unlink()
                    deleted = True
                except Exception as e:
                    logger.warning(f"Failed to delete {file_path}: {e}")
    
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {"message": f"Session {session_id} deleted"}


# -----------------------------------------------------------------------------
# 入口
# -----------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="QoderClaw Service")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    # 切换到脚本所在目录，确保 config.yaml 等相对路径正确
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    os.makedirs("logs", exist_ok=True)
    logger.add(
        "logs/qoderclaw.log",
        rotation="10 MB",
        retention="7 days",
        level="DEBUG",
        encoding="utf-8",
    )

    logger.info(f"Starting QoderClaw on {args.host}:{args.port}")
    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
