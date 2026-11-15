#!/bin/zsh
cd -- "${0:A:h}"
print '5분마다 뉴스를 수집합니다. 이 창을 켜두세요. 종료: Control+C'
print '컴퓨터가 꺼지거나 잠들면 수집되지 않습니다. 재부팅 후 이 파일을 다시 여세요.'
python3 news.py --watch --interval 300 --open
print '\n종료하려면 Enter를 누르세요.'
read
