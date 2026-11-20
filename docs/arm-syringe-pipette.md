# SP02: dedicated 1 ml syringe arm with a clipped hose

**A 1004 mm hose now follows the arm through seven plastic clips and four local
joint loops.** Both native CAD builds pass all 16 required static poses,
2368 body comparisons and 10 bound views. The focused checks cover 147 unique
passing tests. The smallest nominal clearance is only 0.030613 mm; this is a
static geometric fit, not a qualified manufacturing margin, motion or dosing
result.

The leading construction is
[`model/arm-syringe.shared.json`](../model/arm-syringe.shared.json), with
[`arm-syringe.schema.json`](../model/arm-syringe.schema.json). One Fine nominal
1 ml glass syringe, its motor/lead screw and the fixed macro head are derived
from the unchanged [SP01 library](syringe-pipette-concept.md). The original arm,
cameras and manufacturer geometry remain referenced. There is no second
syringe, manifold or automatic tool changer.

## Pump and unchanged pneumatic interfaces

The pump remains on L2's negative-X face, outlet toward the wrist along L2 +Z.
Reversal preserves the `SinglePumpPlate` mounting footprint. The head and
separate consumable follow L6. The perfusor analogy concerns piston actuation:
this syringe moves air, while sample liquid remains in the disposable tip.
Motor angle is `360 × stroke / screw lead`: 10,800° for 60 mm with the assumed
2 mm lead. Normal states reserve 2 mm at each end; hard-end references require
an explicit flag. Theoretical swept volume and actual dispensed liquid remain
distinct; the latter is unknown.

Both tube ends insert into sockets and bottom on annular floors with coaxial
through-bores. Historical IDs `PumpHoseBarb` and `TipSidePort` retain their socket
geometry. Tube ID/OD remains provisionally 0.5/1.8 mm.

| Assumption | Default (mm) | Range (mm) |
| --- | ---: | ---: |
| Socket radial clearance | 0.05 | 0.02–0.15 |
| Insertion depth | 6 | 4–10 |
| Supported strain relief | 10 | 5–20 |
| Straight free connector lead | 10 | 5–20 |
| Tip engagement | 8 | 5–12 |
| Tip-mouth radial relief | 0.05 | 0.02–0.15 |
| Clip support length | 10 | 6–12 |
| Straight free clip exit | 3 | 3–10 |

Material end, pneumatic junction, socket mouth, unsupported exit and first
permitted bend have separate source meanings. The material end and pneumatic
junction share the floor coordinate. Each floor-to-bend run remains 26 mm:
6 inserted +10 supported +10 free. `PumpHoseClamp` follows the pump;
`TipHoseClamp` follows the head and loads no disposable tip. OD compression
sealing and retention remain assumptions rather than qualified hardware.

The relieved `TipShaft` engages the separate `DisposableTip` at one seal circle,
8 mm below its mouth. The gap opens upward to 0.05 mm relief, using the inherited
65.01 mm interior-cutter slope. The actual tip exit defines the TCP. Insertion
force, retention force and gas sealing remain open.

## Seven real clips and four local flex sections

The previous R50 carrier is **not installed**. Its source, schema, helper and
pinned manufacturer brochure remain byte-identical for reuse and historical
comparison. Its article radius has not been reduced to justify the new route.

Seven source-derived plastic split clips mount to named structural host bodies:
parent and child supports at J3, J4 and J5, plus the parent support at J6. The
head-mounted strain relief provides the downstream support at J6. Each clip has
portable solid geometry, a host-link transform, a tube groove and an explicit
mount to existing arm material. Clearance-fit CAD geometry assumes compression
retention; it does not prove non-slip grip, elastic closure, manufacturing fit
or mount strength.

Four fixed runs are constructed once in L2–L5 coordinates and rigidly follow
their respective links. Four separately sized flex sections cross J3–J6. Each
clip owns one fixed cumulative material coordinate along the hose. Every section
between supports therefore has one invariant material length across all 16
poses. Material cannot slide through another clip or disappear into a global
service loop. The helper rejects compensated section-length changes even when
the total cut remains constant.

Insertions, socket supports, connector leads, clip supports and free spans are
disjoint material regions. Their measured line/arc lengths sum to the cut.
The six provisional cutting/placement allowances total 3.5 mm; rounding is
applied once. Their allocation to a named flex section must itself solve in
every pose, without changing any other section's length or material station.
Nominal insertions and clip supports are already counted in the physical path.

## Explicit assumptions and the J4 correction

Bare hose must achieve at least **R12**. This is a hard computational constraint
and an unqualified design assumption until a tube article is selected. A curve
that cannot fit it fails with a witness; no automatic radius reduction is used.

The assumed free straight exit from each plastic clip is now **3 mm**, within
the declared 3–10 mm range. The earlier 5 mm value was our provisional choice,
not a manufacturer or user limit. The change leaves the 10 mm connector leads
and 10 mm socket strain relief unchanged. Supported material inside each
nominal clip remains 10 mm.

The J4 parent groove moves axially from 420 to **401 mm** in its source frame;
the child groove remains at 465 mm. Together with the 3 mm exits, this provides
a 48 mm axial core for a gentle two-arc R12 S transition. The earlier route
could return through the downstream support despite passing an isolated-loop
self-check. Selection now also screens the neighbouring support straights and
source-parameter continuations. These diagnostic probe lengths add no material.

Nonlocal hose portions must clear each clip's outer groove reservation: with
0.9 mm tube radius, 0.05 mm clearance and 1.2 mm wall, the required centreline
reservation is 3.05 mm. Only the intended straight entry/exit is excluded from
that reservation. Tube-to-tube self-clearance alone cannot prove clearance from
plastic walls; complete native clip solids pass separate checks in all 16 poses.

## Closeness and the static proof scope

Fixed runs have explicit maximum distance bounds to named structural hosts:

| Fixed run | Native upper bound (mm) | Source limit (mm) | Host region |
| --- | ---: | ---: | --- |
| Upper arm | 31.904360 | 80 | Includes the pump connector return. |
| Elbow | 28.905104 | 45 | J3 hub and J4 structural posts. |
| Forearm | 10.991280 | 25 | Forearm tube and wrist structure. |
| Wrist | 25.019153 | 35 | A6 housing and J6 posts. |

These are maximum centreline-to-host distance upper bounds over every section,
including the arc-length interval margin, maximized across all 16 poses. Native
checks measure actual host shapes and retain material-membership witnesses.
Source proximity independently uses witnesses inside actual portable CSG
material, including cuts and later translations. A distance to an enclosing
box cannot prove closeness to a hollow body.

Joint loops have separate radial and axial pockets in the actual joint-parent
frames. Bounds cover whole curve intervals through an arc-length spacing
margin. Reports must retain maxima and worst witnesses; a global minimum
clearance cannot hide a long detour away from the arm.

Native joint-pocket bounds across the same 16 poses are:

| Joint loop | Radial upper bound /limit (mm) | Axial outer bounds /allowed range (mm) |
| --- | --- | --- |
| J3 | 47.628804 /80 | −103.632283…−71.010000 /−115…−65 |
| J4 | 45.436112 /60 | −29.000000…27.000000 /−30…55 |
| J5 | 38.991525 /80 | 5.008475…46.350276 /0…50 |
| J6 | 58.531286 /60 | −8.986676…31.544180 /−20…45 |

All **16 original complete pose dictionaries remain unchanged**, as do the robot
pin, seven SP01 files and unused carrier library. They are named static
configurations. This task makes no new 842-coordinate Cartesian-window claim,
continuous hose-deformation proof or timed-motion claim. The former carrier
scan cannot qualify the replacement geometry.

The unchanged tooling inspection bounds are source assumptions, separate from
robot limits and supported-pose evidence:

| Joint | Inspection bounds (°) | Reason |
| --- | ---: | --- |
| J1 | −160…160 | Full source yaw range; arm and awareness camera rotate together. |
| J2 | −30…65 | Retained lower pump/turret margin; folded head/base interference motivated the upper cap. |
| J3 | −10…65 | Retained pump/forearm margin and upper folding cap. |
| J4 | −30…30 | Assumed limited hose twist. |
| J5 | −110…110 | Full source wrist-pitch range, tested only at named poses. |
| J6 | −30…30 | Side air entry requires routing checks despite the axisymmetric tip. |

The source calculation selects **1004 mm**, compared with the historical
1193 mm carrier cut: 189 mm less. This is a demonstrated result within the
declared finite construction/search family, not a global physical minimum.
The current pinned proof records all eight section lengths, seven material
stations, allowance/rounding arithmetic and passed complete source/self/proximity
checks. The current native proof independently checks the resulting solid fit.

| Quantity | Historical carrier build `650b54b75cfa` | Current clipped source design |
| --- | --- | --- |
| Hose cut | 1193 mm, native-built | 1004 mm, all 16 source configurations solved |
| Guide | R50, 361.6 mm /32 stations | Removed; seven physical split clips |
| Material restraint | Single service-loop coordinate | Four independently fixed joint-span lengths |
| Bare bend requirement | R12 | R12 retained |
| Tube socket insertion | 6 mm at both ends | Unchanged |
| Clip free exits | Earlier route contract | Assumed 3 mm; connector free leads remain 10 mm |
| Complete native evidence | 16 states, 2288 comparisons, 10 views | 16 states, 2368 comparisons, 10 views |

## Current and historical evidence

The passed source-only report is
`exports/arm-close-hose/routing-proof.json`, format
`solidcraftbot.arm-hose-routing-proof/1`, SHA-256
`4e082be2a3eeaa76dc4f3263e2e2ba568d2d76ffff909e5e33ab1861f5aaee1b`.
It retains 21 current source/dependency pins and all 16 required poses. It
records independently fixed section lengths and material stations rather than
a sampled global service-loop band.

| Invariant section | Kind | Length (mm) |
| --- | --- | ---: |
| `upper_run` | Fixed on L2 | 222.660891 |
| `elbow_flex` | J3 loop | 99.000000 |
| `elbow_run` | Fixed on L3 | 106.951349 |
| `roll_flex` | J4 loop | 72.000000 |
| `forearm_run` | Fixed on L4 | 39.651193 |
| `pitch_flex` | J5 loop | 117.000000 |
| `wrist_run` | Fixed on L5 | 90.548668 |
| `flange_flex` | J6 loop | 134.187899 |

Clip centre material stations, measured from the pump-side tube end, remain
253.660891, 362.660891, 479.612240, 561.612240, 611.263433, 738.263433 and
838.812101 mm in chain order. The base physical route is 999.812101 mm;
3.5 mm of itemized allowances and 0.687899 mm rounding produce 1004 mm.
All 4.187899 mm of extra material is allocated once to `flange_flex`, increasing
its base 130 mm length, and independently solved in every pose.

The disjoint material sum is 12 mm inserted, 20 mm socket strain relief,
20 mm connector leads, 70 mm clip supports and 882 mm free spans. It totals
1004 mm with no carrier material and no double-counted diagnostic support probe.

The current [native build report](../cad/arm-syringe/shared-build-report.json),
revision **`arm-syringe-48da6c4acaac-r2`**, passes both FreeCAD and SolidCraft in
all 16 poses, with **148 semantic bodies per pose /2368 comparisons**. Its
SHA-256 is `6ff0e27c8e6bab1c0ccbf9d22244d2ed686a7337aad2109b1ca3283d6677912b`; all 32 source/producer pins are current.
The entire hose, seven clips, actual host shapes, sockets, relieved tip seat,
head air path, native air inventory and saved closed solids pass their checks.
All **208 declared-contact observations have zero raw overlap**. No undeclared
contact or positive material interference is accepted.

| Material category | Minimum gap (mm) | Closest bodies | State |
| --- | ---: | --- | --- |
| Hose /arm | 0.030613 | `PneumaticHose` /`A4_housing_plate` | `window_wrist_pos` |
| Tooling /arm | 0.050000 | `HoseClipJ6Parent` /`J6_mount_post_2` | `window_route_longest` |
| Tooling /tooling | 0.050000 | `TipHoseClamp` /`PneumaticHose` | `window_wrist_pitch_pos` |

The actual smallest distance is **0.030612609627 mm**. The assumed 0.05 mm local
socket/clip gaps are not a global clearance claim. Printed-part tolerances,
tube dimensions, flex under load and motion remain unqualified; this nominal
static gap establishes no manufacturing-ready fit.

The 13 original declared contact pairs remain narrow interface permissions,
not component-wide exclusions. The added clips require positive native material
gaps and receive no blanket hose/arm exemption.

| Touching bodies | Declared interface |
| --- | --- |
| `ClampPadL0` and `ClampPadL1`, each with `Upper_plate_L` | Provisional existing plate-edge clamp contact. |
| `ClampPadR0` and `ClampPadR1`, each with `Upper_plate_R` | Provisional existing plate-edge clamp contact. |
| `TipFlangePad`, each with `Bare_tool_flange` and `J6_output_coupler` | Shared flange/coupler mounting plane. |
| `MotorEnvelopeFine` with `LeadScrewEnvelopeFine` | Idealized motor/screw shaft interface. |
| `MotorEnvelopeFine` with `ScrewCoupler` | Coupler abuts the motor shaft envelope. |
| `SinglePumpPlate`, each with `ClampBridge0` and `ClampBridge1` | Provisional bracket mounting faces. |
| `PneumaticHose`, each with `PumpHoseBarb` and `TipSidePort` | Annular material end on its own socket floor only. |
| `TipShaft` with `DisposableTip` | Derived lower seal circle of the relieved taper. |

The analytical working air inventory is syringe 533.333333, fittings 64.732517,
tube 197.134939 and head 1464.772790 µl: **2259.973579 µl total**. Tube lumen is
counted once, including inserted portions. Ambient tip-relief air, 6.322876 µl,
stays separate. The working native cavity union is **2259.973703 µl**; the
largest relative error across all 16 poses is **1.10611×10⁻⁷**, below the unchanged
10⁻⁶ limit. Each union is one valid solid, constructed in rigid local frames and
placed with checked volume invariance. This is an ideal open-valve inventory, including
for the isolated-valve inspection state. These volumes establish no leakage
rate, physical dead volume or delivered liquid.

The report binds these 10 views to their native artifact hashes:

| View | Named state |
| --- | --- |
| [overview](../renders/arm-syringe-48da6c4acaac-r2/overview.png) | `working` |
| [overview close](../renders/arm-syringe-48da6c4acaac-r2/overview-close.png) | `working` |
| [pump](../renders/arm-syringe-48da6c4acaac-r2/pump.png) | `working` |
| [tip](../renders/arm-syringe-48da6c4acaac-r2/tip.png) | `working` |
| [syringe junction](../renders/arm-syringe-48da6c4acaac-r2/syringe-junction.png) | `working` |
| [pipette junction](../renders/arm-syringe-48da6c4acaac-r2/pipette-junction.png) | `working` |
| [tightest bend](../renders/arm-syringe-48da6c4acaac-r2/tightest-bend.png) | `upright` |
| [clip transition](../renders/arm-syringe-48da6c4acaac-r2/guide-transition.png) | `working` |
| [pump section](../renders/arm-syringe-48da6c4acaac-r2/pump-section.png) | `upright` |
| [tip section](../renders/arm-syringe-48da6c4acaac-r2/tip-section.png) | `upright` |

The transition view shows the J4 child clip and local flex section; no R50 guide
is installed. The two upright sections use XZ/y=0 cuts through the syringe and
tip axes, with section commands pinned in the report. Generated native files,
images, logs and reports are local ignored outputs, not committed publication
media. Static hose snapshots require regeneration after manual arm changes.

Cross-runtime comparison keeps exact physical curves, lengths and material
stations at 10⁻⁹ mm. A floating-point tie can split the same 72 mm section into
36 or 37 intervals at a 2 mm maximum step. Both achieved radial/axial bounds must
independently remain finite and satisfy the same source limits; their complete
observations, actual sample grids and world points remain recorded as derivation
diagnostics. Required pocket limits stay canonical. This correction changes no
hose geometry, clearance threshold or physical bend requirement.

The historical report remains preserved at
`cad/arm-syringe/shared-build-report-650b54b75cfa.json`, together with the original
scan `exports/arm-syringe/window-scan-650b54b75cfa.json`, native files, images,
source pins and test logs. Its 16-state/2288-comparison native proof and 121-test
result retain their original carrier scope. Older r2/r5, socket/stub, air-union
and saved-edit probes likewise keep their original scope and hashes.

## Verification and entry points

The final coverage contains **147 unique passing tests**, with no skips:
121 unchanged source/policy cases, all 15 current Window cases, all 10 current
adapter-policy/canonical cases and the single fresh native-evidence case.
The repaired Window module took 12.090 s; the adapter checks took 0.050 s.
The native case took 23.502 s and ran only after actual publication
of the 16-state/10-view report. A fresh cold design took 113.568 s;
the publication-gate check took 0.051 s. Neither counted as a testcase.

The original 144-case source run (340.494 s) exposed the inactive-carrier
compatibility bug. Its failed log remains preserved; only the affected modules
were rerun after the scoped fixes. The [combined coverage summary](../exports/arm-close-hose/final-focused-147-summary.json)
records exact testcase IDs, phase provenance and all 49 unchanged current inputs.
The [AST/file-pin evidence](../exports/arm-close-hose/source-146-native-only-ast-preservation.json)
confirms the native-only numeric assertion fix changed no source-case body.
All nine offline Markdown checks also pass. No testcase was dropped or
substituted for current native evidence.

```sh
PYTHONPATH=tests python3 -m unittest -v \
  test_syringe_pipette test_arm_syringe test_pneumatic_hose \
  test_arm_syringe_window test_spatial_hose_carrier \
  test_arm_syringe_routing test_arm_syringe_clearance test_joint_hose_routing
```

The locked environment uses `jsonschema==4.26.0` from
[`requirements/sila2-test.lock`](../requirements/sila2-test.lock). Source-only
routing preparation and native generation use the same model:

```sh
python3 scripts/prepare_arm_hose_routing.py
python3 scripts/build_arm_syringe.py --backend both --arm-report exports/generated/build-report.json
```

Either CAD backend also builds independently. Repeat `--state NAME`, use
`--parameter NAME=VALUE` or `--no-render` as needed. A changed variant needs its
own current routing proof and native evidence; the former carrier window entry
point is not the proof for this clipped mode.

## Explicitly open

All seven assembly qualification flags remain false and all fourteen unknown
hardware requirements remain null. The clipped routing separately leaves fit,
axial retention and continuous-motion qualification false. Selected syringe,
tube, tip and clip articles, actual dimensions, print material, clamp retention,
mount strength, fasteners, drive-nut axial retention/force path, actuator force,
feedback/end stops, fatigue, pressure response, leakage, calibration and dosing
accuracy remain unqualified.

ROS 2/RViz, Gazebo, firmware, pressure calibration, liquid-transfer runtime,
tip pickup/ejection and hardware execution are not implemented for this attached
assembly. A command acknowledgement or motor position does not prove delivered
liquid. CAD fit establishes geometric fit only. The earlier
[Luer discussion](syringe-pipette-concept.md#ist-luer-lock-hinreichend-gasdicht)
applies to the complete air path.

The [AliExpress reference](https://de.aliexpress.com/item/1005013047448030.html)
could not be inspected because site-safety policy denied access; no product
measurements or component selection are attributed to it.
