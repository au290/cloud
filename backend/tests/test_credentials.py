def test_list_credentials_never_returns_secret(client, user_headers):
    res = client.get("/api/credentials", headers=user_headers)
    assert res.status_code == 200
    creds = res.get_json()
    assert len(creds) >= 1  # one minted at registration
    for c in creds:
        assert "secret_key" not in c
        assert c["access_key_id"]


def test_new_credential_returns_secret_once(client, user_headers):
    res = client.post("/api/credentials", headers=user_headers)
    assert res.status_code == 201
    body = res.get_json()
    assert body["secret_key"]
    # Listing again must not expose it.
    listed = client.get("/api/credentials", headers=user_headers).get_json()
    match = next(c for c in listed if c["access_key_id"] == body["access_key_id"])
    assert "secret_key" not in match


def test_secret_is_encrypted_at_rest(client, user_headers):
    res = client.post("/api/credentials", headers=user_headers)
    plaintext = res.get_json()["secret_key"]
    access_key = res.get_json()["access_key_id"]

    from database import db_session
    from models import Credential
    from security import decrypt_secret
    cred = db_session.query(Credential).filter(Credential.access_key_id == access_key).first()
    # Stored value differs from plaintext but decrypts back to it.
    assert cred.secret_key_encrypted != plaintext
    assert decrypt_secret(cred.secret_key_encrypted) == plaintext
