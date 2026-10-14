
import sqlite3
from datetime import datetime

from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

from database import get_connection, init_db


app = Flask(__name__)
CORS(app)

# ================= CO2 SAVINGS =================

CO2_SAVINGS = {
    "Walking": 0.15,
    "Public Transport": 0.10,
    "Recycling": 0.05,
    "Plastic Reduction": 0.03,
    "Food Waste Reduction": 0.20
}


def calculate_co2_savings(activity_type):
    return CO2_SAVINGS.get(activity_type, 0.0)


# ================= ECO RECOMMENDATIONS =================

def generate_recommendations(activity_types):
    recommendations = []

    if "Walking" not in activity_types:
        recommendations.append({
            "title": "Choose Green Transport",
            "message": "Try walking for short trips instead of using a vehicle.",
            "category": "Transport"
        })

    if "Plastic Reduction" not in activity_types:
        recommendations.append({
            "title": "Reduce Single-Use Plastic",
            "message": "Carry a reusable water bottle and shopping bag.",
            "category": "Plastic"
        })

    if "Food Waste Reduction" not in activity_types:
        recommendations.append({
            "title": "Prevent Food Waste",
            "message": "Plan your meals and store leftover food properly.",
            "category": "Food Waste"
        })

    if "Recycling" not in activity_types:
        recommendations.append({
            "title": "Recycle More",
            "message": "Separate recyclable paper, plastic, and other materials.",
            "category": "Recycling"
        })

    if "Public Transport" not in activity_types:
        recommendations.append({
            "title": "Try Public Transport",
            "message": "Consider a bus or shared transport for your next trip.",
            "category": "Transport"
        })

    if not recommendations:
        recommendations.append({
            "title": "Keep Up the Great Work!",
            "message": "You've recorded all five eco-activity types. Keep building sustainable habits!",
            "category": "Achievement"
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
        "status": "success"
    })


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "project": "EcoTrack",
        "timestamp": datetime.now().isoformat()
    })


# ================= ACTIVITY POINTS =================

ACTIVITY_POINTS = {
    "Recycling": 10,
    "Walking": 8,
    "Public Transport": 10,
    "Plastic Reduction": 10,
    "Food Waste Reduction": 7
}


# ================= ADD ACTIVITY =================

@app.route("/api/activities", methods=["POST"])
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
        return jsonify({
            "error": "Please select a valid activity type."
        }), 400

    if not description:
        return jsonify({
            "error": "Description is required."
        }), 400

    points = ACTIVITY_POINTS[activity_type]
    co2_saved = calculate_co2_savings(activity_type)

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO activities
                (activity_type, description, points)
            VALUES (?, ?, ?)
            """,
            (activity_type, description, points)
        )
        connection.commit()

        return jsonify({
            "message": "Activity saved successfully!",
            "activity": {
                "id": cursor.lastrowid,
                "activity_type": activity_type,
                "description": description,
                "points": points,
                "co2_saved_kg": co2_saved
            }
        }), 201

    finally:
        connection.close()


# ================= VIEW ACTIVITIES =================

@app.route("/api/activities", methods=["GET"])
def get_activities():
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT id, activity_type, description, points, created_at
            FROM activities
            ORDER BY id DESC
            """
        ).fetchall()

        activities = [dict(row) for row in rows]

        for activity in activities:
            activity["co2_saved_kg"] = calculate_co2_savings(
                activity["activity_type"]
            )

        return jsonify({
            "total_activities": len(activities),
            "activities": activities
        })

    finally:
        connection.close()


# ================= DASHBOARD =================

@app.route("/api/dashboard", methods=["GET"])
def dashboard():
    connection = get_connection()

    try:
        activity = connection.execute(
            """
            SELECT COUNT(*) AS total_activities,
                   COALESCE(SUM(points), 0) AS activity_points
            FROM activities
            """
        ).fetchone()

        challenges = connection.execute(
            """
            SELECT COALESCE(SUM(reward_points), 0) AS challenge_points
            FROM challenges
            WHERE completed = 1
            """
        ).fetchone()

        total_points = (
            activity["activity_points"]
            + challenges["challenge_points"]
        )

        co2_rows = connection.execute(
            "SELECT activity_type FROM activities"
        ).fetchall()

        total_co2_saved = sum(
            calculate_co2_savings(row["activity_type"])
            for row in co2_rows
        )

        completed_challenges = connection.execute(
            """
            SELECT COUNT(*)
            FROM challenges
            WHERE completed = 1
            """
        ).fetchone()[0]

        return jsonify({
            "total_activities": activity["total_activities"],
            "total_eco_points": total_points,
            "eco_score": min(100, 50 + total_points // 10),
            "completed_challenges": completed_challenges,
            "total_co2_saved_kg": round(total_co2_saved, 2)
        })

    finally:
        connection.close()


# ================= RECOMMENDATIONS =================

@app.route("/api/recommendations", methods=["GET"])
def get_recommendations():
    connection = get_connection()

    try:
        rows = connection.execute(
            "SELECT DISTINCT activity_type FROM activities"
        ).fetchall()

        activity_types = [
            row["activity_type"] for row in rows
        ]

        recommendations = generate_recommendations(activity_types)

        return jsonify({
            "total_recommendations": len(recommendations),
            "recommendations": recommendations
        })

    finally:
        connection.close()


# ================= VIEW CHALLENGES =================

@app.route("/api/challenges", methods=["GET"])
def get_challenges():
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT id, title, description, reward_points, completed
            FROM challenges
            ORDER BY id
            """
        ).fetchall()

        return jsonify({
            "total_challenges": len(rows),
            "challenges": [dict(row) for row in rows]
        })

    finally:
        connection.close()


# ================= COMPLETE CHALLENGE =================

@app.route(
    "/api/challenges/<int:challenge_id>/complete",
    methods=["POST"]
)
def complete_challenge(challenge_id):
    connection = get_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")

        challenge = connection.execute(
            """
            SELECT id, title, reward_points, completed
            FROM challenges
            WHERE id = ?
            """,
            (challenge_id,)
        ).fetchone()

        if challenge is None:
            connection.rollback()
            return jsonify({
                "error": "Challenge not found."
            }), 404

        if challenge["completed"]:
            connection.rollback()
            return jsonify({
                "message": "Challenge already completed.",
                "points_awarded": 0
            }), 200

        connection.execute(
            """
            UPDATE challenges
            SET completed = 1
            WHERE id = ?
            """,
            (challenge_id,)
        )

        connection.commit()

        return jsonify({
            "message": "Challenge completed successfully!",
            "challenge": challenge["title"],
            "points_awarded": challenge["reward_points"]
        }), 200

    except Exception:
        connection.rollback()
        app.logger.exception("Could not complete challenge")

        return jsonify({
            "error": "Could not complete challenge."
        }), 500

    finally:
        connection.close()


# ================= CREATE ACCOUNT =================

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
        return jsonify({
            "error": "Please fill in all fields."
        }), 400

    if len(password) < 8:
        return jsonify({
            "error": "Password must contain at least 8 characters."
        }), 400

    password_hash = generate_password_hash(password)
    connection = get_connection()

    try:
        connection.execute(
            """
            INSERT INTO users
                (full_name, email, contact_number, password_hash)
            VALUES (?, ?, ?, ?)
            """,
            (full_name, email, contact_number, password_hash)
        )
        connection.commit()

        return jsonify({
            "message": "Account created successfully!",
            "user": {
                "full_name": full_name,
                "email": email
            }
        }), 201

    except sqlite3.IntegrityError:
        return jsonify({
            "error": "This email is already registered."
        }), 409

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
        return jsonify({
            "error": "Enter your email and password."
        }), 400

    connection = get_connection()

    try:
        user = connection.execute(
            """
            SELECT id, full_name, email, password_hash
            FROM users
            WHERE email = ?
            """,
            (email,)
        ).fetchone()

        if user is None or not check_password_hash(
            user["password_hash"], password
        ):
            return jsonify({
                "error": "Invalid email or password."
            }), 401

        return jsonify({
            "message": "Login successful!",
            "user": {
                "id": user["id"],
                "full_name": user["full_name"],
                "email": user["email"]
            }
        }), 200

    finally:
        connection.close()


# ================= START SERVER =================

if __name__ == "__main__":
    app.run(debug=True, port=5000)
