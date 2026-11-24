"""Stockage objet Cloudflare R2 (API S3) — bucket privé, URL signées courtes."""
from functools import lru_cache

from .config import get_settings
from .security import assert_key_in_org, storage_key
from .tenancy import TenantContext


@lru_cache
def _s3():
    import boto3  # import différé : inutile en tests

    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.R2_ENDPOINT,
        aws_access_key_id=s.R2_ACCESS_KEY_ID,
        aws_secret_access_key=s.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def presign_upload(ctx: TenantContext, module: str, filename: str, content_type: str, expires: int = 300) -> dict:
    key = storage_key(ctx.org_id, module, filename)
    url = _s3().generate_presigned_url(
        "put_object",
        Params={"Bucket": get_settings().R2_BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=expires,
    )
    return {"key": key, "upload_url": url}


def presign_download(ctx: TenantContext, key: str, expires: int = 120) -> str:
    assert_key_in_org(key, ctx.org_id)
    return _s3().generate_presigned_url(
        "get_object", Params={"Bucket": get_settings().R2_BUCKET, "Key": key}, ExpiresIn=expires
    )
