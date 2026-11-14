# CAD and L01 layout pin revalidation

Rebuilt and checked on 14–15 November 2026.

The analytical native-evidence check previously resolved a report built with
an older `scripts/furniture_model.py`. Its builder also defaulted to a fixed
historical CF01 report. The synthetic-scene build now records the checked
native CF01 report and its SHA-256; the analytical builder resolves and verifies
that binding instead of selecting a revision by name. The analytical report
also pins the actual selected native report.

The L01 transfer protocol previously pinned the layout before TapeStation,
NanoDrop and Qubit were installed. Its layout pin now matches the installed
composition. The transfer builder additionally handles the installed
TapeStation's single-model report when binding upstream native inputs; it
checks the default case, successful source binding and actual artifact bytes.
No motion limits, collision thresholds, source poses or device positions were
changed for this repair.

Installed layout SHA-256: `040c5407d04cb34e250003acc649b0b47b7c7af2169b64f0a47486d13af41228`.

## Fresh native evidence

These builds were executed in the isolated `codex/fix-cad-layout-pins` worktree.
The generated CAD files and complete reports remain local, under that worktree's
`cad/` and `exports/generated/` directories. The receipt below records their
revisions and hashes without committing generated CAD or rewriting historical
reports and curated media. Rebuilds may allocate a different revision suffix.

### L01 static composition

- Revision: `lab-layout-l01-040c5407d04c-r2`; report SHA-256: `dcc7db63ab206aa9b16ea0261cd9744fca5a951e8d4b2d185e50ad98859757ad`.
- FreeCAD: 878 bodies, no invalid geometry, static overlaps, corridor or
  transporter-route collisions; all 171 equipment access poses passed.
- Cross-CAD: 20 instance comparisons and 87 equipment-body comparisons passed.
- Nine vendor housing metrics use the existing checked local-body properties
  under rigid placement because SolidCraft cannot integrate those world-space
  rational surfaces directly. This remains a documented limitation, rather
  than a claim of complete direct world-space measurements.

### Independent CF01 and reference-bank composition

- Revision: `synthetic-lab-scene-a3853d4f9bf1`; report SHA-256: `dc47fb91d2cd003e8015112b18fe8d463c2ef201bfc9e462c8e70399008915f9`.
- Independent SolidCraft CF01 review: 241 bodies in each of the two successful
  frozen poses, followed by source-derived NanoDrop/Qubit composition.
- Both composed poses and both FreeCAD instrument approaches passed. The
  instrument screen checked 191 CF01 path samples, two approaches and NanoDrop
  hinge positions from 0° to 75° in 5° increments, with no collisions.
- Minimum NanoDrop-lever/arm clearance lower bound: 27.8242 mm against the
  unchanged 5 mm requirement. This screen excludes the carried tube/cap and
  does not certify continuous swept volume or connecting instrument paths.
- Reference images were rendered using the CPU fallback; numerical geometry
  and cross-CAD comparisons are independent of that display limitation.

### Current-layout transfer audit

- Revision: `lab-transfer-l01-93cc10dcf3a2-r2`; native audit SHA-256: `959e2fe35d15e7cec0be868b3cae0e76eda4bccb0757130cb0b4d9f380c89221`.
- FreeCAD passed all 4594 requested frames (4508 distinct states), with no
  collision failures. Endpoint prechecks passed; native arm-frame agreement
  reached a maximum matrix-element error of 1.82e-12.
- Conservative minimum furniture/equipment distance lower bound: 124.1799 mm,
  against the unchanged 5 mm requirement. The nearest reported pair is the
  ArmC A3 housing and Freezer01 cabinet at the initial vehicle approach.
- Comparison with the previous timeline confirms identical arm/station curves,
  poses, events, segments, sample envelope, limits, keyframes and physical
  duration (1248.694434 s). Only source bindings and the definition's layout
  pin differ. The new layout geometry was audited in full rather than adopting
  the previous native motion report.
- Completed transfer report SHA-256: `63fa173c7c486a024e90e05ebe3a49736f04acf8e4179a19f389fd65f941b688`.
- Actual SolidCraft export: 257 frames / 4369 rigid-pose comparisons passed, with maximum
  position error 0.02805101 mm and rotation-element error 0.0000489818.
- Canonical dynamics and the derived preview were revalidated at completion.
  The installed SolidCraft preview remains linear; it is not a native C2/PVA
  execution qualification. Existing lenient STEP tessellation warnings do not
  establish imported surface fidelity.

### Analytical composition

- Revision: `two-arm-analytics-1f0ba0354e58-r4`; report SHA-256: `225a883add6f5a60041bfb1784584fe27b83145ebbb49685d95a0e69eb68efdf`.
- All 23 instance comparisons between independently built native CAD models
  passed; all 14 support checks passed, with no geometric collisions.
- The report now binds current `scripts/furniture_model.py` SHA-256 `ba37509ed2030c4c3c479eba85fe019230d269b2978a8fee45a86c880fb6b76a`, the checked current reference-bank report and the actual selected native CF01 report.

## Validation and reproduction

The final source/regression run passed 81 tests in the existing project test
environment. A separate final run passed the three native-evidence tests and
repeated the originally failing TR01 handoff-height test: 84 distinct targeted
tests, with no failures or native-evidence skips. Both original failing checks
now pass. The final native test verifies current source and actual CAD artifact
hashes, rather than accepting only a declared successful build.

```sh
python3 scripts/build_synthetic_lab_scene.py
python3 scripts/build_analytics_concept.py
python3 scripts/build_lab_layout.py
python3 scripts/build_lab_transfer.py
python3 -m unittest tests.test_analytics_concept tests.test_assembly_model \
  tests.test_lab_transfer_model tests.test_lab_transfer_build \
  tests.test_lab_layout_model tests.test_synthetic_lab_scene
```

Use a project test environment containing `jsonschema` for the schema tests.
The builds require the configured native FreeCAD Python and SolidCraft CLI,
plus the checked upstream arm/instrument inputs described by their builders.
Current local locator indexes may point into the isolated worktree, retaining
an original native-report path and hash. Rebased locators do not change native
proof bytes or checksum values. A new checkout generates its own local reports.

The geometric screens retain their declared sampling and contact exclusions.
No continuous swept-volume, hardware, biological or human-safety qualification
is inferred. The provisional room and device dimensions remain unchanged.
