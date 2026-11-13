# CUT&RUN-Inputsonikation über SiLA 2

Der separate Adapter bietet die vorhandene [S09-Fixture-Engine](cutrun-input-sonication-runtime.md)
über TLS/gRPC auf Loopback an. Der CUT&RUN-Root bleibt Eigentümer von
Inventar, Gewahrsam, Materialbuchungen, Originalartefakten und Reservierungen.
Netzwerkquittungen liegen in demselben Root-Journal. Ein S09-Abschluss ist
weiterhin kein Abschluss des gesamten CUT&RUN-Laufs.

Die Ausführung bleibt `test_clock` und `test_fixture`. Ultraschall, Gerät,
Robotik, ROS und Flüssigkeitshandhabung werden nicht ausgeführt. Fehlendes
Herstelleroriginal, offene reale Anforderungen und die deaktivierte
Standardvorlage bleiben erhalten. Login und TLS machen aus einem Fixture
keine authentifizierte Laborbeobachtung oder reale Gerätefreigabe.

## Quelle und Einstieg

`model/cutrun-input-sonication-sila2.protocol.json` ist der nichtgeometrische
Netzwerkvertrag. Er referenziert S09-Komposition und Beispieldaten mit SHA-256,
pinnt die unveränderten Standard-FDLs samt Provenienz und bindet die verwendeten
lokalen Python-Helfer einschließlich Authentifizierung und Client. Der Builder
`scripts/build_cutrun_input_sonication_sila2.py` erzeugt
`CutRunInputSonicationWorkflow` v1.0 im Status `Draft` unter `exports/generated/`.
Es gibt keine neue Galerieansicht oder Geometriequelle.

Vorhandene Abhängigkeiten aus `requirements/sila2-test.lock` werden verwendet.
Es werden weder ROS noch neue Pakete installiert. Die Bedienhilfe ist auf
Deutsch und Englisch verfügbar; technische Feature-/Befehlskennungen bleiben
stabil auf Englisch.

```sh
python3 scripts/run_sonication_sila2.py --language de --help
python3 scripts/run_sonication_sila2.py --language en --help
python3 scripts/build_cutrun_input_sonication_sila2.py
python3 scripts/run_sonication_sila2.py init \
  --directory exports/sonication-server \
  --credentials-input exports/private-sonication-users.json \
  --credentials exports/sonication-server/users.json
python3 scripts/run_sonication_sila2.py serve \
  --directory exports/sonication-server \
  --credentials exports/sonication-server/users.json \
  --tls-directory exports/sonication-server/tls \
  --ready-file exports/sonication-server/ready.json
```

Die private Benutzereingabe ist eine JSON-Liste aus `username`, `password`
und `role` (`operator` oder `observer`). Die separate Client-Login-Datei enthält
`username` und `password`. Zugangsdaten, Token und private Schlüssel gehören
nicht in Git, Logs, Nachweise oder Videos. Ready-Datei, öffentliche ServerUUID
und bewusst gewähltes Zertifikatsvertrauen binden die Gegenstelle. Falsches
Zertifikat, falsche UUID und unverschlüsselte Verbindungen werden abgewiesen.
TLS-Identität und Prozesssperre sind adaptereigen; CF01-Helfer bleiben unverändert.

Ein zweiter Prozess kann den vollständigen normalen Softwarefall ausführen:

```sh
python3 scripts/run_sonication_sila2.py scenario \
  --ready-file exports/sonication-server/ready.json \
  --login-input exports/private-sonication-client.json \
  --run-id TEST.S09.Network01 --out exports/sonication-scenario-01.json
```

Jede Ausgabe wird vor dem ersten Dispatch auf vorhandene Dateien und nicht
als Verzeichnis nutzbare Vorfahren geprüft. Eine Wiederholung setzt weder
Fixture-Dateien noch Material zurück. Szenarioidentitäten sind aus der
gepinnten Fixturequelle gebunden; gehaltene Gefäße können nicht unter einem
zweiten Lauf erneut eingeführt werden. Getrennte Stores sind ausdrücklich
getrennte synthetische Testwelten, keine Fortsetzung eines realen Bestands.

## Fachliche Oberfläche und atomare Quittungen

`Status` und `Report` sind Properties mit reinem Lesezugriff. Der Dienst bietet
`CreateRun`, das beobachtbare `RunUntilDecision`, `ResumeRun`, `ReconcileRun`,
`CancelRun` und `FinishCancel`. Jeder Effektbefehl bindet Request- und Run-ID.
Nur `CreateRun` wählt einmalig `normal`, `restart` oder `cancel` aus der
Fixturequelle. Es gibt kein generisches `Act`, keine frei bestätigbaren
Geräteschritte und keine Testpause im Wire-Vertrag.

Der Wire-Bericht kennzeichnet sich zusätzlich als
`solidcraftbot.s09-sila2-wire-report/1`: Er enthält den aktuellen Rootzustand,
Bilanz, Belegreferenzen und die Hashkettenmetadaten aller Ereignisse, aber
keine wiederholten historischen Vollzustände in `trace`. Damit bleibt der
Bericht innerhalb der SiLA-Stringgrenze. Der Offline-Bericht und der
Nachweisexport enthalten weiterhin die vollständigen Originaljournale.

Der Root speichert die erste Netzwerkquittung im selben CAS-Commit wie die
erste Wirkung, auch bei Laufanlage und Wiederaufnahme. Weitere Transitionen
tragen dieselbe Korrelation; `command_finished` hält den Abschluss fest.
Eine identische Wiederholung durch denselben Principal liefert den gespeicherten
Ausgang ohne neues Ereignis oder Dispatch. Eine andere Verwendung derselben
Request-ID wird abgewiesen. Ein noch `accepted` oder später `uncertain`
erscheinender Auftrag ist kein Wiederholungsauftrag. RPC-Timeout, getrennte
Verbindung, Command-Annahme und fachlicher Abschluss sind verschiedene Zustände.

Netzwerk-Principal, deklarierter Fixture-Akteur und Gefäßort bleiben getrennt.
Der zusätzliche `network_receipt` ersetzt die bestehende
`material_evidence.provenance=test_fixture` nicht. Normale Rootübergänge,
Beobachtungsablehnungen und Kontrollerereignisse behalten ihre Systemfelder.
Quellen- und Helferdrift sperrt neue Schreibvorgänge. Auf neuen gebundenen
Läufen darf die bisherige lokale S09-CLI weiter Status/Report lesen, aber weder
schreiben, resumieren noch schließen. Bestehende Standalone-Läufe werden nicht
an einen Server gebunden oder still migriert.

## Wiederaufnahme, Abgleich und Abbruch

`ResumeRun` rotiert Sitzung und Boot-Fence atomar. Alte offene Quittungen werden
`uncertain`, Absichten und Holds bleiben erhalten. Sonikation und QC werden
nicht erneut dispatcht. Eine neue Testuhrdomäne benötigt den vorhandenen
ausdrücklichen Zeitlückenabgleich, bevor regulär weitergearbeitet wird.

Auch ein Abbruch direkt nach dem atomaren `created`-Commit und vor der ersten
Inventarannahme ist wiederaufnehmbar. Ausschließlich der Netzwerk-Subclass
erlaubt hierfür `accept_inventory` während des Abgleichs; der bestehende Handler
fordert weiterhin den Anfangszustand und die unveränderten Anfangsorte.

`ReconcileRun` und `FinishCancel` nehmen ein begrenztes JSON-Dokument im Format
`solidcraftbot.s09-fixture-reconciliation/1` an. Es enthält ausdrücklich
gewählte Fixturebelege: Grund, `decision_evidence`-Referenz, vollständige
Gefäß-/Material-/Ortsbeobachtungen, Arbeitsplatzbeobachtung, gegebenenfalls
Zeitlückenintervall und Ausgang der offenen Sonikationsabsicht. `performed`
benötigt das richtige Gefäß und die gepinnte Testmenge. Das beobachtete Inventar
beschreibt den Zustand **nach** dieser erklärten Auflösung. Der Server prüft
es vorab an einer nicht gespeicherten Ledger-Proposal-Kopie.

Der Client muss diese synthetischen Beobachtungen ausdrücklich erklären.
Der Server erstellt keinen Abgleich aus seinem eigenen Ledger. Der
Client-Helfer `reconciliation_document` ist ausschließlich eine sichtbar
synthetische Vorschlagsfunktion, kein Scan, Sensor oder Personenbeleg.
`unknown` hält Ressourcen. `FinishCancel` braucht darüber hinaus ursprüngliche
Rackrückgabe und vollständige ausdrückliche Materialdispositionen; verbrauchte
Elternmaterialien werden nicht umetikettiert.

Auch eine unterbrochene S02-Inputvorbereitung oder S09-QC-Entnahme benötigt
einen erreichbaren ausdrücklichen Abgleich. Das optionale Dokumentfeld
`material` identifiziert dafür ausschließlich eine dieser beiden bereits
offenen Absichten. `performed` verlangt die ausdrücklich erklärten, gepinnten
Testmengen in `actual_inputs` und `actual_outputs`; `unknown` und
`not_performed` tragen keine erfundenen Mengen. `sonication` und `material`
dürfen nicht gleichzeitig eine Wirkung erklären. Nach bestätigtem Abgleich
setzt die Fixture bereits abgeschlossene Stufen und Belege anhand ihrer
gespeicherten IDs fort: kein zweiter S01-Abschluss, keine wiederholte
Vorbereitung und keine zweite QC-Entnahme. Fehlende synthetische Temperatur-
oder Größenoriginale können ergänzt werden, ohne die Wirkung zu wiederholen.

`CancelController.CancelCommand` stoppt nur die betreffende Ausführung an
einer Transitionsgrenze. `CancelRun` setzt dagegen die Abbruchabsicht des
**gesamten Root**, nicht einer separaten Stage-Cancel-Zustandsmaschine.
Erst `FinishCancel` erfüllt die vorhandenen Freigabebedingungen. LockController
bleibt v1.0: Leaseablauf und Logout sperren Folgeeffekte, geben aber keine
Laborressource frei. `StartRealMode` wird abgewiesen.

## Nachweise und Prüfungen

Der fachliche Rootbericht behält seine Fixture-Grenzen. `transport_receipts`
weist die tatsächlich verwendete SiLA-Loopback-Grenze separat aus. Der neue
Nachweisexport `scripts/sonication_sila2_evidence.py` verwendet einen eigenen
versionierten Netzwerkmanifestvertrag. Er bindet ursprüngliche Journaldokumente,
Kettenköpfe, Originalartefakte, Quellenabschluss, Netzwerkquittungen, öffentliche
TLS-Identität und Testlogs. Generierte Quell-FDL und vom SDK ausgelieferte
XML-Bytes werden getrennt gebunden, nicht bytegleich behauptet.
Der Export weist auch das eigene Credentialformat mit Passwort-Hashes sowie
Token in CamelCase-Schreibweisen zurück. Ein erlaubter Dateiname wie
`users.json` macht solche privaten Inhalte nicht zu einem öffentlichen Testlog.

Neue schematische Bilder/Videos entstehen ausschließlich unter
`exports/sonication-evidence/`. Sie trennen logische Testprozesszeit,
Server-/Journal-Erfassungszeit und geraffte Videozeit. Netzwerkkennzeichen
benötigen gespeicherte Loopbackquittungen und gebundene Nachweise. Sie beweisen
keine Hardware, Biochemie, ROS-Ausführung, LAN-Qualifikation oder Zertifizierung.
Historische Fixturemanifeste mit „SiLA nicht ausgeführt“ werden weder
umetikettiert noch neu gerendert; ihre bestehenden Prüfer bleiben erhalten.

```sh
python3 -B -m unittest discover -s tests -p 'test_sonication_sila2_contract.py' -v
python3 -B -m unittest discover -s tests -p 'test_sonication_sila2_control.py' -v
python3 -B -m unittest discover -s tests -p 'test_sonication_sila2_runtime.py' -v
python3 -B -m unittest discover -s tests -p 'test_sonication_sila2_evidence.py' -v
SOLIDCRAFTBOT_SILA_NETWORK_TESTS=1 python3 -B -m unittest discover \
  -s tests -p 'test_sonication_sila2_network.py' -v
```

Die Netzwerktests verwenden getrennte Prozesse und tatsächliche Loopback-TLS-
Verbindungen, darunter einen SIGKILL nach persistierter Sonikationsabsicht.
Ohne Schalter übersprungene Tests sind kein Netzwerknachweis. Die vorhandenen
P2-Negativfälle für Ausgabevorfahren und widersprüchliche Größenbefunde bleiben
Teil der Regression. Medien, Galerie, Herstelleroriginale, CF01-Helfer,
Standard-FDLs und deren historische Provenienz werden nicht geändert.
