import asyncio
import base64
import json
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src import knowledge, metrics, orchestrator
from src.sarvam import bulbul, saaras, translate as translate_mod, vision, live_stt

app = FastAPI()

SESSION_DIR = Path(__file__).parent.parent / "sessions"
SESSION_DIR.mkdir(exist_ok=True)
SESSION_TIMEOUT_SECONDS = 30 * 60


def _session_path(session_id):
    return SESSION_DIR / f"{session_id}.json"


def _load_session(session_id):
    path = _session_path(session_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="session not found")
    with open(path, encoding="utf-8") as f:
        session = json.load(f)
    if time.time() - session["last_active"] > SESSION_TIMEOUT_SECONDS:
        raise HTTPException(status_code=410, detail="session expired")
    return session


def _save_session(session):
    session["last_active"] = time.time()
    with open(_session_path(session["session_id"]), "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)


@app.post("/session")
def create_session():
    session_id = str(uuid.uuid4())
    session = {
        "session_id": session_id,
        "created_at": time.time(),
        "last_active": time.time(),
        "language": None,
        "language_override": None,
        "messages": [],
        "audit_log": [],
        "thumbs_up": None,
    }
    _save_session(session)
    return {"session_id": session_id}


@app.get("/session/{session_id}")
def session_status(session_id: str):
    session = _load_session(session_id)
    return {
        "session_id": session_id,
        "language": session.get("language"),
        "language_override": session.get("language_override"),
        "active_claim_id": session.get("active_claim_id"),
        "last_grievance": session.get("last_grievance"),
    }


@app.post("/session/{session_id}/feedback")
def submit_feedback(session_id: str, thumbs_up: bool = Form(...)):
    session = _load_session(session_id)
    session["thumbs_up"] = thumbs_up
    _save_session(session)
    return {"thumbs_up": thumbs_up}


@app.get("/metrics")
def get_metrics():
    return metrics.compute_metrics()


@app.post("/turn")
async def turn(session_id: str = Form(...), audio: UploadFile = None):
    session = _load_session(session_id)
    audio_bytes = await audio.read()

    try:
        stt_result = saaras.transcribe(audio_bytes)
        transcript = stt_result["transcript"].strip()
    except Exception:
        transcript = ""

    if not transcript:
        response_language = session.get("language_override") or session.get("language") or "en-IN"
        retry_text = translate_mod.translate(orchestrator.RETRY_TEXT, "en-IN", response_language)
        audio_out = bulbul.synthesize(retry_text, response_language)
        return {
            "detected_language": response_language,
            "transcript": "",
            "assistant_text": retry_text,
            "assistant_audio": base64.b64encode(audio_out).decode("ascii"),
            "action": None,
        }

    detected_language = stt_result["language_code"]
    session["language"] = detected_language

    response_language = session.get("language_override") or detected_language
    turn_result = orchestrator.run_turn(session, transcript, response_language)
    audio_out = bulbul.synthesize(turn_result["assistant_text"], response_language)

    session.setdefault("audit_log", []).append({
        "timestamp": time.time(),
        "detected_language": detected_language,
        "response_language": response_language,
        "transcript": transcript,
        "assistant_text": turn_result["assistant_text"],
        "assistant_text_en": turn_result["assistant_text_en"],
        "action": turn_result.get("action"),
    })
    _save_session(session)

    return {
        "detected_language": detected_language,
        "transcript": transcript,
        "assistant_text": turn_result["assistant_text"],
        "assistant_audio": base64.b64encode(audio_out).decode("ascii"),
        "action": turn_result.get("action"),
    }


INTRO_TEXT_EN = (
    "Hello, I'm the Sampoorna Health Secure assistant. I can help with cashless approval, "
    "reimbursement documents, or explaining a claim decision. Speak after the beep."
)


@app.post("/session/{session_id}/intro")
def get_intro(session_id: str):
    session = _load_session(session_id)
    language = session.get("language_override") or session.get("language") or "en-IN"
    text = translate_mod.translate(INTRO_TEXT_EN, "en-IN", language)
    audio_out = bulbul.synthesize(text, language)
    return {
        "assistant_text": text,
        "assistant_audio": base64.b64encode(audio_out).decode("ascii"),
    }


@app.websocket("/ws/live-transcribe")
async def ws_live_transcribe(websocket: WebSocket):
    await websocket.accept()
    browser_open = True

    async def relay_browser_to_sarvam(upstream):
        nonlocal browser_open
        try:
            while True:
                chunk = await websocket.receive_bytes()
                await live_stt.send_chunk(upstream, chunk)
        except WebSocketDisconnect:
            pass
        finally:
            browser_open = False
            await live_stt.send_flush(upstream)

    async def relay_sarvam_to_browser(upstream):
        async for event in live_stt.iter_events(upstream):
            if not browser_open:
                break
            try:
                await websocket.send_json(event)
            except RuntimeError:
                break

    try:
        async with live_stt.connect() as upstream:
            relay_task = asyncio.create_task(relay_sarvam_to_browser(upstream))
            await relay_browser_to_sarvam(upstream)
            relay_task.cancel()
    except Exception as exc:
        print(f"[live-transcribe] session ended with error: {exc}")


@app.post("/document")
async def document(session_id: str = Form(...), file: UploadFile = None):
    session = _load_session(session_id)
    claim_id = session.get("active_claim_id")
    if not claim_id:
        raise HTTPException(status_code=400, detail="no active claim on this session yet")

    claim = knowledge.get_claim_status(claim_id=claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="active claim not found")

    file_bytes = await file.read()
    ocr_text = vision.digitize_document(file_bytes, file.filename, language="en-IN")
    document_id = orchestrator.classify_uploaded_document(claim["claim_type"], ocr_text)

    uploaded = session.setdefault("uploaded_documents", [])
    if document_id != "unknown" and document_id not in uploaded:
        uploaded.append(document_id)

    completeness = knowledge.check_document_completeness(claim_id, additional_received=uploaded)
    reply_en = orchestrator.upload_confirmation_text(document_id, completeness)

    response_language = session.get("language_override") or session.get("language") or "en-IN"
    reply_localized = translate_mod.translate(reply_en, "en-IN", response_language)
    audio_out = bulbul.synthesize(reply_localized, response_language)

    session.setdefault("audit_log", []).append({
        "timestamp": time.time(),
        "event": "document_upload",
        "filename": file.filename,
        "classified_as": document_id,
        "assistant_text": reply_localized,
        "assistant_text_en": reply_en,
    })
    _save_session(session)

    return {
        "document_id": document_id,
        "assistant_text": reply_localized,
        "assistant_audio": base64.b64encode(audio_out).decode("ascii"),
        "missing": completeness.get("missing", []),
        "action": "REQUEST_DOCUMENT" if completeness.get("missing") else None,
    }


@app.post("/session/{session_id}/language")
def set_language_override(session_id: str, language_code: str = Form(...)):
    session = _load_session(session_id)
    session["language_override"] = language_code
    _save_session(session)
    return {"language_override": language_code}


@app.get("/audit/{session_id}")
def audit(session_id: str):
    session = _load_session(session_id)
    return {"session_id": session_id, "audit_log": session.get("audit_log", [])}


@app.get("/sessions")
def list_sessions():
    summaries = []
    for path in sorted(SESSION_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(path, encoding="utf-8") as f:
                session = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        audit_log = session.get("audit_log", [])
        summaries.append({
            "session_id": session["session_id"],
            "created_at": session.get("created_at"),
            "turns": len([e for e in audit_log if "detected_language" in e]),
            "escalated": any(e.get("action") == "ESCALATE" for e in audit_log),
            "language": session.get("language"),
        })
    return {"sessions": summaries}


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
