# Used-tip collector T01 — review concept

Prepared 28 October 2026 for the requested **10 µl, 200 µl and 1000 µl pipettes**.
This station removes disposable tips; the pipette remains on the robot.
The three lanes empty into one common removable bin.

![T01 collector with UMR and three exchangeable fork inserts](../cad/tip-collector-t01/collector-shared-iso.png)

## Shared development in SolidCraft and FreeCAD

Both native models now come from [one CAD-independent source](../model/tip-collector-t01.shared.json).
The bin carries **UMR**, using the robot's same bold outline letters, 24 mm high
and raised 0.8 mm from its front face. The letters belong to the removable bin
group. Its mechanical design and the three provisional groove widths are retained.

- [Current native SolidCraft model](../cad/generated/tip-collector-t01-be9cf1f341cc-r4/TipCollector_T01_Shared.sc)
- [Current native FreeCAD model](../cad/generated/tip-collector-t01-be9cf1f341cc-r4/TipCollector_T01_Shared.FCStd)
- [Current STEP assembly](../exports/generated/tip-collector-t01-be9cf1f341cc-r4/default.step)
- [Cross-CAD report and latest model paths](../cad/tip-collector-t01/shared-build-report.json)
- [Front view of UMR](../cad/tip-collector-t01/collector-shared-front.png)

```powershell
python scripts/build_tip_collector.py
python -m unittest discover -s tests -p test_tip_collector_model.py -v
```

Edit driving values under `parameters` in the shared JSON, then rebuild both.
For example, `groove_M` changes the middle groove and `bin_h` changes the bin
height together with the support height, top pilot bores, fork plane and markings.
`grooves` also retains the original draft dimensions as descriptive metadata;
the `parameters` values drive the generated geometry. New runs use new folders;
the report is the current model locator. The original T01 source is historical.

FreeCAD exposes these values under **ModelParameters → Shared dimensions (mm)**.
Boxes, cylinders, taper sketches, extrusions and booleans are native features;
portable label faces are built from lines and quadratic curves. No STEP import
forms the FreeCAD model. Colours, final-body visibility and a camera are saved.
SolidCraft retains expression-driven sketches and parameters. Native edits are
explorations and do not update the shared JSON. Change label text or outline scale
in the source and rebuild; the native UMR height is read-only in FreeCAD.

The common builder checks 14 bodies in the default design, with `groove_M=7 mm`
and with `bin_h=160 mm`. For each case it compares analytic volumes/centres,
SolidCraft measurements, native FreeCAD geometry and the symmetric difference
against SolidCraft STEP solids. It also tests both parameter edits directly in
each saved native model. FreeCAD reopening and static interference checks pass.
Saved FreeCAD presentation metadata is structurally checked; a FreeCAD GUI render
has not been verified. These checks do not establish real tip fit or stripping
forces.

## Stripping principle

With the pipette vertical, lower the **top rim of the used tip below the fork**.
Slide the exposed shaft into the groove from the front, then lift the pipette
vertically. The underside of the fork holds the tip rim down while the pipette
withdraws. The released tip falls into the bin. The groove must clear the shaft
and retain the tip rim; sideways rubbing on the tip cone is not the intended
release mechanism.

The narrow section has parallel sides and a rounded closed end. A flared 20 mm
entrance helps locate the shaft, but is not a license to push against an edge.
The nominal capture point is inside the straight section, before its closed end.
The inserts bolt to the rear beam; that beam and two posts carry the reaction to
the table-mounted base. The removable bin is not the stripping-force support.

| Lane / colour | Intended pipette capacity | Draft groove width | Status |
|---|---:|---:|---|
| S / orange | 10 µl | 4 mm | Unqualified placeholder |
| M / teal | 200 µl | 6 mm | Unqualified placeholder |
| L / blue | 1000 µl | 9 mm | Unqualified placeholder |

**Capacity markings identify the intended lanes, not proven compatibility.**
No manufacturer, pipette article or tip article has been selected. Different
tips of the same nominal volume can need different inserts. Measure the exposed
shaft, smallest tip-rim diameter, rim geometry and available vertical gap to the
pipette body/ejector sleeve. For each article, require:

`shaft_max + 2 × running_clearance ≤ groove_width ≤ rim_min − 2 × capture_margin`

The 4 mm insert thickness plus operating clearance must also fit above the tip
rim without hitting the pipette or its ejector sleeve. If that gap is unavailable,
this fork concept needs a different interface or use of the pipette's ejector;
do not compensate by increasing robot force. Determine the real withdrawal
stroke, release force and tool retention load experimentally.

## Dimensions and service access

| Feature | T01 dimensions |
|---|---|
| Base | 240 × 184 × 8 mm, four Ø6.6 mm table-mount placeholders |
| Removable bin | 184 × 144 × 150 mm outside; 4 mm walls/floor |
| Bin opening | 176 × 136 mm, rim at Z=158 mm |
| Fork undersides / tops | Z=168 / 172 mm |
| Each insert | 48 × 96 × 4 mm; front Y=−42 mm, rear Y=54 mm |
| Lane centrelines | X=−56, 0, +56 mm |
| Narrow section | Y=−24 to +5 mm, then a semicircular end |
| Capture reference | Y=0 mm; Z depends on the measured article |
| Rear beam | 232 × 24 × 8 mm; centre Y=42 mm |
| Insert fixing | Two Ø4.5 mm through holes per insert, 32 mm apart, at Y=42 mm |
| Bin removal | Slide towards −Y; 10 mm gap from rim to fork underside |

Axes: X across the lanes, +Y towards the rear beam, +Z up from the base underside.
All lengths are in mm. The pipette is vertical in this concept, with its shaft
along Z. Robot joint angles and an installation transform are not defined here.

The cavity's geometric volume is approximately 3.49 L. This is **not** a working
tip capacity. The synthetic check uses a 120 mm-long tip below a collar at Z=167 mm:
its bottom is Z=47 mm, giving 35 mm clearance above the empty floor at Z=12 mm.
A provisional waste envelope up to Z=35 mm leaves only 12 mm clearance. That fill
limit, tip length and upright cylindrical envelope are invented test values.
Real tipped, bridged and piled waste, including tips leaning through a groove,
must determine the actual usable capacity and emptying threshold.

Rails and a rear stop locate the bin with 1 mm nominal side/rear gaps. No front
latch, sensor, carrying handle or transport lid is modeled. Keep manual servicing
outside a robot reservation; a liner or bag must not project into the drop path
or compromise locating the bin. Select the bin material and cleaning/disposal
procedure for the actual laboratory use. Printed prototype walls are not a
cleanability, chemical-compatibility, containment or leak-tightness qualification.

The fork inserts are candidates for metal fabrication; material, edge radii,
deburring and allowable wear need tests. Clearance holes and blind pilot bores
are mounting placeholders. Screws, threads, preload, post-to-base attachment and
the upward stripping-load path require mechanical design and verification.
CAD default density does not establish real station mass.

## Robot interaction proposal

1. Reserve the collector workspace for one arm. Up to three arms may share it
   sequentially. Confirm bin seated, acceptable fill, clear drop region, a correct
   qualified tip profile and usable force/observation feedback.
2. Approach above the opening from the front. Lower into the bin at the selected
   lane, outside the fork entrance. Only then translate into the groove. The
   draft's local collar reference moves from Y=−54 mm to Y=0 mm; these values are
   illustrative, not a robot program.
3. Lift vertically at a qualified speed and limited force/stroke. Confirm that
   the tip detached and cleared the fork before any lateral retreat. A commanded
   lift alone does not prove ejection.
4. Withdraw the complete tool and robot, then release the reservation. Stop and
   reconcile the state on an overload, jam, missing bin, full bin, stale view or
   uncertain tip release. Do not retry blindly or pass the used tip over clean
   racks while attempting recovery.

Bin presence/fill and tip-release sensing are requirements for integration;
no sensor or working interlock is implemented. Proposed checks can use suitable
local sensing and the planned cameras after qualification. Servo position alone
does not measure tip release or stripping force. Include withdrawal loads and
moments in the later pipette adapter and arm verification. The arm still ends at
its existing general flange; no adapter or robot geometry has been changed.

## Original T01 review files and checks (historical)

- [Native SolidCraft design](../cad/tip-collector-t01/TipCollector_T01.sc)
- [Native JSON](../cad/tip-collector-t01/TipCollector_T01.native.json)
- [STEP assembly](../cad/tip-collector-t01/TipCollector_T01.step)
- [Bin STL for dimensional prototype review](../cad/tip-collector-t01/TipCollector_T01_bin.review.stl)
- [Top view](../cad/tip-collector-t01/collector-top.png)
- [Original station dimensions and assumptions](../model/tip-collector-t01.json)
- [Original command generator](../scripts/prepare_tip_collector.py)
- [Original validation and file hashes](../cad/tip-collector-t01/draft-validation.json)

The original generator and `build.commands.json` reproduce the earlier
SolidCraft-only review without UMR. Use the shared development command above for
current work. The arm source remains `model/robot.json`. Old native body names
retain a draft width after an interactive edit; current shared models use stable
`Fork_S`, `Fork_M`, `Fork_L` identities.

`python scripts/validate_tip_collector.py` audits the saved CAD evidence, native
source association, exported bin mesh and artifact hashes. It does not rerun a
CAD engine or perform a new physical test; capture fresh evidence after a rebuild.

Core volumes and bounds are checked against analytic references before the
0.3 mm-deep capacity engravings. Engravings are checked separately for closed
bodies, unchanged bounds and a positive, small removed volume. A native parameter
test changes the middle groove from 6 to 7 mm and restores 6 mm. The computed
volume change is checked independently. The final static model is checked for
timeline errors and solid interference, then rendered from the CAD geometry.
These are geometric checks only. This fixed station has no moving joints; the
arm's joint solution and its stand pose were not changed or tested here.

No selected real tip profile, complete pipette envelope, continuous robot path,
inverse kinematics, pile simulation, release force, stiffness, drop reliability,
wear, splashing or aerosol containment has been verified. Before fabrication of
working inserts, measure the three actual articles and run a separate force and
repeatability bench test using existing pipettes and workshop equipment. Then
calibrate the station and validate full approach/withdrawal paths with the real
tool. Costs and mounting hardware remain to be estimated within the existing
3,000–5,000 EUR prototype budget; no priced bill of materials is claimed.
