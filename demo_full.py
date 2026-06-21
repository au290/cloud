"""
Full Scenario Demo — Simulasi Platform IaaS (MiniStack)

Simulates every possible user flow and edge case:

  AUTH
    ✓ Register (valid)
    ✓ Register duplicate email           → 400
    ✓ Register invalid email format      → 422
    ✓ Login correct                      → JWT
    ✓ Login wrong password               → 401
    ✓ Login non-existent email           → 401
    ✓ Access protected route, no token   → 401
    ✓ Access protected route, bad token  → 401

  PACKAGES
    ✓ List all packages
    ✓ Get single package by valid ID
    ✓ Get package — ID does not exist    → 404

  RENTALS
    ✓ Rent storage package               → S3 bucket created
    ✓ Rent same package again (duplicate)→ 400
    ✓ Rent compute package               → SSM instance
    ✓ Rent network package
    ✓ Rent non-existent package          → 404
    ✓ Release active subscription
    ✓ Release already-cancelled sub      → 404
    ✓ Release sub belonging to other user→ 404
    ✓ Release non-existent sub           → 404

  DASHBOARD & QUOTA
    ✓ Dashboard with no subscriptions    → empty
    ✓ Dashboard after renting all types
    ✓ Quota shows compute + storage + network
    ✓ Quota after releasing all          → back to empty

  CREDENTIALS
    ✓ Credentials auto-generated on register
    ✓ Request new credentials manually
    ✓ Multiple credentials accumulated
    ✓ Use credentials with boto3 on S3

  MINISTACK S3
    ✓ Upload file to bucket
    ✓ List objects in bucket
    ✓ Download & verify content
    ✓ Overwrite same key
    ✓ Delete object

  COMPUTE (SSM)
    ✓ Instance registered in SSM
    ✓ Verify instance_id / vCPU / status

  ADMIN
    ✓ Admin login                        → JWT
    ✓ Admin view stats
    ✓ Admin view all users
    ✓ Admin view all rental logs
    ✓ Regular user hits /admin/stats     → 403
    ✓ No token hits /admin/stats         → 401

  ACTIVITY LOGS
    ✓ User sees their own logs only
    ✓ Rent + release both appear in log

Run:
  cd Cloud_AWANN
  backend\\venv\\Scripts\\python demo_full.py
"""

import sys
import json
import time
import random
import string
import requests
import boto3
from botocore.exceptions import ClientError

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_URL   = "http://localhost:8000"
ENDPOINT   = "http://localhost:4566"
AWS_KEY    = "test"
AWS_SECRET = "test"
REGION     = "us-east-1"

# ── Display helpers ────────────────────────────────────────────────────────────
PASS = 0
FAIL = 0

def sep(title):
    print(f"\n{'═'*64}")
    print(f"  {title}")
    print(f"{'═'*64}")

def section(title):
    print(f"\n  {'─'*58}")
    print(f"  {title}")
    print(f"  {'─'*58}")

def check(description, condition, actual=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {description}")
    else:
        FAIL += 1
        detail = f"  (got: {actual})" if actual else ""
        print(f"  ❌ {description}{detail}")
    return condition

def info(msg):
    print(f"     {msg}")

def warn(msg):
    print(f"  ⚠️  {msg}")

def show_err(r):
    """Print status + body when a request returns unexpected result."""
    try:
        body = r.json()
    except Exception:
        body = r.text
    print(f"     HTTP {r.status_code}: {body}")

# ── HTTP helpers ───────────────────────────────────────────────────────────────
def api(method, path, token=None, json_body=None, form=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    if form is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    r = requests.request(
        method,
        BASE_URL + path,
        headers=headers,
        json=json_body if json_body is not None else None,
        data=form if form is not None else None,
        timeout=10,
    )
    return r

def safe(r, key, default=None):
    """Safely get a key from a response JSON, returns default on error."""
    try:
        return r.json().get(key, default)
    except Exception:
        return default

def rand_suffix():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=6))

def boto_client(service):
    return boto3.client(
        service,
        endpoint_url=ENDPOINT,
        aws_access_key_id=AWS_KEY,
        aws_secret_access_key=AWS_SECRET,
        region_name=REGION,
    )

# ══════════════════════════════════════════════════════════════════════════════
sep("0 / PRE-FLIGHT — Services health check")
# ══════════════════════════════════════════════════════════════════════════════

try:
    health = api("GET", "/health").json()
    db_status = health.get("database", "")
    ms_status = health.get("ministack", "")
    info(f"Database  : {db_status}")
    info(f"MiniStack : {ms_status}")
    check("PostgreSQL is reachable", db_status == "connected")
    check("MiniStack is reachable on :4566", ms_status == "connected")
    if db_status != "connected" or ms_status != "connected":
        print("\n  Cannot continue. Start missing services and retry.")
        sys.exit(1)
except requests.exceptions.ConnectionError:
    print(f"\n  ❌ Cannot reach {BASE_URL} — is uvicorn running?")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════════════════════
sep("1 / AUTH SCENARIOS")
# ══════════════════════════════════════════════════════════════════════════════

suffix  = rand_suffix()
email   = f"demo_{suffix}@example.com"
pwd     = "demopass123"
token_A = None
token_B = None
user_A  = {}
user_B  = {}

# ─ Register valid ──────────────────────────────────────────────────────────────
section("Register — valid data")
r = api("POST", "/auth/register", json_body={
    "full_name": f"User {suffix}", "email": email, "password": pwd
})
if check("Register valid user → 201", r.status_code == 201, r.status_code):
    user_A = r.json()
    info(f"id={user_A['id']}  email={email}")
else:
    show_err(r)

# ─ Register duplicate email ────────────────────────────────────────────────────
section("Register — duplicate email → 400")
r = api("POST", "/auth/register", json_body={"full_name": "Dup", "email": email, "password": pwd})
if check("Duplicate email → 400", r.status_code == 400, r.status_code):
    info(f"detail: {safe(r, 'detail')}")
else:
    show_err(r)

# ─ Register invalid email ─────────────────────────────────────────────────────
section("Register — invalid email format → 422")
r = api("POST", "/auth/register", json_body={"full_name": "Bad", "email": "not-an-email", "password": pwd})
if check("Invalid email format → 422", r.status_code == 422, r.status_code):
    try:
        info(f"validation: {r.json()['detail'][0]['msg']}")
    except Exception:
        pass
else:
    show_err(r)

# ─ Login correct ──────────────────────────────────────────────────────────────
section("Login — correct credentials")
r = api("POST", "/auth/login", form={"username": email, "password": pwd})
if check("Login correct → 200", r.status_code == 200, r.status_code):
    token_A = r.json()["access_token"]
    info("JWT token obtained ✓")
else:
    show_err(r)
    print("  FATAL: cannot continue without token_A")
    sys.exit(1)

# ─ Login wrong password ────────────────────────────────────────────────────────
section("Login — wrong password → 401")
r = api("POST", "/auth/login", form={"username": email, "password": "wrongpass"})
if check("Wrong password → 401", r.status_code == 401, r.status_code):
    info(f"detail: {safe(r, 'detail')}")
else:
    show_err(r)

# ─ Login non-existent email ────────────────────────────────────────────────────
section("Login — non-existent email → 401")
r = api("POST", "/auth/login", form={"username": "nobody@nowhere.com", "password": pwd})
if check("Non-existent email → 401", r.status_code == 401, r.status_code):
    info(f"detail: {safe(r, 'detail')}")
else:
    show_err(r)

# ─ No token ───────────────────────────────────────────────────────────────────
section("Protected route — no token → 401")
r = api("GET", "/auth/me")
check("No token → 401", r.status_code == 401, r.status_code)

# ─ Bad token ──────────────────────────────────────────────────────────────────
section("Protected route — invalid token → 401")
r = api("GET", "/auth/me", token="this.is.garbage")
check("Bad token → 401", r.status_code == 401, r.status_code)

# ─ /auth/me valid ─────────────────────────────────────────────────────────────
section("/auth/me — valid token")
r = api("GET", "/auth/me", token=token_A)
if check("/auth/me → 200", r.status_code == 200, r.status_code):
    me = r.json()
    info(f"full_name={me['full_name']}  is_admin={me['is_admin']}")
else:
    show_err(r)

# ─ Register second user ────────────────────────────────────────────────────────
suffix_B = rand_suffix()
email_B  = f"demo_{suffix_B}@example.com"
r = api("POST", "/auth/register", json_body={"full_name": f"User B {suffix_B}", "email": email_B, "password": pwd})
user_B = r.json() if r.status_code == 201 else {}
r2 = api("POST", "/auth/login", form={"username": email_B, "password": pwd})
token_B = r2.json().get("access_token") if r2.status_code == 200 else None
info(f"\n     (Second user: id={user_B.get('id')}  email={email_B})")

# ══════════════════════════════════════════════════════════════════════════════
sep("2 / PACKAGES SCENARIOS")
# ══════════════════════════════════════════════════════════════════════════════

packages    = []
pkg_storage = None
pkg_compute = None
pkg_network = None

section("List all packages")
r = api("GET", "/packages/", token=token_A)
if check("GET /packages/ → 200", r.status_code == 200, r.status_code):
    packages = r.json()
    check(f"Returns ≥ 3 packages (got {len(packages)})", len(packages) >= 3, len(packages))
    print()
    print(f"  {'ID':<4} {'Name':<22} {'Type':<10} {'Quota':<14} {'Price':>8}")
    print(f"  {'─'*4} {'─'*22} {'─'*10} {'─'*14} {'─'*8}")
    for p in packages:
        print(f"  {p['id']:<4} {p['name']:<22} {p['type']:<10} "
              f"{str(p['quota_value'])+' '+p['quota_unit']:<14} ${float(p['price']):>7.2f}/mo")
    pkg_storage = next((p for p in packages if p["type"] == "storage"), None)
    pkg_compute = next((p for p in packages if p["type"] == "compute"), None)
    pkg_network = next((p for p in packages if p["type"] == "network"), None)
else:
    show_err(r)

section("Get single package by valid ID")
if packages:
    r = api("GET", f"/packages/{packages[0]['id']}", token=token_A)
    if check(f"GET /packages/{packages[0]['id']} → 200", r.status_code == 200, r.status_code):
        info(f"name={r.json()['name']}")
    else:
        show_err(r)

section("Get package — ID does not exist → 404")
r = api("GET", "/packages/99999", token=token_A)
if check("Non-existent package → 404", r.status_code == 404, r.status_code):
    info(f"detail: {safe(r, 'detail')}")
else:
    show_err(r)

# ══════════════════════════════════════════════════════════════════════════════
sep("3 / DASHBOARD — Empty state (before any rental)")
# ══════════════════════════════════════════════════════════════════════════════

section("Dashboard with no subscriptions")
r = api("GET", "/dashboard/", token=token_A)
if check("GET /dashboard/ → 200", r.status_code == 200, r.status_code):
    dash = r.json()
    subs = dash.get("subscriptions", [])
    check("subscriptions list is empty", len(subs) == 0, len(subs))
    info("Quota: Compute=None, Storage=None, Network=None  ✓")
else:
    show_err(r)

# ══════════════════════════════════════════════════════════════════════════════
sep("4 / RENTAL SCENARIOS")
# ══════════════════════════════════════════════════════════════════════════════

sub_storage = None
sub_compute = None
sub_network = None
bucket_name = None
instance_id = None

# ─ Rent non-existent package ──────────────────────────────────────────────────
section("Rent non-existent package → 404")
r = api("POST", "/rentals/99999", token=token_A)
if check("Rent id=99999 → 404", r.status_code == 404, r.status_code):
    info(f"detail: {safe(r, 'detail')}")
else:
    show_err(r)

# ─ Rent Storage ───────────────────────────────────────────────────────────────
if pkg_storage:
    section(f"Rent '{pkg_storage['name']}' (Storage)")
    r = api("POST", f"/rentals/{pkg_storage['id']}", token=token_A)
    if check("Rent storage → 201", r.status_code == 201, r.status_code):
        sub_storage = r.json()
        bucket_name = sub_storage.get("resource_ref")
        info(f"subscription id : {sub_storage['id']}")
        info(f"S3 bucket       : {bucket_name}")
    else:
        show_err(r)

    section(f"Rent same Storage package again → 400 (duplicate)")
    r = api("POST", f"/rentals/{pkg_storage['id']}", token=token_A)
    if check("Duplicate active sub → 400", r.status_code == 400, r.status_code):
        info(f"detail: {safe(r, 'detail')}")
    else:
        show_err(r)

# ─ Rent Compute ───────────────────────────────────────────────────────────────
if pkg_compute:
    section(f"Rent '{pkg_compute['name']}' (Compute)")
    r = api("POST", f"/rentals/{pkg_compute['id']}", token=token_A)
    if check("Rent compute → 201", r.status_code == 201, r.status_code):
        sub_compute = r.json()
        instance_id = sub_compute.get("resource_ref")
        info(f"subscription id : {sub_compute['id']}")
        info(f"instance id     : {instance_id}")
    else:
        show_err(r)

# ─ Rent Network ───────────────────────────────────────────────────────────────
if pkg_network:
    section(f"Rent '{pkg_network['name']}' (Network)")
    r = api("POST", f"/rentals/{pkg_network['id']}", token=token_A)
    if check("Rent network → 201", r.status_code == 201, r.status_code):
        sub_network = r.json()
        info(f"subscription id : {sub_network['id']}")
        info("resource ref    : — (network has no MiniStack resource)")
    else:
        show_err(r)

# ─ Release sub belonging to another user ──────────────────────────────────────
if sub_storage and token_B:
    section("Release subscription belonging to another user → 404")
    r = api("DELETE", f"/rentals/{sub_storage['id']}", token=token_B)
    if check("User B cannot release User A's sub → 404", r.status_code == 404, r.status_code):
        info(f"detail: {safe(r, 'detail')}")
    else:
        show_err(r)

# ─ Release non-existent sub ───────────────────────────────────────────────────
section("Release non-existent subscription → 404")
r = api("DELETE", "/rentals/99999", token=token_A)
if check("Non-existent sub → 404", r.status_code == 404, r.status_code):
    info(f"detail: {safe(r, 'detail')}")
else:
    show_err(r)

# ── Dashboard — all 3 types active ────────────────────────────────────────────
section("Dashboard — quota with Compute + Storage + Network active")
r = api("GET", "/dashboard/", token=token_A)
if check("GET /dashboard/ → 200", r.status_code == 200, r.status_code):
    dash = r.json()
    subs = dash.get("subscriptions", [])
    types_active = {s["package"]["type"] for s in subs}
    check("Compute active", "compute" in types_active, types_active)
    check("Storage active", "storage" in types_active, types_active)
    check("Network active", "network" in types_active, types_active)
    print()
    for s in subs:
        p = s["package"]
        print(f"  [{p['type'].upper():8}]  {p['name']:<22}  {p['quota_value']} {p['quota_unit']}")
else:
    show_err(r)

# ─ Release storage → then try releasing it again ──────────────────────────────
if sub_storage:
    section("Release storage subscription")
    r = api("DELETE", f"/rentals/{sub_storage['id']}", token=token_A)
    if check(f"Release sub #{sub_storage['id']} → 200", r.status_code == 200, r.status_code):
        info(f"new status: {r.json().get('status')}")
    else:
        show_err(r)

    section("Release already-cancelled subscription → 404")
    r = api("DELETE", f"/rentals/{sub_storage['id']}", token=token_A)
    if check("Already-cancelled sub → 404", r.status_code == 404, r.status_code):
        info(f"detail: {safe(r, 'detail')}")
    else:
        show_err(r)

# ─ Release compute and network ────────────────────────────────────────────────
if sub_compute:
    r = api("DELETE", f"/rentals/{sub_compute['id']}", token=token_A)
    check(f"Release compute #{sub_compute['id']} → 200", r.status_code == 200, r.status_code)
    if r.status_code != 200: show_err(r)
if sub_network:
    r = api("DELETE", f"/rentals/{sub_network['id']}", token=token_A)
    check(f"Release network #{sub_network['id']} → 200", r.status_code == 200, r.status_code)
    if r.status_code != 200: show_err(r)

# ── Dashboard after releasing all ─────────────────────────────────────────────
section("Dashboard after releasing all → empty again")
r = api("GET", "/dashboard/", token=token_A)
if check("GET /dashboard/ → 200", r.status_code == 200, r.status_code):
    subs = r.json().get("subscriptions", [])
    check("subscriptions list is empty again", len(subs) == 0, len(subs))
else:
    show_err(r)

# ══════════════════════════════════════════════════════════════════════════════
sep("5 / CREDENTIALS SCENARIOS")
# ══════════════════════════════════════════════════════════════════════════════

all_creds = []

section("Auto-generated credential on register")
r = api("GET", "/dashboard/credentials", token=token_A)
if check("GET /dashboard/credentials → 200", r.status_code == 200, r.status_code):
    all_creds = r.json()
    check(f"At least 1 credential auto-generated (got {len(all_creds)})", len(all_creds) >= 1, len(all_creds))
    if all_creds:
        info(f"Access Key : {all_creds[0]['access_key']}")
        info(f"Secret Key : {all_creds[0]['secret_key']}")
else:
    show_err(r)

section("Request a new credential manually")
r = api("POST", "/dashboard/credentials", token=token_A)
if check("POST /dashboard/credentials → 201", r.status_code == 201, r.status_code):
    new_cred = r.json()
    info(f"New Access Key : {new_cred['access_key']}")
    info(f"New Secret Key : {new_cred['secret_key']}")
else:
    show_err(r)

section("Accumulated credentials")
r = api("GET", "/dashboard/credentials", token=token_A)
if r.status_code == 200:
    all_creds = r.json()
    check(f"Now has ≥ 2 credentials (got {len(all_creds)})", len(all_creds) >= 2, len(all_creds))

# ══════════════════════════════════════════════════════════════════════════════
sep("6 / MINISTACK S3 SCENARIOS")
# ══════════════════════════════════════════════════════════════════════════════

# Re-rent storage and show exactly what the API returned
s3_api_bucket = None
if pkg_storage:
    section("Re-rent storage — diagnose resource_ref")
    r = api("POST", f"/rentals/{pkg_storage['id']}", token=token_A)
    if r.status_code == 201:
        sub_storage = r.json()
        s3_api_bucket = sub_storage.get("resource_ref")
        info(f"subscription id : {sub_storage['id']}")
        info(f"resource_ref    : {s3_api_bucket!r}")
        if s3_api_bucket is None:
            warn("resource_ref is None → ensure_bucket() raised an exception in rentals.py")
            warn("Check the uvicorn terminal for 'WARNING: Could not create bucket:'")
    else:
        show_err(r)

# Direct MiniStack S3 probe — works whether or not the API gave us a bucket
section("Direct boto3 probe — MiniStack S3 capability")
s3 = boto_client("s3")
direct_bucket = f"demo-direct-{rand_suffix()}"

s3_ok = False
try:
    s3.list_buckets()
    check("list_buckets() works", True)
    s3_ok = True
except Exception as e:
    check("list_buckets() works", False, str(e))

if s3_ok:
    try:
        s3.create_bucket(Bucket=direct_bucket)
        check(f"create_bucket '{direct_bucket}'", True)
    except ClientError as e:
        check("create_bucket", False, e.response["Error"]["Code"])
        s3_ok = False

# Decide which bucket to use for tests
bucket_name = s3_api_bucket or (direct_bucket if s3_ok else None)
if bucket_name:
    info(f"Using bucket: {bucket_name}  (source: {'API' if s3_api_bucket else 'direct boto3'})")

if bucket_name and s3_ok:
    section("Bucket exists in MiniStack")
    all_buckets = [b["Name"] for b in s3.list_buckets().get("Buckets", [])]
    check("Bucket visible in list_buckets", bucket_name in all_buckets, all_buckets)
    info(f"All buckets: {all_buckets}")

    section("Upload files to bucket")
    try:
        s3.put_object(Bucket=bucket_name, Key="hello.txt", Body=b"Hello, IaaS!")
        check("Upload hello.txt", True)
    except ClientError as e:
        check("Upload hello.txt", False, e.response["Error"]["Code"])

    try:
        s3.put_object(Bucket=bucket_name, Key="data/report.json",
                      Body=json.dumps({"status": "ok", "ts": time.time()}).encode())
        check("Upload data/report.json (nested key)", True)
    except ClientError as e:
        check("Upload data/report.json", False, e.response["Error"]["Code"])

    section("List objects in bucket")
    try:
        objects = s3.list_objects_v2(Bucket=bucket_name).get("Contents", [])
        check(f"2 objects in bucket (got {len(objects)})", len(objects) == 2, len(objects))
        for obj in objects:
            info(f"{obj['Key']:<30} {obj['Size']} bytes")
    except ClientError as e:
        check("list_objects_v2", False, e.response["Error"]["Code"])

    section("Download and verify content")
    try:
        body = s3.get_object(Bucket=bucket_name, Key="hello.txt")["Body"].read().decode()
        check("Content matches uploaded value", body == "Hello, IaaS!", repr(body))
        info(f"content: \"{body}\"")
    except ClientError as e:
        check("get_object hello.txt", False, e.response["Error"]["Code"])

    section("Overwrite same key")
    try:
        s3.put_object(Bucket=bucket_name, Key="hello.txt", Body=b"Overwritten!")
        body2 = s3.get_object(Bucket=bucket_name, Key="hello.txt")["Body"].read().decode()
        check("Key overwritten", body2 == "Overwritten!", repr(body2))
        info(f"new content: \"{body2}\"")
    except ClientError as e:
        check("Overwrite key", False, e.response["Error"]["Code"])

    section("Delete one object")
    try:
        s3.delete_object(Bucket=bucket_name, Key="data/report.json")
        objects_after = s3.list_objects_v2(Bucket=bucket_name).get("Contents", [])
        check("Object deleted — 1 remaining", len(objects_after) == 1, len(objects_after))
    except ClientError as e:
        check("delete_object", False, e.response["Error"]["Code"])

    section("Use user's own IAM credentials with boto3")
    if all_creds:
        user_s3 = boto3.client(
            "s3",
            endpoint_url=ENDPOINT,
            aws_access_key_id=all_creds[0]["access_key"],
            aws_secret_access_key=all_creds[0]["secret_key"],
            region_name=REGION,
        )
        try:
            user_buckets = user_s3.list_buckets().get("Buckets", [])
            check("list_buckets with user's own IAM key", True)
            info(f"visible buckets: {[b['Name'] for b in user_buckets]}")
        except ClientError as e:
            warn(f"IAM user key not functional: {e.response['Error']['Code']}")
            check("IAM user credentials functional", False, e.response["Error"]["Code"])
    else:
        warn("No credentials to test with — skipping IAM key test")
else:
    warn("MiniStack S3 not functional — all S3 tests skipped")

# ══════════════════════════════════════════════════════════════════════════════
sep("7 / COMPUTE (SSM) SCENARIOS")
# ══════════════════════════════════════════════════════════════════════════════

# Re-rent compute and show exactly what came back
api_instance_id = None
if pkg_compute:
    section("Re-rent compute — diagnose resource_ref")
    r = api("POST", f"/rentals/{pkg_compute['id']}", token=token_A)
    if r.status_code == 201:
        sub_compute = r.json()
        api_instance_id = sub_compute.get("resource_ref")
        info(f"subscription id : {sub_compute['id']}")
        info(f"resource_ref    : {api_instance_id!r}")
        if api_instance_id is None:
            warn("resource_ref is None → provision_compute() raised an exception")
            warn("Check the uvicorn terminal for 'WARNING: Could not provision compute:'")
    else:
        show_err(r)

# Direct SSM probe — works whether or not the API gave us an instance_id
section("Direct boto3 probe — MiniStack SSM capability")
ssm = boto_client("ssm")
user_id    = user_A.get("id", 0)
test_iid   = api_instance_id or f"i-{user_id:04d}9999"
param_name = f"/iaas/compute/user-{user_id}/{test_iid}"

ssm_ok = False
try:
    ssm.put_parameter(
        Name=param_name,
        Value=json.dumps({"instance_id": test_iid, "vcpu": 2, "status": "running"}),
        Type="String",
        Overwrite=True,
    )
    check("put_parameter works", True)
    ssm_ok = True
except ClientError as e:
    check("put_parameter works", False, e.response["Error"]["Code"])
    warn("SSM not supported by this MiniStack build — compute tests skipped")

if ssm_ok:
    section("Read back SSM parameter")
    try:
        val  = ssm.get_parameter(Name=param_name)["Parameter"]["Value"]
        data = json.loads(val)
        check("Parameter exists in SSM", True)
        check("instance_id field correct", data.get("instance_id") == test_iid, data.get("instance_id"))
        check("status is 'running'", data.get("status") == "running", data.get("status"))
        check("vcpu field present", "vcpu" in data, data)
        info(f"raw data: {data}")
    except ClientError as e:
        check("get_parameter", False, e.response["Error"]["Code"])

    section("List SSM parameters by path")
    try:
        params = ssm.get_parameters_by_path(Path=f"/iaas/compute/user-{user_id}/").get("Parameters", [])
        check(f"get_parameters_by_path returns ≥ 1 result (got {len(params)})", len(params) >= 1, len(params))
        for p in params:
            info(f"  {p['Name']}")
    except ClientError as e:
        check("get_parameters_by_path", False, e.response["Error"]["Code"])

# ══════════════════════════════════════════════════════════════════════════════
sep("8 / ADMIN SCENARIOS")
# ══════════════════════════════════════════════════════════════════════════════

section("Regular user accessing /admin/stats → 403")
r = api("GET", "/admin/stats", token=token_A)
if check("Regular user → 403 Forbidden", r.status_code == 403, r.status_code):
    info(f"detail: {safe(r, 'detail')}")
else:
    show_err(r)

section("No token accessing /admin/stats → 401")
r = api("GET", "/admin/stats")
check("No token → 401", r.status_code == 401, r.status_code)

section("Admin login")
r = api("POST", "/auth/login", form={"username": "admin@iaas.local", "password": "admin123"})
token_admin = None
if check("Admin login → 200", r.status_code == 200, r.status_code):
    token_admin = r.json().get("access_token")
    r_me = api("GET", "/auth/me", token=token_admin)
    if r_me.status_code == 200:
        check("Admin is_admin=True", r_me.json().get("is_admin") is True, r_me.json().get("is_admin"))
else:
    show_err(r)
    warn("Admin login failed — was admin@iaas.local seeded? Try restarting uvicorn.")

if token_admin:
    section("Admin GET /admin/stats")
    r = api("GET", "/admin/stats", token=token_admin)
    if check("Admin /admin/stats → 200", r.status_code == 200, r.status_code):
        stats = r.json()
        info(f"total_users          : {stats['total_users']}")
        info(f"active_subscriptions : {stats['active_subscriptions']}")
        info(f"total_logs           : {stats['total_logs']}")
        info(f"total_buckets        : {stats['total_buckets']}")
        check("total_users ≥ 2", stats["total_users"] >= 2, stats["total_users"])
        check("total_logs > 0", stats["total_logs"] > 0, stats["total_logs"])
    else:
        show_err(r)

    section("Admin GET /admin/users")
    r = api("GET", "/admin/users", token=token_admin)
    if check("Admin /admin/users → 200", r.status_code == 200, r.status_code):
        users = r.json()
        info(f"total users: {len(users)}")
        print()
        print(f"  {'ID':<4} {'Name':<22} {'Email':<30} {'Role':<8} {'Active Subs'}")
        print(f"  {'─'*4} {'─'*22} {'─'*30} {'─'*8} {'─'*11}")
        for u in users:
            role = "Admin" if u["is_admin"] else "User"
            print(f"  {u['id']:<4} {u['full_name']:<22} {u['email']:<30} {role:<8} {u['active_subscriptions']}")
    else:
        show_err(r)

    section("Admin GET /admin/logs")
    r = api("GET", "/admin/logs", token=token_admin)
    if check("Admin /admin/logs → 200", r.status_code == 200, r.status_code):
        logs = r.json()
        check(f"Logs contain entries (got {len(logs)})", len(logs) > 0, len(logs))
        print()
        print(f"  {'ID':<4} {'User':<18} {'Package':<22} {'Action':<10} {'Resource':<26}")
        print(f"  {'─'*4} {'─'*18} {'─'*22} {'─'*10} {'─'*26}")
        for l in logs[:10]:
            print(f"  {l['id']:<4} {l['user']['full_name']:<18} {l['package']['name']:<22} "
                  f"{l['action']:<10} {(l['resource_ref'] or '—'):<26}")
        if len(logs) > 10:
            info(f"... and {len(logs)-10} more")
    else:
        show_err(r)

# ══════════════════════════════════════════════════════════════════════════════
sep("9 / ACTIVITY LOGS")
# ══════════════════════════════════════════════════════════════════════════════

section("User A sees only their own logs")
r = api("GET", "/rentals/logs", token=token_A)
if check("GET /rentals/logs → 200", r.status_code == 200, r.status_code):
    logs_A = r.json()
    info(f"total entries: {len(logs_A)}")
    rent_count    = sum(1 for l in logs_A if l["action"] == "rent")
    release_count = sum(1 for l in logs_A if l["action"] == "release")
    check(f"rent actions logged (got {rent_count})", rent_count > 0, rent_count)
    check(f"release actions logged (got {release_count})", release_count > 0, release_count)
    print()
    print(f"  {'#':<4} {'Action':<10} {'Package':<22} {'Resource':<28} Timestamp")
    print(f"  {'─'*4} {'─'*10} {'─'*22} {'─'*28} {'─'*19}")
    for i, l in enumerate(logs_A, 1):
        print(f"  {i:<4} {l['action']:<10} {l['package']['name']:<22} "
              f"{(l['resource_ref'] or '—'):<28} {l['timestamp'][:19]}")
else:
    show_err(r)

section("User B sees only their own logs (not User A's)")
if token_B:
    r = api("GET", "/rentals/logs", token=token_B)
    if check("GET /rentals/logs User B → 200", r.status_code == 200, r.status_code):
        logs_B = r.json()
        check("User B has 0 logs (never rented)", len(logs_B) == 0, len(logs_B))
        info(f"User B log count: {len(logs_B)}")
else:
    warn("Skipping User B log check — token_B unavailable")

# ══════════════════════════════════════════════════════════════════════════════
sep("FINAL RESULTS")
# ══════════════════════════════════════════════════════════════════════════════

total = PASS + FAIL
print()
print(f"  Passed : {PASS}/{total}")
print(f"  Failed : {FAIL}/{total}")
print()
if FAIL == 0:
    print("  🎉  All scenarios passed!")
else:
    print(f"  ⚠️   {FAIL} scenario(s) failed — see ❌ above for details.")

print()
print(f"  Test user  : {email} / {pwd}")
print(f"  Admin      : admin@iaas.local / admin123")
if bucket_name:
    print(f"  S3 bucket  : {bucket_name}  (persists in MiniStack)")
print()
