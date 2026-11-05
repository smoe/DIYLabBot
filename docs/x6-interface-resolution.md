# X6-Motorplatten: Zuordnung geklärt und korrigiert

Stand: 28. Oktober 2026. Die vermeintliche Abweichung zwischen Zeichnung und STEP
entstand durch eine falsche Zuordnung der Maßpfeile in unserer ersten Integration.
Die M4-Angabe gehört zum inneren Ausgangsflansch, die zehn M3 zur äußeren
Gehäusebefestigung. Die Herstellerdaten sind an diesen Stellen konsistent.

Dieser Bericht dokumentiert die erste Lochbildkorrektur. Der anschließend
ausgelegte Stand mit Passung, radialem Langloch und Schraubenkopfsenkungen steht
in [X6: Zentrierung und Schraubenstapel](x6-fits-fasteners.md); die damaligen
Prüfzahlen und Bilder unten bleiben als Historie erhalten.

## Quellen und Befund

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

## Korrektur der gemeinsamen Motorplatten

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

## Prüfung und verbleibende Auslegung

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
