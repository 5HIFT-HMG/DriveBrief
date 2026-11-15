import getpass
import os
from pathlib import Path
import re
import subprocess
import tempfile
import webbrowser

from shared_db import ROOT, sync_after_collection


def main():
    print('Supabase 연결을 시작합니다. 서버 키는 화면에 표시되지 않습니다.')
    webbrowser.open('https://supabase.com/dashboard')
    print('브라우저에서 로그인하고 무료 프로젝트를 만들어 주세요.')
    url = input('프로젝트 URL (https://...supabase.co): ').strip().rstrip('/')
    match = re.fullmatch(r'https://([a-z0-9-]+)\.supabase\.co', url)
    if not match:
        raise ValueError('프로젝트 URL 형식을 확인하세요.')
    schema = ROOT.parent / 'supabase/migrations/20261113_shared_news.sql'
    sql = schema.read_text(encoding='utf-8')
    try:
        subprocess.run(['pbcopy'], input=sql, text=True, check=True)
        print('DB 생성 SQL을 복사했습니다. 열린 SQL Editor에서 새 쿼리에 붙여넣고 Run을 눌러 주세요.')
    except (OSError, subprocess.CalledProcessError):
        print(f'다음 SQL 파일 내용을 SQL Editor에 붙여넣고 실행하세요: {schema}')
    webbrowser.open(f'https://supabase.com/dashboard/project/{match.group(1)}/sql/new')
    input('SQL 실행이 완료되면 Enter: ')
    webbrowser.open(f'https://supabase.com/dashboard/project/{match.group(1)}/settings/api-keys')
    secret = getpass.getpass('Secret key (sb_secret_로 시작, 입력 내용 숨김): ').strip()
    if not secret.startswith('sb_secret_') or any(c.isspace() for c in secret):
        raise ValueError('서버용 Secret key를 확인하세요.')
    path = ROOT / '.env'
    existing = path.read_text(encoding='utf-8').splitlines() if path.exists() else []
    lines = [line for line in existing if line.split('=', 1)[0].strip() not in
             ('SUPABASE_URL', 'SUPABASE_SECRET_KEY')]
    lines += [f'SUPABASE_URL={url}', f'SUPABASE_SECRET_KEY={secret}']
    fd, temporary = tempfile.mkstemp(prefix='.setup-', dir=ROOT)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(lines) + '\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    import sqlite3
    db = sqlite3.connect(ROOT / 'news.sqlite3')
    db.row_factory = sqlite3.Row
    try:
        result = sync_after_collection(db)
    finally:
        db.close()
    if result['state'] != 'synced':
        print('설정은 저장됐지만 업로드에 실패했습니다. 프로젝트 URL, Secret key, SQL 실행 여부를 확인하세요.')
        return 1
    print(f"연결 완료: {result['uploaded']}개 업로드했습니다. 자동수집을 재시작하면 이후에도 자동 반영됩니다.")
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyboardInterrupt, EOFError):
        print('\n연결을 완료하지 못했습니다. 다시 실행해 주세요. 키는 출력하지 않습니다.')
        raise SystemExit(1)
