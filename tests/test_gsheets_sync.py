from __future__ import annotations

import unittest

from app.etl.gsheets_sync import parse_sheet_observations


class TestGSheetsSync(unittest.TestCase):
    def test_extracts_only_activities_coffee_and_wakeup_notes(self) -> None:
        data_values = [
            [
                "Night",
                "Date",
                "CPAP Usage Time",
                "CPAP AHI",
                "Activity Notes for day before sleep",
                "# of cups of morning coffee",
                "Self Observation Notes on previous night sleeping experience ",
            ],
            [
                "1",
                "10/13/26",
                "8h 08m",
                "1.00",
                "Crossfit WOD (6pm), Dry Sauna (9pm)",
                "2",
                "",
            ],
            [
                "7",
                "10/19/26",
                "7h 34m",
                "0.40",
                "Cold Plunge (7am), Crossfit WOD (6pm)",
                "2",
                "Was hard to feel comfortable with nose mask this evening.",
            ],
            [
                "8",
                "10/20/26",
                "7h 34m",
                "0.20",
                "",
                "",
                "",
            ],
        ]
        notes_values = [
            ["My regular habits and routines:"],
            ["", "I limit my coffee to the morning only."],
            ["", "I cold plunge four times per week at 48F."],
        ]

        obs_rows, note_rows = parse_sheet_observations(
            data_values=data_values,
            notes_values=notes_values,
            spreadsheet_id="17SgQVoT53xm5299WKZHsIW5PgLInuszCSfeLu50Zsvc",
            run_id="run-gs-1",
            ingested_at_iso="2026-11-20T18:00:00Z",
        )

        # Row 3 had no activity/coffee/observation notes so it is skipped
        self.assertEqual(len(obs_rows), 2)
        self.assertEqual(obs_rows[0]["observation_date"], "2026-10-13")
        self.assertEqual(obs_rows[0]["night_number"], 1)
        self.assertEqual(obs_rows[0]["morning_coffee_cups"], 2.0)
        self.assertIn("Crossfit WOD", obs_rows[0]["activity_notes"])
        self.assertIsNone(obs_rows[0]["wake_up_observations"])

        self.assertEqual(obs_rows[1]["observation_date"], "2026-10-19")
        self.assertIn("nose mask", obs_rows[1]["wake_up_observations"])

        self.assertEqual(len(note_rows), 2)
        self.assertEqual(note_rows[0]["note_category"], "My regular habits and routines")
        self.assertIn("morning only", note_rows[0]["note_text"])


if __name__ == "__main__":
    unittest.main()
