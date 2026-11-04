"""Docker launch: both services bound inside container, published only on host loopback."""
import os
import subprocess
import sys
import time


def main():
    secret=os.getenv('API_KEY','')
    if len(secret) < 24 or secret.startswith(('REPLACE_', 'YOUR_')):
        raise SystemExit('Set a strong non-placeholder API_KEY in .env')
    if os.getenv('MARKET_MODE','demo') not in ('live','demo'):
        raise SystemExit('MARKET_MODE must be live or demo')
    children=[]
    try:
        for srv,port in [('app.server:app',8000),('app.ui_server:UI_APP',8001)]:
            children.append(subprocess.Popen([sys.executable,'-m','uvicorn',srv,'--host','0.0.0.0','--port',str(port),'--no-access-log']))
        while all(p.poll() is None for p in children):
            time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in children:
            if p.poll() is None:p.terminate()
        for p in children:
            try:p.wait(timeout=3)
            except subprocess.TimeoutExpired:p.kill()

if __name__ == '__main__':
    main()
