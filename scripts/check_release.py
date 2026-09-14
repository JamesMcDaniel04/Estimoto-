#!/usr/bin/env python3
"""Run the local release checks and write source-bound, non-secret evidence.

Use --integration for a release gate with zero skipped backend tests. PostgreSQL
URLs must point to disposable test databases; the tests reset their own schema.
The original Estimoto backend is supplied separately, never a production API.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_ENV = (
    'PLUS_TEST_POSTGRES_URL', 'CALENDAR_TEST_POSTGRES_URL',
    'DISCOVERY_TEST_POSTGRES_URL', 'ESTIMOTO_BRIDGE_BACKEND',
    'ESTIMOTO_BRIDGE_PYTHON',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--integration', action='store_true')
    parser.add_argument('--output', type=Path, required=True,
                        help='An empty directory outside the checkout for logs/evidence')
    args = parser.parse_args()
    output = args.output.resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error('Keep release evidence outside the checkout until it has been reviewed.')
    if output.exists() and any(output.iterdir()):
        parser.error('Use a new empty output directory for each candidate.')
    if args.integration and any(not os.environ.get(key) for key in INTEGRATION_ENV):
        parser.error('--integration requires all five documented integration environment variables.')
    status = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=ROOT)
    if status:
        parser.error('Commit the candidate first; release checks require a clean source tree.')
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    venv = ROOT / 'backend/.venv/bin/python'
    python = str(venv) if venv.exists() else sys.executable
    junit = output / 'backend.xml'
    checks = [
        ('backend', [python, '-m', 'pytest', '-q', f'--junitxml={junit}'], ROOT / 'backend'),
        ('flutter-analyze', ['flutter', 'analyze', '--no-pub'], ROOT / 'app'),
        ('flutter-tests', ['flutter', 'test', '--no-pub'], ROOT / 'app'),
        ('capture-web', ['bash', 'scripts/build_capture.sh'], ROOT),
        ('api-and-dart-socket', [python, 'scripts/smoke_api.py', '--flutter-client'], ROOT),
        ('discovery-socket', [python, 'scripts/smoke_discovery.py'], ROOT),
        ('calendar-socket', [python, 'scripts/smoke_calendar.py'], ROOT),
    ]
    evidence = {'source_sha': source, 'integration_required': args.integration,
                'started_at': datetime.now(timezone.utc).isoformat(), 'checks': [], 'passed': False}
    evidence_file = output / 'result.json'
    for name, command, cwd in checks:
        print(f'Running {name}', flush=True)
        log = output / f'{name}.log'
        with log.open('wb') as stream:
            result = subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
        os.chmod(log, 0o600)
        check = {'name': name, 'exit_code': result.returncode,
                 'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
        if name == 'backend' and result.returncode == 0:
            suites = ET.parse(junit).getroot()
            skipped = sum(int(suite.get('skipped', '0')) for suite in suites.iter('testsuite'))
            check['skipped'] = skipped
            if args.integration and skipped:
                check['gate_error'] = 'Integration release gate requires zero skipped backend tests.'
        evidence['checks'].append(check)
        evidence_file.write_text(json.dumps(evidence, indent=2) + '\n')
        if result.returncode or check.get('gate_error'):
            print(f'Failed {name}; inspect {log}', file=sys.stderr)
            return 1
    # Catch source edits made during the gate, including concurrent agent work.
    final_status = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=ROOT)
    final_source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    evidence['source_unchanged'] = not final_status and final_source == source
    evidence['passed'] = evidence['source_unchanged']
    evidence['finished_at'] = datetime.now(timezone.utc).isoformat()
    evidence_file.write_text(json.dumps(evidence, indent=2) + '\n')
    if not evidence['passed']:
        print('Source changed during checks; rerun against a clean candidate.', file=sys.stderr)
        return 1
    print(f'All release checks passed for {source}; evidence: {evidence_file}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
