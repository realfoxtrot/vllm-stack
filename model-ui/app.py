"""
FastAPI management UI.
Handles HTTP requests and enqueues background jobs to rq-worker.
Does NOT import worker functions directly (different process boundary).
"""
import os
import redis
import requests

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from huggingface_hub import HfApi
from rq import Queue
from rq.job import Job

app = FastAPI(title="vLLM Control Panel")
templates = Jinja2Templates(directory="templates")

MODEL_DIR = "/models"
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
HF_TOKEN = os.getenv("HF_TOKEN", "")

redis_client = redis.from_url(REDIS_URL, decode_responses=True)
# Queue references worker.deploy_model by import path string — no direct import needed
task_queue = Queue(connection=redis_client)


def get_active_model() -> str:
    return redis_client.get("active_model") or "None"


def get_deploy_status() -> str:
    return redis_client.get("deploy_status") or "idle"


@app.get("/health")
async def health():
    """Health endpoint for Docker healthcheck."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    local_models = []
    if os.path.exists(MODEL_DIR):
        local_models = [
            d for d in os.listdir(MODEL_DIR)
            if os.path.isdir(os.path.join(MODEL_DIR, d))
        ]
    return templates.TemplateResponse("index.html", {
        "request": request,
        "local_models": local_models,
        "current_model": get_active_model(),
        "deploy_status": get_deploy_status(),
    })


@app.post("/apply")
async def apply_model(repo_id: str = Form(...), token: str = Form("")):
    if not repo_id.strip():
        raise HTTPException(status_code=400, detail="repo_id is required")

    job = task_queue.enqueue(
        "worker.deploy_model",
        repo_id.strip(),
        token.strip() or HF_TOKEN,
        job_timeout=7200,
        result_ttl=86400,
    )
    return {"job_id": job.id, "status": "queued"}


@app.get("/api/search")
async def search_models(q: str = ""):
    try:
        api = HfApi()
        models = list(api.list_models(
            filter="text-generation",
            sort="downloads",
            direction=-1,
            limit=20,
            search=q.strip() or None,
        ))
        return {"results": [
            {"id": m.id, "downloads": getattr(m, "downloads", 0)}
            for m in models
        ]}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"HuggingFace API error: {e}")


@app.get("/api/job/{job_id}")
async def job_status(job_id: str):
    try:
        job = Job.fetch(job_id, connection=redis_client)
        return {
            "status": str(job.get_status()),
            "result": job.result if job.is_finished else None,
            "error": str(job.exc_info) if job.is_failed else None,
            "deploy_status": get_deploy_status(),
        }
    except Exception:
        raise HTTPException(status_code=404, detail="Job not found")


@app.get("/api/vllm/status")
async def vllm_status():
    """Proxy vLLM health for frontend polling."""
    try:
        r = requests.get("http://vllm:8000/health", timeout=5)
        return {"healthy": r.status_code == 200}
    except Exception:
        return {"healthy": False}
