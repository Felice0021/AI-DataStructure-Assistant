"""Run the original read-only V2 CLI twice and verify its generated mapping."""
from datetime import datetime, timedelta, timezone
from importlib.metadata import distributions
import json
from pathlib import Path
import platform
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/v2/course_audit/2026-11-04'
COMMAND = ['-B', '-m', 'backend.v2.tools.import_course', 'knowledge_base/ds_chunks.jsonl']

def main():
    first = subprocess.run([sys.executable, *COMMAND], cwd=ROOT, capture_output=True, text=True, check=True)
    manifest = json.loads(first.stdout)
    mapping_path = OUT / ('.cli-mapping-' + uuid4().hex + '.json')
    try:
        second = subprocess.run([sys.executable, *COMMAND, '--mapping-output', str(mapping_path)],
                                cwd=ROOT, capture_output=True, text=True, check=True)
        assert json.loads(second.stdout) == manifest, 'Repeated CLI result differs'
        actual_mapping = json.loads(mapping_path.read_text(encoding='utf8'))
        expected_mapping = json.loads((OUT / 'preview_mapping.json').read_text(encoding='utf8'))
        assert actual_mapping == expected_mapping, 'CLI mapping differs from offline prepare()'
        assert len(actual_mapping) == manifest['source_records'] == 1010
    finally:
        mapping_path.unlink(missing_ok=True)
    offline = json.loads((OUT / 'prepare_offline.json').read_text(encoding='utf8'))
    assert offline['derived_txt'] == manifest, 'CLI preview differs from offline prepare()'
    report = {
        'verified_at': datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),
        'platform': platform.system(), 'python':platform.python_version(),
        'command': 'python ' + ' '.join(COMMAND),
        'exit_code':first.returncode, 'stdout':manifest, 'stderr':first.stderr,
        'repeat_with_new_mapping_output_exit_code':second.returncode,
        'repeat_stdout_matches':True, 'mapping_matches_offline':True, 'mapping_records':len(actual_mapping),
        'scope':'Original CLI dry-run on native Windows; no --apply; not a full Windows/WSL backend acceptance',
        'installed_packages':dict(sorted((d.metadata['Name'], d.version) for d in distributions())),
    }
    (OUT / 'cli_dry_run.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'exit_code':first.returncode,**manifest,'repeat_matches':True,'mapping_matches':True}))

if __name__ == '__main__':
    main()
