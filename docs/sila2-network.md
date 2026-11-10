# CF01 SiLA 2 network implementation

The adapter provides a real TLS/gRPC transport for the existing CF01 simulator,
with the existing rack-batch runner as its first consumer and an independent
.NET client as the interoperability gate. Verification and limits are below. No
hardware, CAD, NanoDrop/Qubit network feature or historical-media change belongs
to this work.

The [SiLA/GENtle architecture](../ARCHITECTURE.md) describes a separate future
capability/resource binding. That binding is not implemented by this simulator
server. The shared CF01 → NanoDrop → Qubit workflow remains a local synthetic
workflow with durable CF01 checkpoints before effects. Its local `sila2`
decoder selection is not a network execution. The `batch` command documented
here is the separate TLS/gRPC consumer and retains its own durable client
intents and handoff checkpoints.

## Sources and reproducibility

- `model/cf01-sila2.shared.json` references the existing CF01 protocol, station and batch fixture
  with SHA-256 pins. It defines the separate network Feature version 2.0 against
  SiLA 2 specification 1.1. The local v1 and ROS interfaces remain supported.
- `scripts/build_cf01_sila2.py` reuses the existing command/state definitions and
  adds command-specific errors, generated bounds/units and request metadata.
  Slot capacity and conceptual RCF bounds are references, not copied geometry.
  State-dependent qualifications still belong to the core and are not implied
  by a syntactic upper bound. RCF is dimensionless; `g` for tube mass is grams.
- Official standard FDLs are archived unchanged in `interfaces/sila2/standard/`
  with upstream revision, hashes and MIT license. `CancelController` belongs to
  category `core.commands`, not `core`. `SiLAService` is supplied by the selected
  SDK, while its official definition is retained for comparison.
- Runtime uses `unitelabs-sila==0.14.0`. The older `sila2==0.14.0` package is an
  optional independent test client, not the production server dependency.
  Exact production packages and hashes are in `requirements/sila2.lock`.

SDK research sources: [UniteLabs library](https://gitlab.com/unitelabs/sila2/sila-python),
[legacy SDK status](https://sila2.gitlab.io/sila_python/),
[Tecan .NET SDK](https://gitlab.com/SiLA2/vendors/sila_tecan),
[official definitions](https://gitlab.com/SiLA2/sila_base).

The installed UniteLabs API supplies `SiLAService` by default but defaults to
plaintext. This adapter explicitly enables TLS; it never offers an insecure
mode. Certificate/key pairing, validity and server UUID are checked on startup.
The private key, credentials and station database stay under ignored `exports/`.
Passwords are PBKDF2 hashes; returned access tokens are short-lived and retained
only as hashes in memory. Tokens expire against monotonic wall time, even when a
unit test injects a manual process clock. Neither passwords nor tokens are CLI
arguments or ordinary log output.

## Ownership, time and recovery

`LockController.LockIdentifier` is metadata. Its lease is separate from the
core's boot-scoped process ownership and watchdog. A standard lease expiry or
unsafe unlock requests controlled stopping and leaves process reconciliation
latched. It does not free uncertain vessels or robot responsibility.

`RequestIdentifier` is a UUID identifying one state-changing CF01 intent. The
station journal commits that intent before executing its effect. Reusing an ID
is rejected without repeating the command, including after restart. Result and
checkpoint updates are atomic. A dedicated SQLite exclusive transaction fences
the entire server process, independently of ordinary station writes; a stale
PID or expired timer cannot steal a live server's store.
The journal retains canonical command arguments as well as their fingerprint,
principal, boot and execution receipt. Pending argument corruption is rejected.
Its explicit schema is `solidcraftbot.cf01-intents/1`; older development stores
require an explicit migration or a separate new store. They are never silently
upgraded, cleared or rebound to the current source signature.

The default process clock is elapsed `time.monotonic()` at rate 1.0. The server
ticker progresses the simulator independently of client polling. RPC and
execution deadlines use monotonic wall time. An injected manual clock is only a
Python test dependency; there is no network command to advance the clock.

`CancelController` accepts a controlled-stop request. The original observable
command remains active through braking, then finishes with the defined
`CommandCanceled` error after confirmed standstill and held brake. Stop receipt
is never a standstill measurement or an emergency-stop function.

No unfinished job is replayed after process restart. Server UUID persists; boot
UUID changes. Old execution UUIDs are not silently rebound to fresh jobs. The
last recorded station state is not a new physical observation. A complete local
`synthetic_person_confirmation`, targeting the recorded server and boot, is
required to reconcile uncertain requests and observed rotor contents. Missing
slots, missing acknowledgements or nonpositive safe-state confirmations fail.
Original unknown execution outcomes remain recorded as unknown, even after this
explicit synthetic observation. A live server's store cannot be reconciled.

The batch runner receives a station boundary instead of constructing a second
simulator. Its existing sample ledger and handoff checkpoints remain authoritative.
`RotorSlots` is a typed projection of the one server simulator, with explicit
mass validity. The separate `SyntheticRobotObservation` feature records indexed
loading/removal access and matching withdrawal, including boot, actor, sample,
slot and observation UUID. Station motion remains blocked until withdrawal.
These are synthetic assertions, not native robot trajectories, scans or sensor
overrides. There is no network clock-control command.

The client writes and fsyncs each intent before transmission and preserves the
execution UUID receipt and runner checkpoints in a new exclusive JSONL journal.
It never retries an uncertain effect or resumes an old batch automatically.
After a partial handoff or connection loss, retain both journals and reconcile
the station and the runner's pending sample responsibility explicitly. Station
reconciliation alone does not close or reconstruct the client sample ledger.

## Deutsch: Bedienung und Grenzen

Abhängigkeiten in einer eigenen Python-Umgebung installieren:

```sh
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python --require-hashes -r requirements/sila2.lock
.venv/bin/python scripts/build_cf01_sila2.py
.venv/bin/python scripts/run_cf01_sila2.py --language de --help
```

`init` benötigt eine private JSON-Datei mit einer Liste aus `username`,
`password` und `role` (`operator` oder `observer`). Es gibt keine eingebauten
Standardzugangsdaten. Die Eingabedatei enthält Geheimnisse und gehört ebenfalls
unter `exports/` mit eingeschränkten Dateirechten.

```sh
.venv/bin/python scripts/run_cf01_sila2.py init \
  --credentials-input exports/cf01-sila2/users-input.json \
  --credentials exports/cf01-sila2/users.json \
  --store exports/cf01-sila2/station.sqlite3
.venv/bin/python scripts/run_cf01_sila2.py serve \
  --credentials exports/cf01-sila2/users.json \
  --store exports/cf01-sila2/station.sqlite3 \
  --tls-directory exports/cf01-sila2/tls \
  --ready-file exports/cf01-sila2/ready.json
```

Der Standard bindet nur `127.0.0.1` und wählt einen freien Port. Die Bereitschafts-
datei enthält den tatsächlich gebundenen Port und den öffentlichen Zertifikatspfad.
Ein vorhandenes Bereitschaftsartefakt wird nicht überschrieben. `--discovery`
aktiviert mDNS/DNS-SD; sein Nachweis ist ein eigener Netzwerkprüfschritt.
`--bind` und `--port` konfigurieren die Bindung ausdrücklich. Zertifikatsvertrauen
muss im Client explizit eingerichtet werden; es gibt keinen Abschalter für TLS.

Nach einem Abbruch: `inspect --store ...` zeigt den gespeicherten Prüfpunkt,
keinen aktuellen Gerätebefund. `reconcile --store ... --observation ...` nimmt
eine vollständige synthetische Personenbestätigung entgegen. Diese Funktionen
setzen voraus, dass kein Server denselben Store geöffnet hält.

Der vollständige Netzwerk-Chargenlauf verwendet eine private JSON-Datei mit
`username` und `password` eines Operators. Journal und Bericht müssen neue Pfade
unter `exports/` sein. Ein alter oder unklarer Lauf wird nicht wiederholt:

```sh
.venv/bin/python scripts/run_cf01_sila2.py --language de batch \
  --ready-file exports/cf01-sila2/ready.json \
  --login-input exports/cf01-sila2/operator-login.json \
  --journal exports/cf01-sila2/batch-001.jsonl \
  --out exports/cf01-sila2/batch-001.json
```

Der Lauf erhält dieselben zwölf Proben-IDs und ursprünglichen Rackplätze.
Bei unvollständiger Übergabe bleibt deren Verantwortung offen; aus einer
Stoppquittung folgt keine Rückgabe. Die synthetischen Roboterbeobachtungen
verifizieren weder eine Ladebahn noch reale Identität oder Sensorik.

## English: operation and boundaries

Use `--language en --help` for English CLI descriptions. Initialize named
operator/observer users from a private input file, start `serve` with a dedicated
store/TLS directory, and explicitly trust the emitted public certificate in the
client. Only a simulated station is available. `StartRealMode` always fails.
`inspect` reads a stored checkpoint, not live instrument state. Recovery requires
a complete explicitly acknowledged synthetic observation; it never restarts an
old command automatically. FDL descriptions remain English and wire identifiers
do not change with the operator language.

Run `--language en batch` with `--ready-file`, a private `--login-input`
(`username`/`password`), a new `--journal` and a new `--out` path under `exports/`.
It runs the same twelve-sample round trip over TLS while preserving original
rack places and identities. Retain incomplete handoffs as unresolved. A stop
receipt does not return a sample, and synthetic observations do not verify
physical identity, robot motion or sensor feedback.

## Verification gates

Verified so far:

- CF01 v2 FDL passes the packaged official XSD and SDK parser.
- Source pins, command-specific errors and source-derived bounds/units are tested.
- The SDK prerequisite probe exercised actual TLS/SiLAService with clients from
  two Python implementations. This is not the .NET acceptance test.
- Store/runtime tests cover duplicate intents, process fencing, atomic completion,
  checksum corruption, restart, explicit reconciliation, owner timeout and braking.
- Basic CF01 TLS/gRPC tests cover discovery through SiLAService, typed completion,
  observer/operator access, invalid bounds, real-mode refusal and duplicate calls.
- Real network spin and cancellation tests confirm server-side clock progression
  and completion only after braking, standstill and held brake.
- The independent Tecan .NET client has passed TLS certificate/UUID checks,
  live feature discovery, authentication, standard lock metadata and observable
  rotor indexing, duplicate-intent rejection, real-mode refusal, normal spin
  completion and cancellation through braking. Cancellation completes the
  original command with `CommandCanceled`, after standstill and held brake.
  The same runner also completes the full twelve-sample round trip through the
  Tecan client, which performs every station RPC with its own SiLA implementation.
- The rotor-slot projection is a fresh, typed observation of the existing core;
  it carries explicit mass validity and no sample identity ledger.
- Wrong certificate trust and plaintext connections are rejected by the TLS
  endpoint. A client execution deadline leaves the same durable request pending,
  without redispatch; explicit cancellation can then observe the final error.
- Both Python and Tecan transports complete the original rack-batch runner with
  no local simulator, preserved identities/order and an empty released station.
- A partially confirmed network handoff retains the pending ledger responsibility,
  simulated workspace occupancy and station ownership.
- Actual CLI processes cover initialization, live-store fencing, network batch,
  forced termination, persistent UUID/certificate, changed boot, stale execution
  rejection, no replay and explicit local reconciliation.
- A TCP proxy drops actual TLS responses after command dispatch: one durable
  request and one spin remain, then cancellation reaches its terminal error.
- Actual channel loss and lease expiry trigger braking and retain process
  responsibility even after the standard lock expires.
- mDNS/DNS-SD discovery is exercised on IPv4 loopback, followed by a TLS connection
  with independently configured certificate trust. LAN interfaces are not qualified.
- Startup rejects expired/future certificates, wrong UUID, incomplete identities
  and mismatched keys; clients reject wrong trust, wrong hostname and plaintext.
- Role/scope, idle expiry and revocation are tested independently of process time.

Final verification on 2026-11-09:

- Full project run: 456 tests, 22 skipped for unavailable optional environments,
  no failures. After the final journal and pipe changes, the complete dedicated
  SiLA suite was run again: 47 tests, no skips or failures.
- A fresh environment installed `requirements/sila2.lock` with required hashes
  and passed CLI initialization, live-store fencing and the complete TLS batch.
  The legacy Python SDK is absent from that production environment.
- All 94 tracked historical media/model-gallery, fixture, vendor and provenance
  files checked against baseline `ec04655` remain byte-identical.
- Local evidence and source hashes are retained in
  `exports/generated/cf01-sila2/acceptance-report.json` and its referenced logs.
  These results establish bounded simulator interoperability; they are not
  formal SiLA certification, LAN qualification or hardware safety evidence.

## Rebase verification on 2026-11-10

The original SiLA commit was rebased without conflict onto master `7b7f581` as
`0bb3874`. The earlier acceptance results above describe the pre-rebase source
revision and must not be used as proof that this rebased composition passes.
The documentation alignment does not change server behavior, model pins or the
architecture's proposed LockController version.

Two integration findings remain explicit:

- `network_batch.source_sha256` still pins `e3c40b6ca0636968b56b230b67ed2bce4670749ef9e884bdf8fe72133a2cf7d0`,
  while the current shared batch source is
  `da39b92cda9293858de7c5e7c096ce5ea1a6bd2a59743cf3b478f9a00e844681`.
  Contract loading rejects the mismatch before server startup. Tests failing
  there do not prove network, process-recovery or .NET interoperability on this
  rebased stand. This rebase/documentation task leaves the model pin unchanged;
  any subsequent update must preserve the source binding of existing journals.
- `render_model_gallery.py --check` currently treats
  `model/cf01-sila2.shared.json` as a model source requiring an image and rejects
  its missing gallery coverage. It is a transport profile. No image, catalog or
  historical provenance was added or rewritten to conceal this failure.

The offline and network/.NET-enabled project runs, per-file SiLA results with
skip reasons, gallery check and shared-workflow demo are recorded locally in
`exports/generated/sila-rebase-7b7f581/verification-report.json` and its logs.
Skipped checks and failures before transport startup are not passed network
acceptance gates.

Commands for the current checks:

```sh
uv pip install --python .venv/bin/python -r requirements/sila2-test.in
.venv/bin/python -m unittest discover -s tests -p 'test_cf01_sila2*.py' -v
SOLIDCRAFTBOT_SILA_NETWORK_TESTS=1 .venv/bin/python -m unittest discover \
  -s tests -p test_cf01_sila2_network.py -v
.venv/bin/python scripts/probe_sila2_sdk.py \
  --out exports/generated/cf01-sila2/sdk-probe.json
```

Network tests bind real local sockets. Offline tests do not turn a local mock
dispatch into a network result. No CAD rebuild is required for this transport
work, and no native geometry or hardware qualification is claimed.

## Independent .NET client

The probe uses the official Tecan source at revision
`adf5dbadfdfdf033956657cd278566ede75a746f`, checked out under
`exports/research/sila-tecan`. It was built with local .NET SDK 10.0.403. Restore
requires NuGet access. Use absolute paths for `DOTNET_CLI_HOME` and
`NUGET_PACKAGES`, both inside ignored `exports/tools/`.

Create the upstream checkout once, then select the pinned revision:

```sh
git clone https://gitlab.com/SiLA2/vendors/sila_tecan.git exports/research/sila-tecan
git -C exports/research/sila-tecan checkout adf5dbadfdfdf033956657cd278566ede75a746f
```

```sh
.venv/bin/python scripts/build_cf01_sila2_dotnet.py
SOLIDCRAFTBOT_SILA_DOTNET_TESTS=1 .venv/bin/python -m unittest discover \
  -s tests -p test_cf01_sila2_dotnet.py -v
```

The probe supplies its own certificate-pinned HTTPS channel. It bypasses the
SDK connection helper's permissive certificate callback and plaintext fallback.
No private credentials are passed in command arguments. The upstream build
currently emits obsolete API and package warnings; its sources are unchanged.
The Tecan dynamic decoder leaves omitted protobuf scalar defaults as `null`.
The probe interprets Boolean defaults accordingly, including false standstill
while braking; it does not treat a cancellation receipt as completed execution.
The build wrapper rejects a different or modified tracked upstream revision and
records the SDK, client source hashes and assembly hash. The network test checks
this report so that an old binary cannot stand in for changed client source.
The test-only JSON pipe bridge sends calls from the existing Python batch runner
to the Tecan process. It is not a second sample ledger or a second SiLA encoder.
The Tecan process independently discovers features, serializes network requests,
tracks observable executions and subscribes to status.
Pipe replies carry a call UUID. A missing, malformed or mismatched reply blocks
further effects on that pipe, so a delayed reply cannot masquerade as a stop
receipt. The original intent remains uncertain and station ownership is retained.
