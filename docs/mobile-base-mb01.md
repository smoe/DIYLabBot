# MB01 — manually repositionable bench arm

Owner-approved concept direction, 28 October 2026. A person can move the complete
arm aside to share laboratory bench space. The working task controls the actual
pipette tip relative to the actual tube, including orientation and depth. Accurate
return to fixed global bench coordinates and a precision docking station are not
requirements. Real camera precision remains to be measured.

## Shared construction

`model/mobile-base-mb01.shared.json` references the single arm source
`model/robot.json`. The arm references this external assembly through `mobile_base`.
The seven arm links and six rotary axes remain unchanged. Three semantic operations
describe a manual four-caster base, an adjustable support tripod and a rear handle.
`scripts/mobile_base_model.py` expands them once for both CAD adapters.

The nominal chassis is 400 × 340 mm, with a 10 mm deck and 44 mm wheel diameter.
The arm mounting plane is 56 mm above the nominal wheel contact plane. Four caster
envelopes provide manual repositioning; caster swivel/rolling and tire contact are
not simulated. A rear handle and tether anchor provide places to push and route
the supply cable. Cable flexibility, connector, slack, push force and table edge
containment remain open. Wheels are not motorized.

Three independent thumbwheel supports have guided stems, deck clearance bores and
44 mm pads. At the supported state their ideal 11 mm travel lowers the pads to the
table and raises the chassis 3 mm, unloading the wheels geometrically. When
retracted, the wheels touch the table and the pads have 8 mm clearance. The support
frame IDs are `MB01.Support.A/B/C`; `MB01.ArmMount` and `MB01.Handle` provide other
shared references. Screw pitch, retention, materials, actual contact, adjustment
mechanism and component selection remain unqualified. The ideal chassis lift is
a geometric model of load transfer, not an implemented lifting mechanism.
The rigid arm-to-deck CAD joint records the mounting reference; deck bolt
registration, fasteners and connection stiffness still require detailed design.

The supporting triangle is a geometry concept. No actual mass, centre of mass,
support stiffness, tipping margin, bench capacity or process force has been
established. Stable support is a design objective, not a measured performance claim.

## Working, folding and yielding the bench

Named poses in the source:

| Pose | Arm | Supports | Use |
|---|---|---|---|
| `working` | Existing stand pose | Deployed | Representative supported arm configuration; no pipette attached |
| `parking_supported` | Compact fold | Deployed | Fold before releasing the base |
| `manual_reposition` | Same compact fold | Retracted | Manually roll using the handle |
| `parked_aside` | Same compact fold | Deployed | Illustrative displaced/rotated parking location |

The parking angles are J1=0°, J2=0°, J3=90°, J4=0°, J5=90°, J6=0°.
These are within the current demonstration limits. The parked-aside location
(-300 mm, +120 mm, +25°) illustrates manual relocation; it is not a surveyed route
or proof of edge clearance. No tool or flexible tether is included in the measured
parking envelope. The arm still ends at its general flange.

`MB01.YieldAndResume` defines pause/withdraw, fold, release supports, manually move,
return/stabilize, reacquire the target and deliberately resume. Protocol IDs connect
the source to the sampled CAD checks. Manual relocation invalidates previous task
localization. Fresh observation of the actual tip and tube, observable depth and
orientation, acceptable image age, a clear path and operator resume are required.
These conditions are a design contract; no hardware interlock or visual servo
controller has been implemented. Pause/fault behavior must be tested before use.

## Generate and open

```powershell
python scripts/build_models.py --ros2
python -m unittest discover -s tests -v
```

The common entry builds the standalone arm and the mobile assembly. A mobile-only
rebuild is `python scripts/build_mobile_base.py --ros2`; this uses the existing
arm ROS description, so regenerate through the common entry after arm changes.
Every build gets a fresh directory based on both source checksums.

Current paths and checksums: [build report](../cad/mobile-base-mb01/shared-build-report.json).
It lists native SolidCraft and FreeCAD files for working, manual-reposition and
parked-aside states. Original generated models remain available as history.

SolidCraft exposes the original six axes, three independent support sliders,
an illustrative manual planar location, the ideal chassis lift and the rigid
arm mount. `MB01_ManualReposition` values are x/y in mm and yaw in degrees. These
are external assembly coordinates, not additional powered arm axes. The generated
pose scripts set the coordinated support/lift values. Independent native edits
must keep that relationship consistent; native edits do not update the source.

In FreeCAD, `Controller.J1…J6` edit the arm. `MB01_BaseX`, `MB01_BaseY` and
`MB01_BaseYaw` illustrate manual location; `MB01_SupportA/B/C` and
`MB01_ChassisLift` set the support state. The mobile macro offers named poses.
The hierarchy and expression-driven placements persist in the FCStd; the model
does not require a serialized Python proxy or a STEP import of the arm.

## What the checks mean

Both CADs are compared by named body, volume, centre and bounding box in three
states. Native FreeCAD edits of chassis length and wheel radius are compared to
regenerated SolidCraft cases; mounting height and support references follow the
same parameters. FreeCAD checks the fold at at most 5° joint increments, support
transfer samples, moved parking, table contact geometry and independent kinematic
probes for all arm and camera frames. Virtual camera cones are excluded from
physical collisions. FreeCAD documents are reopened after saving.

The SolidCraft solver checks the twelve assembly joints and their origins.
The external mounting offset is applied to oriented vendor STEP import matrices
in world coordinates; joint anchors receive the same offset. Bounding-box
comparisons use FreeCAD's tight analytic bounds, avoiding the excess margins of
its default BRep bounds for some vendor surfaces.

A failed final comparison can retain already passed native FreeCAD evidence with
`python scripts/build_mobile_base.py --ros2 --reuse-freecad-report PATH`.
This accepts only identical arm/base source snapshots, copies the native files
into a new revision, rechecks all sampled frames and parameter geometry, and
refreshes tight bounds. Original collision results remain linked by report
checksum; they are not presented as a new collision execution. SolidCraft and
the cross-CAD comparisons are rebuilt. The normal common entry still performs
the full build and sampled collision checks.

Sampling does not prove continuous collision-free motion, full workspace,
stability, human safety or liquid-handling performance. The future pipette/tool,
bench clutter and cable sweep need further checks. Saved native FreeCAD colors
and visibility are prepared; interactive GUI operation remains a separate check.

## ROS description boundary

`robot_mb01_working.urdf` and `robot_mb01_manual_reposition.urdf` add the same base
geometry in explicit m/rad to the existing six-axis arm description. Their mobile
base/support coordinates are fixed illustrations of manual states; no mobile
actuator is added to the six-axis controller. Wheel hubs and small bores are
omitted from conservative mobile collision/visual primitives. Arm angles still
come from joint states; the mock initial values match the selected source pose.
Runtime ROS/RViz,
real camera acquisition, navigation, contact physics and hardware execution are
not validated or implemented by this build.

Next measurements: actual tool/load mass, lateral compliance and tipping under
representative poses/forces; push/parking effort and time with coworkers; bench
edge containment and tether clearance; repeated manual relocation followed by
camera reacquisition and independently measured tip-to-tube error. Costs remain
open and must be reconciled with the 3,000–5,000 EUR first-prototype budget.
