"""
Builds the system prompt context for the AI race engineer assistant.
"""

from database.db import get_db
from processing.analyzer import format_lap_time


RACE_ENGINEER_PROMPT = """\
You are a veteran Formula 1 and IndyCar race engineer with 20 years of experience at the highest level of motorsport.
You are the on-site data engineer for the Purdue High School EV Grand Prix team competing at Indianapolis.
Your job is to analyze kart telemetry data and give precise, actionable coaching to the drivers and team.

COMMUNICATION STYLE:
- Talk like a real F1/IndyCar engineer on the pit wall radio: direct, specific, data-driven, professional
- Use proper motorsport terminology: corner entry, minimum speed, apex, trail braking, traction circle,
  understeer, oversteer, brake release point, throttle application, sector time, delta, stint, install lap,
  scrub speed, rotation, chassis balance, yaw, pitch, roll
- Reference actual numbers from the data (speeds in mph, times in seconds, g-forces)
- When something needs fixing, state exactly what it is and give a specific, actionable fix
- Be encouraging but direct — this is a high school team building their craft
- Keep responses focused: 3-5 bullet points or one sharp paragraph — no fluff, no filler
- Engineers don't say "Great question!" — they say "Copy that, here's what the data shows."

KART & COMPETITION CONTEXT:
- Two electric karts (Kart #6 and Kart #70) — instant torque from standstill, no gear changes,
  regenerative braking possible depending on controller setup
- Drivers: Jayden, Kolten, James (each recording is tagged with the driver who ran it)
- Competition: Purdue High School EV Grand Prix, Indianapolis area circuit (~500-foot circuit)
- Short lap times (typically 11-48 seconds), tight and technical layout
- GPS accuracy: ±2.3 feet — good enough for track position and braking marker analysis
- IMU at 50Hz — high enough resolution to analyze brake pressure ramp, turn-in snap, throttle application

TWO-KART KNOWLEDGE:
{kart_comparison_data}

CURRENT SESSION DATA:
{session_data}

IMPORTANT RULES:
- When analyzing, note differences between the two karts if the data shows them
- Only cite numbers that appear in the data above — never guess or invent figures
- If asked about something not in the data, say clearly what additional data would help
- Always give at least one specific, actionable recommendation the driver can try on the next run
"""


def build_kart_context():
    """Build a summary comparing both karts across all sessions."""
    db = get_db()
    karts = db.execute("SELECT * FROM karts ORDER BY id").fetchall()
    lines = []
    for k in karts:
        stats = db.execute(
            """SELECT MIN(best_lap_time) as best, AVG(avg_lap_time) as avg_lap,
                      MAX(max_speed_mph) as top_speed, SUM(lap_count) as total_laps
               FROM sessions WHERE kart_id=? AND lap_count > 0""",
            (k['id'],)
        ).fetchone()
        lines.append(f"{k['name']}:")
        if stats['best']:
            lines.append(f"  All-time best lap: {format_lap_time(stats['best'])}")
            lines.append(f"  Average lap: {format_lap_time(stats['avg_lap'])}" if stats['avg_lap'] else "  Average lap: N/A")
            lines.append(f"  Top speed: {round(stats['top_speed'], 1)} mph" if stats['top_speed'] else "  Top speed: N/A")
            lines.append(f"  Total laps logged: {stats['total_laps'] or 0}")
        else:
            lines.append("  No sessions uploaded yet")
    db.close()
    return "\n".join(lines) if lines else "No kart data available yet."


def build_session_context(session_id):
    """Build a detailed context string for a specific session."""
    db = get_db()
    sess = db.execute(
        "SELECT s.*, k.name as kart_name FROM sessions s JOIN karts k ON k.id=s.kart_id WHERE s.id=?",
        (session_id,)
    ).fetchone()
    if not sess:
        db.close()
        return "Session not found."

    laps = db.execute(
        """SELECT l.global_lap, l.lap_time, l.is_best, l.max_speed, l.max_lat_g, l.max_inline_g,
                  r.name as rec_name, r.driver
           FROM laps l JOIN recordings r ON r.id=l.recording_id
           WHERE l.session_id=? ORDER BY l.global_lap ASC""",
        (session_id,)
    ).fetchall()
    drv_rows = db.execute(
        "SELECT DISTINCT driver FROM recordings WHERE session_id=? AND driver IS NOT NULL",
        (session_id,)
    ).fetchall()
    db.close()

    drivers_str = ', '.join([d['driver'] for d in drv_rows]) if drv_rows else 'unknown'
    lines = [
        f"Kart: {sess['kart_name']}",
        f"Session name: {sess['name']}",
        f"Date: {sess['event_date'] or 'unknown'}",
        f"Driver(s) in this session: {drivers_str}",
        f"Total laps: {sess['lap_count'] or 0}",
    ]
    if sess['best_lap_time']:
        lines.append(f"Best lap: {format_lap_time(sess['best_lap_time'])}")
    if sess['avg_lap_time']:
        lines.append(f"Average lap: {format_lap_time(sess['avg_lap_time'])}")
    if sess['consistency_pct'] is not None:
        lines.append(f"Consistency score: {sess['consistency_pct']}%")
    if sess['max_speed_mph']:
        lines.append(f"Session top speed: {sess['max_speed_mph']} mph")

    if laps:
        lines.append("\nLap-by-lap breakdown:")
        for l in laps:
            marker = " ← BEST" if l['is_best'] else ""
            spd = f"  max {l['max_speed']} mph" if l['max_speed'] else ""
            lat = f"  lat {l['max_lat_g']}g" if l['max_lat_g'] else ""
            inl = f"  brake {l['max_inline_g']}g" if l['max_inline_g'] else ""
            drv = f"  [{l['driver']}]" if l['driver'] else ""
            lines.append(
                f"  Lap {l['global_lap']}: {format_lap_time(l['lap_time'])}{marker}{spd}{lat}{inl}{drv}"
            )

    return "\n".join(lines)


def build_full_context(session_id):
    """Assemble the complete system prompt for a session."""
    kart_data = build_kart_context()
    session_data = build_session_context(session_id)
    return RACE_ENGINEER_PROMPT.format(
        kart_comparison_data=kart_data,
        session_data=session_data,
    )
