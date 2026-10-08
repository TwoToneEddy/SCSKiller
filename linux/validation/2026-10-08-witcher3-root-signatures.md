# Witcher 3 root signatures and pipeline-state matching — 2026-10-08

Steam build 14504303 (version 3 material cache), CachyOS Proton, RTX 5090.

## Why generated pipelines never hit

vkd3d-proton reuses a cached pipeline only when its compatibility record matches:
state-description hash, root-signature hash and every shader hash
(`cache.c` `vkd3d_pipeline_cache_compat_from_state_desc`). Against the game's own
800 entries, the old plan shared 506/604 shaders, **0/55 root signatures** and 1/205
state hashes.

## Root signatures (fixed)

One session with `VKD3D_SHADER_DUMP_PATH` dumped the game's 72 root signatures
(file FNV-1 = the hash in the cache). This build does not use the three fixed
REDengine 3 signatures of the version 5 recording. It uses one layout whose
tables are sized to the pipeline's shaders: per stage (PS, VS, GS, HS, DS) a
CBV/SRV/sampler table sized to highest register + 1, rounded to 4/8/14,
4/8/16/32/128 and 4/8/16; absent stages get the largest size; one UAV table
(4/8/16). Compute: CBV/SRV/sampler/UAV tables, sized the same way. Predicted from
DXIL bindings, **744 of 744** checkable game pipelines get the exact signature.

Implemented as `RootSig.Rule.Red3Buckets`, chosen by `RedEngineReader` fork
`cache-v3` (version 3 material cache). The Red3 rule stays for version 5.

Isolated compile (`out/verify-red3buckets`, 42,353 pipelines, 0 failed), measured
with `linux/vkd3d-compare.py`:

- game root signatures generated: 48 of 59; the generated blobs hash identically to the dump
- **full matches: 30**, all compute: 30 of the game's 57 compute pipelines (the rest use
  shaders outside the game's shader caches). The game creates its pipelines with
  NodeMask 1, as the helper does.
- graphics: 654 of 743 have the same shaders and root signature but a different
  state hash.

## Graphics state (open)

Steam's community Fossilize cache (`steam_pipeline_cache.foz`, 10,985 graphics
pipelines) contains every shader combination of the game's 743 graphics
entries; modules carry the DXIL hash as an OpString. Reconstructing the D3D12
state from the Vulkan records did not reproduce any game state hash, even for
full-screen passes with an exhaustive search over the fields vkd3d-proton drops
(blend factors when blending is off, logic op, depth/stencil when disabled, DSV
format when unused, line mode, strip cut, flags). The hash function itself is
verified on the helper's own compute and synthesized graphics pipelines.
The next step is an exact recording of the game's D3D12 pipeline descriptions
(the project's recorder).
