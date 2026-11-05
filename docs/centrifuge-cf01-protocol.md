# CF01 robot access animation and ROS 2 / SiLA 2 contract

The shared source is [centrifuge-cf01.protocol.json](../model/centrifuge-cf01.protocol.json).
It defines the animation timeline, commands, argument types, execution rules and
robot pickup sequence. Geometry, joints, limits and named poses remain in
[centrifuge-cf01.shared.json](../model/centrifuge-cf01.shared.json).
The [protocol build report](../cad/centrifuge-cf01/protocol-build-report.json)
binds both source hashes to the actual animation, CAD files and interface files.

The follow-up [six-axis robot grasp/withdrawal scene](centrifuge-cf01-robot-pickup.md)
now demonstrates tube removal before closure and supported placement into an
output rack, using a longer arm mounted directly on the bench. The 33-second sequence
described below remains the earlier centrifuge-only, reversible presentation cycle.

The 33-second illustrative cycle retracts both lid pins, opens the lid to 105°,
advances the pusher through its 12 mm park gap, raises tube 01 by 16 mm along its
35° tilted axis, holds it for pickup, then reseats the same tube, parks the
pusher, closes and locks the lid. Axial tube travel corresponds to **13.1 mm
vertical and 9.2 mm inward**. The rotor remains stopped and its parking brake
held throughout. This is a reversible presentation demonstration: no robot
grasp, withdrawal, removal or physical tube contact is simulated. Lift/pin
timings are illustrative; the lid uses the provisional 10°/s requirement.
The native GIF plays about 2.25 times faster; the interactive view offers
0.5×/1×/2× playback and a tube/pusher close-up.

## Reproduce and view

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

## Compatible definitions, explicit runtime boundary

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

**No ROS node/action server or SiLA gRPC server is implemented.** ROS 2, colcon,
SiLA SDK and real hardware are unavailable on this Windows environment, so the
ROS package has not been compiled or run and no live SiLA client/server has
been tested. Authentication, TLS, discovery, deployment, qualified drive I/O
and independent feedback are future work. The originator namespace is a
provisional project identifier, not a registered standard SiLA feature.
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

## Orchestrator sequence

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

## Observable completion and cancellation

`OpenLid`, `CloseLid`, `IndexRotor`, `PresentTube`, `RetractLift`, `LowerTube` and
`RunCentrifuge` are actions / observable commands. The current core makes lid,
index and lift moves idealized instant operations. Their protocol jobs finish
after that synthetic confirmation; no physical timing or progress is fabricated
(`progress=-1` means unknown). A future driver must await actual limit, encoder,
seating, brake and health feedback before completing each operation.

`RunCentrifuge` remains active through both dwell and deceleration. `Stop` is a
short priority stop request; successful acceptance is **not standstill**.
The local `cancel(job_id)` requests stop and reports `stopping` until standstill
and held parking brake are confirmed, then reports `canceled`. An external SiLA
implementation must map its custom `Stop` command and execution status to this
behavior; do not assume ROS action cancellation is a universal built-in SiLA
command. Owner expiry or sensor faults latch recovery and never auto-restart.
Heartbeats and status remain available while one observable job is active.
This coordination stop is not an emergency-stop or certified safety function.

Tests exercise both wire parameter spellings, SI/validity conversion, blocked
concurrent motion, transfer uncertainty, occupied workspace, owner timeout,
normal run completion through braking and cancellation through standstill.
Default spinning remains rejected without the explicit fictitious test fixture;
tests cannot qualify the 16,000 × g target.
