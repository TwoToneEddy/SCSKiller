# Linux port: current state and resumption guide

Updated: 2026-10-06. Branch: `linux_port`. Workspace used for validation: `/home/lee/SCSKiller`.

## Objective and current stopping point

The original request was full Windows parity on CachyOS/Bazzite with a similar GUI. The user subsequently prioritized the performance benefit: **extract shaders from installed game files, compile pipelines before launch, and establish that games benefit**. Prioritize proving that benefit over additional cosmetic or account features.

**Extraction and pre-launch GPU compilation now work for the installed Witcher 3 DX12 build on CachyOS/NVIDIA. Actual game cache reuse and reduced stutter are not yet verified.** This is a native Linux frontend with the original engine running through Proton, not a fully native Linux rewrite of the C#/DirectX backend. Full Windows parity remains incomplete.

The user requested this branch and commit as a resumable checkpoint. The old sandbox restriction is gone: Proton executes successfully with the current permissions. Do not repeat the earlier claim that sandbox restrictions block testing. No sudo was needed for the successful verification.

## NEXT STEP (start here)

The GUI precompile → normal Steam launch workflow is implemented (section 1). What remains, in order:

1. **User test of the normal launch — needs the user at the machine.**
   - Clear Witcher 3's Steam Launch Options. They still contain the old `out/witcher3-game-test/launch.sh precompiled %command%` test wrapper, which redirects every cache.
   - Run `./linux/run.sh`, select Witcher, open **Game shaders…**, then **Compile** (experimental generated pipelines are enabled in `~/.config/scskiller/settings.json`).
   - With the dialog still open, click **Play**, reach the main menu and quit.
   - Pass: the Log tab shows `OK` for the NVIDIA cache directory, the NVIDIA application name and the mapped vkd3d archive (`The Witcher 3/bin/vkd3d-proton.cache`). If the live launch settings differ from the saved profile, the dialog asks you to Compile again; do so and repeat.
   - Record the result in a new `linux/validation/` note.
2. **Measure entry reuse after that launch.** Count how many of the game's newly written `bin/vkd3d-proton.cache.write` entries already exist in the merged `.cache` (hash comparison as in section 1). The expected result today is ~0 hits.
3. **Make generated pipelines match the game (the real blocker to any benefit).** Hashes from the previous gameplay test overlapped 0/610 with the generated set, while the game's own hashes are stable between runs. Investigate the synthesized root signatures and PSO templates (`Planning/Planner.cs`, `Planning/RootSig.cs`), using the game's own vkd3d archive entries or a recording as ground truth. Re-measure overlap after each change.
4. Only then compare stutter/frame times on a workload that has baseline compilation stalls.

## What was actually verified

| Item | Evidence |
| --- | --- |
| Host | CachyOS; RTX 5090; NVIDIA driver 615.71.09 |
| Game | The Witcher 3, Steam app 292030, build 14504303, DX12 executable |
| Runtime | Game's Steam-recorded `/usr/share/steam/compatibilitytools.d/proton-cachyos-slr` |
| Extraction | 24,266 shaders from installed files; 344,246 material techniques |
| Planning | 42,350 generated pipelines; zero recorded pipelines or middleware shared items |
| First GPU compile | 42,350 / 42,350, zero reported failures/skips; 119.32 seconds with a fresh isolated disk cache |
| Second helper compile | Same 42,350 / 42,350, zero failures/skips; 5.21 seconds using the same cache |
| Output | 275,210,233 bytes of NVIDIA/vkd3d cache files |
| Automated checks | 26 Python tests and 8 C# cache-format tests passed; Python package builds |
| Build | Original-core .NET helper publish and C++ MinGW cross-build succeeded |

Compile times include orchestration, not just GPU calls. The second pass runs another compiler process: its speedup supports helper-side reuse, **not proof of reuse by the actual game**. Eight stage combinations were excluded during planning. The 4,076 ray-tracing libraries remain uncovered by generated ray-tracing state objects. Zero compiler skips does not mean complete game coverage.

The game was not launched, no recorder was installed, and existing Steam caches were not cleared or used as test output. Extraction also found 8,340 shaders in Cyberpunk 2077, but its detected format requires a recording for planning; its compilation was not verified.

Earlier, real Fossilize replay for Witcher completed with partial coverage: reported counters were 10,007 graphics, 619 compute and 866 ray-tracing compiles, zero worker crashes, plus skipped pipelines, 64 validation failures and 193 missing modules. That separate path also has no measured game-stutter benefit. Do not confuse it with the later generated-pipeline verification above.

Durable evidence: [validation report](linux/validation/2026-10-05-witcher3.md) and [machine-readable summary with tested binary hashes](linux/validation/2026-10-05-witcher3.json). The summary correctly records the dirty working tree/source revision used during testing; it predates this checkpoint commit.

## Implemented components

- `linux/scskiller_linux/backend.py`: Steam discovery, Fossilize indexing/replay, Vulkan GPU detection, XDG settings/history and cancellation.
- `gui.py`: native PySide6 application following the Windows dark layout; library, search, replay queue, settings, details and Steam launch links.
- `core_gui.py`: original-engine dialog for extraction, planning, compilation, queue controls, settings, keys, recorder controls, session chart and account services. Many controls beyond extraction/compilation are implemented but untested against real games/services.
- `engine.py`: local JSON-lines transport to Proton; private-prefix initialization, runtime selection/fingerprinting, one game per session, process monitoring and shutdown.
- `linux/engine/Program.cs`: original `SCSKiller.Core` bridge. Reuses its readers, planner, warmer and application services. Automatic recorder management and automatic plan checks remain disabled. Generated-template capability is explicitly experimental and off by default.
- `linux/build-engine.py`: pinned LLVM-MinGW/DirectX-Headers cross-build and self-contained win-x64 .NET helper publish. Windows helper binaries run through Proton.
- `linux/verify-engine.py`: repeatable real-GPU extraction/planning/compilation test, fresh output directory, isolated caches, JSON report and event log. Does not launch the game.
- `linux/build.sh`, `package.py`, `run.sh`, `install-desktop.sh`: Python zipapp packaging, launcher and optional desktop entry. Python/Qt/Steam/drivers remain runtime dependencies.
- `proxy/` changes: MinGW GUID declarations, assembly forwarding stubs and COM structure-return compatibility; original MSVC paths retained.
- `RedShaderCache.cs`, `RedEngineReader.cs`: support Witcher DX12 cache versions 3 and 5 and their respective filenames.
- `.github/workflows/linux.yml`: Python/Qt build-test workflow. It has not been run on GitHub and does not validate the Proton/GPU path.

### Runtime fixes established by the tests

1. `runinprefix` skips Proton setup. Initialize the private prefix using `proton run cmd.exe /c exit 0` first so DXVK/vkd3d and ICU exist.
2. Include `d3d12core` in native DLL overrides; its Wine stub cannot serialize the required root signatures.
3. Version-3 Witcher material caches use unsuffixed filenames and omit the two short lists preceding the version-5 footer. Do not merely rename files or relax all validation.
4. The warmer stages itself as `witcher3.exe`. Exclude helper staging paths from game-running detection, or compilation pauses itself.
5. Set driver cache variables on the **Linux process before starting Proton**. Windows child environment changes alone did not redirect the native NVIDIA driver's cache. One game per helper session is enforced for this reason.
6. Hash translation DLLs under modern `x86_64-windows` as well as older `x86_64` layouts for invalidation. This fingerprint fix was unit-tested during the GPU run; it did not alter that run's compiler inputs.

## Build, run and reproduce

Full installation instructions: [Linux README](linux/README.md).

```bash
# Requires Linux .NET SDK 10. Bootstrap downloads the pinned C++ toolchain/headers.
python3 linux/build-engine.py --bootstrap
./linux/build.sh
./linux/run.sh

# Real GPU verification; choose a NEW output directory every time.
python3 linux/verify-engine.py steam:292030 \
  --output out/verification-witcher3-next --threads 4 --passes 2
```

The verifier determines the game's actual Proton runtime before redirecting its cache. It disables community/sharing for this test, refuses pre-existing recordings, and uses experimental generated templates. `--device` selects a Vulkan GPU; `--proton` explicitly overrides runtime selection. Do not use a different runtime and assume the game will reuse its cache.

GUI: select the GPU/Proton settings as needed, enable experimental generated pipelines, then select Witcher and open **Game shaders…**. The main library's Compile queue remains the separate Fossilize workflow. Ordinary engine compilation targets the selected game's cache; the verifier is the isolated alternative.

CLI:

```bash
./linux/run.sh engine index steam:292030
./linux/run.sh engine plan steam:292030 --experimental-templates
./linux/run.sh engine compile steam:292030 --experimental-templates
```

Automated checks:

```bash
./linux/build.sh
# Use the installed SDK executable if dotnet is not on PATH.
dotnet test tests/SCSKiller.Tests/SCSKiller.Tests.csproj \
  --filter FullyQualifiedName~RedShaderCacheFormatTests
```

Local toolchains are already available under `~/.local/share/scskiller-tools/`: `dotnet/dotnet` (SDK 10.0.401), `llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64`, and `DirectX-Headers`. The build script finds these as fallbacks. Overrides: `SCSKILLER_DOTNET` (executable), `SCSKILLER_LLVM` and `SCSKILLER_DX_HEADERS` (directories). `--no-restore` is only for an already-restored checkout. Do not assume a fresh machine has these tools or cached NuGet dependencies.

## Local artifacts and Git boundaries

Committed: source, tests, build/launch scripts, documentation, existing app assets, and the small validation summary. Generated binaries, downloaded toolchains, prefixes, shader blobs and GPU caches stay ignored.

Useful artifacts still on this machine:

- `dist/linux/scskiller`, `dist/linux/scskiller.pyz`, `dist/linux/engine/` — built GUI and helper.
- `out/verification-witcher3/report.json` and `events.jsonl` — complete successful run.
- `out/verification-witcher3/native-environment.json` — actual compiler process's Linux cache variables.
- `out/verification-witcher3/host/helper.log` — Proton/helper diagnostics.
- `out/verification-witcher3/host/state/games/steam_292030/linux-work/` — materialized shader and generated pipeline databases.
- `out/verification-witcher3/cache/` — verified isolated cache.
- `out/e2e/` — investigation scripts/logs; use the maintained verifier instead when resuming.
- `out/proton-engine/`, `out/linux-native/`, `out/linux-engine/` — earlier investigation/build outputs.

Regular app data uses `~/.local/share/scskiller/` and settings use `~/.config/scskiller/`, respecting XDG overrides. A desktop entry may point at this checkout. Old `dist/linux/gui.pid`/screenshots/logs are historical; do not assume a saved PID still identifies the app. No test game was left running.

## Remaining work, in priority order

### 1. GUI precompilation followed by normal Steam launch — implemented; live-launch verification pending

**This is the immediate implementation priority, before broader parity or more gameplay benchmarks.** The user must be able to select Witcher 3 in the GUI, compile its shaders, close the tool and launch the game normally through Steam. No helper commands, environment-file handoff, wrapper script or custom Steam Launch Options may be required from the user.

This workflow is technically feasible to implement on Linux: the helper must target the cache locations and graphics configuration the normal Steam/Proton game already uses. The isolated-cache wrapper was a test mechanism, not the intended product design. Correct cache routing does not itself establish that generated pipeline entries are compatible or reused.

Implementation work, in order:

1. **Automatically determine the game's normal launch configuration.** Resolve its selected Proton/runtime, GPU, executable identity, driver-cache application name, relevant vkd3d/DXVK graphics flags and default cache locations. Use Steam metadata and supported runtime configuration; if actual process observation is necessary, capture only the relevant fields automatically during a normal launch, save them per game, and explain any prerequisite in the GUI. The user must not collect `/proc` environment files manually.
2. **Compile into the caches that normal gameplay already opens.** For NVIDIA/Steam, match the normal per-game driver-cache path and application name. For vkd3d, handle both an explicit cache directory and the game's default working-directory cache, including their different filenames. Match the actual runtime/environment rather than asking the game to adopt the helper's settings. Account for Steam's container paths; do not blindly import container-only loader paths into a host helper. Preserve existing cache entries and game data.
3. **Integrate this into Game shaders → Compile.** Start/manage the helper automatically, apply the per-game configuration, record the resolved cache destinations and configuration in diagnostics, and invalidate cached configuration after relevant game/Proton/driver changes. Keep generated pipelines experimental until reuse is proven. A failed match must produce an actionable GUI message rather than silent success.
4. **Verify end to end with no custom Steam launch options.** Compile through the GUI, then launch Witcher normally through Steam. Confirm the actual game opens the cache populated by that GUI compile. Observe individual entry hits or source-aware key compatibility; investigate generated root signatures/pipeline states if entries do not match. Do not report cache opening as proof of entry reuse.

Acceptance for this immediate step: the entire workflow is GUI compile → ordinary Steam launch, with no manually supplied environment file, helper command or custom game launch parameter; process-level evidence confirms the same caches are opened. Acceptance for a useful precompiler additionally requires evidence that the game reuses compiled entries. Stutter reduction requires a separate repeatable workload that exhibits relevant stalls.

**Current evidence (2026-10-06):** the normal DX12 game's environment was captured in `out/witcher3-game-test/normal-game-environment.json`; its d3d12/d3d12core/dxgi hashes match CachyOS Proton and its NVIDIA driver is 615.71.09. `verify-engine.py --game-environment` replays an explicit graphics allowlist and records applied flags; Steam IDs are now supplied by the helper. Protonfixes remains disabled in the helper, with captured supported graphics flags applied directly. All 28 Python tests pass. Fresh compilation produced 42,350 pipelines with zero failures/skips under `out/witcher3-game-test/precompiled`.

The manual-wrapper gameplay comparison confirmed both requested isolated cache paths and the game's mapping of the generated vkd3d archive. Promotion from `.write` to `.cache` preserved its SHA-256. **This verifies routing/opening, not individual generated-entry hits.** Both gameplay runs were smooth; durations differed (121.89/91.81 seconds), and similar amounts of new NVIDIA/vkd3d cache data were written. No performance benefit is established. See [gameplay validation](linux/validation/2026-10-06-witcher3-game.md). Raw local evidence includes `report.json`, `native-environment.json`, per-phase game environments and before/after cache hashes. The GUI does not yet automate this matching.

**Implementation status (2026-10-06, evening):** steps 1–3 are implemented; step 4 still needs a normal game launch.

- `linux/scskiller_linux/launch_profile.py` observes the running game started by Steam (environment allowlist, `/proc/<pid>/cwd`, mapped vkd3d archive, translation DLL hashes, NVIDIA driver version), saves a per-game profile and marks it stale after game/Proton/driver changes.
- `EngineClient` with `launch_profile` points the native NVIDIA/Mesa cache at the game's Steam cache with its application name, stages vkd3d-proton output, and `publish_caches()` merges it into the archive the game opens. The default case is `<cwd>/vkd3d-proton.cache`; Witcher's is `The Witcher 3/bin/vkd3d-proton.cache`. The archive format is a 0x30-byte header (`VKS`, vendor/device ID, UUID) plus `{u64 hash, u64 checksum, u32 size, u32 type, payload}` entries. The merge keeps existing `.cache`/`.cache.write` entries, writes one `.cache` and backs up the originals. `routing.json` records the result.
- The bridge (`Program.cs` `HostGame.CacheEnvironment`) previously overrode `VKD3D_SHADER_CACHE_PATH` for the warmer child with the Steam shadercache directory, which the game never opens. The host now supplies the exact cache environment.
- GUI: Game shaders has **Detect from Steam launch** (opens `steam://rungameid`, polls `/proc`), an experimental-pipelines checkbox (restarts the helper), and Compile → publish with an explicit summary or actionable failure. While open it verifies a running game's cache paths, app name and mapped archive in the Log tab.
- Real run (headless, same code path): 42,350/42,350 compiled into `shadercache/292030/nvidiav1` (second pass 8 s, reusing that cache); 42,350 vkd3d entries merged with the game's 610 existing entries into `bin/vkd3d-proton.cache`. That profile was built from the earlier normal capture (`normal-game-environment.json`). A live detection replaces it the next time the game runs with the dialog open.
- **Reuse warning:** in the earlier gameplay test, **none** of the game's 610 vkd3d pipeline hashes matched any of the 42,350 generated hashes. The game's own hashes were stable across runs (600/610 identical). The planner logs `root sigs rebuilt from shader counts … 12 synthesized templates, 3 root signatures`. Generated root signatures and render-state templates therefore do not match the game's real PSOs. Routing is fixed, but until that changes the precompile gives no benefit. Next investigation: derive the real root signatures and PSO templates (from a recording, or from the game's own vkd3d archive entries) and re-measure hash overlap.
- Witcher's Steam Launch Options still contained the old `out/witcher3-game-test/launch.sh precompiled %command%` wrapper at this point. It must be cleared for normal-launch verification.

After the immediate workflow is implemented:

- [ ] Measure actual entry hits/misses or pipeline compilation events in a reproducible scene, preserving caches/saves/settings and using dedicated test caches when appropriate for controlled experiments.
- [ ] Compare matched gameplay frame times/compilation stalls on a workload with meaningful baseline stalls. A fast second helper pass alone is insufficient.
- [ ] Investigate root-signature, pipeline-state, application/profile and translation-layer differences when reuse fails. Windows `StateIndependentCache` assumptions are not established on Linux.
- [ ] Publish results, including negative findings. Only remove experimental status after game-side reuse is supported by evidence.

### 2. Recording and coverage

- [ ] Validate recorder installation/removal in the game's existing prefix, authorization ledger placement, DLL override backup/restoration and recovery from partial failure.
- [ ] Test mod coexistence, recording limits, session/frame data and pipeline replay without compromising original anti-cheat exclusions.
- [ ] Cover the currently uncompiled ray-tracing state objects through a valid recording and confirm game-side reuse.
- [ ] Validate per-prefix data/key/codec lookup: some original readers still use `AppStore.DefaultDir`, while host state uses a separate configured directory.
- [ ] Implement automatic recorder lifecycle only after explicit per-game flows are reliable. Never infer recording support from the cross-built DLL alone.

### 3. Broaden the proven path

- [ ] Exercise other original engine readers/planners on real games. Cyberpunk extraction works, but planning requires a recording; other installed games remain unverified.
- [ ] Validate DX11 through DXVK, graphics/compute/RT coverage, and NVIDIA/AMD capability profiles. Do not copy Windows driver measurements as Linux facts.
- [ ] Validate game/driver/Proton update invalidation, cancellation/recovery, resource limits and GPU selection on real workloads.
- [ ] Test Bazzite, AMD and native/Flatpak Steam runtime compatibility, additional libraries, permissions and non-ASCII paths. None has passed the complete generated-pipeline test yet.
- [ ] Run relevant original Windows tests/builds to confirm cross-compilation and REDengine changes preserve Windows behaviour. The full suite and native self-test executable have not been run.

### 4. Remaining product parity — secondary to performance proof

- [ ] Non-Steam launcher/prefix discovery and launching; complete installed-executable manual addition instead of just importing Fossilize recordings.
- [ ] Linux cache usage/management and supported driver controls. The bridge vendor cache usage remains a placeholder; progress may show zero cache growth despite real output. The verifier measures output files separately.
- [ ] Reliable background driver-update monitoring/rebuilds, Linux idle detection, notifications, startup and tray behaviour. Do not assume Windows idle/process APIs see the host desktop.
- [ ] End-to-end account authentication, entitlement, community download and opt-in sharing tests.
- [ ] Complete missing GUI/CLI/settings/queue actions and unify the original-engine and replay presentation. Review persistence, accessibility, scaling, themes and keyboard behaviour.
- [ ] Linux update/distribution mechanism and clean-machine reproducible packaging. Current zipapp is not self-contained; helper bootstrap still requires a separately installed .NET SDK.
- [ ] Define Linux equivalents or explicit exclusions for Windows-only services rather than claiming universal parity.

## Source map for resuming

Start with `linux/verify-engine.py`, `linux/scskiller_linux/engine.py`, and `linux/engine/Program.cs` for the verified flow. Original orchestration is `src/SCSKiller.Core/App/ScsKiller.cs`; capability rules are in `Contracts.cs` and `Planning/Planner.cs`; serialization in `Planning/RootSig.cs`; process execution in `Warming/Warmer.cs`; GPU/native cache code in `Vendors/` and `App/GameCaches.cs`. Recorder and compiler internals are `proxy/proxy.cpp`, `warm.cpp`, `warm11.cpp`, and `selftest.cpp`. Windows UI reference is `src/SCSKiller.App/` and `.github/assets/library.webp`.
