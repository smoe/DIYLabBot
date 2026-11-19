# SP02: dedicated 1 ml syringe arm

**Current status: 1193 mm source cut demonstrated in all 16 required static
states within the unchanged 0–80 mm service-loop limit.** All 272 sampled loop
trials and 16 independently solved selected cuts pass the source gates.
Diagnostics found a genuinely shorter pose, so a sixteenth case was added
without changing any of the original 15. Both native CAD builds now pass all
16 states, 2288 body comparisons and 10 bound views; all 121 focused tests pass
with zero skips. Gas tightness, continuous motion and dosing remain unqualified.

The leading source is
[`model/arm-syringe.shared.json`](../model/arm-syringe.shared.json), with
[`arm-syringe.schema.json`](../model/arm-syringe.schema.json). One Fine nominal
1 ml syringe, its motor/lead screw and the fixed macro head are derived from the
unchanged [SP01 library](syringe-pipette-concept.md). The original arm, cameras
and manufacturer geometry remain referenced. No second syringe, manifold or
automatic tool changer is included.

The pump remains outboard on L2's negative-X face, outlet toward the wrist along
L2 +Z. Reversal preserves the `SinglePumpPlate` mounting footprint. The fixed
head and separate consumable follow L6. The perfusor analogy describes piston
actuation; this syringe moves air rather than directly infusing the sample.
Motor coupling remains `360 × stroke / screw lead`: 10,800° for 60 mm with the
assumed 2 mm lead. Normal states reserve 2 mm at each end; hard-end references
need an explicit flag. Actual dispensed liquid remains unknown.

## Revised interfaces

Both tube ends now insert into sockets and bottom on annular floors with
coaxial through-bores. Historical IDs `PumpHoseBarb` and `TipSidePort` remain,
but their geometry is no longer a face-only connection. Tube ID/OD is still
provisionally 0.5/1.8 mm.

| Assumption | Default (mm) | Range (mm) |
| --- | ---: | ---: |
| Socket radial clearance | 0.05 | 0.02–0.15 |
| Insertion depth | 6 | 4–10 |
| Supported strain relief | 10 | 5–20 |
| Straight free lead after support | 10 | 5–20 |
| Tip engagement | 8 | 5–12 |
| Tip-mouth radial relief | 0.05 | 0.02–0.15 |

The source distinguishes material end, pneumatic junction, socket mouth,
unsupported exit and first permitted bend. Material end and junction share the
floor coordinate; their meanings differ. The nominal straight run from the floor
is 26 mm: 6 inserted +10 supported +10 free. `PumpHoseClamp` follows the pump;
`TipHoseClamp` follows the head and loads no disposable tip. The head socket
floor sits outside the collar envelope, avoiding an undeclared hose contact.
OD ferrule/compression sealing and retention remain assumptions, not selected
or qualified hardware.

A relieved `TipShaft` replaces SP01's blunt `TipCone` in this composition. Its
lower edge touches the tip's inner cone at one seal circle, 8 mm below the mouth;
the gap opens upward to 0.05 mm relief. The derivation uses the inherited
65.01 mm interior-cutter slope. `DisposableTip` is a separate rigidly mounted
`ConsumableTip`, so its shaft contact is checked across components. Its actual
exit defines the TCP. Insertion force, retention force and gas sealing are open.

## Demonstrated source cut

Routing uses explicit link/origin/tangent/x-axis/clamp frames and a service-loop
coordinate. Bare bends must achieve at least **12 mm**; corners that cannot fit
raise a witnessed error rather than shrink. The guide separately requires R50,
with straight leads at both ends. Internal leads belong to its nominal length;
external leads already belong to free spans.

The guide profile references
[igus TRL.30.050.0](https://www.igus.com/product/triflex-TRL?artnr=TRL.30.050.0):
34.5 mm outer envelope, R50 and 11.3 mm pitch in the pinned
[historical brochure](https://www.igus.com/us/pdf/triflexr.pdf). Its leading source
now uses **32 stations /361.6 mm**, the **smallest demonstrated count in the
declared finite biarc/offset/service search**. The current proof is
`exports/arm-syringe-physical-fit/current-guide-count-search-650b54b7.json`
(SHA-256 `82dcf943cca80a98327e145b3d10fd03a11d4778e5787e30bf0553ed46edca98`),
with current, unchanged source/producer pins and all 16 required states.
A necessary bound of 177.079633 mm gives N≥16; N16–29 fail upright, N30–31
fail working and N32 passes geometry plus conservative source guard checks
in all 16 cases. N16–19 are diagnostic trials below the normal variant
range20–120. The finite-search result is no global optimum or hardware
qualification; actual channels, articulated links, anchors and article/print
design remain open. The earlier 15-state count report is preserved.

The current 16-state source band is
`exports/arm-syringe-physical-fit/final-named-band.json`, SHA-256
`a2d9bc9f73e661b31844eaaa84be73956da362c45124f37d6b973f7fe930db5f`.
Its **272/272 trials and 16 independently solved cuts pass** hard bends,
finite nonlocal self-screening and conservative source envelopes, with current
unchanged source/producer pins. The earlier 15-state band is preserved.

The completed current corner/edge scan contains **842 coordinates and 1684
endpoint evaluations**, with **144 explicitly classified unsupported endpoint
observations**, all 16 named states supported and no unexpected errors.
`exports/arm-syringe-physical-fit/final-canonical-window.json` has SHA-256
`e8707973abb9790766e727809c9fefa0f3da0f5956beca0d1ff6bab90c685687`.
Its genuine supported shortest diagnostic is
`[-160, -30, -10, 30, 110, 0]`, 1136.089533 mm at zero loop and 1213.787043 mm
at 80 mm loop. That is 15.654846 mm below the old named minimum, beyond the
fit/arithmetic tolerance. It is now required as `window_route_shortest_revised`.
Its independent 1193 mm solve passes at approximately 65.707860 mm loop and is
included in the completed 16-state band and the full native proof.

The revised L5 pre-flange support is at X=−64 mm, Y=0, with its Z derived from
the real head air-junction plane. This reduces the asymmetric wrist-tail
length changes without increasing loop travel or loosening bend/clearance gates.
For the retained 15 cases, sampled minimum-length spread fell from
**81.698516 mm** in the stopped proposal to **37.214861 mm**. Including the new
shortest diagnostic increases the 16-case spread to **52.869706 mm**;
it is retained rather than hidden by the earlier named set.

| Current 16-state selection | Length (mm) |
| --- | ---: |
| Largest sampled minimum: `window_wrist_neg` | 1188.959240 |
| Smallest sampled maximum: `window_route_shortest_revised` | 1213.787043 |
| Itemized provisional allowances | 3.500000 |
| Rounding to the next whole millimetre | 0.540760 |
| Selected source cut | 1193 |

That cut lies inside the sampled common hull and is independently solved and
checked in each of the 16 states. A sampled hull does not prove intermediate
feasibility or continuous reachability. The result remains a **minimum
demonstrated under stated assumptions**, not a global optimum or hardware
minimum.

Each named state was sampled at 5 mm loop increments from 0 to 80 mm.
The limits below are demonstrated sampled lengths within that declared cap,
not exact physical extrema. The selected cut was then solved independently:

| State | Sampled minimum (mm) | Sampled maximum (mm) | Selected loop (mm) |
| --- | ---: | ---: | ---: |
| `upright` | 1152.860698 | 1230.558208 | 52.598119 |
| `working` | 1152.860698 | 1230.558208 | 52.598119 |
| `extended` | 1152.860698 | 1230.558208 | 52.598119 |
| `pump_advanced` | 1152.860698 | 1230.558208 | 52.598119 |
| `pump_retracted` | 1152.860698 | 1230.558208 | 52.598119 |
| `isolated` | 1152.860698 | 1230.558208 | 52.598119 |
| `window_back` | 1152.860698 | 1230.558208 | 52.598119 |
| `window_wrist_pos` | 1151.744379 | 1229.441889 | 53.536578 |
| `window_wrist_neg` | 1188.959240 | 1266.656750 | 8.795491 |
| `window_wrist_pitch_pos` | 1152.860698 | 1230.558208 | 52.598119 |
| `window_wrist_pitch_neg` | 1152.860698 | 1230.558208 | 52.598119 |
| `window_route_shortest` | 1151.744379 | 1229.441889 | 53.536578 |
| `window_route_longest` | 1188.959240 | 1266.656750 | 8.795491 |
| `window_carrier_mid` | 1152.860698 | 1230.558208 | 52.598119 |
| `window_camera_mount` | 1188.959240 | 1266.656750 | 8.795491 |
| `window_route_shortest_revised` | 1136.089533 | 1213.787043 | 65.707860 |

Allowances name cutting (1 mm), each insertion tolerance (0.25 mm), guide-entry
and guide-exit placement (0.5 mm each), and clip placement (1 mm). Nominal
insertions/supports already belong to the physical route. The actual working
material partition is:

| Disjoint material region | Length (mm) |
| --- | ---: |
| Two inserted portions | 12.0 |
| Socket strain relief | 20.0 |
| Connector straight free leads | 20.0 |
| Ordinary clip-supported straights | 20.0 |
| Nominal guide, including its internal leads | 361.6 |
| Free bare spans, including external guide leads | 759.4 |
| Total | 1193.0 |

The two external guide leads total 20 mm and already belong to the free-span
row. Loop travel and selection allowances are not added again to this sum.
The working loop coordinate is approximately 52.598119 mm.

All 16 selected source routes achieve a 12 mm minimum bare radius;
guide minima are **50.321901–55.018207 mm** and their smallest conservative
source-margin lower bound is **0.643661 mm**, separate from native body minima.
Working support-frame radial standoffs and diagnostic sensitivities are:

| Crossing | Frame distance from joint axis (mm) | Largest supported same-edge zero-loop length swing (mm) |
| --- | ---: | ---: |
| J3 /`guide_exit` | 22.360680 | 33.646316 |
| J4 /`roll_clip` | 35.000000 | 37.214861 |
| J5 /`wrist_clip` | Approximately zero | 33.646316 |
| J6 /head clamp exit | 27.000000 | 15.654846 |

Frame standoffs are not minimum distances along the whole hose. The swing
analysis compares supported samples only along each diagnostic edge, holding
all other joints fixed; source/self failures and incompatible length brackets
are excluded and counted. J1/J2 changes are numerical ties below 7×10⁻¹³ mm.
The reproducible analysis is
`exports/arm-syringe-physical-fit/diagnostic-joint-length-swings.json`, SHA-256
`1a7cf2c10f4fb684169aee1a4a73d72d18718f7eac713bc131bc4215bb1d2f6a`.
These finite differences reflect the constrained route choices, not selected
cuts at unlisted poses or continuous motion. Native validation covers the 16
named configurations separately.

The earlier `canonical-band-proposal.json` is the preserved stopped bce7a4a2
proposal: its sampled hull was empty (1191.824250–1187.823244 mm), so its rounded
1196 mm calculation was rejected and no state selected. That stop was resolved
by geometry changes under the retained 80 mm limit; its old pins and the r2
unsupported-grid witnesses remain historical evidence only.

These tooling-use bounds remain separate from unchanged robot limits:

| Joint | Inspection bounds (°) | Source reason |
| --- | ---: | --- |
| J1 base yaw | −160…160 | Full source range; arm and awareness camera rotate together. |
| J2 shoulder | −30…65 | Retain the provisional lower pump/turret margin; native folded-head/base collisions at 75/80° motivated the 65° cap. |
| J3 elbow | −10…65 | Retain the lower pump/forearm margin; folded poses at 105–135° hit shoulder/camera geometry, so finite studies use the 65° cap with J2≤65°. |
| J4 forearm roll | −30…30 | Assumed limited hose twist; vertical pipetting requires no larger roll. |
| J5 wrist pitch | −110…110 | Full source range, subject to named boundary checks. |
| J6 flange roll | −30…30 | Axisymmetric tip/TCP on the axis; the side air entry still requires routing checks. |

These bounds describe inspection inputs, not a supported Cartesian operating
range. No timed transport or continuously deforming guide is implemented.

## Native geometry evidence

The current [generated build report](../cad/arm-syringe/shared-build-report.json),
revision **`arm-syringe-650b54b75cfa`**, passes both FreeCAD and SolidCraft in
**all 16 states**, with **143 semantic bodies per state /2288 body comparisons**.
Its SHA-256 is
`ac3b51d5ccfcfe4729363a6f62c38fbd6596dc8bbad45ab695bc811667bcea15`;
all 33 recorded source/producer pins are current. The actual hollow hose and
guide, socket mating, tip seating, clear head air path and native cavity union
pass. All **208 declared-contact observations have zero raw overlap**; no
undeclared contacts or interferences are accepted.

| Metric | Historical r2 | Current 16-state evidence |
| --- | ---: | --- |
| Cut length (mm) | 1091 | 1193, independently solved and native-built in every state |
| Guide length /stations | 463.3 /41 | 361.6 /32 |
| Smallest bare radius (mm) | 1.313335 | 12.000000, strict source/native route checks |
| Smallest protected radius (mm) | 51.319356 | 50.321901, strict source/native route checks |
| Pump/head insertion (mm) | 0 /0 | 6 /6, native mating checks |
| Tip engagement (mm) | 0, butt contact | 8, native relieved seat |
| Socket radial gap (mm) | Not modeled | 0.050000, positive native measurements |
| Full native hose/arm minimum (mm) | 8.800000 | 2.100000 |
| Working ideal air inventory (µl) | 2878.559662, analytical r2 | 2297.083642 analytical /2297.083996 native union |

Native category minima below exclude the declared contact pairs. The filled
carrier guard is a checking envelope, not delivered material; its separate
categories test the space occupied by the guide against arm and tooling.

| Category | Minimum (mm) | Closest bodies | State |
| --- | ---: | --- | --- |
| Hose /arm | 2.100000 | `PneumaticHose` /`Wrist_yoke_bridge` | `window_route_shortest_revised` |
| Tooling /arm | 4.000000 | `HeadCollar` /`Bare_tool_flange` | `window_route_shortest` |
| Tooling /tooling | 0.050000 | `TipHoseClamp` /`PneumaticHose` | `window_back` |
| Filled carrier guard /arm | 4.750000 | `CarrierOuterGuard` /`A3_housing` | `window_route_shortest_revised` |
| Filled carrier guard /tooling | 77.210278 | `CarrierOuterGuard` /`ClampPadR1` | `window_route_shortest_revised` |

The analytical working air inventory is syringe 533.333333, fittings 64.732517,
tube 234.245002 and head 1464.772790 µl. The tube lumen is counted once,
including inserted portions; ambient tip-relief air **6.322876 µl** is separate.
Each native cavity union is one valid solid. The maximum relative volume error
across all 16 cases is **1.915×10⁻⁷**, below the unchanged **10⁻⁶** limit.
This is an ideal **open-valve** inventory, including for the isolated-valve
inspection state; it proves no leakage rate, physical dead volume or delivered
liquid.

Source envelopes ignore cuts, use 1e−6 mm padding and adaptive 1-Lipschitz
interval bounds; an envelope hit means inconclusive proximity rather than a
proven native collision. Complete intended socket regions defer only their own
connector/clamp mating to mandatory native checks. Arm and unrelated tooling
remain checked. The native socket checks require coaxial alignment, measured
insertion, positive radial gap and floor-plane-only contact. The separate tip
requires its seal circle, upward relief and rederived exit/TCP.

The declared pairs are narrow interface permissions, not component-wide
exemptions. Grouped entries below name each of the 13 pairs:

| Touching bodies | Declared interface |
| --- | --- |
| `ClampPadL0` and `ClampPadL1`, each with `Upper_plate_L` | Existing plate edge; provisional clamp contact. |
| `ClampPadR0` and `ClampPadR1`, each with `Upper_plate_R` | Existing plate edge; provisional clamp contact. |
| `TipFlangePad`, each with `Bare_tool_flange` and `J6_output_coupler` | Shared flange/coupler mounting plane. |
| `MotorEnvelopeFine` with `LeadScrewEnvelopeFine` | Idealized motor-to-screw shaft interface. |
| `MotorEnvelopeFine` with `ScrewCoupler` | Coupler abuts the motor shaft envelope. |
| `SinglePumpPlate`, each with `ClampBridge0` and `ClampBridge1` | Provisional bracket mounting faces. |
| `PneumaticHose`, each with `PumpHoseBarb` and `TipSidePort` | Annular tube material end on its declared socket floor only. |
| `TipShaft` with `DisposableTip` | Derived lower seal circle of the relieved taper. |

FreeCAD retains hollow-segment construction and lumen/volume/annulus checks.
SolidCraft retains the geometry-preserving circular-profile seam correction;
the FreeCAD collar proxies likewise use a fixed circular seam with explicit
volume/centroid/bounds invariance checks. Air cavities are grouped in their
rigid local frames, united with the tube in `PumpFrame`, then rigidly placed in
the world. This avoids a coordinate-sensitive native Boolean cleanup error;
local/world volume invariance remains checked. These adapter changes alter no
physical curve or tolerance. Cross-runtime route comparison permits only
co-directed collinear subdivisions within the same material part, with all
retained trace points checked; arcs and raw bend/source/self gates stay strict.

The report binds these **10 generated views** to their exact native input bytes:

| View | Named state |
| --- | --- |
| [overview](../renders/arm-syringe-650b54b75cfa/overview.png) | `working` |
| [overview close](../renders/arm-syringe-650b54b75cfa/overview-close.png) | `working` |
| [pump](../renders/arm-syringe-650b54b75cfa/pump.png) | `working` |
| [tip](../renders/arm-syringe-650b54b75cfa/tip.png) | `working` |
| [syringe junction](../renders/arm-syringe-650b54b75cfa/syringe-junction.png) | `working` |
| [pipette junction](../renders/arm-syringe-650b54b75cfa/pipette-junction.png) | `working` |
| [tightest bend](../renders/arm-syringe-650b54b75cfa/tightest-bend.png) | `window_wrist_pitch_neg` |
| [guide transition](../renders/arm-syringe-650b54b75cfa/guide-transition.png) | `working` |
| [pump section](../renders/arm-syringe-650b54b75cfa/pump-section.png) | `upright` |
| [tip section](../renders/arm-syringe-650b54b75cfa/tip-section.png) | `upright` |

The two sections use upright XZ/y=0 cuts through the syringe and pipette axes,
with their `inspect.section` commands pinned in the report. Saved hose/guide
snapshots require regeneration after manual arm changes. ROS 2/RViz and Gazebo
support for this attached assembly remains unimplemented.

Historical evidence is preserved: r2 at
`cad/arm-syringe/shared-build-report-4d1631a114ce-r2.json` and
`exports/arm-syringe/window-scan-4d1631a114ce-r2.json`, plus the older r5 backup.
Earlier local socket/stub, artificial-tube air-union and saved-edit probes keep
their original scope and pins; they are superseded as full current evidence by
the report above. None is relabeled as a current saved-edit qualification.

## Verification and entry points

The complete seven-module suite passed **121 tests, zero failures/errors/skips**,
with **all 59 captured input pins unchanged**. The single-process run took
**568.221 s**, including **269.855 s** waiting for the actual final report and
10 renders to be published. The first 120 tests took 280.794 s; the final native
evidence test ran only after publication and took 17.573 s. The wait was not a
test and no testcase was dropped or substituted.

The [test log](../exports/arm-syringe-physical-fit/final-focused-121.log) and
[summary](../exports/arm-syringe-physical-fit/final-121-gated-summary.json) record
the phases and before/after pins. After building current native evidence, the
same existing tests can also run conventionally:

```sh
PYTHONPATH=tests python3 -m unittest -v \
  test_syringe_pipette test_arm_syringe test_pneumatic_hose \
  test_arm_syringe_window test_spatial_hose_carrier \
  test_arm_syringe_routing test_arm_syringe_clearance
```

The locked environment uses `jsonschema==4.26.0` from
[`requirements/sila2-test.lock`](../requirements/sila2-test.lock).
`python3 scripts/arm_syringe_window.py` is the source-only design/diagnostic entry.
The 16-state band and its fresh classified corner/edge scan are complete.
Native generation uses the current source inputs:

```sh
python3 scripts/build_arm_syringe.py --backend both --arm-report exports/generated/build-report.json
```

Either backend also builds independently. Repeat `--state NAME`, use
`--parameter NAME=VALUE` or `--no-render` as needed; a changed variant needs its
own current scan.

## Explicitly open

Seven assembly qualification flags remain false. The eleven earlier nulls are
retained plus three for socket ferrules/seals/tolerances, clamps/strain relief
and tip insertion/retention forces. Article selection, dimensions, mount strength,
fasteners, drive-nut retention/force path, actuator force, feedback/end stops,
leakage, usable liquid range and permitted dose error remain open. The carrier
has its own unresolved hardware requirements.

Firmware, pressure calibration, liquid-transfer runtime, tip pickup/ejection and
hardware execution are not implemented. A command acknowledgement or motor
position does not prove delivered liquid. CAD fit proves no gas tightness,
continuous-motion suitability or dosing accuracy. The earlier
[Luer discussion](syringe-pipette-concept.md#ist-luer-lock-hinreichend-gasdicht)
applies to the complete air path.

The [AliExpress reference](https://de.aliexpress.com/item/1005013047448030.html)
could not be inspected because site-safety policy denied access; no product
measurements or component selection are attributed to it.
