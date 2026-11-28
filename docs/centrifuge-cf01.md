<a id="cf01-overview"></a>

# CF01 — robot-accessible centrifuge, assembled inspection view

Diese Datei ist die führende CF01-Beschreibung für Konstruktion, lokalen Vertrag,
Roboteraufstellung, Chargenlauf und geglättete Entnahme. Die zusammengeführten
Originalabschnitte bleiben vollständig erhalten; ihre Aussagen gelten für die
jeweils benannten Module und Prüfstände.

## Lesepfad und Geltungsbereiche

- [Station, Mechanik und lokales Grundmodell](#cf01-station)
- [Protokollvorschau und ROS-/SiLA-Vertragsgrenzen](#cf01-protocol)
- [Roboteraufstellung und eigenständiger Chargenlauf](#cf01-robot-pickup)
- [Durchgehende Drei-Proben-Entnahme und Prüfgrenzen](#cf01-smooth-unloading)
- [Historischer Review-Nachtrag vom 8. November 2026](#cf01-historical-review-2026-11-08)

Der lokale JSON-Lines-/MockProtocol-Vertrag, seine Vertragsdecoder und der
separate [SiLA-Netzwerkadapter](sila2-network.md) sind verschiedene
Ausführungswege. Ein Mock-Erfolg belegt keine Netzwerkkommunikation; ein
Netzwerknachweis belegt keine Hardwareausführung. Die frühere einzelne
47,5-s-Entnahme und der reihenfolgetreue lokale Zwölfer-Chargenrunner sind
außerdem getrennte Programme. Die fließende Drei-Proben-Entnahme hat eine
eigene Zeitachse, Dynamik- und Geometrieprüfung.

Konkrete Testzahlen, CAD-Revisionen und Medienvergleiche unten sind
standsgebundene Nachweise. Das Zusammenführen von Text erzeugt weder neue
Prüfergebnisse noch eine weitergehende mechanische, biologische oder
sicherheitsbezogene Qualifikation. Historische Fehlbefunde und Grenzen,
einschließlich des SolidCraft-Gesamtimports, bleiben erhalten.

### Unveränderte Archiv- und Kompatibilitätspfade

Drei frühere Dokumentfassungen sind selbst durch bytegenaue Medienprovenienz
gebunden. Ihre Dateien bleiben deshalb unverändert am bisherigen Pfad; sie
sind eingefrorene Nachweise und keine zusätzlich zu pflegenden führenden
Beschreibungen. Die Herkunftsmanifeste und Medien werden nicht umgeschrieben.
Der Review-Pfad bleibt als kurzer Einstieg für Verweise aus diesen Archiven.

| Erhaltener Pfad | Rolle und Bindung |
|---|---|
| [centrifuge-cf01-protocol.md](centrifuge-cf01-protocol.md) | Eingefrorene Protokollfassung; SHA-256 `21aad97403596a31aa29ed56ad0dd76c84c7098e942cf7f04eb59934160ffc4d` in [robot-demo-smooth-batch.provenance.json](media/robot-demo-smooth-batch.provenance.json). |
| [centrifuge-cf01-robot-pickup.md](centrifuge-cf01-robot-pickup.md) | Eingefrorene Einzelentnahme-/Aufstellungsfassung; SHA-256 `0463de2942f46fb8cf6a3eb78a05e4e370653943a3f4ecbc9b92f307422d50c6` in [robot-demo-overlap.provenance.json](media/robot-demo-overlap.provenance.json). |
| [cf01-smooth-unloading.md](cf01-smooth-unloading.md) | Eingefrorene Bewegungsbeschreibung; SHA-256 `12b7eacec6341695327f9408c45e46be87740e8a774713ec0e066957694ba65d` in [robot-demo-continuous-cfr.provenance.json](media/robot-demo-continuous-cfr.provenance.json). |
| [cf01-claude-review.md](cf01-claude-review.md) | Kompatibilitätseinstieg mit erhaltenen Ankern zum vollständig übernommenen historischen Nachtrag. |

<a id="cf01-station"></a>

## Station und lokales Grundmodell

<!-- cf01-source-begin: station -->

Requested on 28 October 2026: **16,000 × g**, commanded opening/closing of the
instrument lid, camera-readable rotor orientation and presentation of individual
microcentrifuge tubes to the six-axis robot. CF01 supplies a shared-source layout
and runnable mock programming interface. It is **not a qualified centrifuge,
manufacturing design or demonstrated 16,000 × g capability**.

Leading source: [centrifuge-cf01.shared.json](../model/centrifuge-cf01.shared.json).
The [animated robot-access cycle and ROS/SiLA protocol](centrifuge-cf01.md#cf01-protocol)
now have a separate shared protocol source, native playback and generated
interface definitions; their mock behavior is tested offline, with no network server.
The later [robot grasp and withdrawal animation](centrifuge-cf01.md#cf01-robot-pickup)
adds a bench-mounted longer-link variant of the same six-axis arm and a concept
gripper. The carried tube and arm clear the centrifuge before the lid closes;
the robot then places the tube into a guided 12-position output rack.
The [current build report](../cad/centrifuge-cf01/shared-build-report.json) lists
the actual native SolidCraft/FreeCAD files, STEP exports, renderings and checks.
Historic directories remain historic; open the report's current `cases` paths.

<a id="cf01-mechanical-draft"></a>

### Mechanical draft

| Item | Initial interpretation, subject to review |
|---|---|
| Capacity | 12 illustrative closed 1.5/2.0 mL tubes |
| Rotor | Fixed angle, 35° from vertical; tube-bottom reference radius 80 mm |
| Envelope | Base 400 × 380 mm; lower bay 150 mm high; closed assembly about 292 mm high including lid gearbox; rotor diameter 212 mm |
| Steel chamber | 22 mm radial wall, 12 mm floor plate; translucent inspection appearance in the native models |
| Steel lid | 20 mm disc; steel grade and lid retention/actuation design remain open |
| Lower housing | Hollow steel bay, 3 mm walls/roof and 6 mm bottom; four steel floor-support posts |
| Instrument lid | Rear hinge shaft, 60:1 gearmotor, motor holding brake, two powered locking pins; commanded 0–105° |
| Pickup position | Front, station −Y; selected pocket indexes here |
| Indexing | At most 2 rpm, **lid closed and locked**, lifter parked, robot clear |
| Tube presentation | Stop, hold rotor, open lid, then lift 16 mm along tube axis |
| Lifter | Stationary retracting axial pusher in a coaxial guide; 28 mm nominal park gap and 44 mm total stroke |
| Frame | Origin at base-center underside; +Z up, +X right, approach from −Y |

The pusher reaches through a passage below the selected pocket and retracts
entirely before rotation. The 16 mm axial tube lift gives approximately 13.1 mm
vertical rise and 9.2 mm inward travel, exposing body below the collar. A future
gripper must match the 35° orientation. Individual tube caps remain closed.

This is a stopped-rotor interpretation of the proposed slow ramp. A continuously
engaged ramp would have to disappear completely from the high-speed sweep and
confirm this state; it is not implemented. The CAD coordinates are independent
inspection controls: only named poses and sampled protocol sequences are checked.
Never rotate with an extended pusher or lifted tube.

The owner specified **steel for the housing, chamber and lid only**. Rotor
material remains unselected. The previous 14 mm transparent chamber envelope is
replaced by a 22 mm steel wall and a separate floor. Four posts connect the
floor plate to the base bottom through clearance holes in its roof; hinge
supports now reach the base. These establish a proposed geometric load path,
not verified joints or structural capacity. The motor, spindle and electronics
occupy the hollow lower bay. Shaft seals, fasteners, welds and vibration mounts
still need design.

The 22/12/20 mm dimensions are provisional layout choices, **not calculated
burst-containment thicknesses**. Steel grade, corrosion/cleaning requirements,
yield strength, impact behavior and joints are open. The generic SolidCraft
Steel material and FreeCAD material annotations record the selected family;
library material properties must not be mistaken for a chosen grade.
Using an explicit preliminary density assumption of 7,850 kg/m³ gives roughly
10 kg for the lid and 14 N·m closed-position gravitational hinge torque before
friction or acceleration. The build report calculates the nominal CAD estimates.
A supported/counterbalanced lid, actuator and positive retention need separate
load qualification; these numbers are not actuator ratings or measured masses.
The current revision implements their geometric arrangement: two bored hinge
bearing housings, a rotating hinge shaft, lid arms/output coupling, a geared
motor with holding brake and two pin/strike lock mechanisms. The bay is taller
to accommodate a separate spindle motor, parking brake, encoder and bearing.

The stepped pockets intentionally have clearance; they do not establish tube
support or a real load path. Bottom passages change rotor structure. **Do not
drill or modify a rated commercial rotor to realize this sketch.** A purpose-
qualified rotor and matched drive/containment assembly need development with a
suitable supplier. A commercial robotic centrifuge core with an approved
extraction interface is an alternative to evaluate. No purchased part is selected.

<a id="cf01-the-16000--g-target"></a>

### The 16,000 × g target

`RCF = 1.118 × 10⁻⁵ × radius_cm × rpm²` gives **13,375 rpm** at the illustrative
80 mm reference radius. This is a kinematic calculation, not a strength rating.
Actual fluid radius depends on tube and rotor; the draft uses the tube-bottom
centerline. The radius/speed relation and a commercial 1.5/2.0 mL rotor above this
target are described in the [Eppendorf 5425 operating manual](https://www.eppendorf.com/product-media/doc/en/338022/Centrifugation_Operating-manual_Centrifuge-5425.pdf).
That product's rating does not apply to CF01.

Rotor material, stress/fatigue life, maximum tube mass, tube article, overspeed
margin, bearings, drive, braking, lid retention, independent standstill sensing,
imbalance detection, temperature and burst containment remain open. There is no
aerosol-tight rotor lid or its automated handling; hazardous-sample use is not
established. Costs are additional to the existing arm budget and remain unknown.

<a id="cf01-camera-orientation"></a>

### Camera orientation

Large light **01–12** numerals sit on the dark rotor face, counterclockwise viewed
from above. At zero angle, 01 is at the front. A unique yellow triangle points
towards 01; a cyan square on rotor +X provides a second, different shape. A fixed
dark L and three dots mark the station. Shape/position permit monochrome use too.
These are custom shapes, **not AprilTag/ArUco codes**.

Thin marking solids are visual aids. A durable, flush, supplier-approved marking
process and its effects on balance/integrity must be selected. Read only at
standstill with lid open. Encoder indexing is primary; vision cross-checks the
chosen pocket. Camera decoding, lighting, pixel size, calibration and recognition
performance have not been implemented or measured. Robot-to-station transform
is unknown; reported pickup coordinates are local station coordinates.

<a id="cf01-power-entry-and-cable"></a>

### Power entry and chassis bond

`CF01.POWER` is the common interface at the right side of the lower bay. The CAD
contains an inlet/switch/fuse-module envelope. The detachable mains cord
assembly is outside the geometry scope.

A chassis earth stud and short green bond lead are represented. PE bonding to
all steel panels and the lid, electrical isolation, drive/control supplies,
fusing, EMC treatment and complete wiring are requirements. The lid bonding
braid and complete wire routing are not modeled. Nominal mains voltage, current,
power, fuse rating, conductor area and purchased inlet/cord remain `null`.
There is no energized circuit or electrical test. The geometry is an envelope,
not a registered IEC mounting interface. Combined inlet/switch/fuse units are
illustrated by the [SCHURTER KD data sheet](https://www.schurter.com/en/datasheet/typ_kd.pdf);
no particular product has been selected.

<a id="cf01-rotation-measurement"></a>

### Rotation measurement

`CF01.ENCODER` is a noncontact spindle ring plus stationary readhead and steel
bracket **below the chamber floor**, in the intended dry electrical bay. The
nominal radial gap is 1 mm; a purple signal lead runs towards the control bay,
separately from the side mains entry. Sealing the shaft opening and protecting
the encoder from leakage/contamination remain open. The ring is a balanced
component envelope, without individually modeled lines or a selected mounting
method. The ring/readhead arrangement follows the architecture described by
[Renishaw's rotary encoder documentation](https://www.renishaw.com/en/rotary-optical-encoders--48559).

The process feedback requirement is A/B quadrature plus one Z reference:
1,024 line cycles/revolution, ×4 counting, 4,096 counts/revolution. Nominal
quantization is 0.08789°, **not achieved accuracy**. A calibrated error at most
0.1° and a speed rating of at least 16,000 rpm are requirements; actual part,
accuracy, supply, counter and speed rating remain unknown. Z and a calibrated
offset relate the encoder to rotor slot 01.

At the 13,375 rpm target this produces about 228 kHz per A/B channel and
913 kcounts/s. At the requested 16,000 rpm sensor rating, ×2 headroom requires
about 2.185 MHz; a 3 MHz counter-input requirement is recorded. These are
interface calculations, not bandwidth tests. `encoder_requirements()` derives
them from the source. `encoder_measurement(delta_count, interval_s)` converts a
signed count delta to rpm and degrees; **zero counted motion never establishes
safe standstill**. The separate `CF01.STANDSTILL` hardware monitor remains
unimplemented. Encoder loss/staleness inhibits start/access and faults a mock
run while retaining the lid state; a physical driver must request a stop and
wait for independent standstill feedback.

<a id="cf01-spindle-motor-and-brakes"></a>

### Spindle motor and brakes

`CF01.MOTOR` is a direct-drive three-phase brushless spindle architecture. Both
CADs now contain separate stator shell, rotating motor core, shaft, lower/upper
motor bearing envelopes, upper spindle bearing housing, motor mount, terminal
box and motor cable. The spindle bearing housing meets the chamber-floor
underside; rotating bodies remain on `RotorGroup`, housings on `Frame`. These
are parametric component concepts, not selected manufacturer geometry. Required
speed rating is at least 16,000 rpm; actual motor/drive, continuous power,
torque, cooling, bearing fits and ratings remain open.

`CF01.BRAKE` has two different functions. The drive provides controlled
electrical deceleration into a chopper/braking resistor; the CAD includes the
drive and resistor envelopes. At confirmed standstill, an electrically
positioned parking caliper holds a separate spindle disc. Opposed upper/lower
pads have visible release travel, a fixed caliper/support and actuator envelope.
The rotating disc also needs high-speed strength and balance qualification even
though pad engagement is restricted to zero rpm. **The parking brake is not the
routine high-speed stopping brake.** This separation follows the distinction
between controlled drive braking and holding brakes in the
[Siemens motor configuration guidance](https://cache.industry.siemens.com/dl/files/345/55379345/att_68428/v1/1FK7_G2_config_man_0218_en-US.pdf).

The parking actuator is specified as bistable to avoid assuming automatic pad
application to a spinning shaft on power loss. Actual actuation/hold-off,
power-loss coastdown, lid retention and recovery require hardware design and
validation. Brake force, disc rating, resistor resistance, energy, peak power,
thermal duty and actual stopping time are unknown. Rotating inertia is `null`;
the report therefore leaves kinetic energy `null` rather than guessing it from
generic CAD material density. Sizing needs `E = 0.5 × J × omega²`, allowable
deceleration and duty cycle. See the manufacturer's
[braking resistor sizing discussion](https://library.e.abb.com/public/985ec66897df0c8fc12575a2001bec71/ACS510_01_UM_RevD_EN.pdf).

<a id="cf01-powered-lid-without-a-manual-step"></a>

### Powered lid without a manual step

`CF01.LID_DRIVE` turns the lid through its hinge shaft and bolted output coupling.
The stationary gearbox and motor sit outside the opening sweep. A separate
motor holding brake retains position; self-locking of the gearbox is **not**
assumed. The hinge is raised 8 mm above the lid underside so the shaft clears
the chamber rim. Two powered pins engage blind bores in reinforced lid strikes;
their housings and actuator guides have explicit bores and retraction clearance.

The nominal 60:1 ratio and 10°/s lid-speed intent correspond to 100 rpm at the
gearmotor input. A 40 N·m output-torque target covers a factor of two on the
provisional gravity estimate for both checked geometry cases; it is not a
selected gearbox rating or proof of strength. Hinge/shaft/fastener stresses,
actuator margin, lock retention, obstruction force and power-loss holding remain
unqualified. Bracket joints, motors, brakes and lock actuators still need actual
part selection and their manufacturer data.

`open_lid` automatically retracts both pins, confirms release, releases the lid
holding brake, commands the open limit and reapplies the holding brake. It
requires rotor standstill, the parking brake and a clear workspace. `close_lid`
requires a parked tube lifter and clear workspace, drives to the closed limit,
holds the lid, then extends/confirms both pins. There is no request for a person
to push or pull the lid. In the mock, limit switches and these moves are
idealized; real motor IO, motion timeouts and force/obstruction sensing are not
implemented.

<a id="cf01-executable-programming-interface"></a>

### Executable programming interface

[centrifuge_control.py](../scripts/centrifuge_control.py) provides a dependency-free
Python mock and local JSON-lines interface. There is **no hardware driver,
network endpoint, ROS node or SiLA 2 server**. A future adapter can map these
commands, run IDs and feedback to SiLA; no SiLA conformance is asserted.
The generated [request schema](../interfaces/centrifuge-cf01/request.schema.json)
describes requests. Responses contain `ok`/`result`, or an error `code`/`message`.

```powershell
python scripts/centrifuge_control.py --demo
python scripts/centrifuge_control.py
```

The second command accepts one JSON object per line, preserving state until exit.
Replace the token placeholder with the actual `acquire` response:

```json
{"command":"acquire","client_id":"arm-orchestrator"}
{"command":"rotation_feedback"}
{"command":"index","token":"TOKEN_FROM_ACQUIRE","slot":3}
{"command":"open_lid","token":"TOKEN_FROM_ACQUIRE"}
{"command":"present_tube","token":"TOKEN_FROM_ACQUIRE"}
{"command":"confirm_removed","token":"TOKEN_FROM_ACQUIRE","grasp_confirmed":true,"tube_absent":true}
{"command":"retract_lift","token":"TOKEN_FROM_ACQUIRE"}
{"command":"close_lid","token":"TOKEN_FROM_ACQUIRE"}
{"command":"release","token":"TOKEN_FROM_ACQUIRE"}
```

Send `heartbeat` with the token within each 10 s ownership interval. The normal
mock starts with 12 synthetic seated tubes of unknown mass. `--demo` injects
explicitly fictitious ratings and masses to exercise a 16,000 × g request, stop
and pickup from 03. It never qualifies or connects hardware. A normal `start`
is rejected because real qualification limits are unknown.

Equivalent Python, from the project directory:

```python
import sys
sys.path.insert(0, "scripts")
from centrifuge_control import Simulator

cf = Simulator()  # synthetic sensors; cannot drive hardware
token = cf.execute("acquire", client_id="robot")["token"]
cf.execute("index", token, slot=3)
cf.execute("open_lid", token)
state = cf.execute("present_tube", token)
print(state["grip_frame"])  # mm and unit tube axis in CF01.station
```

| Commands | Intended completion / restrictions |
|---|---|
| `acquire`, `heartbeat`, `release` | Exclusive owner, boot-scoped token; coordination is not authentication |
| `status`, `events` | Lid/lock, speed/standstill, brake, index, lift, occupancy/mass, rotation-sensor health, fault, run phase/ID, ordered events |
| `rotation_feedback` | Synthetic rpm, age, health, indexed angle/count and Z-home state; no physical sensor connection |
| `open_lid`, `close_lid` | Full powered motor/holding-brake/pin sequence; standstill and clear workspace; closing requires parked lifter and seated tubes |
| `index(slot)` | Closed/locked lid, robot clear, lifter parked; slow index then encoder settling and brake hold |
| `present_tube` | Open lid, fresh standstill, brake and selected-index feedback |
| `confirm_removed` | Both grasp confirmation and tube-absence feedback |
| `retract_lift` | Tube removed and robot withdrawn |
| `lower_tube` | Failed-pick recovery: robot clear; lower still-present tube and confirm seating |
| `confirm_seated` | Mock loading: parked lift, seated tube, closed cap, measured total mass |
| `start(rcf_x_g, duration_s)` | Qualified limits, closed/locked lid, parked lifter, robot clear, known balanced load |
| `stop` | Start/retain simulated drive deceleration; keep parking pads released until standstill, then hold; retain lid state |
| `reset_fault` | Fresh standstill, brake, robot clear and parked lifter; explicit recovery |

The draft balance rule requires opposite occupied pairs, known total tube masses
and a configured pair tolerance. This restrictive rule is not a proven dynamic
balancing algorithm. Real ratings/tolerances remain `null` in the source.
Unknown masses, non-finite arguments and excessive requests are rejected.

Feedback must be at most 0.5 s old. Standstill needs zero speed, an independent
standstill indication and holding-brake feedback. Index error must be within
0.2°. Lost ownership/feedback latches a fault and aborts the mock run, retaining
lid state. Explicit lowering of a raised tube or retracting an empty lifter is
permitted during recovery; reset then requires a parked mechanism. There is no
automatic opening, ownership transfer or resume. `CF01.` event/protocol IDs
connect the actions with source requirements and CAD poses.

**Mock limits:** lid/index setpoints and sensor updates remain idealized. `stop`
now enters `braking` with a linear **5 s synthetic deceleration**. It does not
claim physical stopping performance. The lid stays locked, pads stay released
and access/reset is refused while speed remains nonzero. At model standstill
the parking brake engages and the run ends `completed`, `aborted` or `faulted`.
A repeated stop does not restart the timer. An encoder/owner fault requests this
stop rather than instantly declaring zero speed. Dwell is represented by a run
ID/timer; poll `status` and send heartbeats. Timer/watchdog
checks occur on requests, not in an independent real-time loop. Default feedback
is synthetically refreshed on requests. Boolean confirmations are injected mock
feedback, not proof from physical sensors. A future driver needs measured
completion, persistent recovery, real watchdogs, power-loss behavior, independent
interlocks and local supervision; it must not fabricate standstill after a stop.

The new `rotation_sensor` status object uses ID `CF01.ENCODER`. During simulated
spin the mock reports its synthetic speed; continuous pulse counting is not
simulated, so angle/count are unavailable until indexing. Public clients cannot
set a sensor healthy or synthesize a safety input through the command interface.
Tests inject faults directly into the mock. A physical A/B/Z reader, independent
standstill device and real-time counter/watchdog are not implemented.
`mechanisms` status also exposes motor/braking state, lid angle/limits, lid
holding brake and both pin positions. Fault checks cover brake release feedback,
pin release/locking, lid drive health and obstruction. Tests are model tests,
not safety validation of hardware.

<a id="cf01-shared-build-and-checks"></a>

### Shared build and checks

```powershell
python scripts/build_centrifuge.py
python -m unittest discover -s tests -v
```

`centrifuge_model.py` expands the steel chamber/floor/supports, hollow bay,
power entry and chassis bond, spindle encoder, fixed-angle pocket pattern,
tubes, numeral contours, landmarks, lid and ejector once for both CAD adapters.
`centrifuge_mechanisms.py` adds the shared spindle, caliper, geared hinge and
powered lock recipes. There are nine rigid groups and eight motion coordinates:
lid/rotor rotation, tube/pusher translation, two brake pads and two locking pins.
The six-axis arm schema is separate. SolidCraft MCP ran the initial model; the
reproducible CLI saves project files because this MCP session restricts output
to its temporary/recovery directories. Native dimension changes require source
regeneration; motion coordinates remain editable in both CADs.

Each build records new revision paths and source/generator/output hashes.
Body identity, solid validity, volume, center of mass and exact exported STEP
bounding boxes are compared. Display-mesh bounds can overrun trimmed curved
faces and are reported separately. Conservative OCC bounds are replaced with
optimal bounds. This is not a full STEP symmetric-difference comparison.

Each geometry case checks 44 discrete poses: closed/open/pickup, unlocked/spin-ready states, lid samples,
all 12 index angles and approach/lift samples. A second case changes bottom
radius, mouth/lid heights, lift travel, enclosure width, wall/floor/lid thickness
and sensor gap. Geometry, ports and anchors follow the same
parameters. Additional samples cover parking-pad and powered-pin strokes.
Analytic checks cover steel wall/floor/lid, stator and brake-disc volumes
plus the sensor gap. Internal overlaps within each rigid component are cached between
poses because they do not change under rigid motion. Pairwise
intersections distinguish internal rigid overlaps from moving-component overlaps.
Only tube 01 is a separate lifting CAD body; the mock can present any selected
pocket. The complete robot/gripper, continuous swept volumes, high-speed dynamics
and physical function are not validated. FreeCAD is reopened headlessly and
presentation metadata saved; its GUI rendering is not checked. The current report
determines which checks actually passed.

The report also links `service-interfaces.json`, with explicit units, service
frames, open component data and encoder bandwidth requirements. An additional
drive-detail render hides the enclosure to reveal motor, brake, sensor, drive
and resistor; a lid-detail view shows the powered hinge and lock mechanisms.
The saved product model opens fully assembled in the `closed` pose, with tubes
seated, ejector parked, parking brake held and both lid pins engaged. On 29 October
2026 the owner requested a semi-transparent assembly view. The shared
`presentation` record assigns 18% opacity (82% transparency) to the housing,
chamber wall, floor and lid in both CADs; internal mechanisms and supports retain
their contrasting opaque colors. Steel assignments, dimensions and mechanical
properties are unchanged. `display_pose` and `presentation` are consumed by the
shared expansion and both adapters, so rebuilding reproduces this view.
`mechanism-interfaces.json` records
mechanism requirements, all joints and the same sampled states. Steel mass/hinge-torque estimates are
reported with their density assumption and do not qualify the structure.

Next: a stationary low-force handling mockup with a measured tube and intended
gripper, resolving support, pickup clearance, reseating, jams and cleaning.
In parallel, choose a qualified centrifuge-core/rotor route and rotor-lid handling
before committing to the high-speed design. Register camera/station frames before
planning complete robot transfer paths.
<!-- cf01-source-end: station -->

<!-- cf01-source-begin: protocol -->
<a id="cf01-protocol"></a>

## CF01 robot access animation and ROS 2 / SiLA 2 contract

<!-- cf01-editorial-note -->
Die folgenden Angaben beschreiben den lokalen Mock-/Dateivertrag und seine native Protokollvorschau. Aussagen zu fehlenden Netzwerkservern gelten für diese Adapter; der additive SiLA-Dienst ist separat in [sila2-network.md](sila2-network.md) dokumentiert. Die Opt-in-Rotorindexierung bleibt von den Standardbefehlen getrennt.
<!-- /cf01-editorial-note -->

The shared source is [centrifuge-cf01.protocol.json](../model/centrifuge-cf01.protocol.json).
It defines the animation timeline, commands, argument types, execution rules and
robot pickup sequence. Geometry, joints, limits and named poses remain in
[centrifuge-cf01.shared.json](../model/centrifuge-cf01.shared.json).
The [protocol build report](../cad/centrifuge-cf01/protocol-build-report.json)
binds both source hashes to the actual animation, CAD files and interface files.

The follow-up [six-axis robot grasp/withdrawal scene](centrifuge-cf01.md#cf01-robot-pickup)
now demonstrates tube removal before closure and supported placement into an
output rack, using a longer arm mounted directly on the bench. The 33-second sequence
described below remains the earlier centrifuge-only, reversible presentation cycle.

The archived 33-second illustrative cycle retracts both lid pins, opens the lid to
105°, advances the pusher through the earlier 12 mm park gap, raises tube 01 by 16 mm along its
35° tilted axis, holds it for pickup, then reseats the same tube, parks the
pusher, closes and locks the lid. Axial tube travel corresponds to **13.1 mm
vertical and 9.2 mm inward**. The rotor remains stopped and its parking brake
held throughout. This is a reversible presentation demonstration: no robot
grasp, withdrawal, removal or physical tube contact is simulated. Lift/pin
timings are illustrative; the lid uses the provisional 10°/s requirement.
The native GIF plays about 2.25 times faster; the interactive view offers
0.5×/1×/2× playback and a tube/pusher close-up.
Current CAD derives a nominal 28 mm park gap from the rotor and pusher geometry.

<a id="cf01-protocol-reproduce-and-view"></a>

### Reproduce and view

```powershell
python scripts/build_centrifuge_animation.py
& 'C:/Users/u005069/AppData/Local/Programs/FreeCAD 27.1/bin/python.exe' scripts/export_centrifuge_animation_mesh.py
python scripts/build_centrifuge_visual.py
python scripts/build_centrifuge_interfaces.py
./scripts/validate_centrifuge_fdl.ps1
./scripts/verify_centrifuge_protocol.ps1
python -m unittest discover -s tests -p 'test_centrifuge*.py' -v
```

The animation builder requires a current, checked CF01 geometry build. It reads
the latest native files from the geometry report and checks their hashes. It
adds a SolidCraft motion study named `CF01RobotAccess`, exports native joint
frames and a GIF, and saves a new `.sc` without changing the geometry source.
It copies the checked native FreeCAD document and generates a separate
`CF01_RobotAccess.FCMacro` with a timer, play/pause and timeline slider. Open and
run that macro in FreeCAD for native playback; its GUI is prepared but has not
been executed here. Opening the `.FCStd` alone gives the original closed pose.
The interactive view uses reduced meshes tessellated from those native solids,
including actual rotor bores, and the same joint hierarchy and keyframes.

The animation pose audit compares all nine native SolidCraft rigid-group frames
at 133 samples against independent transforms from the shared model. Limits,
pin/lid interlocks and pusher/tube coupling are checked. Existing geometry
evidence remains attached to its original geometry revision. These are sampled
kinematics, not a new continuous swept-volume, gripper-clearance, strength,
contact or high-speed dynamics validation.

<a id="cf01-protocol-compatible-definitions-explicit-runtime-boundary"></a>

### Compatible definitions, explicit runtime boundary

The generated [transport contract](../interfaces/centrifuge-cf01/transport-contract.json)
maps each operation to the same mock core. It includes:

- A standalone ROS 2 Jazzy-targeted interface package,
  [solidcraftbot_cf01_interfaces](../ros2_ws/src/solidcraftbot_cf01_interfaces/CMakeLists.txt):
  one coherent `State.msg`, seven actions and nine short services.
- A custom SiLA 2 v1.1 draft feature,
  [CentrifugeControl-v1_0.sila.xml](../interfaces/centrifuge-cf01/CentrifugeControl-v1_0.sila.xml):
  16 commands, seven observable, plus an observable typed `Status` property.
- The runnable local `MockProtocol` in
  [centrifuge_protocol.py](../scripts/centrifuge_protocol.py), including ROS/SI and
  SiLA parameter decoding, coherent SI state conversion, exclusive motion jobs,
  polling and controlled cancellation. It calls the existing local simulator.

ROS actions use goal/result/feedback definitions in an `ament_cmake` interface
package as described in the [official ROS action tutorial](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Tutorials/Intermediate/Creating-an-Action.rst).
The SiLA feature follows the
[SiLA 2 mapping specification](https://sila-standard.com/wp-content/uploads/2022/03/SiLA-2-Part-B-Mapping-Specification-v1.1.pdf)
and is validated against the archived official XSD files under
`exports/research/sila2-schema/`. Schema validity is distinct from server
conformance and client interoperability.

The v1 definitions and `MockProtocol` above remain local contracts and mocks.
**No ROS node/action server is implemented.** The original Windows checks did
not compile or run the ROS package or exercise live SiLA networking.
A separate [CF01 v2 TLS/gRPC server](sila2-network.md) now implements the network
boundary to the same simulator core, with authentication and feature discovery.
Its historical checks, current integration status and explicit acceptance gates
are documented separately; local v1 decoding is not evidence of network success.
The network adapter does not qualify real drive I/O, independent feedback, LAN
deployment, hardware or safety. The originator namespace remains a provisional
project identifier, not a registered standard SiLA feature.
The local mock always reports `simulation_only=true`, `hardware_qualified=false`.

To compile the prepared definitions in an installed ROS 2 Jazzy environment:

```bash
source /opt/ros/jazzy/setup.bash
cd ros2_ws
colcon build --packages-select solidcraftbot_cf01_interfaces
source install/setup.bash
ros2 interface show solidcraftbot_cf01_interfaces/action/PresentTube
ros2 interface show solidcraftbot_cf01_interfaces/msg/State
```

These commands build/inspect definitions; they do not launch a centrifuge server.
The existing six-axis arm package remains separate. No CF01 URDF/RViz node or
Gazebo physics model was added; a complete robot pickup path is not claimed.

<a id="cf01-protocol-orchestrator-sequence"></a>

### Orchestrator sequence

| Step | Operation / required completion |
|---|---|
| Reserve | `AcquireControl`; retain returned boot-scoped token and send heartbeats within the reported deadline |
| Index | `IndexRotor(slot)` with lid closed/locked, pusher parked and robot clear; ≤2 rpm; finish at confirmed standstill with brake held |
| Open | `OpenLid`; both pins retracted, open limit reached, lid holding brake engaged |
| Present | `PresentTube`; finish only with selected tube raised and `pickup_valid=true` |
| Grasp | Robot approaches the calibrated pickup frame and grasps; independent occupied-workspace input inhibits station movement |
| Transfer | `ConfirmRemoved(grasp_confirmed=true, tube_absent=true)`; either missing confirmation leaves transfer unresolved |
| Withdraw | Robot leaves; independent clearance feedback must be fresh and true |
| Park | `RetractLift`; no unsupported tube may remain on the pusher |
| Close | `CloseLid`; closed limit, lid held, both pins engaged |
| Release | `ReleaseControl`; stationary, parked, clear workspace |

The animation uses `LowerTube(seated_confirmed=true)` instead of removal, to show
a complete reversible cycle without depicting an unmodeled robot. Actual robot
clearance is a future independently measured input, not a command parameter or
remote client override. The current mock generates synthetic feedback only.

The `pickup_position_m` is XYZ in uncalibrated `cf01_station`; `pickup_axis` is a
unit tube-axis vector, not a calibrated six-degree-of-freedom grasp pose. Robot
calibration, roll, gripper geometry and approach/escape trajectories remain open.
All wire positions use m, angles rad, speed rad/s and ages s; RCF explicitly uses
`rcf_x_g`, tube mass uses `mass_g`. Invalid encoder numbers have separate validity
bits; numeric placeholders must be ignored when invalid. `sequence` counts core
events within `boot_id`, rather than inventing a wall-clock observation timestamp.

<a id="cf01-protocol-observable-completion-and-cancellation"></a>

### Observable completion and cancellation

`OpenLid`, `CloseLid`, `IndexRotor`, `PresentTube`, `RetractLift`, `LowerTube` and
`RunCentrifuge` are actions / observable commands. The current core makes lid,
index and lift moves idealized instant operations. Their protocol jobs finish
after that synthetic confirmation; no physical timing or progress is fabricated
(`progress=-1` means unknown). A future driver must await actual limit, encoder,
seating, brake and health feedback before completing each operation.

`RunCentrifuge` remains active through both dwell and deceleration. `Stop` is a
short priority stop request; successful acceptance is **not standstill**.
The local `cancel(job_id)` requests stop and reports `stopping` until standstill
and held parking brake are confirmed, then reports `canceled`. The separate
[network v2 adapter](sila2-network.md) maps its `CancelController` to this core
behavior; do not assume ROS action cancellation is a universal built-in SiLA
command. Owner expiry or sensor faults latch recovery and never auto-restart.
Heartbeats and status remain available while one observable job is active.
This coordination stop is not an emergency-stop or certified safety function.

Tests exercise both wire parameter spellings, SI/validity conversion, blocked
concurrent motion, transfer uncertainty, occupied workspace, owner timeout,
normal run completion through braking and cancellation through standstill.
Default spinning remains rejected without the explicit fictitious test fixture;
tests cannot qualify the 16,000 × g target.

<a id="cf01-protocol-opt-in-synthetic-indexing-with-an-open-lid"></a>

### Opt-in synthetic indexing with an open lid

The separate [open-lid contract](../model/cf01-open-lid-index.protocol.json) and
[its schema](../model/cf01-open-lid-index.schema.json) add exactly one command,
`index_open_lid(slot)`. They pin the existing CF01 station and v1 protocol bytes;
the index-speed limit is a reference to the station's
`handling.index_limit_rpm`, rather than a second independent setting.
`scripts/cf01_open_lid_index.py` implements it only in the explicitly constructed
`OpenLidIndexSimulator` subclass. The standard `Simulator`, its JSON request
schema, `MockProtocol` command definitions and dispatch, ROS and SiLA bindings
are unchanged. In particular, the existing `index` and `start` still reject an
open or unlocked lid.

The new command requires a valid owner, no latched fault, fresh feedback,
confirmed standstill and held parking brake (`_still`), a clear robot workspace
(`_clear`), and a parked pusher with every present tube seated (`_parked`). The
lid must be at its open limit with a healthy holding brake engaged. Rotor,
encoder and parking-brake effects match the existing idealized `index`; the lid
stays open. It uses existing error codes, including `LidNotOpen`,
`LidAccessFault`, `TubeRaised`, `WorkspaceOccupied`, `NotStationary`,
`StaleFeedback` and `RecoveryRequired`. These are synthetic guards, not a
qualified permission to index physical equipment with its lid open.

`replay_station_commands(program)` (also named `replay_program`) checks the
explicit started/confirmed station-command events of the compiled three-sample
unloading program against this opt-in simulator. It begins with all twelve
original samples seated after the synthetic spin and preserves their original
rotor/rack identities. The first index uses the closed-lid base command; one
opening is followed by open-lid indexing, explicit tube-removal confirmations,
clearance and pusher retractions, and one final closure. The next sample cannot
become active or index before the preceding sample has rack support and complete
jaw release. Numerical station coordinates and their resting derivatives are
synthetic boundary observations; the separate motion validator checks actual
curve geometry, velocities and event thresholds.

The frozen simulator applies a lid command instantly and consumes pin
acknowledgements inside that idealized operation. Replay therefore checks the
explicit command-completion endpoint to supply its synthetic pin acknowledgement
and compares the resulting state with that endpoint. This is not feedback
available at the earlier physical start time. The replay's logical event clock
and injected local heartbeats retain mock ownership only: they do not test a
watchdog, communication latency, execution time or independently measured
feedback. A passing replay is no ROS/SiLA registration, hardware integration,
mechanical or biological qualification, or safety proof. The arm trajectory has
no implemented interruption/recovery branch. See
[the smooth unloading description](centrifuge-cf01.md#cf01-smooth-unloading) for the derived
preview and its other validation limits.
<!-- cf01-source-end: protocol -->

<!-- cf01-source-begin: pickup -->
<a id="cf01-robot-pickup"></a>

## CF01 bench-mounted robot and output rack

<!-- cf01-editorial-note -->
Dieser Abschnitt erhält die Aufstellung, den eigenständigen lokalen Chargenvertrag und die Nachweise der früheren Einzelentnahme. Aussagen zum 47,5-s-Baustein, zur README-Fassung `robot-demo-overlap` und ihren damals „aktuellen“ Prüfzahlen sind historische, buildgebundene Aussagen. Für die durchgehende Drei-Proben-Entnahme ist der [Bewegungsabschnitt](#cf01-smooth-unloading) maßgeblich. Die getrennte Anbindung an den [gemeinsamen Laborworkflow](synthetic-lab-workflow.md) erweitert den hier beschriebenen Standalone-Runner nicht stillschweigend.
<!-- /cf01-editorial-note -->

The [shared pickup scene](../model/centrifuge-cf01.robot-pickup.shared.json) now
combines the existing six-axis [robot](../model/robot.json),
[centrifuge](../model/centrifuge-cf01.shared.json) and
[command contract](../model/centrifuge-cf01.protocol.json). A provisional
parallel tube gripper is attached to the arm's existing flange reference.
The [combined pickup report](../cad/centrifuge-cf01/robot-pickup-build-report.json)
lists the generated animation, native CAD views, playback macro and evidence.
The independent SolidCraft result is recorded separately in
`cad/centrifuge-cf01/solidcraft-pickup-build-report.json`.

The 47.5-second illustrative sequence opens the lid, raises tube 01, approaches
with open jaws, closes them around the tube body, extracts the tube along its
35° axis, and withdraws the robot with the tube. The pusher retracts and the lid
closes only after the robot and carried tube have cleared the centrifuge.
After clearance confirmation, the robot turns the tube upright and travels to
output rack slot 01 while the station parks its pusher and closes/locks its lid.
The robot confirms rack support, opens its fingers and lifts away.
The tube stays in the rack. Playback can be paused/scrubbed; tube-handling and
rack-placement close-ups supplement the full assembly view.

| End time | State |
|---|---|
| 11.5 s | Lid fully open and held |
| 14.5 s | Tube elevated 16 mm axially, still supported by the pusher |
| 17.5 s | Gripper at the approach pose, 35 mm above the grasp along the tube axis |
| 20.5 s | Open fingers aligned around the tube body |
| 21.5 s | Jaws at 10.8 mm gap; synthetic grasp confirmation; rigid tube ownership transfers to gripper |
| 24.5 s | Tube extracted a further 45 mm along its axis; its tip is above the chamber rim |
| 28.5 s | Arm and retained tube at the withdrawal pose |
| 29.5 s | Synthetic independent workspace-clear confirmation |
| 30.5 s | Empty pusher parked; lid may start closing |
| 33.5 s | Tube upright outside the centrifuge; lid is closing |
| 37.5 s | Tube above empty output rack slot 01; lid is still closing |
| 41 s | Lid closed |
| 41.5 s | Tube bottom reaches the rack base through the guide bore |
| 42 s | Lid pins engaged independently of robot travel |
| 42.5 s | Synthetic rack-support confirmation; ownership transfers without a jump |
| 43.5 s | Fingers open after support confirmation |
| 47.5 s | Empty gripper withdrawn; tube remains in slot 01 |

Times, grasp and clearance confirmations are illustrative. They are not physical
sensor data or hardware timing predictions. The new scene is separate from the
earlier centrifuge-only demonstration, which deliberately reseated the tube.

<a id="cf01-robot-pickup-geometry-and-motion-source"></a>

### Geometry and motion source

The same six joint definitions, limits, vendor components and camera envelopes
are reused with **280 mm upper arm and 250 mm forearm** (previously 200/175 mm).
The synthetic equipment layout stores only parameter overrides of `model/robot.json`; it does not
duplicate the arm design. Native geometry, vendor mounting positions and joint
anchors follow those same dimensions. The generated `CF01_LongLink_Arm.FCStd`
retains the native parametric history of the arm variant. Full-pose inverse kinematics finds
joint configurations for the contact frame, with continuous nearby solutions
along approach, extraction, withdrawal and rack placement. A fixed grasp roll
avoids a joint-limit-induced wrist flip; consecutive trajectory samples are
checked for branch discontinuities. The tool points opposite the tube axis;
a fixed tool-to-tube transform established at grasp keeps the same
tube and cap rigidly attached to the moving gripper without a position jump.
No duplicate tube is left in the rotor.

The `parallel_tube_gripper_envelope` operation expands once into a mount,
actuator envelope, two stems and two contact pads for the native scene and
animation. Stepped fingers leave the wider cap free and touch the tube body
below the collar. It is a concept tool for this demonstration, not a selected
gripper, force/friction design or the still-excluded pipette attachment.
Its proposed flange-to-grasp distance is 55 mm; real fit, retention and grip
force remain open.

The revised pads are 5 × 6 × 9 mm, with the stepped stems retained farther
outboard to leave the cap free. The first bench-level trial passed intersection
checks but had a 2.9 mm finger/neighbor-cap gap. Slimmer, shorter pads improve
that approach gap; the final full-path audit must meet a 5 mm nominal equipment
clearance requirement. This is a geometric refinement, not a finger-strength
or grip-force qualification.

The local arm mounting frame is **[-330, 80, 0] mm, yaw −50°**, relative to
the centrifuge's bench frame. The base plate sits directly on the bench;
there is **no pedestal**. The longer-link variant resolves the bench-height
reach/joint-limit problem for this path. Bench attachment, tipping, link
deflection, actuator loads and settling remain unqualified; lower mounting
alone is not a measured stability result. The local frame is uncalibrated;
the L01 room layout and its older arm placement remain separate work.

The `guided_tube_rack` operation describes a 112 × 84 mm, 12-position rack
at **[-260, -280, 0] mm**, with 24 mm pitch. It has a 4 mm base supporting
tube bottoms, side rails, and a guide at 18–24 mm above the bench. Guide bores
are Ø13.8 mm with Ø18 mm conical entries. Against the illustrative Ø10.8 mm
tube body, the nominal radial clearance is 1.5 mm. The open fingers and seated
tube are checked against the actual rack bodies. Rack material and real tube
article fit remain open. This rack is a bottom-supported handling design;
the older TR01 cassette has tighter straight bores and is not substituted here.

The owner set **approximately 1 mm** as sufficient transport accuracy on
5 November 2026. This is a design target, not measured robot performance.
The larger rack entries accommodate that nominal lateral error; fine numerical
IK residuals are only solver checks. They do not establish hardware accuracy.
The existing centrifuge pocket has much less clearance, so pickup still needs
local alignment and/or compliant guidance. Pipetting accuracy requirements are
unaffected by the tube-transport target.

<a id="cf01-robot-pickup-reproduce-and-inspect"></a>

### Reproduce and inspect

```powershell
python scripts/build_centrifuge_robot_pickup.py
python -m unittest discover -s tests -v
```

The combined builder creates a new revision. It checks the upstream native-model
source and artifact hashes, generates the constrained trajectory, builds and
tests the FreeCAD scene, writes the animation, and independently constructs
the SolidCraft review poses from the shared sources. Source dimensions and protocol intent remain in JSON;
native snapshots are derived review files rather than additional master models.

- FreeCAD: seven posed scenes (`Closed`, `Grasp`, `Extracted`, `Withdrawn`,
  `ClosedAfterPickup`, `RackSeated`, `RackReleased`), a parametric long-link arm
  and `CF01_Robot_Pickup.FCMacro`. Run the macro to play or
  scrub all six robot axes, lid, pusher, jaws and carried tube. Its live GUI is
  prepared but has not been run here; the underlying native placements were checked.
- SolidCraft: `Grasp` and `RackReleased` review poses built using the existing
  native arm and centrifuge recipes, shared gripper/rack primitives and shared
  kinematics. These are **frozen review poses, not a native handoff motion study**.
  Per-body closure, identities, volumes and transformed centers are checked.
  A FreeCAD comparison is optional; it never provides geometry to this adapter.
- Interactive playback: meshes tessellated from the same native bodies plus the
  shared joint hierarchy and sampled joint trajectory. Vendor detail is clustered
  at 1 mm only for responsive display; exact BRep geometry remains in CAD checks.

The report distinguishes these backend capabilities. The same sampled arm
channel can now be exported for the existing ROS `FollowJointTrajectory` client;
see [the README instructions](../README.md#roboter-in-bewegung). This is not an integrated ROS scene or
hardware execution of the gripper/lid cycle. The separate SiLA simulator adapter
retains its own network tests and limits.

<a id="cf01-robot-pickup-executed-checks-and-limits"></a>

### Executed checks and limits

The trajectory samples all six original joint limits at 0.25-second intervals
and checks end-effector position/orientation. Independent forward kinematics
from the original robot module agrees with the cached trajectory calculations.
Tests verify no jump at handoff, fixed tube-to-gripper attachment afterward,
cap keep-out, axial extraction above the rim, and withdrawal before closure.

`check_centrifuge_robot_motion.py` adaptively subdivides the actual
joint-interpolated playback path, including lid motion, fingers and carried tube.
It refines whenever consecutive body-bound corners move more than 2 mm or a
robot/lid angle changes more than 1°. It checks the entire path against the
centrifuge, moving lid, rack and bench, plus nonadjacent arm links and cap/tool
clearance. Conservative oriented bounds use the existing L01 separation test;
overlapping bounds are refined by exact native BRep intersection. Exact closest
robot-to-equipment distances are recorded in `native-motion-validation.json`.
The current report gives the executed sample count, spacing and smallest gap.

The original 17 station poses and seven self/grip snapshots supplement that
audit. Intended tube/pad and flange mounting contacts, adjacent joint interfaces
and internal tool assembly are excluded. These are discrete checks, not a
continuous swept-volume proof or dynamic validation. The displayed slot-01
transfer is checked; full-rack occupancy and every loading order need further
path validation. Endpoint reachability alone does not qualify those paths.
All twelve approach and seated endpoints have numerical six-axis reach checks.

The endpoint protocol trace uses the existing local mock: an unconfirmed tube
absence cannot complete removal; `RetractLift` and `CloseLid` are refused while
the robot-clear input is false. Heartbeats remain active through the sequence.
Removal confirmation follows extraction, and clearance precedes pusher parking
and closure. This validates local handshake behavior, not real sensors or a
networked ROS/SiLA deployment. [Protocol/runtime boundaries](centrifuge-cf01.md#cf01-protocol).

SolidCraft MCP inspection was attempted, but its allowed paths exclude this
project directory. The existing reproducible local SolidCraft CLI adapter was
used for the two source-derived review scenes and cross-CAD measurements.

<a id="cf01-robot-pickup-zweisprachige-bedienung--bilingual-controls"></a>

### Zweisprachige Bedienung / Bilingual controls

Neu erzeugte HTML-Demos starten auf Deutsch. Über **Sprache / Language** lässt
sich jederzeit auf Englisch wechseln. Erklärungen, Bedienelemente, barrierefreie
Beschriftungen, Bewegungsphasen und Chargenzustände wechseln gemeinsam; Zeit,
Probenbesitz und eine laufende Wiedergabe bleiben erhalten. Proben-IDs wie
`Sample01` und die maschinenlesbaren Protokoll-IDs bleiben sprachunabhängig.
Das optionale Chargenpanel darf bei fehlenden oder fehlerhaften Daten ausfallen,
ohne die Bewegungsansicht zu blockieren.

Newly generated demos default to German. **Sprache / Language** switches all
explanations, controls, accessibility labels, motion phases and batch states
to English while preserving playback and sample ownership. Machine-readable
identifiers stay unchanged. An unavailable optional batch panel does not block
the motion view.

Die ursprünglichen `robot-demo.*` unter `docs/media/` bleiben der historische
Build. Das README verweist jetzt auf `robot-demo-overlap.*` mit eigener
Provenienz und überlappender Arm-/Deckelbewegung. Die Zuordnung des älteren
Builds zu seiner Quellrevision und frühere Prüfungen stehen im
[Nachtrag zur Claude-Prüfung](centrifuge-cf01.md#cf01-historical-review-2026-11-08).
Die aktuelle Berichtssemantik ist nachfolgend beschrieben.

Neue native Einzelberichte führen unter `collision_scope` die im Workspace
vorhandenen, aber nicht modellierten Geräte auf. NanoDrop und Qubit sind damit
nicht stillschweigend durch den CF01-Einzelbuild geprüft. Der Verweis auf den
Gesamtbericht zählt nur mit aktuellen Quellen und derselben gebundenen
Trajektorie; andernfalls bleibt `overall_workspace_validation_required` wahr.
Die genaue [Prüfumfangs- und Trajektorienbindung](synthetic-lab-workflow.md)
unterscheidet modellierte Körper von tatsächlich geprüften Paaren. Historische
Berichte und Medien bleiben unverändert.

<a id="cf01-robot-pickup-aktueller-lokaler-chargenlauf-buchführung-und-offene-übergaben"></a>

### Aktueller lokaler Chargenlauf: Buchführung und offene Übergaben

```sh
python3 scripts/run_cf01_rack_batch.py
python3 scripts/run_cf01_rack_batch.py --transport sila2
```

Beide Optionen führen lokale Vertragsdecoder aus. Die Berichte werden mit
Profilhash und Zeitstempel unter `exports/generated/cf01-rack-batch-*/` abgelegt.
Der Eingangszustand ist auf ein bereitgestelltes Rack und einen leeren Rotor
beschränkt. Fiktive Massen und zeitlose Roboterübergaben bleiben ausgewiesene
Mock-Annahmen. `initial_state` enthält nur den Anfangszustand; Massenquelle und
Roboterübergabezeit stehen getrennt in `mock_assumptions`. Die Testuhr wird beim
Warten auf beobachtbare Befehle einschließlich Schleudern und Bremsen fortgeschrieben.
Die Rotor-/Rackkapazität im Runner wird aus dem validierten Profil abgeleitet;
der CF01-Vertrag verlangt weiterhin eine vollständige Zwölferbeladung.

`handoff_policy` verlangt eine positive Roboterquittung und bei Übergaben
zwischen Greifer und Rotor zusätzlich die zugehörige Stationsbestätigung und
Belegungsprüfung. Vor der Roboterquittung wird die ausstehende Übergabe erfasst.

Für alle nicht beobachtbaren Befehle zählt nur eine Antwort mit dem
booleschen Feld `success: true`, einschließlich Reservierung, Heartbeat, Freigabe
und den beiden Stationsquittungen `confirm_seated` / `confirm_removed`. Negative, fehlende oder ungültige Antworten
lassen die Stationsquittung offen, auch wenn die Stationsaktion im Mock bereits
ausgeführt wurde. Eine passende Belegung ersetzt diese positive Quittung nicht.

Beobachtbare Befehle benötigen eine gültige Job-ID und eine bekannte Phase.
Der Runner wartet bis `succeeded`, prüft bei jedem Poll dieselbe Job-ID, sendet
Heartbeats und begrenzt die Wartezeit durch `command_execution` im Profil.
Leere Antworten oder ein unkorreliertes `running` bestätigen keinen Abschluss.
Während eines noch laufenden Deckel-/Index-/Heberbefehls beginnt keine Übergabe.
Die Frist läuft auf der expliziten Testuhr; Zeitüberschreitungen blockierender
SDK-/Netzwerkaufrufe müssten ein späterer echter Treiber zusätzlich behandeln.

Der Spin muss weiterhin `running` → `braking` → `succeeded` mit bestätigtem
Stillstand und gehaltener Bremse durchlaufen. Sein Fristbudget enthält die
Profil-Laufzeit und synthetische Bremszeit zusätzlich zum Befehlszeitbudget.
Der Trace kennzeichnet den angenommenen Spinauftrag als `submitted`; erst
`spin_complete` meldet den geprüften Abschluss. Ein Stopp wird ebenfalls als angenommener Auftrag (`submitted`) dargestellt,
weil seine Quittung keinen Stillstand belegt. Andere Befehle werden nach
bestätigtem Abschluss als `completed` aufgezeichnet.

Erst nach vollständiger Bestätigung wird die Buchführung weitergeführt:

| Berichtsfeld | Bedeutung |
|---|---|
| `inventory` | Buchführung der letzten vollständig bestätigten Übergaben; bei einer Störung keine Zusicherung des physischen Orts. |
| `world_inventory` | Separate synthetische Ortsbeobachtung nach den positiven Roboterquittungen; keine reale Identitätssensorik. |
| `pending_handoff` | Probe, Quelle, Ziel, Roboterquittung und Stationsquittung. `null` bei abgeschlossener Übergabe; `station_confirmation: null`, wenn keine Stationsquittung erforderlich ist. |
| `inventory_consistent` | Stimmen Buchführung und synthetische Ortsbeobachtung überein? Auch bei Übereinstimmung kann noch eine Quittung fehlen. |
| `ownership` | `pending` während der laufenden Übergabe, `unresolved` bei deren Abbruch oder widersprüchlichen Inventaren nach Fehler; nach abgeschlossenem Abgleich `confirmed`. Dies beschreibt die Zuordnung im Mock, keine Hardwarefreigabe. |
| `failure` | Auslösende Operation, Probe, ursprünglicher Fehlertyp/-code und Stationsfehler vor dem Stoppversuch. Der Fehler wird nicht durch einen späteren Stoppfehler ersetzt. |
| `stop_attempted` | Der Runner hat einen Stopp über den ausgewählten Vertragsdecoder versucht. |
| `stop_via_contract` | Der Decoder hat den Stopp erfolgreich beantwortet. Bei normalen erfolgreichen Läufen und fehlgeschlagenem Stoppversand `false`; kein Nachweis realen Stillstands. |
| `stop_error` | Fehler beim Stoppversuch bzw. dessen Protokollierung, falls vorhanden. |
| `station_inventory_check` | `mock_internal`: Belegung, Sitz und Masse werden aus `Simulator.slots` gelesen. Diese Prüfung ist nicht im gemeinsamen ROS-/SiLA-Zustand verfügbar. |

Beispiel: Der Roboter quittiert das Absetzen und Freigeben von `Sample01`, aber
die Stationsbestätigung schlägt fehl. Die synthetische Beobachtung führt die
Probe im Rotor, die letzte bestätigte Buchführung noch beim Greifer. Der Bericht
zeigt die offene Übergabe mit `ownership: unresolved` und behauptet keinen
weiterhin sicher gehaltenen Gegenstand. Dasselbe gilt umgekehrt bei einer
unbestätigten Rotorentnahme. Der Lauf stoppt ohne weitere Übergabe; automatischer
Wiederanlauf oder Abgleich mit einem realen Gerät sind nicht implementiert.

Lokale Platz-ID und Geometrie-ID werden gemeinsam von `rack_slots.places`
erzeugt. Der Runner schlägt numerische Plätze in Tabellen nach und interpretiert
keine Textpräfixe. Rackplätze werden als Instanz und relativer Platz ausgegeben, beispielsweise
`rack_instance: Rack` und `place_id: Slot01`. Der vorhandene Geometriebezug
`rack_place_id: CF01.OutputRack.Slot01` bleibt zusätzlich unverändert erhalten.
Dies ist eine lokale CF01-Zuordnung; getrennte Gefäß-/Probenidentitäten und eine
Anbindung an NanoDrop bleiben eigenständige Aufgaben.

Die HTML-Chargenanzeige benennt ihre Inventarfelder als Buchführung und zeigt
offene Übergaben samt fehlenden Quittungen auf Deutsch und Englisch. Die
unabhängige 47,5-s-Bewegung stellt solche Fehlerzustände nicht räumlich nach.
Historische Downloads unter `docs/media/` bleiben unverändert und enthalten
diese aktuelle Fehlerdarstellung nicht. Neu erzeugte lokale Demos verwenden
die aktuelle Vorlage; ein bestandener CAD-Aufbau ersetzt keine Geräteprüfung.

English: `inventory` records fully acknowledged handoffs, while
`world_inventory` records synthetic robot observations. A missing robot or
required station acknowledgement leaves `pending_handoff` and
`ownership: unresolved`; neither view is asserted to be a verified physical
location. Stop attempts and accepted stop responses are reported separately.
Slot occupancy checks use mock internals, not a real ROS/SiLA driver contract.
Required station acknowledgements must explicitly contain boolean `success: true`;
negative, missing or malformed replies leave the handoff unresolved.

<a id="cf01-robot-pickup-nachprüfung-der-befehlsabschlüsse-und-lf-migration"></a>

#### Nachprüfung der Befehlsabschlüsse und LF-Migration

Die aktuelle Software wartet bei beobachtbaren Befehlen auf den bestätigten
Jobabschluss. Negative Tests decken `running` ohne Job-ID, leere Antworten,
falsche Job-IDs, nie abgeschlossene Jobs sowie Heartbeat-/Reservierungs-/
Freigabequittungen ab. Bei erfolgreichen Läufen bleiben laufende Übergaben
`pending`; der Trace enthält keine `unresolved`-Einträge. Die lokalen Platznamen
werden zentral erzeugt und ohne Textparsing nachgeschlagen. Die Testparameter
für Masse und Übergabezeit stehen getrennt vom Anfangsinventar.

Der erste allgemeine Arm-Neuaufbau nach der LF-Migration ist nicht bestanden:
SolidCraft importierte fünf Servogehäuse offen und lieferte dafür keine
Schwerpunkte. Die FreeCAD-Prüfung dieses Versuchs besteht, aber der
CAD-Quervergleich bricht ab. ROS-Ausgabe, MB01 und davon abhängige Neuaufbauten
wurden danach nicht ausgeführt. Der lokale Bericht liegt unter
`exports/generated/2fa84f950446/build-attempt-status.json`. Historische
Buildberichte und README-Medien werden deshalb nicht als aktuelle Nachweise
umgeschrieben. Die neuen HTML-/Mock-Prüfungen verwenden ausdrücklich die
vorherigen Anzeigemeshe mit dokumentierter LF-Quelläquivalenz; dies ersetzt
keinen neuen bestandenen nativen CAD-Aufbau.

Die anschließende Importkorrektur verwendet die geschlossenen Hersteller-
Einzelteile auch im Arm-Builder. Der frische native Armvergleich in Revision
`2fa84f950446-r3` besteht einschließlich Gelenk- und Protokollstichproben;
ROS-Dateien sind neu erzeugt. Details und Körperzuordnungen stehen in der
[Servo-Integration](servo-integration.md#geschlossene-gehäuse-im-solidcraft-neuaufbau).
Die obigen historischen Medien, HTML-Prüfungen und ihr Nachweisstand bleiben
unverändert; der neue Armaufbau ist kein neuer Nachweis der CF01-Ladebahn.

<a id="cf01-robot-pickup-historischer-nachweis-des-restplans-bis-95471df"></a>

#### Historischer Nachweis des Restplans bis `95471df`

Der isolierte Stand aus `dc5df84` plus den Änderungen dieses Restplans besteht
261 Tests, davon 20 mangels gespeicherter Buildartefakte übersprungen. Die
21 gezielten CF01-Umgebungs-/Chargentests bestehen vollständig. Sie prüfen
Fehlertext, ursprünglichen Fehlertyp/-code, Operation und Probe sowie beide
halb bestätigten Übergaberichtungen, verlorene Stationsantworten und
fehlgeschlagene bzw. unbestätigte Stoppantworten. Alle 13 Schema-Dokumentprüfungen
und die Galerieprüfung bestehen. Das erneut erzeugte Chargendiagramm ist
bytegleich; nur seine aktuelle Quellenbindung wurde erneuert.

Die Browserprüfung besteht auf Deutsch und Englisch einschließlich zweier
echter Fehlerberichte, Sprachwechsel, optionaler Panelfehler und Breiten von
320/600/960 px ohne Konsolenfehler. Die neuen Fehleransichten wurden zusätzlich
visuell geprüft. Die lokale Demo und ihre Berichte liegen in der Revision
`cf01-batch-handoffs-64cd218f4b8a-20261108T173343413919Z` unter `renders/` und
`exports/generated/`; `batch-handoff-validation.json` bindet den Prüfstand.
Die CAD-Geometriequellen sind unverändert. Für diese HTML-Prüfung wurden die
vorhandenen nativen Anzeigemeshe mit dokumentierter Prüfsumme wiederverwendet;
ein neuer nativer CAD-Aufbau und eine erneute mechanische Prüfung wurden nicht
ausgeführt. Die Bewegung bleibt vom Chargenfehler entkoppelt.

<a id="cf01-robot-pickup-ergänzende-unabhängige-prüfung-am-8-november-2026"></a>

#### Ergänzende unabhängige Prüfung am 8. November 2026

Die Nachprüfung von `95471df` zeigte eine fehlende Erfolgsprüfung für
Stationsquittungen: Nach einer bereits ausgeführten Aktion konnte eine Antwort
mit `success: false` dennoch zum erfolgreichen Chargenabschluss führen. Die
Korrektur verlangt das boolesche `success: true` vor der Übernahme der Quittung.
Der ergänzte Regressionstest prüft 32 Fälle: beide Decoder, beide
Übergaberichtungen, Antworten mit und ohne vorherige Stationsausführung sowie
fehlende, leere, negative und nicht boolesche Antworten. Der Fehler wurde vor
der Korrektur reproduziert; danach bleiben solche Übergaben ungeklärt und der
Chargenlauf meldet keinen Erfolg.

Der korrigierte Gesamtstand besteht 291 Offline-Tests einschließlich aller
22 gezielten CF01-Umgebungs-/Chargentests. Die 13 Schema-Dokumentprüfungen und
die Galerieprüfung bestehen ebenfalls. Die Browserprüfung auf Deutsch und
Englisch verwendet vier Fehlerberichte für fehlende und negative Quittungen in
beiden Richtungen; Sprachwechsel, optionale Panelfehler und 320/600/960 px
werden ohne Konsolenfehler geprüft. Die Fehleransichten wurden visuell geprüft.
Der lokale Nachweis steht in
`exports/generated/cf01-review-95471df-20261108T190137002745Z/independent-review.json`;
die zugehörige HTML-Demo liegt im gleichnamigen Ordner unter `renders/`.
Die vorhandenen Geometriemeshe wurden nach Quellen- und Prüfsummenabgleich
wiederverwendet. Diese Nachprüfung erzeugt keinen neuen nativen CAD-, Bahn-,
Hardware- oder Netzwerknachweis; die oben dokumentierten Grenzen bleiben bestehen.

Während erfolgreicher Läufe enthält der Trace keine `unresolved`-Einträge.
Offene Quittungen einer gerade bearbeiteten Übergabe sind `pending`; eine
fehlgeschlagene Bestätigung macht daraus `unresolved`. Die Anzeige unterscheidet
„Übergabe läuft“ / „Handoff pending“ von der ungeklärten Zuordnung nach einem Fehler.

<a id="cf01-robot-pickup-synthetic-workspace-and-complete-local-batch"></a>

### Synthetic workspace and complete local batch

`model/synthetic-cf01-workspace.shared.json` composes an explicitly unbounded
space, reference-bank catalogue, furnishing instance and equipment layout.
There is no room shell. The standalone rack source is
`model/guided-tube-rack.shared.json`. The former bank dimensions, device world
poses are unchanged. The original 241-sample/60-second timing is preserved in
the historical media; the current independent-channel timing uses 191 samples
over 47.5 seconds.

Run `python3 scripts/run_cf01_rack_batch.py` (optionally `--transport sila2`) for
the twelve-sample local fixture. The profile declares an initially empty rotor,
a delivered rack and fictitious masses. All robot handoffs are abstract synthetic
confirmations. A separate world inventory checks actual indexed slots and sample
identities against the runner ledger and simulated station presence/mass. This
is no physical sample identification. Polling uses the local MockProtocol API;
commands and failure-stop requests pass through the selected contract decoder.
The explicit test clock advances while awaiting observable command completion, including spin/braking. Failures retain confirmed ledger,
synthetic observations and pending acknowledgements separately and produce a
failed report; they do not claim restored sample order.

The 47.5-second motion component (rotor slot 01 → rack slot 01) has its own timeline
and mock confirmations. The batch runner does not execute that component or
any loading/return path. The README HTML presents the two independently.

The earlier macOS STEP-snapshot build failed strict SolidCraft closure validation
for Rotor and Arm_A1/A3/A4/A5/A6_housing. That historical report remains failed;
the README media provenance continues to record that build honestly.
No network, hardware, live FreeCAD macro or transporter execution is established.

<a id="cf01-robot-pickup-independent-solidcraft-build-and-importer-workaround"></a>

### Independent SolidCraft build and importer workaround

```sh
python3 scripts/export_centrifuge_robot_pickup_solidcraft.py
```

This entry needs Python, SolidCraft CLI and the versioned shared sources/vendor
library. It does not read an FCStd, FreeCAD-generated scene STEP, display mesh,
or any previous CAD build report. It creates its own revision under
`cad/generated/centrifuge-cf01-solidcraft-*` and `exports/generated/`.
`cad/centrifuge-cf01/solidcraft-pickup-build-report.json` locates the result.

The rotor and other own geometry are constructed natively. For X2/X4 housings,
the current importer loses faces from the registered, fused STEP derivatives.
`solidcraft_vendor.py` instead imports the unchanged archived manufacturer STEP,
selects its exterior with the same CAD-independent partition used by the vendor
preparer, and retains the original closed case pieces. Internal parts are
omitted as before. The selected pieces make a native SolidCraft STEP round trip
with closure, volume, center and bounds checks. No hole patching or mesh
replacement is accepted. The original files and registered library remain intact.

The earlier reviewed scene has 235 CAD bodies for the same 223 semantic source
bodies: each X4 housing uses four original pieces and each X2 housing three.
New builds also isolate the seven X6 housing pieces, including both locating
sleeves, giving 241 native bodies. The shared source geometry is unchanged. A manifest
maps these parts to their original housing ID and arm link. Their original seam
overlaps remain; summed case-piece volume differs slightly from the old fused
representation. No claim about real mass or mechanical fits follows.

Both review poses check every body's identity, closure, volume and world center
against the unposed native construction and the shared transforms. Closure is
mandatory; relative volume integration error must stay below 0.01% and center
error below 0.001 mm (1 µm). These numerical integration tolerances are not
hardware accuracy claims. To add a
comparison with an independently generated FreeCAD metrics report:

```sh
python3 scripts/export_centrifuge_robot_pickup_solidcraft.py --compare-freecad /path/to/snapshot-metrics.json
```

The optional comparison uses the existing 0.1% volume and 0.02 mm center limits.
Only the complete multi-backend builder passes `--context`; standalone generation
does not require that context or FreeCAD. These checks do not validate a native
SolidCraft motion study or the full loading path. The standalone arm and MB01
builders now reuse the same vendor adapter; other legacy STEP-snapshot adapters
remain separate.

<a id="cf01-robot-pickup-concurrent-withdrawal-and-lid-closure"></a>

### Concurrent withdrawal and lid closure

The pickup source declares `timeline_semantics: independent_sparse_channels`.
Robot poses, station poses/coordinates and jaw settings each interpolate only
between their own keyframes. Ownership, rack support and workspace-clear events
are confirmations, not interpolated sensor readings. A station-only event does
not stop robot travel, and a robot-only event does not interrupt lid closure.

The arm starts its existing upright/rack path at 29.5 s after the synthetic
clearance confirmation. The pusher must still be parked before closure starts
at 30.5 s; lid motion ends at 41 s and locking at 42 s. There is no requirement
to hold the arm at the withdrawal pose until locking completes. Existing poses,
move durations, grasp and rack ownership rules are retained. The adaptive native
audit additionally checks the arm, tool, carried tube and cap against the moving
lid after clearance, including the declared 5 mm margin. This remains a discrete
geometric check, not a real safety sensor or continuous swept-volume proof.

The current native audit passed all 1,343 requested frames (1,338 distinct
geometric states). Its closest robot/equipment gap is 5.477 mm. After clearance,
the conservative arm/tool/tube/cap-to-lid distance bound is at least 70.694 mm;
all 299,782 relevant sampled pairs exceed the 5 mm requirement without needing
exact near-field refinement. These figures describe the nominal model only.

Current README media use a separate `robot-demo-overlap` revision. The original
`robot-demo` files and their failed historical SolidCraft import result remain
unchanged. The independent native SolidCraft adapter remains the supported
source-derived route; its frozen poses do not demonstrate live native motion.
<!-- cf01-source-end: pickup -->

<!-- cf01-source-begin: smooth -->
<a id="cf01-smooth-unloading"></a>

## Geglättete synthetische CF01-Entnahme

<!-- cf01-editorial-note -->
Der folgende Bewegungsabschnitt ist der führende Einstieg zur geglätteten Drei-Proben-Entnahme. Seine konkreten Build-, Medien- und Testzahlen dokumentieren den jeweils gebundenen Veröffentlichungsstand; diese Dokumentationskonsolidierung führt keine neue Bewegungs-, CAD-, ROS-, Netzwerk- oder Hardwareprüfung aus.
<!-- /cf01-editorial-note -->

Die [interaktive Ansicht](media/robot-demo-continuous-cfr.html) und das
[Video](media/robot-demo-continuous-cfr.mp4) zeigen drei aufeinanderfolgende
Entnahmen aus einem vollständig belegten Rotor nach dem synthetischen
Schleuderlauf. Sample01–03 gelangen in dieser Reihenfolge an ihre ursprünglichen
Plätze `Rack/Slot01`–`Rack/Slot03`; neun Gefäße bleiben im Rotor. Das ist ein
Entnahmeausschnitt mit eigener Modellzeit, kein ausgeführter vollständiger
Roboter-Chargenlauf. Transporter, Beladung und Zentrifugation werden hier nicht
animiert oder als Hardwarebefehle ausgeführt.

<a id="cf01-smooth-unloading-führende-quellen-und-zeitachse"></a>

### Führende Quellen und Zeitachse

`model/cf01-unload-demo.motion.json` referenziert die vorhandene
Entnahmeszene, `model/cf01-rack-batch.protocol.json` und die additive Quelle
`model/cf01-open-lid-index.protocol.json`. Das Schema
`model/cf01-unload-demo.schema.json` beschreibt den unterstützten Vertrag.
Raum, Bank, Geräte, zwölf Gefäße und ursprüngliche Rackplätze werden aus ihren
bestehenden Quellen übernommen. `scripts/cf01_unload_motion.py` verwendet den
vorhandenen Chargenrunner ausschließlich als synthetischen Nachweis für
Probenidentitäten und Rückgabereihenfolge. Dessen bisherige Befehlsfolge
beweist die neue offene Indexierung nicht; die Testzeit wird nicht mit der
Animationszeit gleichgesetzt.

Der Compiler erzeugt `program.json`: separate Arm-, Stations- und Greiferkanäle,
Ereignisse, Gefäßeigentümer und Prüfberichte. Arm und Station können parallel
fortschreiten. Der erste Index erfolgt mit dem unveränderten Basisbefehl bei
geschlossenem, verriegeltem Deckel. Danach öffnet der Deckel einmal und bleibt
zwischen den drei Entnahmen bei 105° geöffnet und gehalten. Nach jeder aus
der tatsächlichen Bahn abgeleiteten Freiraumbestätigung darf der Heber parken,
während der Arm ohne Halt zum Rack weiterfährt. Die nächste offene Indexierung
wartet auf die vorherige Rackabstützung und Fingerfreigabe, den geparkten Heber,
bestätigten Stillstand und freien Stationsbereich. Erst nach der letzten
Freigabe und dem letzten Heberrückzug schließt und verriegelt der Deckel.
Die bestehende Indexgrenze von 2 U/min bleibt erhalten. Der Deckel behält seine
nominale Grenze von 10 °/s; sie wird nicht für einen kürzeren Clip erhöht.

Die Präsentation hebt das jeweilige Gefäß unverändert um 16 mm entlang seiner
geneigten Achse an. Das entspricht 13,106 mm vertikalem Hub, nicht 16 mm in Z.
Sobald Hub und vorherige Armrückfahrt beendet sind, beginnt die Anfahrt;
eine zusätzliche reine Präsentationspause entfällt.
Die Detailkamera zeigt das angehobene Gefäß während der Anfahrt.
Greifen, Freiraumfreigabe und Rackabstützung besitzen eigene synthetische
Bestätigungen. Gefäß und Kappe folgen genau einem Besitzer: Rotor, Greifer
oder ursprünglicher Rackplatz. Bereits abgelegte Gefäße bleiben dort stehen.

Auch die leere Anfahrt und Rückfahrt enthalten keine Zwischenruhepunkte mehr.
Die Richtungswechsel bei `pregrasp` und `rack_approach` erhalten eine räumliche
C2-Bézierverrundung. Die letzten 25 mm der Greifanfahrt bleiben axial; die
ersten 96 mm der Rückfahrt bleiben vertikal und ohne Werkzeugneigung. Danach
wechselt die Neigung durchgehend bis zum Fahrtende. Die anschließende Greif- beziehungsweise vorausgehende
Freigabebewegung bleibt eine eigene Operation. Die tatsächlichen PVA-Kurven
werden mit denselben vorläufigen Gelenkgrenzen geprüft; das Kein-Halt-Kriterium
isoliert auch in diesen sechs leeren Bahnen die beiden ruhigen Endbereiche.

Das neue Programm dauert **99,674 s** und enthält **3.876 Armknoten**.
Gegenüber der vorherigen lokalen Fassung mit Zwischenhalten und Deckelzyklen
je Probe sind das 13,2 % weniger als deren 114,823 s. Die erste durchgehende
Fassung dauerte 80,759 s. Die zusätzlichen Verrundungen der leeren Fahrten
benötigen bei denselben Gelenkgrenzen mehr Zeit, obwohl die drei Vorführpausen
entfallen. Die gewählte Kurvenform wird gleichmäßig gegen die tatsächlichen
Grenzen skaliert; eine globale Zeitoptimierung ist nicht implementiert. Der faire Vergleich
vom ersten Griff bis zur bestätigten Rackabstützung beträgt dagegen
11,611 s statt 11,731 s, also rund 1,0 % weniger. Die anschließende
Stützbestätigung dauert unverändert 0,25 s; sie gehört nicht zur bewegten Bahn.

| Probe | Griff → Rackankunft | Griff → bestätigte Rackabstützung |
|---|---:|---:|
| Sample01 | 11,361 s | 11,611 s |
| Sample02 | 11,327 s | 11,577 s |
| Sample03 | 11,408 s | 11,658 s |

Alle drei beladenen Fahrten werden durch die konservative translatorische
Gefäßruckschranke begrenzt: etwa 4.999,85 mm/s³ bei einer unveränderten Grenze
von 5.000 mm/s³. Das ist eine obere Intervallgrenze, kein gemessener
Hardware-Spitzenwert. Die Vergleiche betreffen Modellzeiten, keinen Hardware-
oder Durchsatzbenchmark. Alle Grenzwerte bleiben unverändert: unter anderem
1 rad/s für leere und 0,5 rad/s für beladene Armfahrt.

<a id="cf01-smooth-unloading-ausdrückliche-opt-in-erweiterung"></a>

### Ausdrückliche Opt-in-Erweiterung

`scripts/cf01_open_lid_index.py` erweitert den vorhandenen Simulator um genau
`index_open_lid(slot)`. Die neue Protokollquelle pinnt die unveränderte Station
und ihren Basisvertrag. Nur die ausdrücklich gewählte Unterklasse
`OpenLidIndexSimulator` kennt den Befehl. Sie verwendet die vorhandenen
Prädikate für frische Rückmeldung, Stillstand mit gehaltener Parkbremse,
freien Arbeitsbereich, geparkten Heber und sitzende vorhandene Gefäße. Dazu
kommen Offen-Endschalter, gesunde gehaltene Deckelbremse und Fehlerfreiheit.
Die Indexgrenze wird aus `handling.index_limit_rpm` der Station referenziert.

Der Standardsimulator und die bestehenden Befehle bleiben unverändert.
Insbesondere verlangen `index` und Schleuderstart weiter den geschlossenen,
verriegelten Deckel. Die Erweiterung registriert keinen ROS-/SiLA-Befehl und
ändert weder `MockProtocol` noch den bisherigen Chargenrunner oder den
gemeinsamen CF01-/NanoDrop-/Qubit-Workflow. Der neue Befehl wird dort nicht
automatisch ausgeführt. Ein eigener Replay gegen die Opt-in-Unterklasse
prüft die neue Stationsfolge vom synthetischen Zustand „voller Rotor nach
Spin“ aus; seine logische Uhr ist kein Watchdog- oder Hardware-Timingnachweis.
Die [CF01-Protokolldokumentation](centrifuge-cf01.md#cf01-protocol) trennt Erweiterung
und Basisvertrag.

<a id="cf01-smooth-unloading-glatte-bahn-und-vorläufige-grenzwerte"></a>

### Glatte Bahn und vorläufige Grenzwerte

Die ganze beladene Fahrt ist eine Referenzbahn vom bestätigten Griff bis zur
Rackankunft. Auf die axiale Gerade folgen krümmungsstetige Verrundungen mit
den vorhandenen `withdrawn`- und `upright`-Bezugspunkten als Kontrollen;
die letzte Gerade führt senkrecht in den Rackplatz. Diese Kontrollen sind
keine Zwischenhalte. Die Gefäßneigung bleibt auf dem axialen Anteil bei 35°,
geht monoton auf 0° über und bleibt während der vertikalen Ablage aufrecht.
Ein begrenztes Zeitgesetz mit Geschwindigkeitsplateau, ein durchgehender
IK-Durchlauf, ein Kurvenfit und eine gemeinsame Zeitskalierung verbinden die
gesamte beladene Strecke. Ruhe ist nur an Griff und Rackankunft vorgesehen;
die anschließende Stützbestätigung ist eine getrennte Haltezeit.

Die lokalen Ableitungen liefern die Position-/Geschwindigkeit-/
Beschleunigungsknoten (PVA) der tatsächlich ausgewerteten stückweisen
Quintiken. Die Kurve ist **C2**: Position,
Geschwindigkeit und Beschleunigung sind stetig. Der Ruck hat endliche,
begrenzte einseitige Werte, kann an Knoten jedoch springen. Eine C3-Kurve oder
global zeitoptimale Bahn wird nicht behauptet.

Axiale Entnahme und vertikale Rackablage behalten ihre geometrischen
Richtungen, erhalten aber keine ruhenden Grenzen zum Transit.
`removed_confirmed_s` und `clear_s` sind Schwellzeiten der tatsächlichen
FK-Kurve; der Arm hält dafür nicht an. Die Kriterien betreffen axiale
Entnahme und das Erreichen der quellgebundenen Freigabegrenze. Sie sind
synthetische Bestätigungen, keine gemessenen Sensorwerte.
Die leere Rückfahrt beginnt an der Rackablage, hebt zunächst vertikal ab und
führt über die verrundete Ecke der Rackannäherung zum Rückzugspunkt.
Stations- und Greiferachsen verwenden begrenzte S-Kurven. Eine allgemeine
automatische Wegsuche oder Glättung beliebiger Kollisionskorridore ist nicht
implementiert.

Der folgende Stand ist eine lesbare Übersicht; maßgeblich bleibt das Profil:

| Größe | Geschwindigkeit | Beschleunigung | Ruck |
|---|---:|---:|---:|
| Armgelenk, beladen | 0,5 rad/s | 2 rad/s² | 20 rad/s³ |
| Armgelenk, leer | 1 rad/s | 2 rad/s² | 20 rad/s³ |
| Gefäßpunkte, Translation | 200 mm/s | 500 mm/s² | 5.000 mm/s³ |
| Gefäßorientierung | 30 °/s | 90 °/s² | 900 °/s³ |
| Stationsdeckel | 10 °/s | 180 °/s² | 1.800 °/s³ |
| Rotor beim Indexieren | 2 U/min | 30 °/s² | 300 °/s³ |
| Lineare Stations-/Greiferachsen | 50 mm/s | 200 mm/s² | 2.000 mm/s³ |

`qualified: false` und `biological_tolerance: null` sind ausdrücklich Teil des
Vertrags. Die Werte sind vorläufige synthetische Einstellungen. Sie belegen
weder geringe biologische Schädigung noch mechanische Tragfähigkeit oder
Regelgüte. Flüssigkeitsbewegung, Verschlusskräfte, Greifkraft, Resonanzen und
Schwingungen der gemeinsamen Bank werden nicht modelliert.

Die gemeinsame Mathematik in
`ros2_ws/src/solidcraftbot_ros/solidcraftbot_ros/motion.py` prüft die
Gelenkpolynome einschließlich innerer Extrema. `scripts/sample_motion.py`
überträgt Ableitungen über die Kinematik und begrenzt Punkt- und Winkelbewegung
mit konservativen numerischen Intervallen. Acht umschließende Gefäß-/Kappenecken
und drei axiale Bezugspunkte berücksichtigen den vollständigen Körper statt
nur des TCP. Die adaptive FK-Prüfung beginnt mit vier Teilintervallen je
Quintikintervall und verfeinert jeweils den Abschnitt mit der größten
konservativen Zeitskalierungsanforderung, höchstens bis 256 Teilintervalle.
Sie endet, wenn dieser obere Skalierungsfaktor höchstens das 1,1-Fache des
aus tatsächlichen Auswertungen gewonnenen unteren Faktors beträgt oder der
aktuell begrenzende Abschnitt die Auflösungsgrenze erreicht. Die zurückgegebene
Schranke bleibt die Vereinigung aller Intervallhüllen; Abtastwerte steuern nur
die Verfeinerung und ersetzen keine obere Grenze. Das Profil führt Start-
und Höchstauflösung ausdrücklich. Die Bahntoleranz wird zusätzlich an vier
inneren Stellen jedes Quintikintervalls geprüft. Diese numerischen Grenzen
sind kein formales Gleitkommazertifikat. Zeitdehnung reduziert Geschwindigkeit,
Beschleunigung und Ruck entsprechend mit 1/T, 1/T² und 1/T³.

Beim Einlesen eines gespeicherten Programms berechnet
`scripts/cf01_unload_validation.py` die Grenzen aus seinen tatsächlichen
PVA-Kurven erneut. Kopierte Segmentberichte gelten nicht als Dynamiknachweis;
auch beladene Intervalle, Stationsachsen, Greifer und Gefäßhüllen werden geprüft.
Das Kein-Halt-Kriterium betrachtet die tatsächliche Gefäßgeschwindigkeit und
die Norm der Gelenkgeschwindigkeiten: Unterhalb der Profil-Schwellen sind nur
ein zusammenhängender Anfangs- und ein Endbereich der beladenen Fahrt erlaubt.
Ein eingefügter Ruhepunkt oder ein inneres ruhendes Intervall wird abgewiesen.
Die numerische Wurzelisolation wird vorwärts und rückwärts im jeweiligen
Quintikintervall ausgewertet, damit Auslöschung nahe dem Ende keinen sehr
kurzen ruhigen Endbereich verschwinden lässt. Die Schwellen bleiben gleich.
Axial-/Vertikalanteile und Ereignisprädikate werden aus der FK nachgerechnet;
Stationsbewegungen benötigen die vorgesehenen Ruhe- und Freiraumbedingungen.
Das Ergebnis wird getrennt vom nativen Geometriebericht gespeichert.


<a id="cf01-smooth-unloading-native-geometrie-und-prüfgrenzen"></a>

### Native Geometrie und Prüfgrenzen

`scripts/cf01_unload_geometry.py` übernimmt ausschließlich unveränderte
Konstruktionsgeometrie aus geprüften, quell- und artefaktgebundenen Berichten.
Der historische CF01-Bericht, sein unveränderter Stations-Unterbericht und
die nativen Dateien werden per SHA-256 geprüft. Der Stations-Unterbericht
liefert auch die Bindung des Mechanikhelfers, die im älteren übergeordneten
Bericht fehlte. Er verändert dessen historische Prüfsummen nicht. Alte
Weltposen werden zuerst mit ihrer damaligen Zeitachse normalisiert; danach
werden alle zwölf vorhandenen Gefäß-/Kappenpaare durch das neue Programm
transformiert. Die Instrumentgeometrie stammt aus dem geprüften gemeinsamen
NanoDrop-/Qubit-Szenenbericht. Ein frischer Checkout muss diese geprüften
lokalen Basis- und Instrument-Builds zunächst erzeugen.

Ein neuer Lauf von `scripts/check_cf01_unload_motion.py` prüft die neue Bahn
und schreibt `native-motion-validation.json`. Alte Kollisionsberichte werden
nicht als neuer Bewegungsnachweis übernommen. Er berücksichtigt:

- alle zwölf Gefäße und Kappen gegen Rotor, Rahmen, Deckel, Rack, Nachbarn und
  Roboter; belegte Rackplätze bleiben Hindernisse;
- native Körperüberschneidungen und mindestens 5 mm Abstand des Roboters zur
  Ausrüstung, mit gezielten Ausnahmen für die vorgesehenen Greifkontakte;
- in jedem Stationsbewegungsfenster Abstand für Arm, Werkzeug und getragenes
  Gefäß zu den jeweils bewegten Gruppen: Rotor einschließlich rotoreigener
  Gefäße, Heber und zuletzt Deckel; jedes Fenster erhält eigene Prüfzähler;
- den durchgehend bei 105° offenen Deckel als Hindernis, auch wenn er gerade
  nicht bewegt wird;
- beide Messgeräte in ihren quellgebundenen Posen sowie konservative Hüllen
  des gesamten NanoDrop-Hebelbereichs; die Qubit-Haube bleibt in ihrer
  eingefrorenen Quellpose.

Nur die beiden Pads gegenüber dem aktiven Gefäß erhalten die vorgesehene
Greifkontakt-Ausnahme. Rackabstützung wird auf eine tatsächliche dünne
Kontaktzone an der Basisoberkante begrenzt. Alle Kanalknoten und Ereignisse
einschließlich Eigentümerwechseln werden geprüft; adaptive Zwischenstellungen
begrenzen den diskreten Schritt der Körperhüllen auf 2 mm und von Arm-, Rotor-
und Deckelwinkeln auf 1°. Konservative AABB-Abstände oberhalb der geforderten
Marge genügen als Trennungsnachweis; darunter verfeinert die native BRep-Distanz.
Das ist keine kontinuierliche Kollisionsfreiheit oder Sensor-/Schutzfunktion.

Der aktuelle native Bericht im Format
`solidcraftbot.cf01-unload-native-motion-validation/2` besteht mit 12.082
angeforderten Frames und 12.044 unterschiedlichen Zuständen, ohne
Kollisions- oder Abstandsfehler. Die Dynamikprüfung bestätigt das Kein-Halt-
Kriterium für alle drei tatsächlich getragenen Kurven; sechs zusätzliche
Leerfahrten bestehen die eigene Istkurvenprüfung. Die Browserprüfung
besteht 112 Python-/JS-Vergleiche einschließlich Gelenkgeschwindigkeit,
Entnahme-/Freigabezeitpunkten und je drei inneren Zeiten pro beladener Fahrt;
alle drei Hübe sowie Deutsch/Englisch und drei Fensterbreiten sind geprüft.

Die veralteten Instrumenten- und Mehrarm-Aufstellungsnachweise wurden durch
die neuen nativen Revisionen `synthetic-lab-scene-a3853d4f9bf1-r6` und
`two-arm-analytics-1f0ba0354e58-r3` ersetzt. Ihre 19 gezielten Tests bestehen.
Die Galerie enthält auch die zuvor fehlenden Laborglas- und Gerätebilder.
Diese separaten statischen CAD-Prüfungen sind kein Bewegungsnachweis für
weitere Roboterabläufe; der vollständige Teststand steht in der neuen
[Medienprovenienz](media/robot-demo-continuous-cfr.provenance.json).

Der neue Build erzeugt zwei abgeleitete native FreeCAD-Prüfstellungen:
`CF01_Unload_PresentedSample2.FCStd` und `CF01_Unload_Final.FCStd`. Eine neue
native SolidCraft-Bewegungsstudie wird nicht erzeugt. Die unabhängige
SolidCraft-Konstruktionsquelle und die bisherigen statischen Prüfstellungen
bleiben bestehen. Insbesondere bleiben die dokumentierten Fehler und Grenzen
des historischen STEP-Gesamtimports erhalten; siehe
[Medienhistorie](media/README.md) und
[unabhängiger SolidCraft-Aufbau](centrifuge-cf01.md#cf01-robot-pickup-independent-solidcraft-build-and-importer-workaround).

<a id="cf01-smooth-unloading-reproduzieren-und-getrennt-auswerten"></a>

### Reproduzieren und getrennt auswerten

Mit vorhandenen geprüften lokalen Geometrie-Builds und FreeCAD:

```bash
python3 scripts/build_cf01_unload_demo.py
```

Der Einstieg findet FreeCAD über die gemeinsame Werkzeugauflösung oder
`--freecad-python`. Er erstellt eine neue Revision unter `exports/generated/`,
`cad/generated/` und `renders/`; `tmp/cf01-unload-context.json` verweist auf den
letzten Lauf. `--prepare-only` erzeugt Programm und Browseransicht ohne einen
bestandenen nativen Bewegungsnachweis. `--program` übernimmt ein bereits
kompiliertes Programm nur mit weiterhin passenden Quellen. Berichte,
Modellartefakte und Provenienz müssen dieselbe Revision und Prüfsummen binden.
`--finish-existing <context.json>` erlaubt eine neue Browserfassung nur bei
unverändertem Programm, nativen Prüfern, Geometrienachweisen, Nachbargeräten
und Prüfstellungsdateien. Diese Bindungen werden vor und nach dem Rendern
kontrolliert; die Dynamikprüfung wird aus den Kurven neu abgeleitet. Der alte
native Bericht bleibt dabei bytegenau erhalten.


Die Browseransicht `renders/<revision>/cf01-unload-demo.html` wertet dieselben
PVA-Polynome aus; zusätzliche Vorschau-Samples dienen nur der Bildauswahl.
Die kuratierte [Medienprovenienz](media/robot-demo-continuous-cfr.provenance.json)
bindet die README-Medien an die tatsächlich ausgeführten Prüfungen. Ein
beschleunigter Videoclip ändert die Modellzeit oder Grenzwerte nicht.
Das aktuelle Video verdichtet die 99,674 s Modellzeit auf 45 s. Der Export
wertet 900 gleichmäßig verteilte Modellzeiten aus und codiert mit festen
20 Bildern/s. Die Renderdauer beeinflusst die Bildabstände nicht; jedes Bild
erhält Quellzeit und PNG-Prüfsumme im lokalen Frame-Manifest.

Der separate ROS-Export übernimmt ausschließlich den Armkanal. In den folgenden
Befehlen `<revision>` durch den tatsächlichen Buildordner ersetzen:

```bash
python3 scripts/export_cf01_unload_ros2.py \
  --program exports/generated/<revision>/program.json \
  --output exports/generated/<revision>/ros2-scenarios.json
PYTHONPATH=ros2_ws/src/solidcraftbot_ros python3 -m solidcraftbot_ros.demo \
  --config exports/generated/<revision>/ros2-scenarios.json \
  --scenario cf01_unload_three_samples --dry-run
```

Die vollständigen PVA-Knoten entsprechen der [quintischen Spline-Interpolation
des ROS Joint Trajectory Controllers](https://control.ros.org/jazzy/doc/ros2_controllers/joint_trajectory_controller/doc/trajectory.html).
Der Export prüft die Nanosekundenquantisierung und die daraus entstehenden
Polynome: Innere PVA-Werte werden an den gerundeten Zeiten neu ausgewertet;
Ruheendpunkte bleiben erhalten. Das Kein-Halt-Kriterium wird auch auf den
ROS-quantisierten Punkten geprüft.
Der Quellkanal und der geprüfte ROS-Export enthalten jeweils 3.876 Armknoten;
der vorhandene Client führt den Daten-Dry-run über 99,673878165 s erfolgreich
aus. Die Zahl der Exportpunkte ist mit dem Armkanal identisch.
`compiled_program_sha256` bindet sortiert und kompakt serialisierte JSON-Daten
(`json.dumps(..., sort_keys=True, separators=(',', ':'), allow_nan=False)`);
der Byte-SHA der formatierten Programmdatei ist separat dokumentiert.
Der Client verlangt vollständige PVA-Knoten und passende Grenzen.
Ein tatsächlicher Trajektoriencontroller muss Splines verwenden; seine
Live-Konfiguration und die passende Roboterbeschreibung sind nicht geprüft.
Export, Nachrichtenerzeugung und Dry-run sind Datenprüfungen. ROS-Laufzeit,
Hardware und eine integrierte CF01-/Greifer-/Sensorsteuerung sind damit nicht
nachgewiesen. Insbesondere gibt der Arm-Export allein keinen gesamten
Laborablauf frei.

Das zeitgebundene Armprogramm besitzt noch keinen von Stations- oder
Sensorzuständen abhängigen Abbruch- und Rückführzweig. Ein erfolgreicher
Replay, Dry-run oder eine diskrete Kollisionsprüfung ergänzt diesen Zweig
nicht. Globale Zeitoptimalität, biologische Verträglichkeit und reale
Hardware-Sicherheit werden nicht zugesichert.


<a id="cf01-smooth-unloading-übergreifende-prüfgrenzen-dieses-builds"></a>

### Übergreifende Prüfgrenzen dieses Builds

Die neue Medienprovenienz bindet die ausgeführten Bewegungs-, Mathematik-,
Opt-in-, ROS- und Gesamtsuite-Prüfungen an ihre tatsächlichen Quellen und
Artefakte. Loopback-Tests laufen außerhalb der Sandbox; ausdrücklich
übersprungene SiLA-Netzwerk-, .NET- und Laufzeitprüfungen zählen nicht als
bestanden. Im isolierten Veröffentlichungsstand sind alle 788 entdeckten
Tests abgedeckt: 766 bestanden, 22 ausdrücklich übersprungen, keine
Fehler. Hauptlauf und Galerie-/Bibliotheksprüfungen liefen getrennt; 14 zunächst
wegen fehlender lokaler ROS-Builddateien übersprungene Prüfungen wurden nach
Übernahme dieser Artefakte erfolgreich nachgeholt. Das ist keine ROS-Laufzeit-
oder Hardwareprüfung. Die nativen L01-Nachweise stehen separat im
[L01-Bericht](lab-transfer-l01.md#validation-boundary).
Historische Provenienzen behalten ihren damaligen Teststand,
einschließlich der inzwischen separat behobenen CAD-/Galeriebefunde.
<!-- cf01-source-end: smooth -->

<!-- cf01-source-begin: review -->
<a id="cf01-historical-review-2026-11-08"></a>

## CF01: Nachtrag zur Claude-Prüfung vom 8. November 2026

<!-- cf01-editorial-note -->
**Historischer Anhang:** Der vollständige Nachtrag vom 8. November 2026 bleibt als Bericht über den ausdrücklich benannten Commit und seine damaligen Ausgaben erhalten. „Aktuell“, „neu“ und Zukunftsaufgaben im folgenden Originaltext beziehen sich auf diesen damaligen Prüfstand, nicht auf den heutigen Gesamtumfang des Repositories.
<!-- /cf01-editorial-note -->

Dieser Nachtrag trennt die aktuelle Umsetzung von der unveränderten historischen
README-Mediendemo. Die Prüfung betrifft die synthetische Umgebung und den lokalen
Chargenlauf; sie erweitert weder Hardware- noch Netzwerk- oder Bahnunterstützung.
Die angebotene erneute Claude-Konsultation wurde auf Eigentümerwunsch ausgelassen.

Dieser Nachtrag hält den Prüfstand von Commit `b80461d` fest. Die damaligen
Erfolgstests belegten noch keine eindeutige Zuordnung bei halb bestätigten
Übergaben; die zweite Claude-Prüfung hat diese Lücke aufgezeigt. Die korrigierte
aktuelle Semantik steht in der
[Baugruppendokumentation](centrifuge-cf01.md#cf01-robot-pickup-aktueller-lokaler-chargenlauf-buchführung-und-offene-übergaben).
Die nachfolgenden damaligen Build- und Mediennachweise bleiben historische
Nachweise und werden nicht als erneute Prüfung der neuen Fehlersemantik ausgegeben.

<a id="cf01-review-2026-11-08-abgleich-der-hinweise"></a>

### Abgleich der Hinweise

| Claude-Punkt | Berücksichtigung |
|---|---|
| A1: Kommunikationsausfall | Bereits vorhandene Fehlerbehandlung mit Vertrags-Stopp und `BatchError`; Rückmeldung `None` sowie Verbindungs-, Feld- und Typfehler werden getestet. |
| A2: Identität als Echo | Standardlauf verwendet die separate synthetische Weltinventur, tatsächlichen Rotorindex sowie Stationsbelegung und Fixture-Masse. Das injizierbare Echo bleibt ausschließlich ein ausdrücklich benannter Testhelfer. |
| A3: Rückgabe und Bewegungsbaustein | Alle Chargenübergaben bleiben abstrahiert; der 60-s-Bewegungsbaustein läuft unabhängig. Keine Kopplung einer beliebig zugeordneten Probe an Rotorplatz 01. |
| A4: Mediennachweise | Historische Medien und Prüfsummen bleiben erhalten; ihr vollständiger Quellstand ist unten gebunden. Aktuelle Ausgaben und Prüfungen werden separat erzeugt. |
| A5: Unvollständige Zentrifugation | Explizite Folge `braking` → `succeeded`; Tests für Stopp, Encoder- und Bremsfehler verhindern die Rückgabe. |
| B6: Vertragsdecoder | Runner und Decoder verwenden dieselbe Feldnamenabbildung `centrifuge_protocol.wire`. Stopp läuft über den Decoder; Job-Polling bleibt ausdrücklich lokal und prüft keine Transportserialisierung. |
| B7: Bericht und tatsächliches Profil | Effektives Profil samt Hash, Implementierungsprüfsummen und revisionierte Ausgaben sind vorhanden. Die neue gemeinsame Platzabbildung ist ebenfalls gehasht und im Bericht enthalten. |
| B8: Mock-Annahmen | Leerer Rotor, fiktive Profilmasse und zeitlose Übergaben stehen im Profil und Bericht. Testzeit vergeht nur beim Schleudern und Bremsen. |
| B9: Instanzvertrag | Geräte verwenden `host` und die eingeschränkte gemeinsame `equipment_instance`-Definition im Baugruppenvertrag; Laufzeitprüfung verwendet `assembly.validate_instance`. Armparameter laufen weiterhin über `robot_spec.load` / `parameter_variant`. |
| B10: Geräte und Exportkontext | Die Pflicht zu Arm/CF01/Rack liegt im CF01-Szenenadapter. Der Umgebungsloader erzwingt diese Geräteliste nicht. `_workspace` wird nicht mehr in Szene, Mesh oder HTML geschrieben. |
| B10: Quellen und Plätze | Führende Szene referenziert das Protokoll; Arm- und CF01-Quellen stammen aus Equipment-Assets. `rack_slots.places` erzeugt dieselben stabilen Platz-IDs für Geometrie, Chargenzuordnung und Übergabeprotokoll. `slot_order: row_major` steht in Rackquelle und Schema. `rack` war bereits ein Pflichtfeld. |
| B10: HTML und Sprachen | Deutsch ist Standard; Erklärungen, Bedienung, barrierefreie Labels und Zustände lassen sich auf Englisch umschalten. Fehlendes oder beschädigtes Chargenpanel blockiert die Bewegung nicht. Sprache und laufende Wiedergabe sind unabhängig. Technische IDs bleiben stabil. |
| B10: Regression und Katalog | Numerischer Vergleich mit absoluter Toleranz 1e-8 und relativer Toleranz 1e-12; Struktur und IDs bleiben exakt. Fixture-Herkunft `ad9de56` / Szene `05dba7428daa` bleibt dokumentiert. Der eigene Referenzbankkatalog schützt weiterhin die unveränderte L01-Revisionsbindung. |

Die Vereinfachungen unter C bleiben bestehen: vollständige Zwölferbeladung,
Balanceprüfung durch CF01, Station am Weltursprung, eine Referenzfläche ohne
Raumschale, synthetische Übergaben und fiktive Qualifikation. Die Erweiterungen
unter D bleiben Zukunftsarbeit: vollständige Roboterbahnen, physische Identität,
Netzwerkserver, Wiederanlauf, Teilbeladung und andere Aufstellungen.

<a id="cf01-review-2026-11-08-historische-medien-provenienz"></a>

### Historische Medien-Provenienz

Unverändert bleiben `docs/media/provenance.json`, `robot-demo.html`,
`robot-demo.png` und `robot-demo.mp4`. Sämtliche **50 Quellprüfsummen** der
Provenienz passen exakt zu Commit
`e5eedc828a2bb1ae4e903378ec9359644bd8a467`.
Die drei Medienprüfsummen passen weiterhin zu den versionierten Dateien.
Die alte fehlgeschlagene SolidCraft-Importprüfung bleibt fehlgeschlagen; neue
native Prüfungen ersetzen diesen historischen Befund nicht.

SHA-256 der unveränderten `docs/media/provenance.json`:

```text
80e954c9b2b7a4a16ee40f280382e0a134702b9edcefa6d01b6d267e45e5160c
```

Zur unabhängigen Nachprüfung lassen sich die mit `source_files_sha256` benannten
Dateien durch `git show e5eedc8:<Dateipfad>` lesen und ihre Bytes gegen den
jeweiligen gespeicherten SHA-256 vergleichen. Die aktuelle Arbeitskopie ist kein
Ersatz für diese historische Quellrevision.

<a id="cf01-review-2026-11-08-aktuelle-ausgaben-und-prüfung"></a>

### Aktuelle Ausgaben und Prüfung

Der neue lokale Aufbau ist `centrifuge-cf01-robot-19cf33001d73-r2`.
Seine Dateien liegen unter `cad/generated/`, `exports/generated/` und `renders/`;
sie werden nicht als zusätzliche führende Quellen versioniert. Die neue
zweisprachige Demo liegt unter
`renders/centrifuge-cf01-robot-19cf33001d73-r2/cf01-robot-pickup.html`.

Der Browsercheck ist mit `node tests/check_cf01_demo.cjs <HTML-Datei>`
wiederholbar; optional folgen der Playwright-Modulpfad und das Chrome-Programm.
Er kontrolliert Deutsch/Englisch, Sprachwechsel bei laufendem Chargenpanel,
Besitz bei 0/15/30/45/60 s, wiederhergestellte Rackreihenfolge, fehlende und
beschädigte Chargendaten sowie Breiten von 320/600/960 px ohne Konsolenfehler.
Die beiden Sprachfassungen wurden zusätzlich als Bilder visuell geprüft.

Die Galerie wird nur für die drei betroffenen Einträge `synthetic-workspace`,
`guided-rack` und `rack-batch` erneuert und an den aktuellen Quellstand gebunden.
Der vorherige Galerienachweis bleibt in Commit `ad94615` nachvollziehbar;
`docs/media/provenance.json` bleibt davon unabhängig.

Bestanden sind 219 Offline-Tests, 13 Schema-Dokumentprüfungen und die oben
beschriebenen Browserchecks. Die Ablehnung alter `parent_frame`-Instanzen,
fehlender Hosts, nicht unterstützter Instanzfelder und nicht numerischer
Aufstellungskoordinaten wurde zusätzlich gegen das Schema geprüft.
Beide lokalen Vertragsdecoder (`ros2`, `sila2`) stellen die ursprüngliche
Rackreihenfolge wieder her.

FreeCAD hat sieben native Snapshots mit jeweils 223 Körpern erzeugt.
Ihre aggregierten Volumina und Schwerpunkte stimmen exakt mit dem vorherigen
Medien-Build überein; Körper-IDs, Mesh-Geometrie, Farben und Deckkraft ebenfalls.
Die Referenzbank bleibt bei `#8a959d` und Deckkraft 0,38. Die native Szenenprüfung,
Selbst-/Greifprüfung und der adaptive Bewegungstest bestehen: 1601 angeforderte
Prüfstellungen, 1593 unterschiedliche Zustände und kleinster geprüfter Abstand
5,47699 mm. Das ist eine diskrete BRep-Prüfung, kein kontinuierlicher
Bewegungsraum- oder realer Funktionsnachweis.

SolidCraft hat beide nativen Prüfstellungen unabhängig von FreeCAD erzeugt und
mit jeweils 235 geschlossenen Körpern geprüft. Die gemeinsame Beschreibung
enthält weiterhin 223 semantische Körper; die größere native Zahl entsteht
allein durch die dokumentierte Aufteilung der Herstellergehäuse. Beide
Stellungen bestehen den Quervergleich mit FreeCAD: relative Volumenabweichung
unter 4,51e-7, Schwerpunktabweichung unter 0,00018 mm. Es handelt sich um
statische Prüfstellungen, keine native Übergabebewegung.

Die vollständige lokale Zuordnung von Quellen, Generatoren und Ausgaben steht
unter `exports/generated/centrifuge-cf01-robot-19cf33001d73-r2/` in
`robot-pickup-build-report.json`, `solidcraft-scene-validation.json` und
`claude-review-validation.json`. Historische Quell-/Medienprüfsummen und die
Übereinstimmung der vorherigen Geometrie sind im letzten Bericht separat
festgehalten. Netzwerk, Hardware und das Live-FreeCAD-Makro wurden nicht
ausgeführt.

Die drei betroffenen Galerieansichten wurden erneut erzeugt und visuell geprüft.
Alle drei Bilddateien sind bytegleich mit dem vorherigen Stand; aktualisiert
wurden ausschließlich ihre Quellen-, Modell- und Berichtsbindungen in der
Galerie-Provenienz. Der abschließende Galeriecheck besteht für 27 Bilder und
22 abgedeckte Modellquellen bei insgesamt 2.231.021 Bildbytes.
<!-- cf01-source-end: review -->
