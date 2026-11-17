#pragma warning disable GHCP001
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using GitHub.Copilot;

if (args.Length is not (3 or 4)) return 2;
bool invalidWorkingDirectory = args.Length == 4 && args[3] == "invalid-working-directory-control";
if (args.Length == 4 && !invalidWorkingDirectory) return 2;
string runtime = Path.GetFullPath(args[0]);
string scratch = Path.GetFullPath(args[1]);
string receiptPath = Path.GetFullPath(args[2]);
if (File.Exists(receiptPath) || Directory.Exists(receiptPath)) return 2;
string native = Path.Combine(runtime, "runtimes", "win-x64", "native", "copilot.exe");
string nativeLibrary = Path.Combine(runtime, "runtimes", "win-x64", "native", "copilot_runtime.dll");
string Hash(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
var result = new Dictionary<string, object?>
{
    ["schemaVersion"] = 1,
    ["evidenceSource"] = "public_sdk_create_session_control",
    ["control"] = invalidWorkingDirectory ? "invalid-working-directory" : "valid-bare-startup",
    ["modelSendCalled"] = false,
    ["providerCredentialsFetched"] = false,
    ["requestHandlerAdmissions"] = 0,
    ["operation"] = "preflight",
    ["sessionCreated"] = false,
    ["clientDisposed"] = false,
    ["ownedStateRemoved"] = false,
};
var requests = new RejectRequests();
CopilotClient? client = null;
bool owned = false;
bool identity = false;
int exit = 1;
string Classify(Exception error) => error switch
{
    RemoteRpcException => "sdk_rpc",
    OperationCanceledException => "canceled",
    UnauthorizedAccessException => "access_denied",
    DirectoryNotFoundException => "directory_missing",
    FileNotFoundException => "file_missing",
    IOException => "io",
    InvalidOperationException => "invalid_operation",
    ArgumentException => "argument",
    _ => "unknown",
};
void Failure(Exception error, string field)
{
    var value = new Dictionary<string, object?> { ["exceptionCategory"] = Classify(error) };
    if (error.InnerException != null) value["innerExceptionCategory"] = Classify(error.InnerException);
    RemoteRpcException? rpc = error as RemoteRpcException ?? error.InnerException as RemoteRpcException;
    if (rpc != null)
    {
        value["rpcErrorCode"] = rpc.ErrorCode;
        value["rpcErrorDataKind"] = rpc.ErrorData?.ValueKind.ToString() ?? "absent";
    }
    result[field] = value;
}
try
{
    if (!OperatingSystem.IsWindows()) throw new InvalidOperationException();
    result["workingDirectoryExists"] = Directory.Exists(runtime);
    result["workingDirectoryIsFile"] = File.Exists(runtime);
    if (Directory.Exists(scratch) || File.Exists(scratch)) throw new InvalidOperationException();
    string sdkHash = Hash(typeof(CopilotClient).Assembly.Location);
    string nativeHash = Hash(nativeLibrary);
    string launcherHash = Hash(native);
    result["sdkSha256"] = sdkHash;
    result["nativeSha256"] = nativeHash;
    result["launcherSha256"] = launcherHash;
    identity = sdkHash == "f788257d2b1d8f158a85ce1940d2f757495e6e9c40406973f9ae16d7d12b7f1f" &&
        nativeHash == "5c817c3f315da691e31a3a2acbd7ab9a8ae4cea0aebb456999ccfa0ed1dade92" &&
        launcherHash == "776e6a9c6365c7c5d60f4e6f692a5e16f9562a7add3347fe591342d62c5c4149";
    result["exactPackagedSdkAndNativeVerified"] = identity;
    if (!identity || !Directory.Exists(runtime)) throw new InvalidOperationException();
    Directory.CreateDirectory(scratch);
    owned = true;
    string probe = Path.Combine(scratch, "write-probe.tmp");
    File.WriteAllText(probe, "startup-control");
    File.Delete(probe);
    result["ownedStateParentWritable"] = true;
    result["tempDirectoryExists"] = Directory.Exists(Path.GetTempPath());
    result["tempDirectoryIsFile"] = File.Exists(Path.GetTempPath());
    using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(60));
    client = new CopilotClient(new CopilotClientOptions
    {
        Mode = CopilotClientMode.Empty,
        Connection = RuntimeConnection.ForStdio(native),
        BaseDirectory = Path.Combine(scratch, "state"),
        WorkingDirectory = runtime,
        UseLoggedInUser = false,
        RequestHandler = requests,
        Environment = new Dictionary<string, string> { ["COPILOT_TELEMETRY_DISABLED"] = "true" },
    });
    result["operation"] = "native_start";
    var watch = Stopwatch.StartNew();
    await client.StartAsync(deadline.Token);
    result["nativeStartElapsedMilliseconds"] = watch.ElapsedMilliseconds;
    result["operation"] = "session.create";
    watch.Restart();
    string? invalidDirectory = null;
    if (invalidWorkingDirectory)
    {
        invalidDirectory = Path.Combine(scratch, "controlled-file-not-directory");
        File.WriteAllText(invalidDirectory, "controlled-invalid-directory");
    }
    try
    {
        await using var session = await client.CreateSessionAsync(new SessionConfig
        {
            Model = "offline-startup-control",
            Provider = new ProviderConfig { Type = "openai", WireApi = "responses",
                BaseUrl = "http://127.0.0.1:1", ApiKey = "offline-not-a-credential" },
            AvailableTools = [],
            WorkingDirectory = invalidDirectory,
            EnableManagedSettings = false,
            EnableConfigDiscovery = false,
            EnableSkills = false,
            EnableFileHooks = false,
            EnableSessionStore = false,
            EnableSessionTelemetry = false,
            EnableHostGitOperations = false,
            InteractiveUser = false,
            OnPermissionRequest = (_, _) => Task.FromResult(GitHub.Copilot.Rpc.PermissionDecision.Reject("Startup-only control")),
        }, deadline.Token);
        result["sessionCreated"] = true;
        exit = requests.Count == 0 ? 0 : 1;
    }
    finally
    {
        result["sessionCreateElapsedMilliseconds"] = watch.ElapsedMilliseconds;
    }
}
catch (Exception error)
{
    exit = 1;
    Failure(error, "failure");
}
finally
{
    if (client != null)
    {
        try { await client.DisposeAsync(); result["clientDisposed"] = true; }
        catch (Exception error) { Failure(error, "cleanupFailure"); exit = 1; }
    }
    if (owned)
    {
        try { Directory.Delete(scratch, true); result["ownedStateRemoved"] = !Directory.Exists(scratch); }
        catch (Exception error) { Failure(error, "stateCleanupFailure"); exit = 1; }
    }
    result["requestHandlerAdmissions"] = requests.Count;
    if (requests.Count != 0) exit = 1;
}
result["exitCode"] = exit;
string json = JsonSerializer.Serialize(result);
try { await File.WriteAllTextAsync(receiptPath, json + "\n"); }
catch (Exception error)
{
    exit = 1;
    result["exitCode"] = exit;
    Failure(error, "receiptWriteFailure");
    json = JsonSerializer.Serialize(result);
}
Console.WriteLine(json);
return exit;

sealed class RejectRequests : CopilotRequestHandler
{
    public int Count;
    protected override Task<HttpResponseMessage> SendRequestAsync(HttpRequestMessage request, CopilotRequestContext context)
    {
        Interlocked.Increment(ref Count);
        throw new InvalidOperationException("Startup-only control forbids request forwarding.");
    }
}
