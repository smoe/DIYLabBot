# Tube carrier and handoff dock — H01

**Historical enclosed-sleeve concept.** The owner requested optical access and
bottom-assisted transfer after reviewing H01. The current investigation is the
[open H02 frame with bottom lifter and split receiver](tube-frame-h02.md).
The H01 source and native snapshots below remain preserved.

Prepared 28 October 2026 at the owner's request. H01 is an abstract mechanical
proposal generated independently in native SolidCraft and native FreeCAD from
[one source](../model/tube-carrier-h01.shared.json). It is not a fabrication
release, a measured fit for an Eppendorf article, or an operating handling system.
The volume classes here are **1.5 mL and 2.0 mL**.

![H01 comparison: 1.5 mL docked left, 2.0 mL at front right](../cad/tube-carrier-h01/carrier-overview.png)

The owner reports that the conical 1.5 mL tube is stable in a small hole while
the round-bottom 2.0 mL tube is not. This supports using article-specific body
inserts rather than relying on the bottom shape alone. The external tube shapes
in H01 illustrate that distinction; they do not reproduce a manufacturer's
dimensions, material wall or nominal internal volume. Eppendorf's
[Safe-Lock catalogue](https://www.eppendorf.com/product-media/doc/en/11112106/General_Catalog_Main-Eppendorf-Catalog-UK-Version.pdf)
lists conical and round bottoms for those respective Safe-Lock sizes. Other
articles, including other Eppendorf families, must be checked individually.

## Mechanical proposal

| Feature | H01 interpretation |
|---|---|
| Dark blue carrier | Same shell, keyed foot and grip pads for both variants |
| Green / blue metal insert | Shape-specific cavity; 1.5 mL conical and 2.0 mL rounded |
| Upper insert face | Proposed seat beneath tube collar, defining the mouth height |
| Amber side clips | Concept retention over the collar; compliance and release not designed |
| Rear amber locator | Concept hinge orientation key, leaving the mouth clear |
| Grey dock rails | Front insertion and lips over the foot to limit uplift |
| Amber front latch | Blocking envelope, retracted sideways before transfer |
| Grey gripper at 2.0 mL carrier | Space envelope around external grip pads, with 0.2 mm nominal side clearance |

![H01 section through both docked carriers](../cad/tube-carrier-h01/carrier-cutaway.png)

The carrier foot is 26 × 24 × 3 mm; the two outer grip surfaces are 34 mm apart.
Each grip pad has 10 mm depth and 8 mm height. These are proposed robot
interfaces, not tube dimensions. The illustrative collar seat is at Z=42 mm and
mouth reference at Z=44 mm above the dock base underside. Metal insert and
carrier bottom share Z=8 mm, proposing a heat path to the dock floor.
The demonstration docks are 92 mm apart; this spacing only separates the variants
on screen and does not define a final station layout.

The hollow tube reference includes an illustrative upper cavity, collar, cap and
hinge. The cap is shown closed without a contact or latch simulation. Its shape
and the clips must be redesigned together from the actual article. The first
prototype can be loaded manually outside the lid mechanism, with the clips
removed/retracted. H01 has no automatic clip release, fastener design or
loose-tube rack pickup mechanism.

The rounded bottom and cavity use a six-segment radial profile, sampled at 15°
intervals and revolved through 360°. This explicit geometric approximation keeps
both native CAD representations based on the same portable profile and avoids
tangent sphere/cylinder booleans. It is not manufacturer geometry. All fits
require measurement.

## Handoff and motion

The stationary dock allows sender and receiver to work sequentially. A single
arm may park a carrier while changing tools; later two arms can share the same
dock. No additional arm or pipette attachment is added to A01.

1. Close the tube lid and confirm tube retention in the carrier.
2. Reserve the dock and inhibit lid motion. Retract the dock latch.
3. Carry the assembly upright, gripping its external pads, and approach from the front.
4. Confirm seating, tube presence and hinge orientation.
5. Close the dock latch and confirm retention before the sender releases.
6. The receiver confirms its grasp before the latch retracts and withdrawal begins.

Sensor concepts and state transitions express design requirements. No sensors,
force limits, drivers, SiLA implementation or verified grip detection are supplied.
The gripper envelope follows the carrier to illustrate the approach space; it is
not a selected gripper or a modeled opening/closing mechanism.

Four independent sliders express the demonstration: `SlideV15` / `SlideV20`
translate 0–55 mm along −Y, and `LatchV15` / `LatchV20` translate 0–35 mm along +X.
Positions and limits are in **mm**, with no rotary joints. `comparison` shows
the 1.5 mL carrier docked and locked, the 2.0 mL carrier outside its unlocked dock.
The other named source poses show both docked/locked, docked/unlocked and outside.

## Shared model and generators

Checked native snapshot from 28 October 2026:
[SolidCraft H01](../cad/generated/tube-carrier-h01-8c7468aabb75-r3/TubeCarrier_H01.sc),
[FreeCAD H01](../cad/generated/tube-carrier-h01-8c7468aabb75-r3/TubeCarrier_H01.FCStd),
[STEP](../exports/generated/tube-carrier-h01-8c7468aabb75-r3/default.step).
The build report remains the current-model pointer after subsequent rebuilds.

```powershell
python scripts/build_tube_carrier.py
python scripts/render_tube_carrier.py
python -m unittest discover -s tests -v
```

- Source: [tube-carrier-h01.shared.json](../model/tube-carrier-h01.shared.json).
- CAD-independent semantic lowering and SolidCraft command generator:
  [tube_carrier_model.py](../scripts/tube_carrier_model.py).
- Native FreeCAD primitive/boolean/expression adapter:
  [build_tube_carrier_freecad.py](../scripts/build_tube_carrier_freecad.py).
- Build orchestration and comparison:
  [build_tube_carrier.py](../scripts/build_tube_carrier.py).
- Current native models, STEP and detailed validation locations:
  [shared-build-report.json](../cad/tube-carrier-h01/shared-build-report.json),
  under `cases[0].files` for the default concept.
- Model images and their exact source/model hashes:
  [render-manifest.json](../cad/tube-carrier-h01/render-manifest.json).

Each build uses a new source-hash directory under `cad/generated/` and
`exports/generated/`. Failed/older attempts are not current releases. Edit the
shared JSON and rebuild; native CAD edits do not flow back to it. `ModelParameters`
in FreeCAD exposes dimensions and `Controller` exposes the four slider positions.
SolidCraft retains the same parameters and native slider assembly joints, usable
through **Assemble → Drive Joints**. FreeCAD uses expression-driven placements,
not native Assembly solver joints. For reproducible pose changes, use the values
from `poses_mm`; dimension changes and motion positions are separate controls.
SolidCraft's generated joint-frame origins are numerical reference frames.
Rebuild after changing the module pitch to realign those glyphs with the geometry;
the source rebuild derives both docks and all frame origins together. Slider
travel limits retain parameter expressions in the native SolidCraft model.

## Validation and limits

The build creates default, all-lower-bound and all-upper-bound parameter cases.
Both independent kernels are compared by body count/name, volume, center of mass,
bounding box and symmetric STEP difference. Simple dock and tube-reference
volumes additionally have analytic checks. Each variable parameter is exercised
at both declared endpoints in the native models and compared across kernels.
The FreeCAD file is reopened and its presentation metadata is saved and checked.

For each case the SolidCraft solver visits the named poses and sampled transfer
and latch positions. FreeCAD checks the corresponding translations and BRep
intersections between different rigid components. Overlaps within a rigid
component are reported separately as construction/contact-envelope overlaps;
they are not qualified fits. The report records results and tolerances.

The sampled front slides do not prove continuous swept clearance or a complete
robot path. The two cap clips and hinge locator have no release/contact simulation;
stability, holding forces, deformation, cleaning, contamination separation and
thermal contact remain physical test tasks. Block temperature does not establish
sample or 1 µL wall-droplet temperature.

H01 is a separate handoff demonstration. It does not replace C01's 12 mm bore or
prove loading through C01's lid fingers. Integration needs a revised cold dock,
shared references, the actual gripper, parked lid-finger configuration and complete
insertion/removal paths. C01's existing SiLA FDL remains unchanged.
