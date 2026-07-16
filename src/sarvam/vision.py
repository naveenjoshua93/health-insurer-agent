import io
import time
import zipfile
import httpx
from src.config import SARVAM_API_KEY, SARVAM_BASE_URL

HEADERS = {"api-subscription-key": SARVAM_API_KEY, "Content-Type": "application/json"}


def digitize_document(file_bytes: bytes, filename: str, language: str = "en-IN",
                       poll_timeout_seconds: int = 60) -> str:
    """Runs the doc-digitization job flow and returns the extracted Markdown text.

    This is an async job under the hood (create -> upload -> start -> poll -> download);
    a caller should expect several seconds of latency, not an instant response.
    """
    create_resp = httpx.post(
        f"{SARVAM_BASE_URL}/doc-digitization/job/v1",
        headers=HEADERS,
        json={"job_parameters": {"language": language, "output_format": "md"}},
        timeout=30,
    )
    create_resp.raise_for_status()
    job_id = create_resp.json()["job_id"]

    upload_resp = httpx.post(
        f"{SARVAM_BASE_URL}/doc-digitization/job/v1/upload-files",
        headers=HEADERS,
        json={"job_id": job_id, "files": [filename]},
        timeout=30,
    )
    upload_resp.raise_for_status()
    upload_url = upload_resp.json()["upload_urls"][filename]["file_url"]

    put_resp = httpx.put(
        upload_url, content=file_bytes,
        headers={"x-ms-blob-type": "BlockBlob"}, timeout=30,
    )
    put_resp.raise_for_status()

    start_resp = httpx.post(
        f"{SARVAM_BASE_URL}/doc-digitization/job/v1/{job_id}/start",
        headers=HEADERS, json={}, timeout=30,
    )
    start_resp.raise_for_status()

    deadline = time.time() + poll_timeout_seconds
    job_state = None
    while time.time() < deadline:
        status_resp = httpx.get(
            f"{SARVAM_BASE_URL}/doc-digitization/job/v1/{job_id}/status",
            headers=HEADERS, timeout=30,
        )
        status_resp.raise_for_status()
        job_state = status_resp.json().get("job_state")
        if job_state in ("Completed", "PartiallyCompleted", "Failed"):
            break
        time.sleep(2)

    if job_state not in ("Completed", "PartiallyCompleted"):
        raise RuntimeError(f"Document digitization did not complete in time (state={job_state})")

    download_resp = httpx.post(
        f"{SARVAM_BASE_URL}/doc-digitization/job/v1/{job_id}/download-files",
        headers=HEADERS, json={}, timeout=30,
    )
    download_resp.raise_for_status()
    download_urls = download_resp.json()["download_urls"]
    zip_url = next(iter(download_urls.values()))["file_url"]

    zip_resp = httpx.get(zip_url, timeout=30)
    zip_resp.raise_for_status()
    archive = zipfile.ZipFile(io.BytesIO(zip_resp.content))
    md_name = next(name for name in archive.namelist() if name.endswith(".md"))
    return archive.read(md_name).decode("utf-8")
