"""FastAPI orchestrator: A2A JSON-RPC, bounded parallel processing, read-only market scanner."""
import asyncio
import os
import secrets
import time
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .engine import MarketProvider, parse_markets, screening
from .a2a_protocol import AGENTS, agent_card, a2a_call, deep_evaluate, handle_a2a

MODE = os.getenv("MARKET_MODE", "demo").lower()
PROVIDER = MarketProvider(MODE, ttl=int(os.getenv("MARKET_TTL", "70")))
API_KEY = os.getenv("API_KEY", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
MAX_PARALLEL = min(20, max(1, int(os.getenv("MAX_PARALLEL", "12"))))
MAX_DEEP = min(1000, max(1, int(os.getenv("MAX_DEEP", "300"))))

app = FastAPI(title="Hakimi A2A Nobitex Intelligence", version="0.1.0", description="Analysis-only. No exchange credentials or live order placement.")


def require_key(key: str | None):
    if not API_KEY:
        raise HTTPException(503, "API_KEY must be configured on server")
    if not secrets.compare_digest(key or "", API_KEY):
        raise HTTPException(401, "Valid X-API-Key required")


@app.get("/")
async def index():
    return {"service":"A2A read-only API", "public_dashboard":False, "execution_enabled":False}


@app.get("/health")
async def health():
    return {"ok": True, "market_mode": MODE, "trading_enabled": False, "a2a_agents": list(AGENTS),
            "provider_calls": PROVIDER.calls, "api_key_enabled": bool(API_KEY)}


@app.get("/.well-known/agent-card.json")
@app.get("/.well-known/agent.json")
async def orchestrator_card():
    card = agent_card("decision", PUBLIC_BASE_URL)
    card["name"] = "Hakimi Market Orchestrator"
    card["url"] = PUBLIC_BASE_URL+"/a2a/decision"
    card["description"] = "A2A-compatible subset; route /api/scan performs read-only market scan"
    return card


@app.get("/a2a/{agent_name}/.well-known/agent-card.json")
@app.get("/a2a/{agent_name}/.well-known/agent.json")
async def agent_discovery(agent_name: str):
    if agent_name not in AGENTS:
        raise HTTPException(404, "Unknown agent")
    return agent_card(agent_name, PUBLIC_BASE_URL)


@app.post("/a2a/{agent_name}")
async def agent_rpc(agent_name: str, request: Request, x_api_key: str | None = Header(None)):
    require_key(x_api_key)
    if agent_name not in AGENTS:
        raise HTTPException(404, "Unknown agent")
    if int(request.headers.get("content-length", "0") or "0") > 100_000:
        raise HTTPException(413, "A2A body too large")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required")
    return handle_a2a(agent_name, payload)


class PaperPreviewRequest(BaseModel):
    symbol: str = Field(..., max_length=30)
    side: str
    capital_quote: float = Field(..., gt=0, le=1e15)
    fee_bps_per_side: float = Field(30, ge=0, le=200)
    stop_distance_pct: float = Field(2.0, gt=0, le=50)
    risk_fraction: float = Field(.005, gt=0, le=.02)


@app.post("/api/paper/preview")
async def paper_preview(data: PaperPreviewRequest, x_api_key: str | None = Header(None)):
    require_key(x_api_key)
    if data.side not in ("BUY", "SELL"):
        raise HTTPException(400, "Only BUY/SELL scenarios; SELL requires pre-existing holding")
    books, stats = await PROVIDER.get()
    market = next((m for m in parse_markets(books, stats) if m["symbol"] == data.symbol.upper()), None)
    if not market:
        raise HTTPException(404, "Market not found")
    blockers = screening(market)
    if blockers:
        return {"status": "BLOCKED", "reasons": blockers, "symbol": market["symbol"], "paper_only": True}
    from .engine import risk_agent
    risk = risk_agent(market, data.capital_quote, data.fee_bps_per_side, data.risk_fraction)
    # This is a quote-denominated notional cap, not a fill or actual order.
    allowed = risk["max_notional_quote"]
    approximate_qty = allowed / (market["ask"] if data.side == "BUY" else market["bid"])
    return {"status": "PAPER_PREVIEW", "paper_only": True, "symbol": market["symbol"], "side": data.side,
            "quote": market["quote"], "entry_reference": market["ask"] if data.side=="BUY" else market["bid"],
            "maximum_notional_quote": allowed, "approximate_base_quantity": round(approximate_qty, 10),
            "risk_limit": risk, "notice": "No live trading. Not a backtest, execution or profit guarantee."}


@app.get("/api/scan")
async def scan(top_k: int = Query(12, ge=1, le=100),
               budget_irt: float = Query(100_000_000, gt=0, le=1e15),
               budget_usdt: float = Query(1000, gt=0, le=1e9),
               fee_bps: float = Query(30, ge=0, le=200),
               x_api_key: str | None = Header(None)):
    require_key(x_api_key)
    started = time.perf_counter()
    try:
        books, stats = await PROVIDER.get()
        universe = parse_markets(books, stats)
        raw_market_count = sum(isinstance(v, dict) and k != "status" for k,v in books.items())
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    accepted, denied = [], []
    for m in universe:
        why = screening(m)
        if why:
            denied.append({"symbol": m["symbol"], "quote": m["quote"], "reasons": why})
        else:
            accepted.append(m)
    # Every valid symbol is screened; deep A2A analysis is bounded and transparent.
    accepted.sort(key=lambda m: (abs(m["imbalance"])*.65 + min(abs(m["day_change_pct"])/8, 1)*.35), reverse=True)
    selected = accepted[:MAX_DEEP]
    sem = asyncio.Semaphore(MAX_PARALLEL)
    # In-process HTTP transport still uses true JSON-RPC request/response and routes;
    # external services can replace this client with network transport to the same Agent Cards.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://internal-a2a", timeout=25.0,
                                 headers={"X-API-Key": API_KEY} if API_KEY else {}) as a2a_client:
        async def run(m):
            async with sem:
                try:
                    return await deep_evaluate(a2a_client, m, budget_irt, budget_usdt, fee_bps)
                except Exception as e:
                    return {**m, "action": "ERROR", "score": 0, "error": type(e).__name__}
        results = await asyncio.gather(*(run(m) for m in selected))
    # Only eligible and evaluated markets are considered, and HOLD is not an opportunity.
    buy = sorted((r for r in results if r["action"] == "BUY"), key=lambda r: r["score"], reverse=True)
    sell = sorted((r for r in results if r["action"] == "SELL"), key=lambda r: r["score"], reverse=True)
    hold = sum(r["action"] == "HOLD" for r in results)
    errors = sum(r["action"] == "ERROR" for r in results)
    top = sorted(buy + sell, key=lambda r: r["score"], reverse=True)[:top_k]
    accepted_symbols = {m["symbol"] for m in accepted}
    return {"project": "Hakimi Nobitex A2A Market Intelligence", "mode": MODE,
            "data_status": "SYNTHETIC DEMONSTRATION DATA" if MODE == "demo" else "LIVE PUBLIC SNAPSHOT (not authenticated, not streaming)",
            "generated_at": datetime.now(timezone.utc).isoformat(), "execution_enabled": False,
            "metrics": {"raw_orderbook_markets": raw_market_count, "invalid_or_unsupported": raw_market_count - len(universe),
                        "symbols_in_valid_books": len(universe), "screened": len(universe),
                        "rejected": len(denied), "eligible": len(accepted), "a2a_evaluated": len(results),
                        "a2a_skipped_limit": max(0, len(accepted)-len(selected)),
                        "buy_candidates": len(buy), "sell_candidates": len(sell), "hold": hold, "errors": errors,
                        "elapsed_ms": round((time.perf_counter()-started)*1000, 2),
                        "external_calls_since_start": PROVIDER.calls},
            "best_buy": buy[0] if buy else None, "best_sell": sell[0] if sell else None,
            "recommendation": top[0] if top else None, "opportunities": top,
            "market_universe": [{"symbol": m["symbol"], "quote": m["quote"],
                                 "spread_bps": m["spread_bps"], "imbalance": m["imbalance"],
                                 "day_change_pct": m["day_change_pct"],
                                 "screen": "ELIGIBLE" if m["symbol"] in accepted_symbols else "FILTERED"} for m in universe],
            "excluded_examples": denied[:20],
            "method": {"policy": "SCREEN_ALL_THEN_A2A_BOUNDED", "parallel_limit": MAX_PARALLEL,
                       "max_deep": MAX_DEEP, "signals": "Orderbook imbalance + 24h change + liquidity gate",
                       "score": "Heuristic ranking, NOT predicted win probability",
                       "liquidity": "Quote-denominated; IRT and USDT amounts are not directly comparable",
                       "short_selling": "Not supported; SELL means exit/reduce owned spot holdings",
                       "fee_bps_per_side_assumed": fee_bps,
                       "limitation": "No OHLC backtest, maker/taker model calibration, private balances, or real fill simulation"}}
