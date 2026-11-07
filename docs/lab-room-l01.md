# Abstract laboratory room — L01

Prepared on 28 October 2026 from the owner's description of a room analogous to
the institute environment in Rostock. This is an editable spatial sketch with
provisional dimensions. It is not a measured room or a reconstruction of the
institute's building. The floor-plan photograph is still pending.

Updated on 29 October 2026: the window-side bench is split by a vertical concrete
support close to the windows. The owner reports approximately 300 mm width and
500 mm depth, with its front aligned to two straight bench runs toward the room
corners. The window curvature stays unchanged. Heating covers occupy the space
behind the straight bench backs and around the support in this provisional
interpretation. The support's exact lateral position and window setback remain
unknown. The render colours were chosen for legibility, not obtained from a
photograph or measured finish information.

The central unit now has an open shelf at 1,500 mm and two closed cupboard
envelopes whose underside starts at approximately 1,750 mm, following the owner's
height references. The intervening 250 mm band has no back panel; narrow uprights
leave open spans for reaching through to the other side. The window benches no
longer have cupboards or plinths underneath; two open leg envelopes support each
worktop. Actual reach, fixings and load capacity remain unverified.

![L01 room with benches and storage](../cad/generated/lab-room-l01-7f455f722169/room-iso.png)


## Source layers for L01

The entry point `model/lab-room-l01.shared.json` is now a pinned composition of
`model/environments/l01.geometry.json`, `model/furniture/laboratory.catalog.json`
and `model/furnishings/l01.furnishings.json`. The shell can be evaluated without
furniture. The furnished room retains its body IDs, named frames and existing
equipment positions. The four-level target and the current implementation scope
are documented in [ARCHITECTURE.md](../ARCHITECTURE.md).

The build entry remains `python scripts/build_lab_room.py`. Run
`python scripts/validate_assembly_schemas.py` with the optional `jsonschema`
development dependency to validate the source contracts. Furniture placement is
currently translation plus yaw; general device attachments and multi-room or
corridor topology remain future work.

The native five-case build was also executed with the installed macOS runtimes
(FreeCAD 27.1 and SolidCraft 0.40.0-rc.2):

```sh
PYTHONPATH=/Applications/FreeCAD.app/Contents/Resources/lib \
python3 scripts/build_lab_room.py \
  --freecad-python /Applications/FreeCAD.app/Contents/Resources/bin/python \
  --solidcraft-cli /Applications/SolidCraft.app/Contents/MacOS/solidcraft-cli
```

The old/new native comparison and current cross-CAD build are recorded locally
in `cad/lab-room-l01/shared-build-report.json`; exports remain ignored by Git.

## Layout and orientation

The origin is the inside left corner of the entrance wall at finished floor
level. Looking from the doors toward the windows, +X is right, +Y points toward
the windows, and +Z is up. Both sidewalls meet the entrance wall at 90 degrees.
The right sidewall is shorter. The exterior/window boundary is represented by
an adjustable curve influenced by the building's oval outline.

Two door openings occupy the entrance wall, which has no bench. Left and right
wall benches and two window-side bench sections surround an island of two long benches
placed back to back. Both end passages and both side aisles are kept open in
this provisional geometry. Four closed lower-storage blocks remain below the
side benches and central island. The two window worktops have open lower space
and simple legs. Two shallower upper-storage blocks are assumed along the
sidewalls. Their actual locations and any additional shelf tiers remain open.
A narrow shelf and two higher cupboard modules stand above the island's centre line.

The model contains 41 final bodies grouped into room shell, perimeter benches,
island, island shelf, upper storage and building services. Three grey heating-cover envelopes
fill the rear gaps and the clearances around the concrete support. Their slots,
airflow and small-object retention are not modeled or tested. Walls are translucent for inspection; no ceiling is
drawn. Cabinet interiors, doors and opening sweeps are omitted. The three window
divisions and exact door locations are assumptions, not observations.

![Top view of provisional L01](../cad/generated/lab-room-l01-7f455f722169/room-top.png)

The top render shows the full wall height, including lintels above the doors;
it is not a conventional horizontal section through the door openings.

## Adjustable provisional dimensions

| Dimension | Starting value |
|---|---:|
| Inside width | 6,600 mm |
| Left / right wall length | 7,000 / 6,600 mm |
| Facade bulge relative to endpoint chord | 450 mm |
| Room height / wall thickness | 2,800 / 180 mm |
| Two door openings | 900 × 2,150 mm each |
| Door left-edge positions on entrance wall | 600 / 5,100 mm |
| Perimeter bench depth / worktop height | 700 / 900 mm |
| Window-side bench depth | 500 mm, provisional |
| Concrete support width / depth | approximately 300 / 500 mm, owner-reported |
| Support lateral offset from room centre | 0 mm, provisional |
| Support setback from central facade reference | 75 mm, provisional |
| Heating-cover thickness / gap at room corners | 20 / 75 mm, provisional |
| Central island length / total width | 3,400 / 1,500 mm |
| Island distance from entrance wall | 1,700 mm |
| Upper-storage depth / underside / height | 320 / 1,550 / 600 mm |
| Central shelf length / depth / thickness | 3,100 / 350 / 25 mm |
| Central shelf top height / end setbacks | 1,500 / 150 mm |
| Three central shelf upright sections | 40 × 40 mm |
| Central cupboard underside / height / depth | 1,750 / 600 / 350 mm |
| Open band above shelf | 250 mm |
| Window-bench legs | Four 40 × 40 mm leg envelopes |

Every parameter has an unknown measured value (`measured_mm: null`). The numbers
above are editable placeholders; only the support width/depth also carry the
owner's approximate reported values. Shelf height and cupboard underside also
record the owner's 1,500/1,750 mm references. At the starting values the side aisles are
1,850 mm, the entrance-end passage is 1,700 mm, and the window-end passage is
about 1,460 mm to the straight window-bench fronts. Sidewall upper storage is set back 380 mm from the side-bench front and
starts 650 mm above the worktop. These are geometric distances, not qualified
human/robot passing, head-clearance, accessibility or egress dimensions.

The facade uses a 12-segment quadratic bulge:

`x(t) = t × room_width`

`y(t) = (1−t) × left_depth + t × right_depth + 4t(1−t) × facade_bulge`

This is a portable approximation, not a fitted ellipse. Facade, glazing and the
rear edge of the heating covers use the same samples. Each window-bench section
is a straight quadrilateral, with its front aligned to the support at the inner
end. The covers fill the varying strip between the straight bench backs and
curved facade. The support does not cut or reshape the glazing. Rear wall
thickness, support depth and window-bench depth are measured along Y. Detailed
joinery between side benches and window sections is not modeled.

The old central frame `L01.WindowBench.Worktop` is replaced by
`L01.WindowBenchLeft.Worktop` and `L01.WindowBenchRight.Worktop` so a work reference
does not sit inside the concrete support. The support has `L01.ConcreteSupport`.
Its position, width/depth, bench depth and cover dimensions are native parameters.

The central shelf is centred on the seam between the two island worktops. Its
length follows `island_length - 2*island_shelf_end_inset`. The default board
underside is 575 mm above the worktops, and it leaves a 575 mm worktop strip on
each side. Three uprights extend from bench height to the board underside; their
positions follow the island length and shelf setbacks. The named reference
`L01.IslandShelf.Top` follows the board. Three narrow upper uprights extend
from the 1,500 mm shelf top to the 1,750 mm cupboard underside. Two cupboard
modules occupy the upper level, with a provisional 10 mm gap between them and
their own named bottom frames. The band between shelf and cupboards has no back
panel. Cupboard depth and height are provisional. All are layout envelopes,
without selected fixings, load rating, rigidity or item-retention design.

## Current native files and source

- [FreeCAD room](../cad/generated/lab-room-l01-7f455f722169/default.FCStd).
- [SolidCraft room](../cad/generated/lab-room-l01-7f455f722169/default.sc).
- [STEP exchange file](../exports/generated/lab-room-l01-7f455f722169/default.step).
- [Leading shared source](../model/lab-room-l01.shared.json), format `solidcraftbot.lab-room/2`.
- [Current comparison report](../cad/lab-room-l01/shared-build-report.json).

FreeCAD exposes the dimensions under `ModelParameters`. SolidCraft exposes the
same named user parameters. Boxes, polygon points, extrusion depths and the
FreeCAD named door/bench frames follow parameter expressions. Both programs
can therefore adjust dimensions natively. Native edits do not return to the
shared source. For a durable change, edit `parameters` in the JSON and regenerate:

```powershell
python scripts/build_lab_room.py
python -m unittest discover -s tests -v
```

The loader rejects overlapping/out-of-wall doors, reversed sidewall lengths,
nonpositive passages and invalid vertical arrangements. Native editors do not
enforce all these source-level conditions; revalidate after changes.

Portable room, bench and storage semantics live in
[lab_room_model.py](../scripts/lab_room_model.py). Both adapters consume the same
operations. FreeCAD independently creates native boxes, expression-constrained
polygon sketches, extrusions and cuts; it does not import STEP as its source.
SolidCraft uses parameter-driven primitives and sketch points. The default
SolidCraft model was generated through MCP; the same commands run through the
CLI in the reproducible build.

Five cases compare all 41 bodies for validity, volume, centre, bounding box
and symmetric STEP difference. Door and bench frames are checked against their
parameter-derived positions, including worktop heights. A wider room with more
facade bulge is also tested by native parameter edits in both CADs. A second
native edit and fourth build case shift and resize the support. Checks verify
the aligned bench fronts and no intersection between support, bench sections
and heating covers. Source tests verify that support edits leave facade and
glazing geometry unchanged. The deeper case changes wall lengths, bench height
and upper-storage depth. A fifth case and third native edit change island length,
shelf/cupboard depth, height and end setbacks. Checks verify that the shelf stays centred,
inside the island footprint and above both worktops, with the uprights meeting
the worktops and shelf underside without penetrating the worktops. Upper-post
contact heights and cupboard-bottom frames are checked. Two cross-island line
probes between uprights pass through the open band; they establish geometric
openness only, not hand-size, reach distance or ergonomic qualification. Window
legs are checked against floor and worktop heights. Source tests verify that
window cupboards and their plinths are absent. Saved FreeCAD
files are reopened, and their colors/visibility/camera are stored. SolidCraft
isometric and top views were visually inspected; FreeCAD GUI rendering was not
separately tested.

This revision passed five cross-CAD cases and ten L01 source tests. The broader
offline suite ran 128 tests and reported four MB01 validation failures because
saved mobile-base evidence refers to the older arm source. The failure details
are in the [offline test log](../exports/generated/lab-room-l01-7f455f722169/offline-tests.txt);
they concern the separate mobile-base artifacts.

## Completing the environment

The room model reserves stable room, door and bench IDs. A separate
[equipment layout study](lab-layout-l01.md) now places three arms, CF01, TR01,
T01 and racks while retaining this room source. Its static checks and
position-only reach screens are documented there. Robot navigation, traffic,
door/furniture sweeps, utilities and physical operating clearances remain
unvalidated. No ROS environment or building model is generated.

From the floor-plan photograph, establish a readable scale or one known length,
the room's location in the building, wall endpoints and facade shape, door
positions/widths/swings, window positions and actual bench/storage dimensions.
Then register L01 in a building coordinate frame; that pose is currently null.
Keep observed dimensions separate from assumptions as the remaining rooms are
added.
