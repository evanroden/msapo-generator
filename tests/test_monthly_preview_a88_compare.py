"""A88 benchmark receipts must never invent queue wait, percentiles or pixel success."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import qa_monthly_preview_a88_compare as matrix


class A88ComparisonTests(unittest.TestCase):
    def test_three_samples_report_only_min_median_max(self):
        values = {"samples_ms": [10.0, 9.0, 11.0],
                  "n": 3, "min_ms": 9.0, "median_ms": 10.0, "max_ms": 11.0}
        self.assertEqual(matrix._samples(values), 10.0)
        with self.assertRaises(AssertionError):
            matrix._samples({**values, "p95_ms": 10.9})
        with self.assertRaises(AssertionError):
            matrix._samples({**values, "n": 99})
        with self.assertRaises(AssertionError):
            matrix._samples({**values, "median_ms": 9.0})

    def test_cgroup_oom_or_wrong_limit_must_fail(self):
        receipt = {"environment": {"memory_limit_bytes": 512 * 1024 ** 2,
                                   "cpu_quota": 0.5},
                   "memory_events_delta": {"oom": 0, "oom_kill": 0},
                   "peak_process_rss_bytes": 100,
                   "cgroup_peak_bytes": 200,
                   "elapsed_seconds": 1,
                   "python_process_cpu_seconds": 0.1,
                   "child_office_cpu_seconds": 0.2}
        self.assertEqual(matrix._resource(receipt, 512 * 1024 ** 2, .5)["cgroup_peak_bytes"], 200)
        with self.assertRaises(AssertionError):
            matrix._resource(receipt, 1024 ** 3, 1.0)
        with self.assertRaises(AssertionError):
            matrix._resource({**receipt, "memory_events_delta": {"oom": 1, "oom_kill": 0}},
                             512 * 1024 ** 2, .5)

    def test_decoded_browser_image_required_for_each_of_three_runs(self):
        good_image = {"width": 300, "height": 400, "decoded_png_sha256": "a" * 64}
        one = {
            "first_section_image": good_image,
            "thumbnail": good_image,
            "latest_section_image": good_image,
            "preview_generation_changed": True,
            "manual_edit_retained": True,
            "fresh_report_press_to_decoded_section_seconds": 2.,
            "native_upload_to_requested_decoded_thumbnail_seconds": 3.,
            "edit_commit_to_current_section_seconds": 1.,
        }
        data = {"engines": {key: [{**one}, {**one}, {**one}]
                            for key in ("chromium", "webkit")}}
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for case in ("capped", "larger"):
                (root / f"browser-{case}.json").write_text(json.dumps(data))
            result = matrix.browser(root)
            self.assertEqual(result["engines"]["chromium"]["capped"][
                "fresh_report_press_to_decoded_section_seconds"]["n"], 3)
            data["engines"]["chromium"][1]["thumbnail"] = {"width": 0, "height": 400,
                                                            "decoded_png_sha256": "a" * 64}
            (root / "browser-larger.json").write_text(json.dumps(data))
            with self.assertRaises(AssertionError):
                matrix.browser(root)
            data["engines"]["chromium"] = [{**one}, {**one}]
            (root / "browser-larger.json").write_text(json.dumps(data))
            with self.assertRaises(AssertionError):
                matrix.browser(root)


if __name__ == "__main__":
    unittest.main()
