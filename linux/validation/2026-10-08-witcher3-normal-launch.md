# Witcher 3 GUI compile → normal Steam launch — 2026-10-08

Steam build 14504303, CachyOS Proton (`proton-cachyos-slr`), RTX 5090, driver
615.71.09. Steam Launch Options empty. The user ran the GUI and the game.

## Workflow (passed)

1. **Game shaders… → Detect from Steam launch.** The profile was captured with
   working directory `bin/x64_dx12`, while the game mapped
   `bin/vkd3d-proton.cache`. Routing used the working directory, so the first
   publish wrote 42,350 entries to `bin/x64_dx12/vkd3d-proton.cache`, which
   the game never opens. Fixed: routing now prefers the mapped archive
   (`launch_profile.routing`, test `test_mapped_archive_wins_over_working_directory`),
   and the profile change check compares routing instead of the working directory.
2. **Compile in the dialog** (after the fix): 42,350 / 42,350, 0 failed,
   0 skipped. vkd3d archive `bin/vkd3d-proton.cache`: 0 added, 43,007 kept
   (the generated set is deterministic and already present). NVIDIA cache
   `shadercache/292030/nvidiav1` (`steamapp_shader_cache`), 980.2 MB.
   Reported growth 10.3 MB is the vkd3d staging archive (10,259,304 bytes)
   plus driver writes; the label now says so.
3. **Normal Steam launch with the dialog open.** Log tab:
   - OK NVIDIA cache directory
   - OK NVIDIA cache application name
   - OK vkd3d-proton archive mapped `bin/vkd3d-proton.cache`

Routing acceptance for the normal-launch workflow is met: no launch options,
helper commands or environment files.

## Entry reuse (failed, as expected)

`bin/vkd3d-proton.cache` holds 43,007 type-2 (pipeline) entries: 42,350
generated + 657 written by the game itself (610 on 2026-10-06, 47 earlier
today). Overlap between the game's own entries and the generated set: **0**.
This short session wrote 28 more pipelines to `.cache.write`. None were in
`.cache` or in the 2026-10-06 game set.

The game opens the precompiled cache but never requests a generated pipeline.
Precompilation currently gives no benefit. Next: make generated root
signatures and PSO templates match the game's (see handoff, NEXT STEP).
