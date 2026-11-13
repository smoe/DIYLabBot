# S09-Inputsonikation am bestehenden CUT&RUN-Root

Die eigene Engine `input_sonication_mock/1` verbindet die optionale
[Sonikationsvorbereitung](dna-sonication.md) mit der bestehenden
[manuellen SOP-Stufe S09](cutrun-manual-runtime.md). Sie verwendet dasselbe
Journal, denselben Materialledger und dieselben Ressourcen wie der SOP-Kern.
Es gibt keine zusätzliche Mengenbilanz oder Geräte-Zustandsdatenbank.

**Ausgeführt werden ausschließlich Software-Fixtures.** Die Engine verlangt
`test_clock` und `test_fixture`. Ein Systemzeitgeber oder eine reale
Personenbeobachtung wird abgewiesen. Geräte, Ultraschall, Flüssigkeitshandhabung,
ROS und SiLA werden nicht ausgeführt. Die vorhandenen Laufarten behalten ihre
Formate; eine automatische Migration oder Öffnung durch die alte CLI ist
ausgeschlossen.

Der separate [SiLA-2-Rootadapter](sonication-sila2-network.md) ergänzt
authentifiziertes TLS/gRPC über Loopback für neue gebundene Fixture-Läufe.
Die hier beschriebene lokale CLI und ihre historischen Nachweise bleiben
eigenständige Software-Fixtures ohne ausgeführten SiLA-Transport.

## Einstieg

```sh
python3 scripts/run_cutrun_input_sonication.py prepare
python3 scripts/run_cutrun_input_sonication.py prepare --require-complete
python3 scripts/run_cutrun_input_sonication.py --store exports/sonication-runtime/demo.sqlite3 demo \
  --directory exports/sonication-runtime/fixture-run-01 \
  --evidence-directory exports/sonication-evidence/fixture-proof-01 --render
```

`prepare` liest nur Quellen und öffnet keinen Store. Die Vorlage ist deaktiviert
und enthält offene Bindungen; `--require-complete` liefert deshalb Exitcode 2.
Die Demo benötigt neue Verzeichnisse und unverbrauchte Fixturekennungen.
Eine Wiederholung setzt weder Material noch Journale zurück. Weitere unabhängige
Testwelten benötigen einen ausdrücklich getrennten Store; das ist keine
Fortsetzung eines realen oder bereits eingeführten Bestands.

`status` und `report` lesen einen gespeicherten Lauf mit dessen letztem
Testuhr-Snapshot. `resume` und `act` verlangen eine explizite Testuhrdatei;
`act` außerdem aktuelle Sitzung, Akteur, Beobachtungsdatei und Befehlsdaten.
`fixture-intent --wait` ist der lokale Kindprozess-Einstieg für den
Abbruchnachweis. Er bedient kein Gerät. Die CLI-Hilfe beschreibt die Argumente.
Ausgaben bleiben unter `exports/`; vorhandene Ausgabedateien werden erhalten.
Nicht als Verzeichnis nutzbare Vorfahren der Demo-Ausgabepfade werden vor dem
Öffnen des Stores und vor jeder Szenarioausführung abgewiesen.

## Quellen und die ausdrückliche Fixture-Grenze

| Quelle | Verantwortung |
|---|---|
| `model/cutrun-input-sonication.profile.json` | Opt-in, Input-Reaktionsbindung, deklarierte Gefäßklasse/Position und Pins der unveränderten SOP-/Sonikationsquellen |
| `model/cutrun-input-sonication.schema.json` | Form des neuen Kompositionsprofils |
| `model/cutrun-input-sonication.fixture.json` | Einmalige Quelle sämtlicher erfundener Demowerte und unabhängiger Szenarioidentitäten |
| `scripts/cutrun_input_sonication_sources.py` | Komposition, Quellenabschlussprüfung und getrennte reale/synthetische Bereitschaft |
| `scripts/cutrun_input_sonication_workflow.py` | Zusätzliche S09-Absichten, Belege und Abschlussbedingungen am vorhandenen Root |

Die Komposition benutzt den bisherigen SOP-Compiler unverändert mit
`original_pdf=None`. Es wird kein künstliches Hersteller-PDF erzeugt oder als
Original ausgegeben. Fehlendes Herstelleroriginal, offene reale Anforderungen,
`original_pdf_verified=false` und die reale Stufenbereitschaft bleiben erhalten.
Nur die neue, zwingend als Fixture gekennzeichnete Engine besitzt eine getrennte
`synthetic_gate_readiness` für S01/S02/S09. Dabei ist allein das fehlende
Herstelleroriginal von der **Fixture-Gateprüfung** ausgenommen; alle übrigen
benötigten Bindungen müssen ausdrücklich als Testdeklarationen vorliegen.
Die übernommenen manuellen Profilfelder wie `locally_confirmed` sind in diesem
Modus fiktive Deklarationen, keine örtliche Freigabe oder authentifizierte Person.

Der Bericht zeigt reale Bereitschaft und synthetische Gates getrennt.
`preparation_complete`, `reference_success` und `execution_ready` bleiben falsch.
Bekannte S09-Temperaturgrenzen dürfen die im Sonikationsplan deklarierte Grenze
nicht überschreiten; unbekannte Werte werden nicht ergänzt. Private
Override-Quellen werden mit ihren unveränderten Originalbytes zusätzlich zu
ihrem effektiven JSON-Digest archiviert. Alle tatsächlich verwendeten
Quellen, Compiler, CLI, Demo und Fixturedaten werden vor neuen Befehlen gepinnt.

## Identität, Bilanz und Belege

S09 bindet ausschließlich die aktuelle Input-Reaktion. Ihre aktuelle
Materialidentität, Gefäßidentität, Inhaltsmenge und beobachtete Position stammen
aus dem Root. H3K4me3 und IgG gelangen nicht in diese Sonikationsstrecke.
Die Klasse `tube_1_5ml` und der Geräteplatz sind ausdrückliche synthetische
Deklarationen; eine reale Passung wird nicht behauptet.

Eine vollständige Inventarbeobachtung stellt das identifizierte Gefäß an den
deklarierten logischen Geräteplatz. Das ist eine Fixture-Beobachtung, keine
ausgeführte Ladebahn. `begin_sonication` speichert danach eine kanonische
Material-Umwandlungsabsicht vor jeder Wirkungsbehauptung. Erst die eigene
Bestätigung mit Originalartefakt bucht den neuen Materialzustand im selben
Gefäß. Generische Bestätigungs-/Abgleichbefehle umgehen diese Bindung nicht.
Eine wiederholte gleiche Beobachtungskennung erzeugt kein weiteres Ereignis;
abweichende Parameter unter derselben Kennung werden abgewiesen.

Pulsplan, physische Wirkungsbehauptung, Zeitintervall, Temperaturabdeckung und
Fragmentgrößenbefund sind verschiedene Belege. Die Zeitdaten müssen den
Pulsplan abdecken und dürfen im gleichen Uhrbezug nicht vor der Absicht oder
nach der erfassten Wirkungsquittung liegen. Es gibt keine geratenen Vergleiche
zwischen unterschiedlichen Uhrdomänen. Ein Größenbefund benötigt seinen
eigenen bestätigten Root-QC-Verbrauch am richtigen Sonikationsprodukt sowie
unveränderte Originalbytes. Konzentrationswerte ersetzen diesen Befund nicht.
Abweichende Befunde bleiben erhalten und sperren die Stufe.

Die Beispieldaten enthalten eine ausdrücklich erfundene S02-Umwandlung von
10.000 Zellen in 300 µl Inputlysat. Das ist keine Lysisimplementierung oder
Ausbeuteberechnung. Die fiktive Sonikation führt 300 µl im selben Gefäß weiter;
ein separat bestätigter QC-Verbrauch von 5 µl lässt 295 µl im Rootbestand.
Auch 3 × 7 s Pulse, zwei Pausen à 2 s, 4 °C und 150–450 bp sind allein
Testdaten. Daraus werden keine Geräteeinstellungen oder Laborergebnisse abgeleitet.

Der Geräteplatz wird über die vorhandene Root-Ressourcentabelle reserviert.
Eine unklare Wirkung oder ein noch am Gerät beobachtetes Gefäß hält diese
Reservierung. S09 benötigt die ausdrückliche Rückgabe an den ursprünglichen
Rackplatz. Spätere Materialumwandlungen einer folgenden Stufe entwerten den
historischen S09-Beleg nicht allein wegen einer neuen Materialidentität.

## Wiederaufnahme und Abbruch

Ein Neustart übernimmt die bestehende Definition und rotiert die Sitzung.
Die gespeicherte Absicht bleibt offen; kein Sonikationsauftrag wird wiederholt.
Die alte Sitzung verliert ihren Schreibzugriff. Eine neue Uhrdomäne benötigt
einen ausdrücklichen Zeitlückenabgleich. `unknown` hält Bestand, Gefäß- und
Geräteressourcen. Erst eine eigene Beobachtung löst die alte Wirkung auf;
Inventar und Arbeitsplatz sind zusätzlich vollständig abzugleichen.

`cancel` setzt die Abbruchabsicht. `finish_cancel` kann erst nach geklärten
Wirkungen, bestätigter Rackrückgabe, Materialdispositionen und vollständiger
Inventar-/Arbeitsplatzbeobachtung freigeben. Verbrauchte Elternmaterialien
werden nicht umetikettiert oder neu eingeführt.

## Nachweis und Video

Die Demo führt drei unabhängige Fixtureläufe aus: normale S09, tatsächlicher
SIGKILL eines lokalen Python-Kindprozesses nach gespeicherter Absicht mit
anschließendem Abgleich, sowie Abbruch bei unklarer Wirkung. Die normale und
wiederaufgenommene S09 enden als abgeschlossene **Stufe**; der gesamte CUT&RUN-
Root bleibt offen und hält seine Materialien. Das ist kein vollständiger
CUT&RUN- oder biochemischer Erfolgsnachweis.

`sonication_evidence.py` exportiert unveränderte Journal-Dokumentstrings,
Hashkette, Definition und Originalartefakte. Quellen- und Implementierungsbytes,
Arbeitsstand, Testlogs und Szenen werden im neuen Bundle archiviert.
`render_sonication_evidence.py` erzeugt daraus beschriftete PNG/MP4.
Bei mehreren Größenbefunden zeigt die Karte jeden Befund mit Kennung,
Bereich und Originalbeleg. Ein unpassender Befund bleibt unabhängig von der
JSON-Schlüsselreihenfolge als Widerspruch mit gesperrtem S09-Abschluss sichtbar;
passende Größenbefunde ersetzen die übrigen S09-Gates nicht.
Root-Prozesszeit/-Intervall, gemessene lokale Fixture-Laufzeit und geraffte
Videozeit erscheinen getrennt. Die Laufzeitmarken werden **nach** den jeweiligen
Ereignissen erfasst; Kindprozessereignisse kann der überlebende Treiber gemeinsam
erst nach dem Prozessende beobachten. Diese Marken sind keine Gerätemesszeiten.

```sh
python3 scripts/sonication_evidence.py --check exports/sonication-evidence/fixture-proof-01/manifest.json
```

Die Prüfung verwendet archivierte Quellenbytes, nicht einen späteren Checkout.
Sie bindet Originale, Kette, IDs, Root-Bilanz, Szenentexte, PNG/MP4 und
aufgezeichnete Werkzeugdaten; `ffprobe` prüft die tatsächliche Videostruktur.
Eine Sichtprüfung wird erst nach tatsächlichem Ansehen protokolliert und
erzeugt ein zusätzliches Reviewmanifest. Das ursprüngliche Manifest wird nicht
umgeschrieben. Swift-Modulcaches sind ungebundene Hilfsdateien.
Die Integritätshashes sind keine Signatur oder authentifizierte Laborauditierung.
Historische Medien, Galerie und deren Provenienz bleiben unverändert.

```sh
python3 -B -m unittest discover -s tests -p 'test_cutrun_input_sonication*.py' -v
python3 -B -m unittest discover -s tests -p 'test_run_cutrun_input_sonication.py' -v
python3 -B -m unittest discover -s tests -p 'test_sonication_evidence.py' -v
```
