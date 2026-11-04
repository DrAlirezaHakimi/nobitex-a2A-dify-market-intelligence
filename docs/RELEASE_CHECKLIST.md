# Public release checklist

- [x] Public repository created on GitHub.
- [x] Bilingual README and offline-friendly Persian/English HTML setup guide added.
- [x] A2A API, five logical agent modules and local dashboard source added.
- [x] Base and optional LLM Dify workflows added.
- [x] Dify workflows use a Secret environment variable for the A2A API key.
- [x] `.env.example` contains placeholders only; no real credentials are required.
- [x] `.gitignore` excludes local secrets, databases, caches and Python bytecode.
- [x] Default mode is `demo`; live mode reads public market data only.
- [x] Dashboard is loopback-only; public exposure is not intended.
- [x] Documentation distinguishes logical agents from separate microservices.
- [x] Documentation states that A2A is a limited JSON-RPC subset.
- [x] Documentation states that scores are heuristics and real trading is disabled.
- [x] Local validation: `python -m compileall -q app tests` succeeded.
- [x] Local validation: `python -m pytest -q` — 17 passed.
- [ ] Verify GitHub Actions workflow after initial push.
- [ ] Re-import or update existing Dify workflows with the secured YAML and set the A2A_API_KEY secret in Dify Studio.
