import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'healthcheck'))
from healthcheck import Finding, reconcile


def test_new_issue_alerts():
    alerts, resolved = reconcile([Finding('disk:/', 'Disk full')], {}, 3600, 1000)
    assert len(alerts) == 1 and resolved == []


def test_repeat_within_cooldown_is_silent():
    state = {'disk:/': {'first_seen': 1000, 'last_alert': 1000}}
    alerts, _ = reconcile([Finding('disk:/', 'Disk full')], state, 3600, 1500)
    assert alerts == []


def test_repeat_after_cooldown_alerts_again():
    state = {'disk:/': {'first_seen': 1000, 'last_alert': 1000}}
    alerts, _ = reconcile([Finding('disk:/', 'Disk full')], state, 3600, 5000)
    assert len(alerts) == 1
    assert state['disk:/']['first_seen'] == 1000


def test_resolved_when_issue_clears():
    state = {'disk:/': {'first_seen': 1000, 'last_alert': 1000}}
    alerts, resolved = reconcile([], state, 3600, 2000)
    assert alerts == []
    assert resolved == ['disk:/']
    assert state == {}
