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

### Geschlossene Gehäuse im SolidCraft-Neuaufbau

Der SolidCraft-STEP-Importer verliert beim Import der vereinigten X2-/X4-
Gehäuse Flächen. Betroffen sind `A1_housing`, `A3_housing`, `A4_housing`,
`A5_housing` und `A6_housing`. Das vereinigte X6-Gehäuse ist zwar geschlossen,
überschreitet beim Schwerpunktvergleich aber die bestehende 0,01-mm-Grenze.
Arm und mobile Basis verwenden deshalb denselben Adapter
`scripts/solidcraft_vendor.py` wie die unabhängigen CF01-Prüfstellungen.
Er wählt anhand der gemeinsamen Außenkörperzuordnung die geschlossenen
Einzelteile aus den archivierten Herstelleroriginalen aus. Wiederholte
Teile wie die beiden X6-Zentrierhülsen werden über getrennte native STEP-
Exporte in unveränderter Weltlage isoliert. Der Adapter prüft einen STEP-Export
mit Wiederimport. FreeCAD und die registrierte Bibliothek
werden dafür nicht verändert.

Die ursprünglichen Gehäuse-IDs bleiben semantisch erhalten. SolidCraft führt
ihre Einzelteile mit Suffixen `_Part01` usw. am selben starren Glied.
Der lokale `solidcraft-vendor/vendor-build-report.json` bindet Originale,
Registrierung, Auswahl und abgeleitete STEP-Dateien mit Prüfsummen;
`solidcraft_body_aliases` im Baugruppenbericht ordnet die Körper zu.
Fehlende, doppelte, zusätzliche oder offene Körper und fehlende beziehungsweise
nicht endliche Schwerpunkte werden abgewiesen.

Für den Vergleich mit FreeCAD werden die Teilvolumina summiert und deren
Schwerpunkte volumengewichtet. Ursprüngliche Nahtüberlappungen sind darin
enthalten; die Summe ist kein boolesches Vereinigungsvolumen und keine reale
Masse. Die bisherigen Vergleichsgrenzen bleiben bestehen: unter 0,1 %
Volumenabweichung und unter 0,01 mm Schwerpunktabweichung; MB01 prüft zusätzlich
unter 0,02 mm Außenmaßabweichung. Gelenke, Komponentenrahmen und Importmatrizen
bleiben erhalten. Neue Ausgaben entstehen in neuen lokalen Revisionen;
historische Medien und ihre Provenienz werden nicht aktualisiert.

Der native Arm-Neuaufbau vom 8. November 2026, Revision `2fa84f950446-r3`,
besteht mit 110 geschlossenen SolidCraft-Körpern für 92 semantische Körper.
Die maximale Schwerpunktabweichung gegenüber dem frisch erzeugten FreeCAD-
Modell beträgt rund 0,001113 mm, die maximale relative Volumenabweichung rund 0,01038 %.
Alle sechs SolidCraft-Achsen wurden um 5° bewegt und zurückgesetzt;
FreeCAD-Standpose und Protokollstichproben bestehen ebenfalls. ROS-Dateien
wurden erzeugt, eine ROS-/RViz-Laufzeit wurde nicht ausgeführt.
Der revisionsbezogene Bericht liegt unter
`exports/generated/2fa84f950446-r3/build-report.json`. Das neue Arbeitsrendering
`cad/generated/2fa84f950446-r3/arm-review.png` ist visuell geprüft und ersetzt
keine historischen Medien.

Der mit demselben Einstieg frisch erzeugte MB01-Stand
`mobile-base-mb01-a8cda21d42e9` besteht ebenfalls: drei Zustände, zwei native
Maßvarianten, zwölf aufgelöste Baugruppengelenke und 14 FreeCAD-Kollisionsstichproben
ohne erkannte Überschneidungen. Die 149 geschlossenen SolidCraft-Körper sind
131 semantischen Körpern zugeordnet; die drei neuen Zustandsbilder wurden
visuell geprüft. Vorherige Kollisionsberichte wurden nicht wiederverwendet.

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
[Auflösungsbericht](x6-fits-fasteners.md#merged-x6-interface-resolution) führt Quellen und Nachweise.

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

<a id="merged-servo-cables"></a>

<a id="merged-servo-cables--servoantriebe-und-flexible-leitungen"></a>

## Servoantriebe und flexible Leitungen

Die gemeinsame Quelle [model/robot.json](../model/robot.json) enthält unter
`services` auch Inhalte, die in der Bewegungsansicht ausgeblendet bleiben.
Sechs Servoantriebe mit auslesbarer Positionsrückmeldung sind eine am
28.10.2026 bestätigte Eigentümeranforderung. Die vorhandenen Motorkörper
werden inzwischen durch die [integrierten Servos](servo-integration.md) ersetzt.
Die [Antriebsauswahl](actuator-selection.md) ist in der Serviceebene benannt;
physische Qualifikation, Geberzuordnung und Verkabelung stehen aus.
Konkrete Leitungen sind noch nicht gewählt. Der
[Hersteller-CAD-Plan](vendor-cad-plan.md) beschreibt die getrennte Befestigung
von Gehäuse und rotierendem Ausgang sowie die dafür nötigen Kabelrahmen.

<a id="merged-servo-cables--was-modelliert-ist"></a>

### Was modelliert ist

| Inhalt | Bedeutung |
|---|---|
| `actuators` | Zuordnung eines Servos zu Gelenk, Motorbauraum und tragendem Glied |
| `required_feedback` | Gemessene Position, Abtastzeitpunkt und Fehlerstatus müssen auslesbar sein |
| `feedback` | Messort, Positionsreferenz, Abtastperiode, zulässiges Datenalter und Latenz; offen |
| `transmission` | Übersetzung, Vorzeichen und Gelenknullpunkt; offen |
| `circuits` | Logische Versorgung, Befehle und Rückmeldung zwischen Steuerung und jedem Servo |
| `route_links` | Reihenfolge der starren Glieder bis zum jeweiligen Motor |
| `cable` | Artikel, Durchmesser, Länge, dynamischer Biegeradius, Torsionsgrenze und Längenmasse; offen |
| `routing` | Führungspunkte, Klemmen/Zugentlastung, Bewegungsreserve und Freiraum; offen |
| `joint_passages` | Führungskonzept, Neutralwinkel und erlaubte Winkel an beweglichen Durchführungen; offen |
| `electrical` | Spannung, Spitzenstrom, Protokoll, Stecker und Schirmung; offen |

`null` bedeutet unbekannt. Es bedeutet weder null Millimeter noch unbegrenzte
Beweglichkeit noch eine bestandene Prüfung. Die Struktur beschreibt Anforderungen
und einen Topologieentwurf, keine freigegebene Verdrahtung.
Sechs logische Verbindungen legen weder sechs Einzelkabel noch einen gemeinsamen
Bus fest. Leistungsversorgung und Datenbus können verschiedene Topologien haben.

Der Motor von J3 liegt auf dem Oberarm L2. Seine Versorgung kreuzt daher nur J1
und J2. Die Versorgung des J6-Motors reicht bis L5 und kreuzt J1 bis J5.
Über J6 selbst muss für diesen Motor keine Leitung geführt werden. Eine spätere
Werkzeugleitung über den Flansch ist eine eigene Erweiterung; die Werkzeugaufnahme
bleibt weiterhin außerhalb dieses Entwurfs.

Die beiden inzwischen ergänzten Armkameras besitzen getrennte logische
Anschlussanforderungen in den `camera`-Operationen von `model/robot.json`.
Der Kamerabericht und ROS `config/cameras.json` auditieren den Pfad zur
Übersichtskamera auf L1 über J1 und zur Nahkamera auf L6 über J1 bis J6.
Die sechs Servokreise und deren Durchführungsliste werden dadurch nicht
als vollständig verdrahtete Kameraanbindung ausgegeben. Kamera-Dateninterface,
Kabel, Zugentlastung, Bildalter und räumliche Führung sind offen.

<a id="merged-servo-cables--prüfen-und-ableiten"></a>

### Prüfen und ableiten

```powershell
python scripts/robot_services.py
python scripts/build_models.py --ros2
python -m unittest discover -s tests -v
```

Der erste Befehl erzeugt [services-report.json](../exports/generated/services-report.json).
Der gemeinsame Aufbau prüft die Serviceebene ebenfalls und schreibt den Bericht
in den neuen Modellordner. Das ROS-Paket erhält `config/services.json` als
zugeordneten Vertrag. Der Laufzeit-Treiber liest diese Anforderungen bisher nicht ein.
Das [Schema](../model/services.schema.json) beschreibt die zusätzlichen Felder.

Die Prüfung erkennt fehlende Servos, fehlende Versorgungs-/Rückmeldepfade,
Widersprüche zwischen Motorbauraum und Montageglied, übersprungene Glieder und
fehlende Gelenkdurchführungen. Wenn ein Winkelbereich für eine Durchführung
angegeben wird, muss er die im Robotermodell deklarierten Gelenkgrenzen abdecken.
Diese deklarative Prüfung ersetzt keine geometrische oder experimentelle Prüfung.

Für alle physischen Prüfungen meldet der Bericht derzeit ausdrücklich
`not_performed`: räumliche Führung und Reserve, Biegung, Torsion, Kollision und
Hängenbleiben, Spannungsabfall/Erwärmung sowie Rückmeldezeit und Kalibrierung.
SolidCraft, FreeCAD und URDF erhalten weiterhin die starren Körper; es werden
noch keine flexiblen Leitungen oder Kabelkräfte simuliert.

<a id="merged-servo-cables--nächste-abstraktionsstufe"></a>

### Nächste Abstraktionsstufe

Nach der Antriebsauswahl werden Führungspunkte und Klemmen relativ zu den
bewegten Gliedern festgelegt. Dieselben Bewegungsprotokolle sollen dann den
Längenbedarf, die Bewegungsreserve, Biegeradien, Verdrehung und den benötigten
Freiraum prüfen. Eine Kurve mit Hüllvolumen kann für diese Auslegung ausreichend
sein. Solche Kurven und Prüfungen sind noch zu implementieren. Eine einfache
Verbindungslinie oder ein Abstand zwischen Endpunkten wäre lediglich eine untere
Längenschranke; sie beweist keine führbare, kollisionsfreie Leitung.

Die Darstellung kann dafür später auf vereinfachte Kabelkurven umgeschaltet
werden. Eine flexible Dynamikrechnung kommt hinzu, wenn etwa Kabelkräfte am
Handgelenk die konkrete Untersuchungsfrage sind. Das Ausblenden darf die
Leitungsanforderungen und späteren Prüfungen nicht deaktivieren.

Biegeradius, Zugentlastung und ausreichende Schlaufe sind praktische Auslegungsgrößen:
die [igus-Montageanleitung](https://www.igus.com/contentData/wpck/pdf/us_en/Triflex%20Retraction%20System%20Assembly%20Guide.pdf)
behandelt entsprechende Fehlerfälle einschließlich Torsionsbeanspruchung und
Hängenbleiben. Grenzwerte sind für den gewählten Leitungstyp und Einbau zu bestimmen.

<a id="merged-servo-cables--rückmeldung-bis-ros-2"></a>

### Rückmeldung bis ROS 2

Eine interne Servoregelung allein erfüllt die Rückmeldeanforderung nicht.
Beim üblichen RC-Servoprotokoll ist die Istposition nicht auslesbar; darauf weist
die [Pololu-FAQ](https://www.pololu.com/product/1351/faqs) hin. Auslesbare Busservos
oder separate Positionssensoren können die Schnittstelle bereitstellen.
Noch ist kein Hersteller oder Kommunikationsprotokoll festgelegt.

Ein Motorencoder vor Getriebe oder Riemen misst deren Ausgangsspiel und
Verformung nicht direkt. Die Umrechnung in den ROS-Gelenkwinkel benötigt
Übersetzung, Richtung und Referenz; die Werkzeugposition bleibt eine weitere Messfrage.

Ein späterer Hardwareadapter soll gemessene Gelenkpositionen in rad an die
`position`-Zustandsschnittstellen liefern. Der
[ROS-2-Zustands-Broadcaster](https://control.ros.org/jazzy/doc/ros2_controllers/joint_state_broadcaster/doc/userdoc.html)
veröffentlicht diese über `joint_states`; zusätzliche Zustände haben eigene
Schnittstellen. Messzeitpunkt und Datenalter müssen bis zur Erfassung im Treiber
nachvollziehbar bleiben. Ein Publikationszeitstempel allein belegt keine frische
Sensormessung. Anforderungen an Aktualisierungsrate, Latenz und Reaktion bei
veralteten Daten sind noch festzulegen und zu implementieren.

Der jetzige ROS-Adapter bleibt Mock-Hardware. Seine zurückgespiegelten
Sollwerte sind keine Messwerte eines realen Servos.
