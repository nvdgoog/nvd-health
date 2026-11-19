export interface UploadSignedInfo {
  upload_url: string;
  method: string;
  mode: string;
  required_headers: Record<string, string>;
  gcs_path: string;
}

const CHUNK_SIZE_BYTES = 8 * 1024 * 1024; // 8 MiB (multiple of 256 KiB as required by GCS)

/**
 * Upload a browser File directly to Google Cloud Storage, bypassing Cloud Run's 32 MiB limit.
 * Supports V4 Resumable Signed URLs (for >400 MB .zip files), V4 PUT Signed URLs, and direct session URIs.
 */
export async function uploadFileDirectToGcs(
  file: File,
  signed: UploadSignedInfo,
  onProgress?: (uploadedBytes: number, totalBytes: number) => void
): Promise<void> {
  if (signed.mode === "put_signed_url") {
    const res = await fetch(signed.upload_url, {
      method: "PUT",
      headers: signed.required_headers,
      body: file,
    });
    if (!res.ok) {
      throw new Error(`GCS PUT failed (${res.status}): ${await res.text()}`);
    }
    onProgress?.(file.size, file.size);
    return;
  }

  let sessionUri = signed.upload_url;
  if (signed.mode === "resumable_signed_url") {
    const startRes = await fetch(signed.upload_url, {
      method: "POST",
      headers: signed.required_headers,
    });
    if (!startRes.ok) {
      throw new Error(
        `Failed to initiate GCS resumable session (${startRes.status}): ${await startRes.text()}`
      );
    }
    const location = startRes.headers.get("Location");
    if (!location) {
      throw new Error("GCS resumable initiation did not return a Location header.");
    }
    sessionUri = location;
  }

  // Stream in 8 MiB chunks
  const total = file.size;
  if (total === 0) {
    const res = await fetch(sessionUri, { method: "PUT", body: file });
    if (!res.ok) throw new Error(`Empty upload failed: ${res.status}`);
    onProgress?.(0, 0);
    return;
  }

  let offset = 0;
  while (offset < total) {
    const end = Math.min(offset + CHUNK_SIZE_BYTES, total);
    const chunk = file.slice(offset, end);
    const contentRange = `bytes ${offset}-${end - 1}/${total}`;

    const res = await fetch(sessionUri, {
      method: "PUT",
      headers: {
        "Content-Range": contentRange,
      },
      body: chunk,
    });

    if (res.status === 308 || res.status === 200 || res.status === 201) {
      offset = end;
      onProgress?.(offset, total);
    } else {
      throw new Error(
        `Chunk upload failed at offset ${offset} (${res.status}): ${await res.text()}`
      );
    }
  }
}
