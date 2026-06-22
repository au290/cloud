"""Thin boto3 wrapper around MiniStack (the Docker-free AWS emulator on :4566).

The backend uses ADMIN credentials here to provision buckets and mint per-user
IAM keys. End users get their own keys for the direct-access (CLI/SDK/rclone) layer.
"""
import os
import secrets
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError
from dotenv import load_dotenv

load_dotenv()

ENDPOINT = os.getenv("MINISTACK_ENDPOINT", "http://localhost:4566")
# Backend's own admin credentials for provisioning (skill §7 wiring notes).
ADMIN_KEY = os.getenv("MINISTACK_ADMIN_KEY", os.getenv("MINISTACK_ACCESS_KEY", "admin"))
ADMIN_SECRET = os.getenv("MINISTACK_ADMIN_SECRET", os.getenv("MINISTACK_SECRET_KEY", "admin"))
REGION = os.getenv("AWS_DEFAULT_REGION", os.getenv("MINISTACK_REGION", "us-east-1"))

# Short timeouts + no retries so a dead MiniStack fails fast instead of hanging a request.
_BOTO_CONFIG = Config(connect_timeout=3, read_timeout=10, retries={"max_attempts": 1})


@lru_cache(maxsize=2)
def _client(service: str):
    return boto3.client(
        service,
        endpoint_url=ENDPOINT,
        aws_access_key_id=ADMIN_KEY,
        aws_secret_access_key=ADMIN_SECRET,
        region_name=REGION,
        config=_BOTO_CONFIG,
    )


def get_s3():
    return _client("s3")


def get_iam():
    return _client("iam")


# --- Buckets ----------------------------------------------------------------
def create_bucket(name: str, region: str = REGION) -> None:
    """Idempotently create a bucket. Tolerates MiniStack's non-standard responses."""
    s3 = get_s3()
    try:
        s3.head_bucket(Bucket=name)
        return  # already exists
    except ClientError:
        pass
    try:
        if region and region != "us-east-1":
            s3.create_bucket(
                Bucket=name,
                CreateBucketConfiguration={"LocationConstraint": region},
            )
        else:
            s3.create_bucket(Bucket=name)
    except ClientError as e:
        # MiniStack may create the bucket but return an odd response; confirm before raising.
        try:
            s3.head_bucket(Bucket=name)
        except ClientError:
            raise e


def list_objects(bucket: str) -> list[dict]:
    s3 = get_s3()
    out: list[dict] = []
    token = None
    while True:
        kwargs = {"Bucket": bucket}
        if token:
            kwargs["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kwargs)
        for obj in resp.get("Contents", []):
            out.append({"key": obj["Key"], "size": obj.get("Size", 0)})
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
    return out


def total_size(bucket: str) -> int:
    return sum(o["size"] for o in list_objects(bucket))


def put_object(bucket: str, key: str, body: bytes, content_type: str | None = None) -> None:
    kwargs = {"Bucket": bucket, "Key": key, "Body": body}
    if content_type:
        kwargs["ContentType"] = content_type
    get_s3().put_object(**kwargs)


def upload_fileobj(bucket: str, key: str, fileobj, content_type: str | None = None) -> None:
    """Stream a file-like object to S3 using boto3's managed multipart upload.

    Reads the source in chunks instead of buffering the whole file in memory, and
    parallelizes parts for large objects — much faster + lighter than put_object for
    big uploads.
    """
    extra = {"ContentType": content_type} if content_type else None
    get_s3().upload_fileobj(fileobj, bucket, key, ExtraArgs=extra)


def get_object(bucket: str, key: str) -> tuple[bytes, str | None]:
    resp = get_s3().get_object(Bucket=bucket, Key=key)
    return resp["Body"].read(), resp.get("ContentType")


def delete_object(bucket: str, key: str) -> None:
    get_s3().delete_object(Bucket=bucket, Key=key)


def presigned_url(bucket: str, key: str, expires: int = 300) -> str:
    return get_s3().generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires
    )


# --- Credentials ------------------------------------------------------------
def create_user_credentials(username: str) -> dict:
    """Mint an Access/Secret key pair for the user.

    Tries MiniStack IAM first; if its create_access_key is only a stub (or IAM is
    unreachable) we fall back to locally generated AWS-style keys (skill §5).
    """
    try:
        iam = get_iam()
        try:
            iam.create_user(UserName=username)
        except ClientError:
            pass  # already exists
        resp = iam.create_access_key(UserName=username)
        key = resp["AccessKey"]
        if key.get("AccessKeyId") and key.get("SecretAccessKey"):
            return {"access_key": key["AccessKeyId"], "secret_key": key["SecretAccessKey"]}
    except (ClientError, EndpointConnectionError, KeyError, Exception):
        pass
    return _generate_local_keys()


def _generate_local_keys() -> dict:
    return {
        "access_key": "AKIA" + secrets.token_hex(8).upper(),
        "secret_key": secrets.token_urlsafe(30),
    }


def list_buckets() -> list[str]:
    return [b["Name"] for b in get_s3().list_buckets().get("Buckets", [])]
