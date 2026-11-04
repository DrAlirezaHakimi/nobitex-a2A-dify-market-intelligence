"""A2A JSON-RPC 2.0 message/send + tasks/get subset (protocol draft v0.2.6).
Real HTTP semantics via ASGI transport; not a claim of full A2A SDK compliance.
"""
import time
import uuid
import httpx
from .engine import orderflow_agent, trend_agent, liquidity_agent, risk_agent, judge_agent

AGENTS = {
    "orderflow": orderflow_agent, "trend": trend_agent, "liquidity": liquidity_agent,
    "risk": risk_agent, "decision": judge_agent,
}
TASKS = {}


def agent_card(name, base_url="http://127.0.0.1:8000"):
    return {
        "protocolVersion": "0.2.6", "name": "Hakimi " + name.title() + " Agent",
        "description": "Read-only quantitative market intelligence, paper analysis only",
        "url": f"{base_url.rstrip('/')}/a2a/{name}", "preferredTransport": "JSONRPC",
        "version": "0.1.0", "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["application/json"], "defaultOutputModes": ["application/json"],
        "skills": [{"id": name+"_analysis", "name": name.title()+" analysis",
                    "description": "Evaluate structured market data without placing trades", "tags": ["markets", "analysis", "read-only"]}],
    }


def task_response(value):
    task_id = str(uuid.uuid4()); context_id = str(uuid.uuid4())
    task = {"kind": "task", "id": task_id, "contextId": context_id,
            "status": {"state": "completed", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
            "artifacts": [{"artifactId": str(uuid.uuid4()), "name": "analysis", "parts": [{"kind": "data", "data": value}]}]}
    # bounded in-memory registry; no persistence beyond process lifetime
    if len(TASKS) > 1000:
        TASKS.clear()
    TASKS[task_id] = task
    return task


def handle_a2a(name, request):
    rid = request.get("id")
    def error(code, message):
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}
    if request.get("jsonrpc") != "2.0":
        return error(-32600, "Invalid JSON-RPC request")
    method = request.get("method")
    if method == "tasks/get":
        task = TASKS.get(str(request.get("params", {}).get("id", "")))
        return {"jsonrpc": "2.0", "id": rid, "result": task} if task else error(-32001, "Task not found")
    if method != "message/send":
        return error(-32601, "Unsupported A2A method")
    try:
        parts = request["params"]["message"]["parts"]
        data = next(p["data"] for p in parts if p.get("kind") == "data")
        if not isinstance(data, dict):
            return error(-32602, "Expected data part")
        fn = AGENTS[name]
        if name == "decision":
            value = fn(data["market"], data["orderflow"], data["trend"], data["liquidity"], data["risk"])
        elif name == "risk":
            value = fn(data["market"], requested_quote=float(data.get("budget_quote", 100_000_000 if data["market"]["quote"] == "IRT" else 1000)),
                       fee_bps=float(data.get("fee_bps", 30)))
        else:
            value = fn(data["market"])
        return {"jsonrpc": "2.0", "id": rid, "result": task_response(value)}
    except (KeyError, ValueError, TypeError, OverflowError) as exc:
        return error(-32602, "Invalid agent input: " + type(exc).__name__)


async def a2a_call(client: httpx.AsyncClient, name, data):
    rpc = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "message/send",
           "params": {"message": {"role": "user", "messageId": str(uuid.uuid4()), "parts": [{"kind": "data", "data": data}]}}}
    res = await client.post("/a2a/"+name, json=rpc)
    res.raise_for_status()
    body = res.json()
    if body.get("error"):
        raise RuntimeError(f"A2A {name}: {body['error']['message']}")
    return body["result"]["artifacts"][0]["parts"][0]["data"]


async def deep_evaluate(client, market, budget_irt, budget_usdt, fee_bps):
    budget = budget_irt if market["quote"] == "IRT" else budget_usdt
    payload = {"market": market, "budget_quote": budget, "fee_bps": fee_bps}
    import asyncio
    flow, trend, liquidity, risk = await asyncio.gather(*(
        a2a_call(client, name, payload) for name in ["orderflow", "trend", "liquidity", "risk"]))
    decision = await a2a_call(client, "decision", {**payload, "orderflow": flow,
                                                    "trend": trend, "liquidity": liquidity, "risk": risk})
    action = decision["action"]
    entry = decision["entry_reference"]
    # Price levels are arithmetic illustrations, NOT empirically optimized targets.
    if action == "BUY":
        distance = risk["stop_distance_pct_hypothetical"] / 100
        plan = {"kind": "PROPOSED_SPOT_BUY_ONLY", "entry_reference": entry,
                "stop_loss_reference": round(entry * (1-distance), 8),
                "take_profit_1_reference": round(entry * (1+distance*1.8), 8),
                "take_profit_2_reference": round(entry * (1+distance*2.5), 8),
                "rr_gross_before_costs": [1.8, 2.5], "max_notional_quote": risk["max_notional_quote"],
                "requires_human_approval": True, "execution": "disabled"}
    elif action == "SELL":
        plan = {"kind": "REDUCE_OR_EXIT_EXISTING_SPOT_HOLDING", "exit_reference": entry,
                "requires_existing_holding": True, "short_selling": False,
                "requires_human_approval": True, "execution": "disabled"}
    else:
        plan = {"kind": "NO_TRADE", "execution": "disabled"}
    return {**market, "action": action, "score": decision["score"],
            "entry_reference": entry, "invalidation": decision["invalidation"],
            "explanation": decision["explanation"], "risk": risk, "plan": plan,
            "agents": {"orderflow": flow, "trend": trend, "liquidity": liquidity, "risk": risk, "decision": decision}}
