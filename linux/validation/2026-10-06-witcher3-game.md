# Witcher 3 gameplay/cache-path validation — 2026-10-06

Steam build 14504303, CachyOS Proton 11.0-100, NVIDIA RTX 5090, driver 615.71.09.
The user launched and played the game through Steam. The helper ran on the host
with a private Proton prefix. No recorder was installed.

Captured the normal DX12 game's graphics environment, then used
`verify-engine.py --game-environment` to replay supported flags. The game's
d3d12, d3d12core and dxgi DLL hashes matched the selected Proton runtime.
All 42,350 generated pipelines compiled with zero failures/skips in 69.50 seconds;
the fresh test cache contained 277,009,618 bytes before game launch.

Two Steam launch-option runs redirected NVIDIA, Mesa, vkd3d and DXVK caches to
separate `out/witcher3-game-test/baseline/cache` and `precompiled/cache`
directories. The baseline cache was empty before its game launch. The
precompiled cache's file hashes were unchanged by the baseline run.

## What is mechanically verified

- Both actual game process environments contained the expected phase's paths.
- The precompiled game used NVIDIA cache application name
  `steamapp_shader_cache`, matching the native warmer's captured environment.
- `/proc/<game-pid>/maps` showed the game mapping the exact generated
  `precompiled/cache/vkd3d-proton.witcher3.exe.cache` file.
- The precompiler's 10,259,304-byte `.cache.write` was promoted to `.cache` with
  an identical SHA-256. The game therefore opened the generated cache archive.
- MangoHud was mapped in the game and produced frame-time CSVs for both runs.

## Results and limits

| Metric | Baseline | Precompiled |
| --- | ---: | ---: |
| Recorded duration | 121.89 s | 91.81 s |
| Mean frame time | 8.343 ms | 8.342 ms |
| 99th percentile frame time | 10.005 ms | 10.397 ms |
| Maximum frame time | 42.202 ms | 37.293 ms |
| Frames over 33.333 ms | 1 | 1 |
| Frames over 50 ms | 0 | 0 |

The user reported virtually no baseline stutters. These are single, unequal-duration
samples, approximately 120 FPS; they establish no performance improvement.
They do not attribute individual stalls to shader compilation.

Opening the correct archive does **not** prove hits on individual generated
entries. The game still produced 147,856 bytes of new vkd3d cache data versus
152,784 baseline bytes, and about 12.33 MB of new NVIDIA `.bin` data versus
12.49 MB baseline. These similar writes warrant further investigation of
generated pipeline compatibility; they are not a verified hit count or miss rate.
The helper's generated NVIDIA `.bin` data (~259.88 MB) remained unchanged.
Steam-container versus host execution and generated root signatures/pipeline
states remain possible differences to investigate.

Next: instrument actual cache entry hits/misses or compare shader/pipeline keys
with source-aware parsing. Cache routing is verified; generated entry reuse and
performance value remain unverified. Restore normal Steam Launch Options after
the comparison. No game shader binaries or raw caches are committed.

Local evidence is under `out/witcher3-game-test/`: normal-game environment,
native warmer environment, per-phase game environments, frame-time CSVs,
summaries and before/after cache hashes. Durable metrics are in
`2026-10-06-witcher3-game.json` beside this document.
