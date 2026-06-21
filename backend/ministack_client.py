import os
import json
import boto3
from botocore.config import Config
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()

ENDPOINT = os.getenv("MINISTACK_ENDPOINT", "http://localhost:4566")
ACCESS_KEY = os.getenv("MINISTACK_ACCESS_KEY", "test")
SECRET_KEY = os.getenv("MINISTACK_SECRET_KEY", "test")
REGION = os.getenv("MINISTACK_REGION", "us-east-1")

# Short timeouts so a dead MiniStack never blocks a request thread for long.
# max_attempts=1 disables boto3's built-in retry so FastAPI can handle errors fast.
_BOTO_CONFIG = Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 1})


@lru_cache(maxsize=3)  # one cached client per service string (s3, iam, ssm)
def get_client(service: str):
    return boto3.client(
        service,
        endpoint_url=ENDPOINT,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        region_name=REGION,
        config=_BOTO_CONFIG,
    )


def get_s3():
    return get_client("s3")


def get_iam():
    return get_client("iam")


def get_ssm():
    return get_client("ssm")


def provision_compute(user_id: int, subscription_id: int, vcpu: int) -> str:
    instance_id = f"i-{user_id:04d}{subscription_id:04d}"
    param_name  = f"/iaas/compute/user-{user_id}/{instance_id}"
    ssm = get_ssm()
    try:
        ssm.put_parameter(
            Name=param_name,
            Value=json.dumps({"instance_id": instance_id, "vcpu": vcpu, "status": "running"}),
            Type="String",
            Overwrite=True,
        )
    except Exception:
        # MiniStack may write the parameter but return a non-standard response.
        # Re-check existence before deciding whether to raise.
        try:
            ssm.get_parameter(Name=param_name)
        except Exception:
            raise
    return instance_id


def ensure_bucket(bucket_name: str) -> None:
    s3 = get_s3()
    try:
        s3.head_bucket(Bucket=bucket_name)
        return  # already exists
    except Exception:
        pass
    try:
        s3.create_bucket(Bucket=bucket_name)
    except Exception as e:
        # MiniStack may create the bucket but return a non-standard response;
        # confirm with a second head_bucket before deciding to raise.
        try:
            s3.head_bucket(Bucket=bucket_name)
        except Exception:
            raise e


def create_iam_user_credentials(username: str) -> dict:
    iam = get_iam()
    try:
        iam.create_user(UserName=username)
    except Exception:
        pass  # User already exists in MiniStack IAM
    response = iam.create_access_key(UserName=username)
    key = response["AccessKey"]
    return {
        "access_key": key["AccessKeyId"],
        "secret_key": key["SecretAccessKey"],
    }
