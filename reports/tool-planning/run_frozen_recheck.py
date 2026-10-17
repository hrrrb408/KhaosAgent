"""Reuse the frozen dataset preparer/grader with the manually reviewed product."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from run_experiment import launch_product

ROOT = Path(__file__).resolve().parent
DATASET = ROOT.parent / "benchmark" / "dataset-v1"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['start', 'finish'])
    parser.add_argument('--task', required=True)
    parser.add_argument('--attempt', default='planning-v2-01')
    args = parser.parse_args()
    freeze = json.loads((ROOT / 'FREEZE.json').read_text())
    assert hashlib.sha256(Path('khaos/macos/AgentHost.swift').read_bytes()).hexdigest() == freeze['host_sha256']
    selected = [freeze['formal_primary_task']] + freeze['formal_followup_tasks_if_primary_progress']
    assert args.task in selected
    run = DATASET / 'runs' / 'api' / args.task / args.attempt
    record_path = run / 'run.json'
    if args.operation == 'start':
        controls = json.loads((ROOT / 'local-evidence/formal-controls/controls.json').read_text())
        control = next(c for c in controls if c['task'] == args.task)
        assert [v['passed'] for v in control['variants']] == [False, True]
        workspace_root = tempfile.mkdtemp(prefix='khaos-planning-frozen-')
        subprocess.run(['python3', str(DATASET / 'prepare_run.py'), '--model', 'api', '--task-id', args.task, '--attempt', args.attempt, '--workspace-root', workspace_root], check=True, capture_output=True)
        record = json.loads(record_path.read_text())
        logs = Path(tempfile.mkdtemp(prefix='khaos-planning-frozen-logs-'))
        (logs / 'stdin').write_bytes((run / 'task-prompt.txt').read_bytes())
        assert hashlib.sha256((logs / 'stdin').read_bytes()).hexdigest() == record['prompt_sha256']
        for name in ['stdout', 'stderr']:
            (logs / name).touch()
        process = launch_product(Path(freeze['product_app']), logs)
        record.update(status='running', started_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), product_source_commit=freeze['production_commit'], production_host_sha256=freeze['host_sha256'], app=freeze['product_app'], model_id=freeze['model'], model_provider=freeze['provider'], logs=str(logs), open_pid=process.pid, steps=[], credential_source='authorized existing Hermes GLM key, environment only; value omitted')
        record_path.write_text(json.dumps(record, indent=2) + '\n')
        capture = subprocess.Popen(
            [
                'python3', str(DATASET / 'capture_agent_events.py'),
                '--stdout', str(logs / 'stdout'), '--stderr', str(logs / 'stderr'),
                '--attempt-id', args.attempt, '--waiter-pid', str(process.pid),
                '--output', str(run / 'agent-events.jsonl'),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        record['capture_pid'] = capture.pid
        record_path.write_text(json.dumps(record, indent=2) + '\n')
        print(json.dumps({'run': str(run), 'workspace': record['workspace'], 'logs': str(logs)}))
        return
    record = json.loads(record_path.read_text())
    logs = Path(record['logs'])
    stdout = (logs / 'stdout').read_text()
    for name in ['stdout', 'stderr']:
        shutil.copyfile(logs / name, run / ('launcher.' + name))
    terminal_path = run / 'terminal-outcome.jsonl'
    snapshot_command = [
        'python3', str(DATASET / 'capture_agent_events.py'), '--snapshot',
        '--attempt-id', args.attempt, '--stdout', str(run / 'launcher.stdout'),
        '--stderr', str(run / 'launcher.stderr'), '--output', str(terminal_path),
    ]
    if record.get('open_pid'):
        snapshot_command.extend(['--waiter-pid', str(record['open_pid'])])
    subprocess.run(snapshot_command, check=True, capture_output=True, text=True)
    terminal = json.loads(terminal_path.read_text(encoding='utf-8'))
    record.update(
        status='completed' if terminal['task_record_present'] else 'terminal_outcome_incomplete',
        completed_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        terminal_outcome=terminal,
        workspace_diff=subprocess.check_output(
            ['git', '-C', record['workspace'], 'diff', 'HEAD'], text=True
        ),
    )
    records = [line for line in stdout.splitlines() if line.startswith('Launcher task record:')]
    if records:
        record['launcher_task_record'] = records[-1]
    record_path.write_text(json.dumps(record, indent=2) + '\n')
    if terminal['task_record_present']:
        subprocess.run(['python3', str(DATASET / 'grade_attempt.py'), '--model', 'api', '--task-id', args.task, '--attempt', args.attempt], check=True)
    else:
        print(json.dumps({'terminal_class': terminal['terminal_class'], 'evidence_complete': terminal['evidence_complete'], 'grade': 'NOT_RUN'}))


if __name__ == '__main__':
    main()
