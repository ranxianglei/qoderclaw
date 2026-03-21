import logging
import os
import time
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer(auto_error=False)

QODERCLAW_BASE_URL = os.environ.get("OPENAI_API_BASE_URL", "http://localhost:8080/v1").replace("/v1", "")
QODERCLAW_API_KEY = os.environ.get("OPENAI_API_KEY", "")


def get_admin_user_id(db_path: str) -> str:
    """Get the first admin user ID from the database."""
    import sqlite3
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT id FROM \"user\" WHERE role = 'admin' ORDER BY created_at ASC LIMIT 1")
        row = cur.fetchone()
        conn.close()
        if row:
            return row[0]
    except Exception:
        pass
    return ""


async def optional_auth(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Optional authentication - allows access with or without valid token."""
    return credentials


@router.get("/sessions", dependencies=[Depends(optional_auth)])
async def get_qoder_sessions():
    """Get all QoderClaw sessions."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{QODERCLAW_BASE_URL}/api/qoder-sessions",
            headers={"Authorization": f"Bearer {QODERCLAW_API_KEY}"},
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Failed to fetch sessions")
        return resp.json()


@router.get("/sessions/{session_id}/transcript", dependencies=[Depends(optional_auth)])
async def get_qoder_session_transcript(session_id: str):
    """Get transcript for a specific QoderClaw session."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{QODERCLAW_BASE_URL}/api/qoder-sessions/{session_id}/transcript",
            headers={"Authorization": f"Bearer {QODERCLAW_API_KEY}"},
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Failed to fetch transcript")
        return resp.json()


@router.get("/sessions/{session_id}/stream", dependencies=[Depends(optional_auth)])
async def stream_qoder_session(session_id: str):
    """SSE proxy for real-time session streaming."""
    
    async def event_generator():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "GET",
                f"{QODERCLAW_BASE_URL}/api/qoder-sessions/{session_id}/stream",
                headers={"Authorization": f"Bearer {QODERCLAW_API_KEY}"},
            ) as response:
                if response.status_code != 200:
                    yield f"event: error\ndata: {{\"error\": \"Failed to connect\"}}\n\n"
                    return
                async for chunk in response.aiter_text():
                    yield chunk
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.post("/import-session/{session_id}", dependencies=[Depends(optional_auth)])
async def import_qoder_session(session_id: str):
    """
    Import a QoderClaw session into Open WebUI's database.
    Uses the QoderClaw session_id as the Open WebUI chat_id so that
    x-session-id header forwarding works correctly.
    """
    import json
    import sqlite3

    # 1. Fetch session info
    async with httpx.AsyncClient(timeout=10) as client:
        sess_resp = await client.get(
            f"{QODERCLAW_BASE_URL}/api/qoder-sessions",
            headers={"Authorization": f"Bearer {QODERCLAW_API_KEY}"},
        )
        if sess_resp.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to fetch sessions")
        sessions_data = sess_resp.json()
        session_info = None
        for s in sessions_data.get("sessions", []):
            if s["id"] == session_id:
                session_info = s
                break
        if not session_info:
            raise HTTPException(status_code=404, detail="Session not found")

    # 2. Fetch transcript
    async with httpx.AsyncClient(timeout=30) as client:
        trans_resp = await client.get(
            f"{QODERCLAW_BASE_URL}/api/qoder-sessions/{session_id}/transcript",
            headers={"Authorization": f"Bearer {QODERCLAW_API_KEY}"},
        )
        if trans_resp.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to fetch transcript")
        transcript = trans_resp.json()

    messages = transcript.get("messages", [])
    title = session_info.get("title", "Qoder Session")

    # 3. Build Open WebUI chat structure
    now = int(time.time())
    history_messages = {}
    messages_array = []
    prev_id = None

    for i, msg in enumerate(messages):
        msg_id = str(uuid.uuid4())
        role = msg.get("role", "assistant")
        content = msg.get("content", "")
        ts_str = msg.get("timestamp", "")

        # Parse timestamp
        try:
            from datetime import datetime
            if isinstance(ts_str, str) and ts_str:
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                ts = int(dt.timestamp())
            else:
                ts = now - len(messages) + i
        except Exception:
            ts = now - len(messages) + i

        msg_obj = {
            "id": msg_id,
            "parentId": prev_id,
            "childrenIds": [],
            "role": role,
            "content": content,
            "timestamp": ts,
        }

        if role == "user":
            msg_obj["models"] = ["default-assistant"]
        elif role == "assistant":
            msg_obj["model"] = "default-assistant"
            msg_obj["modelName"] = "default-assistant"
            msg_obj["modelIdx"] = 0
            msg_obj["done"] = True

        # Link parent to this child
        if prev_id and prev_id in history_messages:
            history_messages[prev_id]["childrenIds"].append(msg_id)

        history_messages[msg_id] = msg_obj
        messages_array.append(msg_obj)
        prev_id = msg_id

    # Get the last message ID for currentId
    current_id = prev_id

    chat_json = {
        "id": "",
        "title": title,
        "models": ["default-assistant"],
        "params": {},
        "history": {
            "messages": history_messages,
            "currentId": current_id,
        },
        "messages": messages_array,
        "tags": [],
        "timestamp": now,
        "files": [],
    }

    # 4. Write to Open WebUI database
    db_path = "/app/backend/data/webui.db"
    user_id = get_admin_user_id(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        # Check if chat already exists
        cur.execute("SELECT id FROM chat WHERE id = ?", (session_id,))
        existing = cur.fetchone()

        if existing:
            # Update existing chat
            cur.execute(
                "UPDATE chat SET chat = ?, title = ?, updated_at = ? WHERE id = ?",
                (json.dumps(chat_json, ensure_ascii=False), title, now, session_id)
            )
            # Delete old chat_messages for this chat
            cur.execute("DELETE FROM chat_message WHERE chat_id = ?", (session_id,))
        else:
            # Insert new chat
            cur.execute(
                "INSERT INTO chat (id, user_id, title, chat, meta, archived, pinned, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, user_id, title,
                 json.dumps(chat_json, ensure_ascii=False),
                 json.dumps({"tags": []}),
                 0, 0, now, now)
            )

        # Insert chat_message records
        for msg_obj in messages_array:
            cm_id = f"{session_id}-{msg_obj['id']}"
            role = msg_obj["role"]
            content = json.dumps(msg_obj.get("content", ""), ensure_ascii=False)
            parent_id = msg_obj.get("parentId")
            model_id = msg_obj.get("model") if role == "assistant" else None
            ts = msg_obj.get("timestamp", now)

            output = "null"
            if role == "assistant":
                output = json.dumps([{
                    "type": "message",
                    "id": f"imported-{msg_obj['id']}",
                    "status": "completed",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": msg_obj.get("content", "")}]
                }], ensure_ascii=False)

            cur.execute(
                """INSERT OR REPLACE INTO chat_message
                   (id, chat_id, user_id, role, parent_id, content, output, model_id,
                    files, sources, embeds, done, status_history, error, usage,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'null', 'null', 'null', 1, 'null', 'null', 'null', ?, ?)""",
                (cm_id, session_id, user_id, role, parent_id,
                 content, output, model_id, ts, ts)
            )

        conn.commit()
    except Exception as e:
        conn.rollback()
        log.exception(f"Failed to import session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to import session: {str(e)}")
    finally:
        conn.close()

    return {
        "status": "ok",
        "chat_id": session_id,
        "message_count": len(messages_array),
        "title": title,
    }
