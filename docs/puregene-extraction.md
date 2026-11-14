# Synthetische Puregene-Zellextraktion mit TapeStation-QC

Puregene ergänzt die bestehende [DNeasy-Extraktion](dneasy-extraction.md) als
eigene Protokollfamilie. Die erste Ausprägung folgt dem Zellprotokoll des
**Puregene DNA Handbook, HB-0326-004, Januar 2022, S. 30–33** für die kleine
Mikrozentrifugenvariante mit 1–2 Millionen kultivierten Zellen. Der Testfall
verwendet ein fiktives Zellpellet mit einer Million Zellen und ausdrücklich
deklariertem Restmedium. Er behauptet keine zuvor ausgeführte Zellernte.

Die Quelle ist das vom Eigentümer bereitgestellte Herstellerhandbuch; dessen
SHA-256 steht im Protokoll. Das Original-PDF wird nicht zur Laufzeit benötigt
oder als weitere führende Rezeptquelle im Repository kopiert.
[Herstellerhandbuch](https://www.qiagen.com/en-US/resources/download/KitHandbook/puregene-dna-handbook).

## Einstieg

```sh
python3 scripts/run_puregene_extraction.py --help
python3 scripts/run_puregene_extraction.py --store exports/puregene-demo/workflows.sqlite3 demo --run-id SYN.PUREGENE.DEMO01
python3 scripts/run_puregene_extraction.py --store exports/puregene-demo/workflows.sqlite3 report SYN.PUREGENE.DEMO01
```

Nur `demo` erfindet positive Prozessbeobachtungen, Reagenzverbräuche,
Produktvolumina und Messergebnisse. `create` legt einen frischen, unbestätigten
Lauf an. `status` und `report` lesen ohne Sitzungsübernahme. `resume` verlangt
ausdrücklichen Inventar- und gegebenenfalls Wirkungsabgleich; `act` nimmt
einzelne synthetische Beobachtungen mit der ausgegebenen Sitzung an.
Eine Demo kann mit `--pause-after PHASE_ID`, `before_confirm:PHASE_ID`,
`extracted` oder `tapestation_loaded` unterbrochen werden. Der Wiederanlauf
wiederholt keine Aspiration, Abgabe oder andere unklare Wirkung automatisch.

Für unabhängige Demo-Wiederholungen einen neuen synthetischen Store verwenden.
Die festen Material-/Aliquotkennungen des Profils dürfen nicht neu in denselben
Store eingeführt werden. Eine neue Laufkennung setzt keine Mengen zurück.
Quellenänderungen erlauben keine stille Migration alter Journale.

## Führende Quellen und gemeinsamer Ablaufkern

| Quelle | Verantwortung |
|---|---|
| `model/puregene-extraction.protocol.json` | Puregene-Identität, Zellschritte, Herstellerparameter und Fraktionsrollen |
| `model/puregene-extraction.synthetic.json` | Eigenständige Probe/Produkt, ausgegebene Reagenzaliquots, reale Prozessgegenstände und ausdrücklich synthetische Beobachtungen |
| `model/puregene-extraction.schema.json` | Formaler Quellenvertrag |
| `scripts/puregene_extraction_sources.py` | Semantische Prüfung, Materialgraph und Quellenpins |
| `scripts/extraction_workflow.py` | Gemeinsame geordnete Absicht-/Bestätigungshülle und manuelle TapeStation-QC |
| `scripts/puregene_extraction_workflow.py` | Puregene-spezifischer Engine-Guard und Bericht |
| `scripts/extraction_qc_sources.py` | Gemeinsam abgeleitete TapeStation-Bindung |
| `scripts/extraction_demo.py` und `scripts/extraction_cli.py` | Gemeinsame explizite Fixture-/CLI-Hülle für Puregene und DNeasy |

Puregene und DNeasy behalten getrennte Protokollidentitäten und Quellen.
Die geordnete Ausführung, Sitzungsprüfung, Journaleffekte, Recovery und
TapeStation-Importregeln werden einmal implementiert. Inventar und Mengen
bleiben im vorhandenen Material-Ledger; es gibt keine Puregene-Nebenbilanz.
Die bestehende E1-Vorbereitung wird nicht als Puregene-Rezept ausgegeben.

## Wechsel der zurückzubehaltenden Fraktion

| Prozesszustand | Zurückbehalten | Abtrennen |
|---|---|---|
| Proteinpräzipitation | DNA-haltiger Überstand | Proteinpellet im Ausgangsgefäß |
| Isopropanol-DNA-Präzipitation | DNA-Pellet im Präzipitationsgefäß | Flüssiger Überstand |
| Ethanolwäsche | Dasselbe DNA-Pellet | Waschflüssigkeit |
| Trocknung/Hydratation | DNA und schließlich gelöstes Produkt | Keine neue, angenommene DNA-Masse |

Pellet und Flüssigkeit befinden sich nach einer Zentrifugation zunächst im
**selben physischen Gefäß**. Bis zur tatsächlichen Trennung bleibt deshalb ein
kanonisches zusammengesetztes Material bestehen. Fraktionszustand und
Zurückbehaltungsregel sind Prozessmetadaten, kein zweiter Mengenbestand.
Erst eine bestätigte physische Trennung führt getrennte Materialidentitäten
in den tatsächlich beteiligten Gefäßen ein. Eine virtuelle Pelletablage wird
nicht erfunden.

Für die Überführung in das bereits mit Isopropanol vorbereitete Gefäß beschreibt
die synthetische Automationsvariante drei getrennte Vorgänge: Isopropanol
vorlegen, DNA-haltigen Überstand in eine identifizierte Transfer-Spitze
aufnehmen und aus dieser Spitze in das vorbereitete Gefäß abgeben.
Die Spitze ist ein deklarierter realer Prozessgegenstand. Ihr Fassungsvermögen,
ihre Auswahl und der Transfer sind unqualifiziert. Diese Pipettieradaption
ersetzt in der Testwelt das vorsichtige Gießen des Herstellerprotokolls;
sie ist keine geprüfte Änderung einer Labor-SOP.

Das Proteinpellet erhält dadurch keinen falschen Isopropanol-Elternbezug.
Nach Unterbrechung zwischen Aufnahme und Abgabe bleibt die DNA als Material
in der Spitze reserviert. Eine Wiederaufnahme darf weder eine zweite Aufnahme
noch eine bereits erfolgte Abgabe annehmen. Die anschließenden Abtrennungen
benennen das zu erhaltende DNA-Pellet und die tatsächlichen Abfallgefäße.
Unbekannte Pelletmassen bleiben `ng: null`; Zellzahl und Flüssigkeitsvolumen
werden nicht in DNA-Ertrag umgerechnet.

## Beobachtungen, Zeit und Fehlerfälle

Lysis, optionale RNase-Behandlung, Proteinpräzipitation, kompakter Proteinpellet,
schonendes Invertieren, DNA-Präzipitation, Pelletretention, Ethanolwäsche,
Trocknung und vollständige Hydratation benötigen eigene Prozessbelege.
Synthetische Zeit wird protokolliert; RCF-Grenzen sind ausdrücklich `x_g`,
keine RPM-Ersatzwerte. Die Rechnung allein bestätigt keine Pelletposition,
keine sichere Aspiration und keine tatsächliche Temperatur.

Das Handbuch nennt für die abschließende Raumtemperatur-Hydratation
**„overnight“ ohne feste Stundenzahl**. Die Demo verwendet dafür eine ausdrücklich
erfundene Zeitvorgabe aus dem Profil. Diese ist keine Herstellerangabe und
keine freigegebene SOP. Der Schritt wird nicht still übersprungen.
Das gleiche gilt für beobachtete Restflüssigkeit und Produktvolumina:
Fixturewerte sind keine Nachweise für quantitative Rückgewinnung.

Ein lockerer oder verlorener Pellet, falsche Fraktion, Dosisabweichung oder
Über-Trocknung rechtfertigt keinen normalen Fortgang. Unklare Wirkungen
bleiben beabsichtigt und reserviert. Der ausdrückliche Abgleich unterscheidet
Durchführung, Nichtdurchführung und unbekannten Ausgang. Für bekannte, bereits
ausgeführte Fehlverarbeitung steht zusätzlich ein ausdrücklich abnormaler
Abgleich zur Verfügung: tatsächliche Verbräuche und negative Beobachtungen
bleiben erhalten, betroffene Materialien werden quarantänisiert und der Lauf
bleibt auf kontrollierten Abbruch beschränkt. Er wird dadurch nicht erfolgreich.

Die Retentionsangabe folgt nach jeder Materialumwandlung dem aktuellen
DNA-haltigen Material. Ein bestätigter Nullausgang dieses Materialstroms oder
der erforderlichen Isopropanol-Vorlage wird wahrheitsgemäß gebucht und sperrt
die Fortsetzung. Eine unbekannte Menge bleibt dagegen `null`; sie wird weder
als Nullmenge noch als positiver Rückgewinnungsnachweis ausgegeben.

Bedingte Rettungswege, erneute Proteinpellet-Zentrifugation, Carrierzugabe und
automatische Wiederholungen sind in dieser ersten Ausprägung nicht implementiert.
Ein Abbruch verlangt geklärte Absichten, Inventar und Materialdispositionen.
Ein angelegter TapeStation-Auftrag benötigt vor Ressourcenfreigabe weiterhin
einen eigenen Stillstands-/Rücknahmebeleg; Storno sendet keinen Geräte-Stopp.

## TapeStation und Prüfgrenzen

Die vorhandene **TS01 mit 4200-Planungsreferenz** und der separate
[Genomic-DNA-ScreenTape-Vertrag](dneasy-extraction.md#tapestation-vorbereitung-messende-import-und-bewertung)
werden wiederverwendet. Probe und Ladder erhalten getrennte Ansätze und
Buchungen. Die QC-Entnahme belastet das aufbewahrte DNA-Produkt genau einmal;
Import und Review erzeugen keinen zusätzlichen Probenverbrauch.
Originalbytes, Lauf-, Analyse-, Mess-, Lane-, Material-, Gefäß- und
Inhaltsrevisionsbezug bleiben erhalten.

DIN und Fragmentgröße bleiben getrennte Metriken. TapeStation-Bereichsgrenzen
erlauben keinen präzisen Nachweis beliebig großer Puregene-DNA. Fehlende oder
zensierte Größen und unbekannte Flags ergeben keine stille Freigabe; eine
positive DIN ersetzt keinen Fragmentgrößennachweis. Die Policy ist ausschließlich
synthetisch, keine Hersteller- oder biologische Freigabe.

```sh
python3 -m unittest discover -s tests -p 'test_puregene_extraction*.py' -v
python3 -m unittest discover -s tests -p 'test_dneasy_extraction*.py' -v
python3 -m unittest discover -s tests -p 'test_tapestation_results.py' -v
```

Reale Extraktion, Hydratation, Pelletsicherung, Flüssigkeitshandhabung,
Spitzengeometrie/-kapazität, native Agilent-Exporte, Rotor-/Gefäßpassung,
Geräte-/Netzwerk-/Roboterbetrieb, biologische Leistung und Sicherheit sind
nicht qualifiziert. Die projektweite Vorgabe fließender Bewegungen gilt
für spätere Bewegungsadapter weiter. Hier wird keine Roboterbahn erzeugt.
