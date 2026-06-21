"""
Demo script — Simulasi Platform IaaS (MiniStack)

What this script does:
  1. Register a test user
  2. Login and get JWT
  3. List available packages
  4. Rent a Storage package  → MiniStack creates a real S3 bucket
  5. Rent a Compute package  → MiniStack registers SSM parameter
  6. Show dashboard quota
  7. USE the S3 bucket (upload / list / download / delete)
  8. Check the compute instance via SSM
  9. Show IAM credentials
 10. Release both subscriptions
 11. Show activity logs

Run:
  cd Cloud_AWANN
  backend\\venv\\Scripts\\python demo.py
"""

import sys
import json
import time
import random
import string
import requests
import boto3
from botocore.exceptions import ClientError

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL  = "http://localhost:8000"
ENDPOINT  = "http://localhost:4566"
AWS_KEY   = "test"
AWS_SECRET= "test"
REGION    = "us-east-1"

# ── Helpers ───────────────────────────────────────────────────────────────────
def sep(title=""):
    line = "─" * 60
    if title:
        print(f"\n{line}")
        print(f"  {title}")
        print(line)
    else:
        print(line)

def ok(msg):  print(f"  ✅  {msg}")
def err(msg): print(f"  ❌  {msg}"); sys.exit(1)
def info(msg):print(f"  ℹ️   {msg}")

def api(method, path, token=None, **kwargs):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.request(method, BASE_URL + path, headers=headers, **kwargs)
    return r

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

# ── 0. Pre-flight ─────────────────────────────────────────────────────────────
sep("0 / Pre-flight check")

try:
    health = requests.get(BASE_URL + "/health", timeout=5).json()
    db_ok  = health.get("database") == "connected"
    ms_ok  = health.get("ministack") == "connected"
    info(f"Database  : {health['database']}")
    info(f"MiniStack : {health['ministack']}")
    if not db_ok:
        err("PostgreSQL is not reachable. Start it first.")
    if not ms_ok:
        err("MiniStack is not reachable on :4566. Run: ministack")
    ok("Both services up")
except requests.exceptions.ConnectionError:
    err("Cannot reach http://localhost:8000 — is uvicorn running?")

# ── 1. Register ───────────────────────────────────────────────────────────────
sep("1 / Register a test user")

suffix = rand_suffix()
email  = f"demo_{suffix}@example.com"
pwd    = "demopass123"

r = api("POST", "/auth/register", json={
    "full_name": f"Demo User {suffix}",
    "email": email,
    "password": pwd,
})
if r.status_code == 201:
    user = r.json()
    ok(f"Registered: {user['full_name']}  (id={user['id']})")
    ok(f"Email     : {email}")
else:
    err(f"Register failed: {r.text}")

# ── 2. Login ──────────────────────────────────────────────────────────────────
sep("2 / Login")

r = api("POST", "/auth/login",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"username": email, "password": pwd})
if r.status_code == 200:
    token = r.json()["access_token"]
    ok("JWT token obtained")
else:
    err(f"Login failed: {r.text}")

# ── 3. List packages ──────────────────────────────────────────────────────────
sep("3 / Available packages")

packages = api("GET", "/packages/", token=token).json()
print()
print(f"  {'#':<4} {'Name':<22} {'Type':<10} {'Quota':<14} {'Price':>8}")
print(f"  {'─'*4} {'─'*22} {'─'*10} {'─'*14} {'─'*8}")
for p in packages:
    print(f"  {p['id']:<4} {p['name']:<22} {p['type']:<10} "
          f"{str(p['quota_value'])+' '+p['quota_unit']:<14} ${p['price']:>7.2f}/mo")

storage_pkg = next(p for p in packages if p["type"] == "storage")
compute_pkg = next(p for p in packages if p["type"] == "compute")

# ── 4. Rent Storage ───────────────────────────────────────────────────────────
sep(f"4 / Rent '{storage_pkg['name']}' (Storage)")

r = api("POST", f"/rentals/{storage_pkg['id']}", token=token)
if r.status_code == 201:
    sub_storage = r.json()
    bucket_name = sub_storage.get("resource_ref") or f"user-{user['id']}-storage-{sub_storage['id']}"
    ok(f"Subscription id : {sub_storage['id']}")
    ok(f"S3 bucket       : {bucket_name}")
else:
    err(f"Rent storage failed: {r.text}")

# ── 5. Rent Compute ───────────────────────────────────────────────────────────
sep(f"5 / Rent '{compute_pkg['name']}' (Compute)")

r = api("POST", f"/rentals/{compute_pkg['id']}", token=token)
if r.status_code == 201:
    sub_compute = r.json()
    instance_id = sub_compute.get("resource_ref") or "—"
    ok(f"Subscription id : {sub_compute['id']}")
    ok(f"Instance id     : {instance_id}")
else:
    err(f"Rent compute failed: {r.text}")

# ── 6. Dashboard quota ────────────────────────────────────────────────────────
sep("6 / Dashboard quota")

dash = api("GET", "/dashboard/", token=token).json()
print()
for s in dash["subscriptions"]:
    p = s["package"]
    print(f"  [{p['type'].upper():8}]  {p['name']:<22}  "
          f"{p['quota_value']} {p['quota_unit']:<6}  status={s['status']}")

# ── 7. USE the S3 bucket ──────────────────────────────────────────────────────
sep(f"7 / Use S3 bucket '{bucket_name}'")

s3 = boto_client("s3")

# List all buckets
buckets = [b["Name"] for b in s3.list_buckets().get("Buckets", [])]
ok(f"All MiniStack buckets: {buckets}")

# Upload
print()
info("Uploading hello.txt …")
s3.put_object(Bucket=bucket_name, Key="hello.txt", Body=b"Hello from IaaS Portal demo!")
ok("Uploaded  hello.txt")

info("Uploading data.json …")
payload = json.dumps({"user": user["full_name"], "plan": storage_pkg["name"], "timestamp": time.time()})
s3.put_object(Bucket=bucket_name, Key="data.json", Body=payload.encode())
ok("Uploaded  data.json")

# List bucket contents
print()
info("Listing bucket contents:")
objects = s3.list_objects_v2(Bucket=bucket_name).get("Contents", [])
for obj in objects:
    print(f"    {obj['Key']:<20}  {obj['Size']} bytes")

# Download and verify
print()
info("Downloading hello.txt …")
body = s3.get_object(Bucket=bucket_name, Key="hello.txt")["Body"].read().decode()
ok(f"Content   : \"{body}\"")

# ── 8. Check compute instance (SSM) ──────────────────────────────────────────
sep(f"8 / Check compute instance in SSM")

if instance_id != "—":
    ssm = boto_client("ssm")
    try:
        param_name = f"/iaas/compute/user-{user['id']}/{instance_id}"
        info(f"SSM parameter: {param_name}")
        val = ssm.get_parameter(Name=param_name)["Parameter"]["Value"]
        data = json.loads(val)
        ok(f"Instance ID : {data['instance_id']}")
        ok(f"vCPU        : {data['vcpu']}")
        ok(f"Status      : {data['status']}")
    except ClientError as e:
        info(f"SSM not available ({e.response['Error']['Code']})")
else:
    info("No instance_id returned (MiniStack SSM may not be supported)")

# ── 9. Credentials ────────────────────────────────────────────────────────────
sep("9 / IAM credentials")

creds = api("GET", "/dashboard/credentials", token=token).json()
if creds:
    for i, c in enumerate(creds, 1):
        print(f"\n  Credential #{i}")
        print(f"    Access Key : {c['access_key']}")
        print(f"    Secret Key : {c['secret_key']}")
        print(f"    Created    : {c['created_at']}")
    ok(f"{len(creds)} credential(s) found")
else:
    info("No credentials found (MiniStack IAM may not be supported)")

# ── 10. Release subscriptions ─────────────────────────────────────────────────
sep("10 / Release subscriptions")

for sub_id, label in [(sub_storage["id"], "Storage"), (sub_compute["id"], "Compute")]:
    r = api("DELETE", f"/rentals/{sub_id}", token=token)
    if r.status_code == 200:
        ok(f"{label} subscription #{sub_id} released")
    else:
        info(f"Release {label} returned {r.status_code}: {r.text}")

# ── 11. Activity logs ─────────────────────────────────────────────────────────
sep("11 / Activity logs")

logs = api("GET", "/rentals/logs", token=token).json()
print()
print(f"  {'#':<4} {'Action':<10} {'Package':<22} {'Resource':<28} Timestamp")
print(f"  {'─'*4} {'─'*10} {'─'*22} {'─'*28} {'─'*20}")
for i, l in enumerate(logs, 1):
    print(f"  {i:<4} {l['action']:<10} {l['package']['name']:<22} "
          f"{(l['resource_ref'] or '—'):<28} {l['timestamp'][:19]}")

# ── Done ──────────────────────────────────────────────────────────────────────
sep()
print()
print("  Demo complete!")
print(f"  User  : {email}")
print(f"  Pass  : {pwd}")
print(f"  Bucket: {bucket_name}  (still exists in MiniStack)")
print()
