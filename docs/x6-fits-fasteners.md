# X6: Zentrierung und Schraubenstapel

Stand: 28. Oktober 2026. Nominelle Auslegung für einen ersten Gelenkversuch;
keine Fertigungsfreigabe. Führend ist
[`model/x6-mounting-interface.json`](../model/x6-mounting-interface.json).
Die Bibliotheksaufbereitung übernimmt Passungsdaten, Kopfsenkungen und
Schraubenannahmen. `mount_plate` erzeugt daraus dieselbe Geometrie für FreeCAD
und SolidCraft; RViz erhält die aktualisierten Strukturmeshes und weiterhin
sechs einfache Servoquader.

## Zentrierung am festen Gehäuse

Die beiden vorhandenen, hohlen Herstellerhülsen bleiben unverändert: außen
4,980–5,000 mm, 2 mm Überstand. Sie sind keine pauschalen h6-Passstifte.

| Merkmal der Gehäuseplatte | Vorgabe |
|---|---|
| Bezug A | Ebene Anlagefläche zum Servogehäuse, vorläufige Ebenheit 0,02 mm |
| Bezug B | Erste registrierte Hülse: runde Bohrung Ø5 H7, 5,000–5,012 mm |
| Bezug C | Gegenüberliegende Hülse: radiales Langloch, Breite 5,000–5,012 mm |
| Langlochlänge gesamt | CAD 5,20 mm; Fertigungsgrenzen 5,20–5,25 mm |
| Langlochrichtung | Verbindungslinie der beiden tatsächlichen CAD-Hülsenzentren |
| Einlauf | Höchstens C0,1 × 45°, Werkstattannahme; geometrisch ausgelassen |

Der primäre Mittelpunkt ist im kanonischen Servorahmen
(-33,491; 13,872) mm, der zweite (33,491; -13,872) mm. Die radiale Entlastung
verhindert, dass zwei eng tolerierte Rundbohrungen zusätzlich den Hülsenabstand
erzwingen. Sie lässt die tangentiale Ausrichtung erhalten. Diese Ausführung
ist unsere Übertragung des Vierweg-/Zweiweg-Lokalisierungsprinzips auf die
vorhandenen runden Hülsen; der Hersteller schreibt dieses Plattenlangloch nicht vor.

Die H7-Grenzen ergeben 0–0,032 mm diametrales Spiel zur dokumentierten Hülse.
Bei Mindestspiel null ist die Handsteckprobe verbindlich: kein Einpressen oder
Erzwingen. Anlageflächen und Passungsstellen beim Beschichten maskieren oder
anschließend fertig bearbeiten. Ein pauschales Eloxalaufmaß ist nicht enthalten.

Das Langloch bietet bei größtem Stift und kleinster Länge ±0,10 mm radialen
Spielraum. Angenommen sind 0,02 mm Fehler des Herstellerabstands, 0,02 mm
Bearbeitungsfehler und konservativ 0,0319 mm unterschiedliche Wärmeausdehnung
über 72,5 mm bei 40 K (Platte 23, Motorabstand 12 µm/(m·K)). Zusammen sind
das 0,0719 mm. Diese Werte sind Entwurfsannahmen, keine Herstellerzusagen.
Abstand, Hülsendurchmesser und tatsächliche Temperaturverhältnisse am Muster prüfen.

Das maximale geometrische Winkelspiel vor dem Klemmen beträgt unter diesen
Annahmen ungefähr ±0,0253°. An einem beispielhaften 400-mm-Hebel entspricht
das ±0,177 mm. Lagefehler, Achsfehler und Lastverformung sind darin nicht
enthalten. Die Passung allein weist daher keine hohe TCP-Genauigkeit nach.
Nach dem Klemmen muss der Gelenkrahmen kalibriert werden. Die Ausgangsplatte
hat weiterhin Freibohrungen; ihre Zentrierung, Kupplung und Wiederholmontage
brauchen einen gesonderten Präzisionsnachweis.

## Schrauben und Kopfsenkungen

Beide Platten: zunächst spanend bearbeitetes EN AW-6082-T6, 6,00 ±0,05 mm.
Werkstoff und Ebenheit sind Auslegungsannahmen. Schrauben ISO 4762, durchgehend
gewindet, Stahl 8.8, ohne Scheiben, Dichtung oder zusätzliche Beschichtungsdicke
im axialen Stapel. Die ausgewählten Längen müssen **unter dem Kopf gemessen**
innerhalb ±0,10 mm liegen. Diese Annahme ist eine Wareneingangsprüfung und
keine Behauptung über die allgemeine Längentoleranz handelsüblicher Schrauben.

| Größe | Gehäuseplatte | Ausgangsplatte |
|---|---:|---:|
| Anzahl / Schraube | 10 × M3×10, bedingt | 12 × M4×6 |
| Freibohrung | Ø3,4 mm | Ø4,5 mm |
| Kopfsenkung von der freien Plattenseite | Ø6,0 × 3,60 ±0,05 mm | Ø7,5 × 4,10 ±0,05 mm |
| Akzeptierter maximaler Kopf Ø / Höhe | 5,70 / 3,00 mm | 7,25 / 4,00 mm |
| Nominelle verbleibende Plattendicke am Sitz | 2,40 mm | 1,90 mm |
| Kleinste verbleibende Plattendicke | 2,30 mm | 1,80 mm |
| Nominelle axiale Überdeckung im Gewindebereich | 4,60 mm | 4,10 mm |
| Überdeckung mit angenommener Toleranzkette | 4,30–4,90 mm | 3,90–4,30 mm |
| Kleinster berechneter Abstand zum nutzbaren Gewindeende | 0,90 mm | 0,50 mm |
| Kleinster Rückstand der Kopfoberseite | 0,55 mm | 0,05 mm |

Berechnet wird `Überdeckung = Schraubenlänge − (Plattendicke − Senktiefe)
− ungewindeter Herstellervorbohrung`. Letztere ist am Gehäuse 3 mm, am
Ausgang null. Die Toleranzkette berücksichtigt gemessene Schraubenlänge
±0,10 mm, Platte und Senktiefe jeweils ±0,05 mm sowie am Gehäuse eine
angenommene Vorbohrungstiefe ±0,10 mm. Von der nominalen Gewindetiefe werden
zusätzlich 0,20 mm als vorläufige Tiefenreserve abgezogen.

**Bedingung für M3×10:** Die Rechnung nimmt einen 6-mm-Gewindebereich **hinter**
der 3-mm-Vorbohrung an. Die Herstellerzeichnung benennt M3 Tiefe 6 und
Vorbohrung Ø3,4 Tiefe 3, ohne den Gewindetiefenbezug in einem Schnitt eindeutig
zu zeigen. Die registrierten STEP-Kernzylinder reichen von z=-6 bis etwa -13 mm,
also etwa 7 mm hinter die Vorbohrung. Das unterstützt die Interpretation,
beweist aber weder volle Gewindelänge noch zulässige Einschraubtiefe.

Deshalb M3×10 erst einsetzen, wenn der Abstand von der Anlagefläche zum
**nutzbaren** Gewindeende mindestens 8,30 mm beträgt und die erforderliche
Gewindeüberdeckung bestätigt ist. Wären die 6 mm als Gesamttiefe ab der
Gehäusefläche gemeint, ist M3×10 hier ungeeignet. Dann Schraubenstapel und
Tragfähigkeit neu auslegen; nicht einfach mit Drehmoment prüfen. Für den
Ausgang sind entsprechend mindestens 4,80 mm Abstand von der Anlagefläche
zum nutzbaren Gewindeende erforderlich. Gewindeauslauf und Schraubenspitze
sind nicht als voll tragende Gewindegänge gerechnet oder qualifiziert.

Die Senkungen und das radiale Langloch sind echte Ausschnitte. Die Schulter-
Kupplungsnabe beginnt jetzt an der freien Plattenseite (`x6_plate_t`), damit
sie die versenkten Schraubenköpfe nicht durchdringt. Die 22 maximalen
Kopf-Hüllzylinder werden in der Standpose gegen alle physischen Endkörper
geprüft, auch innerhalb desselben starren Glieds. Schraubenkörper, Gewindegänge,
Inbusschlüssel und Werkzeugbewegung sind nicht dargestellt. Die Kopfschrauben
vor der anschließenden Oberarmkupplung einsetzen; tatsächlichen Werkzeugzugang
und Montagefolge am Prüfglied kontrollieren.

Am Ausgang verbleiben nominal nur 0,75 mm radialer Randsteg neben den
Kopfsenkungen. Sitzfläche, dünner Senkboden, Randsteg, Innengewindefestigkeit,
Lastverteilung, Dauerfestigkeit und Vorspannung sind nicht nachgewiesen.
Anziehdrehmoment bleibt `null`, bis Innengewindewerkstoff, Herstellerfreigabe
und ein repräsentativer Versuch vorliegen. Katalogdrehmomente für Stahl/Stahl
werden nicht ungeprüft auf das Servogehäuse übertragen.

## Prüfung und Änderung

`scripts/x6_mounting_design.py` berechnet die Stapel und Spielräume ohne CAD.
Zu kurze/zu lange Schrauben, unberücksichtigte Scheiben, unzureichende
Langlochentlastung und eine geänderte X6-Plattendicke werden zurückgewiesen.
Die nominale Rechnung unterscheidet axiale Überdeckung ausdrücklich von
nachgewiesener voller Gewindetragfähigkeit.

`python scripts/x6_mounting_design.py --report exports/x6-fits-fasteners/design-validation.json`
speichert die Rechnung mit aktuellen Quell-/Generatorprüfsummen, CAD-Verweisen
und Schraubenkopfprüfung. Der [Auslegungsbericht als JSON](../exports/x6-fits-fasteners/design-validation.json)
ist damit dem konkreten Modellstand zugeordnet.

Nach Änderungen an dieser Quelle zuerst die Bibliothek neu aufbereiten und
ihre Prüfsumme in `model/robot.json` aktualisieren; dann
`python scripts/build_models.py --ros2`. Der
[Build-Bericht](../exports/generated/build-report.json) benennt die gültigen
CAD-Dateien, Volumen-/Schwerpunktvergleiche, Gelenk- und Protokollstichproben.
Die [neue Plattenansicht](../exports/x6-fits-fasteners/motor-plates.png) zeigt
die tatsächlich erzeugten Körper, Gehäuse links und Ausgang rechts.

Der erzeugte Armstand vergleicht 72 Endkörper zwischen beiden CADs. Alle 22
Kopfhüllen sind in der Standpose frei von Überschneidungen oberhalb 0,0001 mm³.
Sechs Einzelbewegungen, sieben FreeCAD-Posen und elf Protokollstichproben sind
geprüft. Die mobile Referenzbaugruppe stimmt in drei gespeicherten Zuständen
mit je 111 Körpern und zwei Maßvarianten überein; dabei wurde außerdem die
SolidCraft-Verschiebung importierter Servos in den korrekten Armrahmen verlegt.
Die [Offline-Suite](../exports/x6-fits-fasteners/offline-tests.log) bestand mit
111 Tests. Diese Nachweise qualifizieren weder Last noch Fertigungsgenauigkeit.

Vor Freigabe: Maße und Gewindetiefen am konkreten Motor prüfen, Schrauben messen,
Handsteckprobe durchführen, Montagezugang prüfen und das repräsentative Gelenk
unter Last, Temperatur und Wiederholmontage messen. `physical_sample_verified`
und `manufacturing_released` bleiben `false`. ROS-/RViz-Laufzeit ist weiterhin
nicht ausgeführt; der vollständige Bewegungsraum ist nicht geprüft.

## Quellen

- [MYACTUATOR-Zeichnung, Revision 260920, Seite 1](../cad/vendor/myactuator/RMD-X6-P20-60-E/260920/vendor-document-1.pdf): ursprüngliche Bohrungs- und Hülsenangaben.
- [Schaeffler TPI 211, gedruckte Seite 49](https://www.schaeffler.com/remotemedien/media/_shared_media/08_media_library/01_publications/schaeffler_2/tpi/downloads_8/tpi_211_de_en.pdf): ISO-Bohrungstoleranzen, H7 über 3 bis 6 mm: 0/+12 µm.
- [MISUMI: Locating Pins](https://in.misumi-ec.com/pr/blog/locating-fixtures/locating-pins-by-misumi/): Vierweg-/Zweiweg-Prinzip für eindeutige Lage ohne doppelte Abstandsbindung.
- [Würth ISO 4762 M4×6, 8.8](https://eshop.wuerth.de/-/414964%206.sku/de/DE/EUR/): Beispiel eines lieferbaren vollgewindigen Schraubentyps, Kopf 7 × 4 mm.
- [Accu ISO 4762 M3×10](https://www.accu.co.uk/metric-cap-head-screws/642446-SSCF-M3-10-HK-12-9): Kopfmaße eines 12.9-Beispiels; Maßvergleich, keine Übernahme dieser Festigkeitsklasse in die 8.8-Auswahl.
- [Accu M4×6](https://www.accu.co.uk/metric-cap-head-screws/16017-SSCF-M4-6-12-9): Maßvergleich einschließlich Kopfaußendurchmesser bis 7,22 mm. Die Eingangsprüfung muss die oben akzeptierte Hüllkontur bestätigen.
