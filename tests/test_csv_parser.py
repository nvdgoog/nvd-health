from __future__ import annotations

import unittest

from app.etl.csv_parser import iter_rfc4180_csv_chunks, parse_rfc4180_csv_bytes
from app.etl.schemas import CORE_HEALTH_TABLES, get_spec_for_google_family, infer_google_takeout_family


class TestCsvParser(unittest.TestCase):
    def test_multiline_quoted_intervals_and_tabs(self) -> None:
        raw = (
            b"exercise_id,exercise_type,start_time,end_time,duration_milliseconds,intervals,data_source\n"
            b'12345,RUN,2026-10-15T14:00:00Z,2026-10-15T14:30:00Z,1800000,"[{\n\t""start"": ""14:00"",\n\t""end"": ""14:15""\n}]",Pixel Watch 3\n'
        )
        spec = CORE_HEALTH_TABLES["google_user_exercises"]
        rows, _ = parse_rfc4180_csv_bytes(
            raw,
            spec=spec,
            source_file="Health Fitness Data_GoogleData/UserExercises_2026-10-15.csv",
            run_id="run-1",
            ingested_at_iso="2026-11-19T00:00:00Z",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["exercise_id"], "12345")
        self.assertEqual(rows[0]["duration_milliseconds"], 1800000)
        self.assertIn("\n\t", rows[0]["intervals"])
        self.assertEqual(rows[0]["_run_id"], "run-1")

    def test_breathing_quality_multiline_intervals(self) -> None:
        raw = (
            b"timestamp,breathing quality,optimal breathing intervals,strained breathing intervals,data source\n"
            b'2026-10-14T00:00:00Z,OPTIMAL,"01:10-02:30\n\t03:00-05:00","05:15-05:25",Pixel Watch 3\n'
        )
        spec = CORE_HEALTH_TABLES["google_daily_sleep_breathing_quality"]
        rows, _ = parse_rfc4180_csv_bytes(
            raw,
            spec=spec,
            source_file="Physical Activity_GoogleData/Daily Sleep Breathing Quality/daily_sleep_breathing_quality.csv",
            run_id="run-1",
            ingested_at_iso="2026-11-19T00:00:00Z",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["timestamp"], "2026-10-14T00:00:00Z")
        self.assertEqual(rows[0]["breathing_quality"], "OPTIMAL")
        self.assertIn("\n\t", rows[0]["optimal_breathing_intervals"])

    def test_nan_to_null_in_temperature_derivations(self) -> None:
        raw = (
            b"timestamp,nightly temperature celsius,baseline temperature celsius,relative nightly stddev 30d celsius,data source\n"
            b"2025-01-10T00:00:00Z,33.6418431372549,NaN,NaN,Google Health App\n"
        )
        spec = CORE_HEALTH_TABLES["google_daily_sleep_temperature_derivations"]
        rows, _ = parse_rfc4180_csv_bytes(
            raw,
            spec=spec,
            source_file="daily_sleep_temperature_derivations.csv",
            run_id="run-1",
            ingested_at_iso="2026-11-19T00:00:00Z",
        )
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["nightly_temperature_celsius"], 33.6418431372549)
        self.assertIsNone(rows[0]["baseline_temperature_celsius"])
        self.assertIsNone(rows[0]["relative_nightly_stddev_30d_celsius"])

    def test_preserves_minus_one_sentinels_in_bronze_sleep_scores(self) -> None:
        raw = (
            b"sleep_id,sleep_score_id,data_source,score_utc_offset,score_time,overall_score,duration_score,composition_score,revitalization_score,sleep_time_minutes,deep_sleep_minutes,rem_sleep_percent,resting_heart_rate,sleep_goal_minutes,waso_count_long_wakes,waso_count_all_wake_time,restlessness_normalized,hr_below_resting_hr,sleep_score_created,sleep_score_last_updated\n"
            b"1014155564496061720,4552287448003080960,DERIVED,-07:00,2026-08-23T14:03:00Z,86.482,-1,-1,-1,452,97,16.45,49,465,7.33,22,0.07,0.91,2026-08-23T14:04:49Z,2026-08-23T14:04:49Z\n"
        )
        spec = CORE_HEALTH_TABLES["google_user_sleep_scores"]
        rows, _ = parse_rfc4180_csv_bytes(
            raw,
            spec=spec,
            source_file="UserSleepScores_2026-01-09.csv",
            run_id="run-1",
            ingested_at_iso="2026-11-19T00:00:00Z",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["duration_score"], -1.0)
        self.assertEqual(rows[0]["composition_score"], -1.0)
        self.assertEqual(rows[0]["revitalization_score"], -1.0)

    def test_stress_score_and_daily_readiness(self) -> None:
        stress_raw = (
            b"DATE,UPDATED_AT,STRESS_SCORE,SLEEP_POINTS,MAX_SLEEP_POINTS,RESPONSIVENESS_POINTS,MAX_RESPONSIVENESS_POINTS,EXERTION_POINTS,MAX_EXERTION_POINTS,STATUS,CALCULATION_FAILED\n"
            b"2025-01-11T00:00:00,2025-01-11T15:00:12.762,78,0,0,0,0,0,0,READY_NOT_PREMIUM,false\n"
        )
        stress_rows, _ = parse_rfc4180_csv_bytes(
            stress_raw,
            spec=CORE_HEALTH_TABLES["google_stress_score"],
            source_file="Stress Score/Stress Score.csv",
            run_id="run-1",
            ingested_at_iso="2026-11-19T00:00:00Z",
        )
        self.assertEqual(stress_rows[0]["date"], "2025-01-11T00:00:00Z")
        self.assertEqual(stress_rows[0]["stress_score"], 78.0)
        self.assertFalse(stress_rows[0]["calculation_failed"])

        readiness_raw = (
            b"timestamp,score,type,readiness level,sleep readiness,heart rate variability readiness,resting heart rate readiness,data source\n"
            b"2025-01-16,62,MEDIUM,TYPE_UNSPECIFIED,HIGH,MEDIUM,HIGH,Google Health App\n"
        )
        readiness_rows, _ = parse_rfc4180_csv_bytes(
            readiness_raw,
            spec=CORE_HEALTH_TABLES["google_daily_readiness"],
            source_file="daily_readiness.csv",
            run_id="run-1",
            ingested_at_iso="2026-11-19T00:00:00Z",
        )
        self.assertEqual(readiness_rows[0]["timestamp"], "2025-01-16")
        self.assertEqual(readiness_rows[0]["score"], 62.0)

    def test_dynamic_schema_inference(self) -> None:
        raw = (
            b"timestamp,custom metric,device_id,data source\n"
            b"2026-10-01T08:00:00Z,42.5,999111222,Pixel Watch 3\n"
        )
        family = infer_google_takeout_family(
            "Physical Activity_GoogleData/Custom Metric/custom_metric_2026-10-01.csv"
        )
        spec = get_spec_for_google_family(family)
        rows, cols = parse_rfc4180_csv_bytes(
            raw,
            spec=spec,
            source_file="custom_metric_2026-10-01.csv",
            run_id="run-1",
            ingested_at_iso="2026-11-19T00:00:00Z",
        )
        self.assertEqual(spec.table_name, "google_custom_metric")
        self.assertEqual(cols["timestamp"], "TIMESTAMP")
        self.assertEqual(cols["custom_metric"], "FLOAT64")
        self.assertEqual(cols["device_id"], "STRING")
        self.assertEqual(rows[0]["custom_metric"], 42.5)

    def test_streaming_chunks_bounded_memory(self) -> None:
        lines = ["timestamp,beats per minute,data source"]
        for i in range(5):
            lines.append(f"2026-11-18T00:00:0{i}Z,{60 + i}.0,Pixel Watch 3")
        raw = ("\n".join(lines) + "\n").encode("utf-8")
        spec = CORE_HEALTH_TABLES["google_heart_rate"]
        chunks = list(
            iter_rfc4180_csv_chunks(
                data=raw,
                spec=spec,
                source_file="heart_rate_2026-11-18.csv",
                run_id="run-chunk",
                ingested_at_iso="2026-11-19T00:00:00Z",
                chunk_size=2,
            )
        )
        self.assertEqual([len(c[0]) for c in chunks], [2, 2, 1])
        self.assertEqual(chunks[2][0][0]["beats_per_minute"], 64.0)


if __name__ == "__main__":
    unittest.main()
