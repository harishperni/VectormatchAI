#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if command -v python3.11 >/dev/null 2>&1; then
  PYTHON311_BIN="$(command -v python3.11)"
elif [[ -x "/opt/homebrew/bin/python3.11" ]]; then
  PYTHON311_BIN="/opt/homebrew/bin/python3.11"
else
  echo "Missing dependency: python3.11"
  echo "Install Python 3.11 and ensure it is available as 'python3.11' or at /opt/homebrew/bin/python3.11."
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "Missing dependency: node"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "Missing dependency: npm"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Missing dependency: docker"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is installed but not running. Start Docker Desktop and retry."
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Missing dependency: docker compose plugin"
  exit 1
fi

echo "Environment check passed:"
echo "  python3.11: ${PYTHON311_BIN}"
echo "  node: $(command -v node)"
echo "  npm: $(command -v npm)"
echo "  docker: $(command -v docker)"
echo "  docker compose: available"
echo "  repo: ${ROOT_DIR}"
