from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import google.auth
from google.auth.transport.requests import Request
from google.cloud import storage

from app.config import Settings, get_settings

SOURCE_PREFIX_MAP = {
    "google_takeout_zip": "uploads/google_takeout/zips",
    "google_takeout_folder": "uploads/google_takeout/folders",
    "reacthealth_pdf": "uploads/reacthealth_pdf",
    "transcend_micro": "uploads/transcend_micro",
    "zenplanner": "uploads/zenplanner",
}


def sanitize_relative_path(raw_path: str) -> str:
    """Prevent path traversal while preserving Takeout folder hierarchy."""
    parts = [
        re.sub(r"[^A-Za-z0-9._ -]", "_", p).strip()
        for p in raw_path.replace("\\", "/").split("/")
        if p not in ("", ".", "..")
    ]
    return "/".join(parts) or "upload.bin"


def build_gcs_object_path(
    source_type: str,
    relative_path: str,
    upload_batch_id: str,
) -> str:
    """Construct clean GCS object path under uploads/<source>/..."""
    base_prefix = SOURCE_PREFIX_MAP.get(source_type)
    if not base_prefix:
        raise ValueError(f"Unsupported upload source_type: {source_type!r}")
    clean_rel = sanitize_relative_path(relative_path)
    return f"{base_prefix}/{upload_batch_id}/{clean_rel}"


def generate_direct_upload_url(
    object_path: str,
    content_type: str = "application/octet-stream",
    resumable: bool = True,
    origin: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> Dict[str, str]:
    """
    Generate a Direct-to-GCS upload URL so large files (>400 MB Takeout .zips)
    bypass Cloud Run's 32 MiB HTTP body limit.

    Uses IAM signBlob credentials on Cloud Run (zero JSON key files) and supports
    resumable upload sessions when resumable=True.
    """
    cfg = settings or get_settings()
    client = storage.Client(project=cfg.gcp_project_id)
    bucket = client.bucket(cfg.gcs_raw_bucket)
    blob = bucket.blob(object_path)

    credentials, _ = google.auth.default()
    if not credentials.valid:
        credentials.refresh(Request())

    sa_email = cfg.web_service_account_email or getattr(
        credentials, "service_account_email", None
    )

    # Attempt V4 Signed URL via IAM signBlob when service account email is available
    if sa_email and sa_email != "default" and hasattr(credentials, "token"):
        if resumable:
            signed_url = blob.generate_signed_url(
                version="v4",
                expiration=timedelta(minutes=60),
                method="POST",
                headers={"x-goog-resumable": "start"},
                content_type=content_type,
                service_account_email=sa_email,
                access_token=credentials.token,
            )
            return {
                "upload_url": signed_url,
                "method": "POST",
                "mode": "resumable_signed_url",
                "required_headers": {
                    "x-goog-resumable": "start",
                    "Content-Type": content_type,
                },
                "gcs_path": object_path,
                "gcs_uri": f"gs://{cfg.gcs_raw_bucket}/{object_path}",
            }
        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=30),
            method="PUT",
            content_type=content_type,
            service_account_email=sa_email,
            access_token=credentials.token,
        )
        return {
            "upload_url": signed_url,
            "method": "PUT",
            "mode": "put_signed_url",
            "required_headers": {"Content-Type": content_type},
            "gcs_path": object_path,
            "gcs_uri": f"gs://{cfg.gcs_raw_bucket}/{object_path}",
        }

    # Local ADC fallback (user credentials cannot sign V4 URLs without SA impersonation)
    session_uri = blob.create_resumable_upload_session(
        content_type=content_type,
        origin=origin,
    )
    return {
        "upload_url": session_uri,
        "method": "PUT",
        "mode": "resumable_session_uri",
        "required_headers": {"Content-Type": content_type},
        "gcs_path": object_path,
        "gcs_uri": f"gs://{cfg.gcs_raw_bucket}/{object_path}",
    }
