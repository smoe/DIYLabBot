# H02 full-arm pickup animation

The [interactive replay](../exports/generated/h02-arm-animation-f016aa440059/preview.html)
shows the complete 8.677-second approach, grasp and extraction with the existing
arm, gripper, passive H02 holder and eight occupied neighbors. Play/pause,
scrubbing, 0.5×/1×/2× speed, full-arm/detail views, drag-to-orbit and scroll zoom
allow inspection without changing the modeled motion. Playback starts paused,
stops at extraction completion and requires an explicit replay.

Approach takes 3.70 seconds. The jaws then close in about 1.277 seconds while
the tube remains seated. A further 3.70 seconds extracts the tube by 60 mm.
The shared jerk-limited S-curve reaches the unchanged acceleration cap of
20 mm/s² and jerk cap of 100 mm/s³. The 60 mm strokes reach 30 mm/s and have a
short speed-limited cruise. Live speed and acceleration readouts make this
visible. The grasp event is synthetic; it does not supply physical feedback.
There is no invented return stroke or automatic repetition.

The viewer evaluates the existing source polynomial coefficients and analytic
IK continuously, then applies the shared joint frames. It does not linearly
interpolate sampled joint poses. Meshes come from the checked rounded 2 mL
FreeCAD assembly. Display-only arm vertices are welded at 0.1 mm, vendor detail
at 1 mm; these meshes are not collision geometry. The unchanged
[full-arm CAD validation](tube-frame-h02.md#full-arm-direct-pickup) remains the
clearance evidence, with its documented assembly-contact exclusions.

Build with `python3 scripts/build_h02_arm_animation.py`. The build verifies the
existing native build's source and artifact hashes before exporting meshes.
`cad/h02-arm-pickup/animation-report.json` resolves current output paths. The
HTML fragment is self-contained for the conversation viewer; the linked preview
wraps it with the visualization runtime for standalone browser inspection.

The browser verifier is `scripts/verify_h02_arm_animation.cjs`; it takes an output
directory and the bundled Node package directory containing Playwright. Native
placement comparisons pass at seven times, including interior times. Browser
IK and all link transforms agree with Python at 81 times, including every S-curve join,
both sides of the joins and interior times (maximum matrix difference below
4e-13). Playback, scrubbing, detail view and widths 320/736 px pass, with no
browser errors. Full-arm, close-up, narrow and dark views were visually reviewed.
The [animation evidence](media/h02-arm-animation.provenance.json) records source,
native model, output and browser-check hashes. This adds visual replay, not a
new collision qualification or hardware execution.
