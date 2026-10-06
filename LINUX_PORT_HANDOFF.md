# Linux port: current state and resumption guide

Updated: 2026-10-05. Branch: `linux_port`. Workspace used for validation: `/home/lee/SCSKiller`.

## Objective and current stopping point

The original request was full Windows parity on CachyOS/Bazzite with a similar GUI. The user subsequently prioritized the performance benefit: **extract shaders from installed game files, compile pipelines before launch, and establish that games benefit**. Prioritize proving that benefit over additional cosmetic or account features.

**Extraction and pre-launch GPU compilation now work for the installed Witcher 3 DX12 build on CachyOS/NVIDIA. Actual game cache reuse and reduced stutter are not yet verified.** This is a native Linux frontend with the original engine running through Proton, not a fully native Linux rewrite of the C#/DirectX backend. Full Windows parity remains incomplete.

The user requested this branch and commit as a resumable checkpoint. The old sandbox restriction is gone: Proton executes successfully with the current permissions. Do not repeat the earlier claim that sandbox restrictions block testing. No sudo was needed for the successful verification.

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

### 1. Prove the performance value — next milestone

Gameplay follow-up completed 2026-10-06: both actual Steam game runs used the requested isolated caches. The precompiled run mapped the generated vkd3d archive; its promotion from `.write` to `.cache` preserved its SHA-256. This verifies cache routing/opening, **not individual generated-entry hits**. Baseline and precompiled gameplay were both smooth; durations differed (121.89/91.81 seconds), and similar amounts of new NVIDIA/vkd3d data were written. No performance benefit is established. See [gameplay validation](linux/validation/2026-10-06-witcher3-game.md). Next priority is actual entry hit/miss or key compatibility evidence, rather than another uninstrumented smooth-route comparison.

**Next real step, in this order:**

2026-10-06 progress: captured the normally launched DX12 game's environment in `out/witcher3-game-test/normal-game-environment.json`. Its d3d12/d3d12core/dxgi DLL hashes match the selected CachyOS Proton files, and its mapped NVIDIA driver is 615.71.09. Added `verify-engine.py --game-environment` to replay an explicit graphics-variable allowlist, including Steam IDs and NVIDIA shader-cache application name, while retaining private prefix/cache paths. Missing captured flags are cleared; container-only loader paths are not imported. The verifier records applied flags. All 28 Python tests pass. Fresh compilation completed under `out/witcher3-game-test/precompiled`: all 42,350 pipelines compiled, zero failures/skips; see its `report.json`, `native-environment.json` and `cache-before-game.json`. The native warmer environment confirms the captured Steam IDs/NVIDIA cache application name reached the process. Next: baseline gameplay with the dedicated empty cache, verify the running game's redirected paths, then repeat the same route using the precompiled cache. Game-side reuse and performance benefit remain unverified; the Steam-container versus host runtime difference remains a limitation.

1. **Capture the game's real environment.** Launch Witcher 3 normally through Steam and save its environment, e.g. `cat /proc/$(pgrep -f witcher3.exe | head -1)/environ | tr '\0' '\n' > witcher-env.txt`. This needs the user's desktop session and Steam.
2. **Match the helper to it.** Give `witcher-env.txt` to the agent, which updates the helper to use the same variables.
3. **The actual test.** Start with an empty game cache and precompile. Then launch the game and check whether the cache grows and whether the stutters go away in a fixed scene, compared with a run without precompiling.

Skipping straight to step 3 with the current code gives a quick first answer, but a cache miss then wouldn't show whether the approach fails or the environments just differed. Step 1 takes a couple of minutes, so do it first.

- [ ] **Do this before measuring cache hits:** make the helper's Proton environment match the game's own Steam launch. The helper currently sets no `SteamAppId`/`SteamGameId` and sets `PROTONFIXES_DISABLE=1` (`linux/scskiller_linux/engine.py`), so per-game Proton/protonfixes settings (for example `VKD3D_CONFIG` flags) that apply to the game do not apply to the helper. vkd3d-proton can then produce different SPIR-V or pipeline state, and the game misses the cache regardless of the plan. Capture the game's real launch environment (e.g. `/proc/<pid>/environ` of a running game, or `PROTON_LOG=1`), apply the vkd3d/driver-relevant variables to the helper, and record them in the verifier report.
- [ ] Verify the actual Witcher DX12 game uses the same Proton, GPU, native driver-cache path and compatible translation-layer cache as the successful helper. Check executable/profile/configuration identity, not just directory names.
- [ ] Measure game cache hits or pipeline compilation events in a reproducible scene with and without generated precompilation. Preserve existing caches/saves/settings; use dedicated test caches where practical.
- [ ] Compare repeatable gameplay frame times/compilation stalls. The game lacks a test harness in this port; a gameplay segment may require the user's participation.
- [ ] If generated pipelines are not reused, investigate root-signature, pipeline-state, application/profile and translation-layer differences before adding more features. Windows `StateIndependentCache` assumptions are not established on Linux.
- [ ] Publish the result even if it shows no benefit. Only remove experimental status after evidence supports the intended use.

Acceptance: the actual game reuses precompiled work and measurably avoids relevant compilation stalls. A fast second helper pass alone is insufficient.

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
