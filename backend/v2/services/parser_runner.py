"""macOS Seatbelt sandbox + process limits + parent wall/RSS watchdog."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import psutil

from backend.v2.services.chunking import ParseFailure

CHILD = Path(__file__).resolve().parents[1] / "parser_child.py"


def sandbox_profile(input_path, output_path):
    def literal(value):
        return '(literal ' + json.dumps(str(value), ensure_ascii=False) + ')'
    def subpath(value):
        return '(subpath ' + json.dumps(str(value), ensure_ascii=False) + ')'
    reads = [subpath(p) for p in ("/System", "/usr", "/opt/homebrew", "/Library/Apple/System", "/private/preboot/Cryptexes", sys.prefix, CHILD.parent)]
    reads += [literal(p) for p in ("/", "/dev/null", "/dev/urandom", input_path)]
    python = Path(sys.executable).resolve()
    framework_python = Path(sys.base_prefix).resolve() / "Resources/Python.app/Contents/MacOS/Python"
    return ('(version 1)(allow default)(deny network*)(deny process-fork)'
            '(deny process-exec (require-all (require-not ' + literal(python) + ') (require-not ' + literal(framework_python) + ')))'
            '(deny file-read-data (require-all ' + ' '.join('(require-not ' + item + ')' for item in reads) + '))'
            '(deny file-write* (require-all (require-not ' + literal(output_path) + ') (require-not ' + literal('/dev/null') + ')))')



def run_restricted(command, *, source, input_path, output, output_path, timeout, memory_mb, output_limit, stop=None):
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise ParseFailure("isolation_unavailable")
    profile = sandbox_profile(input_path, output_path)
    # No credentials, HOME, DS_V2_* or ambient loader/python variables reach the parser.
    env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
    process = subprocess.Popen(["/usr/bin/sandbox-exec", "-p", profile, *command],
                               stdin=source, stdout=output, stderr=subprocess.DEVNULL,
                               env=env, close_fds=True, start_new_session=True)
    deadline = time.monotonic() + timeout
    try:
        monitor = psutil.Process(process.pid)
        while process.poll() is None:
            if stop is not None and stop.is_set():
                raise ParseFailure("worker_stopped", retryable=True)
            if time.monotonic() >= deadline:
                raise ParseFailure("parse_timeout")
            try:
                if monitor.memory_info().rss > memory_mb * 1024 * 1024:
                    raise ParseFailure("memory_limit")
            except psutil.NoSuchProcess:
                pass
            if os.fstat(output.fileno()).st_size > output_limit:
                raise ParseFailure("output_limit")
            time.sleep(0.05)
        if time.monotonic() >= deadline:
            raise ParseFailure("parse_timeout")
        if process.returncode != 0:
            raise ParseFailure("parser_process_failed")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()


def parse_source(source, claim, settings, stop=None):
    output_limit = settings.parse_max_text_chars * 8 + settings.parse_max_chunks * 1024
    options = {
        "mime": claim.mime_type, "sha256": claim.sha256,
        "max_pages": settings.parse_max_pages, "max_text_chars": settings.parse_max_text_chars,
        "chunk_size": settings.chunk_size, "chunk_overlap": settings.chunk_overlap,
        "max_chunks": settings.parse_max_chunks, "timeout": settings.parse_timeout_seconds,
        "memory_mb": settings.parse_memory_mb, "output_limit": output_limit,
    }
    input_path = settings.file_storage_root / claim.storage_key
    with tempfile.TemporaryDirectory(prefix="ds-v2-parser-") as directory:
        path = Path(directory).resolve() / "result.json"
        with path.open("w+b") as output:
            path.chmod(0o600)
            if settings.parser_backend=='docker' or sys.platform!='darwin':
                from backend.v2.services.docker_parser import run
                run(source,output,options,settings,stop)
            else:
                run_restricted([sys.executable, "-I", "-B", str(CHILD), json.dumps(options)],
                               source=source, input_path=input_path, output=output, output_path=path,
                               timeout=settings.parse_timeout_seconds, memory_mb=settings.parse_memory_mb,
                               output_limit=output_limit, stop=stop)
            if os.fstat(output.fileno()).st_size > output_limit:
                raise ParseFailure("output_limit")
            output.seek(0)
            try:
                result = json.load(output)
            except (ValueError, UnicodeError):
                raise ParseFailure("invalid_parser_output") from None
    if "error" in result:
        # Only known static codes can be persisted; child output is untrusted.
        allowed = {"invalid_format", "memory_limit", "encrypted_pdf", "page_limit", "text_limit", "archive_limit",
                   "unsupported_type", "unsafe_xml", "chunk_limit", "invalid_text", "no_text", "content_changed"}
        raise ParseFailure(result["error"] if result["error"] in allowed else "invalid_parser_output")
    chunks = result.get("chunks")
    if not isinstance(chunks, list) or not 1 <= len(chunks) <= settings.parse_max_chunks:
        raise ParseFailure("invalid_parser_output")
    return chunks
