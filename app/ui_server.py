"""Private loopback-only UI gateway. No API tokens are ever sent to browsers.

Browser -> localhost:8001 -> private gateway -> (local A2A API OR Dify Cloud)
For Dify mode: Dify Cloud -> public HTTPS tunnel -> localhost:8000 A2A API.
"""
import asyncio
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).parents[1]
DATA_DIR = ROOT / 'data'
MODE = os.environ.get('MARKET_MODE', 'demo').lower()
A2A_KEY = os.environ.get('API_KEY', '')
DIFY_KEY = os.environ.get('DIFY_API_KEY', '')
DIFY_BASE = os.environ.get('DIFY_API_BASE', 'https://api.dify.ai/v1').rstrip('/')
PUBLIC_BASE = os.environ.get('PUBLIC_BASE_URL', '').rstrip('/')
UI_MAX_AGE_SECONDS = int(os.environ.get('UI_MAX_AGE_SECONDS', '200'))
API_PORT = int(os.environ.get('PORT', '8000'))
PRIVATE_API = f'http://127.0.0.1:{API_PORT}'
UI_APP = FastAPI(title='Hakimi Private A2A+Dify Dashboard', docs_url=None, redoc_url=None,
                 openapi_url=None, version='1.0.0')
_sem = asyncio.Semaphore(2)


class ScanParams(BaseModel):
    top_k: int = Field(default=15, ge=1, le=100)


def dify_ready():
    parts = urlsplit(PUBLIC_BASE)
    return bool(DIFY_KEY and A2A_KEY and parts.scheme == 'https' and parts.hostname
                and parts.hostname not in ('localhost', '127.0.0.1'))


def db_conn():
    DATA_DIR.mkdir(exist_ok=True)
    con = sqlite3.connect(DATA_DIR / 'scan_history.sqlite3', timeout=3.0)
    con.execute('CREATE TABLE IF NOT EXISTS scans (id TEXT PRIMARY KEY, created_utc TEXT NOT NULL, '
                'source TEXT NOT NULL, mode TEXT NOT NULL, screened INTEGER NOT NULL, '
                'a2a_evaluated INTEGER NOT NULL, buy_candidates INTEGER NOT NULL, '
                'sell_candidates INTEGER NOT NULL, best_symbol TEXT, workflow_run_id TEXT)')
    return con


def save_history(run_id, source, market, workflow_id=''):
    metrics = market['metrics']
    candidate = market.get('recommendation') or {}
    with db_conn() as con:
        con.execute('INSERT INTO scans VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (run_id, datetime.now(timezone.utc).isoformat(), source, market['mode'],
                     metrics.get('screened', 0), metrics.get('a2a_evaluated', 0),
                     metrics.get('buy_candidates', 0), metrics.get('sell_candidates', 0),
                     candidate.get('symbol'), workflow_id))


def validate_market(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('metrics'), dict):
        raise HTTPException(502, 'Malformed A2A market response')
    if payload.get('mode') != MODE:
        raise HTTPException(502, f'Market mode mismatch: expected {MODE}; got {payload.get("mode")}')
    if not isinstance(payload.get('market_universe'), list):
        raise HTTPException(502, 'Market universe is absent')
    when = payload.get('generated_at', '')
    try:
        stamp = datetime.fromisoformat(when.replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc) - stamp).total_seconds()
    except (ValueError, TypeError):
        raise HTTPException(502, 'Market timestamp invalid')
    if age < -30 or age > UI_MAX_AGE_SECONDS:
        raise HTTPException(503, f'Outdated scan ({int(age)}s). Results withheld.')
    if payload.get('execution_enabled') is not False:
        raise HTTPException(502, 'Unexpected trade-execution flag')
    return payload


async def local_scan(top_k):
    if not A2A_KEY:
        raise HTTPException(503, 'API_KEY is not configured')
    async with httpx.AsyncClient(timeout=httpx.Timeout(70, connect=3), trust_env=False) as client:
        try:
            response = await client.get(PRIVATE_API + '/api/scan', params={'top_k': top_k},
                                        headers={'X-API-Key': A2A_KEY})
            response.raise_for_status()
            return validate_market(response.json())
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
            raise HTTPException(502, 'Local A2A request failed: ' + type(exc).__name__)


async def dify_scan(top_k):
    if not dify_ready():
        raise HTTPException(503, 'Dify not configured: set DIFY_API_KEY and PUBLIC_BASE_URL in .env')
    payload = {'inputs': {'backend_url': PUBLIC_BASE, 'top_k': str(top_k)},
               'response_mode': 'blocking', 'user': 'hakimi-local-dashboard'}
    async with httpx.AsyncClient(timeout=httpx.Timeout(115, connect=8), follow_redirects=False) as client:
        try:
            response = await client.post(DIFY_BASE + '/workflows/run', json=payload,
                                         headers={'Authorization': 'Bearer ' + DIFY_KEY,
                                                  'Content-Type': 'application/json'})
            if response.status_code in (401, 403):
                raise HTTPException(502, 'Dify rejected its workflow API key (401/403)')
            if response.status_code == 404:
                raise HTTPException(502, 'Dify workflow not found or not published (404)')
            response.raise_for_status()
            message = response.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
            raise HTTPException(502, 'Dify request failed: ' + type(exc).__name__)
    detail = message.get('data') or {}
    if detail.get('status') not in ('succeeded', 'success'):
        raise HTTPException(502, 'Dify run did not succeed: ' + str(detail.get('error') or detail.get('status'))[:200])
    outputs = detail.get('outputs') or {}
    serialized = outputs.get('details_json') or outputs.get('raw_json')
    if not serialized:
        raise HTTPException(502, 'Dify response has no details_json/raw_json; check Output node')
    try:
        market = json.loads(serialized) if isinstance(serialized, str) else serialized
    except (ValueError, TypeError):
        raise HTTPException(502, 'Dify output is not valid JSON, possibly truncated by DSL')
    market = validate_market(market)
    return market, str(outputs.get('report', '')), str(message.get('workflow_run_id') or detail.get('id') or '')


@UI_APP.middleware('http')
async def reject_cross_site(request: Request, call_next):
    host = request.headers.get('host', '').split(':', 1)[0].lower()
    if host not in ('127.0.0.1', 'localhost'):
        return JSONResponse({'detail': 'Local UI only'}, 403)
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin', '')
        if origin:
            u = urlsplit(origin)
            if u.scheme != 'http' or u.hostname not in ('localhost', '127.0.0.1') or u.port != 8001:
                return JSONResponse({'detail': 'Invalid request origin'}, 403)
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            return JSONResponse({'detail': 'JSON requests only'}, 415)
    result = await call_next(request)
    result.headers['Cache-Control'] = 'no-store'
    result.headers['X-Content-Type-Options'] = 'nosniff'
    result.headers['X-Frame-Options'] = 'DENY'
    result.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"
    return result


@UI_APP.get('/')
async def page():
    return FileResponse(ROOT / 'dashboard' / 'index.html')


@UI_APP.get('/api/ui/status')
async def status():
    return {'mode': MODE, 'execution_enabled': False, 'ui_network': 'loopback-only',
            'dify_configured': dify_ready(), 'a2a_configured': bool(A2A_KEY),
            'dify_is_llm_agent': False, 'a2a_protocol': 'JSON-RPC subset',
            'data_notice': 'Real market snapshot; not guaranteed current at execution time' if MODE == 'live' else 'SYNTHETIC TEST DATA'}


@UI_APP.post('/api/ui/scan')
async def run_scan(params: ScanParams):
    async with _sem:
        market = await local_scan(params.top_k)
        uid = uuid.uuid4().hex
        save_history(uid, 'A2A_DIRECT', market)
        return {'id': uid, 'source': 'A2A_DIRECT', 'market': market,
                'report': '', 'dify_workflow_run_id': None}


@UI_APP.post('/api/ui/dify')
async def run_dify(params: ScanParams):
    async with _sem:
        market, report, workflow_run_id = await dify_scan(params.top_k)
        uid = uuid.uuid4().hex
        save_history(uid, 'DIFY_WORKFLOW', market, workflow_run_id)
        return {'id': uid, 'source': 'DIFY_WORKFLOW', 'market': market,
                'report': report, 'dify_workflow_run_id': workflow_run_id}


@UI_APP.get('/api/ui/history')
async def history():
    with db_conn() as con:
        con.row_factory = sqlite3.Row
        items = con.execute('SELECT id, created_utc, source, mode, screened, a2a_evaluated, '
                            'buy_candidates, sell_candidates, best_symbol, workflow_run_id '
                            'FROM scans ORDER BY created_utc DESC LIMIT 50').fetchall()
    return {'items': [dict(row) for row in items]}
