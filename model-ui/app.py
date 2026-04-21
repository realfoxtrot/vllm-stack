"""
FastAPI management UI for vLLM Control Panel.
Handles HTTP requests and enqueues background jobs to rq-worker.
Does NOT import worker functions directly (different process boundary).
"""
import os
from typing import Any

import redis
import requests
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from huggingface_hub import HfApi
from rq import Queue
from rq.job import Job

# Configuration constants
MODEL_DIR: str = "/models"
REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379")
HF_TOKEN: str = os.getenv("HF_TOKEN", "")
VLLM_HEALTH_URL: str = "http://vllm:8000/health"
DEPLOY_JOB_TIMEOUT: int = 7200
DEPLOY_RESULT_TTL: int = 86400

app = FastAPI(title="vLLM Control Panel")
templates = Jinja2Templates(directory="templates")

redis_client = redis.from_url(REDIS_URL, decode_responses=True)
task_queue = Queue(connection=redis_client)


def get_active_model() -> str:
    """Retrieve the currently active model from Redis."""
    return redis_client.get("active_model") or "None"


def get_deploy_status() -> str:
    """Retrieve the current deployment status from Redis."""
    return redis_client.get("deploy_status") or "idle"


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health endpoint for Docker healthcheck."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> Any:
    """Render the main control panel page."""
    local_models: list[str] = []
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
async def apply_model(repo_id: str = Form(...), token: str = Form("")) -> dict[str, str]:
    """Enqueue a model deployment job."""
    repo_id = repo_id.strip()
    if not repo_id:
        raise HTTPException(status_code=400, detail="repo_id is required")

    job = task_queue.enqueue(
        "worker.deploy_model",
        repo_id,
        token.strip() or HF_TOKEN,
        job_timeout=DEPLOY_JOB_TIMEOUT,
        result_ttl=DEPLOY_RESULT_TTL,
    )
    return {"job_id": job.id, "status": "queued"}


@app.get("/api/search")
async def search_models(q: str = "") -> dict[str, list[dict[str, Any]]]:
    """Search for models on HuggingFace Hub."""
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
        raise HTTPException(
            status_code=502, 
            detail=f"HuggingFace API error: {e}"
        ) from e


@app.get("/api/job/{job_id}")
async def job_status(job_id: str) -> dict[str, Any]:
    """Get the status of a deployment job."""
    try:
        job = Job.fetch(job_id, connection=redis_client)
        return {
            "status": str(job.get_status()),
            "result": job.result if job.is_finished else None,
            "error": str(job.exc_info) if job.is_failed else None,
            "deploy_status": get_deploy_status(),
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail="Job not found") from e


@app.get("/api/vllm/status")
async def vllm_status() -> dict[str, bool]:
    """Proxy vLLM health for frontend polling."""
    try:
        response = requests.get(VLLM_HEALTH_URL, timeout=5)
        return {"healthy": response.status_code == 200}
    except Exception:
        return {"healthy": False}
