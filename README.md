# Nobitex A2A × Dify — Market Intelligence

**A read-only, multi-agent market-analysis demonstration** built with Python, FastAPI, a JSON-RPC A2A subset, a local dashboard, and optional Dify/LLM workflow integration.

> **Safety first:** the public release starts in `demo` mode. `live` mode reads public Nobitex market data only. The application does not connect to private exchange accounts and does not place orders. Scores are heuristic rankings, not probabilities of profit.

**Author:** [Dr. Alireza Hakimi](https://alirezahakimi.ir) · [GitHub](https://github.com/DrAlirezaHakimi)

## Start here

- **[Interactive bilingual setup guide (Persian / English)](USER_GUIDE_BILINGUAL.html)** — step-by-step Windows, Linux, Docker and Dify instructions.
- [English overview](README_EN.md) · [راهنمای فارسی](README_FA.md)
- [Architecture (English)](docs/ARCHITECTURE_EN.md) · [معماری فارسی](docs/ARCHITECTURE_FA.md)
- [Dify deployment (Persian)](docs/DEPLOYMENT_DIFY_FA.md)
- [API reference (Persian)](docs/API_REFERENCE_FA.md)
- [Security policy](SECURITY.md) · [Security notes (Persian)](docs/SECURITY_FA.md)

## What it does

1. Reads public Nobitex market snapshots (order-book and market statistics) when live mode is explicitly enabled.
2. Screens spot markets for data freshness, spread, liquidity and market-status constraints.
3. Runs bounded parallel analysis through five logical agents: **orderflow, trend, liquidity, risk and decision**.
4. Exposes an A2A-style JSON-RPC API on port `8000` and a local dashboard on port `8001`.
5. Optionally calls a published Dify Workflow; an LLM may explain the Python-generated analysis but does not determine the numeric score.
6. Stores a small local execution history in SQLite.

## Quick start — Windows

1. Install Python 3.12 or newer.
2. Extract the project to a normal local folder.
3. Run `start_windows.bat`.
4. Open [http://127.0.0.1:8001](http://127.0.0.1:8001).

The first run uses synthetic `demo` data. To opt into public market data, edit the generated `.env` file and set:

```ini
MARKET_MODE=live
```

Restart the application after changing `.env`. If the public exchange API is unavailable, live mode reports an error rather than silently substituting synthetic values.

## Linux

```bash
chmod +x start_linux.sh run_linux.sh
./start_linux.sh
```

Open [http://127.0.0.1:8001](http://127.0.0.1:8001).

## Docker

Create a local `.env` file from `.env.example`, set a strong `API_KEY`, and run:

```bash
docker compose up --build -d
```

The Compose configuration binds services to loopback. Do not run native startup and Docker Compose simultaneously on the same ports.

## Dify integration

Import one of the YAML workflow files from `dify/` into Dify Studio, configure its backend URL and publish the workflow. For Dify Cloud, the A2A backend must be reachable through a valid HTTPS endpoint. Keep the dashboard on loopback; expose only the API port when needed. The Dify App API key belongs in the server-side `.env` file, never in browser code or a committed workflow.

## Important implementation boundaries

- The five agents are logical agents running in one Python process; they are not five separately deployed microservices.
- The A2A endpoint implements a limited JSON-RPC subset and does not claim full conformance with the current A2A SDK/specification.
- `SELL` means reduce/exit an already-owned spot position; short selling and margin are not supported.
- Scores are uncalibrated heuristics, not calibrated probabilities, guaranteed forecasts or expected returns.
- Stop/target and sizing values are illustrative calculations, not validated trading instructions.
- **Real order execution is not implemented and remains disabled.**

## Repository layout

```text
app/          Python A2A service, orchestration and agents
dashboard/    Local HTML dashboard
dify/         Importable Dify DSL workflows
docs/         Architecture, deployment, API and security documentation
tests/        Automated tests
outputs/      Synthetic sample data, explicitly marked as non-trading
```

## Tests

```bash
python -m pytest -q
```

## Security and responsible use

Never commit `.env`, API keys, ngrok tokens, private exchange credentials or local databases. Use `.env.example` only as a template. See [SECURITY.md](SECURITY.md) and [docs/SECURITY_FA.md](docs/SECURITY_FA.md).

## Copyright

© 2026 Dr. Alireza Hakimi. All rights reserved. This public repository is published for inspection and demonstration; no license to reuse, modify or redistribute is granted unless a separate license is published. See [COPYRIGHT.md](COPYRIGHT.md).
