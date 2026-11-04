# English Guide — Nobitex A2A × Dify Market Intelligence

This is a **read-only market-analysis demonstration**. The default `demo` mode uses clearly labelled synthetic data. The optional `live` mode reads public Nobitex market data only. Private exchange accounts, wallets and real order placement are not implemented.

## Windows quick start

1. Install Python 3.12 or newer.
2. Extract the project to a local folder.
3. Run `start_windows.bat`.
4. Open http://127.0.0.1:8001.
5. To opt into public market data, set `MARKET_MODE=live` in the generated local `.env` file and restart.

## Architecture

- Public market-data ingestion and quality screening
- Five logical agents: orderflow, trend, liquidity, risk and decision
- Python orchestration and FastAPI API on port 8000
- Local dashboard on port 8001
- Two importable Dify workflows: a base workflow and an optional LLM explainer

The agents run in one Python process; they are not separate microservices. The A2A endpoint implements a limited JSON-RPC subset and does not claim full conformance with the latest A2A SDK/specification.

## Dify setup

1. Import a YAML workflow from `dify/` into Dify Studio.
2. Configure the backend URL to reach the API on port 8000.
3. For Dify Cloud, expose only the API through HTTPS. Keep the dashboard loopback-only.
4. In Dify Environment Variables, set the Secret `A2A_API_KEY` to the same value as the local backend `API_KEY`; the workflow sends it in the `X-API-Key` header.
5. The Dify App API key created under Access Point is a different credential. Store it as `DIFY_API_KEY` in the local `.env` so the local dashboard can call the published workflow.
6. Never commit `.env`, API keys, ngrok tokens or private credentials.

## Linux and Docker

```bash
chmod +x start_linux.sh run_linux.sh
./start_linux.sh
```

For Docker, create a local `.env` from `.env.example`, set a strong `API_KEY`, then run:

```bash
docker compose up --build -d
```

## Safety boundaries

- Default mode is `demo`; `live` reads public market data only.
- Real order execution is not implemented and remains disabled.
- Scores are uncalibrated heuristic rankings, not probabilities of profit.
- Stop/target and position-size values are illustrative, not validated trading instructions.

See the [bilingual interactive setup guide](USER_GUIDE_BILINGUAL.html) for detailed steps.

© 2026 Dr. Alireza Hakimi. All rights reserved.
