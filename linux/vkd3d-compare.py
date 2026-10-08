#!/usr/bin/env python3
"""Compare SCSKiller's generated vkd3d-proton pipelines with the ones a game saved.

vkd3d-proton reuses a cached pipeline only when its whole compatibility record
matches: state description hash, root signature hash and every shader hash
(cache.c vkd3d_pipeline_cache_compat_from_state_desc). This reports how much of
each part the generated archive shares with the game's own entries.

  linux/vkd3d-compare.py GENERATED GAME [GAME ...] [--exclude ARCHIVE]

GENERATED: an archive SCSKiller wrote (e.g. verify-engine.py's
cache/vkd3d-proton.witcher3.exe.cache.write). GAME: the game's archives
(vkd3d-proton.cache, .cache.write). --exclude: entries to drop from the game
side, e.g. a backup of the generated set that was merged into the game archive.
"""
import argparse
import struct
from collections import Counter

HEADER = 0x30          # 'VKS', vendor/device ID, UUID
COMPAT_CHUNK = 5       # VKD3D_PIPELINE_BLOB_CHUNK_TYPE_PSO_COMPAT
META_CHUNK = 4         # VKD3D_PIPELINE_BLOB_CHUNK_TYPE_SHADER_META, stage in the upper 16 bits
COMPUTE_BIT = 0x20     # VK_SHADER_STAGE_COMPUTE_BIT


def entries(path):
    """{entry hash: (state hash, root signature hash, shader hashes, is compute)}."""
    data = open(path, 'rb').read()
    out, at = {}, HEADER
    while at + 24 <= len(data):
        key, _, size, _ = struct.unpack_from('<QQII', data, at)
        if at + 24 + size > len(data):
            break                              # vkd3d-proton may be appending
        blob = data[at + 24:at + 24 + size]
        compat, compute, o = None, False, 48   # struct vkd3d_pipeline_blob header
        while o + 8 <= len(blob):
            kind, length = struct.unpack_from('<II', blob, o)
            if kind & 0xffff == COMPAT_CHUNK:
                compat = struct.unpack_from('<7Q', blob, o + 8)
            if kind & 0xffff == META_CHUNK and kind >> 16 == COMPUTE_BIT:
                compute = True
            o = (o + 8 + length + 7) & ~7
        if compat:
            out[key] = (compat[0], compat[1], tuple(h for h in compat[2:] if h), compute)
        at += 24 + size
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('generated')
    parser.add_argument('game', nargs='+')
    parser.add_argument('--exclude', action='append', default=[])
    args = parser.parse_args()
    generated = entries(args.generated)
    game = {}
    for path in args.game:
        game.update(entries(path))
    for path in args.exclude:
        for key in entries(path):
            game.pop(key, None)

    def kinds(keys, table):
        c = Counter('compute' if table[k][3] else 'graphics' for k in keys)
        return f'{c["graphics"]} graphics, {c["compute"]} compute'

    hits = set(game) & set(generated)
    shapes = {(v[1], v[2]) for v in generated.values()}
    near = [k for k, v in game.items() if (v[1], v[2]) in shapes and k not in hits]
    shaders = {h for v in generated.values() for h in v[2]}
    print(f'game pipelines: {len(game)} ({kinds(game, game)}); generated: {len(generated)}')
    print(f'full matches (vkd3d-proton reuses these): {len(hits)} ({kinds(hits, game)})')
    print(f'same shaders and root signature, different state: {len(near)} ({kinds(near, game)})')
    print(f'game root signatures generated: {len({v[1] for v in game.values()} & {v[1] for v in generated.values()})}'
          f' of {len({v[1] for v in game.values()})}')
    print(f'game shaders generated: {len({h for v in game.values() for h in v[2]} & shaders)}'
          f' of {len({h for v in game.values() for h in v[2]})}')


if __name__ == '__main__':
    main()
