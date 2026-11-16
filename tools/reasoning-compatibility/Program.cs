#pragma warning disable GHCP001
using System.Reflection;
using System.Runtime.Loader;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using GitHub.Copilot;
using Microsoft.BusinessCentral.BCal;
using Microsoft.BusinessCentral.BCal.Service;
using Microsoft.Dynamics.Nav.CodeAnalysis.SymbolReference;
using Microsoft.Extensions.AI;

string package = Path.GetFullPath(args[0]);
string output = Path.GetFullPath(args[4]);
AssemblyLoadContext.Default.Resolving += (_, name) =>
{
    string path = Path.Combine(package, name.Name + ".dll");
    return File.Exists(path) ? AssemblyLoadContext.Default.LoadFromAssemblyPath(path) : null;
};
await RunAsync();

async Task RunAsync()
{
    if (File.Exists(output)) throw new InvalidOperationException("Receipt already exists.");
    string model = args[1], policy = args[2], url = args[3];
    bool offline = url == "offline";
    string? effort = policy == "omitted" ? null : policy;
    if (policy is not ("omitted" or "none" or "medium")) throw new ArgumentException("Invalid effort policy.");
    var assembly = AssemblyLoadContext.Default.LoadFromAssemblyPath(Path.Combine(package, "bcal.dll"));
    if (System.Diagnostics.FileVersionInfo.GetVersionInfo(assembly.Location).ProductVersion !=
        "30.0.46.49019+52f3f7f5dd2d26c83f2778d28ace9d47364b481b")
        throw new InvalidOperationException("Package identity differs.");
    Type runtimeType = assembly.GetTypes().Single(t => t.Name == "CopilotBcalAgentSession");
    Type optionsType = assembly.GetTypes().Single(t => t.Name == "CopilotSdkOptions");
    using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(110));
    IBcalAgentSession? runtime = null;
    object options = Activator.CreateInstance(optionsType, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
        null, new object?[] { offline ? "https://offline.invalid/v1" : url + "/v1", model,
            Environment.GetEnvironmentVariable("BCAL_SDK_PROXY_KEY") ?? "offline-key", effort, 1, 100 }, null)!;
    optionsType.GetProperty("PlanningMode", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)!.SetValue(options, "copilot");
    await using IBcalService service = BcalServiceFactory.Create(new BcalSessionOptions
    {
        Endpoint = "https://unused.invalid", BcalPlanningEnabled = false,
        ReferenceLoader = ReferenceLoaderFactory.CreateReferenceLoader(Array.Empty<string>()),
        DependencyVersion = new Version(25, 0, 0, 0),
        AgentSessionFactory = context => runtime = (IBcalAgentSession)Activator.CreateInstance(runtimeType,
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, new object[] { context, options }, null)!,
    });
    SessionConfig config = (SessionConfig)runtimeType.GetMethod("CreateSessionConfig",
        BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public)!.Invoke(runtime, null)!;
    config.SystemMessage = new SystemMessageConfig { Mode = SystemMessageMode.Replace,
        Content = "This is a synthetic API compatibility test. Reply OK or call compat_echo with value OK. No other action." };
    config.Tools = new List<AIFunctionDeclaration> {
        AIFunctionFactory.Create((string value) => value, "compat_echo", "Echo a synthetic value.")
    };
    config.AvailableTools = new List<string> { "custom:compat_echo" };
    var capture = new Boundary(offline);
    using var http = new HttpClient(capture) { Timeout = TimeSpan.FromSeconds(90) };
    Set("modelHttpClient", http);
    Set("turnCancellation", deadline);
    Set("callbacksClosed", false);
    Set("terminalState", "running");
    Set("terminal", new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously));
    Type handlerType = runtimeType.GetNestedType("BcalRequests", BindingFlags.NonPublic)!;
    object handler = Activator.CreateInstance(handlerType,
        BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, new object[] { runtime! }, null)!;
    var forwarding = new ProductionRequests(handler, handlerType);
    string directory = Path.Combine(Path.GetTempPath(), "bcal-compatibility", Guid.NewGuid().ToString("N"));
    Directory.CreateDirectory(directory);
    string outcome = "not_started";
    try
    {
        await using var client = new CopilotClient(new CopilotClientOptions
        {
            Mode = CopilotClientMode.Empty, BaseDirectory = directory, WorkingDirectory = directory,
            UseLoggedInUser = false, RequestHandler = forwarding,
            Environment = new Dictionary<string, string> { ["COPILOT_TELEMETRY_DISABLED"] = "true" },
        });
        await client.StartAsync(deadline.Token);
        var native = await client.CreateSessionAsync(config, deadline.Token);
        try
        {
            await native.SendAsync(new MessageOptions { Prompt = "Return OK or echo OK using compat_echo." }, deadline.Token);
            outcome = await forwarding.Outcome.Task.WaitAsync(deadline.Token);
        }
        finally
        {
            await native.AbortAsync();
            deadline.Cancel();
        }
    }
    catch (OperationCanceledException) { outcome = "local_timeout"; }
    catch (Exception) { outcome = "local_sdk_failure"; }
    finally
    {
        using var file = new FileStream(output, FileMode.CreateNew);
        JsonSerializer.Serialize(file, new {
            requestedPolicy = policy, requestedEffort = effort,
            appliedEffort = config.ReasoningEffort,
            capabilityOverride = config.ModelCapabilities?.Supports?.ReasoningEffort,
            outcome, boundaryRequests = capture.Requests, boundaryBlocked = capture.Blocked,
            terminalState = runtimeType.GetField("terminalState", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(runtime),
            wire = capture.Wire, offline,
            scope = "Packaged native generation and production BcalRequests, synthetic config only; first response, no conversation/tool-result loop."
        });
        if (Directory.Exists(directory)) Directory.Delete(directory, true);
    }
    void Set(string name, object value) => runtimeType.GetField(name, BindingFlags.Instance | BindingFlags.NonPublic)!.SetValue(runtime, value);
}

sealed class ProductionRequests(object handler, Type type) : CopilotRequestHandler
{
    public TaskCompletionSource<string> Outcome { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    protected override async Task<HttpResponseMessage> SendRequestAsync(HttpRequestMessage request, CopilotRequestContext context)
    {
        try
        {
            var pending = (Task<HttpResponseMessage>)type.GetMethod("SendRequestAsync", BindingFlags.Instance | BindingFlags.NonPublic)!
                .Invoke(handler, new object[] { request, context })!;
            var response = await pending;
            Outcome.TrySetResult("response_received");
            return response;
        }
        catch { Outcome.TrySetResult("local_handler_rejection"); throw; }
    }
}

sealed class Boundary(bool offline) : HttpMessageHandler
{
    private readonly HttpMessageInvoker inner = new(new HttpClientHandler { AllowAutoRedirect = false });
    public int Requests;
    public int Blocked;
    public object? Wire;
    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        if (Interlocked.Increment(ref Requests) != 1)
        {
            Interlocked.Increment(ref Blocked);
            throw new HttpRequestException("Diagnostic cell admits one attempt only.");
        }
        JsonObject body = JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!.AsObject();
        var tools = body["tools"]!.AsArray();
        string[] names = tools.Select(t => (string?)t!["name"] ?? "").ToArray();
        if (names.Length != 1 || names[0] != "compat_echo")
            throw new InvalidOperationException("Synthetic tool isolation failed.");
        Wire = new {
            effortPresent = body.ContainsKey("reasoning"), reasoning = body["reasoning"]?.DeepClone(),
            tools = names, stream = body["stream"]?.DeepClone(), model = body["model"]?.DeepClone(),
            parallelToolCalls = body["parallel_tool_calls"]?.DeepClone()
        };
        if (offline)
            return new HttpResponseMessage(System.Net.HttpStatusCode.TooManyRequests) {
                RequestMessage = request,
                Content = new StringContent("{\"error\":{\"message\":\"Synthetic offline429\",\"type\":\"rate_limit_error\"}}", Encoding.UTF8, "application/json")
            };
        if (request.RequestUri!.Host != "127.0.0.1")
            throw new InvalidOperationException("Native diagnostic must use the bounded loopback.");
        return await inner.SendAsync(request, cancellationToken);
    }
    protected override void Dispose(bool disposing) { if (disposing) inner.Dispose(); base.Dispose(disposing); }
}
