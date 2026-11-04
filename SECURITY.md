# Security Policy

## Supported scope

This repository is a demonstration/research application. Security reports are welcome for the current source tree and documented deployment paths.

## Reporting a vulnerability

Please do not open a public issue containing exploit details, credentials, personal data, or a working attack. Contact the author through the contact details published at <https://alirezahakimi.ir> and provide:

- affected version/commit;
- impact and prerequisites;
- reproducible steps or a minimal proof of concept;
- suggested mitigation, if known.

Allow reasonable time for triage and remediation before public disclosure.

## Secret handling

Never commit `.env`, API keys, ngrok tokens, Dify Service API keys, passwords, or account credentials. If a secret is exposed, revoke/rotate it immediately; deleting it from the latest commit is not sufficient if it remains in Git history.

The backend should be exposed only behind HTTPS and appropriate access/rate controls. Keep dashboard port `8001` loopback-only. See [docs/SECURITY_FA.md](docs/SECURITY_FA.md).

## Security limitations

This project is not a hardened financial production system. Its A2A implementation is a limited subset, and no exchange order execution is implemented. Operators must independently review configuration, dependencies, network exposure and operational controls before deployment.
