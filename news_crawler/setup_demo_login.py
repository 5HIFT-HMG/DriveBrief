import getpass
import json
import webbrowser
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from shared_db import ROOT, settings, failure_detail


def call(base, key, path, data=None, token=None):
    headers = {'apikey': key, 'Content-Type': 'application/json', 'Prefer': 'resolution=merge-duplicates'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    payload = json.dumps(data).encode() if data is not None else None
    with urlopen(Request(base + path, data=payload, headers=headers), timeout=30) as response:
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError('response_too_large')
    return json.loads(raw) if raw else None


def main():
    config = settings()
    base, key = config['SUPABASE_URL'], config['SUPABASE_SECRET_KEY']
    if not base or not key.startswith('sb_secret_'):
        print('공유 DB를 먼저 연결하세요.')
        return 1
    host = urlsplit(base).hostname
    if not host or not host.endswith('.supabase.co') or urlsplit(base).scheme != 'https':
        raise ValueError('invalid_supabase_configuration')
    sql = (ROOT.parent / 'supabase/migrations/20261113_news_read_api.sql').read_text()
    editor_url = f'https://supabase.com/dashboard/project/{host.split(".")[0]}/sql/new?content=' + quote(sql, safe='')
    if webbrowser.open(editor_url):
        print('SQL이 미리 입력된 편집기를 열었습니다. Run만 눌러 주세요.')
    else:
        print('브라우저를 자동으로 열지 못했습니다. 아래 주소를 브라우저에 열고 Run을 눌러 주세요.')
        print(editor_url)
    input('Success가 표시되면 Enter: ')
    call(base, key, '/rest/v1/news_demo_members?select=user_id&limit=0')
    email = input('앱 로그인에 사용할 이메일: ').strip()
    password = getpass.getpass('앱 로그인용 비밀번호 (12자 이상): ')
    if '@' not in email or len(password) < 12:
        print('이메일과 12자 이상의 비밀번호를 확인하세요.')
        return 1
    if password != getpass.getpass('비밀번호 확인: '):
        print('비밀번호가 다릅니다.')
        return 1
    try:
        user = call(base, key, '/auth/v1/admin/users',
                    {'email': email, 'password': password, 'email_confirm': True})
        user_id = user['id']
    except HTTPError as error:
        if error.code != 422:
            raise
        session = call(base, key, '/auth/v1/token?grant_type=password',
                       {'email': email, 'password': password})
        user_id = session['user']['id']
    call(base, key, '/rest/v1/news_demo_members?on_conflict=user_id',
         {'user_id': user_id, 'enabled': True})
    session = call(base, key, '/auth/v1/token?grant_type=password',
                   {'email': email, 'password': password})
    page = call(base, key, '/rest/v1/rpc/read_news',
                {'p_categories': None, 'p_offset': 0, 'p_limit': 1}, session['access_token'])
    print(f"앱 연결 확인 완료: 뉴스 {page['total_candidates']}개 조회 가능합니다.")
    print('앱의 공유 뉴스 로그인 화면에 방금 정한 이메일과 비밀번호를 입력하세요.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print('\n설정을 중단했습니다.')
        raise SystemExit(1)
    except Exception as error:
        print('연결 실패: ' + failure_detail(error))
        raise SystemExit(1)
