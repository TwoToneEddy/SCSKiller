import argparse
import json
import signal
from dataclasses import asdict
from . import backend as b


def main():
    parser = argparse.ArgumentParser(description='SCSKiller for Linux — Vulkan shader cache warming')
    parser.add_argument('--screenshot', metavar='PNG', help='capture the real GUI after discovery and exit')
    sub = parser.add_subparsers(dest='command')
    sub.add_parser('scan', help='discover games and count recorded Vulkan pipelines')
    sub.add_parser('doctor', help='report Vulkan and replay dependencies')
    engine_parser = sub.add_parser('engine', help='use the original SCSKiller core through Proton')
    engine_parser.add_argument('operation', choices=['scan', 'index', 'plan', 'compile'])
    engine_parser.add_argument('game', help='exact installed game ID')
    engine_parser.add_argument('--experimental-templates', action='store_true')
    caches_parser = sub.add_parser('caches', help='report or clear one game’s compiled driver caches')
    caches_parser.add_argument('game')
    caches_parser.add_argument('--clear', action='store_true', help='delete them (Steam recordings are kept)')
    compile_parser = sub.add_parser('compile', help='replay one game by exact ID')
    compile_parser.add_argument('game')
    compile_parser.add_argument('--threads', type=int)
    args = parser.parse_args()
    if args.command is None:
        from .gui import main as gui_main
        return gui_main(args.screenshot)
    config = b.settings()
    devices = b.gpu_info()
    if args.command == 'doctor':
        print(json.dumps({'devices': devices, 'replayer': b.find_replayer(config),
                          'libraries': list(map(str, b.library_roots(config))), 'data': str(b.DATA)}, indent=2))
        return 0 if devices and b.find_replayer(config) else 1
    index = config['device']
    driver = b.fingerprint(devices[index]) if 0 <= index < len(devices) else ''
    games, warnings = b.scan(config, driver)
    if args.command == 'scan':
        print(json.dumps({'games': [asdict(g) for g in games], 'warnings': warnings}, default=str, indent=2))
        return 0
    if not driver and args.command != 'caches':
        parser.error('No selected Vulkan device. Install vulkan-tools and check the GPU driver.')
    game = next((g for g in games if g.id == args.game), None)
    if game is None:
        parser.error('Game ID not found; use scan to list IDs.')
    if args.command == 'caches':
        from . import caches, launch_profile as lp
        profile = lp.load(game)
        try:
            if args.clear:
                print(f'Freed {b.human_bytes(caches.clear(game, profile))}')
            print(json.dumps(caches.report(game, profile), indent=2))
            return 0
        except (OSError, caches.CacheError) as error:
            print(str(error))
            return 1
    if args.command == 'engine':
        from .engine import EngineClient
        config['experimental_templates'] = args.experimental_templates or config.get('experimental_templates', False)
        client = None
        try:
            client = EngineClient([game], devices, config,
                lambda packet: print(json.dumps(packet, default=str), flush=True))
            client.ready.result(timeout=60)
            signal.signal(signal.SIGINT, lambda *_: client.request_async('cancel'))
            states = client.request('scan', timeout=600)
            result = states if args.operation == 'scan' else client.request(args.operation, game=game.id, timeout=7200)
            print(json.dumps(result, indent=2))
            return 1 if args.operation == 'compile' and any(q.get('Stage') != 'Done' for q in result) else 0
        except Exception as error:
            print('Original engine failed:', str(error))
            return 1
        finally:
            if client:
                client.close()
    if args.threads is not None:
        if args.threads < 1:
            parser.error('--threads must be positive')
        config['threads'] = args.threads
    replay = b.Replay()
    signal.signal(signal.SIGINT, lambda *_: replay.cancel())
    signal.signal(signal.SIGTERM, lambda *_: replay.cancel())
    try:
        result = replay.run(game, config, driver, lambda line: print(line, flush=True))
        print(result)
        return 0 if result == 'Replayed' else 2
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
