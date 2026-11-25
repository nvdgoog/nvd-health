from __future__ import annotations

import unittest

from app.etl.bq_loader import build_merge_sql
from app.etl.gdrive_transcend_sync import (
    parse_drive_folder_id,
    parse_public_drive_folder_html,
)
from app.etl.registry import ConnectorRegistry
from app.etl.schemas import CORE_HEALTH_TABLES
from app.etl.transcend_parser import parse_transcend_pages


class TestTranscendMicroIngestion(unittest.TestCase):
    def test_parses_standard_extended_and_faa_reports(self) -> None:
        standard_text = """
        CPAP Compliance Report 1 day
        Patient Details
        Patient Name Jane Doe
        Device Serial TR123456
        Patient Setting
        Starting Pressure 4 (cmH2O)
        Maximum Pressure 20 (cmH2O)
        Minimum Pressure 4 (cmH2O)
        Usage
        Dates of Report 11-24-2026 to 11-25-2026
        Days Used 1 of 1 days (100%)
        Average Hours/Night 7.8
        AHI Summary
        AHI Index 1.54
        Apnea Index 0
        Hypopnea Index 1.54
        Leak Summary
        Average Leak 5.47 (L/Min)
        95 Percentile Leak 17 (L/Min)
        Pressure Summary
        Minimum Pressure 4 (cmH2O)
        Maximum Pressure 6 (cmH2O)
        Average Pressure 4.14 (cmH2O)
        95 Percentile Pressure 5.5 (cmH2O)
        Report Generated on 11/25/2026, 6:29:48 AM **
        """
        extended_text = standard_text + """
        Average Length of Apneas (sec) 0
        Longest Apnea (sec) 0
        Flow-Limited Index 7
        Snore Index 0
        Sleep Score Summary
        Sleep Score 95 of 100
        Mask Removed Average 0
        Report Generated on 11/25/2026, 6:30:02 AM **
        """
        faa_text = """
        FAA CPAP Compliance Report
        Patient Name: Jane Doe
        Device Serial Number: TR123456
        Date Range of Use (Line 6) From: 11/24/2026 To: 11/25/2026
        Device Usage (Line 7) # of Days Used: 1 # of Days Covered: 1
        Usage Days (Line 8) % of Days Used: 100
        Average Usage Hours (Line 9) Hours: 7 Minutes: 48
        AHI with Treatment (Line 10) AHI: 1.54
        Report Generated on: 11/25/2026, 6:30:15 AM **
        """

        std = parse_transcend_pages([standard_text], "std.pdf", "run-1", "2026-11-25T15:00:00Z")
        ext = parse_transcend_pages([extended_text], "ext.pdf", "run-1", "2026-11-25T15:00:00Z")
        faa = parse_transcend_pages([faa_text], "faa.pdf", "run-1", "2026-11-25T15:00:00Z")

        self.assertEqual(std.daily_rows[0]["report_priority"], 2)
        self.assertEqual(ext.daily_rows[0]["report_priority"], 3)
        self.assertEqual(faa.daily_rows[0]["report_priority"], 1)

        self.assertEqual(ext.daily_rows[0]["usage_date"], "2026-11-25")
        self.assertEqual(ext.daily_rows[0]["device_sn"], "TR123456")
        self.assertEqual(ext.daily_rows[0]["usage_minutes"], 468)
        self.assertEqual(ext.daily_rows[0]["usage_hours"], 7.8)
        self.assertEqual(ext.daily_rows[0]["pressure"], 4.14)
        self.assertEqual(ext.daily_rows[0]["p95_pressure"], 5.5)
        self.assertEqual(ext.daily_rows[0]["avg_leak"], 5.47)
        self.assertEqual(ext.daily_rows[0]["p95_leak"], 17.0)
        self.assertEqual(ext.daily_rows[0]["ahi"], 1.54)
        self.assertEqual(ext.daily_rows[0]["flow_limited_index"], 7.0)
        self.assertEqual(ext.daily_rows[0]["sleep_score"], 95.0)

        self.assertEqual(faa.daily_rows[0]["usage_minutes"], 468)
        self.assertEqual(faa.daily_rows[0]["usage_hours"], 7.8)
        self.assertEqual(faa.daily_rows[0]["ahi"], 1.54)

    def test_multiday_summary_writes_report_only_without_daily_row(self) -> None:
        text = """
        CPAP Compliance Report 30 days
        Device Serial TR123456
        Dates of Report 11-01-2026 to 11-30-2026
        Days Used 10 of 30 days (33%)
        Average Hours/Night 6.5
        AHI Index 1.2
        """
        res = parse_transcend_pages([text], "30d.pdf", "run-1", "2026-11-30T10:00:00Z")
        self.assertEqual(res.report_metadata["total_days"], 30)
        self.assertEqual(len(res.daily_rows), 0)
        self.assertTrue(len(res.warnings) > 0)

    def test_connector_routing_and_priority_merge_sql(self) -> None:
        reg = ConnectorRegistry()
        c_pdf = reg.resolve("uploads/transcend_micro/drive/file1_Report1.pdf")
        self.assertIsNotNone(c_pdf)
        self.assertEqual(c_pdf.name, "transcend_micro")

        c_home = reg.resolve("uploads/reacthealth_pdf/8.21.26-11.18.26.pdf")
        self.assertIsNotNone(c_home)
        self.assertEqual(c_home.name, "reacthealth_pdf")

        spec = CORE_HEALTH_TABLES["transcend_cpap_daily_usage"]
        sql = build_merge_sql(
            "proj.nvd_health_bronze.transcend_cpap_daily_usage",
            "proj.nvd_health_bronze._stage_tr",
            spec,
            list(spec.columns.keys()),
        )
        self.assertIn("`report_priority` DESC NULLS LAST", sql)
        self.assertIn("COALESCE(S.`report_priority`, 0) > COALESCE(T.`report_priority`, 0)", sql)

    def test_drive_folder_id_and_html_parsing(self) -> None:
        fid = parse_drive_folder_id(
            "https://drive.google.com/drive/folders/1dVV82yiTNJs1nQmUNRZpxMunWBiwWRMs?usp=sharing"
        )
        self.assertEqual(fid, "1dVV82yiTNJs1nQmUNRZpxMunWBiwWRMs")
        self.assertEqual(parse_drive_folder_id("1dVV82yiTNJs1nQmUNRZpxMunWBiwWRMs"), fid)

        sample_html = (
            '["1eh0MZNxBiPCSHnjlNMCUFygZOuAuBWUV",["1dVV82yiTNJs1nQmUNRZpxMunWBiwWRMs"]],"Report1795616989036.pdf"'
        )
        files = parse_public_drive_folder_html(sample_html, fid)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["id"], "1eh0MZNxBiPCSHnjlNMCUFygZOuAuBWUV")
        self.assertEqual(files[0]["name"], "Report1795616989036.pdf")


if __name__ == "__main__":
    unittest.main()
