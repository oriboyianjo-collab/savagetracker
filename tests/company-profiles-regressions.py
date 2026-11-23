#!/usr/bin/env python3
"""Offline tests for company-profile extraction and inventory. No network, no secrets."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from io import BytesIO

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "scripts" / "company-profiles"
FIXT = ROOT / "tests" / "fixtures" / "company-profiles"
sys.path.insert(0, str(HERE))

from extract import EXTRACTOR_VERSION, extract_profile_text, has_dropped_periods, html_to_text, item_body, is_boilerplate_text  # noqa: E402
from inventory import collect, infer_form, is_annual, is_current, latest_annual  # noqa: E402
from sec_http import HardStop, SecClient, TransientDefer  # noqa: E402


class ExtractTests(unittest.TestCase):
    def test_aapl_item1_opening(self):
        raw = (FIXT / "aapl-item1-snippet.html").read_text(encoding="utf-8")
        out = extract_profile_text(raw, "10-K")
        self.assertTrue(out["short_en"], out)
        self.assertIn("designs, manufactures and markets", out["short_en"])
        self.assertIn("smartphones", out["short_en"])
        # Extractive: keep the filing's wording, not a rewrite.
        self.assertTrue(out["short_en"].startswith("The Company") or "The Company designs" in out["short_en"])
        self.assertGreaterEqual(len(out["full_en"]), len(out["short_en"]))
        self.assertNotIn("Risk Factors", out["short_en"])
        # short stays a few lines, not the whole Item 1
        self.assertLess(len(out["short_en"]), 700)

    def test_skips_toc_and_hidden_ixbrl(self):
        raw = (FIXT / "aapl-10k-toc-and-item1.html").read_text(encoding="utf-8")
        out = extract_profile_text(raw, "10-K")
        self.assertIn("designs, manufactures and markets", out["short_en"])
        self.assertTrue(out["short_en"].startswith("The Company") or "The Company designs" in out["short_en"])
        self.assertNotIn("hidden copy should not be used", out["short_en"])
        self.assertNotIn("Risk Factors", out["short_en"])
        self.assertGreater(len(out["item_text"]), 300)
        # The body is the real Item 1, not the one-line TOC stub.
        self.assertIn("Company Background", out["item_text"])
        self.assertNotEqual(out["item_text"].strip().splitlines()[0].strip(), "Item 1.")

    def test_skips_toc_and_officer_headings(self):
        text = (
            "Item 1. Business\n\n"
            "• How We Generate Revenues and Profitability 4\n\n"
            "Information about our Executive Officers 19\n\n"
            "The Company designs, manufactures and markets smartphones and related services.\n\n"
            "Item 1A. Risk Factors\n\nMany risks.\n"
        )
        out = extract_profile_text(text, "10-K")
        self.assertIn("designs, manufactures and markets", out["short_en"])
        self.assertNotIn("Executive Officers", out["short_en"])
        self.assertNotIn("How We Generate", out["short_en"])

    def test_skips_forward_looking_preamble(self):
        raw = (FIXT / "amzn-item1-preamble.html").read_text(encoding="utf-8")
        out = extract_profile_text(raw, "10-K")
        self.assertIn("e-commerce and cloud computing", out["short_en"])
        self.assertTrue(out["short_en"].startswith("Amazon") or "Amazon is a leading" in out["short_en"])
        self.assertNotIn("forward-looking", out["short_en"].lower())
        self.assertNotIn("This Annual Report", out["short_en"])
        self.assertFalse(is_boilerplate_text(out["short_en"]))
        self.assertTrue(is_boilerplate_text(
            "This Annual Report on Form 10-K contains forward-looking statements based on expectations."
        ))

    def test_strips_inc_abbreviation_and_keeps_business(self):
        raw = """
        <html><body>
        <h1>Item 1. Business</h1>
        <p>As used herein, “Amazon.com,” “we,” “our,” and similar terms include Amazon.com, Inc. and its subsidiaries, unless the context indicates otherwise. We seek to be Earth’s most customer-centric company. We are guided by four principles: customer obsession rather than competitor focus.</p>
        <h1>Item 1A. Risk Factors</h1>
        <p>Should not be included.</p>
        </body></html>
        """
        out = extract_profile_text(raw, "10-K")
        self.assertIn("Earth’s most customer-centric company", out["short_en"])
        self.assertTrue(out["short_en"].startswith("We seek") or "We seek to be" in out["short_en"])
        self.assertRegex(out["short_en"], r"company\. We are guided")
        self.assertNotIn("company We are", out["short_en"])
        self.assertNotIn("subsidiaries", out["short_en"])
        self.assertFalse(is_boilerplate_text(out["short_en"]))
        self.assertTrue(is_boilerplate_text("and its subsidiaries, unless the context indicates otherwise. We seek to be Earth’s most customer-centric company."))

    def test_business_overview_of_the_company(self):
        text = (
            "Item 4. Information on the Company\n\n"
            "Our History and Structure Our legal and commercial name is Example Foundry Inc.\n\n"
            "Business Overview of the Company As a foundry, we manufacture semiconductors using our manufacturing processes for our customers.\n\n"
            "Item 5. Operating and Financial Review\n\nShould not be included.\n"
        )
        out = extract_profile_text(text, "20-F")
        self.assertIn("manufacture semiconductors", out["short_en"])
        self.assertNotIn("legal and commercial name", out["short_en"])

    def test_20f_business_overview_not_toc(self):
        raw = (FIXT / "sample-20f-item4-overview.html").read_text(encoding="utf-8")
        out = extract_profile_text(raw, "20-F")
        self.assertIn("semiconductor foundry", out["short_en"])
        self.assertNotIn("Should not be included", out["short_en"])
        self.assertNotIn("Risk Factors", out["short_en"])
        # History subsection is skipped in favor of Business Overview.
        self.assertNotIn("was incorporated in 1987", out["short_en"])

    def test_item4_fallback_when_form_looks_like_10k(self):
        raw = (FIXT / "sample-20f-item4-overview.html").read_text(encoding="utf-8")
        out = extract_profile_text(raw, "10-K")
        self.assertIn("semiconductor foundry", out["short_en"])

    def test_item1_loose_heading(self):
        text = (
            "PART I\n\nItem 1.\n\n   \nBUSINESS\n\n"
            "The Company develops and licenses software platforms for enterprises worldwide.\n\n"
            "Item 1A. Risk Factors\n\nMany risks.\n"
        )
        out = extract_profile_text(text, "10-K")
        self.assertIn("develops and licenses software", out["short_en"])
        self.assertNotIn("Many risks", out["short_en"])

    def test_20f_item4(self):
        raw = (FIXT / "sample-20f-item4.html").read_text(encoding="utf-8")
        out = extract_profile_text(raw, "20-F")
        self.assertIn("designs, manufactures and sells industrial machinery", out["short_en"])
        self.assertIn("designs, manufactures and sells industrial machinery", out["full_en"])
        self.assertNotIn("Business Overview", out["short_en"])  # headings are skipped
        self.assertNotIn("Should not be included", out["short_en"])
        self.assertNotIn("Should not be included", out["full_en"])

    def test_item_body_stops_at_1a(self):
        text = "Intro\n\nItem 1. Business\n\nThe Company makes widgets.\n\nItem 1A. Risk Factors\n\nMany risks.\n"
        body = item_body(text, "10-K")
        self.assertIn("makes widgets", body)
        self.assertNotIn("Many risks", body)


    def test_skips_amd_style_disclosure(self):
        raw = (FIXT / "amd-item1-disclosure.html").read_text(encoding="utf-8")
        out = extract_profile_text(raw, "10-K")
        self.assertIn("global semiconductor company", out["short_en"])
        self.assertTrue(
            out["short_en"].startswith("Advanced Micro Devices")
            or "Advanced Micro Devices, Inc. is a global" in out["short_en"]
        )
        self.assertNotIn("methodological", out["short_en"].lower())
        self.assertNotIn("independently verify", out["short_en"].lower())
        self.assertNotIn("methodological", out["full_en"].lower())
        self.assertFalse(is_boilerplate_text(out["short_en"]))
        self.assertTrue(is_boilerplate_text(
            "Furthermore, much of this information is subject to methodological considerations or information, including from third-parties, that is still evolving."
        ))

    def test_20f_item4b_skips_regulation(self):
        raw = (FIXT / "baba-20f-item4b.html").read_text(encoding="utf-8")
        out = extract_profile_text(raw, "20-F")
        self.assertIn("e-commerce and cloud computing platform", out["short_en"])
        self.assertIn("merchants", out["short_en"])
        self.assertNotIn("regulatory inquiries", out["short_en"].lower())
        self.assertNotIn("rectification", out["short_en"].lower())
        self.assertNotIn("regulatory inquiries", out["full_en"].lower())
        self.assertNotIn("Organizational Structure", out["short_en"])
        self.assertNotIn("was founded in 1999", out["short_en"])
        self.assertFalse(is_boilerplate_text(out["short_en"]))

    def test_20f_information_on_named_company(self):
        raw = (FIXT / "asml-20f-item4.html").read_text(encoding="utf-8")
        out = extract_profile_text(raw, "20-F")
        self.assertIn("lithography systems", out["short_en"])
        self.assertIn("semiconductor industry", out["short_en"])
        self.assertNotIn("incorporated in the Netherlands", out["short_en"])
        self.assertNotIn("Should not be included", out["short_en"])
        self.assertFalse(is_boilerplate_text(out["short_en"]))

    def test_skips_item10_and_lowercase_fragments(self):
        text = (
            "Item 1. Business\n\n"
            "Any information required by this Item 10 regarding compliance with Section 16(a) of the Exchange Act of 1934 included under the caption “Delinquent Section 16(a) Reports” in our Proxy Statement is incorporated herein by reference.\n\n"
            "on Private Education—Regulations on After-school Tutoring Institutions and Online Education” for more details. The Alleviating Burden Opinion Regarding Compulsory Education also provides that administration over academic tutoring services shall be implemented by local authorities.\n\n"
            "The Company operates a nationwide tutoring and learning-services platform for students and families.\n\n"
            "Item 1A. Risk Factors\n\nMany risks.\n"
        )
        out = extract_profile_text(text, "10-K")
        self.assertIn("tutoring and learning-services platform", out["short_en"])
        self.assertNotIn("Item 10", out["short_en"])
        self.assertNotIn("for more details", out["short_en"])
        self.assertFalse(out["short_en"][0].islower())

    def test_dropped_periods_are_detected_and_repaired(self):
        broken = (
            "We seek to be Earth’s most customer-centric company We are guided by four principles: "
            "customer obsession rather than competitor focus."
        )
        self.assertTrue(has_dropped_periods(broken))
        self.assertTrue(is_boilerplate_text(broken))
        raw = """
        <html><body>
        <h1>Item 1. Business</h1>
        <p>As used herein, “Amazon.com,” “we,” “our,” and similar terms include Amazon.com, Inc. and its subsidiaries, unless the context indicates otherwise. We seek to be Earth’s most customer-centric company. We are guided by four principles: customer obsession rather than competitor focus, passion for invention, commitment to operational excellence, and long-term thinking.</p>
        <h1>Item 1A. Risk Factors</h1>
        <p>Should not be included.</p>
        </body></html>
        """
        out = extract_profile_text(raw, "10-K")
        self.assertIn("company. We are guided", out["short_en"])
        self.assertIn("thinking.", out["full_en"])
        self.assertFalse(has_dropped_periods(out["short_en"]))
        self.assertFalse(is_boilerplate_text(out["short_en"]))


class InventoryTests(unittest.TestCase):
    def test_latest_annual_and_form(self):
        ledger = [
            {"slot": "2025-Q3", "form": "10-Q", "filing_date": "2025-08-01", "url": "https://www.sec.gov/q.htm"},
            {"slot": "2025-FY", "filing_date": "2025-10-31", "period_end": "2025-09-27",
             "url": "https://www.sec.gov/Archives/edgar/data/1/a.htm", "body_sha256": "aaa"},
            {"slot": "2026-FY", "filing_date": "2026-11-03", "period_end": "2026-09-26",
             "url": "https://www.sec.gov/Archives/edgar/data/1/b.htm", "body_sha256": "bbb"},
        ]
        latest = latest_annual(ledger)
        self.assertEqual(latest["filing_date"], "2026-11-03")
        self.assertEqual(infer_form(latest), "10-K")
        self.assertTrue(is_annual(latest))
        self.assertFalse(is_annual(ledger[0]))

    def test_20f_from_url(self):
        e = {"slot": "2024-FY", "filing_date": "2025-03-31",
             "url": "https://www.sec.gov/Archives/edgar/data/1/0001/form20-f.htm"}
        self.assertEqual(infer_form(e), "20-F")
        self.assertEqual(infer_form({"url": "https://www.sec.gov/x/d38065d20f.htm"}), "20-F")
        self.assertEqual(infer_form({"url": "https://www.sec.gov/x/beke-20251231x20f.htm"}), "20-F")
        self.assertEqual(infer_form({"url": "https://www.sec.gov/x/valeform20f_2025.htm"}), "20-F")
        self.assertEqual(infer_form({"url": "https://www.sec.gov/x/qh-20241231x20fa.htm"}), "20-F/A")
        self.assertEqual(infer_form({"url": "https://www.sec.gov/x/tsm-20251231.htm"}), "10-K")

    def test_form_from_pass_state_when_url_is_plain(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            links = d / "links"
            pas = d / "pass"
            links.mkdir(); pas.mkdir()
            annual = {"slot": "2025-FY", "filing_date": "2026-04-16",
                      "url": "https://www.sec.gov/Archives/edgar/data/1/tsm-20251231.htm",
                      "body_sha256": "x"}
            (links / "TSM.a.json").write_text(json.dumps({"symbols": {"TSM": {"cik": "1", "ledger": [annual]}}}))
            (pas / "TSM.b.json").write_text(json.dumps({
                "row": {"cik": "1", "ledger": [{**annual, "form": "20-F"}]}
            }))
            items = collect(links, pass_dir=pas)
            self.assertEqual(items[0]["form"], "20-F")

    def test_is_current_matches_hash_and_skips_empty_stub(self):
        rec = {"url": "https://www.sec.gov/a.htm", "filing_date": "2026-11-03", "form": "10-K", "doc_sha256": "abc"}
        self.assertFalse(is_current(None, rec))
        # A real description stays current even without a version stamp.
        self.assertTrue(is_current({"short_en": "The Company designs widgets for industry use worldwide.", "doc_sha256": "abc"}, rec))
        self.assertTrue(is_current({"short_en": "The Company designs widgets for industry use worldwide.", "doc_sha256": "abc", "extractor": EXTRACTOR_VERSION}, rec))
        # Preamble-only fills and empty stubs from an older extractor are retried.
        self.assertFalse(is_current({"short_en": "This Annual Report on Form 10-K contains forward-looking statements.", "doc_sha256": "abc", "extractor": 2}, rec))
        self.assertFalse(is_current({"short_en": "We seek to be Earth’s most customer-centric company We are guided by four principles.", "doc_sha256": "abc", "extractor": 4}, rec))
        self.assertFalse(is_current({"short_en": "Furthermore, much of this information is subject to methodological considerations or information, including from third-parties.", "doc_sha256": "abc", "extractor": 4}, rec))
        self.assertFalse(is_current({"short_en": "Certain of our platform businesses face regulatory inquiries and investigations on involutionary competition, including pricing practices.", "doc_sha256": "abc", "extractor": 4}, rec))
        self.assertFalse(is_current({"short_en": "on Private Education—Regulations on After-school Tutoring for more details.", "doc_sha256": "abc", "extractor": 4}, rec))
        self.assertFalse(is_current({"empty": True, "short_en": "", "doc_sha256": "abc"}, rec))
        self.assertFalse(is_current({"short_en": "Hello", "doc_sha256": "zzz", "url": "x", "filing_date": "x", "form": "10-K", "extractor": EXTRACTOR_VERSION}, rec))
        self.assertTrue(is_current({"empty": True, "short_en": "", "doc_sha256": "abc", "extractor": EXTRACTOR_VERSION}, rec))

    def test_collect_from_shards(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            shard = {
                "symbols": {
                    "ZZZ": {"cik": "1", "ledger": [
                        {"slot": "2026-FY", "filing_date": "2026-01-01",
                         "url": "https://www.sec.gov/Archives/edgar/data/1/z.htm", "body_sha256": "z"}
                    ]},
                    "AAA": {"cik": "2", "ledger": [
                        {"slot": "2026-FY", "filing_date": "2026-02-01",
                         "url": "https://www.sec.gov/Archives/edgar/data/2/a.htm", "body_sha256": "a"}
                    ]},
                }
            }
            (d / "AAA.x.json").write_text(json.dumps(shard))
            rank = d / "rank.json"
            rank.write_text(json.dumps({"ranked": [["AAA", 1, "A"], ["ZZZ", 2, "Z"]]}))
            items = collect(d, rank)
            self.assertEqual([x["symbol"] for x in items], ["AAA", "ZZZ"])
            self.assertEqual(items[0]["form"], "10-K")


class FakeResp:
    def __init__(self, status, body=b"ok"):
        self.status = status
        self._body = body
    def read(self):
        return self._body
    def getcode(self):
        return self.status
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


class FakeOpener:
    def __init__(self, handler):
        self.handler = handler
    def open(self, req, timeout=45):
        return self.handler(req)


class HttpTests(unittest.TestCase):
    def test_refuses_non_sec_host(self):
        c = SecClient(min_interval=0)
        with self.assertRaises(ValueError):
            c.get("https://example.com/10k.htm")

    def test_403_is_hard_stop(self):
        def handler(req):
            raise HTTPError(req.full_url, 403, "Forbidden", hdrs=None, fp=BytesIO(b"no"))
        c = SecClient(min_interval=0, opener=FakeOpener(handler))
        with self.assertRaises(HardStop) as e:
            c.get("https://www.sec.gov/x.htm")
        self.assertEqual(e.exception.status, 403)

    def test_429_is_hard_stop(self):
        def handler(req):
            raise HTTPError(req.full_url, 429, "Too Many", hdrs=None, fp=BytesIO(b"no"))
        c = SecClient(min_interval=0, opener=FakeOpener(handler))
        with self.assertRaises(HardStop):
            c.get("https://data.sec.gov/x.htm")

    def test_503_is_transient(self):
        def handler(req):
            raise HTTPError(req.full_url, 503, "Unavailable", hdrs=None, fp=BytesIO(b"no"))
        c = SecClient(min_interval=0, opener=FakeOpener(handler))
        with self.assertRaises(TransientDefer) as e:
            c.get("https://www.sec.gov/x.htm")
        self.assertEqual(e.exception.status, 503)

    def test_200_ok(self):
        def handler(req):
            self.assertEqual(req.get_header("User-agent") or req.get_header("User-Agent"), "SavageTracker Savtra12@gmail.com")
            return FakeResp(200, b"<html>ok</html>")
        c = SecClient(min_interval=0, opener=FakeOpener(handler))
        self.assertEqual(c.get("https://www.sec.gov/x.htm"), b"<html>ok</html>")


if __name__ == "__main__":
    r = unittest.main(verbosity=2, exit=False)
    sys.exit(0 if r.result.wasSuccessful() else 1)
