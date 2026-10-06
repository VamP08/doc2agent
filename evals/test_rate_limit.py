"""A public demo shares one model budget, so each visitor gets a fair slice of it."""

from fastapi.testclient import TestClient

from app import main


def test_questions_past_the_limit_get_429_before_any_work():
    main.QUESTIONS.clear()
    client = TestClient(main.app)
    body = {"session_id": "no-such-session", "message": "hi"}
    headers = {"x-forwarded-for": "203.0.113.7"}
    for _ in range(main.QUESTION_LIMIT):
        assert client.post("/api/chat", json=body, headers=headers).status_code == 404
    over = client.post("/api/chat/stream", json=body, headers=headers)
    assert over.status_code == 429 and "minute" in over.json()["detail"]
    # another visitor is unaffected
    assert (
        client.post("/api/chat", json=body, headers={"x-forwarded-for": "198.51.100.2"}).status_code
        == 404
    )
    main.QUESTIONS.clear()
