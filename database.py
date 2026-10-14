
import sqlite3

DATABASE = "ecotrack.db"


def get_connection():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    connection = get_connection()

    try:
        # Users table for account registration and login
        connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                contact_number TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Activities table
        connection.execute("""
            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_type TEXT NOT NULL,
                description TEXT NOT NULL,
                points INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Challenges table
        connection.execute("""
            CREATE TABLE IF NOT EXISTS challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                reward_points INTEGER NOT NULL DEFAULT 10,
                completed INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Add sample challenges only if none exist
        existing = connection.execute(
            "SELECT COUNT(*) FROM challenges"
        ).fetchone()[0]

        if existing == 0:
            connection.executemany("""
                INSERT INTO challenges
                    (title, description, reward_points)
                VALUES (?, ?, ?)
            """, [
                (
                    "Plastic-Free Day",
                    "Avoid single-use plastic for one day.",
                    20
                ),
                (
                    "Green Walker",
                    "Walk instead of using a vehicle for a short trip.",
                    15
                ),
                (
                    "Recycling Hero",
                    "Separate and recycle recyclable waste.",
                    10
                )
            ])

        connection.commit()

    finally:
        connection.close()


if __name__ == "__main__":
    init_db()
    print("EcoTrack database initialized successfully!")
