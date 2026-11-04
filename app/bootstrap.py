"""Launch split services in two subprocesses using a local .env file."""
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parents[1]
ENV = ROOT / '.env'


def ensure_env():
    if not ENV.exists():
        secret = secrets.token_urlsafe(36)
        ENV.write_text('# PRIVATE: Do not share this file or commit it to version control.\n'
                       'MARKET_MODE=demo\n'
                       f'API_KEY={secret}\n'
                       'PUBLIC_BASE_URL=\n'
                       'DIFY_API_KEY=\n'
                       'DIFY_API_BASE=https://api.dify.ai/v1\n'
                       'MARKET_TTL=70\nMAX_PARALLEL=12\nMAX_DEEP=300\n', encoding='utf-8')
        print('[CONFIG] Created .env with a strong random A2A backend API_KEY; copy it to Dify's secret A2A_API_KEY environment variable if using a Workflow.')
    load_dotenv(ENV, override=True)
    token = os.getenv('API_KEY', '')
    if len(token) < 24 or token.startswith(('REPLACE_', 'YOUR_')):
        raise SystemExit('Refusing to start: set a strong API_KEY (>=24 chars) in .env')
    mode = os.getenv('MARKET_MODE', '')
    if mode not in ('live', 'demo'):
        raise SystemExit('MARKET_MODE must be live or demo in .env')
    # Explicitly protect UI from accidentally being exposed via tunnel.
    os.environ['BIND_HOST'] = '127.0.0.1'
    os.environ['PORT'] = '8000'


def main():
    ensure_env()
    children = []
    try:
        for module, port in [('app.server:app', 8000), ('app.ui_server:UI_APP', 8001)]:
            proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', module, '--host', '127.0.0.1',
                                     '--port', str(port), '--no-access-log'], cwd=str(ROOT),
                                    env=os.environ.copy())
            children.append(proc)
        time.sleep(1.5)
        if any(p.poll() is not None for p in children):
            raise RuntimeError('A service failed on startup. Check whether ports 8000/8001 are already used.')
        print('\n=== NOBITEX A2A + DIFY INTEGRATED ===')
        print('Private dashboard: http://127.0.0.1:8001')
        print('A2A API (expose ONLY this port via ngrok): http://127.0.0.1:8000')
        print('Market mode: ' + os.environ['MARKET_MODE'].upper())
        print('Dify integration configured: ' + str(bool(os.getenv('DIFY_API_KEY'))))
        print('No exchange credentials; trade execution disabled.\n')
        while all(p.poll() is None for p in children):
            time.sleep(.5)
    except KeyboardInterrupt:
        print('\nStopping services...')
    finally:
        for p in children:
            if p.poll() is None:
                p.terminate()
        for p in children:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == '__main__':
    main()
