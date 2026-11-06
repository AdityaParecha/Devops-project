from dotenv import load_dotenv
load_dotenv()
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.orchestrator import Orchestrator
from app.config import settings
import os

controller = Orchestrator()

@asynccontextmanager
async def lifespan(app: FastAPI):
    controller.start()
    yield
    controller.running = False

app = FastAPI(title="AI DevOps Control Center", version="2.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/")
def dashboard():
    return FileResponse("frontend/index.html")

@app.get("/api/status")
def status():
    return controller.snapshot()

@app.get("/api/health")
def health():
    return {"status": "ok", "application": "AI DevOps Control Center"}

@app.get("/api/diagnostics")
def diagnostics():
    return {
        "zabbix_url": settings.zabbix_url,
        "loki_url": settings.loki_url,
        "ollama_url": settings.ollama_url,
        "laya_model": settings.laya_model,
        "ministral_model": settings.ministral_model,
        "automatic_remediation": settings.automatic_remediation,
        "allow_backend_restart": settings.allow_backend_restart
    }


@app.post("/api/fault")
def inject_fault():
    return controller.inject_backend_fault()

@app.post("/api/analyze")
def analyze_now():
    return controller.analyze_now()
