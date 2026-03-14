"""
主服务 - Qoder Bridge

- 启动时从 config.yaml 自动加载所有机器人和 Qoder 实例
- 飞书使用 WebSocket 长连接，无需公网 IP
- 提供 REST API 用于运行时管理
"""
import asyncio
import os
from typing import Dict, List, Optional
from contextlib import asynccontextmanager

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from loguru import logger
import uvicorn

from adapters.base import BotConfig, BotStatus
from adapters.feishu import FeishuBotAdapter, FeishuPlatformManager
from qoder_manager import QoderConfig, get_process_manager, QoderStatus
from bridge_core import BridgeCore, get_bridge_core


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
    logger.info("  Qoder Bridge 启动中...")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    bridge = get_bridge_core()

    # 加载配置并注册所有实例/机器人
    await init_from_config(bridge)

    # 启动所有机器人（建立飞书 WebSocket 连接）
    await bridge.start()

    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("  Qoder Bridge 启动完成 ✅")
    logger.info("  飞书机器人已主动连接到飞书服务器（无需公网 IP）")
    logger.info("  API 文档: http://localhost:8080/docs")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    yield

    logger.info("Qoder Bridge 正在关闭...")
    await bridge.stop()
    await get_process_manager().stop_all()


# -----------------------------------------------------------------------------
# FastAPI
# -----------------------------------------------------------------------------

app = FastAPI(
    title="Qoder Bridge",
    description="飞书机器人 ↔ Qoder 双向桥接器（WebSocket 模式，无需公网 IP）",
    version="2.0.0",
    lifespan=lifespan,
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
        "service": "Qoder Bridge",
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
# 入口
# -----------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Qoder Bridge Service")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    os.makedirs("logs", exist_ok=True)
    logger.add(
        "logs/qoder_bridge.log",
        rotation="10 MB",
        retention="7 days",
        level="DEBUG",
        encoding="utf-8",
    )

    logger.info(f"Starting Qoder Bridge on {args.host}:{args.port}")
    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
