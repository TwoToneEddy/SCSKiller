# SCSKiller for Linux

Native Qt desktop application for **CachyOS and Bazzite (x86-64)**. The dark GUI follows the Windows app's sidebar, library table, summary cards, queue, settings, and game details. It uses the original icon and known-stutter list.

**Full Windows parity is still incomplete.** The native Qt app supports tested Fossilize replay and an optional, newly implemented bridge to the original SCSKiller core through Proton. The bridge has now extracted and compiled generated pipelines for the installed Witcher 3 on CachyOS/NVIDIA. In-game cache reuse and stutter reduction remain unverified; recording and account services still need runtime validation. Fossilize replay alone needs no Wine prefix or .NET SDK.

## Build and run on this CachyOS machine

From the repository root:

```bash
./linux/build.sh
./linux/run.sh
```

This machine already has Python, PySide6, Vulkan tools, Steam's replay tool, and a working NVIDIA Vulkan driver. The build runs the automated backend and GUI checks, then creates `dist/linux/scskiller.pyz` and its launcher. It does not require root or modify the Windows projects.

Optional application menu entry (points at this checkout; keep it in place):

```bash
./linux/install-desktop.sh
```

Re-run `build.sh` after changing the source. `run.sh` builds automatically only if the launcher is absent.

## Build and use the original-engine bridge

This optional component requires a Linux .NET 10 SDK, Git, Python, an x86-64 Proton installation, and the game installed through Steam. The build pins LLVM-MinGW and DirectX-Headers; initial tool downloads and NuGet restore need internet access.

```bash
python3 linux/build-engine.py --bootstrap
./linux/build.sh
./linux/run.sh
```

The helper is written to `dist/linux/engine/` next to the GUI launcher. You can set `SCSKILLER_DOTNET` to the SDK executable, `SCSKILLER_LLVM` to an existing LLVM-MinGW directory, and `SCSKILLER_DX_HEADERS` to the pinned DirectX-Headers checkout. With packages already restored, use `--no-restore` for a rebuild. `build-info.json` records the toolchain/source identity.

Select a game and click **Game shaders…**. Each engine session handles one game, so the native driver receives that game’s cache environment before Proton starts.

### Precompiling Steam games for a normal launch

No Steam Launch Options are needed (leave the field empty). The first time, click **Detect from Steam launch** in Game shaders: the game starts normally through Steam, SCSKiller reads its cache configuration from the running process (`/proc` environment, working directory and mapped files), and you quit at the main menu. The profile is saved to `~/.local/share/scskiller/launch-profiles/` and must be re-detected after a game, Proton or GPU driver update (the dialog says so). Then click **Compile**:

- NVIDIA/Mesa driver caches are written directly to the game’s Steam cache directory (for example `steamapps/shadercache/<appid>/nvidiav1`) with the same cache application name (`steamapp_shader_cache`).
- vkd3d-proton output is staged, then merged into the archive the game opens: `<working directory>/vkd3d-proton.cache` by default, or `vkd3d-proton.<exe>.cache` in an explicit `VKD3D_SHADER_CACHE_PATH`. Existing entries are kept and the originals are backed up under `~/.local/share/scskiller/engine/backups/`.
- The resolved destinations are recorded in `~/.local/share/scskiller/engine/routing.json`.

Keep the dialog open and click **Play** (or launch from Steam): the Log tab reports whether the running game uses the same NVIDIA cache directory/application name and maps the merged vkd3d archive. Opening the right caches does not prove that generated pipelines are reused; see the handoff document. The app uses Steam’s recorded Proton path; if it cannot determine that path, select the game’s Proton directory in Settings. It uses a private helper prefix by default. The CLI also supports:

```bash
./linux/run.sh engine scan steam:292030
./linux/run.sh engine index steam:292030
./linux/run.sh engine plan steam:292030
./linux/run.sh engine compile steam:292030
```

Generated templates require the experimental Settings switch (or `--experimental-templates`). Windows driver measurements have not been established for Proton, so generated-template capability is off by default. Compilation success would still need evidence that the actual game reuses the resulting driver cache.

The GUI starts the helper automatically; no separate helper terminal is needed. Ordinary Steam/Fossilize replay needs no custom game launch options. The fully matched generated-pipeline Witcher test described below still uses a captured game environment and a Steam launch wrapper: the GUI does not yet capture/apply those settings or configure the game's vkd3d cache path automatically. Do not assume a normal GUI compile reproduces that validated setup. Remove the test wrapper from Steam Launch Options when returning to normal play; that also stops routing the game to the isolated test cache.

Recorder operations require **Recorder session…** in game details, an existing Steam-created prefix, and closed Windows applications. They use that prefix so the original authorization ledger and per-executable DLL override are visible to the game. Installation backs up the previous override for removal. Automatic recorder installation remains disabled. These controls have not been tested against a running game; do not interpret their presence as verified compatibility.

Helper diagnostics are in `$XDG_DATA_HOME/scskiller/engine/helper.log` (normally `~/.local/share/scskiller/engine/helper.log`). The earlier sandbox restriction has been removed. The bridge now supports the installed Witcher 3’s version-3 cache format, as well as version 5. Witcher gameplay cache routing/opening was verified with the explicit test setup; generated-entry hits and performance benefit remain unverified. Bazzite, AMD and Flatpak runtime compatibility remain unverified.

## Fresh CachyOS installation

Install the host dependencies using the distribution's normal packages:

```bash
sudo pacman -Syu --needed python pyside6 qt6-wayland vulkan-tools
```

Install and start Steam, sign in, and install a game. Install the appropriate GPU driver through CachyOS's normal driver setup. Then use the build/run commands above. Confirm Vulkan works with `vulkaninfo --summary`.

## Bazzite

Run from a desktop terminal **on the host**, where Steam and the GPU driver are available. The app is installed in your home directory; no change to the immutable system image is required when Python and Vulkan tools are already available.

```bash
python3 --version
vulkaninfo --summary
./linux/build.sh
./linux/run.sh
```

The build uses system PySide6 when present. Otherwise it creates `linux/.venv` and installs the dependencies in `linux/requirements.txt` from PyPI. [Qt's Python wheels include the Qt libraries](https://doc.qt.io/qtforpython-6/gettingstarted.html). Internet access is needed for this initial dependency installation.

If Python's `venv`/pip support or `vulkaninfo` is missing from your Bazzite image, install the missing host tools, then reboot into the new deployment:

```bash
sudo rpm-ostree install python3-pip vulkan-tools
systemctl reboot
```

Only request packages your image does not already provide. A generic development container may have different Vulkan drivers and cannot establish that host game-cache warming works. Use the host GPU and Steam installation for replay.

Bazzite is a supported target of the implementation but has **not been run in this checkout's validation environment**; the actual desktop and GPU tests were on CachyOS.

## Using the app

1. Open **Library**. Native and Flatpak Steam locations and Steam's additional library folders are discovered automatically. You can add other library roots in Settings.
2. Games with recorded pipelines show shader/pipeline counts and **Ready to compile**. Counts are unique hashes in the selected recordings, not estimates from game file sizes.
3. Use **＋** to queue a game or **Add all ready**, then **Compile queue**. The queue supports removal, moving a pending game up, live output, and Stop. Stop terminates the replay process group, including its workers. Pending jobs remain available to restart.
4. **Play** opens the game's Steam launch URI. Double-click a game for paths, selected recordings, and status.
5. Settings selects a Vulkan GPU, compile thread count, custom replay executable, and additional library paths. GPU/driver or recording changes mark previous replays **Needs rebuilding** on refresh/startup.

Steam must have pipeline recordings for the game. Enable shader pre-caching in Steam, let its downloads finish, and play once if no recordings are available. Not every game supplies them. The app never labels an empty recording as compiled.

**Partial replay** means Fossilize reported missing/unsupported modules, skipped pipelines, validation failures, or worker crashes. Its process can return zero in these cases. Inspect the compile log; recompiling the same incomplete recordings may produce the same result. **Replayed** means the process completed without those reported problems, not a guarantee of zero game stutter or permanent cache residency.

The app selects the most recently updated recording group inside the newest available `fozpipelinesv*` directory. Steam retains historical groups for other Proton/driver configurations; mixing them can select incompatible application features. If there are no runtime groups, the base pipeline archives are used. Mesa `.foz` driver caches, video archives, replay metadata, and whitelists are excluded.

Avoid replay while Steam is processing shaders or while the game is running. SCSKiller serializes its own GUI/CLI replays; it cannot lock Steam's independent jobs. Cache eviction or manual deletion may require replay even if the status still says Replayed.

## Other launchers and manually supplied recordings

**Add a game…** accepts one or more existing Fossilize v6 pipeline archives. Give them a name and the cache root used by the game. These manual entries are persisted. This does not install a recorder or launch a non-Steam game.

Replay sets the same per-game cache locations used for Steam games:

```text
__GL_SHADER_DISK_CACHE=1
__GL_SHADER_DISK_CACHE_PATH=<cache root>/nvidiav1
MESA_SHADER_CACHE_DIR=<cache root>
MESA_SHADER_CACHE_DISABLE=false
```

For a manually added game, launch it with matching cache variables and the same GPU/driver so that it can reuse the output. A standalone `VkPipelineCache` file would not automatically be read by a game, so this app uses the driver's implicit disk cache instead.

Native and Flatpak Steam libraries are discovered. Flatpak Steam's bundled replay binary may depend on libraries from its runtime and fail when executed on the host. In that case select a host-built [Fossilize replay executable](https://github.com/ValveSoftware/Fossilize) in Settings. Paths and the underlying driver-cache contents must be accessible from both environments. This release does not bundle a Flatpak runtime or claim cross-runtime cache compatibility.

## Command line and troubleshooting

```bash
./linux/run.sh doctor
./linux/run.sh scan
./linux/run.sh compile steam:292030 --threads 4
./linux/run.sh --screenshot /tmp/scskiller.png
```

`doctor` reports devices, the detected replay tool, libraries, and data directory. `scan` emits JSON. Compile exit codes are 0 for Replayed, 2 for partial/cancelled, and 1 for failure. Ctrl+C stops replay workers. `--screenshot` launches the real GUI, waits for discovery, saves it, and exits; close an existing GUI first.

If the Wayland Qt plugin is unavailable, use XWayland:

```bash
QT_QPA_PLATFORM=xcb ./linux/run.sh
```

For a headless UI test/capture, set `QT_QPA_PLATFORM=offscreen`. Actual replay still requires a working Vulkan GPU.

Data locations respect XDG environment variables:

- Settings: `~/.config/scskiller/settings.json`
- Replay history and per-game logs: `~/.local/share/scskiller/`
- Driver output: the game's Steam `steamapps/shadercache/<appid>/` directory, or the manually selected cache root.

Fossilize replay reads archives without modification. The optional original-engine recorder controls can install the original DLL and change a per-executable Wine override after confirmation, using the selected game’s existing prefix. Original anti-cheat and mod checks remain in effect. Recording deletion also requires confirmation.

The launcher requires Python 3.10+ and PySide6 6.8+ at runtime. The `.pyz` bundles this app's code and resources, **not Python, Qt, Steam, or GPU drivers**. Keep the checkout's venv if the build created one; copying just the launcher to another PC does not install those dependencies.

## Coverage relative to Windows

| Feature | Linux edition |
| --- | --- |
| Native desktop GUI, search, details, queue, settings | Implemented |
| Steam / Flatpak Steam / external Steam libraries | Implemented |
| Steam game launch | Implemented |
| Manual Vulkan recording import | Implemented |
| Vulkan replay, progress logs, cancellation | Implemented using external Fossilize |
| Per-GPU/driver replay history and stale detection | Implemented on refresh/startup |
| Windows engine readers and DirectX pipeline synthesis | Witcher 3 extraction and 42,350 generated pipeline compiles verified on CachyOS/NVIDIA; other paths unverified |
| Windows DLL recorder and frame-time analysis | Cross-built recorder, prefix controls and frame chart implemented; runtime unverified |
| Automatic Epic/EA/GOG/Ubisoft/Xbox discovery | Not ported; manual recordings can be added |
| Windows GPU cache controls and scheduled tasks | Not applicable; no Linux equivalent implemented |
| Community account/sharing | Original services exposed through bridge; runtime unverified |
| Automatic app updates | Not implemented |

## Development and validation

```bash
python3 -m unittest discover -s linux/tests -v
PYTHONPATH=linux python3 -m scskiller_linux
```

Use `linux/.venv/bin/python` instead if your dependencies were installed in the venv. Tests use temporary data and fake replay subprocesses; they do not launch games or alter Steam caches. GUI tests use Qt's offscreen platform.

Architecture: `backend.py` handles discovery, header-only archive indexing, cache routing, process lifecycle, and persistence; `gui.py` uses worker threads to keep Qt responsive; `__main__.py` also exposes the headless CLI. Packaging uses Python's standard `zipapp` and accesses bundled resources through `importlib.resources`.

Validated on CachyOS with Python 3.14, PySide6 6.11.2, NVIDIA RTX 5090 / driver 615.71.09: built archive launch, desktop screenshot, four installed games discovered, and actual Witcher 3 pipeline replay. The replay writes NVIDIA driver-cache files and reports partial coverage where recordings are incomplete. This is not a before/after game-stutter benchmark.

## Licenses

Application code: repository GPL-3.0-or-later license. PySide6/Qt is an external dependency under LGPLv3/GPLv3 (see [Qt for Python licensing](https://doc.qt.io/qtforpython-6/licenses.html)). Fossilize is an external Valve tool under the MIT license. Its v6 archive specification is documented in [fossilize_db.cpp](https://github.com/ValveSoftware/Fossilize/blob/master/fossilize_db.cpp). No third-party executable is committed or bundled by this build.

## Original-engine verification (2026-10-05)

The installed Witcher 3 (Steam build 14504303, DX12) was tested using its Steam-recorded CachyOS Proton runtime and the RTX 5090. Extraction found **24,266 shaders**; planning generated **42,350 pipelines with zero recorded pipelines**. All 42,350 compiled with zero reported failures or skips. The first pass with a fresh isolated disk cache took **119.3 seconds** including orchestration; the second helper pass took **5.2 seconds**. The cache contained **275,210,233 bytes**. This demonstrates extraction and pre-launch compilation; the game was not launched and no game-performance improvement is claimed.

Coverage is partial: **8 stage combinations were left out of planning**, and **4,076 ray-tracing libraries remain uncovered by generated state objects**. A successful generated-pipeline compile is not complete game coverage. Generated templates remain opt-in while actual game cache reuse is unverified.

Reproduce against a new output directory (no recorder or existing Steam cache is modified):

```bash
python3 linux/verify-engine.py steam:292030 \
  --output out/verification-witcher3-new --threads 4 --passes 2
```

The script selects the game’s recorded Proton runtime before redirecting all compiler output to its isolated cache. It writes `report.json`, `events.jsonl`, helper logs, and generated pipeline data beneath that directory. Use `--device` to select another enumerated GPU and `--proton` only to explicitly override the runtime. The output directory must not already exist. This runs real GPU compilation, not a simulated test.

For a gameplay comparison, first capture the normally launched game's graphics environment. Pass the capture as `--game-environment path/to/capture.json`; its format is `{"environment":{"SteamAppId":"292030","SteamGameId":"292030",...}}`. The helper checks the game IDs and replays an explicit list of graphics flags, including vkd3d/DXVK options and NVIDIA's shader-cache application name. It keeps its private prefix and dedicated cache paths; Steam-container loader paths and the game's DLL overrides are not imported. Missing captured graphics flags are cleared from the helper environment. Protonfixes remains disabled because the captured graphics flags are applied directly. `host/graphics-environment.json` and `report.json` record what was applied. Matching these flags does not establish game-side cache reuse or identical behavior across the Steam container and host.

See [the validation report](validation/2026-10-05-witcher3.md) for fixes, evidence and limits. Automated checks now include 28 Python tests and 8 parser tests covering both REDengine cache versions and malformed inputs.

The [2026-10-06 gameplay follow-up](validation/2026-10-06-witcher3-game.md) verified that the Steam-launched game opens the generated vkd3d cache and uses the intended NVIDIA cache directory/application name. Both recorded runs were smooth. Individual generated-entry hits and a performance benefit remain unverified.
