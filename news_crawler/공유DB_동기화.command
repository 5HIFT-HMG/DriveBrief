#!/bin/zsh
project_dir="${0:A:h}"
if [[ ! -f "$project_dir/shared_db.py" ]]; then
    project_dir="${DRIVEBRIEF_PROJECT_DIR:-$HOME/Documents/Codex/2026-11-13/new-chat/work/DriveBrief-integrated}/news_crawler"
fi
if [[ ! -f "$project_dir/shared_db.py" ]]; then
    print '프로젝트 폴더를 찾지 못했습니다. 원래 news_crawler 폴더에서 실행해 주세요.'
    read -k 1 '?아무 키를 누르면 닫습니다.'
    exit 1
fi
cd -- "$project_dir" || exit 1
python3 shared_db.py
result=$?
read -k 1 '?아무 키를 누르면 닫습니다.'
exit $result
