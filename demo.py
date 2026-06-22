"""End-to-end smoke demo of the MiniStack storage portal API.

Exercises the full happy path from SKILL.md §7 against a running backend:
register -> login -> me -> packages -> subscribe -> upload -> list -> download
-> delete -> credentials -> logs.

Usage:
    # 1. start MiniStack:           ministack
    # 2. start the API:             cd backend && python app.py
    # 3. run this demo:             python demo.py
"""
import io
import sys
import urllib.request
import urllib.error
import json
import uuid

BASE = "http://localhost:8000"


def call(method, path, token=None, json_body=None, files=None):
    url = BASE + path
    headers = {}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if files is not None:
        # minimal multipart/form-data encoder for a single file field named "file"
        boundary = uuid.uuid4().hex
        name, content = files
        body = io.BytesIO()
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'.encode())
        body.write(b"Content-Type: application/octet-stream\r\n\r\n")
        body.write(content)
        body.write(f"\r\n--{boundary}--\r\n".encode())
        data = body.getvalue()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            return resp.status, (json.loads(raw) if raw and ctype.startswith("application/json") else raw)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def step(label, status, body):
    shown = json.dumps(body) if isinstance(body, (dict, list)) else body
    print(f"  [{status}] {label}: {shown}")


def main():
    suffix = uuid.uuid4().hex[:8]
    email = f"demo-{suffix}@example.com"

    print("== register ==")
    status, body = call("POST", "/api/register",
                        json_body={"username": f"demo{suffix}", "email": email, "password": "password123"})
    step("register", status, body)
    if status != 201:
        print("Register failed — is the backend running?")
        sys.exit(1)
    print(f"  (one-time secret key shown: {body.get('secret_key')})")

    print("== login ==")
    status, body = call("POST", "/api/login", json_body={"email": email, "password": "password123"})
    step("login", status, {"is_admin": body.get("is_admin")})
    token = body["access_token"]

    print("== me ==")
    status, body = call("GET", "/api/me", token=token)
    step("me", status, {"bucket": body.get("bucket"), "quota_bytes": body["subscription"]["quota_bytes"]})

    print("== packages ==")
    status, pkgs = call("GET", "/api/packages", token=token)
    step("packages", status, [p["name"] for p in pkgs])

    print("== subscribe to Pro ==")
    pro = next(p for p in pkgs if p["name"] == "Pro")
    status, body = call("POST", "/api/subscriptions", token=token, json_body={"package_id": pro["id"]})
    step("subscribe", status, {"package": body.get("package", {}).get("name")})

    print("== upload ==")
    status, body = call("POST", "/api/objects", token=token, files=("demo.txt", b"hello from demo.py"))
    step("upload", status, body)

    print("== list objects ==")
    status, body = call("GET", "/api/objects", token=token)
    step("objects", status, [o["object_key"] for o in body])

    print("== presigned download URL ==")
    status, body = call("GET", "/api/objects/demo.txt?presigned=1", token=token)
    step("download", status, body)

    print("== delete ==")
    status, body = call("DELETE", "/api/objects/demo.txt", token=token)
    step("delete", status, body)

    print("== new credential pair ==")
    status, body = call("POST", "/api/credentials", token=token)
    step("credentials", status, {"access_key_id": body.get("access_key_id"), "secret_key": body.get("secret_key")})

    print("== logs ==")
    status, body = call("GET", "/api/logs", token=token)
    step("logs", status, [l["action"] for l in body])

    print("\nDemo complete.")


if __name__ == "__main__":
    main()
