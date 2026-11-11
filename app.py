import os
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, jsonify, request, g
from flask_cors import CORS
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from werkzeug.security import generate_password_hash, check_password_hash

from database import get_connection, init_db


app = Flask(__name__)
CORS(app)  # for deployment, restrict with CORS(app, origins=["https://your-site"])

# ================= AUTH TOKENS =================
# Set a real secret before deploying:  export ECOTRACK_SECRET="long-random-text"

SECRET_KEY = os.environ.get("ECOTRACK_SECRET", "dev-only-change-me")
TOKEN_MAX_AGE = 7 * 24 * 60 * 60  # 7 days
serializer = URLSafeTimedSerializer(SECRET_KEY, salt="ecotrack-auth")


def make_token(user_id):
    return serializer.dumps({"uid": user_id})


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")

        if not header.startswith("Bearer "):
            return jsonify({"error": "Please log in."}), 401

        try:
            payload = serializer.loads(
                header[7:], max_age=TOKEN_MAX_AGE
            )
        except SignatureExpired:
            return jsonify({"error": "Session expired. Please log in again."}), 401
        except BadSignature:
            return jsonify({"error": "Invalid session. Please log in again."}), 401

        g.user_id = payload["uid"]
        return view(*args, **kwargs)

    return wrapper


# ================= POINTS AND CO2 =================

ACTIVITY_POINTS = {
    "Recycling": 10,
    "Walking": 8,
    "Public Transport": 10,
    "Plastic Reduction": 10,
    "Food Waste Reduction": 7,
    "Sustainable": 10,
}

CO2_SAVINGS = {
    "Walking": 0.15,
    "Public Transport": 0.10,
    "Recycling": 0.05,
    "Plastic Reduction": 0.03,
    "Food Waste Reduction": 0.20,
    "Sustainable": 0.05,
}


def calculate_co2_savings(activity_type):
    return CO2_SAVINGS.get(activity_type, 0.0)


def calculate_eco_score(total_points):
    return min(100, 50 + total_points // 10)


def short_name(full_name):
    parts = full_name.split()
    if len(parts) <= 1:
        return full_name
    return f"{parts[0]} {parts[-1][0]}."


def get_totals(connection, user_id):
    activity = connection.execute(
        """
        SELECT COUNT(*) AS total_activities,
               COALESCE(SUM(points), 0) AS points
        FROM activities
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()

    challenge = connection.execute(
        """
        SELECT COUNT(*) AS completed,
               COALESCE(SUM(c.reward_points), 0) AS points
        FROM user_challenges uc
        JOIN challenges c ON c.id = uc.challenge_id
        WHERE uc.user_id = ?
        """,
        (user_id,)
    ).fetchone()

    return {
        "total_activities": activity["total_activities"],
        "completed_challenges": challenge["completed"],
        "total_points": activity["points"] + challenge["points"],
    }


# ================= RECOMMENDATIONS =================

def generate_recommendations(activity_types):
    recommendations = []

    options = [
        ("Walking", "Choose Green Transport",
         "Try walking for short trips instead of using a vehicle.", "Transport"),
        ("Plastic Reduction", "Reduce Single-Use Plastic",
         "Carry a reusable water bottle and shopping bag.", "Plastic"),
        ("Food Waste Reduction", "Prevent Food Waste",
         "Plan your meals and store leftover food properly.", "Food Waste"),
        ("Recycling", "Recycle More",
         "Separate recyclable paper, plastic, and other materials.", "Recycling"),
        ("Public Transport", "Try Public Transport",
         "Consider a bus or shared transport for your next trip.", "Transport"),
    ]

    for activity_type, title, message, category in options:
        if activity_type not in activity_types:
            recommendations.append({
                "title": title,
                "message": message,
                "category": category,
            })

    if not recommendations:
        recommendations.append({
            "title": "Keep Up the Great Work!",
            "message": "You've tried every eco-activity type. Keep building sustainable habits!",
            "category": "Achievement",
        })

    return recommendations


# ================= INITIALIZE DATABASE =================

init_db()


# ================= HOME AND HEALTH =================

@app.route("/")
def home():
    return jsonify({
        "project": "EcoTrack",
        "message": "EcoTrack backend is running successfully!",
        "status": "success",
    })


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "project": "EcoTrack",
        "timestamp": datetime.now().isoformat(),
    })


# ================= REGISTER =================

@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}

    full_name = data.get("full_name", "")
    email = data.get("email", "")
    contact_number = data.get("contact_number", "")
    password = data.get("password", "")

    if not all(
        isinstance(value, str)
        for value in [full_name, email, contact_number, password]
    ):
        return jsonify({"error": "Invalid input."}), 400

    full_name = full_name.strip()
    email = email.strip().lower()
    contact_number = contact_number.strip()

    if not full_name or not email or not contact_number or not password:
        return jsonify({"error": "Please fill in all fields."}), 400

    if len(password) < 8:
        return jsonify({
            "error": "Password must contain at least 8 characters."
        }), 400

    password_hash = generate_password_hash(password)
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO users (full_name, email, contact_number, password_hash)
            VALUES (?, ?, ?, ?)
            """,
            (full_name, email, contact_number, password_hash)
        )
        connection.commit()

        return jsonify({
            "message": "Account created successfully!",
            "token": make_token(cursor.lastrowid),
            "user": {
                "id": cursor.lastrowid,
                "full_name": full_name,
                "email": email,
            },
        }), 201

    except sqlite3.IntegrityError:
        return jsonify({"error": "This email is already registered."}), 409

    finally:
        connection.close()


# ================= LOGIN =================

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}

    email = data.get("email", "")
    password = data.get("password", "")

    if not isinstance(email, str) or not isinstance(password, str):
        return jsonify({"error": "Invalid input."}), 400

    email = email.strip().lower()

    if not email or not password:
        return jsonify({"error": "Enter your email and password."}), 400

    connection = get_connection()

    try:
        user = connection.execute(
            """
            SELECT id, full_name, email, password_hash
            FROM users WHERE email = ?
            """,
            (email,)
        ).fetchone()

        if user is None or not check_password_hash(
            user["password_hash"], password
        ):
            return jsonify({"error": "Invalid email or password."}), 401

        return jsonify({
            "message": "Login successful!",
            "token": make_token(user["id"]),
            "user": {
                "id": user["id"],
                "full_name": user["full_name"],
                "email": user["email"],
            },
        }), 200

    finally:
        connection.close()


# ================= PROFILE =================

@app.route("/api/me", methods=["GET"])
@login_required
def get_me():
    connection = get_connection()

    try:
        user = connection.execute(
            "SELECT id, full_name, email, contact_number FROM users WHERE id = ?",
            (g.user_id,)
        ).fetchone()

        if user is None:
            return jsonify({"error": "Account not found."}), 404

        return jsonify({"user": dict(user)})

    finally:
        connection.close()


@app.route("/api/me", methods=["PUT"])
@login_required
def update_me():
    data = request.get_json(silent=True) or {}
    full_name = data.get("full_name", "")

    if not isinstance(full_name, str) or not full_name.strip():
        return jsonify({"error": "Name is required."}), 400

    full_name = full_name.strip()[:100]
    connection = get_connection()

    try:
        connection.execute(
            "UPDATE users SET full_name = ? WHERE id = ?",
            (full_name, g.user_id)
        )
        connection.commit()
        return jsonify({"message": "Profile updated.", "full_name": full_name})

    finally:
        connection.close()


# ================= ACTIVITIES =================

@app.route("/api/activities", methods=["POST"])
@login_required
def add_activity():
    data = request.get_json(silent=True) or {}

    activity_type = data.get("activity_type", "")
    description = data.get("description", "")

    if not isinstance(activity_type, str):
        return jsonify({"error": "Invalid activity type."}), 400

    if not isinstance(description, str):
        return jsonify({"error": "Invalid description."}), 400

    activity_type = activity_type.strip()
    description = description.strip()

    if activity_type not in ACTIVITY_POINTS:
        return jsonify({"error": "Please select a valid activity type."}), 400

    if not description:
        return jsonify({"error": "Description is required."}), 400

    points = ACTIVITY_POINTS[activity_type]
    day_start, day_end = local_day_bounds(parse_tz(data.get("tz")))
    connection = get_connection()

    try:
        used_today = connection.execute(
            """
            SELECT COUNT(*) FROM activities
            WHERE user_id = ? AND activity_type = ?
              AND created_at >= ? AND created_at < ?
            """,
            (g.user_id, activity_type, day_start, day_end)
        ).fetchone()[0]

        if used_today >= MAX_PER_TYPE_PER_DAY:
            return jsonify({
                "error": f"Daily limit reached: you can log {activity_type} "
                         f"{MAX_PER_TYPE_PER_DAY} times a day. Try another "
                         "activity or come back tomorrow."
            }), 400

        cursor = connection.execute(
            """
            INSERT INTO activities (user_id, activity_type, description, points)
            VALUES (?, ?, ?, ?)
            """,
            (g.user_id, activity_type, description[:200], points)
        )
        connection.commit()

        return jsonify({
            "message": "Activity saved successfully!",
            "activity": {
                "id": cursor.lastrowid,
                "activity_type": activity_type,
                "description": description[:200],
                "points": points,
                "co2_saved_kg": calculate_co2_savings(activity_type),
            },
        }), 201

    finally:
        connection.close()


@app.route("/api/activities", methods=["GET"])
@login_required
def get_activities():
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT id, activity_type, description, points,
                   strftime('%Y-%m-%dT%H:%M:%SZ', created_at) AS created_at
            FROM activities
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (g.user_id,)
        ).fetchall()

        activities = [dict(row) for row in rows]

        for activity in activities:
            activity["co2_saved_kg"] = calculate_co2_savings(
                activity["activity_type"]
            )

        return jsonify({
            "total_activities": len(activities),
            "activities": activities,
        })

    finally:
        connection.close()


# ================= DASHBOARD =================

@app.route("/api/dashboard", methods=["GET"])
@login_required
def dashboard():
    connection = get_connection()

    try:
        totals = get_totals(connection, g.user_id)

        rows = connection.execute(
            """
            SELECT activity_type, COUNT(*) AS count
            FROM activities
            WHERE user_id = ?
            GROUP BY activity_type
            """,
            (g.user_id,)
        ).fetchall()

        by_type = {row["activity_type"]: row["count"] for row in rows}

        total_co2 = sum(
            calculate_co2_savings(activity_type) * count
            for activity_type, count in by_type.items()
        )

        return jsonify({
            "total_activities": totals["total_activities"],
            "total_eco_points": totals["total_points"],
            "eco_score": calculate_eco_score(totals["total_points"]),
            "completed_challenges": totals["completed_challenges"],
            "total_co2_saved_kg": round(total_co2, 2),
            "activities_by_type": by_type,
        })

    finally:
        connection.close()


# ================= RECOMMENDATIONS =================

@app.route("/api/recommendations", methods=["GET"])
@login_required
def get_recommendations():
    connection = get_connection()

    try:
        rows = connection.execute(
            "SELECT DISTINCT activity_type FROM activities WHERE user_id = ?",
            (g.user_id,)
        ).fetchall()

        recommendations = generate_recommendations(
            [row["activity_type"] for row in rows]
        )

        return jsonify({
            "total_recommendations": len(recommendations),
            "recommendations": recommendations,
        })

    finally:
        connection.close()


# ================= CHALLENGES =================

@app.route("/api/challenges", methods=["GET"])
@login_required
def get_challenges():
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT c.id, c.title, c.description, c.reward_points,
                   (uc.user_id IS NOT NULL) AS completed
            FROM challenges c
            LEFT JOIN user_challenges uc
                   ON uc.challenge_id = c.id AND uc.user_id = ?
            ORDER BY c.id
            """,
            (g.user_id,)
        ).fetchall()

        challenges = []
        for row in rows:
            item = dict(row)
            item["completed"] = bool(item["completed"])
            challenges.append(item)

        return jsonify({
            "total_challenges": len(challenges),
            "challenges": challenges,
        })

    finally:
        connection.close()


@app.route("/api/challenges/<int:challenge_id>/complete", methods=["POST"])
@login_required
def complete_challenge(challenge_id):
    connection = get_connection()

    try:
        challenge = connection.execute(
            "SELECT id, title, reward_points FROM challenges WHERE id = ?",
            (challenge_id,)
        ).fetchone()

        if challenge is None:
            return jsonify({"error": "Challenge not found."}), 404

        try:
            connection.execute(
                """
                INSERT INTO user_challenges (user_id, challenge_id)
                VALUES (?, ?)
                """,
                (g.user_id, challenge_id)
            )
            connection.commit()

        except sqlite3.IntegrityError:
            # UNIQUE (user_id, challenge_id): this user already finished it
            return jsonify({
                "message": "Challenge already completed.",
                "points_awarded": 0,
            }), 200

        return jsonify({
            "message": "Challenge completed successfully!",
            "challenge": challenge["title"],
            "points_awarded": challenge["reward_points"],
        }), 200

    finally:
        connection.close()


# ================= LEADERBOARD =================

@app.route("/api/leaderboard", methods=["GET"])
@login_required
def leaderboard():
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT u.id, u.full_name,
                   COALESCE((SELECT SUM(a.points)
                             FROM activities a
                             WHERE a.user_id = u.id), 0)
                 + COALESCE((SELECT SUM(c.reward_points)
                             FROM user_challenges uc
                             JOIN challenges c ON c.id = uc.challenge_id
                             WHERE uc.user_id = u.id), 0) AS points
            FROM users u
            ORDER BY points DESC, u.full_name
            LIMIT 10
            """
        ).fetchall()

        board = []
        for rank, row in enumerate(rows, start=1):
            board.append({
                "rank": rank,
                "name": short_name(row["full_name"]),
                "eco_points": row["points"],
                "eco_score": calculate_eco_score(row["points"]),
                "is_you": row["id"] == g.user_id,
            })

        return jsonify({"leaderboard": board})

    finally:
        connection.close()


# ================= WEEKLY REWARDS =================
# Weeks run Monday 00:00 to Sunday 23:59 (UTC). When a week finishes, the
# student with the most points EARNED DURING THAT WEEK wins the reward.
# Ties: more activities wins, then the earlier account.
# Edit WEEKLY_REWARD below to your real prize.

WEEKLY_REWARD = {
    "icon": "🏆",
    "title": "Eco Champion of the Week",
    "description": "Awarded to the student with the most eco points this week.",
}

DB_TIME = "%Y-%m-%d %H:%M:%S"


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def week_start_of(moment):
    monday = moment - timedelta(days=moment.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def to_iso(db_time):
    return db_time.replace(" ", "T") + "Z"


def weekly_standings(connection, start, end, limit=10):
    return connection.execute(
        """
        SELECT * FROM (
            SELECT u.id, u.full_name,
                   COALESCE((SELECT SUM(a.points) FROM activities a
                             WHERE a.user_id = u.id
                               AND a.created_at >= ? AND a.created_at < ?), 0)
                 + COALESCE((SELECT SUM(c.reward_points)
                             FROM user_challenges uc
                             JOIN challenges c ON c.id = uc.challenge_id
                             WHERE uc.user_id = u.id
                               AND uc.completed_at >= ? AND uc.completed_at < ?), 0)
                   AS points,
                   (SELECT COUNT(*) FROM activities a
                    WHERE a.user_id = u.id
                      AND a.created_at >= ? AND a.created_at < ?)
                   AS activity_count
            FROM users u
        )
        WHERE points > 0
        ORDER BY points DESC, activity_count DESC, id
        LIMIT ?
        """,
        (start, end) * 3 + (limit,)
    ).fetchall()


def finalize_finished_weeks(connection):
    """Record the winner of every finished week that has no result yet."""
    this_week = week_start_of(utc_now())

    last = connection.execute(
        "SELECT MAX(week_start) FROM weekly_winners"
    ).fetchone()[0]

    if last:
        week = datetime.strptime(last, DB_TIME) + timedelta(days=7)
    else:
        first = connection.execute(
            """
            SELECT MIN(t) FROM (
                SELECT created_at AS t FROM activities
                UNION ALL
                SELECT completed_at AS t FROM user_challenges
            )
            """
        ).fetchone()[0]

        if not first:
            return

        week = week_start_of(datetime.strptime(first, DB_TIME))

    while week < this_week:
        start = week.strftime(DB_TIME)
        end = (week + timedelta(days=7)).strftime(DB_TIME)

        top = weekly_standings(connection, start, end, limit=1)
        winner = top[0] if top else None

        connection.execute(
            """
            INSERT OR IGNORE INTO weekly_winners (week_start, user_id, points)
            VALUES (?, ?, ?)
            """,
            (
                start,
                winner["id"] if winner else None,
                winner["points"] if winner else 0,
            )
        )
        week += timedelta(days=7)

    connection.commit()


@app.route("/api/leaderboard/weekly", methods=["GET"])
@login_required
def weekly_leaderboard():
    connection = get_connection()

    try:
        finalize_finished_weeks(connection)

        start = week_start_of(utc_now())
        end = start + timedelta(days=7)

        rows = weekly_standings(
            connection,
            start.strftime(DB_TIME),
            end.strftime(DB_TIME)
        )

        board = [
            {
                "rank": rank,
                "name": short_name(row["full_name"]),
                "weekly_points": row["points"],
                "is_you": row["id"] == g.user_id,
            }
            for rank, row in enumerate(rows, start=1)
        ]

        return jsonify({
            "week_start": start.isoformat() + "Z",
            "week_ends_at": end.isoformat() + "Z",
            "reward": WEEKLY_REWARD,
            "leaderboard": board,
        })

    finally:
        connection.close()


@app.route("/api/rewards", methods=["GET"])
@login_required
def get_rewards():
    connection = get_connection()

    try:
        finalize_finished_weeks(connection)

        mine = connection.execute(
            """
            SELECT week_start, points FROM weekly_winners
            WHERE user_id = ?
            ORDER BY week_start DESC
            """,
            (g.user_id,)
        ).fetchall()

        recent = connection.execute(
            """
            SELECT w.week_start, w.points, w.user_id, u.full_name
            FROM weekly_winners w
            JOIN users u ON u.id = w.user_id
            ORDER BY w.week_start DESC
            LIMIT 5
            """
        ).fetchall()

        return jsonify({
            "reward": WEEKLY_REWARD,
            "total_won": len(mine),
            "my_rewards": [
                {
                    "week_start": to_iso(row["week_start"]),
                    "points": row["points"],
                    "title": WEEKLY_REWARD["title"],
                }
                for row in mine
            ],
            "recent_winners": [
                {
                    "week_start": to_iso(row["week_start"]),
                    "name": short_name(row["full_name"]),
                    "points": row["points"],
                    "is_you": row["user_id"] == g.user_id,
                }
                for row in recent
            ],
        })

    finally:
        connection.close()


# ================= DAILY STREAK =================
# A streak is the number of days in a row with at least one logged activity.
# Streaks earn badges (no points, so the leaderboard stays fair).
# The browser sends its timezone offset (minutes east of UTC) as "tz", so a
# "day" matches the user's own calendar day.

MAX_PER_TYPE_PER_DAY = 3

STREAK_MILESTONES = [
    (3, "🔥", "3-Day Spark"),
    (7, "🌿", "Week Warrior"),
    (30, "🌳", "Eco Habit Master"),
]


def parse_tz(value):
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return 0
    return max(-840, min(840, minutes))


def local_day_bounds(tz):
    """UTC start and end (as DB strings) of the user's current local day."""
    local_now = utc_now() + timedelta(minutes=tz)
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = local_start - timedelta(minutes=tz)
    end = start + timedelta(days=1)
    return start.strftime(DB_TIME), end.strftime(DB_TIME)


@app.route("/api/streak", methods=["GET"])
@login_required
def get_streak():
    tz = parse_tz(request.args.get("tz"))
    offset = timedelta(minutes=tz)
    connection = get_connection()

    try:
        rows = connection.execute(
            "SELECT created_at FROM activities WHERE user_id = ?",
            (g.user_id,)
        ).fetchall()

        days = {
            (datetime.strptime(row["created_at"], DB_TIME) + offset).date()
            for row in rows
        }
        today = (utc_now() + offset).date()

        # Current streak: still alive if the last log was today or yesterday
        day = today if today in days else today - timedelta(days=1)
        current = 0
        while day in days:
            current += 1
            day -= timedelta(days=1)

        # Longest streak ever
        longest = run = 0
        previous = None
        for d in sorted(days):
            if previous and d - previous == timedelta(days=1):
                run += 1
            else:
                run = 1
            longest = max(longest, run)
            previous = d

        day_start, day_end = local_day_bounds(tz)
        today_count = connection.execute(
            """
            SELECT COUNT(*) FROM activities
            WHERE user_id = ? AND created_at >= ? AND created_at < ?
            """,
            (g.user_id, day_start, day_end)
        ).fetchone()[0]

        return jsonify({
            "current_streak": current,
            "longest_streak": longest,
            "logged_today": today in days,
            "today_count": today_count,
            "max_per_type_per_day": MAX_PER_TYPE_PER_DAY,
            "next_milestone": next(
                (n for n, _, _ in STREAK_MILESTONES if current < n), None
            ),
            "badges": [
                {"days": n, "icon": icon, "title": title,
                 "earned": longest >= n}
                for n, icon, title in STREAK_MILESTONES
            ],
        })

    finally:
        connection.close()


# ================= START SERVER =================

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=5000)