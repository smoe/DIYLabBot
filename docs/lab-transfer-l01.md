# L01 transporter–centrifuge roundtrip

The [shared protocol](../model/lab-transfer-l01.protocol.json) defines one
closed 2 ml tube moving from TR01 to CF01 and back to the same rack position.
The [layout source](../model/lab-layout-l01.shared.json) now places ArmA and ArmB
on the right-hand middle bench, together with T01 and their rack. ArmC and CF01
remain at the window end of the left wall bench. Both work areas are visible
in a single room view.

The third arm uses a provisional 160 mm open riser. CF01 faces 270°, so the
tilted pocket can be approached with the real wrist limits. TR01 parks at
X=930, Y=6250, clear of the window bench; its deck remains at 900 mm.
All room dimensions and station placements remain provisional.

## Playback and rebuild

The [current transfer report](../cad/lab-transfer-l01/shared-build-report.json)
contains native FreeCAD/SolidCraft paths, renderings, hashes, sampled poses and
the motion validation result. The static room layout remains available through
its [own report](../cad/lab-layout-l01/shared-build-report.json).

```powershell
python scripts/build_lab_layout.py --prepare-only
python scripts/build_lab_transfer.py
```

`--prepare-only` on the transfer builder generates native FreeCAD, audits the
motion and writes SolidCraft commands. Run those commands through SolidCraft
MCP or the reproducible CLI, save the result, then use `--finish <context.json>`.
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

Straight pickup/insertion legs are solved every 2 mm with the tube axis fixed;
joint-space interpolation is used between the clear waypoints. The analytical
oriented IK uses the actual six-axis dimensions and joint limits and is checked
against the original forward kinematics. Axial sample roll is free.

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
travel and 3° per lid increment. This is a sampled geometric screen; no
continuous swept-volume guarantee, dynamics, cable routing, precision, payload,
stability, human detection or safe separation is established. The two arms on
the middle bench remain stationary in this sequence. Timing is illustrative.

The animated scene restores native prescribed kinematics for ArmC and CF01,
with the same original anchors and axes in both CAD adapters. Other equipment
remains a source-bound static snapshot. ROS/SiLA networking and coordinated
hardware execution are not implemented by this scene.
