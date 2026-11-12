# Synthetischer CUT&RUN-Lauf und Wiederanlauf (E3)

E3 führt das SK-Mel-29/H3K4me3-Referenzprofil mit IgG-Reaktion und getrenntem
Input durch seine gebundene Phasenfolge. Alle Personenbeobachtungen, Zeiten,
Temperaturintervalle, Materialmengen und QC-Dateien sind synthetisch. Der Lauf
qualifiziert weder die offene historische SOP noch Dosierung, Enzyminaktivität,
Ausbeute, Anreicherung, Hardware oder einen Watchdog.

```sh
python3 scripts/run_cutrun_workflow.py --store exports/cutrun-e3/workflows.sqlite3 demo --run-id SYN.CUTRUN.E3
python3 scripts/run_cutrun_workflow.py --store exports/cutrun-e3/workflows.sqlite3 status SYN.CUTRUN.E3
python3 scripts/run_cutrun_workflow.py --store exports/cutrun-e3/workflows.sqlite3 report SYN.CUTRUN.E3 --out exports/cutrun-e3/report.json
```

Das Demo-Fixture durchläuft die Zweige seriell und erfindet ausdrücklich die
jeweiligen Beobachtungen. Zeitbefehle warten nicht in Echtzeit. Berichtziele sind
neue Dateien unter `exports/`. Dieselben Material-/Gefäßkennungen lassen sich
im selben Store nicht in einem zweiten Lauf frisch einführen. Der Standard-Store
ist der gemeinsame Store der bisherigen manuellen Abläufe.

## Führende Quellen und Versionen

`model/cutrun-synthetic-run.profile.json` referenziert die bytegebundene
E1-Vorbereitung. Das neue E1-Formatpaar `/2` ergänzt ausdrücklich die Rolle
`activation_reagent`: einen vorbereiteten calciumhaltigen Aktivierungspuffer,
keinen behaupteten Artikel oder eine Dosierung von Calcium-Stammlösung. Auch
das Stoppreagenz ist eine vorbereitete Modellmischung. Ihre synthetischen Dosen
kommen aus der ausdrücklich revidierten Phasenbindung. Andere Phasenvolumina
bleiben abstrakte Planwerte und werden nicht als vollständiges Rezept gebucht.
Passende historische E1-Quellentripel `/1` bleiben kompilierbar; gemischte
Revisionen werden abgewiesen. E3 verlangt die ausdrückliche `/2`-Rollenbindung.

Das Laufprofil ergänzt nur ausgegebene Aliquots, zusätzliche Fraktionsgefäße,
Stoppakteure und als `synthetic_assumption` gekennzeichnete Zeit-/Temperaturgrenzen
sowie Demo-Mengen. Reihenfolge, Rollen, Sollzeiten und Solltemperaturen werden
aus E1 übernommen. `execution_ready` bleibt dort falsch.

| Vertrag | Verantwortung |
|---|---|
| `material-workflow-definition/2` und `material-workflow-state/2` | Unveränderliche Quellen, Prozesszustand und gemeinsamer E2-Materialledger |
| `synthetic_intervals/1` | Untergrenze der Prozesszeit plus Unsicherheit, keine Wanduhr |
| `scripts/cutrun_workflow.py` | Phasen, Reaktionszustand, Stopps, QC und Wiederanlauf |
| `scripts/material_ledger.py` | Dieselben kanonischen Buchungen und Restmengen wie E2 |
| `scripts/manual_tasks.py` | Dasselbe Journal, atomare Ereignisse/Artefakte und dauerhafte Aliquotzuteilung |

Das Journal erkennt ausschließlich passende `/1`- und `/2`-Paare und verhindert
Formatwechsel beim Anhängen. Der E2-Runner öffnet keine E3-Läufe; der E3-Runner
öffnet keine E2-Läufe. Generische Entnahme-/Umwandlungsbefehle sind in E3 gesperrt.
Die gemeinsamen Hüllen erhalten zwei kleine Erweiterungspunkte: Zeitunsicherheit
im selben Wiederaufnahmeereignis und ausdrückliche Akteursprüfung für den
Schutzstopp. Die Standardimplementierungen erhalten das bisherige Verhalten.

## Absichten, Fraktionen und Stopp

`begin_phase` speichert Zweig, Reaktion, Versuch, feste Phase und Absicht vor
der synthetischen Durchführung. `confirm_phase` verlangt eine passende
Beobachtung; eine Zeitspanne ersetzt weder geklärte Suspension noch gemessene
Input-Fragmentgröße. Umwandlungen verlangen ausdrücklich beobachtete
Produktmengen. Die Demo-Mengen sind keine aus Zellzahl berechneten Erträge.

Umgewandelt wird an Fraktionsgrenzen: Eingang → identifizierter Reaktionsinhalt,
Überstand mit behaltenem Bead-Rest/Pellet, Säulenfraktion mit behaltenem
Durchfluss und Eluat mit behaltenem Säulenrest. Die Produktabstammung bleibt
transitiv innerhalb desselben Zweigs. Gefäße sind vorab identifiziert; eine
Materialumwandlung erzeugt kein zusätzliches physisches Gefäß.

Aktivierung und Stopp sind Entnahmen aus ausgegebenen Reagenzaliquots mit
benanntem Zielgefäß. Zugaben entwerten dessen Massenbeleg. Das Modell berechnet
keine neue Mischungsmenge oder Konzentration aus den Zugaben; die nächste
Fraktionsbeobachtung liefert ihre eigene ausdrücklich synthetische Menge.
Produkt-QC belastet ausschließlich das gereinigte Produkt. Andere Reagenzrollen
werden nicht gebucht; E3 ist keine vollständige Reagenzrezeptur.

Vor Aktivierung braucht jeder aktive Zweig sein eigenes Stopp-Aliquot und eine
aktuelle ausdrückliche Zugangs-/Mischbestätigung (`confirm_stop_readiness`).
Eine serielle Terminprüfung berücksichtigt vor **jeder** Aktivierungsabsicht
alle bereits möglichen Aktivierungen, früheste Fristen und den synthetischen
Stopp-Servicebedarf. Ein nicht erfüllbarer Takt wird vor der Absicht abgewiesen.

Ab der Aktivierungsabsicht gilt die Reaktion als `possibly_active`. Die
Quittung liefert nur die obere Grenze des möglichen Kontakts; sie verschiebt
den frühesten Beginn nicht. Eine Zugabe ohne Mischbestätigung bleibt möglich
aktiv und fachlich gesperrt. Eine unklare Aktivierung wird nicht wiederholt.

`begin_stop` und `confirm_stop` sind auch während Halt, Abbruch und
Wiederanlauf erlaubt. Ein ausdrücklich deklarierter zweiter Stoppakteur kann
die Stoppevidenz erfassen. Jeder Reaktionsbehälter besitzt höchstens eine
lebenslange Schutzstoppabsicht. Ihr Aliquot ist fest gebunden, alle offenen
Eingänge müssen disjunkt sein. Ein unquittierter Stopp für Gefäß 1 blockiert
Gefäß 2 nicht. Die alte Aktivierungsbuchung bleibt dabei ungeklärt.

Fehlender Zugang, Mischung oder Stoppreagenz zum Stoppzeitpunkt erzeugt einen
dauerhaft gespeicherten Befund. Ein Stopp wird erst aus bestätigter ausreichender
Zugabe **und** Mischung abgeleitet. Nach bestätigter ungemischter Zugabe kann
`confirm_stop_mixing` ausschließlich die Mischung ergänzen; es bucht keine
weitere Dosis. Verspätete oder zu kurze Stoppbeobachtungen werden erhalten und
als Abweichung gesperrt. Ein Software-Halt bestätigt keinen chemischen Stopp.

## Zeit, Temperatur und Wiederaufnahme

`logical_time_s` ist die Untergrenze. `clock.uncertainty_s` ist die zusätzliche
Breite; `null` bedeutet ein unbegrenztes Maximum. Jeder aktive Wiederaufruf von
`open(..., resume=True)` eröffnet eine ausdrücklich zu klärende Zeitlücke.
Auch nach einem ordentlichen `close` wird keine biologische Pause angenommen.
`resolve_time_gap(min_s, max_s, reason)` speichert die belegte synthetische
Spanne; `max_s=null` lässt die Exposition unbegrenzt. Null Sekunden müssen
ausdrücklich bestätigt werden. Eine einmal unbekannt bestätigte Dauer wird
nicht durch einen späteren Neustart zurückgesetzt.

```sh
python3 scripts/run_cutrun_workflow.py --store exports/cutrun-e3/workflows.sqlite3 resume LAUF_ID
python3 scripts/run_cutrun_workflow.py --store exports/cutrun-e3/workflows.sqlite3 act LAUF_ID --session SESSION_ID --actor SYN.CutRun.Operator --action resolve_time_gap --data '{"min_s":5,"max_s":10,"reason":"synthetisch beobachtete Unterbrechung"}'
```

Die neue Sitzung wird ausgegeben. Weitere `act`-Aufrufe benötigen genau diese
Sitzung. `resolve_effect` verlangt für offene Absichten ausdrücklich
`performed`, `not_performed` oder `unknown` mit Reaktionskennung und Belegen.
`reconcile` bestätigt das vollständige Material-/Gefäßinventar und den
Arbeitsplatz; es verlängert weder Aufgaben- noch Reaktionsfristen. Alte
Sitzungen und veraltete Journalrevisionen können keine Wirkung wiederholen.

`advance_time` bleibt im Halt und Abbruch verfügbar. Ein Zeitsprung bewertet
alle betroffenen Reaktionsfristen im selben Ereignis. Temperaturbeobachtungen
geben Intervalle an; Endpunktwerte ersetzen keine Abdeckung. Fehlende Abdeckung,
widersprechende Werte, unbekannte Exposition und verspätete Stopps bleiben
Abweichungen. Eine gute spätere Beobachtung löscht keine frühere Abweichung.
Der Bericht leitet Exposition als Min/Max ab; ein unbekanntes Maximum bleibt
`null`. Ressourcen bleiben bis zum vollständigen Abgleich reserviert.

## QC und Ende

Fluorometrie und qPCR erhalten eigene Produktentnahmen. Originalbytes werden
atomar mit dem Import gespeichert. Lauf-, Versuchs-, Reaktions-, Zweig-,
Material-, Methoden- und Stufenkennungen werden geprüft. Falsche Zuordnung,
Methode oder Fraktion bleibt mit Originaldatei quarantänisiert. Die PCR-NTC
ist eine separate QC-Rolle und keine dritte CUT&RUN-Aktivierung.

Ein Signal unter Nachweisgrenze bleibt so gekennzeichnet. Es wird weder als
Nullmenge gebucht noch als quantifizierbarer Produkterfolg gewertet. Die
technische synthetische Prüfung verlangt vollständige Produkt-QC und separate
NTC-Evidenz; ein biologischer Anreicherungsschwellenwert bleibt offen.
`passed` bedeutet nur den abgeschlossenen synthetischen Softwarevertrag.

`release` verlangt alle Phasen, beobachtete Stopps, QC-Prüfung, bestätigte
Dispositionen und ein frisches vollständiges Inventar. Ein Abbruch darf eine
aktive Reaktion nicht als gestoppt ausgeben. Eine ausdrückliche fachliche
Beendigung (`abnormal_termination`) hält den fehlenden Stoppnachweis fest und
verlangt Quarantäne. Ungeklärte Effekte müssen weiterhin abgeglichen werden;
es gibt keine automatische Entsorgung oder Freigabe.

## Kompatibilität und Prüfung

Historische Ereignisse bleiben unverändert lesbar. Änderungen an gemeinsamen
Laufzeitdateien betreffen jedoch deren Quellenpins: Nichtterminale ältere
Läufe können die Wiederaufnahme mit geändertem Code verweigern. Das ist keine
Migration; insbesondere werden S01-Fixtures weder zurückgesetzt noch unter
alter Kennung frisch eingeführt. Zur Fortsetzung ist eine gesonderte Prüfung
des gepinnten Laufstands erforderlich.

Die E3-Tests prüfen Phasen-/Identitätsfehler, fehlende Quittungen, zwei unabhängige
Stopps, Mischung, Zeitlücken, Fristen, Temperaturabdeckung, QC und Rollback.
Die `/2`-Ledgertests prüfen Formatpaare, dauerhafte Aliquotzuteilung und disjunkte
Schutzstopps. E1-/E2-, Journal-, NanoDrop-, Qubit-, Gesamtworkflow- und unveränderte
S01-Tests sichern die bestehenden synthetischen Verträge ab. CAD, Netzwerk,
reale SOP und Hardware werden in E3 nicht geprüft.
