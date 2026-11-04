import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import pytest
import httpx
import app.ui_server as ui


def run(coro):
    return asyncio.run(coro)


def fake_market(mode='demo', aged=False):
    d = (datetime.now(timezone.utc) - timedelta(minutes=6 if aged else 0)).isoformat()
    return {'mode': mode, 'generated_at': d, 'metrics': {
        'screened': 63, 'a2a_evaluated': 63, 'buy_candidates': 9, 'sell_candidates': 7,
        'rejected': 0, 'hold': 47}, 'market_universe': [{'symbol':'BTCIRT'}],
        'opportunities': [{'symbol':'BTCIRT','action':'BUY','score':50}],
        'recommendation': {'symbol':'BTCIRT'}, 'execution_enabled':False}


def test_live_mode_rejects_demo_result(monkeypatch):
    monkeypatch.setattr(ui, 'MODE', 'live')
    with pytest.raises(Exception, match='Market mode mismatch'):
        ui.validate_market(fake_market('demo'))


def test_expired_data_refused(monkeypatch):
    monkeypatch.setattr(ui, 'MODE', 'demo')
    with pytest.raises(Exception, match='Outdated scan'):
        ui.validate_market(fake_market('demo', aged=True))


def test_undeclared_execution_not_accepted(monkeypatch):
    monkeypatch.setattr(ui, 'MODE', 'demo')
    m = fake_market('demo'); m['execution_enabled']=True
    with pytest.raises(Exception, match='Unexpected'):
        ui.validate_market(m)


def test_no_dify_secret_in_html():
    html = (Path(__file__).parents[1]/'dashboard'/'index.html').read_text()
    assert 'DIFY_API_KEY=' not in html
    assert 'X-API-Key' not in html
    assert '<script id="offlineData"' not in html


def test_dify_ready_requires_https(monkeypatch):
    monkeypatch.setattr(ui, 'DIFY_KEY','example-dify-token')
    monkeypatch.setattr(ui, 'A2A_KEY','example-a2a-token')
    monkeypatch.setattr(ui, 'PUBLIC_BASE','http://127.0.0.1:8000')
    assert not ui.dify_ready()
    monkeypatch.setattr(ui, 'PUBLIC_BASE','https://example.ngrok-free.dev')
    assert ui.dify_ready()


def test_local_ui_flow_history_and_security(monkeypatch, tmp_path):
    monkeypatch.setattr(ui, 'DATA_DIR',tmp_path)
    monkeypatch.setattr(ui, 'MODE','demo')
    monkeypatch.setattr(ui, 'dify_ready',lambda:True)
    async def scan(n): return ui.validate_market(fake_market('demo'))
    async def dify(n): return ui.validate_market(fake_market('demo')), 'گزارش از Dify', 'wf-001'
    monkeypatch.setattr(ui, 'local_scan',scan)
    monkeypatch.setattr(ui, 'dify_scan',dify)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ui.UI_APP),base_url='http://127.0.0.1:8001') as c:
            status=await c.get('/api/ui/status')
            assert status.status_code==200
            assert status.json()['execution_enabled'] is False
            r=await c.post('/api/ui/scan',json={'top_k':15},headers={'Origin':'http://127.0.0.1:8001'})
            assert r.status_code==200, r.text
            assert r.json()['source']=='A2A_DIRECT'
            assert r.json()['market']['metrics']['screened']==63
            r=await c.post('/api/ui/dify',json={'top_k':15},headers={'Origin':'http://127.0.0.1:8001'})
            assert r.status_code==200, r.text
            assert r.json()['dify_workflow_run_id']=='wf-001'
            assert (await c.get('/api/ui/history')).json()['items'][0]['source']=='DIFY_WORKFLOW'
            assert (await c.post('/api/ui/scan',json={},headers={'Origin':'https://evil.example'})).status_code==403
            assert (await c.post('/api/ui/scan',data='top_k=10')).status_code==415
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ui.UI_APP),base_url='http://evil.example:8001') as c:
            assert (await c.get('/')).status_code==403
    run(scenario())


def test_dify_workflow_outputs_and_http_errors(monkeypatch):
    monkeypatch.setattr(ui, 'DIFY_KEY', 'test-secret')
    monkeypatch.setattr(ui, 'A2A_KEY', 'test-a2a')
    monkeypatch.setattr(ui, 'MODE', 'demo')
    monkeypatch.setattr(ui, 'PUBLIC_BASE', 'https://example.ngrok-free.dev')
    async def scenario():
        def handler(req):
            assert req.url.path.endswith('/workflows/run')
            assert req.headers['authorization']=='Bearer test-secret'
            body=json.loads(req.content)
            assert body['inputs']['backend_url']=='https://example.ngrok-free.dev'
            return httpx.Response(200,json={'workflow_run_id':'wf-10', 'data': {
                'status':'succeeded','outputs':{'report':'گزارش تست','details_json':json.dumps(fake_market('demo'))}}})
        real_client=httpx.AsyncClient
        def fake_client(*a,**kw):
            return real_client(transport=httpx.MockTransport(handler),base_url='https://api.dify.ai')
        monkeypatch.setattr(ui.httpx,'AsyncClient',fake_client)
        market,report,run_id=await ui.dify_scan(15)
        assert market['metrics']['screened']==63 and report=='گزارش تست' and run_id=='wf-10'
    run(scenario())


def test_missing_api_key_fail_closed(monkeypatch):
    import app.server as s
    monkeypatch.setattr(s,'API_KEY','')
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app),base_url='http://127.0.0.1') as c:
            resp=await c.get('/api/scan')
            assert resp.status_code==503
    run(scenario())
