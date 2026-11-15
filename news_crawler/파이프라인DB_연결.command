#!/bin/zsh
project_dir="${0:A:h}"
if [[ ! -f "$project_dir/setup_pipeline_db.py" ]]; then
    project_dir="${DRIVEBRIEF_PROJECT_DIR:-$HOME/Documents/Codex/2026-11-13/new-chat/work/DriveBrief-integrated}/news_crawler"
fi
cd -- "$project_dir" || exit 1
if [[ -x ../backend/.venv/bin/python ]]; then
    ../backend/.venv/bin/python setup_pipeline_db.py
else
    python3 setup_pipeline_db.py
fi
result=$?
read -k 1 '?아무 키를 누르면 닫습니다.'
exit $result
