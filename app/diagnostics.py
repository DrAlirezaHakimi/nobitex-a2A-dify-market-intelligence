"""Read-only checks; never prints or transmits tokens except authenticated request to localhost."""
import asyncio
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).parents[1]
load_dotenv(ROOT / '.env')

async def main():
    url = 'http://127.0.0.1:8000'
    key = os.getenv('API_KEY','')
    print('A2A / Dify integration diagnostics (no credentials displayed)')
    async with httpx.AsyncClient(timeout=75, trust_env=False) as c:
        try:
            res = await c.get(url + '/health')
            print('A2A health: ', res.status_code, res.json())
            unauthed = await c.get(url + '/api/scan?top_k=1')
            print('Unauthorized request correctly blocked:', unauthed.status_code == 401)
            auth = await c.get(url + '/api/scan?top_k=1', headers={'X-API-Key':key})
            print('Authenticated scan HTTP:',auth.status_code)
            if auth.status_code == 200:
                data = auth.json()
                print('Market mode:', data.get('mode'))
                print('Universe:', data.get('metrics',{}).get('screened'))
                print('A2A analyzed:',data.get('metrics',{}).get('a2a_evaluated'))
                print('Trades enabled:',data.get('execution_enabled'))
            else:
                print('Response:',auth.text[:200])
        except httpx.RequestError as exc:
            print('Connectivity failure:',type(exc).__name__)
    print('DIFY_API_KEY configured:',bool(os.getenv('DIFY_API_KEY')))
    print('PUBLIC_BASE_URL configured:',bool(os.getenv('PUBLIC_BASE_URL')))

if __name__=='__main__':
    asyncio.run(main())
