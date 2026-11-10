# README-Demo

## Aktuelle Fassung: drei durchgehende Entnahmen bei offenem Deckel

`robot-demo-smooth-batch.html`, `robot-demo-smooth-batch.mp4` und
`robot-demo-smooth-batch.png` zeigen Sample01–03 nach einem vollständigen
synthetischen Zwölferlauf. Alle drei Gefäße gelangen in ihre ursprünglichen
Rackplätze; neun verbleiben im Rotor. Die automatische Detailansicht zeigt den
unveränderten 16-mm-Präsentationshub entlang der Gefäßachse. Zwischen Griff und
Rackankunft gibt es keinen Zwischenhalt. Der Deckel bleibt zwischen den
Entnahmen offen; nach der letzten Freigabe und dem Heberrückzug schließt und
verriegelt er.
Die Modellzeit beträgt 80,759 s bei 1.565 Armknoten, rund 29,7 % weniger als
bei der vorherigen lokalen Fassung mit Deckelzyklen je Probe. Der erste
Griff bis zur bestätigten Rackabstützung benötigt 11,611 s, rund 1,0 % weniger
als zuvor. Dies sind Modellzeiten, kein Hardware-Durchsatzbenchmark.
Das Video zeigt diese Modellzeit auf 45 s beschleunigt.

[Profil, Aufbau und Prüfgrenzen](../cf01-smooth-unloading.md) und die
[eigene Provenienz](robot-demo-smooth-batch.provenance.json) führen die
vorläufigen Geschwindigkeits-, Beschleunigungs- und Ruckgrenzen, Quellen,
Artefaktprüfsummen und ausgeführten Prüfungen. Browser, native Prüfung und
ROS-Armexport evaluieren dieselben quintischen PVA-Kurven. Position,
Geschwindigkeit und Beschleunigung sind stetig; Ruck kann an Segmentgrenzen
springen. Die Grenzwerte sind synthetisch, biologische Toleranzen unbekannt.

Die native diskrete Prüfung besteht mit 10.026 angeforderten Frames und
9.979 unterschiedlichen Zuständen, ohne Kollisions- oder Abstandsfehler.
Der Browser besteht 112 Python-/JS-Vergleiche einschließlich
Gelenkgeschwindigkeiten und aller drei Hübe, Deutsch/Englisch und drei
Fensterbreiten. Export und ROS-Client-Dry-run bestehen mit 1.565 PVA-Knoten
über 80,759156872 s; das bleibt eine Datenprüfung ohne ROS-Laufzeit und Hardware.

Die 145 gezielten Bewegungs-, Mathematik-, Opt-in- und ROS-Prüfungen bestehen.
Die Gesamtsuite ist dennoch nicht vollständig grün: Vorhandene Mehrarm- und
Instrumenten-Aufstellungsberichte enthalten veraltete Cacheverweise. Die
Galerieprüfung meldet fehlende Bilder für `model/lab-glassware.shared.json`
und die parallel hinzugekommene `model/lab-equipment.shared.json`. Diese
unabhängigen Befunde gehören nicht zum neuen CF01-Bewegungsnachweis.
Die zunächst an der Sandbox gescheiterten Loopback-Tests bestehen nach separater
Wiederholung außerhalb der Sandbox (33 Tests); Netzwerk-Skips bleiben Skips.

Nur unveränderte Geometrie wird aus quellgebundenen CAD-Berichten übernommen;
die neue Bahn erhält eine eigene native diskrete Kollisions-/Abstandsprüfung.
Sie berücksichtigt alle zwölf Gefäße und Kappen, das zunehmend belegte Rack,
NanoDrop und Qubit sowie den gesamten NanoDrop-Hebelbereich. Daraus folgen
keine kontinuierliche Kollisionsgarantie, biologische Verträglichkeit oder
Hardwarequalifikation. Eine neue native SolidCraft-Bewegungsstudie und eine
ROS-Laufzeitausführung wurden nicht durchgeführt. Die historischen
SolidCraft-Importgrenzen unten bleiben erhalten.

Die offene Indexierung verwendet einen neuen, ausdrücklich aktivierten
Simulatorvertrag. Der Standardsimulator, ROS-/SiLA-Verträge und der bisherige
Chargenrunner erhalten diesen Befehl nicht. Ein Replay bestätigt die neue
Befehlsfolge nur im Opt-in-Simulator mit logischer Uhr; es ersetzt keine
Watchdog- oder Sicherheitsprüfung. Ein sensorabhängiger Abbruchzweig des
Armprogramms ist nicht implementiert.

Diese Bewegungszeitachse ist unabhängig vom vollständigen Chargenprotokoll;
sie startet weder eine Zentrifugation noch Netzwerk-/Hardwarebefehle. Das
historische Chargenpanel ist in dieser Bewegungsansicht ausgeblendet.
Der Armkanal ist mit Position, Geschwindigkeit und Beschleunigung für den
bestehenden ROS-Client exportierbar; Greifer-/Stationssteuerung, Sensorik und
Qualitätsrückmeldungen bleiben getrennte Integrationsaufgaben.

## Historische Fassung: Roboter und Deckel parallel

`robot-demo-overlap.html`, `robot-demo-overlap.mp4` und
`robot-demo-overlap.png` zeigen den überarbeiteten Bewegungsbaustein über
47,5 s, im Video auf 20 s beschleunigt. Der Arm fährt nach der synthetischen
Freigabe von Arm und Gefäß bei 29,5 s weiter. Parallel parkt der Heber;
der Deckel schließt von 30,5 bis 41 s und verriegelt bis 42 s. Das Vorschaubild
zeigt 35 s. Geometrie, bisherige Einzelbewegungsdauern und Gefäßübergaben
bleiben erhalten.

[Eigene Provenienz](robot-demo-overlap.provenance.json) bindet diese Medien an
die damalige Quelle und die ausgeführten Prüfungen. Die native adaptive
FreeCAD-Prüfung umfasst auch den getragenen Probenkörper und seine Kappe
gegen den bewegten Deckel nach der Freigabe. SolidCraft erzeugt seine
Prüfstellungen unabhängig aus den Quellen; das bleibt eine Prüfung statischer
Posen. Geometrische Stichproben und synthetische Bestätigungen ersetzen keine
Kollisionssensorik, Prozess-/Qualitätsrückmeldungen oder Hardwarequalifikation.

Das Armprogramm ist zusätzlich für den bestehenden ROS-Trajektorienclient
exportierbar, mit unveränderten Gelenkwinkeln und Zeiten. Export und Dry-run
im Client sind Datenprüfungen; ROS-Laufzeit, passende Live-Roboterbeschreibung
und die integrierte Greifer-/Stationssteuerung sind nicht nachgewiesen.

## Historische Fassung: ursprünglicher Einzeltransfer

Bewusst versionierte Medienauswahl, keine zusätzliche Konstruktionsquelle:

- `robot-demo.html`: unabhängige Bewegungsansicht und lokales Chargenprotokoll.
- `robot-demo.mp4`: beschleunigter 60-s-Bewegungsbaustein Rotorplatz 01 → Rackplatz 01.
- `robot-demo.png`: Vorschau bei 30,5 s mit Gefäß am Greifer.
- `provenance.json`: Quellen, Medienprüfsummen, Prüfungen und Grenzen dieses historischen Medien-Builds.

Die Szene stammt aus `model/synthetic-cf01-workspace.shared.json`: unbegrenzter
Raum, Referenzbank, referenzierter Roboter, CF01 und Rack. Bankmaße, Weltpositionen
und alle 241 Bewegungssamples bleiben gegenüber `05dba7428daa` erhalten.

Das Chargenpanel zeigt zwölf Proben vom bereitgestellten Rack durch den
vollständigen lokalen Schleuderablauf zurück in ihre ursprünglichen Rackplätze.
Alle Roboterübergaben sind abstrahiert; Testzeit vergeht nur für Spin und Bremse.
Der Bewegungsbaustein hat eine eigene Zeitachse und wird vom Chargenrunner nicht
aufgerufen. Transporter, Netzwerk und Hardware werden nicht ausgeführt.

## Prüfnachweise und Grenzen des ursprünglichen Medien-Builds

211 Offline-Tests und 13 Schema-Prüfungen bestehen. FreeCAD: sieben native
Snapshots mit 223 Körpern und adaptive Prüfung mit 1601 angeforderten Frames
bestehen. Körper-IDs und aggregierte Volumina stimmen mit dem bisherigen Stand
überein. Die Browserprüfung kontrolliert Bewegung, Protokollende, ursprüngliche
Rackreihenfolge und schmale Ansichten ohne Konsolenfehler.

SolidCraft importiert die 223 Körper, lässt jedoch Rotor und fünf Servogehäuse
offen. Seine strenge Gesamtprüfung schlägt fehl; die Referenzbank besteht die
Maß- und Volumenprüfung. Der Gesamt-Buildbericht meldet deshalb `passed: false`.
Die Medien belegen keine reale Funktion, Sicherheit oder mechanische Qualifikation.

Diese Provenienz bleibt der festgehaltene Stand dieses Medien-Builds. Der spätere
[native CF01-SolidCraft-Adapter](../centrifuge-cf01-robot-pickup.md#independent-solidcraft-build-and-importer-workaround)
erzeugt die Prüfstellungen unabhängig von FreeCAD. Sein eigener Bericht führt
die erneuten Prüfungen; er überschreibt diese historische Medienprüfung nicht.

## Historischer Quellstand

Alle 50 Quellprüfsummen in `provenance.json` gehören exakt zu Commit
`e5eedc828a2bb1ae4e903378ec9359644bd8a467`. Sie werden nicht auf heutige
Generatoren umgeschrieben. HTML, Video, Vorschaubild und diese Provenienz bleiben
als historischer Medien-Build erhalten. Die neu erzeugte, deutsch/englisch
umschaltbare Demo und ihre aktuellen Prüfungen sind separat im
[Nachtrag zur Claude-Prüfung](../cf01-claude-review.md) beschrieben.

## Aktualisieren

`python3 scripts/build_centrifuge_robot_pickup.py` erzeugt eine neue lokale
Revision. Installierte macOS-Programme werden erkannt; abweichende Programme
können mit `--freecad-python` und `--solidcraft-cli` angegeben werden. FreeCADs
Bibliothek muss für dessen Python über `PYTHONPATH` verfügbar sein. Die strenge
SolidCraft-Prüfung darf bei Importfehlern weiterhin fehlschlagen.

Nach Prüfung das erzeugte HTML aus `renders/` als neue Medienrevision
übernehmen. Historische Dateien nicht überschreiben. Mit Node, Playwright und
Chromium vom Repository-Stamm aus:

```sh
node scripts/export_readme_video.cjs \
  --input renders/<neue-revision>/cf01-unload-demo.html \
  --output-base docs/media/robot-demo-smooth-batch --record-seconds 45
```

Optional sind Playwright-Modul und Chrome-Programm als erstes und zweites
Argument oder mit `--playwright` und `--chrome` übergebbar. Dauer und
Besitzwechsel stammen aus den eingebetteten Quellen; ohne MP4-Unterstützung
bricht der Export ab. Danach Medien prüfen und eine eigene Provenienz
einschließlich aller Medienprüfsummen festhalten. GitHub zeigt HTML als Datei;
für interaktive Bedienung herunterladen und lokal öffnen.
