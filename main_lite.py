"""
简化版 QoderClaw 主服务 - 只包含 OpenAI 兼容 API
用于测试消息持久化功能
"""
import os
import json
from pathlib import Path
from typing import List, Optional
import asyncio
import uuid
from datetime import datetime

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from loguru import logger

from openai_compat import router as openai_router

# API Key 配置
QODERCLAW_API_KEY = os.getenv("QODERCLAW_API_KEY", "sk-qoderclaw")

security = HTTPBearer()

async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> bool:
    if credentials.credentials != QODERCLAW_API_KEY:
        logger.warning(f"Invalid API key attempt: {credentials.credentials[:10]}...")
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return True

# FastAPI 应用
app = FastAPI(
    title="QoderClaw Lite",
    description="简化版 QoderClaw 服务 - OpenAI 兼容 API",
    version="1.0.0",
)

# 注册 OpenAI 兼容路由
app.include_router(openai_router, tags=["OpenAI Compatible"])

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 健康检查端点
@app.get("/")
async def root():
    return {
        "service": "QoderClaw Lite",
        "version": "1.0.0",
        "docs": "/docs",
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/api/auth/test", dependencies=[Depends(verify_api_key)])
async def test_auth(credentials: HTTPAuthorizationCredentials = Security(security)):
    return {
        "status": "ok",
        "message": "Authentication successful",
        "api_key_prefix": credentials.credentials[:8] + "...",
    }

# 简化的 Qoder Sessions API
@app.get("/api/qoder-sessions", dependencies=[Depends(verify_api_key)])
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
                        for line in f:
                            try:
                                entry = json.loads(line)
                                if entry.get("type") in ("user", "assistant"):
                                    msg = entry.get("message", {})
                                    content = msg.get("content", "")
                                    if isinstance(content, list):
                                        has_content = any(
                                            (isinstance(p, dict) and p.get("type") in ("text", "image", "tool_use", "tool_result"))
                                            or isinstance(p, str)
                                            for p in content
                                        )
                                        if has_content:
                                            message_count += 1
                                    elif content:
                                        message_count += 1
                            except json.JSONDecodeError:
                                continue
                
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

@app.get("/api/qoder-sessions/{session_id}/transcript", dependencies=[Depends(verify_api_key)])
async def get_qoder_transcript(session_id: str, limit: int = 0, offset: int = 0, count_only: bool = False):
    """读取会话的 jsonl 文件，返回消息列表"""
    qoder_projects = Path.home() / ".qoder" / "projects"
    
    for project_dir in qoder_projects.iterdir():
        if not project_dir.is_dir():
            continue
        jsonl_file = project_dir / f"{session_id}.jsonl"
        if jsonl_file.exists():
            break
    else:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # count_only 模式
    if count_only:
        count = 0
        with open(jsonl_file, "r") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if data.get("type") in ("user", "assistant"):
                        msg = data.get("message", {})
                        content = msg.get("content", "")
                        if isinstance(content, list):
                            has_content = False
                            for part in content:
                                if isinstance(part, str) and part.strip():
                                    has_content = True
                                    break
                                if isinstance(part, dict):
                                    ptype = part.get("type")
                                    if ptype == "text" and part.get("text", "").strip():
                                        has_content = True
                                        break
                                    elif ptype == "image" and part.get("source", {}).get("data"):
                                        has_content = True
                                        break
                                    elif ptype == "tool_use":
                                        has_content = True
                                        break
                                    elif ptype == "tool_result":
                                        rc = part.get("content", [])
                                        if isinstance(rc, str) and rc.strip():
                                            has_content = True
                                            break
                                        if isinstance(rc, list) and any(
                                            isinstance(r, dict) and r.get("type") == "text" and r.get("text", "").strip()
                                            for r in rc
                                        ):
                                            has_content = True
                                            break
                            if has_content:
                                count += 1
                        elif content and content.strip():
                            count += 1
                except json.JSONDecodeError:
                    continue
        return {"messages": [], "total": count}
    
    messages = []
    with open(jsonl_file, "r") as f:
        for line in f:
            try:
                data = json.loads(line)
                if data.get("type") in ("user", "assistant"):
                    msg = data.get("message", {})
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        text_parts = []
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                text_parts.append(part.get("text", ""))
                            elif isinstance(part, dict) and part.get("type") == "image":
                                source = part.get("source", {})
                                b64_data = source.get("data", "")
                                media_type = source.get("media_type", "image/png")
                                if b64_data:
                                    data_url = f"data:{media_type};base64,{b64_data}"
                                    text_parts.append(f"![image]({data_url})")
                            elif isinstance(part, dict) and part.get("type") == "tool_use":
                                tool_name = part.get("name", "unknown")
                                tool_input = part.get("input", {})
                                tool_desc = f"🛠️ **Tool**: `{tool_name}`"
                                if tool_input:
                                    tool_desc += f"\n```json\n{json.dumps(tool_input, ensure_ascii=False, indent=2)}\n```"
                                text_parts.append(tool_desc)
                            elif isinstance(part, dict) and part.get("type") == "tool_result":
                                result_content = part.get("content", [])
                                if isinstance(result_content, list) and result_content:
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
                        role = msg.get("role", data["type"])
                        messages.append({
                            "role": role,
                            "content": content,
                            "timestamp": data.get("timestamp", 0),
                        })
            except json.JSONDecodeError:
                continue
    
    total = len(messages)
    
    if offset > 0:
        messages = messages[offset:]
    
    if limit < 0:
        messages = messages[limit:]
    elif limit > 0:
        messages = messages[:limit] if len(messages) > limit else messages
    
    return {"messages": messages, "total": total}

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="QoderClaw Lite Service")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    logger.info(f"Starting QoderClaw Lite on {args.host}:{args.port}")
    uvicorn.run(
        "main_lite:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )