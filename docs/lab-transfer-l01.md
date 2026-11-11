# L01 transporter–centrifuge roundtrip

The [shared protocol](../model/lab-transfer-l01.protocol.json) defines one
closed 2 ml tube moving from TR01 to CF01 and back to the same rack position.
The [layout source](../model/lab-layout-l01.shared.json) now places ArmA and ArmB
on the right-hand middle bench, together with T01 and their rack. ArmC and CF01
are grouped on the left wall bench before the freezer bay. Both work areas are visible
in a single room view.

The third arm uses a provisional 160 mm open riser. CF01 faces 270°, so the
tilted pocket can be approached with the real wrist limits. TR01 parks at
X=930, Y=5450; its deck remains at 900 mm. The left station group and the
three existing absolute waypoint references share `left_station_shift_y`.
Those waypoint coordinates accept the same millimetre expressions as the
layout, preserving the 800 mm geometric translation. The historical native
transfer report predates the revised room placement; it is not a current
motion-clearance proof. The current `/2` transport compiler uses that revised
layout explicitly. Its changed curve requires a fresh native motion report;
an older waypoint audit does not establish flowing-motion compliance.
All room dimensions and station placements remain provisional.

## Playback and rebuild

After a complete successful build, the
[transfer report](../cad/lab-transfer-l01/shared-build-report.json) resolves
native paths, hashes, sampled poses and the new motion audit. Until that build
finishes, the implementation alone is not a native collision/clearance proof.
The static room layout has its [own report](../cad/lab-layout-l01/shared-build-report.json).

```powershell
python scripts/build_lab_layout.py --prepare-only
python scripts/build_lab_transfer.py
```

`--prepare-only` on the transfer builder generates native FreeCAD, audits the
motion and writes SolidCraft commands. A full build also constructs the
SolidCraft preview, exports its actual native poses and compares them with the
canonical curve. `--finish <context.json>` completes an already prepared build.
Paths may be staged inside the MCP server's permitted temporary directory;
the stored original commands retain the project paths for CLI rebuilding.

## Demonstrated sequence

1. Start with the rotor stopped, parking brake held and lid already fully open.
2. Approach the selected transporter rack cell, grasp the tube and lift it.
3. Transfer via the clear waypoint, align with the 35° rotor-pocket axis and
   insert the tube in slot 01. Release it and withdraw the arm.
4. Close and lock the lid. Hold stationary, then unlock and reopen it.
5. Raise the tube 16 mm using the existing axial pusher, grasp it and withdraw.
6. Move back to TR01, lower the tube into its original cell, release and park.

The return cycle contains a stationary dwell, not a centrifugation run. The
other rotor tubes retain their upstream illustrative geometry. No measured
balance, speed or containment qualification is implied.

## Continuous transport contract

`model/lab-transfer-l01.protocol.json` and its new schema use
`solidcraftbot.lab-transfer/2`. The current runtime is
`scripts/lab_transfer_motion.py`; the unchanged construction/IK functions in
`lab_transfer_model.py` remain shared helpers, including the CF01 native OBB
checks. Timeline `/1` is not silently treated as a current PVA program.

The compiler generates six continuous arm episodes: four empty approach/retreat
paths and two complete carried-tube transfers, grip → CF01 seating and grip →
the original TR01 cell. Every episode uses one normalized S-curve progress law,
a joint fit and a common time scaling. Position, velocity and acceleration are
continuous; one-sided jerk is finite but may jump. Intermediate transit marks
do not force the arm to rest. Required station operations, the stationary
process dwell and supported ownership handoffs remain separate synchronization
steps. The rotor stays stopped throughout.
Sequence `duration_s` values supply the arm's reference clock and minimum
station-operation times; bound-based retiming determines the actual times in
the generated timeline.

Mechanical axial pickup/insertion/retreat legs retain their dense 2 mm IK
solutions. Their actual between-knot FK is checked against the original axis
and orientation tolerances. Other legs use the existing named source poses as
continuous quintic passage points. Those poses, source dimensions, station
identities and original rack cell remain unchanged, but the **non-axial path
between them changes** from the historical linear study. The narrow
`orient_before_lid` leg explicitly retains the source-pose joint-linear
reference: its intermediate joint positions are calculated from the existing
`transit`/`cf_pre` poses at at most 2° spacing, then fitted continuously without
a rest. All other narrow CF legs retain their dense source-helper Cartesian
IK references, except the four passages between `cf_pre` and `cf_side`.
Those share one source-defined lateral C2 reference in either direction:
straight initial entry, a smooth offset of up to 50 mm in world −Y, then
return to the existing endpoint. The six scalar offset knots declare position
in mm and derivatives with respect to normalized path progress `u`; they are
not physical time derivatives. The compiler derives 257 IK reference points
from this curve, then recomputes all physical-time bounds on the actual arm
PVA. Real grasp/seating/rack targets, the virtual passage endpoints and sample
orientation remain unchanged. Initial native audits on
11 November 2026 found an A5-housing/lid
collision in the unrestricted quintic interpolation; that failed report is
retained locally, together with a subsequent self/contact failure in the
unrestricted `pass_inside_lid` fit and its former straight Cartesian reference.
Neither is adopted as proof. Fresh native checks must examine the
actual corrected PVA curve.

The analytical oriented IK uses the actual six-axis dimensions and limits.
Bounded coordinate-wise PVA tangent damping prevents an interpolation
overshoot without moving its joint-position knots or changing a joint limit.
The fit fails explicitly if this cannot preserve limits, the axial constraints
or the no-intermediate-rest criterion. Axial sample roll remains free.

The former two-second `park_pusher` carrying pause is an independent station
channel. Retraction begins only after the entire enclosing carried-tube/cap
reference box crosses the source `transit` X boundary, while the arm continues
toward TR01. The actual native audit must also check the simultaneous arm,
sample and station poses. This is a synthetic source-bound clearance event,
not measured robot feedback.

Joint and whole-sample velocity, acceleration and jerk caps are referenced from
the pinned `limits` section of `model/cf01-unload-demo.motion.json`, rather than
copied into a second parameter table. `qualified: false` and unknown biological
tolerance remain in force. Exact joint-polynomial extrema and conservative
numerical FK intervals determine time scaling. The no-rest check applies to
both loaded and empty episodes, with only their endpoint quiet bands allowed.
The enclosing radius and axial extent come directly from the actual tube and
closed-cap create/join operations, including the wider collar and cap. Eight
enclosing corners and three axial markers cover that complete construction;
the nominal tube-wall radius alone is insufficient. The validator also derives
the actual Lift/TubeLift retraction window and recomputes whole-vessel
clearance, rather than accepting a declared event or copied audit as proof.
The resulting duration is a synthetic model time, not a speed, hardware or
global-optimality claim. The current source-bound curve takes 1248.694 s
(1742 arm knots): one global time factor per episode slows the entire episode
for its most demanding interval. It is deliberately conservative and has not
been optimized for elapsed time; a local retimer is not implemented.

The FreeCAD macro evaluates the canonical PVA curve directly at its monotonic
playback clock; it does not linearly replay display samples. The installed
SolidCraft `motion.study` contract only accepts value keys. Its explicitly
named `L01SampleRoundtripPreview` is consequently a dense derived **linear
preview**, not an executable C2 transport program. Preview subdivision checks
whole-tube reference-point error against 0.01 mm at quarter/midpoint samples;
this is not a continuous preview-error certificate. The separate native pose
comparison measures what SolidCraft actually produces. No SolidCraft velocity,
acceleration or jerk qualification is inferred from that preview.
Its display clock uses at most 100000 dimensionless steps, as required by the
installed adapter; metadata and the build report preserve the exact mapping
to canonical seconds. This changes neither the canonical times nor its
physical motion bounds. Native rigid groups are constructed explicitly from
the imported body sets and placed using their original source frames.
The installed SolidCraft importer still reports lenient tessellation/pcurve
warnings for some rational STEP faces. These remain a display/import
limitation; the pose comparison does not qualify imported surface fidelity.

## Tool and sample boundary

The CAD still has no selected physical gripper. The transfer assumes an 80 mm
flange-to-handling-reference offset, shown as a gold shaft and collar envelope.
That envelope is checked with the arm. The turquoise sample reuses CF01's
existing Tube01 and ClosedCap01 solids; the selected TR01 tube envelope and the
fixed CF01 Tube01 are removed to avoid duplicate samples. Cap geometry and
article/rack fits retain their unqualified upstream status. The collar is an
assumed handling envelope, not a demonstrated grasp.

Ownership is explicit in every protocol phase: rack, arm or centrifuge. Sample
motion follows arm FK while carried and the existing CF01 axial lift while
supported there. Grasp, seating and workspace-clear confirmations are synthetic
storyboard events. No real feedback is fabricated or sent to hardware.

## Validation boundary

The audit checks sampled arm, tool and sample geometry against the room,
cupboards, benches, risers, vehicle and centrifuge. Conservative oriented
body bounds first separate pairs; possible overlaps are refined with the
native BRep solids. Cached exact results are reused only for the same pair
and relative transform. The audit also checks non-adjacent arm links and
sample/arm overlaps. Within-link construction overlaps, adjacent joint
interfaces and assumed tool/sample contact are excluded.

Sampling limits are 2° per arm-joint increment, 5 mm of handling-reference
travel and 3° per lid increment, with all curve knots and events included.
The new explicit minimum distance to furniture and fixed equipment is 5 mm;
it is not imposed across prescribed tube insertion or support contacts.
The original 0.001 mm³ overlap criterion and contact exclusions are retained.
AABB distance lower bounds at or above 5 mm establish separation directly;
pairs below that bound receive an exact native BRep distance check. The report
calls its overall result `minimum_furniture_distance_lower_bound_mm`, not an
exact global minimum. All pairs and the required margin remain unchanged.
This is a sampled geometric screen; no continuous swept-volume guarantee,
physical dynamics, cable routing, precision, payload,
stability, human detection or safe separation is established. The two arms on
the middle bench remain stationary in this sequence. Timing is illustrative.

The native report binds the exact `timeline.json` and `samples.json` bytes
before its audit and checks those bindings again through build completion.
Final timeline, samples, macro, native models and pose export receive artifact
hashes. `--reuse-geometry` accepts only a passed construction cache with
equivalent geometry sources/generators and unchanged context, scene, STEP
files and native evidence. The new motion is always audited again; an unbound
historical report cannot silently become a current proof.
Construction helpers, the actual native arm/CF builders and nested vendor
library/interface/STEP inputs are bound before construction and checked at
build start, audit completion, finalization and geometry reuse. Replay also
checks the construction helpers used by its current kinematics and layout.

The current local revision `lab-transfer-l01-a03566b376d0-r2` passed 4594 native
frames (4508 distinct states), with no overlap failures and a conservative
minimum furniture-distance bound of 124.1799 mm. Its actual SolidCraft export
passed 257 frames / 4369 rigid-pose comparisons: maximum position error
0.028051 mm and rotation-matrix element error 0.000048982. Its 4594-frame
derived preview reached a maximum sampled reference error of 0.009983 mm;
this includes its displayed yaw/tilt axis. Physical arm/station curves,
events and sample envelope have exactly the same JSON values as the
earlier `a03566b376d0` program; the new source binding and preview samples
were checked afresh. The prior report and slow local-fit prototype remain
historical local archives, not current evidence.

Fresh targeted checks ran 77 tests with one explicit optional CF01
actual-program skip and no failures. The current L01 curve's dynamics,
ownership and pusher overlap were also recomputed during build completion.
The generated FreeCAD macro evaluates this curve directly; interactive GUI
playback, hardware execution and protective feedback were not tested.

The animated scene restores native prescribed kinematics for ArmC and CF01,
with the same original anchors and axes in both CAD adapters. Other equipment
remains a source-bound static snapshot. ROS/SiLA networking and coordinated
hardware execution are not implemented by this scene.
