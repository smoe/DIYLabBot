# X2/X4: Zentrierung, Schrauben und Motorplatten

Stand: 29. Oktober 2026. Nominalauslegung für ein Prüfglied, keine Fertigungs-
oder Präzisionsfreigabe. Führende Quellen sind
[X2](../model/x2-mounting-interface.json), [X4](../model/x4-mounting-interface.json)
und die Einbaulagen/Plattenmaße in [robot.json](../model/robot.json).
Die gemeinsame Bibliothek bindet diese Dateien und ihre CAD-Abgleiche mit SHA-256.

## Herstellerangaben und Auswahl

Maßgeblich sind die X2-Zeichnung im Paket 260920, Seite 1, und die X4-Unterlage
im Paket 261019, PDF-Seite 5 / gedruckte Seite 4. Die Maßpfeile wurden mit den
STEP-Zylinderachsen abgeglichen. X4 verwendet hier die vordere feste
Gehäuseschnittstelle, nicht die hintere M2,5-Schnittstelle der Elektronik.

| Schnittstelle | Schraubenlochbild | Zeichnungs-Gewindetiefe | Gesonderte Zentrierbohrungen |
|---|---|---:|---|
| X4 Gehäuse | 6 × M3, Ø48 mm | 6 mm | 2 × Ø3,000–3,030 mm, 4 mm tief |
| X4 Ausgang | 6 × M3, Ø26 mm | 6 mm | 3 × Ø3,000–3,030 mm, 3 mm tief; davon zwei benutzt |
| X2 Gehäuse | 4 × M3, Ø38 mm | 4 mm | 2 × Ø3,000–3,020 mm, 4 mm tief |
| X2 Ausgang | 4 × M3, Ø25 mm | 5 mm | 2 × Ø3,000–3,020 mm, 4 mm tief |

Die Kernbohrungen im STEP reichen teilweise tiefer: X2-Gehäuse 5 mm statt
4 mm Zeichnungsgewinde, X2-Ausgang 7,5 mm statt 5 mm. Diese CAD-Hohlräume werden
nicht als zulässige Einschraubtiefe verwendet. Die unbeschrifteten Hohlräume
liefern ebenso wenig einen Nachweis voller Gewindegänge. Anders als beim X6
ist für diese vorderen M3-Stellen keine zusätzliche ungewindete Stufe angegeben.

## Schraubenstapel

Alle Platten zunächst 6,00 ±0,05 mm, Materialannahme EN AW-6082-T6,
Anlageflächenebenheit 0,02 mm. Keine Scheiben, Dichtungen oder zusätzliche
Lack-/Beschichtungsdicke im axialen Stapel. Gewinde M3 × 0,5 mm.

| Schnittstelle | Je Motorplatte | Zylindrische Kopfsenkung von freier Seite | Axiale Gewindeüberdeckung nominal / Bereich |
|---|---|---|---|
| X4 Gehäuse | 6 × M3×8 ISO 4762, Stahl 8.8 | Ø6,00 × 3,10 ±0,05 mm | 5,10 / 4,90–5,30 mm |
| X4 Ausgang | 6 × M3×8 ISO 4762, Stahl 8.8 | Ø6,00 × 3,10 ±0,05 mm | 5,10 / 4,90–5,30 mm |
| X2 Gehäuse | 4 × M3×6 DIN 7984, Stahl 08.8 | Ø5,70 × 3,10 ±0,05 mm | 3,10 / 2,90–3,30 mm |
| X2 Ausgang | 4 × M3×8 DIN 7984, Stahl 08.8 | Ø5,70 × 2,10 ±0,05 mm | 4,10 / 3,90–4,30 mm |

Für die ISO-4762-Köpfe werden höchstens Ø5,70 mm und 3,00 mm Höhe akzeptiert,
für DIN 7984 höchstens Ø5,50 mm und 2,00 mm Höhe. DIN 7984 hat wegen der
Kopfform **reduzierte Belastbarkeit**, gekennzeichnet durch 08.8. Sie ist hier
keine gleichwertige Übernahme der vollen Kopftragfähigkeit von ISO 4762.
Würth führt passende M3×6-/M3×8-Ausführungen; es wurde nichts bestellt.

Die tatsächliche Unterkopflänge muss bei Wareneingang innerhalb ±0,10 mm
geprüft werden. Das ist unsere Annahme für die Rechnung, keine allgemeine
Zusicherung handelsüblicher Schrauben. Platte und Senktiefe erhalten jeweils
±0,05 mm. Vom Zeichnungsgewinde werden 0,20 mm als vorläufige Tiefenreserve
abgezogen. Daraus bleiben in allen vier Fällen mindestens 0,50 mm Abstand zum
angenommenen nutzbaren Gewindeende. Gewindeauslauf und Schraubenspitze sind
nicht als voll tragende Gewindegänge qualifiziert.

Berechnet wird `Überdeckung = Unterkopflänge − (Plattendicke − Senktiefe)`.
Am Muster müssen mindestens 5,80 mm nutzbare Tiefe für X4, 3,80 mm am
X2-Gehäuse und 4,80 mm am X2-Ausgang bestätigt werden. Die kleinste nominell
tolerierte Restdicke unter den Senkungen beträgt 2,80 mm, am X2-Ausgang
3,80 mm. Kleinster Kopfrückstand ist 0,05 mm; am X2-Gehäuse 1,05 mm.
Die tiefe Gehäusesenkung ermöglicht die übliche M3×6-Länge trotz des kurzen
4-mm-Herstellergewindes.

Drehmoment bleibt `null`. Innengewindewerkstoff, tragende Gewindelänge,
Auflagefläche unter dem Kopf, Vorspannung, Reibung und Ausreißen müssen am repräsentativen
Gelenk qualifiziert werden. Katalogdrehmomente für Stahl/Stahl werden nicht
auf das Servogehäuse übertragen.

## Eigene Rund-/Entlastungsstifte

X2/X4 liefern weibliche Zentrierbohrungen, keine männlichen Hülsen wie X6.
Jede eigene Platte erhält zwei eigene gestufte Stifte: einen runden und einen
Stift mit rautenförmigem Kopf, dessen schmalere Diagonale entlang der Verbindungslinie liegt. Bei X4-Ausgang
bleibt die dritte Herstellerbohrung frei. Das längste registrierte Bohrungspaar
wird verwendet; die expliziten, aus STEP registrierten Zentren stehen in der Quelle.

| Stiftmerkmal | Auslegung |
|---|---|
| Runder Kopf in Herstellerbohrung | Ø3 h6: 2,994–3,000 mm; CAD 2,997 mm |
| Kopfüberstand ab Anlagefläche | 2,50 ±0,05 mm |
| Entlasteter zweiter Kopf | Konvexe Raute; radial 2,80 ±0,02 mm, tangential 2,988–2,994 mm; CAD tangential 2,991 mm |
| Annahme zur Ausrichtung | Entlastungsrichtung innerhalb ±0,25° zur Linie der beiden Sitze |
| Pressschaft in eigener Platte | Ø3,010–3,016 mm, CAD 3,013 mm; explizite Sondermaße |
| Eigene Aufnahmebohrung | Ø3 H6: 3,000–3,006 mm, CAD 3,003 mm |
| Pressschaftlänge | 3,50 ±0,05 mm |
| Blinde Aufnahmebohrung | 4,00 ±0,05 mm tief |
| Materialannahme | Gehärteter, geschliffener Stahl 58–62 HRC; Güte/Verfahren noch offen |

Damit beträgt das vorgesehene diametrale Übermaß im eigenen Plattensitz bei
Referenztemperatur 4–16 µm. Die Stifte sind **eigene Sonderteile**, keine mit
dem Motor gelieferten oder schon ausgewählten Katalogteile. Werkstattfähigkeit,
Kosten, Einpresskraft, Sitzfestigkeit in Aluminium, Temperaturverhalten und
Auswechselbarkeit sind vor Fertigung zu bestätigen. Beim Einpressen die Platte
abstützen; keine unkontrollierte Presslast ins Servo einleiten.

Der runde h6-Kopf bleibt zur X2-Herstellerbohrung nominell um 0–26 µm,
zur X4-Bohrung um 0–36 µm frei. Die tangentiale Rautenweite hat entsprechend
6–32 bzw. 6–42 µm Spiel. Die Herstellerbohrungen werden ausdrücklich
nicht zu H7 umbenannt. Bei Mindestspiel null ist die Handsteckprobe notwendig;
kein Erzwingen. Fitflächen beim Beschichten maskieren oder nachbearbeiten.
Einlauf C0,15 ist eine Werkstattannahme und geometrisch ausgelassen.

Die schmalere Rautendiagonale bietet mindestens 0,09 mm radiale Entlastung. Die Quelle
setzt 0,020 mm Hersteller-Abstandsfehler, 0,015 mm eigenen Abstandsfehler und
die unterschiedliche Wärmeausdehnung über 40 K an (23 gegenüber 12 µm/(m·K)).
Das größte so angenommene Fehlerbudget liegt bei rund 0,0561 mm am
48-mm-X4-Gehäusepaar; mit möglichem radialem Spiel am primären Rundstift sind
es 0,0741 mm. Alle vier Rautenecken werden gegen den kleinsten Bohrungsradius
gerechnet, einschließlich ±0,25° Ausrichtungsfehler. Eine Rundkontur mit nur
zwei Flächen genügt bei Null-Mindestspiel dafür nicht: ihre verbleibenden
Kreisbögen können trotz radialer Entlastung klemmen. Die Raute und ihr
tangentiales Mindestspiel vermeiden dies innerhalb der genannten Annahmen.
Der tatsächliche Hersteller-Abstandsfehler ist unbekannt.
Diese Annahmen sind am Muster zu prüfen; das CAD liefert keine Toleranzmessung.

Mit 0,10 mm Reserve auf die Hersteller-Bohrungstiefe beträgt der kleinste
Stiftabstand zum Grund 0,35 mm am X4-Ausgang und 1,35 mm an den übrigen Stellen.
Der Pressschaft bleibt mindestens 0,40 mm vor dem Grund seiner Plattenbohrung.

Die beabsichtigte kleine Pressüberdeckung ist als solche im BRep vorhanden.
Die Stiftköpfe müssen in die Herstellerbohrungen passen, ohne Hersteller-Material
zu durchdringen; diese beiden Fälle werden getrennt geprüft. Die 20 Stifte gehören
jeweils zu demselben starren Link wie ihre eigene Platte. Köpfe und radiale
Entlastungen sind modelliert; Fasen und Gewindegänge sind ausgelassen.

## Genauigkeit und Geometrieänderungen

| Schnittstelle | Max. geometrisches Winkelspiel vor Klemmung, unter den Annahmen |
|---|---:|
| X4 Gehäuse | etwa ±0,0466° |
| X4 Ausgang | etwa ±0,0992° |
| X2 Gehäuse | etwa ±0,0437° |
| X2 Ausgang | etwa ±0,0665° |

Das ist keine Zusage für Wiederholmontage oder TCP-Genauigkeit. Allein ±0,0992°
wären an einem beispielhaften 400-mm-Hebel etwa ±0,69 mm. Bohrungs-Lagefehler,
Konzentrizität, Lastverformung und weitere Gelenke sind nicht eingerechnet.
Hohe tatsächliche Genauigkeit erfordert Klemmen, Kalibrieren und Messungen;
die Kamera kann die tatsächliche Spitze-/Gefäßbeziehung zusätzlich erfassen.
Soll auch der mechanische Wiederaufbau präziser werden, sind nach Vermessung
selektiv angepasste Stiftköpfe bzw. Buchsen eine eigene Folgeauslegung.

X2-Ausgangsplatten wachsen von Radius 15,5 auf 15,7 mm; die festen X2-Platten
erhalten Radius 16,0 mm im Mittelfreiraum. Nominal verbleiben 0,30 mm radialer
Bewegungsfreiraum, 0,35 mm äußerer Senkungsrand an der Ausgangsplatte und
0,15 mm innerer Senkungsrand an der festen Platte. Diese schmalen Ränder sind
kein Festigkeitsnachweis. Die Kopfsenkungsböden bleiben dicker als diese radialen
Ränder; Lagertoleranzen und Bearbeitung müssen trotzdem geprüft werden.

Das X4-Ellenbogenmodul liegt 3 mm weiter außen entlang seiner vorhandenen
Achse; das X2-Handgelenkmodul 4 mm weiter außen. So endet die Gehäuseplatte
an der äußeren Arm-/Gabelseite, statt Köpfe mit der Struktur zu überdecken.
J1-Querträger, J1-/J3-/J4-/J5-/J6-Kupplungsenden beginnen bzw. enden an den
neuen freien Plattenseiten. Gelenkachsen, Gliedlängen und Flanschreferenz
bleiben aus derselben Kinematik abgeleitet. Die Kupplungen und die Befestigung
der Platten an der Armstruktur bleiben Konzeptbauteile ohne Lastnachweis.
Schrauben vor den anschließenden Strukturteilen montieren; Werkzeugzugang
und reale Montagefolge sind noch nicht praktisch geprüft.

## Generierung und Nachweise

`scripts/servo_mounting_design.py` verwendet dieselbe Stapelrechnung für
X2, X4 und über den kompatiblen X6-Adapter auch X6. Zu große Köpfe,
ungeeignete Längen, geänderte Plattendicken, unzureichende Retention oder
radiale Entlastung führen zu einem Fehler. Die CAD-unabhängige `mount_plate`-
Expansion erzeugt Platten, Aufnahmen, Pins und deren Entlastungen einmal für
beide CAD-Adapter. Die Herstellerdateien bleiben unverändert.

`python scripts/check_servo_mountings.py` schreibt die Gesamtberechnung mit
Quell-/Generatorprüfsummen, CAD-Nachweisen und der nominellen Hardwareliste.

Nach bewussten Schnittstellenänderungen die Bibliothek mit FreeCADs Kern-Python
neu aufbereiten, Prüfsumme in `model/robot.json` aktualisieren und
`python scripts/build_models.py --ros2` ausführen. Der
[aktuelle Build-Bericht](../exports/generated/build-report.json) benennt die
gültigen Dateien und Quellstände. Die [Berechnung mit Herkunft](../exports/x2-x4-fits-fasteners/design-validation.json),
[freie Plattenseiten](../exports/x2-x4-fits-fasteners/plate-free-faces.png) und
[Stiftseiten](../exports/x2-x4-fits-fasteners/plate-servo-faces.png) gehören zum
jeweiligen Neuaufbau. Von links: X4-Gehäuse, X4-Ausgang, X2-Gehäuse, X2-Ausgang.
RViz erhält die eigenen Platten und Pins in
den Strukturmeshes; die Servos bleiben sechs einfache Quader.

Der abgeschlossene Neuaufbau vergleicht 92 Armkörper in beiden CADs.
Alle 70 Kopfhüllen und alle 20 Stift-/Vendor-Prüfungen bestehen; die beabsichtigte
Pressüberdeckung ist getrennt erfasst. Sieben Armposen und elf Protokollstichproben
zeigen keine erklärungspflichtigen Überschneidungen zwischen starren Gliedern.
Die mobile Referenzbaugruppe stimmt in drei gespeicherten Zuständen mit jeweils
131 Körpern und in zwei Maßvarianten überein. Ihre 14 Kollisionsstichproben
bestanden. Alle 144 [Offline-Tests](../exports/x2-x4-fits-fasteners/offline-tests.log)
bestanden. Die [Prüfherkunft](../exports/x2-x4-fits-fasteners/offline-test-result.json)
hält Modellstand, Testdateien und Log-Prüfsumme fest.

Standpose, Einzelbewegungen, Parametervarianten und Protokollstichproben sind
von kontinuierlicher Bewegungsraumprüfung und mechanischer Qualifikation zu
unterscheiden. ROS-/RViz-Laufzeit, reale Passung, Retentionskraft, Drehmoment
und Tragfähigkeit bleiben ungetestet; beide Freigabeflags bleiben `false`.

## Quellen

- [X2-Herstellerzeichnung, Seite 1](../cad/vendor/myactuator/RMD-X2-P28-7-E/260920/vendor-document-1.pdf).
- [X4-Herstellerunterlage, PDF-Seite 5](../cad/vendor/myactuator/RMD-X4-P36-36-E-L/261019/vendor-document-1.pdf).
- [Schaeffler HG 1, ISO-Passungstabellen](https://www.schaeffler.com/remotemedien/media/_shared_media/08_media_library/01_publications/schaeffler_2/catalogue_1/downloads_6/hg_1_de_en.pdf): H6 bei Nennmaß bis einschließlich 3 mm: 0/+6 µm.
- [MISUMI Rund-/Diamantstiftprinzip](https://in.misumi-ec.com/pr/blog/locating-fixtures/locating-pins-by-misumi/): Vermeidung der doppelten Abstandsbindung; unsere gestuften Stifte sind eine eigene Ausführung.
- [Würth DIN 7984 M3×8, 08.8](https://eshop.wuerth.de/Hexagon-Socket-Head-Cap-Screw-with-low-Head-DIN-7984-steel-88-plain-SCR-CYL-DIN7984-088-HS2-M3X8/00853%20%208.sku/en/US/EUR/): Kopf Ø5,5 × 2 mm und reduzierte Kopfbelastbarkeit.
- [Böllhoff DIN-7984-Datenblatt](https://eshop.boellhoff.de/out/media/pdf/DIN_7984_Stahl_08.8___de.pdf): Grenzmaße und Hinweis zur Kopfbelastbarkeit.
