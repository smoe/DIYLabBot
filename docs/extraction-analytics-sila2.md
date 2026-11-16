# Extraktionsanalytik über den bestehenden DNA-SiLA-Dienst

Das additive SiLA-Feature `ExtractionAnalyticsWorkflow` v1.0 bindet die
[integrierte Extraktionsanalytik](extraction-analytics.md) an den vorhandenen
[DNA-SiLA-Server](dna-sila2-network.md). Beide Features verwenden dieselbe
TLS-Identität, ServerUUID, Authentifizierung, LockController-v1.0-Sperre und
dieselbe `workflows.sqlite3`. Es gibt keine zusätzliche Probenbilanz oder
Transportdatenbank.

Die neue Feature wählt beim Anlegen entweder die gepinnte DNeasy- oder
Puregene-Komposition. Sie führt deren bestehende Folge
**Extraktion → NanoDrop One → Qubit 4 HS → TapeStation** aus.
Alle chemischen, manuellen und analytischen Beobachtungen bleiben ausdrücklich
synthetisch. SiLA transportiert Workflowentscheidungen; es steuert hier kein
Laborgerät und keinen Roboter.

## Quellen und Verträge

`model/extraction-analytics-sila2.protocol.json` führt die neue Feature,
Familienbindungen, Befehle und Quellenpins. Das zugehörige Schema prüft den
Quellenvertrag. `scripts/build_extraction_analytics_sila2.py` erzeugt die FDL
unter `exports/generated/`; sie ist kein weiteres führendes Rezept.
Die bisherige Feature `DnaQuantificationWorkflow` v1.0 und die archivierten
Standard-FDLs werden nicht umgeschrieben. Die neue Feature ist `Draft`;
daraus folgt keine SiLA-Zertifizierung oder GENtle-Bindung.

| Befehl | Wirkung |
|---|---|
| `CreateRun` | Neue synthetische Testwelt für `dneasy` oder `puregene` ausdrücklich anlegen |
| `RunUntilDecision` | Den bestehenden Root bis zum Abschluss oder einer erforderlichen Entscheidung fortführen |
| `ResumeRun` | Sitzung und Bootbezug ausdrücklich übernehmen; keine Wirkung wiederholen |
| `ReconcileRun` | Begrenzte ausdrückliche Wirkungs- und Inventarbeobachtungen prüfen |
| `CancelRun` | Abbruchabsicht im Root setzen; Ressourcen bleiben gehalten |
| `FinishCancel` | Geklärte Wirkungen, Dispositionen und vollständiges Inventar vor Freigabe bestätigen |

`Status` und `Report` sind lesend. Es gibt weder eine generische `Act`-RPC
noch Netzwerkbefehle für Pipettieren, Zeitfortschritt oder einzelne
Gerätebestätigungen. Die Familie wird einmalig beim Anlegen gebunden; ein
Client kann keinen beliebigen Profilpfad einschleusen. Die positiven
Beobachtungen und Messwerte stammen ausschließlich aus dem gepinnten
synthetischen Ausführungstreiber.

## Bedienung

Initialisierung und Serverstart verwenden unverändert die privaten
Zugangsdateien und die bewusst gewählte TLS-Identität des DNA-Dienstes.
Zugangsdaten gehören ausschließlich unter `exports/`, nicht in Modellquellen,
Argumente oder Berichte. Der vorhandene Dienst startet beide Features.

```sh
python3 scripts/run_dna_sila2.py --help
python3 scripts/build_extraction_analytics_sila2.py
python3 scripts/run_dna_sila2.py status --feature extraction --ready-file exports/dna-server/ready.json --login-input exports/private-dna-client-login.json
```

Die lokale Datei `exports/extraction-create.json` enthält beispielsweise nur:

```json
{"family_identifier":"puregene"}
```

Ein neuer Request und ein ausdrücklich benannter Lauf legen diese Testwelt an:

```sh
python3 scripts/run_dna_sila2.py command --feature extraction --ready-file exports/dna-server/ready.json --login-input exports/private-dna-client-login.json --run-id SYN.Extraction.Network01 --request-id Create.Extraction.01 --name CreateRun --arguments-input exports/extraction-create.json
python3 scripts/run_dna_sila2.py command --feature extraction --ready-file exports/dna-server/ready.json --login-input exports/private-dna-client-login.json --run-id SYN.Extraction.Network01 --request-id Run.Extraction.01 --name RunUntilDecision --timeout 180 --lease-timeout 180
python3 scripts/run_dna_sila2.py report --feature extraction --ready-file exports/dna-server/ready.json --login-input exports/private-dna-client-login.json
```

Die Familienprofile besitzen feste Material- und Aliquotkennungen. Eine neue
Laufkennung darf diese nicht frisch in denselben Store einführen oder
Restmengen zurücksetzen. Für unabhängige Fixture-Wiederholungen ist ein bewusst
neues privates Serververzeichnis mit eigenem synthetischem Store erforderlich;
dies ist keine Bestandsfortsetzung oder Übernahme realer Proben.

Ohne `--feature extraction` bleibt die bisherige DNA-Feature die Vorgabe.
Ein Netzwerk-Timeout ist kein Abschlussbeleg. Nach Antwortverlust zuerst den
lesenden Bericht und die eigene gespeicherte Requestquittung prüfen;
keinen neuen Request als automatische Wiederholung eines unklaren Effekts
verwenden. Ein unveränderter Request desselben Principals liefert seine
gespeicherte Quittung. Eine andere Verwendung derselben Kennung wird abgelehnt.
Die Request-Kennungen gelten serverweit über beide Features, alle an dieselbe
ServerUUID gebundenen DNA-/Extraktionsläufe und Bootwechsel hinweg; ihr flüchtiger
Index wird aus dem Root-Journal unter dem gemeinsamen Host-Mutex aufgebaut und
vor jeder neuen Wirkung abgeglichen.

Eine Ausnahme nach eigener gespeicherter Quittung sperrt neue Effekte des
aktiven Laufs. Halt und Abschluss werden bestmöglich im Root-Journal
gespeichert; schlägt auch dies fehl, wird die lokale Schreibsitzung verworfen.
Die Fortsetzung benötigt dann ausdrücklich `ResumeRun` und Abgleich. Andere
noch offene Quittungen werden bei der Wiederaufnahme auch im selben Boot
`uncertain`. SQLite-Fehler erscheinen als `PersistenceFailure`; terminale
Rootzustände und bereits bestätigte Buchungen werden nicht zurückgerollt.

## Eigentum, Quittungen und Wiederaufnahme

Der bestehende Material-Root führt weiterhin Probe, Produktmaterial,
physisches Gefäß, Ursprungsplatz, Inhaltsrevision, Reagenzverbrauch und
Reservierungen. Netzwerkquittung und erste Wirkung werden im selben Root
gespeichert. Principal, verantwortliche Person, ausführender Agent und
Materialgewahrsam bleiben verschiedene Rollen. Netzwerksperre und Token
werden vor weiteren Wirkungen erneut geprüft.

Der SiLA-Ausführungstreiber setzt an bestätigten Phasen und gespeicherten
Gerätebelegen fort. Er startet weder eine neue Demo noch einen neuen
Anfangsbestand. Offene Absichten werden nach Unterbrechung oder Serverneustart
nicht wiederholt. `ResumeRun` entwertet die alte Sitzung; unvollständige
Quittungen bleiben als unsicher erhalten. Lokale Analytics-CLI-Zugriffe auf
gebundene Läufe bleiben lesend; sie dürfen keine Sitzung, Wirkung oder
Freigabe am SiLA-Root vorbei verändern.

Auch nach einem bereits bestätigten Root-Abschluss kann `ResumeRun` eine
unterbrochene Quittung ausdrücklich als unsicher markieren. Dabei ändern sich
weder Material, Mengen noch freigegebene Ressourcen; terminale Arbeit wird
nicht erneut ausgeführt. Andere neue Effektbefehle bleiben auf terminalen
Läufen gesperrt. Der gespeicherte Rootbericht und ursprüngliche Request bleiben
die Grundlage des Abgleichs.

Nach Neustart eines bereits angelegten TapeStation-Auftrags ohne gespeicherte
Laufendebestätigung ist die normale Fortsetzung gesperrt. Dieser Fall benötigt
`CancelRun` und den ausdrücklichen Stillstands-/Rücknahmebeleg in `FinishCancel`.
Eine Inventarbeobachtung ersetzt die fehlende Instrumentlaufbestätigung nicht.
Bereits gespeicherte Laufendebelege bleiben dagegen erhalten; ein fehlender
Import rechtfertigt keine zweite Messung oder Probenentnahme.

`ReconcileRun` verlangt ausdrücklich erklärte Beobachtungen im begrenzten
Format `solidcraftbot.extraction-analytics-reconciliation/1`. Es umfasst den
Grund, vollständige Gefäß-/Material-/Ortsbeobachtungen und die
Arbeitsplatzbeobachtung. Gegebenenfalls wird zusätzlich genau die bestehende
Extraktions-/TapeStation-Ansatzabsicht oder Geräteabsicht aufgelöst. Die
Auflösung unterscheidet `performed`, `not_performed` und `unknown` und nutzt
die vorhandenen Mengen-, Identitäts- und Revisionsprüfungen. Das beobachtete
Inventar beschreibt den Zustand nach der ausdrücklich erklärten Auflösung.
Der Server validiert die Erklärung an einer nicht gespeicherten Proposal-Kopie;
er erzeugt keine angeblichen Beobachtungen aus seinem eigenen Ledger.

`unknown` hält Ressourcen. Eine bestätigte Nichtdurchführung ermöglicht in
dieser ersten Komposition kontrollierten Abbruch, keine automatische neue
Ausführung. Ein nachträglicher Blank-/Kalibrierungsbeleg ersetzt keine
Gerätebeobachtung und verlängert keine gemessene Kalibrierungsserie.

`FinishCancel` benötigt darüber hinaus ausdrückliche Materialdispositionen
und gegebenenfalls bestätigte Entsorgung identifizierter Qubit-Ansatzgefäße.
Ein vorhandener TapeStation-Auftrag benötigt weiterhin seinen eigenen
identitätsgebundenen Beleg über Stillstand, Rücknahme und Materialabgleich.
Ein bekannt fehlerhaftes DNA-Produkt darf beim kontrollierten Abbruch
quarantänisiert bleiben; es muss nicht für die Freigabe der Arbeitsressourcen
als normal aufbewahrt umetikettiert werden. Produkt- und Gefäßidentität sowie
die bestätigte Rückgabe bleiben erhalten. Ein normal erfolgreicher Abschluss
verlangt weiterhin das aufbewahrte Produkt und alle fachlichen Freigaben.
Sperrablauf, Logout und `CancelController.CancelCommand` geben keine
Laborressourcen frei. Letzterer stoppt nur die betreffende Ausführung an einer
Transitionsgrenze; `CancelRun` ist die gesonderte Root-Abbruchabsicht.

## Berichte und Prüfgrenzen

Der Netzwerkbericht erhält das aktuelle Inventar, Buchungen, Gerätebelege,
Quittungen, Originalartefakt-Prüfsummen und Qualifikationskennzeichen.
Historische Trace-Zustände werden für den begrenzten SiLA-String nur als
Metadaten übertragen; das vollständige Journal bleibt lokal unverändert.
Diese Projektion wird ausdrücklich markiert und ist kein vollständiger
Rohjournalexport. Generierte Quell-FDL und vom SDK ausgelieferte XML-Bytes
bleiben getrennte Belege.

Interne Laufzeitlesezugriffe verwenden den vorhandenen geprüften Journal-
Präfixcache. Konstruktion, Wiederaufnahme, vollständiger Bericht und
Abschlussprüfungen behalten ihre vollständigen Audits; der Cache ersetzt
keine Quellen-, Sitzungs- oder Materialprüfung.

TLS/gRPC über Loopback ist von Gerätekommunikation und Laborprozessierung
zu unterscheiden. Die vorhandenen Konzentrations- und TapeStation-Bereiche,
Qubit-Ansatz-/Kalibrierungszuordnung, fließende Bewegungsvorgabe und sämtliche
Grenzen für reale Extraktion, Pelletsicherung, Flüssigkeitshandhabung, lokale
SOP, native Exporte, biologische Leistung und Sicherheit bleiben erhalten.
Es gibt keine neue ROS-Ausführung, Roboterbahn, Hardware-, LAN- oder formale
SiLA-Qualifikation. Stock-/Ownerübernahme und alte Journalmigration bleiben
unimplementiert. Geänderte Quellenpins sperren aktive Fortsetzungen.

```sh
python3 -m unittest discover -s tests -p 'test_extraction_analytics_sila2_contract.py' -v
python3 -m unittest discover -s tests -p 'test_extraction_analytics_sila2_control.py' -v
python3 -m unittest discover -s tests -p 'test_extraction_analytics_sila2_runtime.py' -v
SOLIDCRAFTBOT_SILA_NETWORK_TESTS=1 python3 -m unittest discover -s tests -p 'test_extraction_analytics_sila2_network.py' -v
```

Die Netzwerktests benötigen die vorhandene Umgebung aus
`requirements/sila2-test.lock` und verwenden echte lokale TLS-Verbindungen
zu einem separaten Serverprozess. Übersprungene Tests sind kein bestandener
Netzwerknachweis. Historische Medien, Galerie und Provenienz bleiben unverändert.

Die gezielte Prüfung deckt 37 neue Fälle ab (10 Vertrags-, 11 Kontroll-,
acht Laufzeit- und acht TLS-Prozessfälle) sowie 138 bestehende Regressionsfälle,
darunter zehn TLS-Fälle der bisherigen DNA-Feature. Alle ausgewiesenen Fälle
sind ohne Skips bestanden. Die letzte Änderung am Quarantäne-Abbruchpfad wurde
zusätzlich mit den betroffenen Laufzeit- und vollständigen TapeStation-TLS-
Fällen geprüft; versionsgebundene frühere Läufe bleiben getrennt erhalten.
Dies ist keine vollständige Repository-, CAD-, Hardware- oder LAN-Prüfung.
