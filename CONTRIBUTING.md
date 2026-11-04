# Contributing

This repository is currently published for review and demonstration. Before proposing a change:

1. Open an issue describing the problem or proposed improvement.
2. Keep changes focused and document behavior changes.
3. Add or update tests for changed logic.
4. Run `python -m pytest -q` and `python -m compileall -q app tests`.
5. Never include `.env`, keys, account data, private market-account exports or personal data.
6. Do not add order execution, margin/shorting, or private-account access without a separate design and explicit security review.
7. Preserve the distinction between heuristic ranking and calibrated predictive performance.

Pull requests should explain the motivation, implementation, tests, and any security or data-quality implications.
