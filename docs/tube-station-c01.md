# Cooled tube lid station — C01 draft

Prepared 28 October 2026. This is a mechanical outline and an interaction contract
for discussion. It is not a fabrication release, a running SiLA server or a claim
of compatibility with a particular tube article.

## Mechanical outline

One tube remains in a fixed, cooled nest during opening, pipetting and closing.
The first concept uses local motors for the lid fingers and a local retainer
actuator. A robot-operated lever could use the same interaction sequence later;
its actuation and clearance logic would need a separate review.

![C01 in the pipetting pose with raised UMR lettering](../cad/generated/tube-station-c01-2d9bb38563f8/pipetting-umr.png)

| Item | C01 proposal |
|---|---|
| Base footprint | 200 × 160 mm; allow approximately 130 mm equipment height plus robot approach space |
| Ice reservoir | Removable 160 × 120 × 52 mm outer envelope, below the working mechanism |
| Cold insert | 36 × 36 × 48 mm metal envelope with a nominal 12 mm reference bore |
| Tube position | Centre X=0 mm, Y=0 mm; mouth reference Z=100 mm above base underside |
| Opening finger | Orange; engages the external tab and lifts the lid |
| Closing finger | Green; returns the lid and applies a compliant, limited closing force |
| Retainer | Amber envelopes; must resist uplift and rotation without crushing the tube |
| Lid guide | Magenta envelope beside the parked lid; contact and retention detail remains open |
| Drives and control | Dark envelopes; no motor, gearbox, bearing or controller has been selected |
| Cooling | Ordinary water ice and meltwater in an insulated removable reservoir; no active setpoint |
| Identification | Raised dark-blue UMR on the front reservoir wall; same outlines, 24 mm height and 0.8 mm relief as the robot |

The station frame fixes the insert and finger pivots. Melting ice must not move
the tube. Crossbars support the cold insert independently of the reservoir;
the insert extends into the cooling bath. Provide a controlled meltwater level,
condensate collection and a removable wet assembly for cleaning. The drawn
reservoir is a space envelope: insulation, drain, level sensing and seals are
not detailed.

The reference tube is a hollow cylindrical stand-in for a 1.5 mL snap-cap tube,
not an Eppendorf drawing or a dimensional fit. Retainer jaws, collar capture,
couplings, external-tab contact surfaces and the open-lid catch remain to be
designed from real articles. The 0.5 mL and 2.0 mL entries in the source are future
insert concepts only. No profile is experimentally qualified.

Coordinates are X lateral, +Y toward the hinge/rear, +Z up. The illustrative
finger axis runs along +X through [0, 7, 101] mm. Angles use degrees relative to
the drawn closed reference; negative angles lift and park toward the rear.

| Visualization joint | Pipetting pose | Illustrative limits |
|---|---:|---:|
| Opener | −135° | −140° to 0° |
| Closer | −145° | −150° to +3° |
| ReferenceLid | −115° | −130° to 0° |

The lid has an independent visualization joint. It is not mechanically coupled
to the fingers by a contact simulation. The closed reference is all three joints
at 0°; it is not a verified latch position or closing-force command. The slight
positive closer allowance is a concept range, not permission to overload a cap.

![Detail of parked fingers and accessible tube mouth](../cad/tube-station-c01/mechanism-detail.png)

Fixed-group construction bodies overlap where mounts, housings or sensor
envelopes meet. Finger parts also overlap within their respective rigid groups.
Those intersections represent concept construction, not manufactured fits.
The robot, pipette, optical camera and their swept volumes are not in this model.

## Loading review: C01 does not establish automatic tube handling

The original outline assumed that a separate tube-body gripper would lower a
closed, oriented tube vertically into the nest. That assumption was not worked
through with an actual gripper. The reference geometry leaves only 4 mm of body
between the insert top at Z=94 mm and the collar underside at Z=98 mm. At the
retainer sides the nominal space between the 11 mm tube and each retainer
envelope is only 1.5 mm. The retainer also extends to Z=102 mm. These are model
dimensions, not a verified gripper clearance or a fit for a real tube article.

No gripper or insertion/removal trajectory is modeled. The existing interference
snapshots start with the tube already in position. They do not demonstrate that
a robot can put it there, release its grip, regrasp it or remove it. C01 must not
be presented as ready for automatic tube loading.

The proposed correction is a removable, article-specific metal carrier with
larger, accessible gripping features:

1. Load a closed tube into the carrier outside the lid mechanism. Locate its
   height and hinge orientation and positively retain it. For the first
   prototype an operator can perform this step.
2. Dock the complete carrier into a keyed, cooled station seat. A future handling
   gripper would grasp dry carrier features away from the tube and lid. The
   station must support cap forces through its frame and secure both carrier
   and tube before the handling gripper withdraws.
3. Open, pipette and close while the carrier remains docked and cooled.
4. After verified closure and release of the station lock, remove the complete
   carrier. Keep the tube retained in the carrier during transport.

This proposal requires a new dock and retainer; it is not a drop-in addition to
the drawn 12 mm bore. A front-accessible dock or loading shuttle is a candidate
to keep transfer clear of the lid mechanism, but neither is modeled or selected.
Carrier-to-cooling-seat thermal contact and the actual grip, docking, clearance
and removal motions need verification. Fully automatic transfer of loose tubes
from a source rack into carriers remains a separate handling task.

The separate [H01 carrier and handoff dock](tube-carrier-h01.md) now illustrates
this proposal for conical 1.5 mL and rounded 2.0 mL tube references, using common
external handling features and independent native generators for both CADs.
H01's front-slide samples do not establish a path through C01's lid mechanism.
The C01 geometry and its SiLA FDL have not been revised by that demonstration.

The existing `BeginAccess(Loading)` contract expresses intended motion inhibition,
not proof of a usable loading route. A carrier revision must additionally verify
the selected transfer configuration, open station lock, carrier seating and
retention before enabling lid motion. Precise sensor fields and any interface
changes follow the mechanical choice; the current FDL is unchanged.

## Cooling and measurement

Keep the tube in its insert for the whole cycle, with mouth, hinge and tab above
the wet area. Start with an angled camera view through the mouth; a side opening
in the insert would reduce thermal contact. Condensation may obscure the tube or
resemble a droplet and must be considered during optical validation.

Choose the permitted sample-temperature interval, sample volumes, soak time and
working duration before testing. A block sensor is proposed, but a block reading
alone does not establish sample temperature. This is particularly relevant to the
1 µL droplet near the upper wall. Characterize that location with a suitable
reference method and stated uncertainty. Ice replenishment and stale or failed
temperature readings must make cooling readiness false when necessary.

`CoolingReady` is a process permission based on a qualified thermal profile and
valid monitoring. It is not a temperature setpoint, nor a sample-temperature
measurement. The passive ice version must not advertise a temperature-setting
command. Measure cold-condition dosing and recovery separately from ambient
tests. Measure tab forces and latch verification under the intended cold and
condensing conditions too.

## Interaction and responsibility

The orchestrator coordinates the robot, pipette and station. The station only
secures the tube, operates its lid and reports its own condition. The robot
controller remains responsible for robot motion and tip withdrawal. The station
controller owns all local drive interlocks and sensor checks.

If the station is later shared by up to three arms, the same orchestrator tracks
which robot receives the single access grant. Multiple arms must not enter the
station workspace at once.

The fundamental rule is mutual exclusion: **robot access and station actuation
cannot be active together**. A software access grant inhibits every station
actuator, including the retainer. A proposed independent local clearance input
must also permit every motion. Robot software reporting “done” alone is
insufficient. The input's sensing method and required performance are still to
be designed; SiLA communication is not a physical safety function.

| Command | Preconditions and completion meaning |
|---|---|
| `AcquireControl(ClientId)` | Atomically reserves the station and returns a boot-scoped control token. Another client cannot take ownership. |
| `Heartbeat(ControlToken)` | Refreshes the owner's watchdog. Initial review values: every 2 s, 6 s timeout; configurable and unvalidated. |
| `Initialize(ControlToken, ProfileId, CoolingRequired)` | Empty nest, no access grant, independently clear workspace. Select a qualified article profile, home/park fingers and release retainer. Observable command. |
| `BeginAccess(ControlToken, Purpose)` | Atomically inhibits actuation before returning one access token. Purpose is `Loading`, `Pipetting` or `Unloading`. Requires standstill. |
| `EndAccess(ControlToken, AccessToken)` | Robot is fully withdrawn and independent clearance is true. Only then may the grant end; a failed check preserves inhibition. |
| `OpenTube(ControlToken)` | Loaded tube, no access grant, clear workspace. Verify orientation, secure tube, open and retain lid, park fingers and verify opening. Observable command. |
| `CloseTube(ControlToken)` | Secured/open tube, no access grant, clear workspace. Close within limits, verify latching, park fingers, then release retainer. Observable command. |
| `StopMotion()` | Any authenticated client can request a priority controlled stop, even during another command. Returns acceptance; physical standstill is reported separately. |
| `ReleaseControl(ControlToken)` | Empty, motionless station with no active robot access. Ownership never expires into automatic reassignment. |

An access grant has purpose-specific conditions:

- **Loading:** empty nest, retainer released and fingers parked.
- **Pipetting:** tube secured, lid verified open, fingers parked and cooling ready
  when cooling was requested. Keep the grant throughout pipetting and withdrawal.
- **Unloading:** lid verified closed, retainer released and fingers parked.

Checks are repeated by the local controller when admitting each command and
during motion. “Parked”, “secured”, “open” and “closed” require appropriate
feedback, not merely issued motor positions. Verification of latching is not a
claim that the tube is leak-tight.

```mermaid
sequenceDiagram
    participant O as Orchestrator / SiLA client
    participant S as Tube station / SiLA server
    participant R as Robot and pipette controllers
    O->>S: AcquireControl; start heartbeat; subscribe Status
    O->>S: Initialize(profile, cooling required)
    S-->>O: Observable execution completes
    O->>S: BeginAccess(Loading)
    S-->>O: Access token; station actuation inhibited
    O->>R: Place oriented tube, release gripper, withdraw
    O->>S: EndAccess(token)
    Note over S: Independently confirm workspace clear
    O->>S: OpenTube
    S-->>O: Secured, open verified, fingers parked
    Note over O,S: Wait for CoolingReady when required
    O->>S: BeginAccess(Pipetting)
    O->>R: Pipette; withdraw tip and robot fully
    O->>S: EndAccess(token)
    O->>S: CloseTube
    S-->>O: Closed verified, fingers parked, retainer released
    O->>S: BeginAccess(Unloading)
    O->>R: Remove closed tube and withdraw
    O->>S: EndAccess(token); ReleaseControl
```

Heartbeat and status monitoring continue throughout this sequence, including
while waiting for cooling or while a command runs. Only one station motion
command may run; do not queue incompatible commands. Stop requests and heartbeat
handling must remain responsive while a drive command is active.

## SiLA 2 boundary

Use SiLA 2 with gRPC/Protocol Buffers over HTTP/2. The initial deployment is a
local server on the station controller, called by the orchestrator. Implement the
core `org.silastandard/core/SiLAService/v1` for server identity and feature
introspection. Plan discovery and a configured endpoint fallback, TLS with a
trusted server identity, and deployment-specific client authorization.

The custom feature is
`org.solidcraftbot/samplehandling/TubeStationControl/v1`, feature version 1.0,
maturity **Draft**. The originator is a provisional project namespace, not a
registered or consortium-approved feature. The XML is in
[TubeStationControl-v1_0.sila.xml](../interfaces/tube-station-c01/TubeStationControl-v1_0.sila.xml).

`Initialize`, `OpenTube` and `CloseTube` are observable commands. Use native SiLA
execution UUIDs and execution-status subscriptions to distinguish acceptance
from completion and obtain final results/errors. `Status` is one observable
structured snapshot: boot UUID, sequence, timestamp, operating mode, profile,
tube presence/retention, lid state, access purpose, workspace clearance,
standstill, block temperature/validity, cooling readiness and fault identifier.
Do not reconstruct one coherent state from unrelated property reads. The
initial proposal publishes at least every 1 s and treats receipt age over 3 s
as stale. Values are review defaults, not safety timing guarantees.

`SupportedProfiles` lists only experimentally qualified article profiles. It
would be empty for the present draft. Application modes such as `Ready` and
`RecoveryRequired` are project-defined status values; they are not SiLA command
execution states. Control/access tokens coordinate clients and do not replace
transport authentication. Generate protocol stubs from the FDL with the selected
SiLA implementation later; no wire protocol or REST imitation is supplied here.

## Faults, interruptions and recovery

- Reject wrong ownership, active access, invalid profile or invalid state before
  any new actuation. Report the documented defined execution error. Use standard
  SiLA validation/framework errors for malformed input and transport failures.
- On overload, timeout, missing retention, failed open/latch verification or
  clearance loss, stop locally as appropriate, retain tube support and latch
  `RecoveryRequired`. An opening failure must not lead to blind repeated prying.
- If cooling is lost during pipetting, report it immediately. The orchestrator
  aborts or finishes a controlled withdrawal according to its validated robot
  procedure; the station must never close automatically around the tip.
- On watchdog expiry, inhibit new motion and request controlled stopping of
  active station motion. Preserve any access grant and the tube's support. Do
  not automatically retract fingers, close the lid, release the tube or hand
  ownership to another client. Physical retention on power loss remains a design
  requirement, not a proven property of these envelopes.
- A disconnected client cannot assume that an accepted command was canceled.
  Reconnect, verify the boot UUID, observe status and retrieve the original
  execution result when its UUID remains valid. Do not blindly repeat motion
  commands after an ambiguous response. An unknown execution outcome or lost
  access token requires reconciliation or local recovery.
- A restart creates a new boot UUID, invalidates old tokens and starts with
  unknown physical state and motion inhibited. Local inspection and controlled
  recovery are required before homing or releasing a loaded tube. There is no
  unrestricted remote fault-reset command in this draft.
- `StopMotion` is a software stop request. It is not a safety-rated emergency
  stop; the independent protection and local stop circuit remain to be designed.

## Review files and verification scope

- [Current native FreeCAD model with UMR](../cad/generated/tube-station-c01-2d9bb38563f8/TubeStation_C01.FCStd)
- [Current native SolidCraft model with UMR](../cad/generated/tube-station-c01-2d9bb38563f8/TubeStation_C01.sc)
- [Current STEP layout with UMR](../exports/generated/tube-station-c01-2d9bb38563f8/default.step)
- [Current cross-CAD build and comparison report](../cad/tube-station-c01/shared-build-report.json)
- [Original C01 native SolidCraft model](../cad/tube-station-c01/TubeStation_C01.sc)
- [Original C01 plain native JSON](../cad/tube-station-c01/TubeStation_C01.native.json)
- [Original C01 STEP layout](../cad/tube-station-c01/TubeStation_C01.step)
- [Closed reference view](../cad/tube-station-c01/closed-reference.png)
- [Current CAD-independent station source](../model/tube-station-c01.shared.json)
- [Original C01 dimensions and assumptions](../model/tube-station-c01.json)
- [Original recipe and FDL generator](../scripts/prepare_tube_station_draft.py)
- [Original validation and source/artifact hashes](../cad/tube-station-c01/draft-validation.json)

### Two native CAD models and shared source

Following the owner's request to use both applications to improve the abstraction,
the station now has its own CAD-independent description in
`model/tube-station-c01.shared.json`, format `solidcraftbot.station/1`. It contains
the named parameters, 29 mechanical/reference bodies, a semantic UMR marking
expanded into three lettering bodies, five cuts, four rigid groups, three joint
frames, angle limits, appearances and named poses. Both adapters read these definitions;
mechanical layout is no longer hidden in the SolidCraft-specific build script.
The original C01 files and their report are preserved as the historical baseline.
The SiLA feature definition is unchanged.

Run from the project root:

```powershell
python scripts/build_tube_station.py
python -m unittest discover -s tests -p test_station_model.py -v
```

Each build uses a fresh generated folder and updates the cross-CAD report. The
pipeline launches separate headless processes and does not replace a document
open in either desktop application. The original `prepare_tube_station_draft.py`
is retained to reproduce the historical C01 recipe/FDL, not as the current CAD
source. Native exports represent the pipetting pose. The arm's leading source
remains `model/robot.json`.

The FreeCAD file contains native `Part::Box`, `Part::Cylinder`, `Part::Cut` and
polygon extrusion features with expression-linked `App::Part` placements. The
UMR outlines reuse the robot's font-independent glyph definitions and color;
no installed font is required. Open it directly, select
**Controller**, and edit **Opener**, **Closer** or **ReferenceLid** in degrees.
The same concept limits as the table above apply. These are native expression
placements, not FreeCAD Assembly-solver constraints or physical lid contacts.
Select **ModelParameters** to explore length parameters in mm. Colors, hidden
construction tools and an overview camera are saved in the file; presentation
metadata was checked without opening a FreeCAD GUI process.

A source change should be made in the shared JSON and both models rebuilt.
Native edits are useful experiments but are not automatically written back to
the shared source. SolidCraft receives resolved geometry and frames on rebuild;
FreeCAD additionally keeps the supported native length expressions linked.

The abstraction check covers the default layout, a 10 mm higher working height,
the 3 mm height change where the insert just leaves the drawn coolant envelope,
and a 20 mm longer base. Those are geometry exploration cases, not approved
operating or thermal ranges. Each case checks all 32 bodies against analytic
volume/centroid references and against the other CAD. A FreeCAD edit from
`tube_mouth_z=100 mm` to `110 mm` also verifies the dependent `pivot_z=111 mm`
and the body/support placements without rebuilding the native feature tree.

For every case, the SolidCraft STEP solids are compared with independently built
native FreeCAD solids by symmetric-difference volume, with a tolerance of
0.001 mm³ per body; all four cases reported 0 mm³. Eight joint configurations
per case are checked against independent coordinate transforms. These tests
check geometry and coordinate semantics, not whether a gripper can load the
tube or whether the lid mechanism works physically. The loading review above
and the original two-pose interference scope remain applicable; the carrier
proposal has not been added to either model.

Checks cover primitive body volumes, timeline health, joint solution at selected
poses and interference snapshots. The report separates fixed-group construction
overlaps from different-group overlaps. It does not prove the full motion
envelope, physical contact sequence, sealing, force limits, thermal performance,
cleanability or robot clearances. Nominal CAD material density is not a mass
estimate for procurement or actuator selection.

The FDL was checked against a saved copy of the official XML schema. This checks
XML structure and types, not server behavior, interoperability or SiLA conformance.
Repeat that check with `./scripts/validate_tube_station_fdl.ps1` in PowerShell.
Before hardware integration, implement a simulator and test access exclusion,
ambiguous responses, stale sensing, stop handling, ownership, disconnects and
restarts with a real SiLA client. No server, SDK dependency or device service is
installed or running as part of this draft.

## References

- [SiLA 2 standard overview](https://sila-standard.com/standards/)
- [SiLA 2 Part A v1.1: concepts and core](https://sila-standard.com/wp-content/uploads/2022/03/SiLA-2-Part-A-Overview-Concepts-and-Core-Specification-v1.1.pdf)
- [SiLA 2 Part B v1.1: protocol mapping](https://sila-standard.com/wp-content/uploads/2022/03/SiLA-2-Part-B-Mapping-Specification-v1.1.pdf)
- [Official Feature Definition XML schema](https://gitlab.com/SiLA2/sila_base/-/raw/master/schema/FeatureDefinition.xsd)
- [Official SiLAService feature](https://gitlab.com/SiLA2/sila_base/-/raw/master/feature_definitions/org/silastandard/core/SiLAService-v1_0.sila.xml)
- [Jinno and Nonoyama, 2025: experimental microtube capper/decapper](https://link.springer.com/article/10.1186/s40648-025-00306-5)
- [Eppendorf: temperature effects on air-cushion pipetting](https://www.eppendorf.com/us-en/lab-academy/topics-methods-technology/pipetting-dispensing/influence-of-physical-parameters-on-the-dispensed-volume-of-air-cushion-pipette)

The station mechanics and workflow above are project proposals. Research devices
and commercial thermal modules do not qualify this particular construction.
