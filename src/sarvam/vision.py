import io
import time
import zipfile
import httpx
from src.config import SARVAM_API_KEY, SARVAM_BASE_URL

HEADERS = {"api-subscription-key": SARVAM_API_KEY, "Content-Type": "application/json"}

RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2


def _request_with_retry(method, url, retries=RETRY_ATTEMPTS, **kwargs):
    """Retries on timeouts/connection resets and 5xx responses (transient, e.g. a corporate
    proxy interrupting the blob-storage transfer) - never on 4xx, since retrying a bad request
    just wastes the same amount of time failing again."""
    for attempt in range(retries):
        last_attempt = attempt == retries - 1
        try:
            resp = httpx.request(method, url, **kwargs)
        except (httpx.TimeoutException, httpx.TransportError):
            if last_attempt:
                raise
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
            continue
        if resp.status_code >= 500 and not last_attempt:
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
            continue
        resp.raise_for_status()
        return resp


def digitize_document(file_bytes: bytes, filename: str, language: str = "en-IN",
                       poll_timeout_seconds: int = 60) -> str:
    """Runs the doc-digitization job flow and returns the extracted Markdown text.

    This is an async job under the hood (create -> upload -> start -> poll -> download);
    a caller should expect several seconds of latency, not an instant response.
    """
    create_resp = _request_with_retry(
        "POST", f"{SARVAM_BASE_URL}/doc-digitization/job/v1",
        headers=HEADERS, json={"job_parameters": {"language": language, "output_format": "md"}}, timeout=30,
    )
    job_id = create_resp.json()["job_id"]

    upload_resp = _request_with_retry(
        "POST", f"{SARVAM_BASE_URL}/doc-digitization/job/v1/upload-files",
        headers=HEADERS, json={"job_id": job_id, "files": [filename]}, timeout=30,
    )
    upload_url = upload_resp.json()["upload_urls"][filename]["file_url"]

    _request_with_retry(
        "PUT", upload_url,
        content=file_bytes, headers={"x-ms-blob-type": "BlockBlob"}, timeout=60,
    )

    _request_with_retry(
        "POST", f"{SARVAM_BASE_URL}/doc-digitization/job/v1/{job_id}/start",
        headers=HEADERS, json={}, timeout=30,
    )

    deadline = time.time() + poll_timeout_seconds
    job_state = None
    while time.time() < deadline:
        status_resp = _request_with_retry(
            "GET", f"{SARVAM_BASE_URL}/doc-digitization/job/v1/{job_id}/status",
            headers=HEADERS, timeout=30,
        )
        job_state = status_resp.json().get("job_state")
        if job_state in ("Completed", "PartiallyCompleted", "Failed"):
            break
        time.sleep(2)

    if job_state not in ("Completed", "PartiallyCompleted"):
        raise RuntimeError(f"Document digitization did not complete in time (state={job_state})")

    download_resp = _request_with_retry(
        "POST", f"{SARVAM_BASE_URL}/doc-digitization/job/v1/{job_id}/download-files",
        headers=HEADERS, json={}, timeout=30,
    )
    download_urls = download_resp.json()["download_urls"]
    zip_url = next(iter(download_urls.values()))["file_url"]

    zip_resp = _request_with_retry("GET", zip_url, timeout=30)
    archive = zipfile.ZipFile(io.BytesIO(zip_resp.content))
    md_name = next(name for name in archive.namelist() if name.endswith(".md"))
    return archive.read(md_name).decode("utf-8")
