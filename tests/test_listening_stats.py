import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from listening_stats import summarize


def play(track_id, name, artists, time, duration=180000):
    return dict(track_id=track_id, track_name=name, artists=artists,
                played_at=time, duration_ms=duration)


def test_repeated_plays_and_collaborations():
    plays = [play("a", "Song", ["A", "B", "A"], "2026-11-08T10:00:00Z"),
             play("a", "Song", ["A", "B"], "2026-11-08T11:00:00Z"),
             play("b", "Other", ["B"], "2026-11-08T12:00:00Z", 60000)]
    result = summarize(plays)
    assert result["total_plays"] == 3 and result["unique_tracks"] == 2
    assert result["estimated_minutes"] == 7
    assert result["top_tracks"][0]["plays"] == 2
    assert result["top_artists"] == [{"name": "B", "plays": 3}, {"name": "A", "plays": 2}]


def test_same_title_different_recordings_are_separate():
    result = summarize([play("a", "Same", ["A"], "2026-11-08T10:00:00Z"),
                        play("b", "Same", ["B"], "2026-11-08T11:00:00Z")])
    assert result["unique_tracks"] == 2
    assert result["first_play_at"] == "2026-11-08T10:00:00Z"
    assert result["last_play_at"] == "2026-11-08T11:00:00Z"


def test_empty_history():
    result = summarize([])
    assert result["total_plays"] == result["estimated_minutes"] == 0
    assert result["top_tracks"] == result["top_artists"] == []
    assert result["first_play_at"] is None


def test_weekly_group_uses_local_week_real_time_and_explicit_coverage():
    from datetime import date
    from listening_stats import weekly_group

    monday = date(2026, 11, 2)
    first = play("a", "Song", ["A"], "2026-11-01T23:00:00Z")
    first["ms_played"] = 30000
    outside = play("a", "Song", ["A"], "2026-11-08T23:00:00Z")
    other = play("a", "Song", ["A"], "2026-11-02T12:00:00Z", 60000)
    result = weekly_group([
        {"name": "A", "plays": [first, outside], "covered_days": [monday]},
        {"name": "B", "plays": [other], "covered_days": []},
    ], monday)
    assert [row["name"] for row in result["ranking"]] == ["B", "A"]
    assert result["ranking"][1]["covered_days"] == 1
    assert result["ranking"][0]["covered_days"] == 0
    assert result["group"]["total_plays"] == 2
    assert result["group"]["listening_ms"] == 90000
    assert result["group"]["measured_plays"] == 1
