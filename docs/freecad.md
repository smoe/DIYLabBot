# FreeCAD aus der gemeinsamen Modellquelle

Die aktuelle native FreeCAD-Ableitung wird aus `model/robot.json` erzeugt.
Der Dateipfad steht im [Prüfbericht](../exports/generated/build-report.json).
Die früheren direkt erstellten Modelle und ihre alten Einstiegsmakros wurden
am 28.10.2026 auf Eigentümerwunsch entfernt. Historische Prüfberichte beziehen
sich weiterhin auf den damals dokumentierten Stand.

## Öffnen

Die im Prüfbericht genannte FCStd-Datei direkt öffnen. UMR besteht aus drei
nativen Extrusionen auf dem Oberarm; ihre Farbe und Sichtbarkeit sind gespeichert.
Referenzachsen, Ursprungsebenen und Zwischenkörper sind ausgeblendet.

Für interaktive Bewegung das
[Bewegungsmakro](../cad/generated/Laborarm_Neutral_Bewegung.FCMacro) öffnen und
**Makro → Makro ausführen** wählen. Das Makro öffnet automatisch die aktuelle
Ableitung und ergänzt sechs Winkelregler, Demonstrationen und **Run protocol**.
Die Achswinkel liegen auch direkt unter **Achswinkel (Grad)** im Modellbaum.

## Erzeugen und prüfen

```powershell
python scripts/build_models.py --ros2
python -m unittest discover -s tests -v
```

Der Generator erstellt native Grundkörper, boolesche Features, UMR-Extrusionen
und sechs über Ausdrücke gesteuerte Drehtransformationen. Für die integrierten
Servos werden registrierte Hersteller-STEPs getrennt für Gehäuse und Ausgang
importiert. Die eigenen Motorplatten bleiben native Grundkörper und Bohrungen.
Die Gliedlängen und Gelenkanker werden aus denselben Parametern abgeleitet.

Die Dateiprüfung kontrolliert 62 Körper, gültige Buchstabenkörper, die
Vorwärtskinematik, eine Längenänderung und 11 Kollisionsstichproben des
Bewegungsprotokolls. Zusätzlich werden Standpose und sechs Einzelbewegungen um
+5° auf Überschneidungen geprüft; die Längenvariante kontrolliert zwölf
Vendor-Platzierungen. Der gesamte Bewegungsraum und die Bewegung zwischen den
Stichproben sind nicht kontinuierlich geprüft.

## Gespeicherte Darstellung und Prozessabsturz

Die früheste generierte Kopie direkt in `cad/generated/` enthielt noch kein UMR.
Zusätzlich hatten die zunächst ohne Oberfläche erzeugten Dateien keine
`GuiDocument.xml` mit gespeicherten Ansichtseigenschaften. Der neue Aufbau
schreibt die native Darstellungsmetadaten direkt in den FCStd-Container:
Körperfarben, Sichtbarkeit und eine isometrische Kamera. Die XML- und Materialdaten
entsprechen den von FreeCAD 27.1 gespeicherten Eigenschaften. Geometriedateien
werden bytegleich übernommen; Änderungen an diesem nativen Format sind bei
anderen FreeCAD-Versionen gesondert zu prüfen.

Bei einer Diagnose am 28.10.2026 wurde eine native Speicherzugriffsverletzung
in einem separaten `python.exe`-Prozess angezeigt. Das normale FreeCAD-Fenster
lief weiter. Ein zum Zeitpunkt passender Windows-Fehlereintrag zur Bestimmung
des verursachenden Moduls war nicht verfügbar. Der versuchsweise verwendete
Qt-Offscreen-GUI-Prozess wurde aus dem Aufbau entfernt. Die neue Metadatenerzeugung
benötigt weder `FreeCADGui` noch Qt/OpenGL. Die tatsächliche Ansicht wird separat
im normalen FreeCAD-Fenster geprüft.

Getestete Kerninstallation: FreeCAD 27.1.0dev. Eine vollständige mechanische,
steuerungstechnische oder reale Servoprüfung ist damit nicht verbunden.

Die [frühere FreeCAD-Ansicht mit 41 Körpern](../renders/Laborarm_UMR_FreeCAD.png) wurde im normalen
FreeCAD-Prozess exportiert und visuell geprüft. Alle 41 Endkörper und die drei
dunkelblauen UMR-Buchstaben waren beim direkten Öffnen sichtbar, ohne zuvor
das Bewegungsmakro zur Reparatur der Darstellung auszuführen.

Die Servo-Revision ist als Datei und mit gespeicherten Darstellungsmetadaten
geprüft; ihre normale FreeCAD-GUI wurde noch nicht erneut visuell geprüft.
Der [SolidCraft-Render der Servo-Revision](../renders/Laborarm_Servos.png) zeigt
die neue Baugruppenbelegung. Details: [Servo-Integration](servo-integration.md).
