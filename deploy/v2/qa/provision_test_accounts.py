"""Create QA student accounts and a private test KB using real application routes.

--in-process invokes FastAPI via TestClient using the exact external HTTPS Origin:
this is needed when Cloudflare Quick Tunnel uses interactive email authorization.
It verifies application logic, not Cloudflare/browser connectivity. Browser QA is
required separately. Passwords, API keys and session cookies are not logged.
Existing credentials file is never overwritten; recover partial runs manually.
"""
import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener


def validate_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname
        or not parsed.hostname.endswith((".ts.net", ".trycloudflare.com"))
        or parsed.username or parsed.password or parsed.port or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("Expected exact approved QA HTTPS origin under *.ts.net or *.trycloudflare.com")
    return origin


class BrowserSession:
    def __init__(self, origin: str):
        self.origin = origin
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, method: str, path: str, body=None, content_type: str | None = None):
        headers = {"Accept": "application/json"}
        if method != "GET":
            headers["Origin"] = self.origin
            headers["X-CSRF-Token"] = self.request("GET", "/api/v2/auth/csrf")[1]["csrf_token"]
            if content_type:
                headers["Content-Type"] = content_type
            elif body is not None:
                headers["Content-Type"] = "application/json"
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = Request(self.origin + path, data=body, method=method, headers=headers)
        try:
            with self.opener.open(req, timeout=45) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else {}
        except HTTPError as exc:
            # Safe error code only; never log response bodies or credentials.
            raise RuntimeError(f"{method} {path.split('?')[0]} returned HTTP {exc.code}") from None
        except URLError as exc:
            raise RuntimeError(f"Cannot reach QA site: {type(exc.reason).__name__}") from None

    def register_and_login(self, email: str, password: str):
        self.request("POST", "/api/v2/auth/register", {"email": email, "password": password})
        self.request("POST", "/api/v2/auth/login", {"email": email, "password": password})



class InProcessBrowserSession(BrowserSession):
    """Exercise FastAPI with secure HTTPS cookies without bypassing email Access.

    This test client never opens a tunnel or external connection; it uses the QA
    database in DS_V2_QA_DB_NAME and private QA storage. The actual public HTTPS
    hostname must still be tested separately in a real browser.
    """
    def __init__(self, origin: str):
        from fastapi.testclient import TestClient
        from backend.v2.core.config import Settings
        from backend.v2.main import create_app

        self.origin = origin
        settings = Settings(
            environment="development", allow_insecure_loopback=False,
            allowed_origins=[origin],
            db_name=os.getenv("DS_V2_QA_DB_NAME", "ds_assistant_v2_qa"),
            file_storage_root=Path(os.getenv(
                "DS_V2_QA_STORAGE_ROOT",
                str(Path.home() / ".local/share/ds-assistant-v2/qa/files"))),
            embedding_provider="deterministic", embedding_allow_test_provider=True,
            embedding_cloud_enabled=False,
            rerank_provider="deterministic", rerank_allow_test_provider=True,
            rerank_cloud_enabled=False,
            generation_provider="deterministic", generation_allow_test_provider=True,
            generation_cloud_enabled=False,
        )
        self.client = TestClient(create_app(settings), base_url=origin,
                                 client=("127.0.0.1", 45211))
        self.client.__enter__()

    def request(self, method: str, path: str, body=None, content_type: str | None = None):
        headers = {"Accept": "application/json"}
        if method != "GET":
            headers["Origin"] = self.origin
            csrf = self.client.get("/api/v2/auth/csrf")
            if csrf.status_code != 200:
                raise RuntimeError(f"GET /api/v2/auth/csrf returned HTTP {csrf.status_code}")
            headers["X-CSRF-Token"] = csrf.json()["csrf_token"]
            if content_type:
                headers["Content-Type"] = content_type
        kwargs = {"content": body} if isinstance(body, bytes) else (
            {"json": body} if body is not None else {})
        response = self.client.request(method, path, headers=headers, **kwargs)
        if not response.is_success:
            raise RuntimeError(f"{method} {path.split('?')[0]} returned HTTP {response.status_code}")
        return response.status_code, response.json() if response.content else {}

    def close(self):
        self.client.__exit__(None, None, None)

def save_private(path: Path, payload: dict):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True, help="Exact private HTTPS QA origin (Tailscale or protected Quick Tunnel)")
    parser.add_argument("--in-process", action="store_true", help="Seed through FastAPI TestClient when external email Access blocks scripts")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[3] / "docs/v2/qa_synthetic_ds.txt")
    parser.add_argument("--confirm-source-rights", action="store_true",
                        help="Required to upload a source other than the authored synthetic sample")
    parser.add_argument("--output", type=Path, default=Path.home() / ".local/share/ds-assistant-v2/qa/credentials.json")
    args = parser.parse_args()
    origin = validate_origin(args.origin.strip())
    sample = Path(__file__).resolve().parents[3] / "docs/v2/qa_synthetic_ds.txt"
    source = args.source.resolve()
    if source != sample.resolve() and not args.confirm_source_rights:
        parser.error("Custom V1/PDF source requires explicit --confirm-source-rights after verifying reuse rights")
    if source.suffix.lower() not in {".txt", ".pdf"}:
        parser.error("Only .txt/.pdf supported for this QA seed")
    if not source.is_file() or source.stat().st_size > 20 * 1024 * 1024:
        parser.error("Source missing or over 20 MiB")
    seed = secrets.token_hex(5)
    creds = {
        "origin": origin, "provider": "deterministic", "purpose": "private QA only",
        "student_a": {"email": f"qa-chang-{seed}@example.com", "password": secrets.token_urlsafe(28)},
        "student_b": {"email": f"qa-isolation-{seed}@example.com", "password": secrets.token_urlsafe(28)},
        "kb_id": None, "document_id": None, "document_status_at_upload": None,
    }
    # Save before network activity to avoid losing a registered user's password on failure.
    # Refuse to reuse or clobber any existing secrets.
    save_private(args.output, creds)
    print(f"Credentials securely stored at: {args.output} (0600). Do not commit or post them.")

    SessionClass = InProcessBrowserSession if args.in_process else BrowserSession
    a = SessionClass(origin)
    a.register_and_login(creds["student_a"]["email"], creds["student_a"]["password"])
    b = SessionClass(origin)
    b.register_and_login(creds["student_b"]["email"], creds["student_b"]["password"])

    _, kb = a.request("POST", "/api/v2/knowledge-bases", {
        "name": "数据结构 QA 私人测试库", "description": "组内功能测试，禁止用于正式语义质量指标"})
    kb_id = kb["knowledge_base"]["id"]
    payload = source.read_bytes()
    boundary = "qa-" + secrets.token_hex(12)
    content_type = "application/pdf" if source.suffix.lower() == ".pdf" else "text/plain"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{source.name}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n").encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    _, doc = a.request("POST", f"/api/v2/knowledge-bases/{kb_id}/documents", body,
                       f"multipart/form-data; boundary={boundary}")
    doc_id = doc["document"]["id"]
    creds.update({"kb_id": kb_id, "document_id": doc_id,
                  "document_status_at_upload": doc["document"].get("status")})
    # Credentials are already created: safely update this one file only.
    temporary = args.output.with_name(args.output.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(creds, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(temporary, args.output)
    os.chmod(args.output, 0o600)

    # Verify ownership; B must not see A's private knowledge base.
    try:
        b.request("GET", f"/api/v2/knowledge-bases/{kb_id}")
    except RuntimeError as exc:
        if "HTTP 404" not in str(exc):
            raise
    else:
        raise RuntimeError("SECURITY CHECK FAILED: second user read private KB")

    if args.in_process:
        a.close()
        b.close()
    print(json.dumps({"student_a_email": creds["student_a"]["email"],
                      "student_b_email": creds["student_b"]["email"],
                      "kb_id": kb_id, "document_id": doc_id,
                      "status": doc["document"].get("status"),
                      "next": "Wait until parsed; POST embedding allow_cloud=false; verify ready"}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
