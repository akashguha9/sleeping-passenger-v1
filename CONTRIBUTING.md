# Contributing

**External contributions are not accepted.**

This is a proprietary, owner-only MVP controlled by Akash Guha
(see [PROPRIETARY_NOTICE.md](PROPRIETARY_NOTICE.md) and [LICENSE](LICENSE)).
There is no contributor license, no CLA, and no intention to accept pull
requests, issues, or patches from third parties. Unsolicited submissions
grant no rights and create no obligations.

If you believe you have found a security issue, see [SECURITY.md](SECURITY.md).
For licensing inquiries: akashguha@outlook.com.

## Note for automated coding passes (Claude/GPT/etc.)

When editing this repo, follow the secret-fixture hygiene rule
(SECURITY.md, "Secret fixture hygiene"): never place `REDACTED` or
fake-looking tokens beside key/token/secret/password names, and never
commit realistic token shapes (`sk-…`, `ghp_…`, `AKIA…`). Use
`tests/helpers/scanner_probes.py` for secret-shaped test probes and the
`*_FOR_TESTS_ONLY` sentinels everywhere else.
`python scripts/secret_fixture_lint.py` must pass before committing.
