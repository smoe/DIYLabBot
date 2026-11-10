using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text.Json;
using Grpc.Net.Client;
using Tecan.Sila2;
using Tecan.Sila2.Client;
using Tecan.Sila2.Client.ExecutionManagement;
using Tecan.Sila2.Discovery;
using Tecan.Sila2.DynamicClient;
using Tecan.Sila2.Security;

// Independent Tecan serialization and execution tracking. No Python client or
// hand-written wire encoding is used. Read secrets from a private file, not argv.
var bridgeMode = args.Length > 0 && args[0] == "--bridge";
if (bridgeMode) args = args[1..];
if (args.Length != 3) throw new ArgumentException("ready.json login.json result.json required");
using var ready = JsonDocument.Parse(File.ReadAllText(args[0]));
using var login = JsonDocument.Parse(File.ReadAllText(args[1]));
var config = ready.RootElement;
var expectedUuid = Guid.Parse(config.GetProperty("server_uuid").GetString());
using var pinned = X509Certificate2.CreateFromPem(File.ReadAllText(config.GetProperty("certificate").GetString()));
using var http = new HttpClientHandler
{
    ServerCertificateCustomValidationCallback = (_, certificate, _, errors) =>
        certificate != null && (errors & SslPolicyErrors.RemoteCertificateNameMismatch) == 0 &&
        CryptographicOperations.FixedTimeEquals(certificate.RawData, pinned.RawData) &&
        certificate.NotBefore.ToUniversalTime() <= DateTime.UtcNow && DateTime.UtcNow < certificate.NotAfter.ToUniversalTime()
};
using var channel = GrpcChannel.ForAddress($"https://127.0.0.1:{config.GetProperty("port").GetInt32()}",
                                         new GrpcChannelOptions { HttpHandler = http });
// GetServerData uses this already pinned HTTPS channel directly. Deliberately
// bypass the SDK Connect helper, which can fall back to plaintext on failure.
var server = new ServerConnector(new DiscoveryExecutionManager()).GetServerData(channel);
if (server.Config.Uuid != expectedUuid || !CertificateUtilities.TryFindServerUuid(pinned, out var certUuid) || certUuid != expectedUuid)
    throw new InvalidOperationException("SiLA server UUID/certificate mismatch");
var manager = new ExecutionManagerFactory(Array.Empty<IClientRequestInterceptor>()).CreateExecutionManager(server);

FeatureContext Context(string feature) => new FeatureContext(server.Features.Single(f => f.Identifier == feature), server, manager);
DynamicRequest Request(CommandClient client, FeatureCommand definition, IDictionary<string, object> parameters)
{
    var request = client.CreateRequest();
    var value = new DynamicObject();
    foreach (var parameter in definition.Parameter ?? Array.Empty<SiLAElement>())
        value.Elements.Add(new DynamicObjectProperty(parameter) { Value = parameters[parameter.Identifier] });
    request.Value = value;
    return request;
}
DynamicObjectProperty Call(string feature, string command, IDictionary<string, object> parameters,
                           IDictionary<string, byte[]> metadata = null)
{
    var context = Context(feature);
    var definition = context.Feature.Items.OfType<FeatureCommand>().Single(c => c.Identifier == command);
    var client = new NonObservableCommandClient(definition, context);
    return client.Invoke(Request(client, definition, parameters), metadata);
}
object Field(DynamicObjectProperty response, string name) => ((DynamicObject)response.Value).Elements.Single(e => e.Identifier == name).Value;
byte[] Metadatum(string value) => ByteSerializer.ToByteArray(new PropertyResponse<StringDto>(value));

var authenticated = Call("AuthenticationService", "Login", new Dictionary<string, object>
{
    ["UserIdentification"] = login.RootElement.GetProperty("username").GetString(),
    ["Password"] = login.RootElement.GetProperty("password").GetString(),
    ["RequestedServer"] = expectedUuid.ToString(), ["RequestedFeatures"] = Array.Empty<string>()
});
var auth = new Dictionary<string, byte[]>
{
    ["org.silastandard/core/AuthorizationService/v1/Metadata/AccessToken"] = Metadatum((string)Field(authenticated, "AccessToken"))
};
var lockId = "";
var metadata = new Dictionary<string, byte[]>(auth)
{
    ["org.silastandard/core/LockController/v1/Metadata/LockIdentifier"] = Metadatum(lockId),
    ["org.solidcraftbot/centrifugation/CentrifugeControl/v2/Metadata/RequestIdentifier"] = Metadatum(Guid.NewGuid().ToString())
};
var cf = Context("CentrifugeControl");
Dictionary<string, byte[]> FreshIntent() => new Dictionary<string, byte[]>(metadata)
{
    ["org.solidcraftbot/centrifugation/CentrifugeControl/v2/Metadata/RequestIdentifier"] = Metadatum(Guid.NewGuid().ToString())
};
DynamicIntermediateCommand Submit(string name, IDictionary<string, object> parameters,
                                  IDictionary<string, byte[]> headers = null)
{
    var definition = cf.Feature.Items.OfType<FeatureCommand>().Single(c => c.Identifier == name);
    var client = new IntermediateObservableCommandClient(definition, cf);
    var command = (DynamicIntermediateCommand)client.Invoke(Request(client, definition, parameters), headers ?? FreshIntent());
    command.Start();
    return command;
}
var deadline = TimeSpan.FromSeconds(config.GetProperty("braking_s").GetDouble() + 5);
async Task<DynamicObjectProperty> Observe(string name, IDictionary<string, object> parameters) =>
    await Submit(name, parameters).Response.WaitAsync(deadline);
DynamicObject StationState() => (DynamicObject)Field(Call("CentrifugeControl", "GetStatus", new Dictionary<string, object>(), metadata), "State");
object Value(DynamicObject value, string name) => value.Elements.Single(e => e.Identifier == name).Value;
// Tecan's dynamic decoder represents omitted protobuf scalar defaults as null.
// Boolean false is a valid default, including while the rotor is still moving.
bool Boolean(DynamicObject value, string name) => Convert.ToBoolean(Value(value, name));

object Native(object value, DataTypeType type = null)
{
    if (value is DynamicObject structure)
        return structure.Elements.ToDictionary(e => e.Identifier, e => Native(e.Value, e.Type));
    if (value is DynamicObjectProperty property) return Native(property.Value, property.Type);
    if (value is System.Collections.IEnumerable values && value is not string)
        return values.Cast<object>().Select(item => Native(item)).ToArray();
    if (value != null) return value;
    if (type?.Item is ConstrainedType constrained) return Native(null, constrained.DataType);
    if (type?.Item is ListType) return Array.Empty<object>();
    if (type?.Item is BasicType basic) return basic switch
    {
        BasicType.Boolean => false, BasicType.Integer => 0L, BasicType.Real => 0.0,
        BasicType.String => "", _ => throw new InvalidOperationException("Unsupported scalar default")
    };
    throw new InvalidOperationException("Missing structured response");
}
Dictionary<string, object> Parameters(JsonElement message) => message.GetProperty("parameters").EnumerateObject()
    .ToDictionary(p => p.Name, p => p.Value.ValueKind switch
    {
        JsonValueKind.String => (object)p.Value.GetString(),
        JsonValueKind.True => true, JsonValueKind.False => false,
        JsonValueKind.Number => p.Name == "Slot" ? (object)p.Value.GetInt64() : p.Value.GetDouble(),
        _ => throw new ArgumentException("Unsupported typed parameter")
    });
var statusProperty = cf.Feature.Items.OfType<FeatureProperty>().Single(p => p.Identifier == "Status");
var subscribedStatus = (DynamicObject)new PropertyClient(statusProperty, cf).RequestValue(auth).Value;
if (!Boolean(subscribedStatus, "SimulationOnly"))
    throw new InvalidOperationException("Status subscription did not identify a synthetic station");
if (bridgeMode)
{
    // Only JSON pipe framing is shared with the Python batch runner. Tecan
    // independently discovers, serializes and executes every SiLA network call.
    var jobs = new Dictionary<string, (DynamicIntermediateCommand Execution, string Command)>();
    Console.WriteLine(JsonSerializer.Serialize(new { ok = true, server_uuid = expectedUuid, state = Native(StationState()) }));
    while (await Console.In.ReadLineAsync() is string line)
    {
        using var document = JsonDocument.Parse(line);
        var message = document.RootElement;
        var action = message.GetProperty("action").GetString();
        if (action == "close") break; // Never implicitly unlock an unresolved run.
        var callId = message.GetProperty("call_id").GetString();
        try
        {
            object response;
            if (action == "state") response = new { state = Native(StationState()) };
            else if (action == "lock")
            {
                lockId = message.GetProperty("lock_id").GetString();
                Call("LockController", "LockServer", new Dictionary<string, object>
                     { ["LockIdentifier"] = lockId, ["Timeout"] = message.GetProperty("timeout_s").GetInt64() }, auth);
                metadata["org.silastandard/core/LockController/v1/Metadata/LockIdentifier"] = Metadatum(lockId);
                response = new { state = Native(StationState()) };
            }
            else if (action == "unlock")
            {
                Call("LockController", "UnlockServer", new Dictionary<string, object> { ["LockIdentifier"] = lockId }, auth);
                lockId = "";
                metadata["org.silastandard/core/LockController/v1/Metadata/LockIdentifier"] = Metadatum("");
                response = new { state = Native(StationState()) };
            }
            else if (action == "observe_robot")
            {
                Call("SyntheticRobotObservation", "ObserveRobotAccess", Parameters(message), metadata);
                response = new { state = Native(StationState()) };
            }
            else if (action == "submit")
            {
                var name = message.GetProperty("name").GetString();
                var definition = cf.Feature.Items.OfType<FeatureCommand>().Single(c => c.Identifier == name);
                var headers = new Dictionary<string, byte[]>(metadata)
                {
                    ["org.solidcraftbot/centrifugation/CentrifugeControl/v2/Metadata/RequestIdentifier"] = Metadatum(message.GetProperty("request_id").GetString())
                };
                if (definition.Observable == FeatureCommandObservable.Yes)
                {
                    var job = Submit(name, Parameters(message), headers);
                    jobs.Add(job.CommandId.CommandId, (job, name));
                    response = new { execution_uuid = job.CommandId.CommandId };
                }
                else response = new { state = Native(Field(Call("CentrifugeControl", name, Parameters(message), headers), "State")) };
            }
            else if (action == "poll")
            {
                var job = jobs[message.GetProperty("execution_uuid").GetString()];
                var current = StationState();
                if (!job.Execution.Response.IsCompleted)
                    response = new { phase = (string)Value(current, "RunPhase") == "braking" ? "braking" : "running", state = Native(current), error_code = "" };
                else
                {
                    try
                    {
                        var polledResponse = await job.Execution.Response;
                        response = new { phase = "succeeded", state = Native(Field(polledResponse, "State")), error_code = "" };
                    }
                    catch (DefinedErrorException error)
                    {
                        var code = error.ErrorIdentifier.Split('/').Last();
                        response = new { phase = code == "CommandCanceled" ? "canceled" : "failed", state = Native(current), error_code = code };
                    }
                }
            }
            else throw new ArgumentException("Unknown bridge action");
            Console.WriteLine(JsonSerializer.Serialize(new { ok = true, call_id = callId, response }));
        }
        catch (Exception error)
        {
            var code = error is DefinedErrorException defined ? defined.ErrorIdentifier.Split('/').Last() : error.GetType().Name;
            Console.WriteLine(JsonSerializer.Serialize(new { ok = false, call_id = callId, error_code = code }));
        }
    }
    return;
}
lockId = Guid.NewGuid().ToString();
Call("LockController", "LockServer", new Dictionary<string, object> { ["LockIdentifier"] = lockId, ["Timeout"] = 30L }, auth);
metadata["org.silastandard/core/LockController/v1/Metadata/LockIdentifier"] = Metadatum(lockId);
var indexDefinition = cf.Feature.Items.OfType<FeatureCommand>().Single(c => c.Identifier == "IndexRotor");
var index = new IntermediateObservableCommandClient(indexDefinition, cf);
var execution = index.Invoke(Request(index, indexDefinition, new Dictionary<string, object> { ["Slot"] = 1L }), metadata);
execution.Start();
var completed = await execution.Response.WaitAsync(TimeSpan.FromSeconds(10));
var state = (DynamicObject)Field(completed, "State");
object StateField(string name) => state.Elements.Single(e => e.Identifier == name).Value;
if (Convert.ToInt64(StateField("IndexedSlot")) != 1 || !(bool)StateField("IndexConfirmed") || !(bool)StateField("SimulationOnly"))
    throw new InvalidOperationException("CF01 response did not confirm simulated index completion");
// The same durable intent must not index a second slot, including when the
// independent client receives the failure through an observable response.
try
{
    await Submit("IndexRotor", new Dictionary<string, object> { ["Slot"] = 2L }, metadata).Response.WaitAsync(deadline);
    throw new InvalidOperationException("Duplicate intent was accepted");
}
catch (DefinedErrorException error) when (error.ErrorIdentifier.EndsWith("/DuplicateRequest")) { }
if (Convert.ToInt64(Value(StationState(), "IndexedSlot")) != 1)
    throw new InvalidOperationException("Duplicate intent repeated an effect");
try
{
    Call("SimulationController", "StartRealMode", new Dictionary<string, object>(), auth);
    throw new InvalidOperationException("Real mode was accepted");
}
catch (DefinedErrorException error) when (error.ErrorIdentifier.EndsWith("/StartRealModeFailed")) { }
var empty = new Dictionary<string, object>();
var capacity = config.GetProperty("capacity").GetInt32();
for (long slot = 1; slot <= capacity; slot++)
{
    await Observe("CloseLid", empty);
    await Observe("IndexRotor", new Dictionary<string, object> { ["Slot"] = slot });
    await Observe("OpenLid", empty);
    Call("CentrifugeControl", "ConfirmSeated", new Dictionary<string, object>
         { ["MassG"] = 2.0, ["SeatedConfirmed"] = true, ["CapClosedConfirmed"] = true }, FreshIntent());
}
await Observe("CloseLid", empty);
var spun = await Observe("RunCentrifuge", new Dictionary<string, object> { ["RcfXG"] = 100.0, ["DurationS"] = .3 });
var spinState = (DynamicObject)Field(spun, "State");
if (!Boolean(spinState, "StandstillConfirmed") || !Boolean(spinState, "ParkingBrakeHeld"))
    throw new InvalidOperationException("Spin completed without confirmed standstill/brake");
var running = Submit("RunCentrifuge", new Dictionary<string, object> { ["RcfXG"] = 100.0, ["DurationS"] = 5.0 });
await Task.Delay(150);
Call("CancelController", "CancelCommand", new Dictionary<string, object>
     { ["CommandExecutionUUID"] = running.CommandId.CommandId }, auth);
if (Boolean(StationState(), "StandstillConfirmed"))
    throw new InvalidOperationException("Cancellation receipt incorrectly implied standstill");
try
{
    await running.Response.WaitAsync(deadline);
    throw new InvalidOperationException("Canceled command reported success");
}
catch (DefinedErrorException error) when (error.ErrorIdentifier.EndsWith("/CommandCanceled")) { }
var stopped = StationState();
if (!Boolean(stopped, "StandstillConfirmed") || !Boolean(stopped, "ParkingBrakeHeld"))
    throw new InvalidOperationException("Canceled command finished before standstill/brake");
Call("LockController", "UnlockServer", new Dictionary<string, object> { ["LockIdentifier"] = lockId }, auth);
var result = new { passed = true, tls = true, sdk = "Tecan.Sila2", server_uuid = expectedUuid,
                   feature_discovery = true, authentication = true, lock_metadata = true,
                   observable_completion = true, indexed_slot = 1,
                   duplicate_rejected = true, real_mode_rejected = true, spin_completed = true,
                   full_batch = false, cancellation_tested = true, status_subscription = true };
File.WriteAllText(args[2], JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }));
Console.WriteLine(JsonSerializer.Serialize(result));
