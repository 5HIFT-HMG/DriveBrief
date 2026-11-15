#!/bin/zsh
set -eu
project_dir="${0:A:h}"
if [[ ! -f "$project_dir/backend/pyproject.toml" ]]; then
    project_dir="${DRIVEBRIEF_PROJECT_DIR:-$HOME/Documents/Codex/2026-11-13/new-chat/work/DriveBrief-integrated}"
fi
cd -- "$project_dir/backend"
if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import fastapi, uvicorn, pydantic' >/dev/null 2>&1; then
    .venv/bin/python -m pip install -r requirements.lock
fi
printf 'DriveBrief API: http://127.0.0.1:8000\nRSS: 시작 즉시 수집 후 5분마다 갱신\n수집 상태: http://127.0.0.1:8000/v1/news/status\n종료: Ctrl+C\n'
export DRIVEBRIEF_SHARED_DB="${DRIVEBRIEF_SHARED_DB:-1}"
exec .venv/bin/python -B -m drivebrief_api
