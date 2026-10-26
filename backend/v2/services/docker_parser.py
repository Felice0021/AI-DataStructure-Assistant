"""Container sandbox fallback for Linux/WSL: no network, credentials, writable root or shared data."""
import json,os,shutil,subprocess,tempfile,time
from pathlib import Path
from uuid import uuid4
from backend.v2.services.chunking import ParseFailure


def run(source,output,options,settings,stop=None):
    docker=shutil.which('docker')
    if not docker:raise ParseFailure('isolation_unavailable')
    name='ds-v2-parser-'+uuid4().hex
    with tempfile.TemporaryDirectory(prefix='ds-container-input-') as directory:
        path=Path(directory).resolve()/'source.bin'
        with path.open('wb') as h:
            source.seek(0);shutil.copyfileobj(source,h,65536)
        # Only the single input file is mounted; no .env, source storage root or Docker socket.
        path.chmod(0o444)
        args=[docker,'run','--rm','--name',name,'--network','none','--read-only','--cap-drop','ALL',
            '--security-opt','no-new-privileges','--pids-limit','16','--cpus','1','--memory',str(options['memory_mb'])+'m',
            '--memory-swap',str(options['memory_mb'])+'m','--mount','type=bind,src='+str(path)+',dst=/input/source.bin,readonly',
            settings.parser_docker_image,json.dumps({**options,'container_source':True})]
        process=subprocess.Popen(args,stdout=output,stderr=subprocess.DEVNULL)
        deadline=time.monotonic()+options['timeout']+5
        try:
            while process.poll() is None:
                if stop is not None and stop.is_set():raise ParseFailure('worker_stopped',retryable=True)
                if time.monotonic()>=deadline:raise ParseFailure('parse_timeout')
                if os.fstat(output.fileno()).st_size>options['output_limit']:raise ParseFailure('output_limit')
                time.sleep(.05)
            if process.returncode!=0:raise ParseFailure('isolation_unavailable' if process.returncode==125 else 'parser_process_failed')
        finally:
            if process.poll() is None:
                process.kill();process.wait()
                subprocess.run([docker,'rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
