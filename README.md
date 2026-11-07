# SolidCraftBot

Ein sechsachsiger Laborroboter für ein universitäres Labor, entwickelt aus einer
CAD-unabhängigen, maschinenlesbaren Konstruktionsbeschreibung. FreeCAD, SolidCraft
und ROS 2/RViz sind daraus abgeleitete Darstellungen.

**Stand: CAD-Konzept A01, keine Fertigungsfreigabe.** Der erste Prototyp soll mit
3D-Druckern und der Universitätswerkstatt entstehen; Budgetziel: 3.000–5.000 EUR.
Tragfähigkeit, Steifigkeit, Präzision, Dosierleistung und Sicherheit sind noch
nicht nachgewiesen. Die austauschbare Pipettenaufnahme ist zunächst außerhalb
des CAD-Umfangs; die Armquelle endet an einem allgemeinen Flansch.

## Roboter in Bewegung

[![Roboter entnimmt ein Gefäß aus der Zentrifuge und legt es im Rack ab](docs/media/robot-demo.png)](docs/media/robot-demo.mp4)

[Kurzes Video ansehen](docs/media/robot-demo.mp4) ·
[Interaktive Demo herunterladen](docs/media/robot-demo.html) ·
[Modellstand und Herkunft](docs/media/README.md)

Die Demo zeigt den vollständigen Ablauf mit sechs bewegten Armachsen,
Konzeptgreifer und Gefäßübergabe von CF01 in ein Rack. Die HTML-Datei lokal im
Browser öffnen: **Play cycle**, Zeitschieber und drei Ansichten funktionieren
ohne CAD-Installation oder Netzwerk. GitHub führt die HTML-Datei nicht direkt aus.
Das Video zeigt den 60-s-Modellzyklus beschleunigt. Dies ist eine geometrische
Animation mit synthetischer Rückmeldung; Hardware und Flüssigkeitstransfer sind
nicht implementiert oder durch das Video nachgewiesen.

## Quellen und lokale Ausgaben

Versioniert werden Konstruktionsabsicht, Generatoren, Dokumentation, Tests und
Laufzeitcode. Eigene FreeCAD-/SolidCraft-Dateien, STEP-/Mesh-Exporte,
Build-Berichte und Arbeitsrenderings werden lokal erzeugt und ignoriert.
Die kleine, bewusst ausgewählte README-Demo unter `docs/media/` ist die Ausnahme.

| Inhalt | Maßgeblicher Ort |
|---|---|
| Arm, Parameter, Gelenke, Protokolle und Schnittstellen | `model/` |
| Gemeinsame Ableitung und CAD-/ROS-Adapter | `scripts/` |
| Unveränderte Herstellerdaten und registrierte, prüfsummengebundene Bibliothek | `cad/vendor/` |
| ROS-Laufzeitcode, Launch-Dateien und Paketvorlagen | `ros2_ws/src/solidcraftbot_ros/` |
| Kleine, festgehaltene Geometriereferenzen für Regressionen | `tests/fixtures/` |
| Lokale Modelle | `cad/generated/` und Baugruppenordner unter `cad/` |
| Lokale Prüfberichte und Exporte | `exports/` und Baugruppenordner unter `cad/` |
| Lokale Renderings | `renders/` |
| Generierte ROS-Beschreibungen, Konfiguration und Netze | `ros2_ws/src/solidcraftbot_ros/{urdf,config,meshes}/` |

Die Herstellerbibliothek bleibt vorerst vollständig als Build-Eingabe erhalten:
`model/robot.json` und die Adapter referenzieren ihre registrierten Teilgeometrien
über SHA-256. Sie ist keine zweite führende Quelle für unsere Armkonstruktion.
Native CAD-Änderungen müssen in gemeinsame Quelle oder Generator zurückgeführt
und anschließend neu abgeleitet werden.

## Erzeugen und prüfen

```sh
python3 -m unittest discover -s tests -v
python3 scripts/build_models.py --ros2 --freecad-python /pfad/zum/FreeCAD-Python --solidcraft-cli /pfad/zu/solidcraft-cli
```

Python, FreeCAD mit importierbarem `FreeCAD`/`Part` und SolidCraft CLI müssen lokal
vorhanden sein. Der gemeinsame Arm-Einstieg akzeptiert die Laufzeitpfade explizit;
sein Standardpfad für FreeCAD stammt noch aus der Windows-Umgebung. Die komplette
CAD-Kette wurde nach dem Mac-Checkout noch nicht neu ausgeführt. Weitere
Stations-/Animationsgeneratoren enthalten ebenfalls noch Windows-Pfade.

Auf einem frischen Checkout laufen die Quell- und Kinematiktests ohne CAD.
Tests gespeicherter CAD-/ROS-Ausgaben melden **skipped**, bis die betreffenden
lokalen Builds existieren. Ein bestandener Quelltest ersetzt keine native
Geometrieprüfung. Nach dem Build enthält `exports/generated/build-report.json`
die aktuellen Armdateien, Prüfergebnisse und Grenzen; die Stationsgeneratoren
schreiben ihre jeweiligen `cad/<baugruppe>/shared-build-report.json`.
Dateipfade in älteren Fachdokumenten bezeichnen lokale Build-Ausgaben und sind
keine herunterladbaren GitHub-Artefakte mehr.

## Baugruppen und Entwicklung

- [Architektur: Arbeitsumgebung, Möbeltypen, Möblierung und Geräteausstattung](ARCHITECTURE.md)

- [Gemeinsames Modell und Entwicklungsschleife](docs/shared-model.md)
- [Anforderungen](docs/requirements.md), [Entwurf](docs/design.md), [Entwicklungsplan](docs/development-plan.md)
- [FreeCAD](docs/freecad.md), [ROS 2/RViz und Prüfgrenzen](docs/ros2.md)
- [Servo-Integration](docs/servo-integration.md), [Herstellerdaten](cad/vendor/myactuator/README.md)
- [Mobile Armbasis MB01](docs/mobile-base-mb01.md), [Probentransport TR01](docs/sample-transport-tr01.md)
- [Deckelstation C01](docs/tube-station-c01.md), [Spitzenabwurf T01](docs/tip-collector-t01.md)
- [Zentrifuge CF01](docs/centrifuge-cf01.md), [Roboterentnahme](docs/centrifuge-cf01-robot-pickup.md)
- [Gefäßträger H01](docs/tube-carrier-h01.md), [Rahmen H02](docs/tube-frame-h02.md), [Drehantrieb H03](docs/tube-cam-h03.md)
- [Laborraum](docs/lab-room-l01.md), [Aufstellung](docs/lab-layout-l01.md), [Transfersequenz](docs/lab-transfer-l01.md)

## Repository beziehen

```sh
git clone git@github.com:smoe/DIYLabBot.git
cd DIYLabBot
```

Die Git-Historie wurde am 6. November 2026 bereinigt: Der ursprüngliche einzelne
Import-Commit wurde durch den Quellstand ohne erzeugte Projektmodelle ersetzt.
Primärdateien, Hersteller-Build-Eingaben und die ausgewählten README-Medien
bleiben erhalten. Ein normaler vollständiger Klon benötigt deshalb keinen
Download der früheren CAD-/Exporthistorie mehr.

Vorhandene Klone besitzen noch die alte Historie. Am einfachsten neu klonen;
eigene Änderungen vorher sichern und gezielt übernehmen. Alte Branches nicht
zurück in `main` zusammenführen, da sie die entfernten Binärdateien wieder in
die erreichbare Historie bringen würden. Lokale Build-Ausgaben bleiben lokal.
