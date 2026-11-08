# CF01 bench-mounted robot and output rack

The [shared pickup scene](../model/centrifuge-cf01.robot-pickup.shared.json) now
combines the existing six-axis [robot](../model/robot.json),
[centrifuge](../model/centrifuge-cf01.shared.json) and
[command contract](../model/centrifuge-cf01.protocol.json). A provisional
parallel tube gripper is attached to the arm's existing flange reference.
The [current pickup report](../cad/centrifuge-cf01/robot-pickup-build-report.json)
lists the generated animation, native CAD views, playback macro and evidence.

The 60-second illustrative sequence opens the lid, raises tube 01, approaches
with open jaws, closes them around the tube body, extracts the tube along its
35° axis, and withdraws the robot with the tube. The pusher retracts and the lid
closes only after the robot and carried tube have cleared the centrifuge.
After the lid locks, the robot turns the tube upright in clear space, lowers it
into output rack slot 01, confirms support, opens its fingers and lifts away.
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
| 41 s | Lid closed |
| 42 s | Lid pins engaged; robot still holds the removed tube |
| 46 s | Tube upright outside the centrifuge |
| 50 s | Tube above empty output rack slot 01 |
| 54 s | Tube bottom reaches the rack base through the guide bore |
| 55 s | Synthetic rack-support confirmation; ownership transfers without a jump |
| 56 s | Fingers open after support confirmation |
| 60 s | Empty gripper withdrawn; tube remains in slot 01 |

Times, grasp and clearance confirmations are illustrative. They are not physical
sensor data or hardware timing predictions. The new scene is separate from the
earlier centrifuge-only demonstration, which deliberately reseated the tube.

## Geometry and motion source

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

## Reproduce and inspect

```powershell
python scripts/build_centrifuge_robot_pickup.py
python -m unittest discover -s tests -v
```

The builder creates a new revision. It checks the upstream native-model source
and artifact hashes, generates the constrained trajectory, builds the native
FreeCAD scene and tests it, exports SolidCraft review snapshots, then writes the
interactive animation. Source dimensions and protocol intent remain in JSON;
native snapshots are derived review files rather than additional master models.

- FreeCAD: seven posed scenes (`Closed`, `Grasp`, `Extracted`, `Withdrawn`,
  `ClosedAfterPickup`, `RackSeated`, `RackReleased`), a parametric long-link arm
  and `CF01_Robot_Pickup.FCMacro`. Run the macro to play or
  scrub all six robot axes, lid, pusher, jaws and carried tube. Its live GUI is
  prepared but has not been run here; the underlying native placements were checked.
- SolidCraft: `Grasp` and `RackReleased` review snapshots derived from the
  same native scene. Their body count, total volume and center of mass are
  compared with FreeCAD. These are frozen posed STEP instances, **not a native
  SolidCraft handoff motion study**. Repeated glyph prototypes can have import
  aliases and the repeated-part display palette is simplified. The original arm
  and centrifuge CAD constructions retain their own joints and feature histories.
- Interactive playback: meshes tessellated from the same native bodies plus the
  shared joint hierarchy and sampled joint trajectory. Vendor detail is clustered
  at 1 mm only for responsive display; exact BRep geometry remains in CAD checks.

The report distinguishes these backend capabilities. No ROS scene, hardware
trajectory execution, or SiLA server was added by this animation update.

## Executed checks and limits

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
networked ROS/SiLA deployment. [Protocol/runtime boundaries](centrifuge-cf01-protocol.md).

SolidCraft MCP inspection was attempted, but its allowed paths exclude this
project directory. The existing reproducible local SolidCraft CLI adapter was
used for the two source-derived review scenes and cross-CAD measurements.

## Synthetic workspace and complete local batch

`model/synthetic-cf01-workspace.shared.json` composes an explicitly unbounded
space, reference-bank catalogue, furnishing instance and equipment layout.
There is no room shell. The standalone rack source is
`model/guided-tube-rack.shared.json`. The former bank dimensions, device world
poses and all 241 trajectory samples remain unchanged.

Run `python3 scripts/run_cf01_rack_batch.py` (optionally `--transport sila2`) for
the twelve-sample local fixture. The profile declares an initially empty rotor,
a delivered rack and fictitious masses. All robot handoffs are abstract synthetic
confirmations. A separate world inventory checks actual indexed slots and sample
identities against the runner ledger and simulated station presence/mass. This
is no physical sample identification. Polling uses the local MockProtocol API;
commands and failure-stop requests pass through the selected contract decoder.
Test time advances only during spin/braking. Failures retain partial inventory
and produce a failed report; they do not claim restored sample order.

The 60-second motion component (rotor slot 01 → rack slot 01) has its own timeline
and mock confirmations. The batch runner does not execute that component or
any loading/return path. The README HTML presents the two independently.

On the current macOS build, seven FreeCAD snapshots and the adaptive motion audit
pass. The SolidCraft snapshot import fails strict closure validation for Rotor
and Arm_A1/A3/A4/A5/A6_housing; all 223 body entries are imported and BenchSurface
passes its dimensions and volume check. No closure check is waived. See local
`solidcraft-scene-validation.json` and the overall build report (`passed: false`).
No network, hardware, live FreeCAD macro or transporter execution is established.
