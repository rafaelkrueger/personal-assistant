#!/usr/bin/env bash
set -euo pipefail

required_vars=(
  RPI_HOST
  RPI_USER
  RPI_PASSWORD
)

for var_name in "${required_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    echo "Missing required environment variable: ${var_name}" >&2
    exit 1
  fi
done

RPI_PORT="${RPI_PORT:-22}"
REMOTE_PATH="${REMOTE_PATH:-~/Desktop/personal-assistant}"
INPUT_MODE="${INPUT_MODE:-mic}"
VOICE_ENABLED="${VOICE_ENABLED:-true}"
INSTALL_SYSTEM_DEPS="${INSTALL_SYSTEM_DEPS:-false}"

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p ${RPI_PORT}"
SSH_BASE=(sshpass -p "${RPI_PASSWORD}" ssh ${SSH_OPTS} "${RPI_USER}@${RPI_HOST}")

echo "Ensuring remote directory exists: ${REMOTE_PATH}"
"${SSH_BASE[@]}" "mkdir -p ${REMOTE_PATH}"

echo "Syncing project files to Raspberry Pi"
sshpass -p "${RPI_PASSWORD}" rsync -az --delete \
  --exclude ".git/" \
  --exclude ".github/" \
  --exclude ".venv/" \
  --exclude "__pycache__/" \
  --exclude ".env" \
  --exclude "data/" \
  -e "ssh ${SSH_OPTS}" \
  ./ "${RPI_USER}@${RPI_HOST}:${REMOTE_PATH}/"

echo "Running remote install/restart commands"
"${SSH_BASE[@]}" "export REMOTE_PATH='${REMOTE_PATH}' INSTALL_SYSTEM_DEPS='${INSTALL_SYSTEM_DEPS}' INPUT_MODE='${INPUT_MODE}' VOICE_ENABLED='${VOICE_ENABLED}'; bash -s" <<'EOF'
set -euo pipefail

REMOTE_PATH="${REMOTE_PATH:-~/Desktop/personal-assistant}"
cd "${REMOTE_PATH}"

if [[ "${INSTALL_SYSTEM_DEPS}" == "true" ]]; then
  if command -v sudo >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y python3-venv python3-dev build-essential portaudio19-dev alsa-utils
  else
    apt-get update
    apt-get install -y python3-venv python3-dev build-essential portaudio19-dev alsa-utils
  fi
fi

if [[ ! -x ".venv/bin/python" ]]; then
  python3 -m venv .venv
fi

.venv/bin/python -m ensurepip --upgrade || true
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -r requirements.txt

pkill -f "python main.py" || true
nohup env INPUT_MODE="${INPUT_MODE}" VOICE_ENABLED="${VOICE_ENABLED}" .venv/bin/python main.py >/tmp/personal-assistant.log 2>&1 < /dev/null &
sleep 2

echo "Process status:"
ps -ef | grep -E "python .*main.py" | grep -v grep || true
echo "Last log lines:"
tail -n 30 /tmp/personal-assistant.log || true
EOF

echo "Deploy finished successfully."
