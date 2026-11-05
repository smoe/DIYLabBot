# CF01 — robot-accessible centrifuge, assembled inspection view

Requested on 28 October 2026: **16,000 × g**, commanded opening/closing of the
instrument lid, camera-readable rotor orientation and presentation of individual
microcentrifuge tubes to the six-axis robot. CF01 supplies a shared-source layout
and runnable mock programming interface. It is **not a qualified centrifuge,
manufacturing design or demonstrated 16,000 × g capability**.

Leading source: [centrifuge-cf01.shared.json](../model/centrifuge-cf01.shared.json).
The [animated robot-access cycle and ROS/SiLA protocol](centrifuge-cf01-protocol.md)
now have a separate shared protocol source, native playback and generated
interface definitions; their mock behavior is tested offline, with no network server.
The later [robot grasp and withdrawal animation](centrifuge-cf01-robot-pickup.md)
adds a bench-mounted longer-link variant of the same six-axis arm and a concept
gripper. The carried tube and arm clear the centrifuge before the lid closes;
the robot then places the tube into a guided 12-position output rack.
The [current build report](../cad/centrifuge-cf01/shared-build-report.json) lists
the actual native SolidCraft/FreeCAD files, STEP exports, renderings and checks.
Historic directories remain historic; open the report's current `cases` paths.

## Mechanical draft

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
| Lifter | Stationary retracting axial pusher; 12 mm park clearance, 28 mm total stroke |
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

## The 16,000 × g target

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

## Camera orientation

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

## Power entry and cable

`CF01.POWER` is the common interface at the right side of the lower bay. The CAD
contains an inlet/switch/fuse-module envelope, a removable cord coupler, molded
strain-relief envelope and a 7 mm outside-diameter cord. Two tangent circular
bends give a smooth 45 mm centerline bend radius before the cord reaches the
bench. Both CAD adapters generate an actual round sweep from the same path;
the displayed cord is a short layout section and its supply-side termination is
not modeled. The manufacturer's allowable bend radius is still unknown.

A chassis earth stud and short green bond lead are represented. PE bonding to
all steel panels and the lid, electrical isolation, drive/control supplies,
fusing, EMC treatment and complete wiring are requirements. The lid bonding
braid and complete wire routing are not modeled. Nominal mains voltage, current,
power, fuse rating, conductor area and purchased inlet/cord remain `null`.
There is no energized circuit or electrical test. The geometry is an envelope,
not a registered IEC mounting interface. Combined inlet/switch/fuse units are
illustrated by the [SCHURTER KD data sheet](https://www.schurter.com/en/datasheet/typ_kd.pdf);
no particular product has been selected.

## Rotation measurement

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

## Spindle motor and brakes

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

## Powered lid without a manual step

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

## Executable programming interface

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

## Shared build and checks

```powershell
python scripts/build_centrifuge.py
python -m unittest discover -s tests -v
```

`centrifuge_model.py` expands the steel chamber/floor/supports, hollow bay,
power entry and round cord, spindle encoder, fixed-angle pocket pattern,
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
radius, mouth/lid heights, lift travel, enclosure width, wall/floor/lid thickness,
sensor gap and cord bend radius. Geometry, ports and anchors follow the same
parameters. Additional samples cover parking-pad and powered-pin strokes.
Analytic checks cover steel wall/floor/lid, cord, stator and brake-disc volumes
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
