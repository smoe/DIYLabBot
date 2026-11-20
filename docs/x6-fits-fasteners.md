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

<a id="merged-x6-interface-resolution"></a>

<a id="merged-x6-interface-resolution--x6-motorplatten-zuordnung-geklärt-und-korrigiert"></a>

## X6-Motorplatten: Zuordnung geklärt und korrigiert

Stand: 28. Oktober 2026. Die vermeintliche Abweichung zwischen Zeichnung und STEP
entstand durch eine falsche Zuordnung der Maßpfeile in unserer ersten Integration.
Die M4-Angabe gehört zum inneren Ausgangsflansch, die zehn M3 zur äußeren
Gehäusebefestigung. Die Herstellerdaten sind an diesen Stellen konsistent.

Dieser Bericht dokumentiert die erste Lochbildkorrektur. Der anschließend
ausgelegte Stand mit Passung, radialem Langloch und Schraubenkopfsenkungen steht
in [X6: Zentrierung und Schraubenstapel](x6-fits-fasteners.md); die damaligen
Prüfzahlen und Bilder unten bleiben als Historie erhalten.

<a id="merged-x6-interface-resolution--quellen-und-befund"></a>

### Quellen und Befund

Geprüft wurden die unveränderte
[Herstellerzeichnung, Seite 1](../cad/vendor/myactuator/RMD-X6-P20-60-E/260920/vendor-document-1.pdf)
und die STEP-Datei aus demselben Paket **RMD-X6-P20-60, Revision 260920**.
Der aktuell auf der [Herstellerseite](https://www.myactuator.com/downloads-xseries)
verlinkte Download entspricht derselben Archiv-URL im lokalen Manifest.
Es gibt hier keinen Hinweis auf eine Vermischung verschiedener Modellrevisionen.

| Schnittstelle | Zeichnungsangabe | Passende STEP-Merkmale |
|---|---|---|
| Festes Gehäuse | 10 × M3, Gewindetiefe 6 mm, auf Ø72,5 mm; Stufenbohrung Ø3,4 mm, 3 mm tief | Zehn Ø3,4-mm-Stufenbohrungen und zehn zugehörige Ø2,5-mm-Kernbohrungen an denselben Zentren |
| Rotierender Ausgang | 12 × M4, Gewindetiefe 5 mm, auf Ø44 mm | Zwölf Ø3,3-mm-Kernbohrungen an den zwölf Flanschpositionen |
| Zwei gesonderte Gehäusestellen | Ø5-mm-Zentrierhülsen, Toleranz 0/−0,02 mm, 2 mm Überstand; axiale Ø3-mm-Bohrung und zugehöriges M3-Gewinde 3 mm tief | Zwei hohle Hülsen mit Außendurchmesser 5 mm, Innendurchmesser 3 mm und Länge 8 mm auf dem Ø72,5-mm-Kreis |

Kernbohrungen im vereinfachten STEP sind keine Darstellung des vollen
Gewinde-Außendurchmessers. Die zuvor als Widerspruch gewerteten 3,3 mm passen
zur ausdrücklich mit M4 beschrifteten Ausgangsschnittstelle. Die zwei Hülsen
gehören nicht zur Anzahl der zehn Gehäuseschrauben.

Die [abstrakte Schnittstellenbeschreibung](../model/x6-mounting-interface.json)
enthält diese Zuordnung, Bohrungs- und Gewindetiefen, Referenzdatei und Prüfsumme.
Der [geometrische Abgleich](../cad/vendor/myactuator/RMD-X6-P20-60-E/260920/derived/registered-v2/interface-check.json)
führt die tatsächlichen CAD-Zentren, Kernbohrungszahlen und Hülsengeometrien.
Die nominelle Ringlage ist übernommen; die Ausgangslochzentren behalten ihre
kleine, im Hersteller-CAD vorhandene Winkelverdrehung.

<a id="merged-x6-interface-resolution--korrektur-der-gemeinsamen-motorplatten"></a>

### Korrektur der gemeinsamen Motorplatten

| Teil | Vorher | Jetzt |
|---|---|---|
| A2_housing_plate | Zehn Ø4,5-mm-Freibohrungen; Zentrierhülsen nicht berücksichtigt | Zehn Ø3,4-mm-Freibohrungen für M3 plus zwei nominelle Ø5-mm-Hülsenbohrungen |
| A2_output_plate | Zwölf Ø3,4-mm-Freibohrungen | Zwölf Ø4,5-mm-Freibohrungen für M4 |
| A2_housing, vereinfachte Vendor-Geometrie | Zwei vorstehende Hülsen ausgelassen | Beide Hülsen im festen Gehäusekörper erhalten |

Die generische Operation `mount_plate` übernimmt nun neben dem Schraubenlochbild
auch ausdrücklich registrierte Hülsenbohrungen. Diese Erweiterung wirkt bei X6;
die übrigen Servos haben keine zusätzlich eingetragenen Hülsenstellen.
X6-Gehäuse und -ausgang liegen als neue Ableitung unter `registered-v2/`.
Die alten `registered-v1`-Dateien und alle Originale bleiben unverändert.

`model/robot.json` bindet die aktualisierte Komponentenbibliothek mit SHA-256.
Die Bibliothek bindet ihrerseits Schnittstellenquelle und Abgleichsbericht.
FreeCAD und SolidCraft erzeugen daraus dieselben nativen Plattenbohrungen.
RViz erhält aktualisierte Strukturmeshes und die um die Hülsen erweiterte
konservative Gehäusebox. Kameras, ihre optischen Rahmen und Sichtkegel aus
dem vorhandenen Modellstand bleiben in der gemeinsamen Quelle enthalten.

<a id="merged-x6-interface-resolution--prüfung-und-verbleibende-auslegung"></a>

### Prüfung und verbleibende Auslegung

Der aktuelle [Build-Bericht](../exports/generated/build-report.json) nennt die
betroffenen CAD-Dateien und Prüfungen. Neben Körpervergleich und sechsachsiger
Gelenkprüfung kontrollieren Regressionstests ausdrücklich die korrekte
M3-/M4-Zuordnung, Kernbohrungen, beide Hülsen und die zwei Motorplattenvolumina
gegen die analytisch berechneten Bohrungsabzüge.

Im erfolgreichen Neuaufbau wurden alle 72 Endkörper einschließlich der
vorhandenen Kameras zwischen beiden CADs verglichen. Alle sechs SolidCraft-
Gelenke ließen sich um +5° bewegen und zurücksetzen. Sieben FreeCAD-Posen und
elf Protokollstichproben zeigten keine Überschneidungen oberhalb der erklärten
0,0001-mm³-Schwelle zwischen verschiedenen starren Gliedern. Alle 74 Offline-
Tests bestanden; der vollständige Bewegungsraum ist damit nicht nachgewiesen.
ROS-/RViz-Laufzeit und physische Passung sind weiterhin nicht getestet.

Die [Draufsicht der korrigierten Platten](../exports/x6-interface-review/motor-plates.png)
stammt aus den tatsächlich regenerierten FreeCAD-Volumenkörpern, im kanonischen
Servorahmen nebeneinander angeordnet: Gehäuseplatte links, Ausgangsplatte rechts.
Die [STEP-Prüfansicht](../exports/x6-interface-review/motor-plates.step) und
[Herkunft](../exports/x6-interface-review/plate-view-provenance.json) sind gespeichert.

Die nominale Schnittstelle ist damit geklärt. Die nachfolgende
[Passungs- und Schraubenauslegung](x6-fits-fasteners.md) ersetzt die zwei
einfachen Ø5-mm-Bohrungen durch eine H7-Rundbohrung und ein radiales Langloch.
Sie ergänzt Kopfsenkungen und berechnete M3×10-/M4×6-Stapel. Die M3-Auswahl ist
an eine Gewindetiefenprüfung gebunden. Zulässiger Eingriff und reale Teile müssen
vor Fertigung bestätigt werden. Zeichnungs-Gewindetiefe, im STEP sichtbare
Bohrungstiefe und zulässiger Schraubeneingriff sind getrennte Größen.
`manufacturing_released` und `physical_sample_verified` bleiben daher `false`.
