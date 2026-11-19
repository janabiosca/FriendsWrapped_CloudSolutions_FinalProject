"""Verify that ranking order preserves member identity and local-week boundaries."""
from datetime import date, datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import show_group_stats


def test_ranked_members_keep_their_own_sync_metadata(monkeypatch):
    profiles = {
        'anna': {'display_name': 'Same name', 'last_sync_status': 'ok', 'possible_gaps': 0},
        'helena': {'display_name': 'Same name', 'last_sync_status': 'failed', 'possible_gaps': 2},
        'jana': {'display_name': 'Jana', 'last_sync_status': 'ok'},
    }
    calls = []
    def history(user, start, end):
        calls.append((start, end))
        if user == 'jana':
            return []
        return [{'track_id': user, 'track_name': 'Song', 'artists': ['Artist'],
                 'played_at': '2026-11-16T10:00:00Z',
                 'duration_ms': 60000 if user == 'anna' else 120000}]
    monkeypatch.setattr(show_group_stats.store, 'group_members', lambda group: list(profiles))
    monkeypatch.setattr(show_group_stats.store, 'get_profile', lambda user: profiles[user])
    monkeypatch.setattr(show_group_stats.store, 'plays_between', history)
    result = show_group_stats.weekly_from_store('friends', date(2026, 11, 16),
                                                datetime(2026, 11, 19, 12, tzinfo=timezone.utc))
    assert [row['user_id'] for row in result['ranking']] == ['helena', 'anna', 'jana']
    assert result['ranking'][0]['possible_gaps'] == 2
    assert result['ranking'][1]['last_sync_status'] == 'ok'
    assert result['ranking'][2]['total_plays'] == 0
    assert all(row['covered_days'] == 0 for row in result['ranking'])
    assert result['group']['total_plays'] == 2
    assert calls[0] == ('2026-11-15T23:00:00.000Z', '2026-11-19T12:00:00.000Z')
