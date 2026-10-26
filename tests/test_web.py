from fastapi.testclient import TestClient
from oso.web.main import createApp


def makeClient(tmp_path):
    app = createApp(tmp_path / "data", tmp_path / "videos", password="test-password", startRecorder=False)
    return TestClient(app)


def test_auth_required(tmp_path):
    with makeClient(tmp_path) as client:
        assert client.get("/").status_code == 200
        assert "Sign in" in client.get("/").text
        assert client.get("/state").status_code == 401
        assert client.post("/action", json={"action":"profile.create","payload":{"name":"Other"}}).status_code == 401
        assert client.get("/videos/1/download").status_code == 401
        assert client.post("/login", data={"password":"bad"}).status_code == 401
        response = client.post("/login", data={"password":"test-password"}, follow_redirects=False)
        assert response.status_code == 303
        assert "httponly" in response.headers["set-cookie"].lower()
        assert client.get("/state").status_code == 200
        assert "Overview" in client.get("/").text or "navigation" in client.get("/").text


def test_web_forms_and_actions(tmp_path):
    with makeClient(tmp_path) as client:
        client.post("/login", data={"password":"test-password"})
        create = client.post("/action", json={"action":"profile.create","payload":{"name":"Project One"}})
        assert create.status_code == 200, create.text
        profileId = create.json()["result"]
        channel = client.post("/action", json={"action":"channel.create","payload":{
            "profile_id":profileId, "platform":"tiktok", "username":"@testuser"}})
        assert channel.status_code == 200, channel.text
        id = channel.json()["result"]
        assert client.post("/action", json={"action":"channel.update","payload":{"id":id,"auto_record":True}}).status_code == 200
        state = client.get("/state").json()
        assert len(state["profiles"]) == 2
        assert len(state["channels"]) == 1
        assert state["channels"][0]["auto_record"] == 1
        assert client.post("/action", json={"action":"settings.update","payload":{"language":"es"}}).status_code == 200
        assert client.get("/locale/es").json()["videos"] == "Vídeos"
        assert client.get("/locale/invalid").status_code == 404
        assert client.post("/action", json={"action":"unknown","payload":{}}).status_code == 400
        assert client.post("/import", data={"passphrase":"bad","confirm":"not-confirmed"},
                           files={"file":("bad.zip", b"bad")}).status_code == 400


def test_no_web_video_folder_override(tmp_path):
    with makeClient(tmp_path) as client:
        client.post("/login", data={"password":"test-password"})
        result = client.post("/action", json={"action":"profile.update","payload":{"id":1,"video_dir":"/tmp/evil"}})
        assert result.status_code == 400
