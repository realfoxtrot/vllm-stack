vllm-stack/
├── .env                          ← A100 base config (edit HF_TOKEN here)
├── .env.3090                     ← RTX 3090 profile overrides
├── .gitignore                    ← Excludes secrets & model weights
├── docker-compose.yml            ← Full base stack
├── docker-compose.3090.yml       ← Dual 3090 override
├── nginx/
│   ├── nginx.conf
│   └── .htpasswd.example
├── prometheus/prometheus.yml
├── grafana/provisioning/dashboards/
│   ├── dashboards.yaml
│   └── vllm.json
├── model-ui/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app.py
│   ├── worker.py
│   └── templates/index.html
├── scripts/
│   ├── bootstrap.sh              ← Run first: sudo bash scripts/bootstrap.sh --profile a100|3090
│   └── deploy_model.sh           ← CLI deploy without UI
└── models/                       ← Empty dir, weights land here


Here's what we have in stack structure:

bootstrap.sh — Host setup script (NVIDIA drivers, Docker, NVIDIA Container Toolkit, hugepages/swap for 3090, htpasswd generation). Works for both --profile a100 and --profile 3090.
deploy_model.sh — CLI helper to enqueue model deployment without the UI.
.gitignore — Excludes secrets (.env.active, .htpasswd) and model weights from git.
docker-compose.yml and docker-compose.3090.yml — Base and 3090 override compose files.
.env and .env.3090 — Hardware profile configs.
nginx/nginx.conf — Reverse proxy with rate limiting, streaming support, auth.
prometheus/prometheus.yml — Metrics scrape config.
grafana/provisioning/dashboards/ — Dashboard provisioning YAML and vllm.json.
model-ui/ — FastAPI app (app.py), RQ worker (worker.py), Dockerfile, requirements.txt, and templates/index.html.
models/ — Empty placeholder directory (weights go here).

First steps after extracting:

sudo cp -r vllm-stack /opt/
cd /opt/vllm-stack
sudo bash scripts/bootstrap.sh --profile a100   # or 3090
cp .env .env.active && nano .env.active          # set HF_TOKEN + GRAFANA_PASSWORD
docker compose --env-file .env.active up -d --build

