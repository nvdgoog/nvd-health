from __future__ import annotations

from pathlib import Path
import unittest

from app.agent.sql_tools import validate_readonly_sql
from app.etl.bq_loader import build_merge_sql
from app.etl.registry import ConnectorRegistry
from app.etl.schemas import CORE_HEALTH_TABLES, SYSTEM_TABLES, infer_google_takeout_family


class TestRegistrySqlAndDataform(unittest.TestCase):
    def test_connector_registry_routing(self) -> None:
        reg = ConnectorRegistry()

        takeout_csv = "Health Fitness Data_GoogleData/UserSleeps_2026-01-09.csv"
        c1 = reg.resolve(takeout_csv)
        self.assertIsNotNone(c1)
        self.assertEqual(c1.name, "google_takeout")
        self.assertFalse(c1.should_ignore(takeout_csv))

        readme = "Stress Score/Stress Score Readme.txt"
        c_readme = reg.resolve(readme)
        self.assertIsNotNone(c_readme)
        self.assertTrue(c_readme.should_ignore(readme))

        pdf = "8.21.26-11.18.26.pdf"
        c_pdf = reg.resolve(pdf)
        self.assertIsNotNone(c_pdf)
        self.assertEqual(c_pdf.name, "reacthealth_pdf")

        transcend = "uploads/transcend_micro/2026-11/export.csv"
        c_tr = reg.resolve(transcend)
        self.assertIsNotNone(c_tr)
        self.assertEqual(c_tr.name, "transcend_micro")

        zen = "uploads/zenplanner/2026-11/wods.csv"
        c_zp = reg.resolve(zen)
        self.assertIsNotNone(c_zp)
        self.assertEqual(c_zp.name, "zenplanner")

    def test_sharded_family_inference(self) -> None:
        self.assertEqual(
            infer_google_takeout_family("Physical Activity_GoogleData/Heart Rate/heart_rate_2026-11-18.csv"),
            "heart_rate",
        )
        self.assertEqual(
            infer_google_takeout_family("Health Fitness Data_GoogleData/UserSleeps_2026-01-09.csv"),
            "user_sleeps",
        )
        self.assertEqual(
            infer_google_takeout_family("Stress Score/Stress Score.csv"),
            "stress_score",
        )

    def test_readonly_sql_validator(self) -> None:
        ok_sql = """
        -- Verify SpO2 before vs after CPAP
        SELECT era, pre_mean, post_mean
        FROM `house-tully-310623.nvd_health_gold.v_cpap_before_after_summary`;
        """
        validated = validate_readonly_sql(ok_sql)
        self.assertTrue(validated.startswith("SELECT"))

        with_sql = """
        WITH recent AS (
          SELECT * FROM `house-tully-310623.nvd_health_silver.daily_health_summary`
        )
        SELECT COUNT(*) FROM recent
        """
        self.assertTrue(validate_readonly_sql(with_sql).startswith("WITH"))

        for bad in [
            "DELETE FROM `house-tully-310623.nvd_health_bronze.google_heart_rate` WHERE 1=1",
            "DROP TABLE `house-tully-310623.nvd_health_silver.daily_health_summary`",
            "SELECT * FROM `house-tully-310623.nvd_health_gold.v_daily_health_performance`; DROP TABLE x",
            "SELECT * FROM `other_project.other_dataset.secrets`",
            "MERGE `house-tully-310623.nvd_health_bronze.google_stress_score` USING x ON TRUE WHEN MATCHED THEN DELETE",
        ]:
            with self.assertRaises(ValueError):
                validate_readonly_sql(bad)

    def test_dataform_silver_timezone_and_sentinel_rules(self) -> None:
        silver_path = (
            Path(__file__).resolve().parents[1]
            / "dataform"
            / "definitions"
            / "silver"
            / "daily_health_summary.sqlx"
        )
        sqlx = silver_path.read_text(encoding="utf-8")
        # Wake-up date alignment in Pacific Time
        self.assertIn("DATE(sleep_end, 'America/Los_Angeles')", sqlx)
        # -1 sentinels converted to NULL in Silver
        self.assertIn("NULLIF(duration_score, -1)", sqlx)
        self.assertIn("NULLIF(composition_score, -1)", sqlx)
        self.assertIn("NULLIF(revitalization_score, -1)", sqlx)
        # Intraday shifted to Pacific Time
        self.assertIn("DATE(timestamp, 'America/Los_Angeles') AS health_date", sqlx)
        # UTC-midnight daily summary files kept in literal UTC DATE(timestamp)
        self.assertIn("FROM ${ref(\"google_daily_resting_heart_rate\")}", sqlx)
        # Verify literal DATE(timestamp) appears for UTC-midnight daily summaries
        self.assertGreaterEqual(sqlx.count("DATE(timestamp) AS health_date"), 6)

    def test_build_merge_sql_system_and_health_tables(self) -> None:
        etl_spec = SYSTEM_TABLES["bronze_etl_runs"]
        etl_sql = build_merge_sql(
            "house-tully-310623.nvd_health_bronze.bronze_etl_runs",
            "house-tully-310623.nvd_health_bronze._stage_etl",
            etl_spec,
            list(etl_spec.columns.keys()),
        )
        self.assertNotIn("_ingested_at", etl_sql)
        self.assertIn("`updated_at` DESC NULLS LAST", etl_sql)

        ledger_spec = SYSTEM_TABLES["bronze_ingestion_ledger"]
        ledger_sql = build_merge_sql(
            "house-tully-310623.nvd_health_bronze.bronze_ingestion_ledger",
            "house-tully-310623.nvd_health_bronze._stage_ledger",
            ledger_spec,
            list(ledger_spec.columns.keys()),
        )
        self.assertNotIn("_ingested_at", ledger_sql)
        self.assertIn("`ingested_at` DESC NULLS LAST", ledger_sql)

        cpap_spec = CORE_HEALTH_TABLES["bronze_reacthealth_daily_usage"]
        cpap_sql = build_merge_sql(
            "house-tully-310623.nvd_health_bronze.bronze_reacthealth_daily_usage",
            "house-tully-310623.nvd_health_bronze._stage_cpap",
            cpap_spec,
            list(cpap_spec.columns.keys()),
        )
        self.assertIn("report_generated_date", cpap_sql)
        self.assertIn("`_ingested_at` DESC NULLS LAST", cpap_sql)


if __name__ == "__main__":
    unittest.main()
