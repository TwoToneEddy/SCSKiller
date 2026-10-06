#!/usr/bin/env python3
"""Run actual game extraction and GPU compilation with a fresh isolated cache.

Does not launch the game, install a recorder, or clear Steam's caches. A second
pass measures helper replay only; it is not evidence of in-game cache reuse.
"""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

from scskiller_linux import backend as b
from scskiller_linux.engine import EngineClient, proton_for_game, runtime_fingerprint, unix_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('game', help='installed Steam game ID, e.g. steam:292030')
    parser.add_argument('--output', type=Path, required=True, help='new directory for all test state, caches and reports')
    parser.add_argument('--device', type=int, default=0, help='Vulkan device index')
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--proton', help='explicit Proton directory; otherwise uses Steam recorded runtime')
    parser.add_argument('--passes', type=int, choices=[1, 2], default=2)
    parser.add_argument('--game-environment', type=Path, help='JSON environment capture from this running Steam game')
    args = parser.parse_args()
    if args.threads < 1:
        parser.error('--threads must be positive')
    root = args.output.expanduser().absolute()
    root.mkdir(parents=True, exist_ok=False)
    config = b.settings() | {'device':args.device, 'threads':args.threads, 'experimental_templates':True,
                            'engine_data':str(root / 'host'), 'use_game_prefix':False}
    # Verification uses the selected game's recorded runtime unless explicitly overridden.
    config['proton'] = args.proton or ''
    if args.game_environment:
        config['game_environment'] = str(args.game_environment.expanduser().absolute())
    devices = b.gpu_info()
    if not 0 <= args.device < len(devices):
        parser.error('Selected Vulkan GPU is unavailable')
    games, warnings = b.scan(config, b.fingerprint(devices[args.device]))
    game = next((g for g in games if g.id == args.game), None)
    if game is None:
        parser.error('Game not found; use ./linux/run.sh scan for IDs')
    runtime = proton_for_game(game, config)
    config['proton'] = str(runtime)
    isolated = replace(game, cache=root / 'cache')
    report = {'started':datetime.now(timezone.utc).isoformat(), 'game':game.id, 'build':game.version,
              'gpu':devices[args.device], 'proton':str(runtime), 'protonFingerprint':runtime_fingerprint(runtime),
              'experimentalTemplates':True, 'cache':str(isolated.cache), 'warnings':warnings,
              'gameLaunched':False, 'gameCacheReuseVerified':False, 'passes':[], 'success':False}
    client = None
    last_print = [0.0]
    with (root / 'events.jsonl').open('w') as events:
        def event(packet):
            events.write(json.dumps(packet) + '\n'); events.flush()
            if packet.get('Event') == 'log':
                print(packet['Data'], flush=True)
            elif packet.get('Event') == 'queue' and time.monotonic() - last_print[0] > 5:
                data = packet['Data']; p = data.get('Progress') or {}
                print(f"{data['Stage']}: {p.get('Done', 0)}/{p.get('Total', 0)}, failed {p.get('Failed', 0)}", flush=True)
                last_print[0] = time.monotonic()
        try:
            client = EngineClient([isolated], devices, config, event)
            report['graphicsEnvironment'] = json.loads((client.data / 'graphics-environment.json').read_text())
            ready = client.ready.result(120)
            prefs = ready['Settings'] | {'UseCommunityDb':False, 'ShareRecordings':False,
                                        'Threads':args.threads, 'MaxCompileMemoryGB':8}
            client.request('settings.set', settings=prefs)
            states = client.request('rescan', timeout=1200)
            report['scan'] = states
            state = next(s for s in states if s['Game']['Id'] == game.id)
            recording = unix_path(state['Game']['ExePath']).parent / 'scskiller.db'
            if recording.exists() and recording.stat().st_size:
                raise RuntimeError('Game already has a recording; this test requires a recording-free extraction path')
            start = time.monotonic()
            report['index'] = client.request('index', game=game.id, timeout=1200)
            report['indexSeconds'] = time.monotonic() - start
            report['plan'] = client.request('plan', game=game.id, timeout=1200)
            stats = report['plan']['Plan']['Stats']
            if stats['Recorded'] or not stats['Generated']:
                raise RuntimeError('Test requires generated pipelines from installed files, with no recorded pipelines')
            b.write_json(root / 'report.json', report)
            for number in range(1, args.passes + 1):
                start = time.monotonic()
                queue = client.request('compile', game=game.id, timeout=3600)
                item = next(q for q in queue if q['GameId'] == game.id)
                files = [{'path':str(p.relative_to(isolated.cache)), 'bytes':p.stat().st_size}
                         for p in sorted(isolated.cache.rglob('*')) if p.is_file()]
                report['passes'].append({'number':number,'seconds':time.monotonic()-start,'queue':item,'cacheFiles':files})
                progress = item.get('Progress') or {}
                if (item['Stage'] != 'Done' or progress.get('Failed', 0) or progress.get('Skipped', 0)
                    or not progress.get('Done') or progress['Done'] != progress.get('Total')):
                    raise RuntimeError('Compilation did not complete without failures; see report and helper logs')
                b.write_json(root / 'report.json', report)
            report['success'] = True
        except (Exception, KeyboardInterrupt) as error:
            report['error'] = str(error) or type(error).__name__
            print('Verification failed:', report['error'], flush=True)
        finally:
            if client:
                client.close()
            report['finished'] = datetime.now(timezone.utc).isoformat()
            b.write_json(root / 'report.json', report)
    print('Report:', root / 'report.json', flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
