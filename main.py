"""FastAPI-приложение «Монитор конкурентов Трек ВУЗ»: эндпоинты анализа, парсинга и истории."""
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import config
from models.schemas import ParseRequest, TextRequest
from services.gigachat_service import get_service
from services.history_service import history
from services.pipeline import run_parse

app = FastAPI(
    title="Монитор конкурентов — Трек ВУЗ",
    description="Мультимодальный ИИ-анализ сайтов, скриншотов и PDF сервисов для абитуриентов (GigaChat + Selenium)",
    version="1.0.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR), name="static")
config.DATA_DIR.mkdir(exist_ok=True)
app.mount("/data", StaticFiles(directory=config.DATA_DIR), name="data")

IMAGE_TYPES = {".png", ".jpg", ".jpeg"}


def _save_upload(upload: UploadFile, allowed: set[str]) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(400, f"Ожидается файл {', '.join(sorted(allowed))}, получен «{suffix or 'без расширения'}»")
    tmp = Path(tempfile.mkdtemp()) / f"upload{suffix}"
    with tmp.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    return tmp


def _ai_error(e: Exception) -> HTTPException:
    return HTTPException(502, f"Ошибка ИИ-анализа: {e}")


@app.get("/")
def index():
    return FileResponse(config.FRONTEND_DIR / "index.html")


@app.get("/health")
def health():
    return {"status": "ok", "llm": config.GIGACHAT_TEXT_MODEL, "vision": config.GIGACHAT_VISION_MODEL,
            "key_configured": bool(config.GIGACHAT_AUTH_KEY)}


@app.get("/competitors")
def competitors():
    return config.COMPETITOR_URLS


@app.post("/analyze/text")
def analyze_text(req: TextRequest):
    try:
        analysis, tokens = get_service().analyze_text(req.text)
    except Exception as e:
        raise _ai_error(e)
    item = history.add("text", analysis.model_dump(), req.competitor, req.text, tokens)
    return {"history_id": item.id, "tokens": tokens, "result": analysis}


@app.post("/analyze/image")
def analyze_image(file: UploadFile = File(...), competitor: str = Form("")):
    path = _save_upload(file, IMAGE_TYPES)
    try:
        analysis, tokens = get_service().analyze_image(path)
    except Exception as e:
        raise _ai_error(e)
    item = history.add("image", analysis.model_dump(), competitor, file.filename or "", tokens)
    return {"history_id": item.id, "tokens": tokens, "result": analysis}


@app.post("/analyze/pdf")
def analyze_pdf(file: UploadFile = File(...), competitor: str = Form("")):
    path = _save_upload(file, {".pdf"})
    try:
        analysis, tokens, chars = get_service().analyze_pdf(path)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise _ai_error(e)
    item = history.add("pdf", analysis.model_dump(), competitor, file.filename or "", tokens)
    return {"history_id": item.id, "tokens": tokens, "chars": chars, "result": analysis}


@app.post("/parse/demo")
def parse_demo(req: ParseRequest):
    """С url — один сайт; без url — все конкуренты из config.COMPETITOR_URLS по очереди."""
    targets = {req.competitor or req.url: req.url} if req.url else config.COMPETITOR_URLS
    return [run_parse(name, url) for name, url in targets.items()]


@app.get("/history")
def get_history():
    return history.all()


@app.delete("/history")
def clear_history():
    history.clear()
    return {"status": "cleared"}
