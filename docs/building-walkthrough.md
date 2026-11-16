# Gebäude im Browser erkunden

Der [öffentliche Rundgang auf GitHub Pages](https://smoe.github.io/DIYLabBot/)
bietet fünf direkte Blickpunkte: Doktorandenraum **3.002**,
Labor **3.003**, Küche **1.008**, den Blick durch den **Freiraum / das Atrium**
und den **Kernbereich im 3. OG**.
Von dort lässt sich die Kamera frei bewegen. Die Flächen stammen aus den
fertigen nativen CAD-Körpern einschließlich ihrer Booleschen Öffnungen;
Raumwände, Fenster und Möbel werden nicht als Ersatzquader nachgezeichnet.

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

- Die fünf Ortsknöpfe öffnen die jeweiligen Blickpunkte.
- **WASD / Pfeiltasten** bewegen die Kamera; **Ziehen** mit Maus oder Finger
  ändert die Blickrichtung.
- **Q / E** bewegen die Kamera senkrecht; **Shift** beschleunigt die Bewegung.
- Bildschirmknöpfe bieten dieselbe Bewegung auf Touchgeräten.
- Die Geschossauswahl ändert die Kamerahöhe im Gebäude. „Return to viewpoint“
  setzt den aktuellen Blickpunkt zurück; Vollbild vergrößert die Ansicht.

Die Ortsknöpfe sind Blickpunktwechsel, keine berechneten Gehwege. Die freie
Kamera hat keine Kollisionsprüfung und kann Wände oder Decken durchqueren.

## Gemeinsame Quellen und getrennte Raumbezüge

[`model/building-walkthrough.shared.json`](../model/building-walkthrough.shared.json)
referenziert die vorhandenen Quellen für Gebäude und Labor. Die Raumkameras
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

Das Gebäude verwendet eine ungemessene Darstellskalierung und angenommene
Geschosshöhen. Das detaillierte L01-Modell besitzt einen eigenen lokalen
Raumbezug; eine vermessene Transformation in den Gebäudebezug fehlt weiterhin.
Der Labor-Knopf wechselt deshalb ausdrücklich in eine zweite Szene. Diese
Trennung wird in der Oberfläche angezeigt. Sie fügt keine scheinbar vermessene
Türverbindung ein.

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
von `gh-pages` die HTML-Datei und das Publikationsmanifest ersetzen, committen
und normal nach `origin/gh-pages` pushen. Der Push löst die Pages-Bereitstellung
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

## Nachweise

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

Die Browserprüfung erzeugt neben dem HTML einen separaten `browser-check.json`
und Screenshots der Blickpunkte. Sie prüft tatsächliches WebGL-Zeichnen,
Tastatur-/Zeigerbedienung, die Geschossauswahl, die mobile Ansicht und die
Fehleranzeige. Der CAD-/HTML-Build allein ist noch kein Browsernachweis.
Statische Geometrie, Browserbedienung und reale Begehbarkeit bleiben getrennte
Nachweise; der Rundgang qualifiziert keine Fluchtwege oder Roboterbewegungen.

## Objektbefehle: Kühlschrank und Mikrowelle 1.008

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
Bibliothek in das eigenständige HTML eingebettet. Aktuell sind die
Kühlschranktür und die Mikrowellentür 1.008 als bewegliche Objekte definiert. Raum- und Schranktüren
benötigen noch ihre eigenen Artikulationsbindungen; sie erhalten dieselbe
Bedienung, sobald diese beschrieben sind. Die Kamera-Hilfe `viewObject` bleibt
nur in der Test-API und hat keine Taste in der Oberfläche.

Blickpunkt-, Geschoss- und Szenenwechsel erhalten die Türstellung während
dieser Sitzung; ein Neuladen setzt die Referenzstellung.

Tür und Griff drehen gemeinsam, der vorhandene Pinguin, seine Tasse,
Innenböden und Kühlschrankhülle bleiben unverändert. Ein Objektbefehl gibt
`accepted`, `already_in_state`, `rejected_busy` oder `unknown_target` zurück.
Während einer Bewegung werden weitere Bewegungsbefehle abgewiesen. Es gibt
keine Warteschlange oder automatische Umplanung.

Die zusätzliche Quelle `model/furniture/social.articulations.json` referenziert
den Möbelkatalog und benennt Teile und Scharnierkante ohne
kopierte Abmessungen. `scripts/furniture_articulation.py` leitet den Rahmen aus
der platzierten Tür-Prismenoperation ab. Die Rundgangquelle referenziert nur
Raum, Instanz und Artikulation sowie Beschriftungen und Darstellparameter.
Der Exporter und die geprüften nativen Gebäudekörper werden unverändert benutzt.

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
Positionen und Normalen der vorhandenen Meshgruppen werden zusammen gedreht;
bei der Referenzstellung ist die Modellmatrix exakt die Einheitsmatrix.

Nur der Browser besitzt diese Artikulation. FreeCAD und SolidCraft enthalten
weiter die **geschlossene Referenzstellung**, keine nativen Gebäudegelenke.
Reale Scharniere, vollständige Sichtbarkeit aus jeder Perspektive, Kollisionen,
Schwenkraum, Schrank-/Raumtüren und Roboterbefehle sind damit nicht qualifiziert
oder implementiert. Für diese erste Erweiterung werden keine Daten gespeichert
und keine Hardware-, ROS- oder SiLA-Befehle verschickt.

Die vorhandenen Möbelbilder und ihre ursprüngliche Provenienz bleiben erhalten.
`docs/building-furnishings-media-compatibility.json` bindet die eng begrenzten
Änderungen der Browserquellen an die unveränderten Kameras und Bildbytes.
Dieser Kompatibilitätsnachweis ist weder ein erneutes Rendern der historischen
Bilder noch eine zusätzliche CAD- oder Bewegungsqualifikation. Die neuen
Objektbefehle werden davon getrennt mit der tatsächlichen Browserprüfung geprüft.
