"""Failure classification: status propagation, bounded retry, verification flag."""

from pathlib import Path
import unittest
from unittest import mock

import yaml

from _webclip.article import _extractor_failure
from _webclip.core import ClipError
from _webclip.markdown import render_note
from _webclip import sites as sites_module

SUCCESS = {
    "ok": True,
    "title": "An Article",
    "author": "Ada",
    "published": "2026-07-23",
    "description": "A useful page",
    "site": "Example",
    "canonicalUrl": "https://example.com/article",
    "url": "https://example.com/article",
    "keywords": ["security", "clipping"],
    "markdown": "# An Article\r\n\r\nBody\r\n",
    "wordCount": 3,
    "method": "readability",
}


def payload(**overrides):
    data = dict(SUCCESS)
    data.update(overrides)
    return data


def frontmatter(note: str) -> dict:
    block, _ = note[4:].split("\n---\n", 1)
    return yaml.safe_load(block)


class StatusMessageTests(unittest.TestCase):
    def test_401_points_at_credentials(self):
        error = _extractor_failure({"ok": False, "code": "HTTP_STATUS", "status": 401})
        self.assertEqual(error.status, 401)
        self.assertIn("credentials", str(error))
        self.assertIn("will not help", str(error))

    def test_403_behind_cloudflare_without_cf_mitigated_stays_generic(self):
        error = _extractor_failure(
            {"ok": False, "code": "HTTP_STATUS", "status": 403, "server": "cloudflare"}
        )
        self.assertIn("usually a bot wall", str(error))
        self.assertIn("a retry rarely helps", str(error))

    def test_403_with_cf_mitigated_header_is_a_bot_wall(self):
        error = _extractor_failure(
            {"ok": False, "code": "HTTP_STATUS", "status": 403, "cfMitigated": "challenge"}
        )
        self.assertIn("bot wall", str(error))

    def test_plain_403_is_not_reported_as_an_auth_failure(self):
        error = _extractor_failure({"ok": False, "code": "HTTP_STATUS", "status": 403})
        self.assertIn("403", str(error))
        self.assertNotIn("credentials", str(error))

    def test_429_keeps_retry_after_and_is_retryable(self):
        error = _extractor_failure(
            {"ok": False, "code": "HTTP_STATUS", "status": 429, "retryAfter": "3"}
        )
        self.assertEqual(error.status, 429)
        self.assertEqual(error.retry_after, "3")
        self.assertIn("rate limiting", str(error))

    def test_5xx_and_unexpected_statuses_state_the_number(self):
        self.assertIn("server error (HTTP 503)", str(
            _extractor_failure({"ok": False, "code": "HTTP_STATUS", "status": 503})
        ))
        self.assertIn("HTTP 418", str(
            _extractor_failure({"ok": False, "code": "HTTP_STATUS", "status": 418})
        ))

    def test_missing_status_falls_back_to_the_code_message(self):
        error = _extractor_failure({"ok": False, "code": "HTTP_STATUS"})
        self.assertIn("HTTP_STATUS", str(error))
        self.assertIsNone(error.status)

    def test_challenge_and_fake_success_carry_a_verdict(self):
        challenge = _extractor_failure({"ok": False, "code": "CHALLENGE_PAGE"})
        self.assertIn("browser challenge", str(challenge))
        fake = _extractor_failure({"ok": False, "code": "FAKE_SUCCESS"})
        self.assertIn("Nothing was saved", str(fake))

    def test_unknown_and_unsafe_codes_stay_generic(self):
        self.assertIn("Web extraction failed.", str(_extractor_failure({"code": "../../etc"})))
        self.assertIn("QUALITY_GATE", str(_extractor_failure({"code": "QUALITY_GATE"})))


class ChallengeMarkerTests(unittest.TestCase):
    def test_the_marker_is_named_in_the_message(self):
        error = _extractor_failure(
            {"ok": False, "code": "CHALLENGE_PAGE", "marker": "verify you are human"}
        )
        self.assertIn('Marker: "verify you are human"', str(error))

    def test_a_chinese_marker_is_named_too(self):
        error = _extractor_failure(
            {"ok": False, "code": "CHALLENGE_PAGE", "marker": "\u8bf7\u5b8c\u6210\u5b89\u5168\u9a8c\u8bc1"}
        )
        self.assertIn("Marker: \"\u8bf7\u5b8c\u6210\u5b89\u5168\u9a8c\u8bc1\"", str(error))

    def test_an_unsafe_marker_is_dropped(self):
        # A quote or a newline would break the sentence the user reads.
        for marker in ['a"b', "line\nbreak", "x" * 61]:
            error = _extractor_failure(
                {"ok": False, "code": "CHALLENGE_PAGE", "marker": marker}
            )
            self.assertNotIn("Marker:", str(error))

    def test_a_marker_on_another_code_is_ignored(self):
        error = _extractor_failure(
            {"ok": False, "code": "FAKE_SUCCESS", "marker": "verify you are human"}
        )
        self.assertNotIn("Marker:", str(error))


class RetryTests(unittest.TestCase):
    url = "https://example.com/article"

    def test_rate_limit_is_retried_once_after_the_hinted_delay(self):
        calls = []

        def fake(plugin_root, url, no_browser=False):
            calls.append(url)
            if len(calls) == 1:
                raise ClipError("rate limited", status=429, retry_after="3")
            return {"ok": True}

        with mock.patch.object(sites_module, "run_extractor", fake), mock.patch.object(
            sites_module.time, "sleep"
        ) as sleep:
            result = sites_module.run_extractor_with_fallback(Path("/tmp"), self.url)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(calls), 2)
        sleep.assert_called_once_with(3.0)

    def test_retry_after_zero_still_waits_a_second(self):
        def fake(plugin_root, url, no_browser=False):
            raise ClipError("rate limited", status=429, retry_after="0")

        with mock.patch.object(sites_module, "run_extractor", fake), mock.patch.object(
            sites_module.time, "sleep"
        ) as sleep:
            with self.assertRaises(ClipError):
                sites_module.run_extractor_with_fallback(Path("/tmp"), self.url)

        sleep.assert_called_once_with(1.0)

    def test_non_ascii_digits_fall_back_to_the_default_delay(self):
        # "²".isdigit() is true but float("²") raises, which would escape the
        # retry entirely; the header must be matched as ASCII digits.
        error = ClipError("rate limited", status=429, retry_after="\u00b2")
        self.assertEqual(sites_module._retry_delay(error), sites_module.DEFAULT_RETRY_SLEEP_S)

    def test_non_ascii_retry_after_still_retries_once(self):
        calls = []

        def fake(plugin_root, url, no_browser=False):
            calls.append(url)
            if len(calls) == 1:
                raise ClipError("rate limited", status=429, retry_after="\u00b2")
            return {"ok": True}

        with mock.patch.object(sites_module, "run_extractor", fake), mock.patch.object(
            sites_module.time, "sleep"
        ) as sleep:
            result = sites_module.run_extractor_with_fallback(Path("/tmp"), self.url)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(calls), 2)
        sleep.assert_called_once_with(sites_module.DEFAULT_RETRY_SLEEP_S)

    def test_retry_delay_is_capped(self):
        def fake(plugin_root, url, no_browser=False):
            raise ClipError("rate limited", status=429, retry_after="999")

        with mock.patch.object(sites_module, "run_extractor", fake), mock.patch.object(
            sites_module.time, "sleep"
        ) as sleep:
            with self.assertRaises(ClipError):
                sites_module.run_extractor_with_fallback(Path("/tmp"), self.url)

        sleep.assert_called_once_with(sites_module.MAX_RETRY_SLEEP_S)

    def test_bot_wall_is_never_retried(self):
        calls = []

        def fake(plugin_root, url, no_browser=False):
            calls.append(url)
            raise ClipError("bot wall", status=403)

        with mock.patch.object(sites_module, "run_extractor", fake), mock.patch.object(
            sites_module.time, "sleep"
        ) as sleep:
            with self.assertRaises(ClipError):
                sites_module.run_extractor_with_fallback(Path("/tmp"), self.url)

        self.assertEqual(len(calls), 1)
        sleep.assert_not_called()

    def test_second_failure_propagates_after_one_retry(self):
        calls = []

        def fake(plugin_root, url, no_browser=False):
            calls.append(url)
            raise ClipError("still failing", status=503)

        with mock.patch.object(sites_module, "run_extractor", fake), mock.patch.object(
            sites_module.time, "sleep"
        ):
            with self.assertRaises(ClipError):
                sites_module.run_extractor_with_fallback(Path("/tmp"), self.url)

        self.assertEqual(len(calls), 2)


class VerificationFrontmatterTests(unittest.TestCase):
    def test_weak_verification_is_recorded(self):
        parsed = frontmatter(render_note(payload(verification="weak"), created="2026-07-23T12:00:00+00:00"))
        self.assertEqual(parsed["extraction_verified"], "weak")
        self.assertEqual(parsed["extraction_method"], "readability")

    def test_strong_verification_adds_no_key(self):
        parsed = frontmatter(render_note(payload(verification="strong")))
        self.assertNotIn("extraction_verified", parsed)

    def test_missing_verification_adds_no_key(self):
        parsed = frontmatter(render_note(payload()))
        self.assertNotIn("extraction_verified", parsed)

    def test_unexpected_verification_value_is_dropped(self):
        parsed = frontmatter(render_note(payload(verification="bogus")))
        self.assertNotIn("extraction_verified", parsed)


class ExtractorBoundaryTests(unittest.TestCase):
    def test_status_survives_the_extractor_json_boundary(self):
        import json

        from _webclip import extract as extract_module
        from _webclip.article import _validate_success_payload
        from _webclip.proc import ProcessResult

        failed = ProcessResult(
            returncode=1,
            stdout=json.dumps(
                {"ok": False, "code": "HTTP_STATUS", "status": 429, "retryAfter": "7"}
            ).encode(),
            stderr=b"",
        )
        repo_root = Path(__file__).resolve().parents[1]
        with mock.patch.object(extract_module, "_run_bounded", return_value=failed):
            with self.assertRaises(ClipError) as caught:
                extract_module.run_extractor(repo_root, "https://example.com/article")

        self.assertEqual(caught.exception.status, 429)
        self.assertEqual(caught.exception.retry_after, "7")

        checked = _validate_success_payload(dict(SUCCESS, verification="weak"))
        self.assertEqual(checked["verification"], "weak")


if __name__ == "__main__":
    unittest.main()
