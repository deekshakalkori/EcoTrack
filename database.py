import os
import sqlite3

DATABASE = os.environ.get("ECOTRACK_DB", "ecotrack.db")


def get_connection():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    # SQLite ignores foreign keys unless this is switched on per connection
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _columns(connection, table):
    return [row["name"] for row in connection.execute(f"PRAGMA table_info({table})")]


def init_db():
    connection = get_connection()

    try:
        # ---- Migration from the old shared-data schema ----
        # Old tables are renamed (not deleted) so nothing is lost.
        activity_cols = _columns(connection, "activities")
        if activity_cols and "user_id" not in activity_cols:
            connection.execute(
                "ALTER TABLE activities RENAME TO activities_old_backup"
            )

        challenge_cols = _columns(connection, "challenges")
        if challenge_cols and "completed" in challenge_cols:
            connection.execute(
                "ALTER TABLE challenges RENAME TO challenges_old_backup"
            )

        # ---- Users ----
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

        # ---- Activities (now owned by a user) ----
        connection.execute("""
            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL
                    REFERENCES users(id) ON DELETE CASCADE,
                activity_type TEXT NOT NULL,
                description TEXT NOT NULL,
                points INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_activities_user
            ON activities(user_id, created_at)
        """)

        # ---- Challenges (shared definitions only) ----
        connection.execute("""
            CREATE TABLE IF NOT EXISTS challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                reward_points INTEGER NOT NULL DEFAULT 10
            )
        """)

        # ---- Which user completed which challenge ----
        connection.execute("""
            CREATE TABLE IF NOT EXISTS user_challenges (
                user_id INTEGER NOT NULL
                    REFERENCES users(id) ON DELETE CASCADE,
                challenge_id INTEGER NOT NULL
                    REFERENCES challenges(id) ON DELETE CASCADE,
                completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (user_id, challenge_id)
            )
        """)

        # ---- Weekly reward results (one row per finished week) ----
        # user_id is NULL for a week where nobody earned points
        connection.execute("""
            CREATE TABLE IF NOT EXISTS weekly_winners (
                week_start TEXT PRIMARY KEY,
                user_id INTEGER
                    REFERENCES users(id) ON DELETE SET NULL,
                points INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Sample challenges, only if none exist
        existing = connection.execute(
            "SELECT COUNT(*) FROM challenges"
        ).fetchone()[0]

        if existing == 0:
            connection.executemany("""
                INSERT INTO challenges (title, description, reward_points)
                VALUES (?, ?, ?)
            """, [
                ("Plastic-Free Day",
                 "Avoid single-use plastic for one day.", 20),
                ("Green Walker",
                 "Walk instead of using a vehicle for a short trip.", 15),
                ("Recycling Hero",
                 "Separate and recycle recyclable waste.", 10),
            ])

        connection.commit()

    finally:
        connection.close()


if __name__ == "__main__":
    init_db()
    print("EcoTrack database initialized successfully!")