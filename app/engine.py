"""Market scanner and safety-first, deterministic scenario ranking.
This is a *research prototype*; scores are not probabilities or expected returns.
"""
import asyncio
import math
import random
import time
from datetime import datetime, timezone
from typing import Any

import httpx

API_BASE = "https://apiv2.nobitex.ir"
SYMBOL_BASES = ["BTC", "ETH", "USDT", "SOL", "XRP", "ADA", "DOGE", "LINK", "TRX", "LTC", "AVAX", "DOT", "BNB", "BCH", "ETC", "ATOM", "UNI", "TON", "SHIB", "XLM", "NEAR", "ARB", "OP", "AAVE", "FIL", "MATIC", "SAND", "AXS", "CHZ", "MANA", "FTM", "EOS"]


def num(value: Any, default: float = 0.0) -> float:
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError, OverflowError):
        return default


def clamp(n, low, high):
    return max(low, min(high, n))


def norm_symbol(symbol):
    s = str(symbol).upper().replace("-", "").replace("_", "")
    if s.endswith("RLS"):
        s = s[:-3] + "IRT"
    return s


def stats_symbol(symbol):
    s = str(symbol).lower()
    if "-" in s:
        base, quote = s.split("-", 1)
        return (base + ("irt" if quote in ("rls", "irt") else quote)).upper()
    return norm_symbol(s)


def synthetic_market(seed=42, count=64, now=None):
    """Clearly synthetic values and fresh timestamps; NO real exchange access."""
    rnd = random.Random(seed)
    now = now or int(time.time() * 1000)
    books, stats = {"status": "ok"}, {"status": "ok", "stats": {}}
    pairs = [b + q for q in ("IRT", "USDT") for b in SYMBOL_BASES if not (b == "USDT" and q == "USDT")][:count]
    for idx, sym in enumerate(pairs):
        is_irt = sym.endswith("IRT")
        base = sym[:-3] if is_irt else sym[:-4]
        price = (rnd.uniform(2e4, 5e7) if is_irt else rnd.uniform(.02, 2200))
        if base == "BTC": price = 1e11 if is_irt else 82000
        if base == "ETH": price = 4e9 if is_irt else 3100
        spread = rnd.uniform(.0003, .008)
        book_imbalance = rnd.uniform(-.70, .70)
        bid = price * (1 - spread/2)
        ask = price * (1 + spread/2)
        capital = rnd.uniform(4e8, 40e9) if is_irt else rnd.uniform(3000, 120000)
        bids, asks = [], []
        for depth in range(10):
            pb, pa = bid*(1-depth*.0005), ask*(1+depth*.0005)
            quote = capital/10
            bids.append([str(round(pb, 8)), str(round(quote*(1+book_imbalance)/pb, 9))])
            asks.append([str(round(pa, 8)), str(round(quote*(1-book_imbalance)/pa, 9))])
        day_change = rnd.uniform(-5, 5) + 2*book_imbalance
        books[sym] = {"bids": bids, "asks": asks, "lastUpdate": now - rnd.randint(500, 12000), "lastTradePrice": str(price)}
        key = base.lower() + "-" + ("rls" if is_irt else "usdt")
        stats["stats"][key] = {"isClosed": False, "dayChange": str(round(day_change, 4)), "volumeDst": str(capital*4), "latest": str(price), "dayHigh": str(price*1.04), "dayLow": str(price*.96)}
    return books, stats


class MarketProvider:
    def __init__(self, mode="demo", ttl=65):
        if mode not in ("demo", "live"):
            raise ValueError("MARKET_MODE must be demo or live")
        self.mode, self.ttl, self._lock, self._cache = mode, max(60, ttl), asyncio.Lock(), None
        self._cached_at = 0.0
        self.calls = 0

    async def get(self):
        async with self._lock:
            if self._cache and time.monotonic() - self._cached_at < self.ttl:
                return self._cache
            if self.mode == "demo":
                books, stats = synthetic_market()
            else:
                timeout = httpx.Timeout(15.0, connect=6.0)
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                    try:
                        responses = await asyncio.gather(
                            client.get(API_BASE + "/v3/orderbook/all"),
                            client.get(API_BASE + "/market/stats"),
                        )
                        for response in responses:
                            response.raise_for_status()
                        books, stats = (r.json() for r in responses)
                    except (httpx.HTTPError, ValueError) as exc:
                        raise RuntimeError(f"Nobitex market data unavailable: {type(exc).__name__}") from exc
                if books.get("status") != "ok" or stats.get("status") != "ok":
                    raise RuntimeError("Nobitex returned non-ok status")
            self.calls += 1
            self._cache, self._cached_at = (books, stats), time.monotonic()
            return self._cache


def parse_markets(books, stats, now_ms=None):
    now_ms = now_ms or int(time.time() * 1000)
    stats_by_symbol = {stats_symbol(k): v for k, v in stats.get("stats", {}).items() if isinstance(v, dict)}
    result = []
    for key, item in books.items():
        if key == "status" or not isinstance(item, dict):
            continue
        sym = norm_symbol(key)
        if not sym.endswith(("IRT", "USDT")):
            continue
        def clean_levels(raw, descending=False):
            if not isinstance(raw, list):
                return []
            out = []
            for row in raw[:15]:
                if not isinstance(row, (list, tuple)) or len(row) < 2:
                    continue
                p, q = num(row[0]), num(row[1])
                if p > 0 and q > 0:
                    out.append((p, q))
            return sorted(out, key=lambda t: t[0], reverse=descending)
        bids = clean_levels(item.get("bids"), descending=True)
        asks = clean_levels(item.get("asks"), descending=False)
        if not bids or not asks:
            continue
        bid, ask = bids[0][0], asks[0][0]
        if ask <= bid:
            # Crossed/stale orderbook -> do not issue scenario
            continue
        mid = (bid+ask)/2
        spread_bps = (ask-bid)/mid*10000
        buy_depth = sum(p*q for p, q in bids[:10]); sell_depth = sum(p*q for p, q in asks[:10])
        imbalance = (buy_depth-sell_depth)/(buy_depth+sell_depth) if buy_depth+sell_depth else 0
        market_stat = stats_by_symbol.get(sym, {})
        quote = "IRT" if sym.endswith("IRT") else "USDT"
        last_update = num(item.get("lastUpdate"), 0)
        age_s = max(0.0, (now_ms - last_update)/1000) if last_update > 0 else float("inf")
        # Quote currencies are not comparable in raw magnitude; do not rank across currencies by depth.
        result.append({
            "symbol": sym, "quote": quote, "bid": bid, "ask": ask, "mid": mid,
            "spread_bps": round(spread_bps, 2), "imbalance": round(imbalance, 5),
            "bid_depth_quote": round(buy_depth, 2), "ask_depth_quote": round(sell_depth, 2),
            "total_depth_quote": round(buy_depth+sell_depth, 2),
            "day_change_pct": round(num(market_stat.get("dayChange")), 3),
            "volume_24h_quote": round(num(market_stat.get("volumeDst")), 2),
            "stats_found": bool(market_stat), "is_closed": bool(market_stat.get("isClosed", False)),
            "age_seconds": round(age_s, 2) if math.isfinite(age_s) else None,
            "last_update": int(last_update),
        })
    return result


def screening(m, max_age=120, max_spread_bps=80):
    reasons = []
    if m.get("age_seconds") is None or m["age_seconds"] > max_age:
        reasons.append("داده اردربوک قدیمی یا بدون زمان معتبر")
    if not m["stats_found"]:
        reasons.append("آمار ۲۴ ساعته موجود نیست")
    if m["is_closed"]:
        reasons.append("بازار بسته است")
    if m["spread_bps"] > max_spread_bps:
        reasons.append("اسپرد بالاتر از سقف تعریف‌شده")
    min_depth = 300_000_000 if m["quote"] == "IRT" else 3000
    min_volume = 1_000_000_000 if m["quote"] == "IRT" else 10_000
    if m["total_depth_quote"] < min_depth:
        reasons.append("عمق دفتر سفارش ناکافی")
    if m["volume_24h_quote"] < min_volume:
        reasons.append("گردش ۲۴ ساعته ناکافی")
    return reasons


def orderflow_agent(m):
    im = m["imbalance"]
    return {"agent": "orderflow", "bias": "BUY" if im > .18 else "SELL" if im < -.18 else "HOLD",
            "strength": round(clamp(abs(im), 0, 1), 4),
            "reason": "عدم تعادل سفارش‌های ۱۰ ردیف اول؛ نشانه موقت و قابل دست‌کاری"}


def trend_agent(m):
    change = m["day_change_pct"]
    return {"agent": "trend", "bias": "BUY" if change > .6 else "SELL" if change < -.6 else "HOLD",
            "strength": round(clamp(abs(change)/7, 0, 1), 4),
            "reason": "تغییرات ۲۴ ساعت گذشته؛ نه پیش‌بینی آینده"}


def liquidity_agent(m):
    cost_bps = m["spread_bps"]/2
    return {"agent": "liquidity", "spread_bps": m["spread_bps"], "one_way_half_spread_bps": round(cost_bps, 2),
            "depth_quote": m["total_depth_quote"], "reason": "اسپرد و عمق لحظه‌ای؛ لغزش واقعی به حجم سفارش بستگی دارد"}


def risk_agent(m, requested_quote=100_000_000, fee_bps=30, risk_fraction=.005):
    # Units: requested quote amount and quote currency remain coupled; this is a cap, NOT an order.
    depth_limit = .005 * min(m["bid_depth_quote"], m["ask_depth_quote"])
    max_notional = min(requested_quote, depth_limit)
    fee_round_trip_bps = 2*fee_bps
    friction_bps = fee_round_trip_bps + m["spread_bps"]
    # Protective stop is a hypothetical scenario threshold, not a guaranteed fill.
    stop_distance_pct = clamp(1.6 + abs(m["day_change_pct"])*.12, 1.5, 3.5)
    capital_for_risk = requested_quote  # illustrative: use same-unit capital cap as input
    risk_budget = capital_for_risk * risk_fraction
    size_by_stop = risk_budget / (stop_distance_pct/100 + friction_bps/10000) if stop_distance_pct > 0 else 0
    max_notional = min(max_notional, size_by_stop)
    return {"agent": "risk", "max_notional_quote": round(max(0, max_notional), 2),
            "quote": m["quote"], "stop_distance_pct_hypothetical": round(stop_distance_pct, 2),
            "estimated_round_trip_fee_bps": fee_round_trip_bps, "friction_proxy_bps": round(friction_bps, 2),
            "max_risk_fraction": risk_fraction,
            "reason": "محدودیت نمادین اندازه موقعیت، کارمزد فرضی و حد توقف فرضی؛ تضمین اجرای قیمت وجود ندارد"}


def judge_agent(m, flow, trend, liquidity, risk):
    signs = (flow["bias"], trend["bias"])
    alignment = (signs[0] == signs[1] and signs[0] != "HOLD")
    # A score for relative triage, *not* P(win) or forward expected return.
    score = (28*flow["strength"] + 20*trend["strength"] +
             16*(1-min(1, m["spread_bps"]/80)) + 12*int(alignment))
    score = round(clamp(score, 0, 100), 1)
    friction = risk["friction_proxy_bps"]
    # This is only a heuristic gate, not a validated statistical edge.
    if alignment and score >= 30 and m["spread_bps"] < 65 and friction < 125 and risk["max_notional_quote"] > 0:
        side = flow["bias"]
    else:
        side = "HOLD"
    return {"agent": "decision", "action": side, "score": score,
            "confidence_type": "uncalibrated heuristic score; NOT a success probability",
            "entry_reference": round(m["ask"] if side == "BUY" else m["bid"] if side == "SELL" else m["mid"], 8),
            "invalidation": "ابطال با تغییر جهت عدم‌تعادل، گسترش اسپرد، بسته‌شدن بازار یا قدیمی‌شدن داده",
            "explanation": "هم‌جهتی نشانه‌های اردربوک و تغییر روزانه" if alignment else "شواهد هم‌جهت کافی نیست؛ عدم معامله",
            "short_sale_allowed": False,
            "advice": "سیگنال پژوهشی، بدون توصیه قطعی یا سفارش واقعی"}
