#!/bin/zsh
project_dir="${0:A:h}"
if [[ ! -f "$project_dir/setup_demo_login.py" ]]; then
    project_dir="${DRIVEBRIEF_PROJECT_DIR:-$HOME/Documents/Codex/2026-11-13/new-chat/work/DriveBrief-integrated}/news_crawler"
fi
cd -- "$project_dir" || exit 1
python3 setup_demo_login.py
result=$?
read -k 1 '?아무 키를 누르면 닫습니다.'
exit $result
