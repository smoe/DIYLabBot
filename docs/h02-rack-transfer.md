# H02 direct pickup to the guided rack

`model/h02-rack-transfer.scene.json` composes the existing H02 full-arm pickup
and guided rack sources. Build with:

```sh
python3 scripts/build_h02_arm_pickup.py --transfer --backend both
python3 scripts/build_h02_arm_animation.py --transfer
```

The current native output paths and source/artifact hashes are resolved through
`cad/h02-rack-transfer/shared-build-report.json`. The animation has its own
`cad/h02-rack-transfer/animation-report.json`. Generated files are not leading
construction sources. Either CAD backend can build independently; a verified
SolidCraft vendor cache can be supplied with `--vendor-cache`.

## Fixture and motion

This synthetic H02 fixture instantiates the existing 12-place rack design at
`[36, -116, 0]` mm. Slot01 is empty; the other eleven places contain the existing
H02 tube reference and mouth clearance envelopes. The original CF01 rack layout
is unchanged. H02's eight neighboring tubes remain present. Tube01 retains its
identity through H02 → gripper → H02.OutputRack.Slot01.

The arm approaches empty, closes the existing gripper, transfers continuously
from confirmed grip to supported placement, opens the jaws, and withdraws empty.
The loaded route uses shared C2 corner geometry, the shared jerk-limited scalar
clock and analytic arm IK. Clearance and entry points do not command stops.
The upright tube and gripper turn 45° in free space so the fingers can open
between the occupied neighboring rack slots. Release follows an explicit
synthetic support assertion; it is not inferred from elapsed time.

Walking speed is interpreted as **1500 mm/s (1.5 m/s)**, and the requested
acceleration cap is **9806.65 mm/s² (1 g)**. The existing sample jerk cap
5000 mm/s³ and sample rotation limits remain active. Existing loaded arm limits
(0.5 rad/s, 2 rad/s², 20 rad/s³) also apply and constrain this fixture before the
requested translation caps are reached. Empty travel uses the arm's empty
profile, without imposing sample protection limits. Jaw motion retains the
local gripper profile. Limits are synthetic, not hardware or biological
qualification. They are ceilings, not claimed achieved speeds.

An analytic monotone clock metric allocates more time to the central curved
transfer than to its straight ends. It is uniformly retimed against conservative
interval bounds on joint, TCP and every carried tube point's velocity,
acceleration and jerk, including yaw. This is not a proof of global time
optimality. A manual-task comparison time is not supplied, so the project's
faster-than-human acceptance target remains open.

## Validation scope

Both native CAD adapters construct the arm, holder, original gripper and rack
from the shared sources. The local native swept-volume proof is retained for
finger opening/closure and the original axial holder extraction. The complete
arm route is checked adaptively, using native BRep bounding enclosures, native
solid distances for unresolved nearby pairs and analytic motion-radius bounds
between inspected poses. Filled tube envelopes prevent hollow reference shells
from hiding interference. All occupied rack places and holder neighbors enter
the environmental collision scope.

The allowed-collision matrix records same-link, adjacent-link and flange/tool
mounting interfaces. Local pad/tube contact is intentional. Initial axial
holder separation is discharged only after its native swept proof passes.
Rack base contact uses a signed vertical nonpenetration bound for the complete
path and separate native distance/overlap checks at support. These are not
unrestricted collision exclusions. A deliberately inserted midpath obstacle
must fail the continuous audit although the endpoint poses are clear.

SolidCraft inspection sets all joints to one requested pose using a constant
native motion study. Native solved occurrence frames transform measured native
construction boxes; eight corners enclose every point of each rigid solid.
Nearby distances remain native BRep calculations. This constant study is an
inspection setter, not a replacement transport program, and is deleted before
saving the six inspectable native poses. Full native metrology at those poses
is compared across CADs. Native arm/tool/tube frame probes also check the shared
FK throughout inspection.

The browser replay evaluates the same scalar polynomials, spatial corners,
clock metric and IK. Placement is checked against native FreeCAD transforms,
and browser PVA and matrices against Python reference times. Display meshes
are compacted separately and never feed collision validation. Playback defaults
to 1× model time.

This is geometric and kinematic model validation with fixture confirmations.
It does not implement hardware sensing, grip-force verification, drive dynamics,
biological qualification, safety qualification or real robot execution.
