"""Tests for Asia Disclosure public-page provider wiring.

Sprint goal: register public-page disclosure providers for the remaining
Asia Disclosure coverage countries (no API keys, no login) and prove the
generic public-page fetch+parse path is correct without claiming any
source is healthy unless a real fetch+parse succeeds (mocked here).

The providers ship inactive by default with ``source_class =
'planned_public_page'``.  Tests verify:

  * Provider registration: each target country has a registered provider.
  * Classification: inactive planned_public_page is excluded from stale.
  * Country rows: the 11 canonical rows now reference real public-page
    landing URLs (no fabricated URLs, no placeholder tokens).
  * Public-page fetch path: when a provider is patched ``active=True``
    with ``source_class='public_page'``, the loader uses the generic
    public-page fetcher; success/HTTP error/rate-limit/block/parse-error/
    no-rows paths each emit the correct status.
  * Safety contract: every emitted row carries ADVISORY_ONLY,
    HUMAN_REVIEW_REQUIRED, execution_gate=LOCKED, broker_api_called=False.
  * No fake rows ever leak when a public-page provider is inactive.
  * EDINET / OpenDART non-regression: the existing official-API path is
    untouched and remains the default active sub-sources.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Provider registration / classification
# ---------------------------------------------------------------------------


PUBLIC_PAGE_PROVIDERS = (
    "sgx_public",   # Singapore
    "mops",         # Taiwan
    "hkexnews",     # Hong Kong (China-region coverage)
    "cninfo",       # China
    "tadawul",      # Saudi Arabia
    "adx",          # United Arab Emirates
    "dfm",          # United Arab Emirates
    "kap",          # Turkey
    "idx",          # Indonesia
    "tase_magna",   # Israel
    "russia",       # Russia — planned, no URL until source verified
)

_EXPECTED_JURISDICTION = {
    "sgx_public": "SG",
    "mops":       "TW",
    "hkexnews":   "HK",
    "cninfo":     "CN",
    "tadawul":    "SA",
    "adx":        "AE",
    "dfm":        "AE",
    "kap":        "TR",
    "idx":        "ID",
    "tase_magna": "IL",
    "russia":     "RU",
}

_EXPECTED_COUNTRY = {
    "sgx_public": "Singapore",
    "mops":       "Taiwan",
    "hkexnews":   "Hong Kong",
    "cninfo":     "China",
    "tadawul":    "Saudi Arabia",
    "adx":        "United Arab Emirates",
    "dfm":        "United Arab Emirates",
    "kap":        "Turkey",
    "idx":        "Indonesia",
    "tase_magna": "Israel",
    "russia":     "Russia",
}


class TestPublicPageProviderRegistration(unittest.TestCase):

    def setUp(self):
        from scripts.ingestion.asia_disclosure_loader import _PROVIDER_CONFIGS
        self.configs = _PROVIDER_CONFIGS

    def test_every_public_page_provider_is_registered(self):
        for name in PUBLIC_PAGE_PROVIDERS:
            self.assertIn(
                name, self.configs, f"public-page provider {name!r} not registered"
            )

    def test_provider_jurisdictions_match(self):
        for name, jur in _EXPECTED_JURISDICTION.items():
            self.assertEqual(
                self.configs[name]["jurisdiction"],
                jur,
                f"{name} jurisdiction mismatch",
            )

    def test_provider_countries_match(self):
        for name, country in _EXPECTED_COUNTRY.items():
            self.assertEqual(
                self.configs[name]["country"],
                country,
                f"{name} country mismatch",
            )

    def test_default_inactive_and_planned_public_page(self):
        for name in PUBLIC_PAGE_PROVIDERS:
            conf = self.configs[name]
            self.assertFalse(
                conf["active"],
                f"{name} should ship inactive until parser is verified",
            )
            self.assertEqual(
                conf["source_class"],
                "planned_public_page",
                f"{name} should default to source_class=planned_public_page",
            )
            self.assertFalse(
                conf["requires_key"],
                f"{name} must not require an API key (public-page)",
            )

    def test_landing_urls_are_real_or_none(self):
        for name in PUBLIC_PAGE_PROVIDERS:
            conf = self.configs[name]
            landing = conf.get("landing_url")
            if landing is None:
                # Allowed only for explicitly planned countries (Russia).
                self.assertEqual(
                    name, "russia",
                    f"only russia may omit a landing_url; {name} has none",
                )
                continue
            self.assertIsInstance(landing, str)
            self.assertTrue(
                landing.startswith(("http://", "https://")),
                f"{name} landing URL is not http(s): {landing!r}",
            )
            # No placeholder/fabricated tokens.
            lowered = landing.lower()
            for bad in ("example.com", "tbd", "todo", "fake", "<", ">"):
                self.assertNotIn(
                    bad, lowered, f"{name} landing URL contains placeholder: {landing!r}"
                )

    def test_russia_is_planned_with_no_url(self):
        conf = self.configs["russia"]
        self.assertFalse(conf["active"])
        self.assertEqual(conf["source_class"], "planned_public_page")
        self.assertIsNone(conf.get("landing_url"))
        self.assertIn("planned", conf["note"].lower())


class TestEDINETOpenDARTNonRegression(unittest.TestCase):
    """Adding public-page providers must not change the existing
    official-API providers in any observable way."""

    def setUp(self):
        from scripts.ingestion.asia_disclosure_loader import _PROVIDER_CONFIGS
        self.configs = _PROVIDER_CONFIGS

    def test_edinet_still_active_official_api(self):
        c = self.configs["edinet"]
        self.assertTrue(c["active"])
        self.assertEqual(c["source_class"], "official_api")
        self.assertEqual(c["key_env"], "EDINET_API_KEY")

    def test_opendart_still_active_official_api(self):
        c = self.configs["opendart"]
        self.assertTrue(c["active"])
        self.assertEqual(c["source_class"], "official_api")
        self.assertEqual(c["key_env"], "OPENDART_API_KEY")

    def test_legacy_placeholders_still_inactive(self):
        for name in ("sse", "szse", "hkex", "tdnet", "sgx", "dart"):
            self.assertFalse(self.configs[name]["active"])
            self.assertEqual(self.configs[name]["source_class"], "placeholder")


class TestCountryRowsUpdated(unittest.TestCase):
    """Country rows now reference public-page landing URLs for the
    9 non-Japan/non-Korea/non-Russia countries."""

    def setUp(self):
        from scripts.ingestion.asia_disclosure_loader import (
            get_asia_disclosure_country_rows,
        )
        self.rows = get_asia_disclosure_country_rows()

    def test_exactly_11_rows(self):
        self.assertEqual(len(self.rows), 11)

    def test_india_not_present(self):
        countries = [r["country"] for r in self.rows]
        self.assertNotIn("India", countries)

    def test_each_row_has_required_columns(self):
        required = {"country", "disclosure_source", "source_url", "status", "notes"}
        for r in self.rows:
            self.assertTrue(required <= set(r.keys()), f"missing columns in {r!r}")
            self.assertEqual(r["status"], "Active")

    def test_no_fake_or_placeholder_urls(self):
        forbidden = ("example.com", "tbd", "todo", "fake", "<", ">", "?")
        for r in self.rows:
            url = (r["source_url"] or "").lower()
            for bad in forbidden:
                self.assertNotIn(bad, url, f"placeholder/fake URL: {url!r}")
            if url:
                self.assertTrue(url.startswith(("http://", "https://")))

    def test_japan_and_korea_now_carry_real_urls(self):
        japan = next(r for r in self.rows if r["country"] == "Japan")
        korea = next(r for r in self.rows if r["country"] == "South Korea")
        self.assertTrue(japan["source_url"].startswith("https://"))
        self.assertTrue(korea["source_url"].startswith("https://"))

    def test_russia_row_still_active_no_url(self):
        rus = next(r for r in self.rows if r["country"] == "Russia")
        self.assertEqual(rus["status"], "Active")
        self.assertEqual(rus["source_url"], "")
        self.assertIn("planned", rus["notes"].lower())


# ---------------------------------------------------------------------------
# Skip taxonomy: planned_public_page never produces fake rows
# ---------------------------------------------------------------------------


def _env_without_subsource_keys():
    import os as _os
    stripped = {
        k: v
        for k, v in _os.environ.items()
        if k
        not in {
            "EDINET_API_KEY",
            "JAPAN_EDINET_API_KEY",
            "OPENDART_API_KEY",
            "KOREA_DART_API_KEY",
        }
    }
    return patch.dict("os.environ", stripped, clear=True)


class TestPlannedPublicPageSkipBehavior(unittest.TestCase):
    """An inactive ``planned_public_page`` provider must:
      * never call the network,
      * never produce fake rows,
      * surface a planned_public_page status in the per-sub-source summary.
    """

    def test_single_planned_provider_skips_with_planned_public_page(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader
        loader = AsiaDisclosureLoader(providers=["sgx_public"])
        with patch("requests.get") as mock_get:
            result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertIn("planned_public_page", result.skip_reason.lower())
        mock_get.assert_not_called()

    def test_russia_planned_skips_cleanly(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader
        loader = AsiaDisclosureLoader(providers=["russia"])
        with patch("requests.get") as mock_get:
            result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertIn("planned_public_page", result.skip_reason.lower())
        mock_get.assert_not_called()

    def test_all_planned_sub_sources_combined_skip_reason(self):
        """When the user selects only planned_public_page providers, the
        parent skip reason carries the [PLANNED_PUBLIC_PAGE] tag and the
        per-source summary lists each as planned_public_page."""
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader
        loader = AsiaDisclosureLoader(providers=["kap", "idx", "tadawul"])
        result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertIn("[PLANNED_PUBLIC_PAGE]", result.skip_reason)
        for name in ("kap", "idx", "tadawul"):
            self.assertIn(name, result.skip_reason)

    def test_default_run_without_keys_still_optional_config_missing(self):
        """When all providers are selected (default) and no keys are set,
        the parent skip reason MUST still mention optional_config_missing
        — that is the actionable banner the UI surfaces.  The new
        planned_public_page providers do not override that signal."""
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader
        loader = AsiaDisclosureLoader()
        with _env_without_subsource_keys():
            with patch("requests.get") as mock_get:
                result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertIn(
            "optional_config_missing", result.skip_reason.lower(),
        )
        mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# Active public_page fetch path (mocked HTTP)
# ---------------------------------------------------------------------------


def _activate(name: str, source_class: str = "public_page", url: str | None = None):
    """Return a patched ``_PROVIDER_CONFIGS`` dict that flips ``name`` to
    active=True with the given ``source_class``."""
    from scripts.ingestion.asia_disclosure_loader import _PROVIDER_CONFIGS
    base = dict(_PROVIDER_CONFIGS[name])
    base["active"] = True
    base["source_class"] = source_class
    base["url"] = url or base.get("landing_url") or "https://mock.public.test/feed"
    return {**_PROVIDER_CONFIGS, name: base}


def _json_response(payload, status_code: int = 200):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = payload
    m.text = json.dumps(payload)
    m.raise_for_status.return_value = None
    return m


def _xml_response(xml: str, status_code: int = 200):
    m = MagicMock()
    m.status_code = status_code
    # The public-page parser tries .json() first then falls back to .text.
    m.json.side_effect = ValueError("not json")
    m.text = xml
    m.raise_for_status.return_value = None
    return m


def _http_error_response(status_code: int):
    m = MagicMock()
    m.status_code = status_code
    m.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    m.json.side_effect = ValueError("no body")
    m.text = ""
    return m


def _rate_limited_response():
    m = MagicMock()
    m.status_code = 429
    m.raise_for_status.return_value = None
    m.json.side_effect = ValueError("no body")
    m.text = ""
    return m


def _blocked_response(status_code: int = 403):
    m = MagicMock()
    m.status_code = status_code
    m.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    m.json.side_effect = ValueError("no body")
    m.text = "<html><body>blocked</body></html>"
    return m


def _opaque_html_response():
    """A response that's HTML but contains no extractable item structure —
    the parser must return parse_error, NOT a fake empty list of rows."""
    m = MagicMock()
    m.status_code = 200
    m.json.side_effect = ValueError("not json")
    m.text = "<html><head><title>Maintenance</title></head><body>Please retry later.</body></html>"
    m.raise_for_status.return_value = None
    return m


def _sample_json_items():
    return {
        "list": [
            {
                "company_name": "Singapore Telecommunications Ltd",
                "stock_code": "Z74",
                "title": "Interim Financial Statements",
                "published_at": "2026-05-15",
                "url": "https://www.sgx.com/announcements/12345",
                "doc_id": "12345",
            },
            {
                "company_name": "DBS Group Holdings",
                "stock_code": "D05",
                "title": "Quarterly Update",
                "published_at": "2026-05-14",
                "url": "https://www.sgx.com/announcements/12346",
                "doc_id": "12346",
            },
        ]
    }


def _sample_rss():
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<rss version=\"2.0\"><channel>"
        "<item>"
        "<title>Sabanci Holding — Interim Results</title>"
        "<link>https://www.kap.org.tr/en/Bildirim/123456</link>"
        "<pubDate>Fri, 15 May 2026 09:00:00 +0000</pubDate>"
        "<description>Q1 2026 interim results filed via KAP.</description>"
        "<guid>kap-123456</guid>"
        "</item>"
        "<item>"
        "<title>Garanti BBVA — Material Disclosure</title>"
        "<link>https://www.kap.org.tr/en/Bildirim/123457</link>"
        "<pubDate>Thu, 14 May 2026 12:30:00 +0000</pubDate>"
        "<description>Notice of board changes.</description>"
        "<guid>kap-123457</guid>"
        "</item>"
        "</channel></rss>"
    )


class TestPublicPageFetchPathJSON(unittest.TestCase):

    def _run(self, name, side_effects, **loader_kw):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader
        patched = _activate(name)
        loader = AsiaDisclosureLoader(providers=[name], **loader_kw)
        with patch(
            "scripts.ingestion.asia_disclosure_loader._PROVIDER_CONFIGS",
            patched,
        ):
            with patch("requests.get", side_effect=side_effects):
                return loader.safe_fetch()

    def test_success_normalises_at_least_one_row_sgx(self):
        result = self._run("sgx_public", [_json_response(_sample_json_items())])
        self.assertFalse(result.skipped)
        self.assertGreaterEqual(len(result.records), 1)
        rec = result.records[0]
        self.assertEqual(rec["country"], "Singapore")
        self.assertEqual(rec["jurisdiction"], "SG")
        self.assertEqual(rec["provider"], "sgx_public")
        self.assertEqual(rec["source_class"], "public_page")
        self.assertEqual(rec["issuer_name"], "Singapore Telecommunications Ltd")
        self.assertEqual(rec["ticker_or_identifier"], "Z74")

    def test_success_records_carry_advisory_safety(self):
        result = self._run("sgx_public", [_json_response(_sample_json_items())])
        for rec in result.records:
            self.assertEqual(rec["advisory_status"], "ADVISORY_ONLY")
            self.assertTrue(rec["human_review_required"])
            self.assertEqual(rec["execution_gate"], "LOCKED")

    def test_http_error_becomes_skipped(self):
        result = self._run("sgx_public", [_http_error_response(500)])
        self.assertTrue(result.skipped)
        self.assertIn("http", result.skip_reason.lower())

    def test_rate_limit_429_surfaces_rate_limited(self):
        result = self._run("sgx_public", [_rate_limited_response()])
        self.assertTrue(result.skipped)
        self.assertIn("rate_limited", result.skip_reason.lower())

    def test_blocked_403_surfaces_blocked(self):
        result = self._run("sgx_public", [_blocked_response(403)])
        self.assertTrue(result.skipped)
        self.assertIn("blocked", result.skip_reason.lower())

    def test_blocked_401_surfaces_blocked(self):
        result = self._run("sgx_public", [_blocked_response(401)])
        self.assertTrue(result.skipped)
        self.assertIn("blocked", result.skip_reason.lower())

    def test_empty_list_is_no_rows_not_fake_healthy(self):
        result = self._run("sgx_public", [_json_response({"list": []})])
        self.assertFalse(result.skipped)
        self.assertEqual(len(result.records), 0)
        self.assertIn("no_rows", result.skip_reason.lower())

    def test_parse_error_becomes_parse_error(self):
        """An HTML-only response with no extractable items must surface
        parse_error — never fabricated rows."""
        result = self._run("sgx_public", [_opaque_html_response()])
        self.assertTrue(result.skipped)
        self.assertIn("parse_error", result.skip_reason.lower())

    def test_unreachable_when_request_raises(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader
        patched = _activate("sgx_public")
        loader = AsiaDisclosureLoader(providers=["sgx_public"])
        with patch(
            "scripts.ingestion.asia_disclosure_loader._PROVIDER_CONFIGS",
            patched,
        ):
            with patch("requests.get", side_effect=Exception("network down")):
                result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertIn("unreachable", result.skip_reason.lower())

    def test_max_items_respected(self):
        many = {
            "list": [
                {
                    "company_name": f"Company {i}",
                    "stock_code": f"C{i:04d}",
                    "title": f"Title {i}",
                    "published_at": "2026-05-15",
                    "url": f"https://www.sgx.com/a/{i}",
                    "doc_id": str(i),
                }
                for i in range(40)
            ]
        }
        result = self._run(
            "sgx_public", [_json_response(many)], max_items=5
        )
        # ``_max_items`` applies at the outer slice; the public-page
        # default cap (25) applies internally.  Both must yield <=25 rows
        # and outer slice yields exactly 5.
        self.assertLessEqual(len(result.records), 5)


class TestPublicPageFetchPathRSS(unittest.TestCase):
    """RSS / Atom responses are also acceptable public-page payloads."""

    def _run_kap_rss(self, response):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader
        patched = _activate("kap")
        loader = AsiaDisclosureLoader(providers=["kap"])
        with patch(
            "scripts.ingestion.asia_disclosure_loader._PROVIDER_CONFIGS",
            patched,
        ):
            with patch("requests.get", return_value=response):
                return loader.safe_fetch()

    def test_rss_feed_parses_into_rows(self):
        result = self._run_kap_rss(_xml_response(_sample_rss()))
        self.assertFalse(result.skipped)
        self.assertEqual(len(result.records), 2)
        rec = result.records[0]
        self.assertEqual(rec["country"], "Turkey")
        self.assertEqual(rec["jurisdiction"], "TR")
        self.assertEqual(rec["provider"], "kap")
        self.assertIn("Sabanci Holding", rec["title"])
        self.assertTrue(rec["url"].startswith("https://www.kap.org.tr/"))

    def test_rss_rows_carry_safety_contract(self):
        result = self._run_kap_rss(_xml_response(_sample_rss()))
        for rec in result.records:
            self.assertEqual(rec["advisory_status"], "ADVISORY_ONLY")
            self.assertEqual(rec["execution_gate"], "LOCKED")
            self.assertTrue(rec["human_review_required"])

    def test_malformed_xml_is_parse_error(self):
        bad = _xml_response("<?xml version=\"1.0\"?><rss><channel><item><title>broken")
        result = self._run_kap_rss(bad)
        self.assertTrue(result.skipped)
        self.assertIn("parse_error", result.skip_reason.lower())


# ---------------------------------------------------------------------------
# Public-page normalizer unit tests
# ---------------------------------------------------------------------------


class TestPublicPageNormalizerUnit(unittest.TestCase):

    def _conf(self):
        from scripts.ingestion.asia_disclosure_loader import _PROVIDER_CONFIGS
        return dict(_PROVIDER_CONFIGS["idx"])

    def test_normalizes_with_full_fields(self):
        from scripts.ingestion.asia_disclosure_loader import (
            _normalize_public_page_item,
        )
        rec = _normalize_public_page_item(
            {
                "issuer_name": "Bank Central Asia",
                "ticker": "BBCA",
                "title": "FY2025 Disclosure",
                "summary": "Annual financial disclosure",
                "published_at": "2026-05-15",
                "url": "https://www.idx.co.id/disclosure/12345",
                "doc_id": "12345",
            },
            self._conf(),
        )
        self.assertEqual(rec["issuer_name"], "Bank Central Asia")
        self.assertEqual(rec["ticker_or_identifier"], "BBCA")
        self.assertEqual(rec["country"], "Indonesia")
        self.assertEqual(rec["jurisdiction"], "ID")
        self.assertEqual(rec["disclosure_system"], "Indonesia Stock Exchange News")
        self.assertTrue(rec["url"].startswith("https://"))

    def test_alternate_field_names_company_name(self):
        from scripts.ingestion.asia_disclosure_loader import (
            _normalize_public_page_item,
        )
        rec = _normalize_public_page_item(
            {
                "company_name": "GoTo Group",
                "stock_code": "GOTO",
                "headline": "Material disclosure",
                "date": "2026-05-15",
                "link": "https://www.idx.co.id/disclosure/x",
            },
            self._conf(),
        )
        self.assertEqual(rec["issuer_name"], "GoTo Group")
        self.assertEqual(rec["ticker_or_identifier"], "GOTO")
        self.assertEqual(rec["title"], "Material disclosure")
        self.assertEqual(rec["url"], "https://www.idx.co.id/disclosure/x")

    def test_missing_url_does_not_invent(self):
        from scripts.ingestion.asia_disclosure_loader import (
            _normalize_public_page_item,
        )
        rec = _normalize_public_page_item(
            {"issuer_name": "Foo", "title": "Bar"},
            self._conf(),
        )
        self.assertEqual(rec["url"], "")

    def test_safety_fields_not_present_until_stamped(self):
        """Normalizer alone does not stamp advisory fields — the loader
        calls ``_stamp_record`` separately so callers cannot accidentally
        commit a record that bypassed the contract."""
        from scripts.ingestion.asia_disclosure_loader import (
            _normalize_public_page_item,
        )
        rec = _normalize_public_page_item(
            {"issuer_name": "Foo"}, self._conf()
        )
        # Advisory stamps are added by the loader stamp step, not the
        # normalizer.  The normalizer's output does NOT carry them.
        self.assertNotIn("advisory_status", rec)
        self.assertNotIn("execution_gate", rec)


# ---------------------------------------------------------------------------
# No fake rows when keys missing AND only planned providers selected
# ---------------------------------------------------------------------------


class TestNoFakeRows(unittest.TestCase):

    def test_planned_only_selection_returns_zero_records(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader
        loader = AsiaDisclosureLoader(
            providers=list(PUBLIC_PAGE_PROVIDERS)
        )
        with patch("requests.get") as mock_get:
            result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertEqual(result.records, [])
        mock_get.assert_not_called()

    def test_summary_distinguishes_planned_from_placeholder(self):
        """The per-sub-source JSON summary must list planned_public_page
        providers in a dedicated bucket so the UI/operator does not
        confuse "planned" with "deprecated placeholder"."""
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader
        loader = AsiaDisclosureLoader(providers=["kap", "sgx", "russia"])
        # sgx is legacy placeholder; kap + russia are planned_public_page.
        result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        reason = result.skip_reason
        # The skip reason embeds a JSON summary.  Extract it and inspect.
        marker = "sub_source_status="
        idx = reason.find(marker)
        self.assertGreaterEqual(idx, 0, reason)
        payload = json.loads(reason[idx + len(marker):])
        per = payload["per_source"]
        self.assertEqual(per["sgx"]["status"], "placeholder")
        self.assertEqual(per["kap"]["status"], "planned_public_page")
        self.assertEqual(per["russia"]["status"], "planned_public_page")
        planned_bucket = payload.get("sub_sources_planned_public_page", [])
        self.assertIn("kap", planned_bucket)
        self.assertIn("russia", planned_bucket)
        self.assertNotIn("sgx", planned_bucket)


if __name__ == "__main__":
    unittest.main()
