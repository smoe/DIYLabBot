# Floor sample transporter — TR01

The owner selected a floor-driven mobile robot on 28 October 2026. It should
serve stationary arms within a lab and carry samples between labs on the same
floor. The earlier bench/track variant is retired from the active design.
Track-level positioning precision is not required for travel.

One floor platform carries removable, labware-specific cassettes. Samples stay
on the parked vehicle while the stationary arm loads or unloads them. A bench
shuttle and an automatic cassette transfer between vehicle families are no
longer required.

## Current configurations

| Configuration | Concept capacity |
|---|---|
| Floor_P2 | Two covered microplates |
| Floor_T48 | Two 24-place racks: 48 × 1.5/2.0 mL tube envelopes |
| Floor_Mixed | One plate and one 24-place rack |

All three use the same 500 × 400 mm chassis, 512 × 412 mm bumper envelope,
340 × 190 mm upper deck and two keyed 140 × 104 mm cassette places. Default
deck height is 800 mm above the floor. This is a concept height, adjustable
in the shared source from 700 to 950 mm for regeneration; no powered lift is
implemented. Payload, sample acceleration, speed, range and cost remain open.

![Floor vehicle with two tube racks](../cad/generated/sample-transport-tr01-4785a40b8bad/floor-tubes.png)

The plate and tube inserts retain the earlier cassette interface. Plate bodies
use the nominal footprint from [ANSI/SLAS 1-2004](https://www.slas.org/SLAS/assets/File/public/standards/ANSI_SLAS_1-2004_FootprintDimensions.pdf);
their height, lid and gripping geometry still need article drawings. Tube
bodies/caps are illustrative solid envelopes, not qualified articles or modeled
liquid volumes. Other labware requires additional inserts. Cover, locating
pins and retainers express concepts; release, compliance and actual holding
forces are not designed. The cover is not aerosol-tight.

Carrying a full centrifuge batch remains the preferred capacity target. CF01
currently has 12 conceptual rotor places, but a final centrifuge/rotor and
batch manifest have not been chosen. The 48-tube configuration therefore does
not establish compatibility with every centrifuge. Transport costs remain
additional to the arm prototype budget.

## Arm access and positioning

Serving every arm is a design requirement, not a verified reach result. Each
station needs a feasible parking position, compatible deck height, known arm
base/tool frames and verified approach/retreat paths for all required sample
positions. The source defines `TR01.LoadDeck` and two cassette datums so those
relationships have stable names. No stations or calibrated arm-to-vehicle
transforms have been registered yet.

Floor navigation only has to bring the vehicle into the station's approach
region. Before sample handling, the vehicle must remain stationary and the
arm must know the load's actual relative pose. Vision registration or a simple
mechanical dock are candidate methods; neither is selected or implemented.
A rail or precision mechanical docking system is not required by this concept.
Parking tolerance and local registration uncertainty remain to be measured
against the task. An optional datum-block envelope remains in the CAD.

The upper transport cover must be removed before arm access. Initial manual
cover handling and loading are possible; automated cover handling and the
actual gripper are not constructed. Stationary holding, navigation, braking,
turning, obstacle sensing, doors, thresholds and charging remain engineering
tasks. The four wheels and drive/sensor bodies are space envelopes. Static CAD
checks do not prove driving, stability or station reach.

`TR01.reserve` through `TR01.handoff` specify traffic/workspace reservation,
sample manifests, closure/retention, stationary holding, local load registration,
station-specific reach and grasp confirmation before release. `TR01.fault`
requires stopping and reconciling the load before restart. These are control
requirements; there is no transporter driver, scheduler, hardware feedback,
ROS integration or SiLA server.

## Shared source, models and checks

The leading source is [sample-transport-tr01.shared.json](../model/sample-transport-tr01.shared.json),
format `solidcraftbot.sample-transport/2`. The semantic operations lower the floor
chassis, common deck, plate nest, tube rack and cover once for both CAD adapters.

```powershell
python scripts/build_sample_transport.py
python -m unittest discover -s tests -v
```

| Configuration | SolidCraft | FreeCAD |
|---|---|---|
| Two plates | [Floor_P2.sc](../cad/generated/sample-transport-tr01-4785a40b8bad/Floor_P2.sc) | [Floor_P2.FCStd](../cad/generated/sample-transport-tr01-4785a40b8bad/Floor_P2.FCStd) |
| 48 tubes | [Floor_T48.sc](../cad/generated/sample-transport-tr01-4785a40b8bad/Floor_T48.sc) | [Floor_T48.FCStd](../cad/generated/sample-transport-tr01-4785a40b8bad/Floor_T48.FCStd) |
| Mixed load | [Floor_Mixed.sc](../cad/generated/sample-transport-tr01-4785a40b8bad/Floor_Mixed.sc) | [Floor_Mixed.FCStd](../cad/generated/sample-transport-tr01-4785a40b8bad/Floor_Mixed.FCStd) |

[Current build report](../cad/sample-transport-tr01/shared-build-report.json).
The three default SolidCraft models are generated through MCP; CLI reproduction
uses the same commands. FreeCAD independently constructs native primitives,
fuses and cuts; STEP is comparison input only.

The five build cases compare the three configurations plus a larger/higher
plate vehicle and a lower mixed-load deck. Checks cover body validity, volume,
centre, bounding box, symmetric STEP difference, sample-to-cover clearance,
saved FreeCAD reopening and agreement of deck/cassette frames with geometry.
These are static checks. The vehicle is grounded for CAD inspection; there is
no artificial track joint or wheel-motion simulation. Native dimensional edits
require source regeneration to keep frames and geometry together.

## Retired track concept

The previous [dual-family source](../model/history/sample-transport-tr01-a93faaa97c19.shared.json),
[build report](../exports/generated/sample-transport-tr01-a93faaa97c19/build-report.json)
and generated bench CAD files remain history. They are not current entry points.
The latest source and build generate floor vehicles only.

Next, survey arm mounting heights and accessible floor approach regions, select
the centrifuge/rotor and actual labware, and measure the intended route and
dummy payload. Those inputs determine handoff height, local registration,
stationary holding, steering, drive and power sizing.
