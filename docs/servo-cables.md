# Servoantriebe und flexible Leitungen

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

## Was modelliert ist

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

## Prüfen und ableiten

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

## Nächste Abstraktionsstufe

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

## Rückmeldung bis ROS 2

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
