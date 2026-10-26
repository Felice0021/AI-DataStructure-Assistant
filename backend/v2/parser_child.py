"""Internal parser entry point: inherited input/output only; never prints exceptions."""
import json
import math
import os
from pathlib import Path
import resource
import signal
import sys

# Explicit namespace packages avoid reading/listing the repository root or V1 package.
# Executed with -I; ambient PYTHONPATH and user site packages are ignored.
import types
backend = types.ModuleType("backend")
backend.__path__ = []
v2 = types.ModuleType("backend.v2")
v2.__path__ = [str(Path(__file__).resolve().parent)]
sys.modules["backend"] = backend
sys.modules["backend.v2"] = v2


def main():
    options = json.loads(sys.argv[1])
    memory = options["memory_mb"] * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (math.ceil(options["timeout"]), math.ceil(options["timeout"]) + 1))
    # macOS does not reliably support hard DATA/AS limits for this framework build.
    # The parent enforces live RSS and kills the process; do not claim an AS hard cap.
    if sys.platform != "darwin":
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_FSIZE, (options["output_limit"], options["output_limit"]))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    # Also bounds an orphan child after parent SIGKILL; CPU limits alone do not bound sleep.
    signal.alarm(math.ceil(options["timeout"]) + 2)
    from backend.v2.services.chunking import ParseFailure, chunk_blocks
    try:
        import hashlib
        from backend.v2.services.text_extraction import extract_text
        with (open("/input/source.bin","rb") if options.get("container_source") else os.fdopen(os.dup(0), "rb")) as source:
            digest = hashlib.sha256()
            while data := source.read(65536): digest.update(data)
            if digest.hexdigest() != options["sha256"]:
                raise ParseFailure("content_changed")
            source.seek(0)
            blocks = extract_text(source, options["mime"], options)
        chunks = chunk_blocks(blocks, size=options["chunk_size"], overlap=options["chunk_overlap"], max_chunks=options["max_chunks"])
        result = {"chunks": chunks}
    except ParseFailure as error:
        result = {"error": error.code}
    except MemoryError:
        result = {"error": "memory_limit"}
    except BaseException:
        result = {"error": "invalid_format"}
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
