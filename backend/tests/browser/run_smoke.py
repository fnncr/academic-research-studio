"""Optional real Chromium check; disposable PostgreSQL, mock only, no API key.

From backend: TEST_DATABASE_URL=... ../.venv/bin/python tests/browser/run_smoke.py
Requires Node playwright and Chromium installed in the validation environment.
Not collected by pytest; no new application dependency. Ports 8000/5173 must be free.
"""
import json
import os
import signal
import socket
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import pytest

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
sys.path[:0] = [str(BACKEND), str(BACKEND / 'tests')]
from test_projects import storage
from test_exports import export_work
from test_manuscripts import save
from test_rich_objects import node, png
from test_model_api import TOKEN


def main():
    os.chdir(BACKEND)
    output = Path(os.environ.get('P6_BROWSER_ARTIFACT_DIR', '/tmp/p6-browser-audit')).resolve()
    output.mkdir(parents=True, exist_ok=True)
    processes = []
    logs = []
    for port in (8000, 5173):
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError(f'Port {port} is occupied; refuse to use another application')
    with pytest.MonkeyPatch.context() as patch:
        for key in ('ARS_OPENAI_API_KEY', 'ARS_OPENAI_APPROVAL', 'ARS_OPENAI_PRICE_CONFIRMED'):
            patch.delenv(key, raising=False)
        patch.setenv('MODEL_OWNER_TOKEN', TOKEN)
        database = storage.__wrapped__(patch)
        data = next(database)
        fixture = export_work.__wrapped__(data)
        try:
            client, path, _, old, source, old_plan = next(fixture)
            document = old['document']
            document['schema_version'] = '2'
            image = node('image', png_base64=png(), text='RU / EN — synthetic image', alt='Тестовый рисунок', width_cm=4)
            footnote = node('footnote', text='Synthetic note / примечание',
                            anchor={'block_id': image['id'], 'start': 0, 'end': 2, 'quote': 'RU'})
            owner = dict(id=str(uuid4()), text='Объединённая ячейка', row_span=1, col_span=2, covered_by=None)
            covered = dict(id=str(uuid4()), text='', row_span=1, col_span=1, covered_by=owner['id'])
            document['blocks'] += [image, footnote, node('formula', text='α + β = γ'),
                node('merged_table', rows=[{'id': str(uuid4()), 'cells': [owner, covered]}])]
            rich = save(client, path.rsplit('/', 1)[1], document, old['id']).json()
            response = client.post(path + '/research-plan/revisions', json={
                'request_id': str(uuid4()), 'base_revision_id': old_plan['id'],
                'manuscript_revision_id': rich['id'], 'document': old_plan['document']})
            assert response.status_code == 201, response.text
            seed = {'path': path, 'manuscript': rich, 'plan': response.json(),
                    'source_version': source['latest_version']['id']}
            (output / 'seed.json').write_text(json.dumps(seed, ensure_ascii=False))
            commands = [
                ([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'], BACKEND),
                ([sys.executable, '-m', 'app.model_worker'], BACKEND),
                (['npm', 'run', 'dev', '--', '--port', '5173', '--strictPort'], ROOT / 'frontend'),
            ]
            for index, (command, cwd) in enumerate(commands):
                log = (output / f'process-{index}.log').open('w')
                logs.append(log)
                processes.append(subprocess.Popen(command, cwd=cwd, stdout=log, stderr=log, start_new_session=True))
            with httpx.Client() as http:
                for _ in range(100):
                    if any(p.poll() is not None for p in processes):
                        raise RuntimeError('A smoke-test service exited; inspect local process logs')
                    try:
                        if http.get('http://127.0.0.1:5173/api/health').status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(.1)
                else:
                    raise RuntimeError('Smoke-test services did not become ready')
            subprocess.run(['node', str(Path(__file__).with_name('smoke.cjs')), str(output)], check=True)
        finally:
            for process in reversed(processes):
                try: os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError: pass
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL); process.wait()
            for log in logs: log.close()
            fixture.close()
            database.close()


if __name__ == '__main__':
    main()
