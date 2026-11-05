# Integrierte Servos und Motorplatten im gemeinsamen Modell

Stand: 28. Oktober 2026. Die sechs ausgewählten Servomodule sind jetzt in der
gemeinsamen Armquelle und in beiden CAD-Ableitungen enthalten. RViz erhält
sechs einfache Gehäusequader. Dies ist eine geometrische Konzeptintegration,
keine Fertigungs- oder Präzisionsfreigabe.

## Quelle und Ableitungen

`model/robot.json` enthält die semantischen Operationen `vendor_component` und
`mount_plate`. Die Komponentenbibliothek
[`component-library.json`](../cad/vendor/myactuator/component-library.json)
ist dort mit SHA-256 gebunden. Ein verändertes Bibliotheks- oder STEP-Asset
führt zu einem Fehler, bis die Referenz bewusst aktualisiert wird.

Pro Servo werden vier zusammengehörende Elemente beschrieben: stationäres
Herstellergehäuse und eigene Gehäuseplatte am Elternlink, rotierender
Herstellerausgang und eigene Ausgangsplatte am Kindlink. Ein gemeinsamer
Installationsrahmen beschreibt die Ausgangsstirnfläche mit +Z nach außen.
Die Generatoren verwenden dieselben Rahmen und Bolt-Circle-Daten.

| Gelenke | Integriertes Modul | Gehäuse → Ausgang |
|---|---|---|
| J1 | RMD-X4-P36-36-E-L | L0 → L1 |
| J2 | RMD-X6-P20-60-E | L1 → L2 |
| J3 | RMD-X4-P36-36-E-L | L2 → L3 |
| J4 | RMD-X2-P28-7-E | L3 → L4 |
| J5 | RMD-X2-P28-7-E | L4 → L5 |
| J6 | RMD-X2-P28-7-E | L5 → L6 |

Die sichtbaren Motorplatten sind goldfarben; Gehäuse dunkelgrau und Ausgänge
hellgrau. Die UMR-Kennzeichnung bleibt auf dem Oberarm erhalten.

Die aktuellen Roboterschemata verwenden diese Teile tatsächlich: J1/J3 jeweils
X4-P36-36-E-L, J2 X6-P20-60-E und J4/J5/J6 jeweils X2-P28-7-E. Pro Arm sind
zwölf eigene Motorplatten, zehn Rund- und zehn Diamantstifte sowie 70 spezifizierte
Schrauben zugeordnet. Die [aktuelle Baugruppenzuordnung](../exports/x2-x4-fits-fasteners/design-validation.json)
führt unter `assembly_integration` die Platte, den starren Link, die Pins und
Schrauben je Gelenk. Die Prüfung liest die Vendor-ID und STEP-Prüfsumme aus der
gespeicherten FCStd-Datei, kontrolliert die SolidCraft-Endkörper und die
zugehörigen RViz-Strukturmeshes beziehungsweise Servoquader. Die Schrauben sind
als Montagehardware mit Kopfhüllen und Senkungen spezifiziert; vollständige
Schrauben-/Gewindekörper werden im jetzigen Detailgrad ausgelassen.
Die mobile Basis in allen drei gespeicherten Zuständen und die drei Arm-
Instanzen der Laboraufstellung referenzieren denselben geprüften Armstand.
Der Integrationsnachweis besteht einschließlich der drei neuen Prüfungen für
fehlende CAD-/RViz-Teile und falsche Vendor-IDs mit 147
[Offline-Tests](../exports/x2-x4-fits-fasteners/parts-integration-tests.log).

FreeCAD verwendet native Platten-Grundkörper und Bohrungsfeatures sowie
importierte Vendor-Volumenkörper. SolidCraft erzeugt dieselben Platten und
importiert dieselben STEP-Komponenten. Die FreeCAD-Platzierungen folgen den
nativen Längenausdrücken; für gemeinsame Maßänderungen in SolidCraft den
Generator erneut ausführen. Die Importmatrizen dort sind numerisch ausgewertet.

## Aufbereitung der Herstellergeometrie

`scripts/prepare_servo_components.py` liest die erhaltenen Originalableitungen
und registriert deren unterschiedliche Achslagen. Die Auswahl der äußeren
Gehäuseteile erfolgt über geometrische Merkmale, nicht über feste Flächenindizes.
Geschlossene X4-Außenschalen werden in Volumenkörper überführt. Die äußeren
Gehäuseteile werden vereinigt; der Ausgangsflansch bleibt getrennt.
Interne Leiterplatten, Getriebe und kleine Verbindungsmittel sind ausgelassen.
Die unveränderten Originalpakete und vollständigen Referenzdateien bleiben erhalten.

Die sechs vorbereiteten Teilgeometrien liegen je Baugröße unter
`derived/registered-v1/housing.step` beziehungsweise `output.step`.
Sie enthalten jeweils einen gültigen Volumenkörper. Die Bibliothek führt
Quelle, Prüfsumme, Registrierungsmatrix, Außenmaße und Schnittstellenstatus.
Eine erneute Aufbereitung wird mit FreeCADs Kern-Python ausgeführt:

```powershell
& "$env:LOCALAPPDATA/Programs/FreeCAD 27.1/bin/python.exe" scripts/prepare_servo_components.py
```

Ändert sich dabei die Bibliothek, die neue Prüfsumme bewusst in der Modellquelle
übernehmen. Die Armregeneration selbst benötigt keine erneute Aufbereitung:

```powershell
python scripts/build_models.py --ros2
python -m unittest discover -s tests -v
```

## Motorplatten und offene Schnittstellen

Die Platten sind 6 mm dick. Außenradien und zentrale Freiräume sind eigene
Entwurfsparameter. Die Bohrungszentren stammen aus den registrierten
CAD-Zylindern, abgeglichen mit den Zeichnungen. Kleine Abweichungen des
Hersteller-CAD von idealen Polarkoordinaten bleiben dokumentiert erhalten.
X2/X4 haben jetzt eigene Rund-/Entlastungsstifte und ausgewählte Schraubenstapel:
X4 M3×8 ISO 4762, X2 M3×6 am Gehäuse und M3×8 am Ausgang nach DIN 7984.
Die niedrigen X2-Köpfe sind nur eingeschränkt belastbar (08.8).
Maße, Retention, Gewindeüberdeckung und Bauänderungen stehen im
[X2-/X4-Auslegungsbericht](x2-x4-fits-fasteners.md).
Die X6-Auslegung ergänzt Kopfsenkungen, eine Zentrierbohrung Ø5 H7 und ein
radiales Langloch gleicher kontrollierter Breite. Die nominellen Schraubenstapel
sind M3×10 am Gehäuse (Gewindetiefenbestätigung erforderlich) und M4×6 am Ausgang.
Maße, Toleranzkette und Musterprüfung stehen im [Auslegungsbericht](x6-fits-fasteners.md).

Die zunächst gemeldete X6-Abweichung war eine falsche Zuordnung unserer
Maßpfeil-Interpretation. Geklärt sind zehn M3-Gehäuseschrauben auf Ø72,5 mm
und zwölf M4-Ausgangsschrauben auf Ø44 mm, zusätzlich zwei Ø5-mm-Zentrierhülsen
am Gehäuse. Die Platten haben jetzt entsprechend Ø3,4-mm- beziehungsweise
Ø4,5-mm-Freibohrungen, Kopfsenkungen und zwei gesonderte Hülsenstellen. Die Hülsen sind in
der vereinfachten Vendor-Geometrie enthalten. Der
[Auflösungsbericht](x6-interface-resolution.md) führt Quellen und Nachweise.

Vor Fertigung sind Passungen, gewählte Schrauben und zulässiger Eingriff am
Musterteil zu prüfen. Die X6-Hülsenpassung und Schraubenlängen sind nominell
ausgelegt, ihre Eignung unter Last bleibt ungeprüft. Weitere Pilotpassungen,
Retentionsfestigkeit der eigenen X2-/X4-Stifte, Kabelfreiraum, mechanische
Nullstellung und Geberkalibrierung bleiben offen. Alle Motorplatten führen
`manufacturing_released: false`. Auch die neuen Stützen und Kupplungen sind
Konzeptkörper; Überlappungen innerhalb eines starren Glieds sind keine geprüften
Montageverbindungen.

## Änderungen am Arm

- Die alten Motor-/Getriebe-Platzhalter und der entfernte Ellenbogen-Riemenantrieb
  sind entfernt. J3 verwendet in dieser Revision ein direktes Gelenkmodul.
- J1 erhält eine erhöhte Antriebsposition und vier Stützen; J4/J6 erhalten
  Freiraum und Stützen um die axialen Module. Bestehende Gabeln und Naben bleiben
  teilweise Konzeptgeometrie und benötigen eine spätere konstruktive Auslegung.
- Schulter- und Handgelenkdurchgänge sowie der J3-Plattenfreiraum sind vergrößert,
  um Kollisionen mit den rotierenden Teilen zu vermeiden.
- `flange_z` liegt jetzt bei `wrist_z + 90 mm` statt `+50 mm`. Die allgemeine
  Flanschstirnfläche liegt bei `flange_z + 26 mm`. Bei Standardmaßen sind das
  641 mm in der gemeinsamen Nullstellung. Damit liegt sie insgesamt 56 mm
  weiter distal als vorher. Der Flansch ist weiterhin kein kalibrierter
  Pipettenspitzen-TCP; die Pipettenaufnahme bleibt außerhalb des CAD-Umfangs.
- Die Serviceebene benennt jetzt die konkreten Module und Gehäusekörper,
  Herstellerübersetzungen und nominale 24-/48-V-Versorgungszweige. Tatsächliche
  Rückmeldedaten, Vorzeichen, Nullpunkte, Kabelwege und elektrische Auslegung
  werden dadurch nicht als geprüft ausgegeben.

## RViz und Prüfungen

Die Strukturmeshes enthalten keine Hersteller-Servooberflächen. Stattdessen
erzeugt URDF genau sechs benannte Servo-Quader, jeweils am Gehäuse-Elternlink.
Die Box umschließt das registrierte Gehäuse. Ausgänge bleiben als eigene
Kollisionskörper am Kindlink berücksichtigt; unsere Ausgangsplatten und
Kupplungen bleiben im Strukturmesh sichtbar. Alle ROS-Längen sind in m,
Gelenkwinkel in rad. Zusätzliche Stecker-/Kabelreserven sind noch auszulegen.

Der [aktuelle Build-Bericht](../exports/generated/build-report.json) führt die
Dateien und Nachweise des gültigen Stands. Die spätere X6-Passungsfassung
verglich einschließlich Kameras 72 Körper und 22 maximale Kopfhüllen.
Die aktuelle X2-/X4-Fassung vergleicht 92 Körper, prüft 70 maximale
Schraubenkopfhüllen und 20 eigene Stiftköpfe samt Presssitzen in der Standpose.
Der ursprüngliche erfolgreiche Integrationslauf
prüft 62 Endkörper, alle sechs SolidCraft-Gelenke sowie die Körpervolumina und
Schwerpunkte beider CAD-Kerne. Die größte Schwerpunktabweichung lag bei rund
0,00132 mm, die größte relative Volumenabweichung unter 0,017 %.

FreeCAD prüft die Standpose, sechs Einzelbewegungen um +5° und elf Stichproben
des Bewegungsprotokolls auf Überschneidungen zwischen verschiedenen starren
Gliedern. Für diese Posen wurden keine Überschneidungen oberhalb 0,0001 mm³
gefunden. Eine Variante mit 220 statt 200 mm Oberarmlänge prüft Kinematik und
die zwölf Vendor-Platzierungen. Der gesamte Bewegungsraum und Zwischenposen
sind weiterhin nicht kontinuierlich kollisionsgeprüft.

Die Offline-Prüfungen kontrollieren zusätzlich Teilprüfsummen, Gehäuse-/Ausgangs-
zuordnung, Plattenlochbilder und die einmalige RViz-Boxdarstellung. Der native
[SolidCraft-Modellrender](../renders/Laborarm_Servos.png) ist visuell geprüft.
Eine erneute FreeCAD-GUI-Prüfung sowie ein laufender ROS-/RViz-Test wurden für
diese Revision nicht durchgeführt. Hardware bleibt Mock; Tragfähigkeit,
Steifigkeit, Präzision, Zykluszeit und Haltesicherung sind nicht qualifiziert.
