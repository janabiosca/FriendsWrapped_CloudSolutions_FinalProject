"""Run the weekly ranking with fictional listening data."""
from datetime import date, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from listening_stats import weekly_group


def demo_weekly_ranking():
    monday = date(2026, 11, 2)
    members = []
    for name, daily_plays, coverage in [
        ("Alba", 5, 7), ("Bruna", 7, 5), ("Clara", 3, 7), ("Duna", 4, 4),
    ]:
        covered = [monday + timedelta(days=i) for i in range(coverage)]
        plays = [
            {"played_at": f"{day}T18:{i:02d}:00+01:00",
             "track_id": f"demo-{i % 2}",
             "track_name": ("Órbita", "Luz de puerto")[i % 2],
             "artists": [("Dúo Solar", "Mar de Fondo")[i % 2]],
             "duration_ms": 200000, "ms_played": 150000 if i % 2 == 0 else 180000}
            for day in covered[:-1] for i in range(daily_plays)
        ]
        members.append({"name": name, "covered_days": covered, "plays": plays})

    return weekly_group(members, monday)


def main():
    result = demo_weekly_ranking()
    print("Friends Wrapped | DEMO CON DATOS FICTICIOS | 2–8 de noviembre")
    print("Puesto  Perfil    Reproducciones  Minutos registrados  Días con cobertura")
    for row in result["ranking"]:
        print(f"{row['rank']:>6}  {row['name']:<8}  {row['total_plays']:>14}"
              f"  {row['estimated_minutes']:>19.1f}  {row['covered_days']}/7")
    print("Canciones del grupo")
    for track in result["group"]["top_tracks"]:
        print(f"  {track['name']} · {track['plays']} reproducciones")
    print("Artistas del grupo")
    for artist in result["group"]["top_artists"]:
        print(f"  {artist['name']} · {artist['plays']} reproducciones")


if __name__ == "__main__":
    main()
