# Robot-operated cam and latch — H03

H03 implements the owner's choice of 28 October 2026: robot-operated turning,
with **no additional station motors**. The open H02 tube frame, body seats,
bottom access and receiving halves are retained. A horizontal shaft now carries
two real cam contours; rollers, follower carriers, a closing wedge and a
spring-bolt latch with pull-and-quarter-turn release are added.

![H03 motorless station mechanism](../cad/tube-cam-h03/cam-mechanism.png)

This is a kinematic and geometric concept. Cam torque, contact forces, bearing
loads, spring rates, stiffness, wear, tube fits and physical reliability remain
unqualified. Lids and the robot tool are not modeled. No hardware is commanded.

## Complete transfer and reset animation

The [interactive cycle](../exports/generated/tube-cam-h03-cycle-3d3acefdee73-r3/transfer-reset.html)
plays the checked native geometry with a synchronized section through the latch.
It includes bottom contact, 28 mm tube ejection, receiver closure, the 220°
capture-confirmation pause, follower return, receiver departure and return,
restoration of support at 210°, the 4.5 mm pull and 90° turn, reverse lowering,
untwisting and spring rearming. The final joint state equals the initial state.

The leading [cycle source](../model/tube-cam-h03-cycle.shared.json) pins the H03
geometry by SHA-256. Robot inputs are interpolated first; the existing common
cam/latch law derives the followers, tube, collar and jaws. This avoids separately
keying a tube path or inventing another mechanism for the animation. Time is in
**s**, displacement in **mm**, and angles in **deg**. The 40 s playback duration
is illustrative and does not establish a safe operating speed or cycle time.

`python scripts/build_tube_cam_animation.py` generates a new revision with a
replay timeline, mesh visualization and [animation report](../cad/tube-cam-h03/animation-report.json).
It reads the checked FreeCAD solids, verifies native joint values and full
placement matrices at **483 states**, and keeps both existing native CAD files
unchanged. The visible 2.0 mL variant uses 30 bodies; the hidden mouth keepout
is omitted from the view. Meshes are only display geometry (0.25 mm linear
deflection); the existing CAD interference report remains the geometric check.
No additional dense contact or collision simulation is claimed.

The latch panel cuts the housing and collar stem at Y=21 mm and follows the
receiver. It keeps the complete bolt, cross-pin and handle so their quarter turn
can be seen. Retraction of 4.2 mm in the initial/final open state is the bolt
resting against the collar stem, not a commanded robot pull. Capture confirmation
is an illustrated event; the robot, sensing, springs and contact dynamics are
not simulated. Seven cycle tests cover support, order of operations and rearming.
Browser checks cover playback, 11 key states and layouts at 320/600/820 px;
the final light/dark views and the latch midpoint were inspected visually.
The [full-suite snapshot](../exports/generated/tube-cam-h03-cycle-3d3acefdee73-r3/unit-test-results.json)
has 153 passes out of 154 tests, with one unrelated L01 flange/forward-kinematics
test failing. All 26 tube geometry/cycle tests pass.

## One main turn

The robot engages the red turning lug on the front of the shaft. The orange cam
drives the bottom lifter. The blue cam raises a rear follower that pushes the
green closing collar. Inclined collar faces move the two jaw rollers inward,
closing both receiving halves symmetrically.

| Main-shaft angle | Intended action |
|---|---|
| 0–30° | Take up the 2 mm gap at the exterior tube bottom |
| 30–130° | Lift the tube by 28 mm into the receiver |
| 130–200° | Raise the collar 12 mm and close the receiving halves |
| 200–210° | Spring bolt enters the collar's retaining window |
| 220° | **Pause and confirm actual tube capture and bolt insertion** |
| 220–320° | Return the lifter; the latch keeps the collar and receiver closed |
| 320–360° | Station followers clear; robot can remove the latched receiver |

The closing cam rises 12.15 mm: 0.15 mm takes up the initial pad clearance and
12 mm closes the collar. The follower then withdraws from the latched collar,
so a fixed station linkage does not tether the departing receiver.

![Two cams on the common robot-driven shaft](../cad/tube-cam-h03/cam-profiles.png)

The bearing stands and plate are hidden in this detail view.

The source specifies quintic rise/return laws and dwell intervals once. Both
cam contours are calculated from their roller-center pitch curves, offset by
the roller radius plus a 0.03 mm modeling allowance. The contours are represented
by fixed source-generated polygons; this allowance is not a manufacturing
tolerance. Regenerate the profiles after changing dimensions or motion laws.

The profile checker evaluates roller-to-contour gaps, pressure angles and pitch
curvature over a full turn. These are geometry checks; they do not establish
acceptable drive torque, speed, life or contact stress.

## Positive latch and robot-operated reset

The collar carries a retaining window. A conical-nose bolt slides into it from
the side under a required compression spring. The cylindrical portion supports
the window roof when the collar tries to descend. The housing, shaft bore,
spring cavity, movable spring seat, cross-pin and bayonet slots are modeled.
The compression spring itself is not selected or represented as a working coil.
The bolt, conical nose and integral spring seat come from one axial revolved
profile in the shared source. Cross-pin and robot handle remain separate rigid
assembly bodies.

![Latch bolt and its quarter-turn sleeve](../cad/tube-cam-h03/cam-latch.png)

This section through the bolt axis exposes the retaining window and sleeve.

The receiver departs with its collar, jaws, bolt and latch housing. The cams
remain in the station. A full turn back to the same shaft orientation does not
release the latch; the source explicitly retains the captured state at 360°.

For reset:

1. Return the receiver to its station position while keeping the tube captured.
2. Reverse the main cam to 210°. The pusher supports the tube and the closing
   follower supports the collar again.
3. The robot pulls the latch handle 4.5 mm and turns it 90°. Its cross-pin enters
   the circumferential bayonet pockets and holds the bolt retracted.
4. Reverse the main cam toward 0°. The collar descends, the receiving halves
   open under required outward bias springs, and the pusher lowers the tube.
5. After seating, untwist the latch and let it rearm against the collar stem.

The slot has nominal axial clearance. Under spring return the pin can settle
approximately 0.1 mm while remaining held open; the nose remains outside the
stem in the nominal geometry. Fit, friction, detent/retention and release force
need bench validation. The release is a separate robot manipulation, not a
second station motor.

Required passive elements remain explicit: outward jaw-opening springs, a bolt
compression spring, gravity-assisted collar/follower return, and any preload
needed to maintain cam contact. Spring selection and operating speed are open.
Roller spin and spring/contact dynamics are not simulated.

## Shared source and native operation

The leading source is [tube-cam-h03.shared.json](../model/tube-cam-h03.shared.json).
It includes the H02 source by path and SHA-256, overriding the drive mechanism
without keeping separate FreeCAD and SolidCraft constructions. The semantic
[tube_cam_model.py](../scripts/tube_cam_model.py) lowers both cams, wedge faces,
latch/window, sleeve slots, bearings, shaft and protocol into shared operations.

```powershell
python scripts/build_tube_cam.py
python scripts/verify_tube_cam_native.py
& "$env:LOCALAPPDATA/Programs/FreeCAD 27.1/bin/python.exe" scripts/verify_tube_cam_freecad.py
python scripts/render_tube_cam.py
python -m unittest discover -s tests -v
```

The [build report](../cad/tube-cam-h03/shared-build-report.json) identifies the
current `.sc`, `.FCStd` and STEP files under `cases[0].files`. New source-hash
revision directories preserve earlier models. The
[native coupling report](../cad/tube-cam-h03/native-coupling-checks.json) checks
actual SolidCraft joint values against the common motion law. The
[FreeCAD transform report](../cad/tube-cam-h03/freecad-transform-checks.json)
also checks native joint values and complete translation/rotation matrices.
The [render manifest](../cad/tube-cam-h03/render-manifest.json) ties views to model
and source checksums.

Current nominal files, containing both tube variants:

- [FreeCAD H03](../cad/generated/tube-cam-h03-643bba546a73-r3/TubeCam_H03.FCStd)
- [SolidCraft H03](../cad/generated/tube-cam-h03-643bba546a73-r3/TubeCam_H03.sc)
- [STEP H03](../exports/generated/tube-cam-h03-643bba546a73-r3/default.step)

In SolidCraft edit `CamInputV15` or `CamInputV20` in **Parameters**, from 0 to
360 **deg**. Native `joint.cam` links drive both roller followers; motion links
couple the collar to both jaws. Source-generated expressions retain latch state.
Use `CarryInput*` in **mm** only after the return, `ReleaseInput*` in **mm** for
the pull and `BayonetInput*` in **deg** for the quarter turn. Do not drive the
follower joints independently or wrap the phase from 360° to 0° without reset.

In FreeCAD use `Controller.CamAngleV15/V20`, `ReceiverLift*`, `ReleaseStroke*`
and `BoltTurn*`. The other fields are expression-driven. Angle properties use
**deg**, slider properties **mm**, and intermediate phase variables are unitless.
The native file uses parametric primitives, sketches, extrusions and expressions;
it does not import STEP as its model source or use Assembly contact dynamics.

Manual CAD input changes are visualization, not a hardware safety controller.
The source transition guard requires capture confirmation at 220°, but a CAD
parameter edit does not replace actual sensing or a machine interlock. The
modeled phase/state is deliberately separate from physical spring dynamics.

## Validation and remaining work

The current nominal, lower-bound and upper-bound builds each pass with 62
bodies, 53 sampled states and zero measured symmetric STEP difference. The
separate FreeCAD readback covers all 159 states, including the camshaft and
bayonet cross-pin orientations. SolidCraft's native geometric cam and jaw
links pass 54 probe states across the same three builds. All 19 tube-model
unit tests pass. The broader
[workspace test run](../cad/tube-cam-h03/unit-test-results.json) has 109 passes
out of 111 tests; two unrelated centrifuge parameter tests currently reject
dimensions outside their exploration ranges.
The [delivery audit](../cad/tube-cam-h03/delivery-checks.json) verifies current
source, model, validation and rendering checksums.

Default and parameter-boundary builds compare body names/counts, volume, center
of mass, bounding boxes and symmetric STEP difference. Geometry and anchors are
rebuilt together. Native edits of cam geometry are deliberately not qualified;
edit the common source and regenerate both CADs.

FreeCAD checks sampled forward transfer, receiver departure, latch pull/twist
and reverse/reset states. Different rigid components are checked for BRep
interference. The four cam/roller pairs use a dedicated 2D contour-distance
check. Cam-to-carrier clearance uses the carriers' cross sections over the
same full-turn samples; follower pins remain inside the verified roller
circles. These checks replace repeated near-tangent BRep booleans for those
pairs. Fixed-group assembly
overlaps remain separate in the report and are not manufactured fits.

The source support checker rejects unsupported tubes, early receiver departure,
twisting before pulling and cam return without a latched receiver. Front optical
segments and the no-contact mouth region from H02 remain in the checks. Real
transparent liquid, a 1 µL wall droplet, cap clearance, hardware sensing and
complete robot paths still require separate validation. ROS/SiLA station drivers
and hardware motion control are not implemented.
