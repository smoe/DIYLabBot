# Synthetische DNeasy-69504-Extraktion mit TapeStation-QC

Der neue Ablauf verarbeitet ein ausdrücklich synthetisches Säugerzellpellet
mit dem **DNeasy Blood & Tissue Kit 69504** und behält das identifizierte
DNA-Eluat. Danach wird eine eigene QC-Probe für **TS01 mit Genomic DNA
ScreenTape** vorbereitet. TS01 verwendet die bestehende 4200-Planungsreferenz;
Gerätemodell, CAD, Laborposition und manuelle Bedienart bleiben erhalten.

Dies ist eine ausgeführte Software-Zustandsmaschine mit fiktiven Eingaben,
keine durchgeführte oder qualifizierte Laborprozessierung. Reale Extraktion,
Ausbeute, Pipettieren, Mischen, Temperierung, Zentrifugation, Gerätesteuerung,
Netzwerkkommunikation und Robotik werden nicht ausgeführt.

## Einstieg und Bediengrenzen

```sh
python3 scripts/run_dneasy_extraction.py --help
python3 scripts/run_dneasy_extraction.py --store exports/dneasy-demo/workflows.sqlite3 demo --run-id SYN.DNEASY.DEMO01
python3 scripts/run_dneasy_extraction.py --store exports/dneasy-demo/workflows.sqlite3 report SYN.DNEASY.DEMO01
```

Die Demo erzeugt ausdrücklich erfundene Anfangsmengen, ausgegebene
Reagenzaliquots, positive Prozessbestätigungen und Messergebnisse. Die
Produktvolumina sind Testbeobachtungen und keine Ertragsprognose. Der normale
Runner erzeugt solche Bestätigungen nicht automatisch.

Für eine unabhängige Wiederholung einen **neuen synthetischen Store** verwenden.
Die festen Material-/Aliquotkennungen des Profils dürfen nicht erneut frisch
in denselben Store eingeführt werden; eine neue Laufkennung setzt keinen
Bestand zurück. Laufübergreifende Stock-/Ownerübernahme bleibt offen.
Ohne `--store` gilt die vorhandene gemeinsame Standard-Store-Auflösung.

`create` legt nur den frischen Lauf an. `status` und `report` lesen ohne
Sitzungsübernahme. `resume RUN_ID` übernimmt die Sitzung ausdrücklich und
verlangt danach Inventar- und gegebenenfalls Wirkungsabgleich.
Einzelne synthetische Beobachtungen lassen sich über `act` angeben:

```sh
python3 scripts/run_dneasy_extraction.py --store exports/dneasy-manual/workflows.sqlite3 create --run-id SYN.DNEASY.MANUAL01
# Erst nach vollständigem accept_inventory-Abgleich:
python3 scripts/run_dneasy_extraction.py --store exports/dneasy-manual/workflows.sqlite3 act SYN.DNEASY.MANUAL01 --session SESSION --actor SYN.DNeasy.Operator --action workspace_clear --data '{"confirmed":true}'
```

`SESSION` stammt aus `create` beziehungsweise `resume`. Zuerst ist das
vollständige deklarierte Inventar über `accept_inventory` zu bestätigen;
danach folgen Arbeitsplatzfreigabe und `claim`. Es gibt keine automatische
Scanner- oder Personenbeobachtung. `--out` schreibt neue JSON-Berichte nur
unter `exports/` und überschreibt keine vorhandenen Belege.

Mit `demo --pause-after before_confirm:resuspend_pbs` bleibt eine bestätigungspflichtige
Absicht offen. Weitere Pausen sind nach benannten Phasen, bei `extracted` oder
`tapestation_loaded` möglich. Eine Pause oder ein Prozessabbruch bestätigt
weder Durchführung noch Rückgabe. Eine Fortsetzung braucht die bestehenden
Kennungen und einen ausdrücklichen Abgleich, keine neu gestartete Demo.

## Quellen, Identitäten und Materialfraktionen

Die [Puregene-Erweiterung](puregene-extraction.md) verwendet inzwischen
denselben geordneten Extraktionskern sowie dieselbe QC-, Demo- und CLI-Hülle.
`DNeasyWorkflow` bleibt ein eigener schmaler Quellen-/Berichtsadapter mit dem
bisherigen Engine-Guard. Die Auslagerung dupliziert keine Chemie oder Bilanz;
alte Quellenpins werden nicht auf neue Bytes umgeschrieben.

| Quelle | Verantwortung |
|---|---|
| `model/extraction-automation.*.json` | Unveränderte E1-Kitrollen, DNA-Eingang und geplante Eluatidentität |
| `model/dneasy-extraction.protocol.json` | Geordnete DNeasy-Zellschritte und sachliche Herstellerparameter |
| `model/dneasy-extraction.synthetic.json` | Ein DNA-Testfall, explizite ausgegebene Aliquots, Gefäße, Beobachtungsmengen und synthetische QC-Politik |
| `model/dneasy-extraction.schema.json` | Formaler Profil-/Protokollvertrag |
| `scripts/dneasy_extraction_sources.py` | Quellenpins, DNA-Auswahl, semantische Prüfung und abgeleitete Ausführung |
| `scripts/dneasy_extraction_workflow.py` | Geordnete Absichten, Bestätigungen, Zeit- und QC-Sperren im gemeinsamen Material-Root |
| `model/tapestation-gdna.protocol.json` und Schema | Separater synthetischer Genomic-DNA-ScreenTape-Vertrag mit TS01-Referenz |
| `scripts/tapestation_results.py` | Reiner Decoder und ausdrücklich synthetische QC-Auswertung ohne Bestandswirkung |

Der Loader wählt die DNA-Linie aus dem unveränderten E1-Plan aus. Es wird
kein fiktives RNA-Aliquot als Voraussetzung eingeführt. E1 bleibt
`preparation_only` und `execution_ready: false`. Die neue Laufart verwendet
das vorhandene Material-Formatpaar `/2` mit dem eigenen Typ und Engine-Guard
`dneasy_synthetic/1`. Bestehende E1-, E2-, CUT&RUN-, Mess- und Transportläufe
werden weder geöffnet noch still migriert.

Ein Root führt Material, physische Gefäße, Orte, Buchungen, Absichten und
Ressourcen. `MaterialWorkflow`, `material_ledger.py` und das bestehende Journal
werden wiederverwendet. Eingangszellen, Lysat, beladene Säule, gebundene DNA,
Bindedurchfluss, beide Waschabfälle, Eluat und Säulenrest haben getrennte
Identitäten. Neue Sammelgefäße werden ausdrücklich bestätigt. Durchfluss und
Säulenfraktion dürfen nicht verwechselt werden.

Die Masse der gebundenen DNA bleibt unbekannt (`ng: null`). Zellzahl und
Flüssigkeitsvolumen ergeben keine DNA-Masse. Auch nach Elution bleibt der
Säulenrest eine eigene Fraktion bis zur bestätigten Disposition. Produkte
werden behalten; Abfall, Messansätze und Reagenzreste benötigen ihren eigenen
bestätigten Verbleib. Es gibt keine pauschale Entsorgung aller abgeleiteten
Gefäße als Abschlussbedingung.

## Prozess und Wiederanlauf

Die Quelle trennt Reagenzbereitschaft, Resuspension, Proteinase-K-Zugabe,
ausdrückliche RNase-Auswahl vor AL, Lyse, Bindebedingungen, Säulenbeladung,
Waschschritte, Trocknung und Elution. Eine Phase verlangt vor der
Durchführungsbestätigung eine dauerhaft gespeicherte Absicht. Materialeffekte
und Phasenfortschritt werden atomar bestätigt; wiederholte identische Belege
buchen nicht erneut. Generische Materialbefehle umgehen die Reihenfolge nicht.

Mischen, Heizen und Zentrifugieren besitzen eigene Prozessbelege, auch ohne
Materialbuchung. Zeit schreitet nur durch protokollierte synthetische
Zeitereignisse voran. Mindestzeiten, beobachtete Temperatur und erforderliche
RCF werden geprüft; RPM ersetzt keine Zentrifugalkraft. CF01 wird dafür nicht
als geeignet angenommen oder gestartet.

Die erste Fassung beginnt mit einem vorhandenen Zellpellet und wählt genau
eine Elution. Zusätzliche Ernte, zweite Elution, Ethanol-Übertragskorrektur und
eine automatische Wiederholung nach Nichtdurchführung sind nicht implementiert.
Ein nicht geklärter oder abweichender Ablauf hält an; ein solcher Lauf darf
nicht nachträglich als normal erfolgreich gelten.

Nach Neustart bleiben Absicht und Reservierungen erhalten. `resolve_effect`
unterscheidet `performed`, `not_performed` und `unknown`; ein unbekannter
Ausgang bleibt gesperrt. Danach ist vollständiges `reconcile` erforderlich.
Eine bestätigte Nichtdurchführung erlaubt in dieser ersten Fassung Abbruch
und Abgleich, keine neue Ausführung unter frisch erfundenen Ausgangsidentitäten.
Auch Abbruch verlangt geklärte Wirkungen, Dispositionen und Inventar.
Nach Anlegen eines TapeStation-Auftrags ist zusätzlich
`confirm_tapestation_abort` erforderlich: Instrumentstillstand, Rücknahme beider
Ansätze und deren Identitäten werden ausdrücklich synthetisch bestätigt und
an Instrumentlauf/Analyse gebunden. `cancel` allein ist weder ein Geräte-Stopp
noch eine Freigabe der TS01- oder Arbeitsplatzreservierung. Diese Fassung
unterstützt einen TapeStation-Messversuch pro Lauf, keine automatische Wiederholung.

## TapeStation: Vorbereitung, Messende, Import und Bewertung

Das Standard-Genomic-DNA-ScreenTape-Profil referenziert 5067-5365 und
5067-5366. Eine QC-Probe und ein eigener Ladder-Ansatz werden mit getrennten
Absichten und Reagenzbuchungen vorbereitet. So erhält der Ladder-Ansatz
keinen falschen DNA-Probenelternbezug. Die Demo bestätigt 1 µl Eluat und
10 µl Sample Buffer sowie separat 1 µl Ladder und 10 µl Sample Buffer.
Das Originaleluat wird nur bei dieser Entnahme belastet; Import und Review
erzeugen keinen weiteren Verbrauch.

Reagenzbereitschaft, Mischung, kurzes Zentrifugieren, Beladung, Lanezuordnung,
Laufende und Ladder-Annahme sind getrennte manuelle/synthetische Belege.
Die konkrete Zuordnung der Sample-Lane ist eine Fixtureentscheidung, keine
geprüfte Registrierung im Gerät. TS01, Instrumentlauf, Analyse, Messung,
Sample, Eluat, QC-Material, Gefäß und Inhaltsrevision werden ausdrücklich
gebunden; Zeilenfolge und Probenname sind keine Identitätsnachweise.

Der Import akzeptiert ausschließlich das begrenzte, ausdrücklich markierte
Format `solidcraftbot.synthetic-tapestation-report/1`. Unveränderte
Originalbytes und SHA-256 bleiben im selben Journal erhalten. Dies ist
**kein Decoder eines geprüften Agilent-Exports**, kein Controller und kein
Netzwerkadapter. Gleiche Datei erneut zu importieren verbraucht keine Probe;
widersprüchliche oder fremde Kennungen dürfen keine vorhandene Messung ersetzen.

DIN und Fragmentgröße bleiben eigene Metriken. DIN ist keine Basenpaarzahl;
eine Peakgröße ist kein automatisch berechneter Verteilungs-Mittelwert.
Nullwerte, unbekannte Flags und zensierte Größen verhindern einen stillen
Erfolg. Eine Größe oberhalb des Referenzbereichs wird nicht als präzise
Zahl erfunden. Das Profil besitzt ausdrücklich synthetische Schwellenwerte,
keine QIAGEN- oder Agilent-Freigabekriterien. Import allein gibt nichts frei;
eine eigene fachliche Entscheidung und die bestätigte Entsorgung beider
Messansätze gehen dem Gesamtabschluss voraus.

Die optional berichtete Probenkonzentration besitzt ihren eigenen Probenbezug
und dient der Prüfung des DIN-Funktionsbereichs. Sie wird weder aus dem
Ansatzvolumen berechnet noch nochmals um den Sample-Buffer-Anteil korrigiert.
Eine instrumentinterne Aspiration wird hier nicht als gemessener Volumenverbrauch
modelliert; die angesetzten Restgemische werden ausdrücklich entsorgt.

## Herstellergrundlage und Prüfgrenzen

Die sachlichen DNeasy-Parameter stammen aus
[HB-2061-004, Juni 2023, Zellprotokoll S. 29–32](https://www.qiagen.com/en-US/resources/download/KitHandbook/hb-2061-004-hb-dny-blood-tissue-0623-ww).
Die TapeStation-Referenz ist der
[Genomic DNA ScreenTape Quick Guide, G2991-90041 Rev. D, Ausgabe 03/2026](https://www.agilent.com/cs/library/usermanuals/public/gDNA_QuickGuide.pdf).
Der Guide unterscheidet den Größenbereich von den engeren Bereichen für
spezifizierte Größenpräzision/-genauigkeit sowie Quantifizierung und DIN.
Diese Herstellerangaben sind keine Qualifikation unseres Ablaufs.

```sh
python3 -m unittest discover -s tests -p 'test_dneasy_extraction*.py' -v
python3 -m unittest discover -s tests -p 'test_tapestation_results.py' -v
```

Die gezielten Tests prüfen Quellenbindung, Reihenfolge, Einheiten,
Fraktionen/Abstammung, Istverbrauch, Zeiten/Beobachtungen, Wiederanlauf,
Abbruch, Idempotenz, Originalartefakte und QC-Zuordnung. Es bestanden 61 neue
Fälle (12 Quellen-/Schema-, 22 Ablauf-, 22 Decoder- und fünf CLI-/Abnahmefälle)
sowie 93 bestehende Vorbereitungs-/Materialregressionen ohne übersprungene
Tests. Das ist eine gezielte Prüfung, keine vollständige Repository-/CAD-Suite.
Die neue Funktion
führt keine reale SOP oder Extraktion durch. Rotor-/Säulenpassung,
Pipettierleistung, Temperierung, Kontaminationskontrolle, Fragmentgrößen,
Ausbeute, Roboterbahnen und Schutzfunktionen bleiben unqualifiziert.
Insbesondere ist die projektweite fließende Bewegungsvorgabe weiterhin eine
Anforderung für spätere Bewegungsadapter; hier wird keine Bahn erzeugt.
