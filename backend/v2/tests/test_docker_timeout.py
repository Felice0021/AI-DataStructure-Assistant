"""Docker startup grace and timeout cleanup, without changing production limits."""
import io
import os
import subprocess
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.v2.services import docker_parser
from backend.v2.services.chunking import ParseFailure


def options():
    return {"memory_mb": 128, "timeout": 0.1, "output_limit": 10000}


def test_docker_deadline_includes_startup_grace_and_cleans_process(monkeypatch):
    ticks = iter([100.0, 105.0, 105.11])
    calls = []

    class Process:
        killed = False
        waited = False

        def poll(self):
            return None

        def kill(self):
            self.killed = True

        def wait(self):
            self.waited = True

    process = Process()
    monkeypatch.setattr(docker_parser.shutil, "which", lambda _: "/synthetic/docker")
    commands = []
    monkeypatch.setattr(docker_parser.subprocess, "Popen", lambda args, **kw: (commands.append(args), process)[1])
    monkeypatch.setattr(docker_parser.subprocess, "run", lambda args, **kw: calls.append(args))
    monkeypatch.setattr(docker_parser.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(docker_parser.time, "sleep", lambda _: None)
    # fstat requires a real file; no document content or external processes are involved.
    import tempfile
    with tempfile.TemporaryFile() as output:
        with pytest.raises(ParseFailure) as error:
            docker_parser.run(io.BytesIO(b"synthetic"), output, options(), SimpleNamespace(parser_docker_image="synthetic"))
    assert error.value.code == "parse_timeout"
    assert process.killed and process.waited
    args = commands[0]
    for flag, value in (("--network", "none"), ("--cap-drop", "ALL"), ("--memory", "128m"), ("--pids-limit", "16")):
        assert args[args.index(flag) + 1] == value
    assert "--read-only" in args and "no-new-privileges" in args
    assert len(calls) == 1 and calls[0][:3] == ["/synthetic/docker", "rm", "-f"]
    assert calls[0][3].startswith("ds-v2-parser-")


@pytest.mark.skipif(os.environ.get("DS_V2_RUN_DOCKER_TESTS") != "1", reason="Explicit prebuilt parser image test")
def test_real_slow_container_times_out_and_is_removed(monkeypatch, tmp_path):
    """A synthetic image sleeps beyond timeout + startup grace; no credentials or network."""
    tag = "ds-v2-timeout-test:" + uuid4().hex
    ident = uuid4()
    name = "ds-v2-parser-" + ident.hex
    dockerfile = b'FROM ds-assistant-v2-parser:local\nENTRYPOINT ["python", "-c", "import time; print(\\"started\\", flush=True); time.sleep(30)"]\n'
    built = False
    try:
        subprocess.run(["docker", "build", "-q", "-t", tag, "-"], input=dockerfile, check=True, stdout=subprocess.DEVNULL)
        built = True
        monkeypatch.setattr(docker_parser, "uuid4", lambda: ident)
        started = time.monotonic()
        with (tmp_path / "result").open("w+b") as output:
            with pytest.raises(ParseFailure) as error:
                docker_parser.run(io.BytesIO(b"synthetic"), output, options(), SimpleNamespace(parser_docker_image=tag))
            output.seek(0)
            assert output.read().strip() == b"started"
        elapsed = time.monotonic() - started
        assert error.value.code == "parse_timeout"
        assert 4.5 <= elapsed < 20
        assert subprocess.run(["docker", "inspect", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0
    finally:
        if built:
            subprocess.run(["docker", "image", "rm", tag], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
