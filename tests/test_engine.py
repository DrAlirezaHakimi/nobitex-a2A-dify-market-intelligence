import asyncio
import os
import time
import pytest
import httpx
from app.engine import synthetic_market, parse_markets, screening, risk_agent, judge_agent, MarketProvider
from app.server import app
import app.server as server

@pytest.fixture(autouse=True)
def test_secret(monkeypatch):
    monkeypatch.setattr(server, "API_KEY", "test-key-very-long-for-tests-only")

from app.a2a_protocol import handle_a2a, agent_card


def run(coro):
    return asyncio.run(coro)


def test_all_synthetic_markets_are_parsed():
    books, stats = synthetic_market(seed=20)
    markets = parse_markets(books, stats)
    assert len(markets) == len(books) - 1
    assert len({m['symbol'] for m in markets}) == len(markets)
    assert all(m['bid'] < m['ask'] for m in markets)


def test_data_quality_rejections():
    books, stats = synthetic_market(count=2)
    sym = next(k for k in books if k != 'status')
    books[sym]['lastUpdate'] = int(time.time()*1000)-1000000
    market = next(m for m in parse_markets(books, stats) if m['symbol']==sym)
    assert screening(market)
    books[sym]['asks'] = [['bad'], None, ['-1','2']]
    assert sym not in [m['symbol'] for m in parse_markets(books, stats)]


def test_risk_guards_are_quote_bounded():
    books, stats = synthetic_market(count=3)
    m = parse_markets(books, stats)[0]
    r = risk_agent(m, requested_quote=2_000_000, fee_bps=30)
    assert 0 <= r['max_notional_quote'] <= 2_000_000
    assert r['estimated_round_trip_fee_bps'] == 60


def test_conflicting_agents_hold():
    books, stats = synthetic_market(count=3)
    m = parse_markets(books, stats)[0]
    o = {'bias':'BUY','strength':.9}
    t = {'bias':'SELL','strength':.9}
    risk = risk_agent(m, requested_quote=20000000)
    assert judge_agent(m,o,t,{},risk)['action'] == 'HOLD'


def test_a2a_card_and_rpc_lifecycle():
    assert agent_card('orderflow')['protocolVersion']=='0.2.6'
    books, stats = synthetic_market(count=2)
    market=parse_markets(books,stats)[0]
    req={'jsonrpc':'2.0','id':1,'method':'message/send','params':{'message':{'role':'user','parts':[{'kind':'data','data':{'market':market}}]}}}
    reply=handle_a2a('orderflow',req)
    tid=reply['result']['id']
    assert reply['result']['status']['state']=='completed'
    result=handle_a2a('orderflow',{'jsonrpc':'2.0','id':2,'method':'tasks/get','params':{'id':tid}})
    assert result['result']['id']==tid
    assert handle_a2a('orderflow',{'jsonrpc':'2.0','id':3,'method':'tasks/unknown','params':{}})['error']['code']==-32601


def test_http_scan_and_paper():
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            resp=await client.get('/api/scan?top_k=20',headers={'X-API-Key':'test-key-very-long-for-tests-only'})
            assert resp.status_code==200, resp.text
            report=resp.json()
            m=report['metrics']
            assert m['a2a_evaluated'] == m['eligible']
            assert m['screened']==m['raw_orderbook_markets']
            assert m['errors']==0
            assert report['execution_enabled'] is False
            assert report['mode']=='demo'
            assert all(a['action'] in ('BUY','SELL') for a in report['opportunities'])
            assert all('agents' in a and 'risk' in a['agents'] for a in report['opportunities'])
            resp=await client.post('/api/paper/preview',json={'symbol':'BTCIRT','side':'BUY','capital_quote':50000000},headers={'X-API-Key':'test-key-very-long-for-tests-only'})
            assert resp.status_code==200
            assert resp.json()['paper_only'] is True
            assert (await client.get('/a2a/orderflow/.well-known/agent-card.json')).status_code==200
            assert (await client.get('/')).status_code==200
    run(scenario())


def test_provider_cache_two_calls_one_snapshot():
    async def scenario():
        p=MarketProvider('demo',ttl=70)
        first=await p.get(); second=await p.get()
        assert first is second and p.calls==1
    run(scenario())


def test_api_key_prevents_unauthenticated_scan(monkeypatch):
    import app.server as s
    monkeypatch.setattr(s, 'API_KEY', 'a-test-key')
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
            assert (await c.get('/api/scan')).status_code==401
            assert (await c.get('/api/scan',headers={'X-API-Key':'wrong'})).status_code==401
            assert (await c.get('/api/scan?top_k=1',headers={'X-API-Key':'a-test-key'})).status_code==200
    run(scenario())


def test_live_fails_closed_without_fake_fallback(monkeypatch):
    provider=MarketProvider('live')
    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): return False
        async def get(self,url): raise httpx.ConnectError('no network')
    monkeypatch.setattr(httpx,'AsyncClient',lambda *args,**kwargs: FakeClient())
    async def scenario():
        with pytest.raises(RuntimeError, match='unavailable'):
            await provider.get()
        assert provider.calls==0
    run(scenario())
