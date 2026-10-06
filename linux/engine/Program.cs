// Local JSON-lines bridge. Runs the original application core under the selected
// Proton build; all desktop integration and process transport live on the host.
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using SCSKiller.Core;
using SCSKiller.Core.App;
using SCSKiller.Core.Games;
using SCSKiller.Core.Planning;
using SCSKiller.Core.Vendors;
using SCSKiller.Core.Warming;

Console.InputEncoding = new UTF8Encoding(false);
Console.OutputEncoding = new UTF8Encoding(false);
if (args.Length != 1) { Console.Error.WriteLine("usage: scskiller-engine <host-manifest.json>"); return 1; }
var json = new JsonSerializerOptions { PropertyNameCaseInsensitive = true, Converters = { new JsonStringEnumConverter() } };
var config = JsonSerializer.Deserialize<HostConfig>(File.ReadAllText(args[0]), json) ?? throw new InvalidDataException("No host configuration");
var outputLock = new object();
void Send(object value) { lock (outputLock) { Console.WriteLine(JsonSerializer.Serialize(value, json)); Console.Out.Flush(); } }
var log = new Sink<string>(s => Send(new { Event = "log", Data = s }));
var source = new HostSource(config);
var adapters = GpuBackends.Adapters();
var gpu = adapters.Select(a => a.Gpu).FirstOrDefault(g => g.Name == config.GpuName)
    ?? (string.IsNullOrEmpty(config.GpuName) ? GpuBackends.Primary(adapters) : null)
    ?? throw new InvalidOperationException("Proton does not expose the selected GPU: " + config.GpuName);
var vendor = new ProtonVendor(gpu with { DriverVersion = config.Driver }, config.ExperimentalTemplates);
var readers = ScsKiller.DefaultReaders();
var planner = new Planner(Path.Combine(config.DataDirectory, "packs"), ScsKiller.SharedPackDir(config.DataDirectory, gpu.Vendor));
var warmer = new HostWarmer(vendor, config, log);
var app = new ScsKiller([source, new ManualSource(new AppStore(config.DataDirectory))], vendor, readers, planner, warmer,
    config.DataDirectory, Path.Combine(AppContext.BaseDirectory, "native", "d3d12.dll"));
app.Log = log;
app.CheckPlans = false;
app.ManageRecorders = false; // Recording is only installed by an explicit host request.
// Wine processes in a separate helper prefix cannot enumerate the game's Wine
// server. The host supplies running executable names, read afresh for each check.
app.RunningGameExes = () => ReadRunning(config.RunningFile);
if (!File.Exists(Path.Combine(config.DataDirectory, "settings.json")))
    app.Settings = AppStore.DefaultSettings with { RecordAllGames = false, StartWithWindows = false, ActiveCheck = false,
        ShareRecordings = false, WelcomeSeen = true, Threads = config.Threads };
var account = new Account(config.DataDirectory, openBrowser: uri => Send(new { Event = "open-url", Data = uri.AbsoluteUri }));
app.Community = new Community(config.DataDirectory, (fresh, ct) => account.GetDbTokenAsync(fresh, ct));
app.Sharing = new Sharing(config.DataDirectory, () => app.Settings.ShareRecordings);
app.GameChanged += state => Send(new { Event = "game", Data = state });
app.QueueChanged += item => Send(new { Event = "queue", Data = item });
var gate = new SemaphoreSlim(1);
var operations = new List<Task>();
var lifetime = new CancellationTokenSource();
var activeLock = new object();
CancellationTokenSource? active = null;
Send(new { Event = "ready", Data = new { Protocol = 1, Gpu = gpu, Caps = vendor.Caps, Settings = app.Settings,
    Backend = "Original SCSKiller core via Proton", ExperimentalTemplates = config.ExperimentalTemplates } });

void RequireGamePrefix()
{
    if (!config.GamePrefixInUse || config.Games.Length != 1)
        throw new InvalidOperationException("Recording requires an explicitly selected single game's existing Proton prefix");
}

async Task<object?> Dispatch(JsonElement request)
{
    var method = request.GetProperty("method").GetString();
    string Text(string key) => request.GetProperty(key).GetString() ?? throw new ArgumentException(key + " is required");
    bool Flag(string key) => request.TryGetProperty(key, out var v) && v.GetBoolean();
    string GameId() => Text("game");
    switch (method)
    {
        case "scan": return await app.ScanAsync(active!.Token, userRequested: Flag("online"));
        case "rescan": return await app.RescanAsync(active!.Token, userRequested: Flag("online"));
        case "games": return app.Games;
        case "settings.get": return app.Settings;
        case "settings.set":
            var next = request.GetProperty("settings").Deserialize<Settings>(json) ?? throw new ArgumentException("settings required");
            if (next.Threads < 1 || next.BackgroundThreads < 1 || next.RecordingLimitMB < 0 || next.MaxCompileMemoryGB < 0)
                throw new ArgumentException("Invalid resource limits");
            app.Settings = next with { StartWithWindows = false, RecordAllGames = false };
            return app.Settings;
        case "queue.get": return app.Queue;
        case "queue.add": if (Flag("idle")) app.EnqueueWhenIdle(GameId()); else app.Enqueue(GameId()); return app.Queue;
        case "queue.move": app.MoveInQueue(GameId(), request.GetProperty("index").GetInt32()); return app.Queue;
        case "queue.remove": app.Remove(GameId()); return app.Queue;
        case "queue.start": app.StartQueue(); return true;
        case "queue.pause": app.PauseQueue(); return true;
        case "queue.resume": app.ResumeQueue(); return true;
        case "compile": app.Compile(GameId()); await app.WhenQueueIdle(); return app.Queue;
        case "index":
        case "plan":
        {
            var game = app.Games.First(g => g.Game.Id == GameId());
            var engine = game.Engine ?? throw new InvalidOperationException("Engine not detected");
            var index = await Task.Run(() => readers.Index(game.Game, engine, log, active!.Token));
            var dir = app.Store.GameDir(game.Game.Id);
            Directory.CreateDirectory(dir);
            File.WriteAllText(Path.Combine(dir, "linux-index.json"), JsonSerializer.Serialize(index, json));
            if (method == "index") return new { Game = game.Game.Id, Engine = engine, index.ContentHash, Shaders = index.Shaders.Count, Maps = index.Maps.Count };
            var recordingPath = Path.Combine(Path.GetDirectoryName(game.Game.ExePath)!, "scskiller.db");
            var recording = File.Exists(recordingPath) ? new Recording(recordingPath) : null;
            var plan = await Task.Run(() => planner.Build(game.Game, engine, index, recording, vendor.Caps, dir, log, active!.Token));
            var work = Path.Combine(dir, "linux-work");
            await Task.Run(() => planner.Materialize(plan, game.Game, engine, readers, recording, work, active!.Token));
            return new { Plan = plan, WorkDirectory = work };
        }
        case "key.set": return app.SetEncryptionKey(GameId(), Text("key"));
        case "recorder.install":
        {
            RequireGamePrefix();
            var state = app.Games.First(g => g.Game.Id == GameId());
            var backup = Path.Combine(app.Store.GameDir(GameId()), "linux-dll-override.json");
            var key = @"Software\Wine\AppDefaults\" + Path.GetFileName(state.Game.ExePath) + @"\DllOverrides";
            using var registry = Microsoft.Win32.Registry.CurrentUser.CreateSubKey(key);
            if (!File.Exists(backup)) File.WriteAllText(backup, JsonSerializer.Serialize(new { Key = key, Value = registry.GetValue("d3d12") as string }, json));
            app.InstallRecorder(GameId());
            try { registry.SetValue("d3d12", "native,builtin"); }
            catch { app.UninstallRecorder(GameId()); throw; }
            return app.Games.First(g => g.Game.Id == GameId());
        }
        case "recorder.uninstall":
        {
            RequireGamePrefix();
            var backup = Path.Combine(app.Store.GameDir(GameId()), "linux-dll-override.json");
            app.UninstallRecorder(GameId());
            if (File.Exists(backup))
            {
                var original = JsonDocument.Parse(File.ReadAllText(backup)).RootElement;
                using var registry = Microsoft.Win32.Registry.CurrentUser.CreateSubKey(original.GetProperty("Key").GetString()!);
                // Preserve an override the user changed independently after installation.
                if (registry.GetValue("d3d12") as string == "native,builtin")
                {
                    if (original.GetProperty("Value").GetString() is { } old) registry.SetValue("d3d12", old);
                    else registry.DeleteValue("d3d12", false);
                }
                File.Delete(backup);
            }
            return true;
        }
        case "recorder.alongside": RequireGamePrefix(); app.SetRecordAlongsideMod(GameId(), Flag("enabled")); return true;
        case "recording.clear":
            if (!Flag("confirmed")) throw new InvalidOperationException("Deletion must be confirmed");
            return app.ClearRecording(GameId());
        case "cache.list": return app.GameCaches(GameId(), Flag("gamePrecache"));
        case "cache.clear":
            if (!Flag("confirmed")) throw new InvalidOperationException("Deletion must be confirmed");
            return app.ClearGameCache(GameId(), Flag("gamePrecache"));
        case "manual.preview": return app.PreviewManualGame(Text("exe"));
        case "manual.add": return app.AddManualGame(Text("exe"), request.TryGetProperty("directory", out var directory) ? directory.GetString() : null);
        case "manual.remove": app.RemoveManualGame(GameId()); return true;
        case "stale.dismiss": app.DismissStale(); return true;
        case "account.status": return new { account.Status, account.HasDb };
        case "account.signin": return await account.SignInAsync(active!.Token);
        case "account.signout": await account.SignOutAsync(active!.Token); return true;
        case "account.refresh": await account.RefreshAsync(active!.Token); return account.Status;
        case "community.sync": app.StartCommunitySync(fresh: true); await app.CommunitySync; return app.Games;
        case "refresh.game": app.RefreshGame(GameId()); return app.Games.First(g => g.Game.Id == GameId());
        default: throw new ArgumentException("Unknown method: " + method);
    }
}

while (await Console.In.ReadLineAsync() is { } line)
{
    JsonElement request;
    try { request = JsonDocument.Parse(line).RootElement.Clone(); }
    catch (JsonException error) { Send(new { Id = (int?)null, Error = error.Message }); continue; }
    if (request.ValueKind != JsonValueKind.Object || !request.TryGetProperty("id", out var i)
        || !request.TryGetProperty("method", out var m) || m.ValueKind != JsonValueKind.String)
    { Send(new { Id = (int?)null, Error = "A request requires id and a string method" }); continue; }
    var id = i.Clone();
    var method = m.GetString();
    if (method is "cancel" or "queue.stop" or "shutdown")
    {
        lock (activeLock) active?.Cancel();
        app.StopQueue(); account.CancelSignIn();
        Send(new { Id = id, Result = true });
        if (method == "shutdown") { lifetime.Cancel(); break; }
        continue;
    }
    if (method is "queue.pause" or "queue.resume" or "queue.get" or "games" or "settings.get")
    {
        try { Send(new { Id = id, Result = await Dispatch(request) }); }
        catch (Exception error) { Send(new { Id = id, Error = error.Message }); }
        continue;
    }
    operations.Add(Task.Run(async () =>
    {
        await gate.WaitAsync(lifetime.Token);
        try
        {
            lock (activeLock) active = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token);
            Send(new { Id = id, Result = await Dispatch(request) });
        }
        catch (Exception error) { Send(new { Id = id, Error = error.Message, Type = error.GetType().Name }); }
        finally
        {
            lock (activeLock) { active?.Dispose(); active = null; }
            gate.Release();
        }
    }));
    operations.RemoveAll(task => task.IsCompleted);
}
try { await Task.WhenAll(operations); await app.WhenQueueIdle(); } catch (OperationCanceledException) { }
lifetime.Cancel(); app.StopQueue();
return 0;

static IReadOnlySet<string> ReadRunning(string file)
{
    try { return JsonSerializer.Deserialize<string[]>(File.ReadAllText(file))!.ToHashSet(StringComparer.OrdinalIgnoreCase); }
    catch { return new HashSet<string>(); }
}

sealed class Sink<T>(Action<T> action) : IProgress<T> { public void Report(T value) => action(value); }
// CacheEnvironment, when supplied, is the exact cache routing of the game's normal launch.
sealed record HostGame(string Id, string Name, string InstallDir, string? ExePath, string? Version, string CacheDir,
    Dictionary<string, string>? CacheEnvironment = null);
sealed record HostConfig(string DataDirectory, string RunningFile, string Driver, int Threads, bool ExperimentalTemplates, HostGame[] Games, string? GpuName = null, bool GamePrefixInUse = false);
sealed class HostSource(HostConfig config) : IGameSource
{
    public Store Store => Store.Steam;
    public IReadOnlyList<Game> Discover() => config.Games.Select(g => (g, exe: g.ExePath ?? GameFiles.FindExe(g.InstallDir)))
        .Where(x => x.exe != null).Select(x => new Game(x.g.Id, x.g.Name, Store.Steam, x.g.InstallDir, x.exe!, x.g.Version)).ToList();
}
sealed class ProtonVendor(GpuInfo gpu, bool experimentalTemplates) : IGpuVendorBackend
{
    public GpuInfo Gpu => gpu;
    public GpuVendor Vendor => gpu.Vendor;
    // Do not reuse nvidia-1/amd-1 measurements made on Windows drivers.
    public VendorCaps Caps { get; } = new(experimentalTemplates ? "proton-experimental-templates-1" : "proton-recorded-1",
        CacheKeyedByExeName: true, StateIndependentCache: experimentalTemplates, CacheSizeConfigurable: false);
    public CacheUsage GetCacheUsage() => new("", 0, true);
    public CacheLimit? GetCacheLimit() => null;
    public void SetCacheLimit(CacheLimit limit) => throw new NotSupportedException("Linux cache settings are managed by the host");
}
sealed class HostWarmer(ProtonVendor vendor, HostConfig config, IProgress<string> log) : IWarmer
{
    public IWarmRun Start(Game game, string workDir, WarmOptions options, IProgress<WarmProgress>? progress)
    {
        var entry = config.Games.FirstOrDefault(g => g.Id == game.Id);
        var env = new Dictionary<string, string>();
        if (entry?.CacheEnvironment != null)
            foreach (var (key, value) in entry.CacheEnvironment) env[key] = value;
        else if (entry != null)
        {
            Directory.CreateDirectory(entry.CacheDir + "/nvidiav1");
            // Wine passes these through to the native Vulkan driver as Unix paths.
            var unix = entry.CacheDir.StartsWith("Z:", StringComparison.OrdinalIgnoreCase) ? entry.CacheDir[2..].Replace('\\', '/') : entry.CacheDir;
            env["__GL_SHADER_DISK_CACHE"] = "1";
            env["__GL_SHADER_DISK_CACHE_PATH"] = unix + "/nvidiav1";
            env["MESA_SHADER_CACHE_DIR"] = unix;
            env["MESA_SHADER_CACHE_DISABLE"] = "false";
            env["VKD3D_SHADER_CACHE_PATH"] = entry.CacheDir;
            env["DXVK_STATE_CACHE_PATH"] = entry.CacheDir;
        }
        return new Warmer(vendor, Path.Combine(AppContext.BaseDirectory, "native", "scskiller_warm.exe"))
            { Environment = env, Log = log }.Start(game, workDir, options, progress);
    }
}
