# L01 equipment placement and access study

The furnished scene places three instances of the existing six-axis arm,
CF01, floor transporter TR01, the existing T01 used-tip collector and three
24-place tube cassettes in the current L01 room. The leading source is
[`model/lab-layout-l01.shared.json`](../model/lab-layout-l01.shared.json).
The room geometry remains in its own shared source. Measurements are still
pending; every room dimension retains its provisional status.

## Open and rebuild

The [current build report](../cad/lab-layout-l01/shared-build-report.json)
contains the current FreeCAD and SolidCraft paths, source/native asset hashes,
validation evidence and render paths. Run:

```powershell
python scripts/build_lab_layout.py
```

For execution through SolidCraft MCP, use `--prepare-only`, execute the
generated `scene.commands.json` using MCP, save the scene and measurements at
the paths in its context, then use `--finish <context.json>`. When MCP restricts
file access, stage the source-derived STEP snapshots in its permitted temporary
directory and replace only those input paths. Keep the original command file
for the reproducible CLI path.

Current scene revision: `lab-layout-l01-ffcf822d8b3a`.
[FreeCAD](../cad/generated/lab-layout-l01-ffcf822d8b3a/LabLayout_L01.FCStd),
[SolidCraft](../cad/generated/lab-layout-l01-ffcf822d8b3a/LabLayout_L01.sc),
[overview](../cad/generated/lab-layout-l01-ffcf822d8b3a/layout-iso.png),
[top view](../cad/generated/lab-layout-l01-ffcf822d8b3a/layout-top.png),
[arm pair](../cad/generated/lab-layout-l01-ffcf822d8b3a/pair-detail.png) and
[centrifuge/vehicle](../cad/generated/lab-layout-l01-ffcf822d8b3a/cf-vehicle-detail.png).

## Proposed arrangement

The room origin is the inside left corner at the entrance wall; X points right,
Y towards the windows and Z upwards. Dimensions below are in mm. Coordinates
are placement origins, rather than footprint corners.

| Instance | Placement | Position X, Y, Z | Yaw |
|---|---|---|---|
| ArmA | Right-hand middle bench, entrance side of pair | 3800, 3070, 965 | 70° |
| ArmB | Same bench, window side of pair | 3800, 3730, 965 | −110° |
| ArmC | Left wall bench, window end | 600, 6350, 1060 | −140° |
| CF01 | Left bench beside ArmC | 500, 6050, 900 | −90° |
| TR01, Floor_Mixed | Parked beside left bench | 930, 6250, 0 | 90° |
| T01 | Between the pair, towards the wall | 3550, 3400, 900 | 0° |
| RackPair | Between the pair, towards the aisle | 3900, 3400, 900 | 0° |
| RackCF | Left bench, entrance side of CF01 | 500, 5575, 900 | 0° |
| RackManual | Left half of the middle bench | 2850, 2700, 900 | 0° |

The pair faces a shared work area with bases 660 mm apart. The third arm can
turn between the centrifuge and parked transporter. Its displayed shoulder
pose is raised to prevent its tip-camera housing intersecting the closed lid.
Two open 65 mm concept risers support the pair; ArmC uses a 160 mm riser; their attachment details and
bench loads are unqualified. They are portable box/cut props in the layout
adapter, rather than independently drawn equipment models.

The transporter uses the existing mixed plate/tube configuration with its deck
regenerated at 900 mm. Its transport cover is omitted in this access view;
cover removal and handling are not implemented. The three bench racks reuse
the exact existing TR01 B2 tube-cassette geometry, including its illustrative
closed tubes. The cassettes are not newly qualified commercial racks.

## Checks and interpretation

The build checks cross-instance BRep intersections, open-lid clearance and four
walking strips through a 2000 mm high volume. The strips are 1000 mm wide along
both sides of the island and across the entrance, and 900 mm wide across the
window end. Green floor patches show these reserved study areas. They are
geometric planning choices, not established safety separation distances or an
egress/accessibility assessment. Door-leaf swings and drawers are absent.

The TR01 route runs straight through Door A to the left station. It is checked
at 35 positions spaced no more than 200 mm apart. Its 412 mm cross-route
envelope fits inside the provisional 900 mm door opening. At the parked
position its right edge is X=1136; the left walking strip begins at X=1450,
leaving 314 mm between that edge and the strip. This is a static layout gap,
not a protective separation. The vehicle route crosses the entrance walking
strip; shared traffic management remains necessary. No steering, dynamics,
localization, occupied-person detection or inter-lab corridor is simulated.

Seven position-only flange inverse-kinematics checks use the original arm
dimensions and limits, verified with its forward kinematics: both arms at the
shared work point, both at the T01 approach, and ArmC above CF01 and the two
vehicle bays. These endpoints do not establish tool orientation, a real TCP,
graspability, collision-free arm motions, cables or coordinated collaboration.
No gripper or pipette tool is added. Full arm sweeps are not checked.

This revision passed all static checks: 587 valid scene bodies, zero
cross-instance intersections, four clear walking strips, 35 clear vehicle
samples, a clear open-lid pose and seven reachable flange positions. All 12
equipment/riser instances agree between CADs: maximum volume difference is
0.00393% and maximum centre-of-volume difference is 0.00235 mm. These are
geometric comparison errors, not mechanical accuracy claims. Model renders
were visually inspected; FreeCAD GUI rendering was not separately checked.

The current offline suite passes 159 tests. The separate [sample-transfer study](lab-transfer-l01.md) restores live ArmC/CF01 kinematics and checks a reversible tube-handling sequence.

Known construction overlaps inside each upstream rigid assembly are retained
and excluded from cross-instance collision checking. Valid individual shapes
and agreement between CAD instances do not qualify upstream mechanisms,
containment, payload, stability or human-machine operation.

## Shared-source boundary

Each equipment asset is pinned to its source and native FreeCAD artifact by
SHA-256 and checked against its upstream build report. Native source models
are posed through their existing controllers, then copied into the scene as
static geometry snapshots. Multi-solid products are flattened into named
single-solid records consistently for both CAD targets. SolidCraft imports
those same records as separate component instances; FreeCAD stores them in
named placement groups. The room remains native parametric geometry.

Adjust layout parameters, equipment poses and room dimensions in the leading
sources and rebuild both targets together. FreeCAD placement-group translation
expressions also expose layout values for inspection; the SolidCraft equipment
instances are placed snapshots. Native scene edits are experiments and must
return to the shared source before regeneration. Original arm and CF01 models
retain their editable joints; this combined scene does not duplicate those
live controllers. No ROS environment or coordinated laboratory protocol is
generated by this layout adapter.
