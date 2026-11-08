# CF01 bench-mounted robot and output rack

The [shared pickup scene](../model/centrifuge-cf01.robot-pickup.shared.json) now
combines the existing six-axis [robot](../model/robot.json),
[centrifuge](../model/centrifuge-cf01.shared.json) and
[command contract](../model/centrifuge-cf01.protocol.json). A provisional
parallel tube gripper is attached to the arm's existing flange reference.
The [combined pickup report](../cad/centrifuge-cf01/robot-pickup-build-report.json)
lists the generated animation, native CAD views, playback macro and evidence.
The independent SolidCraft result is recorded separately in
`cad/centrifuge-cf01/solidcraft-pickup-build-report.json`.

The 60-second illustrative sequence opens the lid, raises tube 01, approaches
with open jaws, closes them around the tube body, extracts the tube along its
35° axis, and withdraws the robot with the tube. The pusher retracts and the lid
closes only after the robot and carried tube have cleared the centrifuge.
After the lid locks, the robot turns the tube upright in clear space, lowers it
into output rack slot 01, confirms support, opens its fingers and lifts away.
The tube stays in the rack. Playback can be paused/scrubbed; tube-handling and
rack-placement close-ups supplement the full assembly view.

| End time | State |
|---|---|
| 11.5 s | Lid fully open and held |
| 14.5 s | Tube elevated 16 mm axially, still supported by the pusher |
| 17.5 s | Gripper at the approach pose, 35 mm above the grasp along the tube axis |
| 20.5 s | Open fingers aligned around the tube body |
| 21.5 s | Jaws at 10.8 mm gap; synthetic grasp confirmation; rigid tube ownership transfers to gripper |
| 24.5 s | Tube extracted a further 45 mm along its axis; its tip is above the chamber rim |
| 28.5 s | Arm and retained tube at the withdrawal pose |
| 29.5 s | Synthetic independent workspace-clear confirmation |
| 30.5 s | Empty pusher parked; lid may start closing |
| 41 s | Lid closed |
| 42 s | Lid pins engaged; robot still holds the removed tube |
| 46 s | Tube upright outside the centrifuge |
| 50 s | Tube above empty output rack slot 01 |
| 54 s | Tube bottom reaches the rack base through the guide bore |
| 55 s | Synthetic rack-support confirmation; ownership transfers without a jump |
| 56 s | Fingers open after support confirmation |
| 60 s | Empty gripper withdrawn; tube remains in slot 01 |

Times, grasp and clearance confirmations are illustrative. They are not physical
sensor data or hardware timing predictions. The new scene is separate from the
earlier centrifuge-only demonstration, which deliberately reseated the tube.

## Geometry and motion source

The same six joint definitions, limits, vendor components and camera envelopes
are reused with **280 mm upper arm and 250 mm forearm** (previously 200/175 mm).
The synthetic equipment layout stores only parameter overrides of `model/robot.json`; it does not
duplicate the arm design. Native geometry, vendor mounting positions and joint
anchors follow those same dimensions. The generated `CF01_LongLink_Arm.FCStd`
retains the native parametric history of the arm variant. Full-pose inverse kinematics finds
joint configurations for the contact frame, with continuous nearby solutions
along approach, extraction, withdrawal and rack placement. A fixed grasp roll
avoids a joint-limit-induced wrist flip; consecutive trajectory samples are
checked for branch discontinuities. The tool points opposite the tube axis;
a fixed tool-to-tube transform established at grasp keeps the same
tube and cap rigidly attached to the moving gripper without a position jump.
No duplicate tube is left in the rotor.

The `parallel_tube_gripper_envelope` operation expands once into a mount,
actuator envelope, two stems and two contact pads for the native scene and
animation. Stepped fingers leave the wider cap free and touch the tube body
below the collar. It is a concept tool for this demonstration, not a selected
gripper, force/friction design or the still-excluded pipette attachment.
Its proposed flange-to-grasp distance is 55 mm; real fit, retention and grip
force remain open.

The revised pads are 5 × 6 × 9 mm, with the stepped stems retained farther
outboard to leave the cap free. The first bench-level trial passed intersection
checks but had a 2.9 mm finger/neighbor-cap gap. Slimmer, shorter pads improve
that approach gap; the final full-path audit must meet a 5 mm nominal equipment
clearance requirement. This is a geometric refinement, not a finger-strength
or grip-force qualification.

The local arm mounting frame is **[-330, 80, 0] mm, yaw −50°**, relative to
the centrifuge's bench frame. The base plate sits directly on the bench;
there is **no pedestal**. The longer-link variant resolves the bench-height
reach/joint-limit problem for this path. Bench attachment, tipping, link
deflection, actuator loads and settling remain unqualified; lower mounting
alone is not a measured stability result. The local frame is uncalibrated;
the L01 room layout and its older arm placement remain separate work.

The `guided_tube_rack` operation describes a 112 × 84 mm, 12-position rack
at **[-260, -280, 0] mm**, with 24 mm pitch. It has a 4 mm base supporting
tube bottoms, side rails, and a guide at 18–24 mm above the bench. Guide bores
are Ø13.8 mm with Ø18 mm conical entries. Against the illustrative Ø10.8 mm
tube body, the nominal radial clearance is 1.5 mm. The open fingers and seated
tube are checked against the actual rack bodies. Rack material and real tube
article fit remain open. This rack is a bottom-supported handling design;
the older TR01 cassette has tighter straight bores and is not substituted here.

The owner set **approximately 1 mm** as sufficient transport accuracy on
5 November 2026. This is a design target, not measured robot performance.
The larger rack entries accommodate that nominal lateral error; fine numerical
IK residuals are only solver checks. They do not establish hardware accuracy.
The existing centrifuge pocket has much less clearance, so pickup still needs
local alignment and/or compliant guidance. Pipetting accuracy requirements are
unaffected by the tube-transport target.

## Reproduce and inspect

```powershell
python scripts/build_centrifuge_robot_pickup.py
python -m unittest discover -s tests -v
```

The combined builder creates a new revision. It checks the upstream native-model
source and artifact hashes, generates the constrained trajectory, builds and
tests the FreeCAD scene, writes the animation, and independently constructs
the SolidCraft review poses from the shared sources. Source dimensions and protocol intent remain in JSON;
native snapshots are derived review files rather than additional master models.

- FreeCAD: seven posed scenes (`Closed`, `Grasp`, `Extracted`, `Withdrawn`,
  `ClosedAfterPickup`, `RackSeated`, `RackReleased`), a parametric long-link arm
  and `CF01_Robot_Pickup.FCMacro`. Run the macro to play or
  scrub all six robot axes, lid, pusher, jaws and carried tube. Its live GUI is
  prepared but has not been run here; the underlying native placements were checked.
- SolidCraft: `Grasp` and `RackReleased` review poses built using the existing
  native arm and centrifuge recipes, shared gripper/rack primitives and shared
  kinematics. These are **frozen review poses, not a native handoff motion study**.
  Per-body closure, identities, volumes and transformed centers are checked.
  A FreeCAD comparison is optional; it never provides geometry to this adapter.
- Interactive playback: meshes tessellated from the same native bodies plus the
  shared joint hierarchy and sampled joint trajectory. Vendor detail is clustered
  at 1 mm only for responsive display; exact BRep geometry remains in CAD checks.

The report distinguishes these backend capabilities. No ROS scene, hardware
trajectory execution, or SiLA server was added by this animation update.

## Executed checks and limits

The trajectory samples all six original joint limits at 0.25-second intervals
and checks end-effector position/orientation. Independent forward kinematics
from the original robot module agrees with the cached trajectory calculations.
Tests verify no jump at handoff, fixed tube-to-gripper attachment afterward,
cap keep-out, axial extraction above the rim, and withdrawal before closure.

`check_centrifuge_robot_motion.py` adaptively subdivides the actual
joint-interpolated playback path, including lid motion, fingers and carried tube.
It refines whenever consecutive body-bound corners move more than 2 mm or a
robot/lid angle changes more than 1°. It checks the entire path against the
centrifuge, moving lid, rack and bench, plus nonadjacent arm links and cap/tool
clearance. Conservative oriented bounds use the existing L01 separation test;
overlapping bounds are refined by exact native BRep intersection. Exact closest
robot-to-equipment distances are recorded in `native-motion-validation.json`.
The current report gives the executed sample count, spacing and smallest gap.

The original 17 station poses and seven self/grip snapshots supplement that
audit. Intended tube/pad and flange mounting contacts, adjacent joint interfaces
and internal tool assembly are excluded. These are discrete checks, not a
continuous swept-volume proof or dynamic validation. The displayed slot-01
transfer is checked; full-rack occupancy and every loading order need further
path validation. Endpoint reachability alone does not qualify those paths.
All twelve approach and seated endpoints have numerical six-axis reach checks.

The endpoint protocol trace uses the existing local mock: an unconfirmed tube
absence cannot complete removal; `RetractLift` and `CloseLid` are refused while
the robot-clear input is false. Heartbeats remain active through the sequence.
Removal confirmation follows extraction, and clearance precedes pusher parking
and closure. This validates local handshake behavior, not real sensors or a
networked ROS/SiLA deployment. [Protocol/runtime boundaries](centrifuge-cf01-protocol.md).

SolidCraft MCP inspection was attempted, but its allowed paths exclude this
project directory. The existing reproducible local SolidCraft CLI adapter was
used for the two source-derived review scenes and cross-CAD measurements.

## Zweisprachige Bedienung / Bilingual controls

Neu erzeugte HTML-Demos starten auf Deutsch. Über **Sprache / Language** lässt
sich jederzeit auf Englisch wechseln. Erklärungen, Bedienelemente, barrierefreie
Beschriftungen, Bewegungsphasen und Chargenzustände wechseln gemeinsam; Zeit,
Probenbesitz und eine laufende Wiedergabe bleiben erhalten. Proben-IDs wie
`Sample01` und die maschinenlesbaren Protokoll-IDs bleiben sprachunabhängig.
Das optionale Chargenpanel darf bei fehlenden oder fehlerhaften Daten ausfallen,
ohne die Bewegungsansicht zu blockieren.

Newly generated demos default to German. **Sprache / Language** switches all
explanations, controls, accessibility labels, motion phases and batch states
to English while preserving playback and sample ownership. Machine-readable
identifiers stay unchanged. An unavailable optional batch panel does not block
the motion view.

Die ausgewählten Medien unter `docs/media/` bleiben der historische Build.
Die Zuordnung dieses historischen Builds zu seiner Quellrevision und frühere
Prüfungen stehen im [Nachtrag zur Claude-Prüfung](cf01-claude-review.md).
Die aktuelle Berichtssemantik ist nachfolgend beschrieben.

## Aktueller lokaler Chargenlauf: Buchführung und offene Übergaben

```sh
python3 scripts/run_cf01_rack_batch.py
python3 scripts/run_cf01_rack_batch.py --transport sila2
```

Beide Optionen führen lokale Vertragsdecoder aus. Die Berichte werden mit
Profilhash und Zeitstempel unter `exports/generated/cf01-rack-batch-*/` abgelegt.
Der Eingangszustand ist auf ein bereitgestelltes Rack und einen leeren Rotor
beschränkt. Fiktive Massen und zeitlose Roboterübergaben bleiben ausgewiesene
Mock-Annahmen. `initial_state` enthält nur den Anfangszustand; Massenquelle und
Roboterübergabezeit stehen getrennt in `mock_assumptions`. Die Testuhr wird beim
Warten auf beobachtbare Befehle einschließlich Schleudern und Bremsen fortgeschrieben.
Die Rotor-/Rackkapazität im Runner wird aus dem validierten Profil abgeleitet;
der CF01-Vertrag verlangt weiterhin eine vollständige Zwölferbeladung.

`handoff_policy` verlangt eine positive Roboterquittung und bei Übergaben
zwischen Greifer und Rotor zusätzlich die zugehörige Stationsbestätigung und
Belegungsprüfung. Vor der Roboterquittung wird die ausstehende Übergabe erfasst.

Für alle nicht beobachtbaren Befehle zählt nur eine Antwort mit dem
booleschen Feld `success: true`, einschließlich Reservierung, Heartbeat, Freigabe
und den beiden Stationsquittungen `confirm_seated` / `confirm_removed`. Negative, fehlende oder ungültige Antworten
lassen die Stationsquittung offen, auch wenn die Stationsaktion im Mock bereits
ausgeführt wurde. Eine passende Belegung ersetzt diese positive Quittung nicht.

Beobachtbare Befehle benötigen eine gültige Job-ID und eine bekannte Phase.
Der Runner wartet bis `succeeded`, prüft bei jedem Poll dieselbe Job-ID, sendet
Heartbeats und begrenzt die Wartezeit durch `command_execution` im Profil.
Leere Antworten oder ein unkorreliertes `running` bestätigen keinen Abschluss.
Während eines noch laufenden Deckel-/Index-/Heberbefehls beginnt keine Übergabe.
Die Frist läuft auf der expliziten Testuhr; Zeitüberschreitungen blockierender
SDK-/Netzwerkaufrufe müssten ein späterer echter Treiber zusätzlich behandeln.

Der Spin muss weiterhin `running` → `braking` → `succeeded` mit bestätigtem
Stillstand und gehaltener Bremse durchlaufen. Sein Fristbudget enthält die
Profil-Laufzeit und synthetische Bremszeit zusätzlich zum Befehlszeitbudget.
Der Trace kennzeichnet den angenommenen Spinauftrag als `submitted`; erst
`spin_complete` meldet den geprüften Abschluss. Ein Stopp wird ebenfalls als angenommener Auftrag (`submitted`) dargestellt,
weil seine Quittung keinen Stillstand belegt. Andere Befehle werden nach
bestätigtem Abschluss als `completed` aufgezeichnet.

Erst nach vollständiger Bestätigung wird die Buchführung weitergeführt:

| Berichtsfeld | Bedeutung |
|---|---|
| `inventory` | Buchführung der letzten vollständig bestätigten Übergaben; bei einer Störung keine Zusicherung des physischen Orts. |
| `world_inventory` | Separate synthetische Ortsbeobachtung nach den positiven Roboterquittungen; keine reale Identitätssensorik. |
| `pending_handoff` | Probe, Quelle, Ziel, Roboterquittung und Stationsquittung. `null` bei abgeschlossener Übergabe; `station_confirmation: null`, wenn keine Stationsquittung erforderlich ist. |
| `inventory_consistent` | Stimmen Buchführung und synthetische Ortsbeobachtung überein? Auch bei Übereinstimmung kann noch eine Quittung fehlen. |
| `ownership` | `pending` während der laufenden Übergabe, `unresolved` bei deren Abbruch oder widersprüchlichen Inventaren nach Fehler; nach abgeschlossenem Abgleich `confirmed`. Dies beschreibt die Zuordnung im Mock, keine Hardwarefreigabe. |
| `failure` | Auslösende Operation, Probe, ursprünglicher Fehlertyp/-code und Stationsfehler vor dem Stoppversuch. Der Fehler wird nicht durch einen späteren Stoppfehler ersetzt. |
| `stop_attempted` | Der Runner hat einen Stopp über den ausgewählten Vertragsdecoder versucht. |
| `stop_via_contract` | Der Decoder hat den Stopp erfolgreich beantwortet. Bei normalen erfolgreichen Läufen und fehlgeschlagenem Stoppversand `false`; kein Nachweis realen Stillstands. |
| `stop_error` | Fehler beim Stoppversuch bzw. dessen Protokollierung, falls vorhanden. |
| `station_inventory_check` | `mock_internal`: Belegung, Sitz und Masse werden aus `Simulator.slots` gelesen. Diese Prüfung ist nicht im gemeinsamen ROS-/SiLA-Zustand verfügbar. |

Beispiel: Der Roboter quittiert das Absetzen und Freigeben von `Sample01`, aber
die Stationsbestätigung schlägt fehl. Die synthetische Beobachtung führt die
Probe im Rotor, die letzte bestätigte Buchführung noch beim Greifer. Der Bericht
zeigt die offene Übergabe mit `ownership: unresolved` und behauptet keinen
weiterhin sicher gehaltenen Gegenstand. Dasselbe gilt umgekehrt bei einer
unbestätigten Rotorentnahme. Der Lauf stoppt ohne weitere Übergabe; automatischer
Wiederanlauf oder Abgleich mit einem realen Gerät sind nicht implementiert.

Lokale Platz-ID und Geometrie-ID werden gemeinsam von `rack_slots.places`
erzeugt. Der Runner schlägt numerische Plätze in Tabellen nach und interpretiert
keine Textpräfixe. Rackplätze werden als Instanz und relativer Platz ausgegeben, beispielsweise
`rack_instance: Rack` und `place_id: Slot01`. Der vorhandene Geometriebezug
`rack_place_id: CF01.OutputRack.Slot01` bleibt zusätzlich unverändert erhalten.
Dies ist eine lokale CF01-Zuordnung; getrennte Gefäß-/Probenidentitäten und eine
Anbindung an NanoDrop bleiben eigenständige Aufgaben.

Die HTML-Chargenanzeige benennt ihre Inventarfelder als Buchführung und zeigt
offene Übergaben samt fehlenden Quittungen auf Deutsch und Englisch. Die
unabhängige 60-s-Bewegung stellt solche Fehlerzustände nicht räumlich nach.
Historische Downloads unter `docs/media/` bleiben unverändert und enthalten
diese aktuelle Fehlerdarstellung nicht. Neu erzeugte lokale Demos verwenden
die aktuelle Vorlage; ein bestandener CAD-Aufbau ersetzt keine Geräteprüfung.

English: `inventory` records fully acknowledged handoffs, while
`world_inventory` records synthetic robot observations. A missing robot or
required station acknowledgement leaves `pending_handoff` and
`ownership: unresolved`; neither view is asserted to be a verified physical
location. Stop attempts and accepted stop responses are reported separately.
Slot occupancy checks use mock internals, not a real ROS/SiLA driver contract.
Required station acknowledgements must explicitly contain boolean `success: true`;
negative, missing or malformed replies leave the handoff unresolved.

### Nachprüfung der Befehlsabschlüsse und LF-Migration

Die aktuelle Software wartet bei beobachtbaren Befehlen auf den bestätigten
Jobabschluss. Negative Tests decken `running` ohne Job-ID, leere Antworten,
falsche Job-IDs, nie abgeschlossene Jobs sowie Heartbeat-/Reservierungs-/
Freigabequittungen ab. Bei erfolgreichen Läufen bleiben laufende Übergaben
`pending`; der Trace enthält keine `unresolved`-Einträge. Die lokalen Platznamen
werden zentral erzeugt und ohne Textparsing nachgeschlagen. Die Testparameter
für Masse und Übergabezeit stehen getrennt vom Anfangsinventar.

Der erste allgemeine Arm-Neuaufbau nach der LF-Migration ist nicht bestanden:
SolidCraft importierte fünf Servogehäuse offen und lieferte dafür keine
Schwerpunkte. Die FreeCAD-Prüfung dieses Versuchs besteht, aber der
CAD-Quervergleich bricht ab. ROS-Ausgabe, MB01 und davon abhängige Neuaufbauten
wurden danach nicht ausgeführt. Der lokale Bericht liegt unter
`exports/generated/2fa84f950446/build-attempt-status.json`. Historische
Buildberichte und README-Medien werden deshalb nicht als aktuelle Nachweise
umgeschrieben. Die neuen HTML-/Mock-Prüfungen verwenden ausdrücklich die
vorherigen Anzeigemeshe mit dokumentierter LF-Quelläquivalenz; dies ersetzt
keinen neuen bestandenen nativen CAD-Aufbau.

Die anschließende Importkorrektur verwendet die geschlossenen Hersteller-
Einzelteile auch im Arm-Builder. Der frische native Armvergleich in Revision
`2fa84f950446-r3` besteht einschließlich Gelenk- und Protokollstichproben;
ROS-Dateien sind neu erzeugt. Details und Körperzuordnungen stehen in der
[Servo-Integration](servo-integration.md#geschlossene-gehäuse-im-solidcraft-neuaufbau).
Die obigen historischen Medien, HTML-Prüfungen und ihr Nachweisstand bleiben
unverändert; der neue Armaufbau ist kein neuer Nachweis der CF01-Ladebahn.

### Historischer Nachweis des Restplans bis `95471df`

Der isolierte Stand aus `dc5df84` plus den Änderungen dieses Restplans besteht
261 Tests, davon 20 mangels gespeicherter Buildartefakte übersprungen. Die
21 gezielten CF01-Umgebungs-/Chargentests bestehen vollständig. Sie prüfen
Fehlertext, ursprünglichen Fehlertyp/-code, Operation und Probe sowie beide
halb bestätigten Übergaberichtungen, verlorene Stationsantworten und
fehlgeschlagene bzw. unbestätigte Stoppantworten. Alle 13 Schema-Dokumentprüfungen
und die Galerieprüfung bestehen. Das erneut erzeugte Chargendiagramm ist
bytegleich; nur seine aktuelle Quellenbindung wurde erneuert.

Die Browserprüfung besteht auf Deutsch und Englisch einschließlich zweier
echter Fehlerberichte, Sprachwechsel, optionaler Panelfehler und Breiten von
320/600/960 px ohne Konsolenfehler. Die neuen Fehleransichten wurden zusätzlich
visuell geprüft. Die lokale Demo und ihre Berichte liegen in der Revision
`cf01-batch-handoffs-64cd218f4b8a-20261108T173343413919Z` unter `renders/` und
`exports/generated/`; `batch-handoff-validation.json` bindet den Prüfstand.
Die CAD-Geometriequellen sind unverändert. Für diese HTML-Prüfung wurden die
vorhandenen nativen Anzeigemeshe mit dokumentierter Prüfsumme wiederverwendet;
ein neuer nativer CAD-Aufbau und eine erneute mechanische Prüfung wurden nicht
ausgeführt. Die Bewegung bleibt vom Chargenfehler entkoppelt.

### Ergänzende unabhängige Prüfung am 8. November 2026

Die Nachprüfung von `95471df` zeigte eine fehlende Erfolgsprüfung für
Stationsquittungen: Nach einer bereits ausgeführten Aktion konnte eine Antwort
mit `success: false` dennoch zum erfolgreichen Chargenabschluss führen. Die
Korrektur verlangt das boolesche `success: true` vor der Übernahme der Quittung.
Der ergänzte Regressionstest prüft 32 Fälle: beide Decoder, beide
Übergaberichtungen, Antworten mit und ohne vorherige Stationsausführung sowie
fehlende, leere, negative und nicht boolesche Antworten. Der Fehler wurde vor
der Korrektur reproduziert; danach bleiben solche Übergaben ungeklärt und der
Chargenlauf meldet keinen Erfolg.

Der korrigierte Gesamtstand besteht 291 Offline-Tests einschließlich aller
22 gezielten CF01-Umgebungs-/Chargentests. Die 13 Schema-Dokumentprüfungen und
die Galerieprüfung bestehen ebenfalls. Die Browserprüfung auf Deutsch und
Englisch verwendet vier Fehlerberichte für fehlende und negative Quittungen in
beiden Richtungen; Sprachwechsel, optionale Panelfehler und 320/600/960 px
werden ohne Konsolenfehler geprüft. Die Fehleransichten wurden visuell geprüft.
Der lokale Nachweis steht in
`exports/generated/cf01-review-95471df-20261108T190137002745Z/independent-review.json`;
die zugehörige HTML-Demo liegt im gleichnamigen Ordner unter `renders/`.
Die vorhandenen Geometriemeshe wurden nach Quellen- und Prüfsummenabgleich
wiederverwendet. Diese Nachprüfung erzeugt keinen neuen nativen CAD-, Bahn-,
Hardware- oder Netzwerknachweis; die oben dokumentierten Grenzen bleiben bestehen.

Während erfolgreicher Läufe enthält der Trace keine `unresolved`-Einträge.
Offene Quittungen einer gerade bearbeiteten Übergabe sind `pending`; eine
fehlgeschlagene Bestätigung macht daraus `unresolved`. Die Anzeige unterscheidet
„Übergabe läuft“ / „Handoff pending“ von der ungeklärten Zuordnung nach einem Fehler.

## Synthetic workspace and complete local batch

`model/synthetic-cf01-workspace.shared.json` composes an explicitly unbounded
space, reference-bank catalogue, furnishing instance and equipment layout.
There is no room shell. The standalone rack source is
`model/guided-tube-rack.shared.json`. The former bank dimensions, device world
poses and all 241 trajectory samples remain unchanged.

Run `python3 scripts/run_cf01_rack_batch.py` (optionally `--transport sila2`) for
the twelve-sample local fixture. The profile declares an initially empty rotor,
a delivered rack and fictitious masses. All robot handoffs are abstract synthetic
confirmations. A separate world inventory checks actual indexed slots and sample
identities against the runner ledger and simulated station presence/mass. This
is no physical sample identification. Polling uses the local MockProtocol API;
commands and failure-stop requests pass through the selected contract decoder.
The explicit test clock advances while awaiting observable command completion, including spin/braking. Failures retain confirmed ledger,
synthetic observations and pending acknowledgements separately and produce a
failed report; they do not claim restored sample order.

The 60-second motion component (rotor slot 01 → rack slot 01) has its own timeline
and mock confirmations. The batch runner does not execute that component or
any loading/return path. The README HTML presents the two independently.

The earlier macOS STEP-snapshot build failed strict SolidCraft closure validation
for Rotor and Arm_A1/A3/A4/A5/A6_housing. That historical report remains failed;
the README media provenance continues to record that build honestly.
No network, hardware, live FreeCAD macro or transporter execution is established.

## Independent SolidCraft build and importer workaround

```sh
python3 scripts/export_centrifuge_robot_pickup_solidcraft.py
```

This entry needs Python, SolidCraft CLI and the versioned shared sources/vendor
library. It does not read an FCStd, FreeCAD-generated scene STEP, display mesh,
or any previous CAD build report. It creates its own revision under
`cad/generated/centrifuge-cf01-solidcraft-*` and `exports/generated/`.
`cad/centrifuge-cf01/solidcraft-pickup-build-report.json` locates the result.

The rotor and other own geometry are constructed natively. For X2/X4 housings,
the current importer loses faces from the registered, fused STEP derivatives.
`solidcraft_vendor.py` instead imports the unchanged archived manufacturer STEP,
selects its exterior with the same CAD-independent partition used by the vendor
preparer, and retains the original closed case pieces. Internal parts are
omitted as before. The selected pieces make a native SolidCraft STEP round trip
with closure, volume, center and bounds checks. No hole patching or mesh
replacement is accepted. The original files and registered library remain intact.

The earlier reviewed scene has 235 CAD bodies for the same 223 semantic source
bodies: each X4 housing uses four original pieces and each X2 housing three.
New builds also isolate the seven X6 housing pieces, including both locating
sleeves, giving 241 native bodies. The shared source geometry is unchanged. A manifest
maps these parts to their original housing ID and arm link. Their original seam
overlaps remain; summed case-piece volume differs slightly from the old fused
representation. No claim about real mass or mechanical fits follows.

Both review poses check every body's identity, closure, volume and world center
against the unposed native construction and the shared transforms. Closure is
mandatory; relative volume integration error must stay below 0.01% and center
error below 0.001 mm (1 µm). These numerical integration tolerances are not
hardware accuracy claims. To add a
comparison with an independently generated FreeCAD metrics report:

```sh
python3 scripts/export_centrifuge_robot_pickup_solidcraft.py --compare-freecad /path/to/snapshot-metrics.json
```

The optional comparison uses the existing 0.1% volume and 0.02 mm center limits.
Only the complete multi-backend builder passes `--context`; standalone generation
does not require that context or FreeCAD. These checks do not validate a native
SolidCraft motion study or the full loading path. The standalone arm and MB01
builders now reuse the same vendor adapter; other legacy STEP-snapshot adapters
remain separate.
