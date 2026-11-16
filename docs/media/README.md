# README-Demo

## Aktuelle Fassung: ausgerichtete Greifer- und Übersichtskamera

[Video](robot-demo-cameras-aligned.mp4) und
[interaktive Demo](robot-demo-cameras-aligned.html) zeigen den vollständigen Arm
mit beiden synchronen Kamerabildern. Die Nahkamera ist seitlich zurückgesetzt
und blickt auf den tatsächlichen Griffpunkt, 55 mm vor der Flanschreferenz.
Beide Finger und das gegriffene Gefäß sind sichtbar. Die hintere Kamera sitzt
auf einem auskragenden Mast, blickt aufrecht auf die Arbeitszone und besitzt
etwa 120° horizontalen Bildwinkel. Sie soll später auch Annäherungen und
Gefahrensituationen beobachten können. Bei der CF01-Entnahme liegt das Rack
außerhalb ihres Bildes; bei der Rackankunft ist es sichtbar. Verdeckungen und tote Winkel bleiben;
Gefahrendetektion oder eine Schutzreaktion sind nicht implementiert.

Körper, Halter, optische Rahmen und Sichtkegel stammen gemeinsam aus
`model/robot.json`. Der 16:9-Bildausschnitt bleibt beim Verkleinern des Fensters
gleich. Physische Oberflächen verdecken einander auch dann, wenn die
Gesamtansicht sie transparent zeichnet. Die Optik ist eine illustrative
Lochkamera ohne kalibrierte Intrinsik, Verzeichnung oder reale Bilddaten.

Die Bewegung und sämtliche übrigen Körper der historischen CF01-Szene bleiben
bytegebunden erhalten. `camera_revision.py` erlaubt ausschließlich Änderungen
an Kameraoperationen und nur dort verwendeten Parametern. Der native Build
ersetzt sämtliche Kamerakörper einschließlich Halter und prüft die komplette
Bewegung mit allen zwölf Gefäßen, Nachbargeräten und beweglichen Gruppen neu.
Auch benachbarte Armglieder und der Greifer werden gegen die Kameras geprüft.
Der bisherige 5-mm-Abstand zu Geräten wird beibehalten. Das sind adaptive,
diskrete BRep-Prüfungen, kein kontinuierlicher Kollisions- oder Sicherheitsbeweis.

Die Browserprüfung vergleicht 25 Kameraposen und Gefäßeigentümer mit der Python-FK.
Sie prüft den Griffpunkt auf der optischen Achse und zählt tatsächlich sichtbare
Pixel beider Finger und des Gefäßes in neun Griff-/Transport-/Ablageposen.
Die Übersicht muss dabei die Arbeitsfläche und am jeweiligen Endpunkt
Zentrifuge beziehungsweise Rack zeigen; fehlende Sicht auf das andere Gerät
wird als Einschränkung protokolliert.
Die Videoausgabe verwendet für beide Ansichten exakt dieselbe Modellzeit wie
für die Gesamtansicht. 99,674 s Modellzeit werden mit 20 Bildern/s in 99,700 s
wiedergegeben; der Faktor liegt gerundet bei 1×. Ein menschlicher Zeitvergleich
bleibt offen. Die [Provenienz](robot-demo-cameras-aligned.provenance.json) bindet
Geometrie, native Prüfung, Browserprüfung, Videoframes und fertige Medien.
Der [Einbettungsnachweis](robot-demo-cameras-aligned.embed.json) bestätigt Upload
und authentifizierten Abruf. Der anonyme Abruf lieferte weiterhin 404; der
öffentliche README-Player bleibt ungeprüft. Die lokalen MP4-/HTML-Dateien sind
oben zusätzlich verlinkt.

Reproduktion benötigt die in der historischen Provenienz gepinnten lokalen
CAD-/Build-Artefakte; ein frischer Checkout enthält diese nicht. Der Build
verwendet aktuelle Kameras mit der historischen Umgebung und ist kein Neubau
aller inzwischen geänderten Geräte- und Möbelquellen.

Die direkte Roboteransicht der Modellgalerie ist erneuert; ihre breiten,
nicht physischen Sichtkegel sind für eine lesbare Übersicht ausgeblendet.
Andere Aufstellungen behalten ihre ausdrücklichen Pins auf den vorherigen
Robotquellstand. Der globale Galerie-Check meldet deshalb weiterhin
`Image dependency changed: model/robot.json`. Die Migration dieser Szenen
einschließlich neuer Geometrie-/Bewegungsprüfungen ist ein separater Folgeschritt;
der vollständige Galerie-Check wird hier nicht als bestanden ausgewiesen.

```sh
mkdir -p tmp/camera-alignment
python3 - <<'PYTHON'
import subprocess, sys
sys.path.insert(0, 'scripts')
from tool_paths import default_freecad_python
from build_instrument_concepts import freecad_environment
python = default_freecad_python()
subprocess.run([python, 'scripts/build_cf01_camera_scene.py'],
               env=freecad_environment(python), check=True)
PYTHON
python3 scripts/build_cf01_camera_demo.py
node scripts/export_readme_video.cjs --input docs/media/robot-demo-cameras-aligned.html \
  --output-base docs/media/robot-demo-cameras-aligned --record-seconds 99.7 --fps 20 \
  --screenshot-time 20.65 > tmp/camera-alignment/capture.json
node tests/check_cf01_camera_views.cjs
python3 scripts/build_cf01_camera_demo.py \
  --capture-report tmp/camera-alignment/capture.json \
  --browser-report tmp/camera-demo/browser-validation.json
```

`SOLIDCRAFTBOT_FREECAD_PYTHON` überschreibt den erkannten FreeCAD-Interpreter.
Playwright und Chrome über `SOLIDCRAFTBOT_PLAYWRIGHT` und
`SOLIDCRAFTBOT_CHROME` angeben. Unter macOS verwendet `--angle metal` für den
Export beziehungsweise `SOLIDCRAFTBOT_ANGLE=metal` für die Browserprüfung die
Hardwarebeschleunigung. Ohne Playwright wird der Browserteil ausdrücklich
übersprungen. `python3 scripts/build_models.py --ros2` erzeugt zusätzlich den
Standardarm in beiden CADs und seine ROS-Daten aus derselben Quelle.

## Historischer Kamera-Prototyp: ursprüngliche Blickrichtungen

[Video](robot-demo-cameras.mp4) und [interaktive Demo](robot-demo-cameras.html)
zeigen dieselben drei CF01-Entnahmen wie die Bewegungsquelle unten. Der gesamte
Arm bleibt in der voreingestellten Gesamtansicht sichtbar. `C_scene` am
drehbaren Sockel und `C_tip` am Werkzeugflansch sind farblich markiert; ihre
Perspektiven werden gleichzeitig eingeblendet. Auf schmalen Bildschirmen stehen
die beiden Kamerafenster untereinander.

Die optischen Rahmen stammen aus `model/robot.json`, ausgewertet mit den
280-/250-mm-Armlängen dieser Szene. Beide Bilder verwenden die aktuelle
Gelenkstellung, Station und Gefäßzuordnung derselben Zeitachse. Eine illustrative
16:9-Lochkamera wird in den jeweiligen Sichtkegel eingeschrieben. Das Bildfeld
bleibt beim Verkleinern des Fensters gleich. Die Kegellänge beschreibt keine
gemessene Sensorreichweite; die Darstellung begrenzt Tiefen auf 0,5–5.000 mm.

Die Kamerabilder berücksichtigen Verdeckungen mit einem Tiefenpuffer. Auch die
in der Gesamtansicht transparent gezeigten Gerätehüllen sind dort undurchsichtig.
Das macht vorhandene Einschränkungen sichtbar: Die Sockelkamera blickt teilweise
auf den eigenen Arm, und die enge Greiferkamera ist noch nicht auf den Greifpunkt
dieses Werkzeugs abgestimmt. Kamerahalter und Optik bleiben vorläufig. Reale
Bilddaten, Kalibrierung, Linsenverzeichnung, Schärfe, Beleuchtung und Objekterkennung
sind nicht simuliert oder qualifiziert.

Das Video läuft mit 20 Bildern/s über 99,700 s; die Modellzeit von 99,674 s
wird bis auf die Bildrasterung in Echtzeit wiedergegeben. Der Wiedergabefaktor
ist eingeblendet. Ein Vergleich mit menschlicher Durchführung ist weiterhin
offen. Geometrie und kompiliertes Bewegungsprogramm sind gegenüber
`robot-demo-continuous-cfr.html` unverändert. Dessen native Prüfnachweise und
Grenzen bleiben maßgeblich; diese Erweiterung ist eine Darstellungsprüfung.
Die [neue Provenienz](robot-demo-cameras.provenance.json) bindet die Quellen,
Kamerarahmen, Medien und ausgeführten Prüfungen. Historische Medien bleiben erhalten.
Der [Einbettungsnachweis](robot-demo-cameras.embed.json) enthält die GitHub-URL:
Upload und authentifizierter Abruf sind bestätigt. Der anonyme Abruf lieferte
bei der Prüfung für neues und bisheriges Video 404; die Wiedergabe im
veröffentlichten README ist damit noch nicht bestätigt. Der MP4-Dateilink bleibt
zusätzlich erhalten.

## Bewegungsquelle: drei durchgehende Entnahmen bei offenem Deckel

`robot-demo-continuous-cfr.html`, `robot-demo-continuous-cfr.mp4` und
`robot-demo-continuous-cfr.png` zeigen Sample01–03 nach einem vollständigen
synthetischen Zwölferlauf. Alle drei Gefäße gelangen in ihre ursprünglichen
Rackplätze; neun verbleiben im Rotor. Die automatische Detailansicht zeigt den
unveränderten 16-mm-Präsentationshub entlang der Gefäßachse. Zwischen Griff und
Rackankunft gibt es keinen Zwischenhalt. Der Deckel bleibt zwischen den
Entnahmen offen; nach der letzten Freigabe und dem Heberrückzug schließt und
verriegelt er.
Die Modellzeit beträgt 99,674 s bei 3.876 Armknoten, rund 13,2 % weniger als
bei der vorherigen lokalen Fassung mit Deckelzyklen je Probe. Der erste
Griff bis zur bestätigten Rackabstützung benötigt 11,611 s statt 11,731 s in
der älteren Fassung mit Zwischenhalten. Dies sind Modellzeiten, kein Hardware-Durchsatzbenchmark.
Das Video zeigt diese Modellzeit auf 45 s beschleunigt. Gegenüber der ersten
durchgehenden Fassung mit 80,759 s sind die nun ebenfalls verrundeten leeren
Fahrten langsamer; die beladene Fahrt ist unverändert. Globale Zeitoptimalität
ist nicht nachgewiesen.

[Profil, Aufbau und Prüfgrenzen](../cf01-smooth-unloading.md) und die
[eigene Provenienz](robot-demo-continuous-cfr.provenance.json) führen die
vorläufigen Geschwindigkeits-, Beschleunigungs- und Ruckgrenzen, Quellen,
Artefaktprüfsummen und ausgeführten Prüfungen. Browser, native Prüfung und
ROS-Armexport evaluieren dieselben quintischen PVA-Kurven. Leere An- und
Rückfahrten verrunden die Richtungswechsel bei `pregrasp` beziehungsweise
`rack_approach`; gerader axialer Anflug und vertikales Abheben bleiben erhalten. Position,
Geschwindigkeit und Beschleunigung sind stetig; Ruck kann an Segmentgrenzen
springen. Die Grenzwerte sind synthetisch, biologische Toleranzen unbekannt.

Die native diskrete Prüfung besteht mit 12.082 angeforderten Frames und
12.044 unterschiedlichen Zuständen, ohne Kollisions- oder Abstandsfehler.
Der Browser besteht 112 Python-/JS-Vergleiche einschließlich
Gelenkgeschwindigkeiten und aller drei Hübe, Deutsch/Englisch und drei
Fensterbreiten. Export und ROS-Client-Dry-run bestehen mit 3.876 PVA-Knoten
über 99,673878165 s; das bleibt eine Datenprüfung ohne ROS-Laufzeit und Hardware.

Die zuvor veralteten Instrumenten- und Mehrarm-Aufstellungsnachweise wurden
durch neue native Builds erneuert; die historischen Berichte bleiben erhalten.
Die Galerie enthält jetzt auch Laborglas, Analysenwaage und Kaltlagerung.
Ausgeführte Prüfungen und verbleibende Skips stehen mit ihrem jeweiligen
Quellstand in der neuen Medienprovenienz. Übersprungene Netzwerkprüfungen sind
kein bestandener Netzwerknachweis.

Der Videoexport zeichnet die Bildfolge aus festen Modellzeiten auf, unabhängig
von der Renderdauer. 900 Bilder liegen im MP4 mit genau 50 ms Abstand; der
letzte Modellzustand wird im letzten Bild erreicht. Sobald Präsentationshub
und vorherige Armrückfahrt beendet sind, beginnt die nächste Anfahrt ohne
zusätzliche Vorführpause. Greiferbewegung,
Griff- und Ablagebestätigung besitzen weiterhin ihre eigenen Bedingungen.

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

## Historische Fassung: erste durchgehende Drei-Proben-Entnahme

`robot-demo-smooth-batch.html`, `.mp4`, `.png` und die
[zugehörige Provenienz](robot-demo-smooth-batch.provenance.json) bleiben
unverändert erhalten. Dieser Build hatte bereits eine durchgehende beladene
Bahn und den zwischen den Entnahmen offenen Deckel. Vor jeder Anfahrt enthielt
er noch 0,6 s reine Vorführpause; die damalige Videoaufnahme besaß variable
Bildabstände. Die dort protokollierten veralteten CAD-Verweise und fehlenden
Galeriebilder beschreiben den damaligen Teststand, nicht die erneuerten Builds.

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
  --output-base docs/media/<neue-medienrevision> --record-seconds 45 --fps 20
```

Optional sind Playwright-Modul und Chrome-Programm als erstes und zweites
Argument oder mit `--playwright` und `--chrome` übergebbar. ffmpeg mit
libx264 ist erforderlich (`--ffmpeg` oder `SOLIDCRAFTBOT_FFMPEG`). Dauer und
Besitzwechsel stammen aus den eingebetteten Quellen. Der Export verwendet
verlustfreie Canvas-Einzelbilder als Encoder-Eingabe, feste Bildzeiten und
H.264/YUV420p im MP4; er protokolliert die Quellzeiten und Bildprüfsummen unter
`tmp/readme-video/`. Ein Encoder- oder Browserfehler ersetzt keine bestehende
Videodatei. Danach Medien prüfen und eine eigene Provenienz
einschließlich aller Medienprüfsummen festhalten. GitHub zeigt HTML als Datei;
für interaktive Bedienung herunterladen und lokal öffnen.
