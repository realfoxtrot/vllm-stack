#!/usr/bin/env bash
# =============================================================================
# deploy_model.sh — CLI model deployment helper (no UI required)
# Usage: bash scripts/deploy_model.sh "Qwen/Qwen2.5-14B-Instruct" [env_file]
# =============================================================================
set -euo pipefail

MODEL="${1:?Usage: $0 <repo_id> [env_file]}"
ENV_FILE="${2:-.env.active}"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "[deploy] ERROR: env file not found: $ENV_FILE"
    echo "[deploy] Create it first: cp .env .env.active && nano .env.active"
    exit 1
fi

# Source env for REDIS_URL and HF_TOKEN
set -a; source "$ENV_FILE"; set +a

echo "[deploy] Enqueuing model: $MODEL"
echo "[deploy] Redis: ${REDIS_URL}"

docker compose --env-file "$ENV_FILE" exec rq-worker python -c "
from redis import Redis
from rq import Queue

r = Redis.from_url('${REDIS_URL}')
q = Queue(connection=r)
job = q.enqueue(
    'worker.deploy_model',
    '${MODEL}',
    '${HF_TOKEN}',
    job_timeout=7200,
    result_ttl=86400
)
print(f'[deploy] Job enqueued. ID: {job.id}')
print(f'[deploy] Watch logs: docker compose logs -f rq-worker')
"
