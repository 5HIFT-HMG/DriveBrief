#!/bin/zsh
cd -- "${0:A:h}"
if ! command -v python3 >/dev/null 2>&1; then
  print 'Python 3가 필요합니다. Python 3 설치 후 다시 실행하세요.'
else
  python3 news.py --collect --open
fi
print '\n종료하려면 Enter를 누르세요.'
read
