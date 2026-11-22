# Gebäude im Browser erkunden

Die [Kamerawand im EG-Foyer](foyer-camera-wall.md) zeigt auswählbare
Modellansichten auf 20 Monitoren an der Aufzugaußenwand. Ein Monitorklick öffnet die
Großansicht. Transporter ohne Kamera beziehungsweise ohne laufenden Player
liefern keine Bilder; reale Streams und Aufzeichnungen sind nicht angebunden.

Die freie Kamera prüft ihre Translation kontinuierlich mit einer als Darstellungsannahme geführten Kugel gegen die nativen Dreiecksflächen, einschließlich der aktuellen Türposen. Sie gleitet an Hindernissen entlang; nicht aufgelöste Kontakte stoppen die Bewegung. Radius, Kontaktabstand und Rechengrenzen stehen einmalig unter `navigation` in `model/building-walkthrough.shared.json`. Das ist keine geprüfte menschliche Körperhülle oder reale Schutzfunktion.

Die benannten kleinen Technikzugänge `N3_023` bis `N3_027` starten auf OG1–OG3 geschlossen. Labor- und Bürotüren starten weiterhin offen. Startzustand und native Referenzpose sind getrennt: Die bestehenden offenen Referenzgeometrien werden nicht geändert. Während Türbewegungen bleibt zusätzlich die geschlossene Durchgangspose für die Kamera gesperrt. Freies Bewegen in den Aufzugschacht ist auch bei fehlender Kabine gesperrt; Einsteigen, Mitfahren und Aussteigen erfolgen über die vorhandenen Aufzugbefehle. Blickpunkt- und Geschosswechsel bleiben ausdrücklich diskrete Ansichtswechsel, keine kollisionsgeprüften Gehwege.

Die unabhängigen Kontaktfälle laufen mit `node tests/check_walkthrough_camera.cjs` oder über `python3 -m unittest discover -s tests -p test_walkthrough_camera.py -v`. Sie prüfen dünne Wände bei großen Schritten, Gleiten, Ecken, Böden, offene und geschlossene bewegte Türen, Dreieckskanten und den Schachtzugang. Neue Browserausgaben benötigen einen eigenen Darstellungsnachweis; diese Funktion qualifiziert weder Türschwenkräume noch Personen- oder Hardwarebetrieb.

`node tests/check_walkthrough_camera_native.cjs <index.html>` prüft zusätzlich die tatsächlichen Türblätter `D3_026`/`D3_027`, die offenen Durchgänge von 3.002/3.003 und einen absichtlich geöffneten Schachtzugang im 3. OG ohne dortige Kabine. Die Schachtsperre wird aus den gemeinsamen Rahmenkörpern abgeleitet. Das Ergebnis wird als `camera-native-contacts.json` neben dem lokalen Export abgelegt.

Der Rundgang bietet sieben direkte Blickpunkte: Doktorandenraum **3.002**,
Labor **3.003**, Mikroskop **3.007**, Küchen **3.008** und **1.008**,
den Blick durch den **Freiraum / das Atrium**
und den **Kernbereich im 3. OG**.
Von dort lässt sich die Kamera frei bewegen. Die Flächen stammen aus den
fertigen nativen CAD-Körpern einschließlich ihrer Booleschen Öffnungen;
Raumwände, Fenster und Möbel werden nicht als Ersatzquader nachgezeichnet.
Labor 3.003 liegt jetzt im selben Gebäudebezug wie Flur, Büros und Aufzug.
Die [öffentliche GitHub-Pages-Seite](https://smoe.github.io/DIYLabBot/) bleibt
eine getrennt veröffentlichte Momentaufnahme. Ihr tatsächlicher Quellstand
steht im [Publikationsmanifest](https://smoe.github.io/DIYLabBot/site-manifest.json).
Lokale Erweiterungen werden nach ausdrücklicher Freigabe dorthin übertragen.

## Raumschilder

Der lokale Stand enthält 80 Raumschilder in KG, EG und OG1–OG3: 75 direkt rechts neben der Tür und fünf an der unmittelbar anschließenden rechten Nischenwand. Die bekannten Bezeichnungen stammen aus dem jeweiligen Geschossplan und den vorhandenen, gepinnten Raumzuordnungen, etwa Doktorandenraum, Labor, Mikroskop oder Küche. Die Schildschrift erscheint in Großbuchstaben; die ursprüngliche Bezeichnung und ihre Herkunft bleiben im Interface erhalten. F03-Nummern werden nicht pauschal auf andere Geschosse übertragen, unbekannte Nutzungen nicht erfunden. Ein Schild setzt eine eindeutige, erhaltene direkte Flurtür voraus. Benannte Flächen ohne eine solche Tür stehen unter `unplaced_rooms`; Verbindungstüren zwischen Räumen begründen kein zusätzliches Flurschild.

„Rechts neben der Tür“ gilt vom Flur mit Blick auf die Tür, unabhängig von Planrichtung oder Türanschlag. Die Platzierung berücksichtigt die gesamte Schildplatte samt Schriftstärke, benachbarte Wandstücke, Öffnungen und die modellierten offenen Türblätter; bei Bedarf werden der Türabstand vergrößert oder die Schildbreite reduziert. Eine linke Ausweichposition wird nicht erzeugt. Platte und Schriftstriche sind portable native Geometrie aus derselben Quelle. Der neue vollständige FreeCAD-Aufbau stimmt im strengen Vergleich aller 160 Schildkörper mit der separat erzeugten SolidCraft-Fassung überein; deren unveränderte Geometriebefehle sind für den aktuellen Quellstand ausdrücklich nachgewiesen. Vier zusätzliche, aus der Quelle abgeleitete Prüfblickpunkte im Browser bestätigen die Schilddarstellung. Abmessungen und Positionen bleiben ungemessene Darstellungsannahmen, `signage_qualified` bleibt `false`. Die öffentliche GitHub-Pages-Momentaufnahme wird erst nach gesonderter Freigabe erneuert.

## Erzeugen und öffnen

```bash
python3 scripts/build_building_walkthrough.py --serve
```

Der Aufruf prüft die Quell- und Artefaktpins des nativen FreeCAD-Gebäudemodells
und der L01-Aufstellung. Einen veralteten Gebäudestand baut er unabhängig mit
dem FreeCAD-Adapter neu auf. Für L01 ist ein aktueller geprüfter Build erforderlich;
der Rundgang erzeugt keine neuen Gerätestände. `--no-rebuild` verlangt auch für
das Gebäude einen bereits aktuellen Cache. Das FreeCAD-Werkzeug lässt sich mit
der üblichen `--freecad-python`-Option angeben. Der erste Gebäudeaufbau kann
länger dauern als der anschließende Mesh-/HTML-Export.

SolidCraft lässt sich aus derselben Quelle separat erzeugen und prüfen:

```bash
python3 scripts/build_building_stack.py --backend solidcraft --no-render
```

Die zusätzliche vollständige STEP-XOR-Vergleichsprüfung bei `--backend both`
ist keine Build-Abhängigkeit des Rundgangs. Der Browserbericht benennt die
tatsächlich verwendeten nativen Nachweise und übernimmt keine ausgelassene
Vergleichsprüfung als bestanden.
Mit `--building-report` lässt sich der versionierte FreeCAD-Prüfbericht
ausdrücklich binden, auch wenn ein separater SolidCraft-Aufbau den gemeinsamen
Berichtszeiger anschließend ersetzt.

Die Ausgabe nennt die lokale URL und die dauerhafte Datei
`exports/building-walkthrough/<Revision>/index.html`. Diese HTML-Datei enthält
Geometrie, Bedienelemente und Renderer vollständig und lässt sich auch direkt
in einem Browser mit WebGL 2 öffnen. Es gibt keine CDN- oder Netzwerkbibliothek.
`--serve` stellt sie ausschließlich auf `127.0.0.1:8765` bereit;
`--port` ändert den Port. Vorhandene Revisionen werden erhalten.

## Bedienung

- Die sieben Ortsknöpfe öffnen die jeweiligen Blickpunkte.
- Der Ortstitel bezeichnet den zuletzt gewählten Blickpunkt; freies Gehen
  schaltet diese Beschriftung nicht automatisch auf den betretenen Raum um.
- **W / ↑** gehen vorwärts, **S / ↓** rückwärts. **← / →** drehen die
  Blickrichtung, wie bei der klassischen Doom-Steuerung.
- **Alt + ← / →** bewegen die Kamera seitwärts (Strafing); auf dem Mac heißt
  die Taste **Option / ⌥**. **A / D** erlauben dieselbe Seitwärtsbewegung direkt.
  Alt kann auch während einer gehaltenen Pfeiltaste gedrückt oder losgelassen
  werden; die Steuerung wechselt unmittelbar zwischen Drehen und Seitwärtsgehen.
- **Ziehen** mit Maus oder Finger ändert weiterhin die Blickrichtung.
- **Q / E** bewegen die Kamera senkrecht; **Shift** beschleunigt das Gehen.
- Die Bildschirmknöpfe verschieben die Kamera auch auf Touchgeräten; zum
  Umschauen ziehen. Die seitlichen Knöpfe sind als „Strafe left/right“ bezeichnet.
- In Eingabefeldern und der Geschossauswahl steuern die Tasten die jeweiligen
  Bedienelemente. **Ctrl / Command**-Tastenkürzel bleiben dem Browser überlassen;
  Fokusverlust oder ein ausgeblendeter Tab beendet gehaltene Kamerabewegungen.
- Die Geschossauswahl ändert die Kamerahöhe im Gebäude. „Return to viewpoint“
  setzt den aktuellen Blickpunkt zurück; Vollbild vergrößert die Ansicht.

Der Weghinweis am Blickpunkt **Doktorandenraum 3.002** führt rückwärts in
den Flur und nach rechts zur ersten Tür mit dem Schild **3.003 Labor**. Dort
führt `D3_003B` direkt ins ausgestattete Labor. Wer im Flur weiter zur zweiten
Labortür oder zum Aufzug geht, kann außen um die Spitze des geöffneten Blatts
herumgehen. Der Laufwegtest leitet den Umweg aus der nativen Türkante und der
gegenüberliegenden Flurwand ab. Türstellung und Kameraabstand gelten auf
beiden Wegen.

Die Ortsknöpfe sind Blickpunktwechsel, keine berechneten Gehwege. Freie
Verschiebungen verwenden die oben beschriebene Kamerakugel-Prüfung an den
nativen Flächen. Sie ist keine menschliche Körperhülle und kein Nachweis
realer Begehbarkeit.

## Gemeinsame Gebäudeszene und Laborbindung

[`model/building-walkthrough.shared.json`](../model/building-walkthrough.shared.json)
referenziert die Gebäudekomposition. Deren optionale Quelle
[`model/furnishings/building-laboratories.json`](../model/furnishings/building-laboratories.json)
bindet `Lab3003` an `OG3` / `R3_003`, Eingangswand `W036`, und die gepinnten
L01-Raum- und Layoutdefinitionen. Sie enthält keine kopierten Maße oder
Gerätepositionen. Die Raumkameras
werden aus Raumflächen und tatsächlichen Türöffnungen berechnet. Der
Atriumblick bindet die vorhandene offene Geländerkante an den Flur. Der Blick
in den Kernbereich wird aus seinem offenen Zugang am Flur `C3_021` abgeleitet. Die
Kameraparameter haben explizite mm-, Sekunden- beziehungsweise Gradbezüge.
Der Compiler `scripts/building_walkthrough.py` benötigt kein CAD.

Der Doktorandenraum blickt von der Flurtür zum Fensterende. Der Küchenblick
blickt ebenfalls vom Eingangsbereich zum äußeren Fenster. Die Küche 1.008
fasst im 1. OG die Vorlagenflächen `R3_008A`, `R3_008B` und `R3_009` zusammen;
die frühere hintere Büroabtrennung entfällt dort. Die Tische und die gemeinsam
verschobene Küchenanordnung sind an das Fenster der Quellwand `W005`
gebunden. Der nominale Tisch-/Wandabstand von 100 mm wird einmal mit der
Darstellungseinpassung skaliert. Die Eingangssituation soll den Schrankzugang
frei halten; ein realer Türschwenkweg wird durch den Blickpunkt nicht geprüft.
Raumgröße und Möbeleinpassung bleiben ungemessene Darstellungsannahmen.

Alle sieben Blickpunkte verwenden dieselbe Gebäudeszene. Der Laborblick wird
wie die anderen Raumblicke an einer tatsächlichen Eingangstür berechnet.
Vom Doktorandenraum führt die Darstellung über `D3_002N`, den gemeinsamen
Flur und `D3_003A` oder `D3_003B` in das ausgestattete Labor; dafür ist kein
Szenenwechsel nötig. „Labor isoliert anzeigen“ filtert dieselben Körper im
selben Koordinatenrahmen und ergänzt die zugehörige Gebäudehülle von `R3_003`.
Die isolierte Standalone-L01-Fassung für Ablauftests bleibt zusätzlich erhalten.

`scripts/building_laboratories.py` leitet Breite, linke und rechte Tiefe sowie
Fassadenwölbung aus den Innenflächen des Zielraums ab. Jede Wand wird um die
halbe Darstellungswandstärke eingerückt; die Wölbung folgt dem Mittelpunkt der
hinteren Polylinie. Mit diesen unabhängigen Parametern wertet der Compiler die
bestehenden L01-Rezepte erneut aus. Die Transformation folgt der Eingangswand,
der inneren linken Eingangsecke beim Blick zum Fenster und der OG3-Höhe.
Möbel und Geräte behalten Maßstab 1. Das Gebäude liefert Boden, Wände, Türen
und Verglasung; die entsprechenden L01-Hüllrollen werden nicht dupliziert.

Die neue Gebäude-CAD-Fassung enthält die 183 gebundenen Möbel-/Strukturkörper.
Die 17 Geräteinstanzen werden nur im Browser aus dem geprüften vollständigen
Standalone-L01-Layout übernommen. Je Instanz gilt die starre Abbildung
`Gebäude · gebundene Pose · Standalone-Pose⁻¹`; Normalen und Grenzen folgen
derselben Abbildung. Die drei funktionalen Arm-Unterbauten werden aus derselben Layoutquelle mitgeführt.
Studienkörper `People_*` und Fahrzeugrouten entfallen.
Native Geräte im Gebäude-CAD sind weiterhin fehlende Zielunterstützung.

Die Fassadenpolylinie und die quadratische L01-Näherung stimmen nicht exakt
überein. Ihr Bericht berechnet die maximale lokale Y-Differenz einschließlich der
Extremstellen jedes Segmentes analytisch; aktuell sind es rund 52
Darstellungs-mm. Die Möbelprüfung verwendet ausdrücklich die halbe
Wandstärke als Toleranz. Die aus L01 übernommene Betonstütze ist nicht im
F03-Plan belegt und bleibt eine offene Eigentümerentscheidung. Dasselbe gilt
für die praktische Eignung des nur rund 904 mm breiten Fensterdurchgangs.
Aufmaß, reale Kollisionsfreiheit und `lab_to_building_registered` bleiben
ungeprüft beziehungsweise `false`.

Die drei Hocker sind über feste Bruchteile ihrer Fensterbankabschnitte an
deren tatsächliche Vorderkante gebunden. X und Y verwenden dieselbe
Interpolation; damit bleiben die nativen FreeCAD-Ausdrücke linear. Alle
Standardkörper, Operationen, Rahmen und Gelenke bleiben numerisch gegenüber
der bisherigen L01-Fassung erhalten. Der separate abgeleitete
`l01-default-equivalence.json` weist diese Prüfung samt Toleranz aus.

Das Gebäude-Interface führt benannte Laborarbeitsflächen, Rackplätze aus den
vorhandenen Kassettenteilen und die Tischplatten der Büro-Desktoprezepte im
Gebäudebezug. Der Türgraph liefert die Verbindung Büro–Flur–Labor getrennt von
der Geometrie. Das sind Voraussetzungen für spätere Materialtransfers; T2/T3,
logische Endpunkte und Transporterbahnen werden dadurch nicht angebunden.

Im Doktorandenraum 3.002 bilden die Tischplatten an beiden Längsseiten und vor
dem Fenster eine durchgehende U-förmige Arbeitsfläche mit Wandkontakt. Die
Glastür zu Labor **3.001** liegt beim Blick vom Flureingang zum Fenster links;
ihre Öffnung bleibt frei. Die frühere rechte Verbindung zu 3.003 ist in dieser
Geschossvariante geschlossen. Der Erste-Hilfe-Kasten ist rechts innen neben
der Flurtür verankert. Diese Anordnung folgt der Nutzerbeschreibung;
Abmessungen und Möbelhöhen sind weiterhin Darstellannahmen. Die übrigen
Doktorandenräume behalten ihre bisherige Möblierung.

Der [Kernbereich am Atrium](atrium-seating.md) liegt in der unnummerierten
Fläche `NorthCore`, gegenüber von 3.002 auf der anderen Seite des Atriums.
Er enthält im 1., 2. und 3. OG jeweils einen weißen elliptischen Tisch mit vier
Stühlen. Zugang und Geländer beziehen sich auf `W063` und `W065`.
Die Toilettenseite `R3_011` / `R3_012` / `CoreGap` bleibt wie gezeichnet;
die frühere Platzierung dort wurde zurückgenommen. Die Küche 1.008 bleibt auf
der Küchenseite des Gebäudes und wird innerhalb ihres erweiterten Raumbereichs
zum Außenfenster ausgerichtet. EG und Keller erhalten keine weiteren Sitzgruppen.

## GitHub-README und Bereitstellung

Das anklickbare Vorschaubild im [README](../README.md#interaktiver-gebäuderundgang)
öffnet den [öffentlichen Rundgang](https://smoe.github.io/DIYLabBot/).
Direkt im README führt GitHub ihren Renderer nicht aus:
Die [GFM-Regeln](https://github.github.com/gfm/#disallowed-raw-html-extension-)
filtern unter anderem `script` und `iframe`. Ein öffentlicher Rundgang benötigt
deshalb eine separat gehostete HTML-Datei. [GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)
kann die statische Datei samt JavaScript bereitstellen. Der erste Aufruf lädt
etwa 37 MB; ein Browser mit WebGL 2 ist erforderlich. Der lokale
`127.0.0.1`-Link bleibt ausschließlich auf dem Rechner des lokalen Servers erreichbar.

Die Veröffentlichung verwendet den separaten Branch `gh-pages` mit dessen
Wurzelverzeichnis als Pages-Quelle. Dort liegen die unveränderte geprüfte
`index.html`, `.nojekyll` und eine abgeleitete `site-manifest.json` mit
Quellrevision, HTML-Prüfsumme und Bezug auf den Browsernachweis. Die
Konstruktionsquellen bleiben auf `master`; der Veröffentlichungsbranch enthält
eine erzeugte Momentaufnahme und keine zweite führende Modellquelle.

Zur Aktualisierung den Rundgang wie oben neu erzeugen und mit der unten
genannten Browserprüfung prüfen. Anschließend in einer separaten Arbeitskopie
von `gh-pages` die HTML-Datei und das Publikationsmanifest ersetzen und
committen. Erst nach ausdrücklicher Freigabe normal nach `origin/gh-pages` pushen. Der Push löst die Pages-Bereitstellung
aus. Erst nach erfolgreichem Deployment die öffentliche Seite prüfen; ein
lokaler Export allein veröffentlicht nichts. Andere Änderungen an `master`
erneuern den veröffentlichten Rundgang nicht automatisch.

Vor und nach einer Veröffentlichung prüft der folgende Befehl HTML-Prüfsumme,
Quellenpins, aktuelle Objektbindungen und vollständige Gebäude-Körperabdeckung:

```sh
python3 scripts/check_walkthrough_publication.py /pfad/zur/gh-pages-arbeitskopie
python3 scripts/check_walkthrough_publication.py https://smoe.github.io/DIYLabBot/
```

Er weist auch eine intern korrekt signierte, aber veraltete Momentaufnahme
zurück. Die GitHub-Actions-Prüfung `Walkthrough regressions` führt die
Quell-, Arbeitsplatz-, Artikulations- und Publikationsvertragstests bei
relevanten Änderungen aus. Die tatsächliche Browserbedienung bleibt eine
separate Prüfung des erzeugten nativen Rundgangs mit
`tests/check_building_walkthrough.cjs`; die Quellenprüfung allein belegt keine
erfolgreiche Pages-Bereitstellung.

Die CI installiert die Schema-Prüfer aus
`requirements/walkthrough-test.lock` mit verpflichtenden Paketprüfsummen.
Sie erzeugt die vollständige L01-Aufstellung mit dem unabhängigen FreeCAD-Backend
neu, bevor sie Rackplatzrahmen gegen die nativen Gefäßmittelpunkte und Basis-Z-Werte
prüft. Die Linux-Laufzeit ist die offizielle
[FreeCAD-1.1.4-AppImage](https://github.com/FreeCAD/FreeCAD/releases/tag/1.1.4) mit fester
SHA-256-Prüfsumme; sie wird ohne FUSE entpackt. Ein fehlendes Paket, ein fehlender
oder veralteter nativer Bericht und ein unerwarteter Test-Skip lassen den Job
fehlschlagen. Die lokalen optionalen Testaufrufe behalten ihr bisheriges Verhalten.

Der strenge Teststarter lässt sich auch lokal verwenden:

```sh
python3 -m pip install --require-hashes -r requirements/walkthrough-test.lock
python3 scripts/build_lab_layout.py --backend freecad
python3 scripts/check_walkthrough_regressions.py --pattern test_building_laboratories.py --report exports/ci/walkthrough/building_laboratories.json
```

CI-Artefakte halten Testzahlen, den nativen Bericht, die geometrische Auswertung
und die erzeugte FCStd-Datei sieben Tage fest. Der neue Aufbau belegt FreeCAD
und die jeweils ausgeführten geometrischen Prüfungen; ein CAD-Vergleich mit
SolidCraft, WebGL-/Browserbedienung, öffentliche HTTPS-Bereitstellung, reale
Begehbarkeit, Hardware und Sicherheit bleiben separate Nachweise. Dieser Job
veröffentlicht weder neue README-Medien noch einen neuen Pages-Rundgang.

## Nachweise

**Integration mit dem aktuellen `master` am 16. November 2026:**
Der neu erzeugte FreeCAD-Stand `building-stack-0dfc62c4a318` besteht mit
2.362 geschlossenen Körpern, 509 Geometrieprüfungen und 16 Höhenprüfungen.
Er erhält die inzwischen ergänzten Büro-PCs, Küchengeräte und Treppengeländer.
Die Aufstellung `lab-layout-l01-953a32f28782` verwendet die aktuellen
Armkameras und besteht beide CADs mit 884 Körpern. Sämtliche Aufstellungs-,
Zugangs- und Kollisionsprüfungen sowie die 33 Routenstichproben bestehen.
Auch die vorher mangels aktuellen Berichts ausgelassene Rackplatzprüfung
besteht nach diesem Aufbau; alle 154 gezielten Quelltests sind damit geprüft.
Die Quellenprüfung für Pages erfasst zusätzlich zur Gebäudehülle alle
17 gebundenen Geräte, drei Arm-Unterbauten und den Labor-/Aufzugvertrag.
Der daraus erzeugte Rundgang `building-walkthrough-177026299fe0` enthält
3.045 native Körpergruppen und 730.771 Dreiecke in einem Gebäudebezug.
Die vollständige Chrome-/Metal-Prüfung besteht alle fünf Blickpunkte, den
öffentlichen Büro–Flur–Labor-Weg, Laborfilter, Schranktür und Hockerlift sowie
die Aufzug-Rundfahrt einschließlich Kameramitnahme und Ausstiegsregeln.
Auch Kühlschrank, Mikrowelle und die vollständigen 13 PC-Instanzen bleiben
geprüft. `browser-evidence.json` bindet den Rohbericht, HTML, Prüfsystem und
17 Bildschirmbilder. Die drei betroffenen Galerierecords wurden erneuert;
das Bildbudget beträgt 3.957.511 Bytes. Der bereits auf `master` vorhandene
globale Galeriefehler wegen historischer Robot-Abhängigkeiten bleibt offen.

**Ursprünglicher Prüfstand der Labor-/Aufzugerweiterung in `1bf1d77`:**
`building-stack-2b9b9a5b1e10-r2` besteht den nativen FreeCAD-Aufbau mit 2.121
geschlossenen Körpern, 452 Geometrieprüfungen und 16 Höhenprüfungen. Der
Standalone-Raum `lab-room-l01-8827f0e318a4` besteht fünf Varianten in beiden
CADs sowie drei native Parameteränderungen; die STEP-Volumendifferenz ist 0.
Die vollständige Aufstellung `lab-layout-l01-991a9ba9534d` besteht beide CADs
mit 878 FreeCAD-Körpern und den bisherigen Aufstellungsprüfungen.

Der Rundgang `building-walkthrough-d0fca19566f3` enthält 2.798 native
Körpergruppen und 727.735 Dreiecke in einem Gebäudebezug. Alle 17 Geräte und
drei Arm-Unterbauten sind vollständig übernommen. Die native Begrenzungsprüfung
der Geräte bleibt innerhalb des Zielraums; der kleinste Abstand beträgt 20 mm.
Die 72 Rackplatzrahmen stimmen mit den nativen Tube-Mittelpunkten und Basis-Z-
Werten überein. Die numerische Standard-L01-Abweichung liegt unter `1e-9` mm.
Die vollständige Prüfung in Chrome 157 mit dem Metal-Backend des lokalen Macs
besteht. Sie führt über öffentliche Tasten vom Büro durch den Flur ins Labor,
prüft den Kameraverlauf gegen native Bodenflächen und beide Türöffnungen und
bedient eine Schranktür sowie den 200-mm-Hockerlift. Laborfilter, Kühlschrank,
mobile Oberfläche und Fehleranzeige bestehen ebenfalls. Der Aufzug besteht
die zeitgeführte Fahrt OG3–EG–OG3 einschließlich Zwischenbild mit absoluter
Kameramitnahme, `rejected_busy` und der Ausstiegsregeln für EG, OG und KG.
`browser-check.json` enthält den Rohbericht; `browser-evidence.json` bindet
dessen unveränderte Bytes, HTML, ausgeführtes Prüfsystem und 15 geprüfte Bilder.

Ein neuer vollständiger SolidCraft-Gebäudeaufbau wurde für diese Erweiterung
ausgelassen; der unabhängige SolidCraft-Nachweis gilt hier für Standalone-L01.
Historische Medien und die folgenden Berichte bleiben ihren eigenen Revisionen
zugeordnet und belegen diese Erweiterung nicht.

143 gezielte Offline-Prüfungen einschließlich der neuen Schemas bestehen ohne
Überspringen. Der zusätzlich ausgeführte Gesamtlauf umfasst 2.340 Tests und
ist nicht vollständig grün. Nach gezielten Wiederholungen mit den gesperrten
Testabhängigkeiten, vollständigen Geräte-Cachedateien und lokalen Netzwerkrechten
verbleiben drei bereits auf der Ausgangsbasis fehlschlagende historische
Medienprüfungen, eine dort ebenfalls fehlerhafte synthetische Flur-Fixture und
drei Testklassen ohne aktuellen nativen Verkehrs-/Übergabenachweis. Deren alte
Quellpins werden nicht als neuer Nachweis umgeschrieben. Neue Transportbahnen
und deren Nachweiskette sind separate Folgearbeit. Netzwerk-/SDK-Prüfungen,
die im Gesamtlauf übersprungen wurden, gelten weiterhin nicht als bestanden.

Die bestätigte Lage im Kernbereich und die erweiterte Küche am Fenster sind
im Export `building-walkthrough-987112e02766` an den vollständig geprüften
FreeCAD-Stand `building-stack-ecc15e1b9dd9` gebunden. Alle fünf Blickpunkte,
Bewegungssteuerung, mobile Darstellung und Fehleranzeige bestehen die neue
Chrome-Prüfung. Deren Mesh-Prüfung bestätigt zusätzlich die Sitzgruppe innerhalb
von `NorthCore`, die weiße Tischplatte, erhaltene Toilettenwände/-türen,
entfernte OG1-Küchenpartitionen und das nur in OG1 ergänzte Außenfenster.
Die älteren Rundgänge der Stände
`5406a30fc113` / `6dbc248fae3b` zeigen die zurückgenommene falsche Platzierung
auf der Toilettenseite und sind kein Nachweis für diese Korrektur.

Der Exporter `scripts/export_building_walkthrough_freecad.py` liest die finalen
nativen BRep-Flächen. Der Build-Bericht bindet Quellen, native Artefakte,
Tessellationstoleranzen, sämtliche Körper-IDs, Dreiecksanzahlen und die
Float32-Konvertierungsabweichung. Der semantische blaue `ConceptExchange`-Marker
bleibt im Mesh erhalten und wird nur in dieser Ansicht ausgeblendet.

Die Rundgangquelle setzt die beiden semantischen Wandrollen
`concept_storey_wall` und `circulation_wall_bridge` für Innenansichten auf
deckend. Ihre native CAD-Darstellung ist für Außenübersichten transparent.
Die ursprünglichen Materialwerte bleiben im Mesh erhalten; Glas und alle
anderen Materialien behalten ihre native Transparenz.

```bash
python3 -m unittest discover -s tests -p 'test_building_walkthrough*.py' -v
node tests/check_building_walkthrough.cjs exports/building-walkthrough/<Revision>/index.html
```

Für die lokale Mac-Prüfung lässt sich mit
`SOLIDCRAFTBOT_WALKTHROUGH_GPU=metal` die tatsächliche Grafikbeschleunigung
verwenden. Ohne Auswahl bleibt die portable Softwaredarstellung eingestellt;
der Bericht nennt das tatsächlich verwendete Backend.

Die Browserprüfung erzeugt neben dem HTML einen separaten `browser-check.json`
und Screenshots der Blickpunkte. Sie prüft tatsächliches WebGL-Zeichnen,
Tastatur-/Zeigerbedienung, die Geschossauswahl, die mobile Ansicht und die
Fehleranzeige. Der CAD-/HTML-Build allein ist noch kein Browsernachweis.
Statische Geometrie, Browserbedienung und reale Begehbarkeit bleiben getrennte
Nachweise; der Rundgang qualifiziert keine Fluchtwege oder Roboterbewegungen.

Die Doom-artige Kamerasteuerung besitzt außerdem eine gezielte Browserprüfung:

```bash
node tests/check_walkthrough_controls_browser.cjs exports/building-walkthrough/<Revision>/index.html
```

Für die Prüfung der öffentlichen Seite kann nach dem lokalen HTML, dem
Playwright-Modul, dem Chrome-Pfad und dem Ausgabeordner zusätzlich eine
HTTPS-URL übergeben werden. Der Test öffnet dann diese Seite tatsächlich im
Browser und vergleicht ihre Antwortbytes mit dem geprüften lokalen HTML.

Die Prüfung erfasst Drehen, Seitwärtsgehen, während des Haltens wechselnde Modifikatortasten,
unabhängiges Loslassen mehrerer Tasten, Eingabefokus, Browserkurzbefehle und die
Kamerabindung im Aufzug an der tatsächlichen exportierten Szene.
`browser-controls-report.json` und ein Screenshot entstehen im ignorierten
Exportverzeichnis. Ein kurzer Test mit realen Animationsframes wird durch
kontrollierte Browser-Testzeit ergänzt; daraus folgt kein Echtzeit-Leistungsnachweis.
Eine vom Testbrowser nicht herstellbare Tab-Ausblendung wird ausdrücklich als
ungeprüft ausgewiesen. Diese Bedienprüfung ersetzt keine vollständige erneute
Geometrie-, Kollisions-, Aufzugs- oder Sicherheitsqualifikation.

## Typweite Möbelbefehle

Bewegliche Türen werden direkt im 3D-Bild bedient: **mit der Maus auf das
Türblatt oder den Griff klicken**, um sie zu öffnen oder zu schließen.
Alternativ vor die Tür gehen, die Öffnung mit dem Fadenkreuz ansehen und
**Leertaste** drücken. Die Leertaste bedient auch eine bereits offene Tür
an ihrer ursprünglichen Öffnung. Es gibt keine Objekt-Tastenzeile mehr.
Ziehen mit der Maus dreht weiterhin nur die Kamera; Halten der Leertaste
löst keinen wiederholten Wechsel aus. Normale Bedienelemente wie die
Geschossauswahl behalten ihre Tastaturbedienung.

Ein Hinweis am Fadenkreuz zeigt das erreichbare Objekt, seinen Zustand und
die nächste Aktion. Die Reichweite beträgt zunächst **2.500 Darstellungs-mm**
und ist als ungemessene Annahme in der Rundgangquelle gebunden. Auswahl und
Verdeckung werden an den tatsächlichen nativen Dreiecksflächen geprüft,
auch an gedrehten Türblättern. Eine nähere sichtbare Wand blockiert die
Bedienung dahinter. Dies ist eine visuelle Interaktionsprüfung, keine
Kollisions- oder Wegefreigabe.

Die gemeinsame Auswahlroutine `scripts/walkthrough_interaction.js` unterstützt
alle im Rundgang deklarierten beweglichen Objekte und wird ohne externe
Bibliothek in das eigenständige HTML eingebettet. Alle platzierten Instanzen
eines artikulierten Sozialmöbeltyps (einschließlich Kühlschrank und Mikrowelle
1.008) erhalten ihre Bedienung automatisch aus
`model/furniture/social.articulations.json`. Im Labor stammen die 31
Schranktürgelenke und drei Hockerlifte direkt aus den gebundenen Möbelrezepten.
Die Hockerlifte verwenden prismatische Gelenke und die typspezifischen
Heben-/Senken-Befehle. Auch alle vorhandenen Raumtüren der Gebäudehülle lassen
sich öffnen und schließen, einschließlich der Stahltüren im Keller. Blatt,
Guckfenster und Ringe bewegen sich gemeinsam um den vorhandenen Anschlag.
Die [Geräte- und Aufzugbedienung](building-walkthrough.md#merged-walkthrough-mechanisms) ergänzt Gefrierschubladen,
Abzug, Qubit, NanoDrop und automatisch betätigte Aufzugtüren. Die Kamera-Hilfe `viewObject` bleibt
nur in der Test-API und hat keine Taste in der Oberfläche.

Blickpunkt- und Geschosswechsel sowie der Laborfilter erhalten die
Türstellung während dieser Sitzung; ein Neuladen setzt die Referenzstellung.

Tür und Griff drehen gemeinsam, der vorhandene Pinguin, seine Tasse,
Innenböden und Kühlschrankhülle bleiben unverändert. Ein Objektbefehl gibt
`accepted`, `already_in_state`, `rejected_busy` oder `unknown_target` zurück.
Während einer Bewegung werden weitere Bewegungsbefehle abgewiesen. Es gibt
keine Warteschlange oder automatische Umplanung.

Die zusätzliche Quelle `model/furniture/social.articulations.json` referenziert
den Möbelkatalog und benennt Teile und Scharnierkante ohne
kopierte Abmessungen. `scripts/furniture_articulation.py` leitet den Rahmen aus
der platzierten Tür-Prismenoperation ab. Beschriftungen, Zustandsnamen und Darstellparameter stehen auf Typ- oder
Artikulationsebene, ohne Eintrag je Möbelinstanz. Die Objektkennung bleibt
`<Raum>.<Instanz>.<Gelenk>`; `Kitchen1008.Fridge.Door` behält seine Kennung und
Bedienung. Quellgeometrie, bewegte Körper und die Weltachsen werden gemeinsam
geprüft, bevor das Objekt in den Renderer gelangt.

Die Scharnierkante bei lokal kleinstem X und größtem Y entspricht einem
rechten Anschlag beim Blick von vorn auf die Tür; diese Seite ist weiterhin
eine Darstellungsannahme. Dasselbe gilt für **90 Grad**, **1,2 Sekunden** und
**2.000 mm Blickabstand** im Gebäudedarstellungsrahmen. Die zunächst gewählten
900 mm ließen aus stehender Augenhöhe hauptsächlich den Fachboden erkennen;
3.000 mm lägen außerhalb der Küchenflächen und werden vom Compiler abgewiesen.
2.000 mm liegen innerhalb der Küche. Der mittlere Fachboden verdeckt weiterhin
Teile des Pinguins, insbesondere den Kopf. Die Pixelprüfung verwendet einen
festen Punkt auf der schwarzen unteren Körperflanke und vergleicht dort die
helle geschlossene Tür mit dem geöffnet sichtbaren dunklen Körper. Für einen
niedrigeren freien Blick kann die vorhandene Kamerasteuerung Q verwendet werden.

Die Browserbewegung nutzt absolute Zeit und das weiche Profil
`10u³ − 15u⁴ + 6u⁵`. Bei reduzierter Bewegung wird direkt die Endstellung
angezeigt. Ein verborgener Tab verlängert die modellierte Bewegung nicht.
Positionen und Normalen der vorhandenen Meshgruppen werden gemeinsam
gedreht beziehungsweise bei prismatischen Gelenken verschoben;
bei der Referenzstellung ist die Modellmatrix exakt die Einheitsmatrix.

Nur der Browser besitzt diese Artikulation. FreeCAD und SolidCraft enthalten
weiter die **geschlossene Referenzstellung**, keine nativen Gebäudegelenke.
Reale Scharniere, vollständige Sichtbarkeit aus jeder Perspektive, Kollisionen,
Schwenkraum und Roboterbefehle sind damit nicht qualifiziert. Die
Gebäude-Raumtürblätter bleiben statisch. Für diese erste Erweiterung werden keine Daten gespeichert
und keine Hardware-, ROS- oder SiLA-Befehle verschickt.

Die vorhandenen Möbelbilder und ihre ursprüngliche Provenienz bleiben erhalten.
`docs/building-furnishings-media-compatibility.json` bindet die eng begrenzten
Änderungen der Browserquellen an die unveränderten Kameras und Bildbytes.
Dieser Kompatibilitätsnachweis ist weder ein erneutes Rendern der historischen
Bilder noch eine zusätzliche CAD- oder Bewegungsqualifikation. Die neuen
Objektbefehle werden davon getrennt mit der tatsächlichen Browserprüfung geprüft.


## Aufzug benutzen

Der Aufzug bleibt eine einzelne Kabine der vorhandenen Quelle `BuildingLift`.
Am aktiven Geschossrahmen und am modellierten Ruftaster ruft ein Klick oder
die Leertaste die Kabine. Nach vollständiger Türöffnung kann man mit den
normalen Bewegungstasten hinein- und wieder hinausgehen. Die Kameraposition
bleibt beim Überqueren der Schwelle erhalten. Das Overlay bietet ergänzend
Ruf, Geschosswahl und die bisherigen direkten Ein-/Ausstiegshilfen.
Die fünf physischen Kabinentasten tragen K, E, 1, 2, 3 und sind anklickbar.
Sie sitzen zusammen mit der Anzeige auf der rechten Seitenwand, wenn man
vom Obergeschoss aus eintritt, nahe diesem Eingang. Der obere Handlauf
endet mit 50 mm angenommenem Freiraum vor der Tafel; der untere läuft darunter
weiter. Die äußeren Anzeigen und Ruftaster behalten ihre Positionen.
Eine rote LED-Matrix in der Kabine und je eine am aktiven Zugang jedes
Geschosses zeigen synchron das der aktuellen Kabinenhöhe nächstgelegene
Geschoss. Schachttaster und Anzeigen bleiben am Gebäude, die Kabinentafel
fährt mit. Die Dimensionen bleiben ausdrücklich Darstellungsannahmen.
KG und EG erlauben nur den inneren Ausgang, auf der Seite ohne Bedienpanel;
die Obergeschosse nur den äußeren Ausgang. Halte, Höhen und aktive Seiten stammen aus
`interface.circulation.elevator`, nicht aus einer zweiten Geschossliste.

Die Kabine und die eingestiegene Kamera bewegen sich gemeinsam. Die Kamera
wird nach jeder Objektaktualisierung absolut an den Kabinenzustand gebunden;
es werden keine kleinen Höhenänderungen aufsummiert. In der geöffneten,
angedockten Kabine ist horizontales Gehen möglich. Während Türbewegung und
Fahrt bleibt Translation gesperrt; Umschauen bleibt möglich. Q/E, freie
Geschossauswahl, Ortsknöpfe und Laborisolation bleiben an Bord gesperrt.
Gehen über die aktive Ausgangsschwelle löst die Kamerabindung. Der Schacht
bleibt außerhalb der angedockten Kabine und ihrer offenen Türöffnung
gesperrt. Eine belegte Türschwelle verhindert den Fahrbefehl. Weitere Befehle während
einer Fahrt liefern `rejected_busy`; es gibt keine automatische Warteschlange.

Die Weglänge bestimmt die Dauer. Mit dem glatten Profil
`10u³ − 15u⁴ + 6u⁵` und der deklarierten Spitzen-Geschwindigkeitsannahme von
1.200 Darstellungs-mm/s gilt `Dauer = 1,875 · Weg / Geschwindigkeit`.
Bei reduzierter Bewegung wird unmittelbar die Zielstellung angezeigt. Die
unveränderte native Kabine steht in der EG-Referenz; dort ist ihre
Darstellungsmatrix exakt die Einheitsmatrix. In anderen Geschossen wird nur
diese Kabine verschoben, während Schacht, Geschossrahmen und Nachbarkörper
stehen bleiben. Die geschlossene innere Schachtwand bleibt in den
Obergeschossen erhalten, obwohl die EG-Kabine zwei Öffnungen besitzt.

Die verschiebbaren Kabinen- und Schachttüren schließen vor der Fahrt und
öffnen erst nach der Ankunft auf der aktiven Seite. Edelstahloberflächen,
Handläufe und Tastenreihe folgen den Eigentümerfotos; Maße sind angenommen.
Kabinen- und geschossfeste Metallschwellen verkleinern den bisherigen großen
Spalt auf angenommene 8 mm; die 3-mm-Oberkante folgt dem Kabinenbodenbelag.
Das ist kein vollständiger Bodenstützungsnachweis für BF01: dessen Kurven,
Unterstützungsflächen und native Abstände müssen am neuen Stand neu geprüft werden.
Eine reale Steuerung oder Schutzfunktion wird nicht implementiert.
`lift_operation_implemented` bleibt `false`; die Browserfahrt ist keine
mechanische, zeitliche oder sicherheitstechnische Aufzugsqualifikation.

Die Geh-/Bedienprüfung `tests/check_walkthrough_lift_walking_browser.cjs`
verwendet echte Maus- und Tastaturereignisse am vollständigen nativen Export:
Einsteigen ohne Positionssprung, Fahrwahl über die modellierten Tasten,
gesperrte Translation während der Fahrt, Aussteigen an allen fünf Geschossen
und die tatsächlich gerenderten LED-Pixel. Eine belegte Schwelle und ein
Geschoss ohne Kabine werden als gesperrte Fälle geprüft. Die Testuhr wird
kontrolliert; daraus folgt kein Echtzeitnachweis.

Der lokale Stand `exports/building-walkthrough/building-walkthrough-13815e6fde24/`
enthält diesen Browsernachweis. Der vollständige FreeCAD-Bau
`exports/generated/building-stack-ac608f8fdeff/build-report.json` prüft
4.616 geschlossene Körper, 509 Bereichsprüfungen und 32 Höhenprüfungen.
`exports/lift-walkthrough/native-lift-validation.json` vergleicht unabhängig
245 Aufzugkörper in SolidCraft und FreeCAD, einschließlich der 8-mm-Spalte
an allen fünf Zugängen. Dies ist kein vollständiger SolidCraft-Gebäudenachweis.
Der aktuelle BF01-Schwellenvorlauf findet dort die neue Landeschwelle;
sein Ergebnis bleibt `unproven`, also keine Freigabe für eine Roboterfahrt.

Die anschließende Seitenwandkorrektur wird durch
`exports/generated/building-stack-1b1aa4eb058a/build-report.json` und
`exports/lift-side-panel/native-lift-validation.json` belegt. Die 245
Aufzugkörper stimmen in FreeCAD und SolidCraft überein. 792 Prüfungen der
konservativen Körpergrenzen über die vollständigen linearen Kabinentürhübe
zeigen Abstand zu Panel, Telefon und Handläufen. Der obere Handlauf hält
die angenommenen 50 mm zum Panel ein; alle 95 Körper der äußeren Anzeigen
und Ruftaster bleiben geometrisch unverändert.
Der Browsernachweis unter
`exports/building-walkthrough/building-walkthrough-732b237ba8fe/` prüft
alle fünf physischen Geschosstasten, die LED-Pixel und Ein-/Aussteigen
mit 271 Gehschritten ohne Browserfehler.

Dabei bleibt die vorhandene Kellertür `KG.DK015.Door` ausdrücklich geschlossen:
ihr im Altmodell etwa 2,8 m langes offenes Blatt ragt in die Kabine und verdeckt
die neue Anzeige. Diese unveränderte Raumtürgeometrie benötigt eine separate
Grundriss-/Türkorrektur. Der Browserbericht benennt die geschlossene Stellung;
die Aufzugprüfungen sind kein Freiraumnachweis gegenüber dieser Kellertür.
Die zusätzliche vollständige Prüfung `tests/check_building_walkthrough.cjs`
bestand die nativen Bindungen, sieben Ansichten sowie Kühlgeräte-/Bewegungsfälle,
lief dann jedoch auf dem Gangweg vom Büro zum Labor in einen 180-s-Timeout.
`exports/lift-side-panel/walkthrough-browser.log` hält diesen Fehler fest;
ein bestandener Gesamtrundgang wird für diese Korrektur nicht behauptet.

<a id="merged-walkthrough-mechanisms"></a>

<a id="merged-walkthrough-mechanisms--türen-und-geräte-im-gebäuderundgang"></a>

## Türen und Geräte im Gebäuderundgang

Ein Klick auf eine nahe Tür, Klappe oder einen Griff öffnet beziehungsweise
schließt das Teil. Alternativ darauf blicken und die Leertaste drücken.
Die Leertaste erreicht auch die geschlossene Fläche, wenn das Blatt bereits
weggeschwenkt ist. Davorliegende Körper sperren den Zugriff weiterhin.
Die Reichweite bleibt der gemeinsame Rundgangparameter.

Die Bedienung umfasst alle 139 vorhandenen Raumtüren auf KG, EG und OG1–OG3.
Fensterlose Holz- und Stahlblätter, runde Guckfenster samt Ringen und das
Glastürblatt behalten ihre bestehenden Körper und Materialien.

In Labor 3.003 sind zusätzlich bedienbar:

- Gefrierschranktür und alle sechs Schubladen;
- die vertikal verschiebbare Abzugsscheibe und drei Unterschrankklappen;
- der Qubit-Deckel und der NanoDrop-Hebel.

Die Gefrierschranktür schließt erst, wenn jede Schublade vollständig
eingeschoben ist und ihre Bewegung beendet hat. Eine Schublade lässt sich
erst bei vollständig geöffneter Tür ausziehen. Gleichzeitig eintreffende
Befehle prüfen aktuelle Stellung, Zielstellung und laufende Bewegung.
Eine gesperrte Betätigung meldet die betroffenen Teile und die benötigte
Stellung. Der geschlossene Schrank lässt sich über sein Türblatt oder seinen
Griff wieder öffnen.

<a id="merged-walkthrough-mechanisms--aufzug"></a>

### Aufzug

Die eine vorhandene Kabine erhält zwei gegenüberliegende Schiebetürpaare.
Jeder aktive Geschosszugang besitzt ein eigenes Türpaar. EG und KG öffnen
nach innen, OG1–OG3 nach außen. Nach einem Ruf oder einer
Zielwahl schließen zuerst die Türen. Erst nach deren Abschluss fährt die
Kabine; am Ziel öffnen die dort aktiven Kabinen- und Geschosstüren automatisch.
Ein- und Aussteigen ist erst nach vollständiger Öffnung möglich.

Nach der Eigentümerkorrektur sitzt das Panel auf der rechten Seitenwand
beim Eintritt aus den Obergeschossen, nahe diesem Türende. Im Gebäuderahmen
ist dies die südliche Wand am westlichen Ende. Der obere Handlauf ist dort
verkürzt. Das Telefon bleibt im Nordosten. Abmessungen bleiben
Darstellungsannahmen. Panel, Etagenknöpfe und Telefon fahren mit der
Kabine; ihre Türblätter kombinieren Kabinenhub und seitliche Türbewegung.
Die Etagenwahl erfolgt weiterhin über die vorhandenen Bedienknöpfe des
Rundgangs. Das Telefon ist ein sichtbares Ausstattungsmodell.

<a id="merged-walkthrough-mechanisms--gemeinsame-quellen-und-prüfung"></a>

### Gemeinsame Quellen und Prüfung

`model/building-walkthrough.shared.json` enthält unter `mechanisms` ausschließlich
typbezogene Beschriftungen, Darstellungszeiten und Betrachtungsabstände.
`scripts/walkthrough_mechanisms.py` bindet die vorhandenen Raumtürflächen und
die Gelenke der referenzierten Geräte. Die native Referenzstellung bleibt
erhalten, auch beim zunächst ausgezogenen vierten Gefrierfach und bei den
teilweise geöffneten Gerätehebeln. Die Browsertransformation wird relativ zu
dieser Stellung ausgewertet.

Die Gefrierschrankbedingungen werden aus der bestehenden `validate_pose`-Prüfung
des Geräteproviders abgeleitet. Der Compiler vergleicht die abgeleiteten
Zustandsbedingungen mit sämtlichen Kombinationen der Endstellungen. Die
Bedienung verlangt konservativ die vollständig erreichte Zugangsstellung.

Die Aufzugausstattung entsteht aus `circulation.elevator.fittings` der
Gebäudequelle über `scripts/lift_fittings.py` als portable CAD-Geometrie.
Öffnungsweiten und Schiebewege stammen aus den bestehenden Geschossöffnungen.
`scripts/walkthrough_elevator.py` bindet dieselben Körper und Gelenke an den
Rundgang. `scripts/walkthrough_interaction.js` führt Türfolge, Verriegelung und
absolute Kabinenbindung aus. Bewegungen verwenden weiterhin die gemeinsame
quintische Darstellung mit ruhigem Beginn und Ende; reduzierte Bewegung
führt dieselben Zustandsprüfungen in identischer Reihenfolge aus.

```sh
python3 -m unittest discover -s tests -p 'test_*walkthrough*.py' -v
node tests/check_walkthrough_interaction.cjs
node tests/check_walkthrough_lift.cjs
node tests/check_walkthrough_mechanisms.cjs
node tests/check_walkthrough_mechanisms_browser.cjs <index.html> <playwright> <chrome>
```

Die Browserprüfung betätigt alle Raumtüren, prüft jede Gefrierschublade als
einzelne Sperrbedingung und verwendet Maus-/Tastaturereignisse auf den nativen
Flächen. Ein zeitlich ausgeführter Aufzuglauf prüft geschlossene Türen während
der Fahrt, mitfahrende Kabinentüren und die Zielseiten. Native Gebäudeprüfung,
Browserbedienung und reale Ausführung bleiben getrennte Nachweise: Die native
Gebäudedatei enthält eine statische Referenzstellung; Schwenkfreiheit,
Quetschschutz, reale Aufzugsteuerung und Gerätehardware sind nicht qualifiziert.

Der lokale Nachweis `exports/building-walkthrough/building-walkthrough-65c15de308d5/`
enthält den geprüften Rundgang, `browser-check.json` für die bestehenden
Bedienwege und `mechanisms-browser-report.json` für die neuen Funktionen.
Beide Browserprüfungen bestehen, ebenso alle 49 Modell-/Rundgangtests und die
drei JavaScript-Prüfungen für Picking, Kabinenbindung und Verriegelungen.
Der native FreeCAD-Gebäudebericht
`exports/generated/building-stack-7eed558ca997/build-report.json` bestätigt
2.388 gültige Körper, 509 Geometrieprüfungen und 16 Höhenprüfungen.
`exports/lift-fittings-7eed558ca997/validation.json` prüft die 26 neuen
Aufzugbauteile unabhängig in SolidCraft gegen ihre abgeleiteten Maße;
dies ist kein vollständiger SolidCraft-Gebäude- oder Kollisionsnachweis.
Die linearen Kabinentürwege halten in der Modellprüfung Abstand zu Endwänden,
Panel und Telefon. Der bestehende Circulation-Fixture-Test
`test_stack_integration_preserves_source_floor_ids_and_separates_blue_marker`
scheitert weiterhin am fehlenden Eintrag `D3_002_003`; derselbe Fehler wurde
auch auf dem unveränderten Ausgangsstand bestätigt.
