# Geglättete synthetische CF01-Entnahme

Die [interaktive Ansicht](media/robot-demo-smooth-batch.html) und das
[Video](media/robot-demo-smooth-batch.mp4) zeigen drei aufeinanderfolgende
Entnahmen aus einem vollständig belegten Rotor nach dem synthetischen
Schleuderlauf. Sample01–03 gelangen in dieser Reihenfolge an ihre ursprünglichen
Plätze `Rack/Slot01`–`Rack/Slot03`; neun Gefäße bleiben im Rotor. Das ist ein
Entnahmeausschnitt mit eigener Modellzeit, kein ausgeführter vollständiger
Roboter-Chargenlauf. Transporter, Beladung und Zentrifugation werden hier nicht
animiert oder als Hardwarebefehle ausgeführt.

## Führende Quellen und Zeitachse

`model/cf01-unload-demo.motion.json` referenziert die vorhandene
Entnahmeszene, `model/cf01-rack-batch.protocol.json` und die additive Quelle
`model/cf01-open-lid-index.protocol.json`. Das Schema
`model/cf01-unload-demo.schema.json` beschreibt den unterstützten Vertrag.
Raum, Bank, Geräte, zwölf Gefäße und ursprüngliche Rackplätze werden aus ihren
bestehenden Quellen übernommen. `scripts/cf01_unload_motion.py` verwendet den
vorhandenen Chargenrunner ausschließlich als synthetischen Nachweis für
Probenidentitäten und Rückgabereihenfolge. Dessen bisherige Befehlsfolge
beweist die neue offene Indexierung nicht; die Testzeit wird nicht mit der
Animationszeit gleichgesetzt.

Der Compiler erzeugt `program.json`: separate Arm-, Stations- und Greiferkanäle,
Ereignisse, Gefäßeigentümer und Prüfberichte. Arm und Station können parallel
fortschreiten. Der erste Index erfolgt mit dem unveränderten Basisbefehl bei
geschlossenem, verriegeltem Deckel. Danach öffnet der Deckel einmal und bleibt
zwischen den drei Entnahmen bei 105° geöffnet und gehalten. Nach jeder aus
der tatsächlichen Bahn abgeleiteten Freiraumbestätigung darf der Heber parken,
während der Arm ohne Halt zum Rack weiterfährt. Die nächste offene Indexierung
wartet auf die vorherige Rackabstützung und Fingerfreigabe, den geparkten Heber,
bestätigten Stillstand und freien Stationsbereich. Erst nach der letzten
Freigabe und dem letzten Heberrückzug schließt und verriegelt der Deckel.
Die bestehende Indexgrenze von 2 U/min bleibt erhalten. Der Deckel behält seine
nominale Grenze von 10 °/s; sie wird nicht für einen kürzeren Clip erhöht.

Die Präsentation hebt das jeweilige Gefäß unverändert um 16 mm entlang seiner
geneigten Achse an. Das entspricht 13,106 mm vertikalem Hub, nicht 16 mm in Z.
Eine mindestens 0,6 s lange Präsentationspause macht diesen Hub sichtbar.
Greifen, Freiraumfreigabe und Rackabstützung besitzen eigene synthetische
Bestätigungen. Gefäß und Kappe folgen genau einem Besitzer: Rotor, Greifer
oder ursprünglicher Rackplatz. Bereits abgelegte Gefäße bleiben dort stehen.

Das neue Programm dauert **80,759 s** und enthält **1.565 Armknoten**.
Gegenüber der vorherigen lokalen Fassung mit Zwischenhalten und Deckelzyklen
je Probe sind das 29,7 % weniger als deren 114,823 s. Der faire Vergleich
vom ersten Griff bis zur bestätigten Rackabstützung beträgt dagegen
11,611 s statt 11,731 s, also rund 1,0 % weniger. Die anschließende
Stützbestätigung dauert unverändert 0,25 s; sie gehört nicht zur bewegten Bahn.

| Probe | Griff → Rackankunft | Griff → bestätigte Rackabstützung |
|---|---:|---:|
| Sample01 | 11,361 s | 11,611 s |
| Sample02 | 11,327 s | 11,577 s |
| Sample03 | 11,408 s | 11,658 s |

Alle drei beladenen Fahrten werden durch die konservative translatorische
Gefäßruckschranke begrenzt: etwa 4.999,85 mm/s³ bei einer unveränderten Grenze
von 5.000 mm/s³. Das ist eine obere Intervallgrenze, kein gemessener
Hardware-Spitzenwert. Die Vergleiche betreffen Modellzeiten, keinen Hardware-
oder Durchsatzbenchmark. Alle Grenzwerte bleiben unverändert: unter anderem
1 rad/s für leere und 0,5 rad/s für beladene Armfahrt.

## Ausdrückliche Opt-in-Erweiterung

`scripts/cf01_open_lid_index.py` erweitert den vorhandenen Simulator um genau
`index_open_lid(slot)`. Die neue Protokollquelle pinnt die unveränderte Station
und ihren Basisvertrag. Nur die ausdrücklich gewählte Unterklasse
`OpenLidIndexSimulator` kennt den Befehl. Sie verwendet die vorhandenen
Prädikate für frische Rückmeldung, Stillstand mit gehaltener Parkbremse,
freien Arbeitsbereich, geparkten Heber und sitzende vorhandene Gefäße. Dazu
kommen Offen-Endschalter, gesunde gehaltene Deckelbremse und Fehlerfreiheit.
Die Indexgrenze wird aus `handling.index_limit_rpm` der Station referenziert.

Der Standardsimulator und die bestehenden Befehle bleiben unverändert.
Insbesondere verlangen `index` und Schleuderstart weiter den geschlossenen,
verriegelten Deckel. Die Erweiterung registriert keinen ROS-/SiLA-Befehl und
ändert weder `MockProtocol` noch den bisherigen Chargenrunner oder den
gemeinsamen CF01-/NanoDrop-/Qubit-Workflow. Der neue Befehl wird dort nicht
automatisch ausgeführt. Ein eigener Replay gegen die Opt-in-Unterklasse
prüft die neue Stationsfolge vom synthetischen Zustand „voller Rotor nach
Spin“ aus; seine logische Uhr ist kein Watchdog- oder Hardware-Timingnachweis.
Die [CF01-Protokolldokumentation](centrifuge-cf01-protocol.md) trennt Erweiterung
und Basisvertrag.

## Glatte Bahn und vorläufige Grenzwerte

Die ganze beladene Fahrt ist eine Referenzbahn vom bestätigten Griff bis zur
Rackankunft. Auf die axiale Gerade folgen krümmungsstetige Verrundungen mit
den vorhandenen `withdrawn`- und `upright`-Bezugspunkten als Kontrollen;
die letzte Gerade führt senkrecht in den Rackplatz. Diese Kontrollen sind
keine Zwischenhalte. Die Gefäßneigung bleibt auf dem axialen Anteil bei 35°,
geht monoton auf 0° über und bleibt während der vertikalen Ablage aufrecht.
Ein begrenztes Zeitgesetz mit Geschwindigkeitsplateau, ein durchgehender
IK-Durchlauf, ein Kurvenfit und eine gemeinsame Zeitskalierung verbinden die
gesamte beladene Strecke. Ruhe ist nur an Griff und Rackankunft vorgesehen;
die anschließende Stützbestätigung ist eine getrennte Haltezeit.

Die lokalen Ableitungen liefern die Position-/Geschwindigkeit-/
Beschleunigungsknoten (PVA) der tatsächlich ausgewerteten stückweisen
Quintiken. Die Kurve ist **C2**: Position,
Geschwindigkeit und Beschleunigung sind stetig. Der Ruck hat endliche,
begrenzte einseitige Werte, kann an Knoten jedoch springen. Eine C3-Kurve oder
global zeitoptimale Bahn wird nicht behauptet.

Axiale Entnahme und vertikale Rackablage behalten ihre geometrischen
Richtungen, erhalten aber keine ruhenden Grenzen zum Transit.
`removed_confirmed_s` und `clear_s` sind Schwellzeiten der tatsächlichen
FK-Kurve; der Arm hält dafür nicht an. Die Kriterien betreffen axiale
Entnahme und das Erreichen der quellgebundenen Freigabegrenze. Sie sind
synthetische Bestätigungen, keine gemessenen Sensorwerte.
Die leere Rückfahrt führt von der Rackannäherung direkt zum Rückzugspunkt.
Stations- und Greiferachsen verwenden begrenzte S-Kurven. Eine allgemeine
automatische Wegsuche oder Glättung beliebiger Kollisionskorridore ist nicht
implementiert.

Der folgende Stand ist eine lesbare Übersicht; maßgeblich bleibt das Profil:

| Größe | Geschwindigkeit | Beschleunigung | Ruck |
|---|---:|---:|---:|
| Armgelenk, beladen | 0,5 rad/s | 2 rad/s² | 20 rad/s³ |
| Armgelenk, leer | 1 rad/s | 2 rad/s² | 20 rad/s³ |
| Gefäßpunkte, Translation | 200 mm/s | 500 mm/s² | 5.000 mm/s³ |
| Gefäßorientierung | 30 °/s | 90 °/s² | 900 °/s³ |
| Stationsdeckel | 10 °/s | 180 °/s² | 1.800 °/s³ |
| Rotor beim Indexieren | 2 U/min | 30 °/s² | 300 °/s³ |
| Lineare Stations-/Greiferachsen | 50 mm/s | 200 mm/s² | 2.000 mm/s³ |

`qualified: false` und `biological_tolerance: null` sind ausdrücklich Teil des
Vertrags. Die Werte sind vorläufige synthetische Einstellungen. Sie belegen
weder geringe biologische Schädigung noch mechanische Tragfähigkeit oder
Regelgüte. Flüssigkeitsbewegung, Verschlusskräfte, Greifkraft, Resonanzen und
Schwingungen der gemeinsamen Bank werden nicht modelliert.

Die gemeinsame Mathematik in
`ros2_ws/src/solidcraftbot_ros/solidcraftbot_ros/motion.py` prüft die
Gelenkpolynome einschließlich innerer Extrema. `scripts/sample_motion.py`
überträgt Ableitungen über die Kinematik und begrenzt Punkt- und Winkelbewegung
mit konservativen numerischen Intervallen. Acht umschließende Gefäß-/Kappenecken
und drei axiale Bezugspunkte berücksichtigen den vollständigen Körper statt
nur des TCP. Die adaptive FK-Prüfung beginnt mit vier Teilintervallen je
Quintikintervall und verfeinert jeweils den Abschnitt mit der größten
konservativen Zeitskalierungsanforderung, höchstens bis 256 Teilintervalle.
Sie endet, wenn dieser obere Skalierungsfaktor höchstens das 1,1-Fache des
aus tatsächlichen Auswertungen gewonnenen unteren Faktors beträgt oder der
aktuell begrenzende Abschnitt die Auflösungsgrenze erreicht. Die zurückgegebene
Schranke bleibt die Vereinigung aller Intervallhüllen; Abtastwerte steuern nur
die Verfeinerung und ersetzen keine obere Grenze. Das Profil führt Start-
und Höchstauflösung ausdrücklich. Die Bahntoleranz wird zusätzlich an vier
inneren Stellen jedes Quintikintervalls geprüft. Diese numerischen Grenzen
sind kein formales Gleitkommazertifikat. Zeitdehnung reduziert Geschwindigkeit,
Beschleunigung und Ruck entsprechend mit 1/T, 1/T² und 1/T³.

Beim Einlesen eines gespeicherten Programms berechnet
`scripts/cf01_unload_validation.py` die Grenzen aus seinen tatsächlichen
PVA-Kurven erneut. Kopierte Segmentberichte gelten nicht als Dynamiknachweis;
auch beladene Intervalle, Stationsachsen, Greifer und Gefäßhüllen werden geprüft.
Das Kein-Halt-Kriterium betrachtet die tatsächliche Gefäßgeschwindigkeit und
die Norm der Gelenkgeschwindigkeiten: Unterhalb der Profil-Schwellen sind nur
ein zusammenhängender Anfangs- und ein Endbereich der beladenen Fahrt erlaubt.
Ein eingefügter Ruhepunkt oder ein inneres ruhendes Intervall wird abgewiesen.
Axial-/Vertikalanteile und Ereignisprädikate werden aus der FK nachgerechnet;
Stationsbewegungen benötigen die vorgesehenen Ruhe- und Freiraumbedingungen.
Das Ergebnis wird getrennt vom nativen Geometriebericht gespeichert.


## Native Geometrie und Prüfgrenzen

`scripts/cf01_unload_geometry.py` übernimmt ausschließlich unveränderte
Konstruktionsgeometrie aus geprüften, quell- und artefaktgebundenen Berichten.
Der historische CF01-Bericht, sein unveränderter Stations-Unterbericht und
die nativen Dateien werden per SHA-256 geprüft. Der Stations-Unterbericht
liefert auch die Bindung des Mechanikhelfers, die im älteren übergeordneten
Bericht fehlte. Er verändert dessen historische Prüfsummen nicht. Alte
Weltposen werden zuerst mit ihrer damaligen Zeitachse normalisiert; danach
werden alle zwölf vorhandenen Gefäß-/Kappenpaare durch das neue Programm
transformiert. Die Instrumentgeometrie stammt aus dem geprüften gemeinsamen
NanoDrop-/Qubit-Szenenbericht. Ein frischer Checkout muss diese geprüften
lokalen Basis- und Instrument-Builds zunächst erzeugen.

Ein neuer Lauf von `scripts/check_cf01_unload_motion.py` prüft die neue Bahn
und schreibt `native-motion-validation.json`. Alte Kollisionsberichte werden
nicht als neuer Bewegungsnachweis übernommen. Er berücksichtigt:

- alle zwölf Gefäße und Kappen gegen Rotor, Rahmen, Deckel, Rack, Nachbarn und
  Roboter; belegte Rackplätze bleiben Hindernisse;
- native Körperüberschneidungen und mindestens 5 mm Abstand des Roboters zur
  Ausrüstung, mit gezielten Ausnahmen für die vorgesehenen Greifkontakte;
- in jedem Stationsbewegungsfenster Abstand für Arm, Werkzeug und getragenes
  Gefäß zu den jeweils bewegten Gruppen: Rotor einschließlich rotoreigener
  Gefäße, Heber und zuletzt Deckel; jedes Fenster erhält eigene Prüfzähler;
- den durchgehend bei 105° offenen Deckel als Hindernis, auch wenn er gerade
  nicht bewegt wird;
- beide Messgeräte in ihren quellgebundenen Posen sowie konservative Hüllen
  des gesamten NanoDrop-Hebelbereichs; die Qubit-Haube bleibt in ihrer
  eingefrorenen Quellpose.

Nur die beiden Pads gegenüber dem aktiven Gefäß erhalten die vorgesehene
Greifkontakt-Ausnahme. Rackabstützung wird auf eine tatsächliche dünne
Kontaktzone an der Basisoberkante begrenzt. Alle Kanalknoten und Ereignisse
einschließlich Eigentümerwechseln werden geprüft; adaptive Zwischenstellungen
begrenzen den diskreten Schritt der Körperhüllen auf 2 mm und von Arm-, Rotor-
und Deckelwinkeln auf 1°. Konservative AABB-Abstände oberhalb der geforderten
Marge genügen als Trennungsnachweis; darunter verfeinert die native BRep-Distanz.
Das ist keine kontinuierliche Kollisionsfreiheit oder Sensor-/Schutzfunktion.

Der aktuelle native Bericht im Format
`solidcraftbot.cf01-unload-native-motion-validation/2` besteht mit 10.026
angeforderten Frames und 9.979 unterschiedlichen Zuständen, ohne
Kollisions- oder Abstandsfehler. Die Dynamikprüfung bestätigt das Kein-Halt-
Kriterium für alle drei tatsächlich getragenen Kurven. Die Browserprüfung
besteht 112 Python-/JS-Vergleiche einschließlich Gelenkgeschwindigkeit,
Entnahme-/Freigabezeitpunkten und je drei inneren Zeiten pro beladener Fahrt;
alle drei Hübe sowie Deutsch/Englisch und drei Fensterbreiten sind geprüft.

Der Gesamtprüflauf ist nicht vollständig grün: Die separate
`AnalyticalNativeEvidenceTests`-Prüfung eines vorhandenen Mehrarm-CAD-Berichts
weist einen veralteten Cache nach. `render_model_gallery.py --check` meldet
fehlende Bilder für `model/lab-glassware.shared.json` und die parallel
hinzugekommene `model/lab-equipment.shared.json`. Diese unabhängigen Arbeiten
werden nicht durch den bestandenen CF01-Bewegungsbericht freigegeben.

Der neue Build erzeugt zwei abgeleitete native FreeCAD-Prüfstellungen:
`CF01_Unload_PresentedSample2.FCStd` und `CF01_Unload_Final.FCStd`. Eine neue
native SolidCraft-Bewegungsstudie wird nicht erzeugt. Die unabhängige
SolidCraft-Konstruktionsquelle und die bisherigen statischen Prüfstellungen
bleiben bestehen. Insbesondere bleiben die dokumentierten Fehler und Grenzen
des historischen STEP-Gesamtimports erhalten; siehe
[Medienhistorie](media/README.md) und
[unabhängiger SolidCraft-Aufbau](centrifuge-cf01-robot-pickup.md#independent-solidcraft-build-and-importer-workaround).

## Reproduzieren und getrennt auswerten

Mit vorhandenen geprüften lokalen Geometrie-Builds und FreeCAD:

```bash
python3 scripts/build_cf01_unload_demo.py
```

Der Einstieg findet FreeCAD über die gemeinsame Werkzeugauflösung oder
`--freecad-python`. Er erstellt eine neue Revision unter `exports/generated/`,
`cad/generated/` und `renders/`; `tmp/cf01-unload-context.json` verweist auf den
letzten Lauf. `--prepare-only` erzeugt Programm und Browseransicht ohne einen
bestandenen nativen Bewegungsnachweis. `--program` übernimmt ein bereits
kompiliertes Programm nur mit weiterhin passenden Quellen. Berichte,
Modellartefakte und Provenienz müssen dieselbe Revision und Prüfsummen binden.
`--finish-existing <context.json>` erlaubt eine neue Browserfassung nur bei
unverändertem Programm, nativen Prüfern, Geometrienachweisen, Nachbargeräten
und Prüfstellungsdateien. Diese Bindungen werden vor und nach dem Rendern
kontrolliert; die Dynamikprüfung wird aus den Kurven neu abgeleitet. Der alte
native Bericht bleibt dabei bytegenau erhalten.


Die Browseransicht `renders/<revision>/cf01-unload-demo.html` wertet dieselben
PVA-Polynome aus; zusätzliche Vorschau-Samples dienen nur der Bildauswahl.
Die kuratierte [Medienprovenienz](media/robot-demo-smooth-batch.provenance.json)
bindet die README-Medien an die tatsächlich ausgeführten Prüfungen. Ein
beschleunigter Videoclip ändert die Modellzeit oder Grenzwerte nicht.
Das aktuelle Video verdichtet die 80,759 s Modellzeit auf 45 s.

Der separate ROS-Export übernimmt ausschließlich den Armkanal. In den folgenden
Befehlen `<revision>` durch den tatsächlichen Buildordner ersetzen:

```bash
python3 scripts/export_cf01_unload_ros2.py \
  --program exports/generated/<revision>/program.json \
  --output exports/generated/<revision>/ros2-scenarios.json
PYTHONPATH=ros2_ws/src/solidcraftbot_ros python3 -m solidcraftbot_ros.demo \
  --config exports/generated/<revision>/ros2-scenarios.json \
  --scenario cf01_unload_three_samples --dry-run
```

Die vollständigen PVA-Knoten entsprechen der [quintischen Spline-Interpolation
des ROS Joint Trajectory Controllers](https://control.ros.org/jazzy/doc/ros2_controllers/joint_trajectory_controller/doc/trajectory.html).
Der Export prüft die Nanosekundenquantisierung und die daraus entstehenden
Polynome: Innere PVA-Werte werden an den gerundeten Zeiten neu ausgewertet;
Ruheendpunkte bleiben erhalten. Das Kein-Halt-Kriterium wird auch auf den
ROS-quantisierten Punkten geprüft.
Der Quellkanal und der geprüfte ROS-Export enthalten jeweils 1.565 Armknoten;
der vorhandene Client führt den Daten-Dry-run über 80,759156872 s erfolgreich
aus. Die Zahl der Exportpunkte ist mit dem Armkanal identisch.
`compiled_program_sha256` bindet sortiert und kompakt serialisierte JSON-Daten
(`json.dumps(..., sort_keys=True, separators=(',', ':'), allow_nan=False)`);
der Byte-SHA der formatierten Programmdatei ist separat dokumentiert.
Der Client verlangt vollständige PVA-Knoten und passende Grenzen.
Ein tatsächlicher Trajektoriencontroller muss Splines verwenden; seine
Live-Konfiguration und die passende Roboterbeschreibung sind nicht geprüft.
Export, Nachrichtenerzeugung und Dry-run sind Datenprüfungen. ROS-Laufzeit,
Hardware und eine integrierte CF01-/Greifer-/Sensorsteuerung sind damit nicht
nachgewiesen. Insbesondere gibt der Arm-Export allein keinen gesamten
Laborablauf frei.

Das zeitgebundene Armprogramm besitzt noch keinen von Stations- oder
Sensorzuständen abhängigen Abbruch- und Rückführzweig. Ein erfolgreicher
Replay, Dry-run oder eine diskrete Kollisionsprüfung ergänzt diesen Zweig
nicht. Globale Zeitoptimalität, biologische Verträglichkeit und reale
Hardware-Sicherheit werden nicht zugesichert.


## Übergreifende Prüfgrenzen dieses Builds

Die 145 gezielten Bewegungs-, Mathematik-, Opt-in- und ROS-Tests bestehen.
Der Gesamtlauf umfasst 729 Tests, ist aber wegen veralteter lokaler Mehrarm-/
Instrumenten-Aufstellungsberichte und fehlender Glasware-/Ausrüstungsbilder
nicht vollständig grün. Die ursprünglichen Loopback-Bindefehler der Sandbox
wurden durch eine separate erfolgreiche Wiederholung der 33 betroffenen
Netzwerktests geklärt. Die Provenienz hält ursprünglichen Gesamtlauf, Wiederholung
und verbleibende Befunde getrennt fest; übersprungene Netzwerk- und
Laufzeitprüfungen werden nicht als bestanden gezählt.
