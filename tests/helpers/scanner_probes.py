"""Secret-*shaped* probe strings for redaction/refusal tests — runtime-assembled.

Several modules must refuse or redact text that looks like a credential
(``scripts/data_quality.py``, ``scripts/compliance_preflight.py``,
``scripts/ai_output_schema.py``, ``scripts/source_health_summary.py``, …).
The tests proving that behavior need strings that match those detectors at
runtime.  But committing such strings verbatim turns the test suite into
secret-scanner bait: gitleaks' ``generic-api-key`` rule (and any similar
scanner) cannot tell a synthetic fixture from a real leak, and CI fails on
a false positive (this happened — see ``scripts/secret_fixture_lint.py``).

Rule (enforced by ``scripts/secret_fixture_lint.py`` and documented in
SECURITY.md): never write a literal ``<keyword><operator><value>``
credential shape into tracked source.  Assemble it here from fragments so
the probe only ever exists in process memory.

Conventions that keep this file itself scanner-clean:
  * credential keywords are split *inside* the keyword (``"ap", "i_k", "ey"``)
    so no fragment contains a whole keyword such as ``key`` or ``token``;
  * value fragments stay under 10 characters (below the minimum match
    length of generic secret rules) and are never adjacent to a keyword.

Every value below is synthetic.  None of these are, or ever were, real
credentials.  This file is allow-listed in ``scripts/secret_fixture_lint.py``.
"""
from __future__ import annotations


def assemble(*fragments: str) -> str:
    """Join fragments at runtime so the joined text never appears in source."""
    return "".join(fragments)


# Credential keywords, split mid-word (see module docstring).
KW_API_KEY = assemble("ap", "i_k", "ey")          # the api-key keyword
KW_PASSWORD = assemble("pass", "wo", "rd")        # the password keyword
KW_XAI_API_KEY = assemble("XAI", "_AP", "I_K", "EY")
KW_MVP_API_TOKEN = assemble("MVP", "_AP", "I_TO", "KEN")


def sk_style_token(suffix: str = "") -> str:
    """An OpenAI-style ``sk-…`` shaped token (synthetic)."""
    return assemble("sk", "-") + (suffix or "a" * 20)


def xai_style_token(suffix: str = "") -> str:
    """An xAI-style ``xai-…`` shaped token (synthetic)."""
    return assemble("xa", "i-") + (suffix or "b" * 20)


def api_key_assignment(value: str = "") -> str:
    """``<api-key keyword>=<value>`` — the canonical generic-api-key shape."""
    return KW_API_KEY + "=" + (value or assemble("abcd", "1234", "efgh", "5678"))


def password_assignment() -> str:
    """``<password keyword>: <value>`` shape."""
    return KW_PASSWORD + ": " + assemble("hunter2", "hunter2")


def bearer_probe() -> str:
    """``Bearer <opaque>`` Authorization-header shape."""
    return "Bearer " + assemble("abcdefgh", "ijklmnop", "1234")


def high_entropy_token() -> str:
    """A 32-char high-entropy opaque value (synthetic)."""
    return assemble("z9b8a7c6", "d5e4f3g2", "h1i0j9k8", "l7m6n5o4")
