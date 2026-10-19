from fastapi.testclient import TestClient

from shopdesk.api import create_app


def test_api_end_to_end_and_operator_auth(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/api/knowledge").status_code == 401
        admin = {"X-Admin-Token": "test-admin"}
        session = client.post("/api/sessions").json()["id"]
        payload = {
            "session_id": session,
            "message": "J01 平安扣尺寸和重量？",
            "request_id": "api-test",
        }
        result = client.post("/api/chat", json=payload)
        assert result.status_code == 200 and "28 mm" in result.json()["answer"]
        other = client.get("/api/sessions/" + session, headers={"X-Customer-ID": "other"})
        assert other.status_code == 404
        with client.stream(
            "POST",
            "/api/chat/stream",
            json={**payload, "request_id": "stream", "message": "那它能退吗？"},
        ) as response:
            text = "".join(response.iter_text())
            assert "event: stage" in text and "event: answer" in text and "event: done" in text
        doc = client.post(
            "/api/knowledge",
            json={
                "title": "界面测试规则",
                "kind": "faq",
                "content": "Q：测试问题？\nA：测试问题由测试规则明确回答。",
            },
            headers=admin,
        ).json()["id"]
        assert client.delete("/api/knowledge/" + doc, headers=admin).status_code == 200
        assert (
            client.post(
                "/api/feedback",
                json={
                    "session_id": session,
                    "request_id": "api-test",
                    "rating": -1,
                    "note": "待改进",
                },
            ).status_code
            == 200
        )
        assert len(client.get("/api/metrics", headers=admin).json()["bad_cases"]) == 1
