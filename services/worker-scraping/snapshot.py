"""Snapshot delle evidenze su object store (MinIO in locale, Azure Blob in prod).

Salva uno snapshot **WARC** (riproducibilità probatoria) e l'HTML grezzo,
con **hash SHA-256** e provenance. Funzioni sincrone (boto3): vanno invocate
da attività async via `asyncio.to_thread`.
"""
from __future__ import annotations

import hashlib
import io
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

import boto3
from botocore.client import Config
from warcio.statusandheaders import StatusAndHeaders
from warcio.warcwriter import WARCWriter

ENDPOINT = os.getenv("OBJECT_STORE_ENDPOINT", "http://minio:9000")
ACCESS = os.getenv("OBJECT_STORE_ACCESS_KEY", "minio")
SECRET = os.getenv("OBJECT_STORE_SECRET_KEY", "minio12345")
BUCKET = os.getenv("OBJECT_STORE_BUCKET", "adverse-media-snapshots")


def _client():
    return boto3.client(
        "s3", endpoint_url=ENDPOINT, aws_access_key_id=ACCESS,
        aws_secret_access_key=SECRET, region_name="us-east-1",
        config=Config(signature_version="s3v4"),
    )


def _ensure_bucket(s3) -> None:
    try:
        s3.head_bucket(Bucket=BUCKET)
    except Exception:
        try:
            s3.create_bucket(Bucket=BUCKET)
        except Exception:
            pass


def store(url: str, final_url: str, status: int, content_type: str,
          headers: dict, body: bytes) -> dict:
    body = body or b""
    sha = hashlib.sha256(body).hexdigest()
    host = urlparse(final_url or url).netloc or "unknown"
    now = datetime.now(timezone.utc)
    prefix = f"{host}/{now:%Y/%m/%d}/{sha}"
    raw_key, warc_key = f"{prefix}.html", f"{prefix}.warc.gz"

    # WARC (record 'response')
    buf = io.BytesIO()
    writer = WARCWriter(buf, gzip=True)
    http_headers = StatusAndHeaders(str(status or 200), list((headers or {}).items()), protocol="HTTP/1.1")
    record = writer.create_warc_record(
        final_url or url, "response", payload=io.BytesIO(body), http_headers=http_headers
    )
    writer.write_record(record)

    s3 = _client()
    _ensure_bucket(s3)
    s3.put_object(Bucket=BUCKET, Key=raw_key, Body=body, ContentType=content_type or "text/html")
    s3.put_object(Bucket=BUCKET, Key=warc_key, Body=buf.getvalue(), ContentType="application/warc")

    return {
        "bucket": BUCKET, "raw_key": raw_key, "warc_key": warc_key,
        "content_hash": f"sha256:{sha}", "fetch_ts": now.isoformat(),
    }


def load_html(bucket: str, key: str) -> str:
    s3 = _client()
    data = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return data.decode("utf-8", errors="replace")
