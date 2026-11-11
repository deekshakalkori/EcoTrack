"""Automated EcoTrack tests. Run with:  pip install pytest  then  pytest -v"""

import os
import tempfile

# Must be set BEFORE importing app, so importing never touches ecotrack.db
os.environ["ECOTRACK_DB"] = os.path.join(tempfile.mkdtemp(), "import.db")

import pytest

import database
import app as app_module


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Fresh empty database for every test
    monkeypatch.setattr(database, "DATABASE", str(tmp_path / "test.db"))
    database.init_db()
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def register(client, email="asha@example.com", name="Asha Rao"):
    return client.post("/api/register", json={
        "full_name": name,
        "email": email,
        "contact_number": "9999999999",
        "password": "EcoTrack123",
    })


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------- accounts ----------

def test_register_and_login(client):
    response = register(client)
    assert response.status_code == 201
    assert "token" in response.get_json()

    login = client.post("/api/login", json={
        "email": "asha@example.com", "password": "EcoTrack123"
    })
    assert login.status_code == 200
    assert login.get_json()["user"]["full_name"] == "Asha Rao"


def test_duplicate_email_rejected(client):
    register(client)
    assert register(client).status_code == 409


def test_short_password_rejected(client):
    response = client.post("/api/register", json={
        "full_name": "A", "email": "a@example.com",
        "contact_number": "1", "password": "short",
    })
    assert response.status_code == 400


def test_wrong_password_rejected(client):
    register(client)
    response = client.post("/api/login", json={
        "email": "asha@example.com", "password": "WrongPassword1"
    })
    assert response.status_code == 401


# ---------- authentication ----------

@pytest.mark.parametrize("path", [
    "/api/dashboard", "/api/activities", "/api/challenges",
    "/api/leaderboard", "/api/recommendations", "/api/me",
])
def test_protected_routes_need_login(client, path):
    assert client.get(path).status_code == 401


def test_bad_token_rejected(client):
    response = client.get("/api/dashboard", headers=auth("not-a-real-token"))
    assert response.status_code == 401


# ---------- activities and data isolation ----------

def test_activity_points_and_dashboard(client):
    token = register(client).get_json()["token"]

    response = client.post("/api/activities", headers=auth(token), json={
        "activity_type": "Recycling", "description": "5 bottles"
    })
    assert response.status_code == 201
    assert response.get_json()["activity"]["points"] == 10

    dash = client.get("/api/dashboard", headers=auth(token)).get_json()
    assert dash["total_activities"] == 1
    assert dash["total_eco_points"] == 10


def test_invalid_activity_type_rejected(client):
    token = register(client).get_json()["token"]
    response = client.post("/api/activities", headers=auth(token), json={
        "activity_type": "Flying", "description": "x"
    })
    assert response.status_code == 400


def test_users_do_not_see_each_others_data(client):
    token_a = register(client, "a@example.com", "Asha Rao").get_json()["token"]
    token_b = register(client, "b@example.com", "Ben Lee").get_json()["token"]

    client.post("/api/activities", headers=auth(token_a), json={
        "activity_type": "Walking", "description": "3 km"
    })

    a_data = client.get("/api/activities", headers=auth(token_a)).get_json()
    b_data = client.get("/api/activities", headers=auth(token_b)).get_json()

    assert a_data["total_activities"] == 1
    assert b_data["total_activities"] == 0


# ---------- challenges ----------

def test_challenge_completed_per_user(client):
    token_a = register(client, "a@example.com").get_json()["token"]
    token_b = register(client, "b@example.com").get_json()["token"]

    first = client.post("/api/challenges/1/complete", headers=auth(token_a))
    assert first.get_json()["points_awarded"] == 20

    again = client.post("/api/challenges/1/complete", headers=auth(token_a))
    assert again.get_json()["points_awarded"] == 0

    # User B has not completed it
    b_challenges = client.get("/api/challenges", headers=auth(token_b)).get_json()
    assert b_challenges["challenges"][0]["completed"] is False


def test_unknown_challenge_404(client):
    token = register(client).get_json()["token"]
    response = client.post("/api/challenges/999/complete", headers=auth(token))
    assert response.status_code == 404


# ---------- leaderboard and profile ----------

def test_leaderboard_ranks_by_points(client):
    token_a = register(client, "a@example.com", "Asha Rao").get_json()["token"]
    token_b = register(client, "b@example.com", "Ben Lee").get_json()["token"]

    client.post("/api/activities", headers=auth(token_b), json={
        "activity_type": "Recycling", "description": "paper"
    })

    board = client.get("/api/leaderboard", headers=auth(token_a)).get_json()["leaderboard"]

    assert board[0]["name"] == "Ben L."
    assert board[0]["is_you"] is False
    assert board[1]["is_you"] is True


def test_update_profile_name(client):
    token = register(client).get_json()["token"]

    client.put("/api/me", headers=auth(token), json={"full_name": "Asha R"})
    me = client.get("/api/me", headers=auth(token)).get_json()

    assert me["user"]["full_name"] == "Asha R"


# ---------- weekly rewards ----------

def test_weekly_reward_goes_to_top_user_of_finished_week(client):
    token_a = register(client, "a@example.com", "Asha Rao").get_json()["token"]
    token_b = register(client, "b@example.com", "Ben Lee").get_json()["token"]

    # Two old activities in the same finished week (Mon 5 Jan 2026): Asha leads
    connection = database.get_connection()
    connection.execute(
        "INSERT INTO activities (user_id, activity_type, description, points, created_at) "
        "VALUES (1, 'Recycling', 'x', 10, '2026-01-05 10:00:00')"
    )
    connection.execute(
        "INSERT INTO activities (user_id, activity_type, description, points, created_at) "
        "VALUES (2, 'Walking', 'x', 8, '2026-01-06 10:00:00')"
    )
    connection.commit()
    connection.close()

    asha = client.get("/api/rewards", headers=auth(token_a)).get_json()
    ben = client.get("/api/rewards", headers=auth(token_b)).get_json()

    assert asha["total_won"] == 1
    assert ben["total_won"] == 0
    assert asha["recent_winners"][0]["name"] == "Asha R."
    assert asha["recent_winners"][0]["is_you"] is True


def test_current_week_is_not_rewarded_yet(client):
    token = register(client).get_json()["token"]

    client.post("/api/activities", headers=auth(token), json={
        "activity_type": "Recycling", "description": "bottles"
    })

    rewards = client.get("/api/rewards", headers=auth(token)).get_json()
    weekly = client.get("/api/leaderboard/weekly", headers=auth(token)).get_json()

    assert rewards["total_won"] == 0
    assert weekly["leaderboard"][0]["weekly_points"] == 10
    assert weekly["leaderboard"][0]["is_you"] is True


def test_empty_week_has_no_winner(client):
    token = register(client).get_json()["token"]
    rewards = client.get("/api/rewards", headers=auth(token)).get_json()

    assert rewards["total_won"] == 0
    assert rewards["recent_winners"] == []


# ---------- daily cap and streak ----------

def insert_activity_days_ago(days_ago, user_id=1):
    when = app_module.utc_now() - app_module.timedelta(days=days_ago)
    connection = database.get_connection()
    connection.execute(
        "INSERT INTO activities (user_id, activity_type, description, points, created_at) "
        "VALUES (?, 'Walking', 'x', 8, ?)",
        (user_id, when.strftime(app_module.DB_TIME))
    )
    connection.commit()
    connection.close()


def test_daily_cap_per_activity_type(client):
    token = register(client).get_json()["token"]
    body = {"activity_type": "Recycling", "description": "bottles"}

    for _ in range(3):
        assert client.post("/api/activities", headers=auth(token), json=body).status_code == 201

    fourth = client.post("/api/activities", headers=auth(token), json=body)
    assert fourth.status_code == 400
    assert "Daily limit" in fourth.get_json()["error"]

    other = client.post("/api/activities", headers=auth(token), json={
        "activity_type": "Walking", "description": "2 km"
    })
    assert other.status_code == 201


def test_streak_counts_consecutive_days(client):
    token = register(client).get_json()["token"]

    for days_ago in (0, 1, 2):
        insert_activity_days_ago(days_ago)

    streak = client.get("/api/streak?tz=0", headers=auth(token)).get_json()

    assert streak["current_streak"] == 3
    assert streak["longest_streak"] == 3
    assert streak["logged_today"] is True
    assert streak["badges"][0]["earned"] is True
    assert streak["badges"][1]["earned"] is False


def test_streak_survives_until_end_of_today(client):
    token = register(client).get_json()["token"]

    for days_ago in (1, 2):
        insert_activity_days_ago(days_ago)

    streak = client.get("/api/streak?tz=0", headers=auth(token)).get_json()

    assert streak["current_streak"] == 2
    assert streak["logged_today"] is False


def test_streak_breaks_after_a_gap(client):
    token = register(client).get_json()["token"]

    insert_activity_days_ago(0)
    insert_activity_days_ago(3)

    streak = client.get("/api/streak?tz=0", headers=auth(token)).get_json()

    assert streak["current_streak"] == 1
    assert streak["longest_streak"] == 1


def test_streak_requires_login(client):
    assert client.get("/api/streak").status_code == 401