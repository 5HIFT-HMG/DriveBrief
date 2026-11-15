import os
from pathlib import Path
import sys
from urllib.parse import quote,urlsplit
import webbrowser

ROOT = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from shared_db import settings


def main():
    config = settings()
    base = config['SUPABASE_URL']
    host = urlsplit(base).hostname
    if not host or not host.endswith('.supabase.co'):
        raise ValueError('공유 DB 연결을 먼저 설정하세요.')
    sql = (ROOT.parent/'supabase/migrations/20261113_pipeline_storage.sql').read_text()
    url = 'https://supabase.com/dashboard/project/'+host.split('.')[0]+'/sql/new?content='+quote(sql,safe='')
    if not webbrowser.open(url):
        print('아래 주소를 브라우저에서 열어 주세요:')
        print(url)
    print('SQL이 미리 입력된 화면에서 Run을 눌러 주세요. 새 비밀 키는 필요 없습니다.')
    input('Success가 표시되면 Enter: ')
    sys.path.insert(0,str(ROOT.parent/'backend'))
    os.environ['DRIVEBRIEF_SHARED_DB']='1'
    from drivebrief_api.shared_backend import SharedDatabase,sync_local_reviews
    database = SharedDatabase()
    database.rows('briefing_review_records',{'limit':0})
    print(sync_local_reviews())
    print('DB 연결 확인 완료. run-local.command로 서버를 실행하세요.')


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt,EOFError):
        print('연결을 중단했습니다.')
    except Exception as error:
        print('연결 실패:',type(error).__name__)
        raise SystemExit(1)
