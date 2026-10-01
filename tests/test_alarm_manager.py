import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from cassandra.alarm_manager import AlarmManager


class FakeSound:
    enabled = False

    def play(self, *args, **kwargs):
        return None


class AlarmManagerComputeTests(unittest.TestCase):
    def test_once_uses_exact_date_even_in_another_year(self):
        got = AlarmManager._compute_next_trigger(
            "09:30",
            date_ymd="2027-03-15",
            after=datetime(2026, 9, 27, 8, 0),
        )
        self.assertEqual(got, datetime(2027, 3, 15, 9, 30))

    def test_monthly_skips_to_next_month_when_today_already_passed(self):
        got = AlarmManager._compute_next_trigger(
            "07:00",
            day_of_month=15,
            after=datetime(2026, 9, 16, 8, 0),
        )
        self.assertEqual(got, datetime(2026, 10, 15, 7, 0))

    def test_monthly_clamps_day_31_in_february(self):
        got = AlarmManager._compute_next_trigger(
            "08:00",
            day_of_month=31,
            after=datetime(2026, 2, 1, 7, 0),
        )
        self.assertEqual(got, datetime(2026, 2, 28, 8, 0))

    def test_weekly_keeps_weekday_selection(self):
        # 2026-09-27 is Sunday (weekday 6). Next Monday is 28.
        got = AlarmManager._compute_next_trigger(
            "06:00",
            days_of_week=[0],
            after=datetime(2026, 9, 27, 10, 0),
        )
        self.assertEqual(got, datetime(2026, 9, 28, 6, 0))
        self.assertEqual(got.weekday(), 0)

    def test_daily_picks_tomorrow_when_time_passed(self):
        got = AlarmManager._compute_next_trigger(
            "07:00",
            after=datetime(2026, 9, 27, 8, 0),
        )
        self.assertEqual(got, datetime(2026, 9, 28, 7, 0))


class AlarmManagerPersistTests(unittest.TestCase):
    def _manager(self, path: Path) -> AlarmManager:
        return AlarmManager(ring_sound_path="missing.wav", sound_player=FakeSound(), db_path=str(path))

    def test_add_once_persists_date_ymd(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "alarms.json"
            mgr = self._manager(db)
            alarm = mgr.add_alarm("10:15", recurring_daily=True, label="Consulta", date_ymd="2027-12-25")
            self.assertEqual(alarm.date_ymd, "2027-12-25")
            self.assertFalse(alarm.recurring_daily)
            self.assertIsNone(alarm.days_of_week)
            self.assertEqual(alarm.next_trigger_at, "2027-12-25T10:15:00")
            saved = json.loads(db.read_text(encoding="utf-8"))
            self.assertEqual(saved[0]["date_ymd"], "2027-12-25")

    def test_add_monthly_persists_day_of_month(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "alarms.json"
            mgr = self._manager(db)
            alarm = mgr.add_alarm("08:00", recurring_daily=False, label="Conta", day_of_month=31)
            self.assertEqual(alarm.day_of_month, 31)
            self.assertTrue(AlarmManager._is_recurring(alarm))

    def test_load_old_alarm_without_new_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "alarms.json"
            db.write_text(
                json.dumps(
                    [
                        {
                            "id": "oldalarm01",
                            "label": "Acordar",
                            "time_hhmm": "07:30",
                            "recurring_daily": True,
                            "days_of_week": [0, 1, 2, 3, 4],
                            "next_trigger_at": "2026-09-28T07:30:00",
                            "enabled": True,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            mgr = self._manager(db)
            alarms = mgr.list_alarms()
            self.assertEqual(len(alarms), 1)
            self.assertIsNone(alarms[0]["date_ymd"])
            self.assertIsNone(alarms[0]["day_of_month"])
            self.assertEqual(alarms[0]["days_of_week"], [0, 1, 2, 3, 4])

    def test_rejects_invalid_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = self._manager(Path(tmp) / "alarms.json")
            with self.assertRaises(ValueError):
                mgr.add_alarm("09:00", False, date_ymd="2026-13-40")


class AlarmUiHtmlTests(unittest.TestCase):
    def test_calendar_markup_is_in_web_ui(self):
        html = Path(__file__).resolve().parents[1].joinpath("web_server.py").read_text(encoding="utf-8")
        for needle in (
            'id="alm-cal-grid"',
            "function renderAlmCalendar",
            "function onAlmCalDayClick",
            "function toggleAlmCalPicker",
            "shiftAlmCalYear",
            "date_ymd",
            "day_of_month",
            "function isGatewayTimeout",
            "function waitForChatReply",
            "alertUnlessTimeout",
        ):
            self.assertIn(needle, html)


if __name__ == "__main__":
    unittest.main()
