"""
RQ Worker task definitions.
This module is imported by the RQ worker process, NOT by the FastAPI app.
Tasks are enqueued by app.py and executed here in a separate container.
"""
import os
import time
import docker
import redis as redis_lib

from huggingface_hub import snapshot_download

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
HF_TOKEN = os.getenv("HF_TOKEN", "")
VLLM_CONTAINER_NAME = os.getenv("VLLM_CONTAINER_NAME", "vllm-server")
MODEL_DIR = "/models"

# Each worker process gets its own connections
_redis = None
_docker = None


def get_redis():
    global _redis
    if _redis is None:
        _redis = redis_lib.from_url(REDIS_URL)
    return _redis


def get_docker():
    global _docker
    if _docker is None:
        _docker = docker.from_env()
    return _docker


def deploy_model(repo_id: str, hf_token: str = "") -> dict:
    """
    Full model deployment pipeline:
    1. Download model snapshot from HuggingFace
    2. Update Redis state
    3. Recreate vLLM container with new MODEL_PATH env var
    4. Wait for health check to pass
    """
    r = get_redis()
    d = get_docker()

    token = hf_token.strip() or HF_TOKEN
    safe_name = repo_id.replace("/", "_")
    target_dir = os.path.join(MODEL_DIR, safe_name)

    # Distributed lock — prevent concurrent deploys
    lock = r.lock("deploy_lock", timeout=7200, blocking_timeout=5)
    if not lock.acquire(blocking=False):
        raise RuntimeError("Another deploy is already in progress. Check job queue.")

    try:
        # ── Step 1: Download ─────────────────────────────────────────────────
        r.set("deploy_status", f"downloading:{repo_id}")
        snapshot_download(
            repo_id=repo_id,
            local_dir=target_dir,
            token=token or None,
            ignore_patterns=["*.pt", "*.bin"],   # Prefer safetensors
        )

        # ── Step 2: Update active model in Redis ─────────────────────────────
        r.set("active_model", safe_name)
        r.set("deploy_status", f"restarting:{safe_name}")

        # ── Step 3: Recreate vLLM container with updated MODEL_PATH ──────────
        # FIXED: exec_run cannot set persistent env vars.
        # Correct approach: get container config, update env, recreate container.
        container = d.containers.get(VLLM_CONTAINER_NAME)
        attrs = container.attrs

        # Extract current config
        current_config = attrs["Config"]
        host_config = attrs["HostConfig"]
        network_settings = attrs["NetworkSettings"]

        # Build updated env dict
        env_vars = {
            e.split("=", 1)[0]: e.split("=", 1)[1]
            for e in current_config.get("Env", [])
            if "=" in e
        }
        env_vars["MODEL_PATH"] = safe_name

        # Get network name
        networks = list(network_settings.get("Networks", {}).keys())

        # Build volume binds
        binds = host_config.get("Binds") or []
        volumes = {}
        for b in binds:
            if ":" in b:
                parts = b.split(":")
                src, dst = parts[0], parts[1]
                mode = parts[2] if len(parts) > 2 else "rw"
                volumes[src] = {"bind": dst, "mode": mode}

        # Stop and remove old container
        container.stop(timeout=30)
        container.remove()

        # Recreate with identical config but new MODEL_PATH
        new_container = d.containers.run(
            image=current_config["Image"],
            name=VLLM_CONTAINER_NAME,
            environment=env_vars,
            volumes=volumes,
            network=networks[0] if networks else "vllm-net",
            runtime="nvidia",
            ipc_mode=host_config.get("IpcMode", "host"),
            ulimits=[
                docker.types.Ulimit(name="memlock", soft=-1, hard=-1),
                docker.types.Ulimit(name="stack", soft=67108864, hard=67108864),
            ],
            device_requests=[
                docker.types.DeviceRequest(count=-1, capabilities=[["gpu"]])
            ],
            command=current_config.get("Cmd"),
            detach=True,
            restart_policy={"Name": "unless-stopped"},
        )

        # ── Step 4: Health check polling ─────────────────────────────────────
        r.set("deploy_status", f"waiting_health:{safe_name}")
        max_wait = 300  # 5 minutes
        poll_interval = 10
        elapsed = 0

        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval
            new_container.reload()
            if new_container.status != "running":
                raise RuntimeError(
                    f"Container exited unexpectedly:\n"
                    f"{new_container.logs(tail=50).decode()}"
                )
            try:
                import requests
                resp = requests.get("http://vllm:8000/health", timeout=5)
                if resp.status_code == 200:
                    r.set("deploy_status", "ready")
                    return {
                        "status": "success",
                        "model": safe_name,
                        "elapsed_seconds": elapsed,
                    }
            except Exception:
                pass  # Still starting up

        raise TimeoutError(f"vLLM did not become healthy within {max_wait}s")

    except Exception as e:
        r.set("deploy_status", f"failed:{str(e)[:200]}")
        raise
    finally:
        lock.release()
