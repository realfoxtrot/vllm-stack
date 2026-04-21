#!/usr/bin/env bash
# =============================================================================
# bootstrap.sh — One-shot host preparation for vLLM stack
# Supports: Ubuntu 22.04 / 24.04
# Usage: sudo bash scripts/bootstrap.sh [--profile 3090|a100]
# =============================================================================
set -euo pipefail

PROFILE="a100"
for arg in "$@"; do
    case $arg in
        --profile) shift; PROFILE="${1:-a100}" ;;
        3090|a100) PROFILE="$arg" ;;
    esac
done

echo "[bootstrap] Profile: $PROFILE"

# ── 1. System packages ───────────────────────────────────────────────────────
apt-get update -qq
apt-get install -y --no-install-recommends \
    curl wget git build-essential \
    apache2-utils \
    linux-headers-$(uname -r) \
    ubuntu-drivers-common

# ── 2. NVIDIA Drivers ────────────────────────────────────────────────────────
if ! command -v nvidia-smi &>/dev/null; then
    echo "[bootstrap] Installing NVIDIA drivers..."
    ubuntu-drivers autoinstall
    echo "[bootstrap] ⚠  REBOOT REQUIRED after driver install."
    echo "[bootstrap]    Run: sudo reboot"
    echo "[bootstrap]    Then re-run this script after reboot."
    exit 0
else
    echo "[bootstrap] NVIDIA driver already installed: $(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)"
fi

# ── 3. Docker ────────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "[bootstrap] Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker "${SUDO_USER:-$USER}"
    echo "[bootstrap] Docker installed. User ${SUDO_USER:-$USER} added to docker group."
else
    echo "[bootstrap] Docker already installed: $(docker --version)"
fi

# ── 4. NVIDIA Container Toolkit ──────────────────────────────────────────────
if ! dpkg -l 2>/dev/null | grep -q nvidia-container-toolkit; then
    echo "[bootstrap] Installing NVIDIA Container Toolkit..."
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
        | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -sL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
        | sed 's|deb https://|deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://|g' \
        | tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
    apt-get update -qq
    apt-get install -y nvidia-container-toolkit
    nvidia-ctk runtime configure --runtime=docker
    systemctl restart docker
    echo "[bootstrap] NVIDIA Container Toolkit installed."
else
    echo "[bootstrap] NVIDIA Container Toolkit already installed."
fi

# ── 5. Hugepages (recommended for 3090/64GB config) ──────────────────────────
if [[ "$PROFILE" == "3090" ]]; then
    echo "[bootstrap] Configuring hugepages for 64GB RAM profile..."
    # 16GB of 2MB hugepages
    echo "vm.nr_hugepages = 8192" >> /etc/sysctl.conf
    sysctl -p
    echo "[bootstrap] Hugepages configured: $(cat /proc/meminfo | grep HugePages_Total)"
fi

# ── 6. Swap (safety net for 64GB config) ─────────────────────────────────────
if [[ "$PROFILE" == "3090" ]]; then
    SWAP_TOTAL=$(free -m | awk '/^Swap:/{print $2}')
    if [[ "$SWAP_TOTAL" -lt 16384 ]]; then
        echo "[bootstrap] Creating 32GB swapfile for 3090 profile..."
        # Remove existing swapfile if it exists and is in use
        if [[ -f /swapfile ]]; then
            echo "[bootstrap] Deactivating existing swapfile..."
            swapoff /swapfile 2>/dev/null || true
            rm -f /swapfile
        fi
        # Ensure no stale entry in fstab
        sed -i '/^[^#].*\/swapfile.*swap/d' /etc/fstab
        # Create new swapfile
        fallocate -l 32G /swapfile
        chmod 600 /swapfile
        mkswap /swapfile
        swapon /swapfile
        echo '/swapfile none swap sw 0 0' >> /etc/fstab
        echo "[bootstrap] Swap created: $(free -h | grep Swap)"
    else
        echo "[bootstrap] Swap already sufficient: ${SWAP_TOTAL}MB"
    fi
fi

# ── 7. htpasswd generation ────────────────────────────────────────────────────
HTPASSWD_FILE="/opt/vllm-stack/nginx/.htpasswd"
if [[ ! -f "$HTPASSWD_FILE" ]]; then
    echo -n "[bootstrap] Set nginx admin password: "
    read -rs NGINX_PASS
    echo
    htpasswd -bc "$HTPASSWD_FILE" admin "$NGINX_PASS"
    echo "[bootstrap] .htpasswd created at $HTPASSWD_FILE"
else
    echo "[bootstrap] .htpasswd already exists, skipping."
fi

# ── 8. Verify GPU visibility ──────────────────────────────────────────────────
echo ""
echo "[bootstrap] GPU status:"
nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader

echo ""
echo "======================================================================="
echo "[bootstrap] ✅ Host setup complete for profile: $PROFILE"
echo "======================================================================="
echo ""
if [[ "$PROFILE" == "3090" ]]; then
    echo "Launch command:"
    echo "  cd /opt/vllm-stack"
    echo "  cat .env .env.3090 > .env.active"
    echo "  # Edit .env.active — set HF_TOKEN and GRAFANA_PASSWORD"
    echo "  docker compose --env-file .env.active -f docker-compose.yml -f docker-compose.3090.yml up -d --build"
else
    echo "Launch command:"
    echo "  cd /opt/vllm-stack"
    echo "  cp .env .env.active"
    echo "  # Edit .env.active — set HF_TOKEN and GRAFANA_PASSWORD"
    echo "  docker compose --env-file .env.active up -d --build"
fi
