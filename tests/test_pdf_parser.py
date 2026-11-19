from __future__ import annotations

import unittest

from app.etl.pdf_parser import parse_hhmm_duration, parse_mmddyy, parse_reacthealth_pages


class TestReactHealthPdfParser(unittest.TestCase):
    def test_date_and_duration_parsing(self) -> None:
        self.assertEqual(parse_mmddyy("11/18/26"), "2026-11-18")
        self.assertEqual(parse_mmddyy("8/21/26"), "2026-08-21")
        mins, hrs = parse_hhmm_duration("07:09")
        self.assertEqual(mins, 429)
        self.assertEqual(hrs, 7.15)
        z_mins, z_hrs = parse_hhmm_duration("00:00")
        self.assertEqual(z_mins, 0)
        self.assertEqual(z_hrs, 0.0)

    def test_parse_reacthealth_pages_with_no_data_and_zero_minutes(self) -> None:
        page1 = """
        ReactHealth Sleep Therapy Report
        Date range: 8/21/26 - 11/18/26
        Report generated on: 11/19/26
        Usage Days: 37/90 days (41.11%)
        >= 4 hours: 37 days
        Best 30: 10/20/26 - 11/18/26 30/30 days (100.0%)
        Avg Pressure: 5.2 Avg P95: 6.3 Avg Leak: 6.0 Avg AHI: 0.5 Avg CAI: 0.1
        """
        page2 = """
        Date Time Pressure AHI P95 CAI Avg Leak Mode Device SN
        11/18/26 07:09 5.0 0.1 5.5 0.0 3.9 Auto-CPAP A3126439542
        11/17/26 07:46 5.2 0.1 6.0 0.0 6.3 Auto-CPAP A3126439542
        10/13/26 08:08 6.0 1.0 7.5 0.0 17.7 Auto-CPAP A3126439542
        10/12/26 No data received
        10/7/26 00:00 0.0 0.0 0.0 0.0 0.0 CPAP A3126439542
        10/6/26 No data received
        """
        res = parse_reacthealth_pages(
            pages_text=[page1, page2],
            source_file="8.21.26-11.18.26.pdf",
            run_id="run-pdf-1",
            ingested_at_iso="2026-11-19T10:00:00Z",
        )

        meta = res.report_metadata
        self.assertEqual(meta["report_date_range_start"], "2026-08-21")
        self.assertEqual(meta["report_date_range_end"], "2026-11-18")
        self.assertEqual(meta["report_generated_date"], "2026-11-19")
        self.assertEqual(meta["usage_days"], 37)
        self.assertEqual(meta["total_days"], 90)
        self.assertEqual(meta["days_ge_4h"], 37)
        self.assertEqual(meta["best30_start"], "2026-10-20")
        self.assertEqual(meta["best30_end"], "2026-11-18")
        self.assertEqual(meta["best30_pct"], 100.0)
        self.assertEqual(meta["avg_ahi"], 0.5)
        self.assertEqual(meta["device_sn"], "A3126439542")
        self.assertEqual(meta["valid_days_count"], 4)
        self.assertEqual(meta["no_data_days_count"], 2)
        self.assertEqual(meta["zero_minute_days_count"], 1)

        # 'No data received' skipped; 00:00 preserved
        dates = [r["usage_date"] for r in res.daily_rows]
        self.assertEqual(
            dates,
            ["2026-11-18", "2026-11-17", "2026-10-13", "2026-10-07"],
        )
        self.assertEqual(res.daily_rows[0]["usage_minutes"], 429)
        self.assertEqual(res.daily_rows[0]["usage_hours"], 7.15)
        self.assertEqual(res.daily_rows[3]["usage_minutes"], 0)
        self.assertEqual(res.daily_rows[3]["mode"], "CPAP")


if __name__ == "__main__":
    unittest.main()
