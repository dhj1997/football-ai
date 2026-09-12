from datetime import UTC, datetime, timedelta

from app.notifier import notification_due


def _fixture(delta_minutes: int, notified: bool = False):
    kickoff = (datetime.now(UTC) + timedelta(minutes=delta_minutes)).isoformat()
    return {
        "status": "scheduled",
        "kickoff": kickoff,
        "evidence": {"automation_refresh": {"notified_1h_at": "x"}} if notified else {},
    }


def test_notification_due_only_within_one_hour_window():
    assert notification_due(_fixture(30)) is True
    assert notification_due(_fixture(90)) is False
    assert notification_due(_fixture(-5)) is False
    assert notification_due(_fixture(30, notified=True)) is False
