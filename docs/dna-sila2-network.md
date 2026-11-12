# DNA-Ablauf über SiLA 2 und vorbereiteter ROS-Auftragsvertrag

Der DNA-Root ist der Ablaufeigentümer. Ein SiLA-2-Client gibt Entscheidungen
an diesen Root; dessen Auftragsport beauftragt einen lokalen **Mock-Worker**.
Inventar, Verbrauch, Gewahrsam, Reservierungen und Netzwerkquittungen liegen
im selben Root-Journal. Ein ROS-Client vor einem SiLA-Weiterleiter ist nicht
die gewählte Architektur.

Die Gerätewerte, Handhabungsbeobachtungen, Inkubation und Kalibrierung bleiben
synthetisch. TLS/gRPC über Loopback ist eine getrennt prüfbare Netzwerkgrenze.
**Kein ROS-Knoten/Action-Server wurde gebaut oder ausgeführt.** Es gibt keine
Roboterfahrt, Pipettierung, Hardwareanbindung, LAN- oder SiLA-Zertifizierung.
Fachliche Vorgaben und F10/F20 stehen in [DNA-Quantifizierung](dna-quantification.md).

## Führende Quellen und Einstieg

`model/dna-quantification-sila2.shared.json` bindet DNA-Profil, DNA-Protokoll,
Auftragsvertrag und unveränderte Standard-FDLs mit SHA-256. Der Builder
`scripts/build_dna_quantification_sila2.py` erzeugt daraus die FDL
`DnaQuantificationWorkflow` v1.0. Das exakte nichtgeometrische Format
`solidcraftbot.dna-sila2/1` ist von einer CAD-Galerieansicht ausgenommen;
unbekannte Versionen benötigen weiterhin die normale Klassifizierung.
Galeriebilder, Katalog und historische Provenienz werden nicht regeneriert.

Die generierte Quell-FDL und die über `SiLAService.GetFeatureDefinition`
gelesenen XML-Bytes werden getrennt archiviert und gehasht. Das SDK serialisiert
die Definition neu: unter anderem fehlen die expliziten Root-Attribute
`MaturityLevel` und `Locale`, während `schemaLocation` hinzukommt. Diese Bytes
werden nicht gleichgesetzt. Die gepinnte XSD setzt eine fehlende MaturityLevel
auf `Draft`; daraus folgt keine Zertifizierung. Ein dokumentierter Strukturvergleich
unter ausdrücklich benannten Ausnahmen ersetzt keinen Bytevergleich.

Für die lokale Ausführung werden die Abhängigkeiten aus
`requirements/sila2-test.lock` benötigt. Eine vorhandene geeignete Umgebung
kann verwendet werden; ROS und pixi werden dafür nicht installiert.

```bash
python3 scripts/run_dna_sila2.py --help
python3 scripts/build_dna_quantification_sila2.py
python3 scripts/build_dna_ros_interfaces.py
```

Die private Eingabe zur Initialisierung ist eine JSON-Liste aus
`username`, `password` und `role` (`operator` oder `observer`). Zugangsdaten
werden aus einer lokalen Datei unter `exports/` gelesen; sie gehören weder
in Modellquellen noch in Argumente, Berichte oder Videos.

```bash
python3 scripts/run_dna_sila2.py init \
  --directory exports/dna-server \
  --credentials-input exports/private-dna-login.json \
  --credentials exports/dna-server/users.json
python3 scripts/run_dna_sila2.py serve \
  --directory exports/dna-server --credentials exports/dna-server/users.json \
  --tls-directory exports/dna-server/tls --ready-file exports/dna-server/ready.json
```

Der Server läuft weiter, während ein zweiter Prozess `status`, `report`,
`command` oder das Referenzszenario aufruft. Der Client liest sein Login aus
einer privaten JSON-Datei mit `username` und `password`. Zertifikat und
erwartete ServerUUID stammen aus der bewusst gewählten Ready-Datei; falsches
Vertrauen oder eine andere UUID werden abgelehnt.

Authentifizierung und Client-Verbindung verwenden die vorhandenen CF01-Helfer
unverändert. Die kleine TLS-Identitätsfunktion ist dagegen bewusst DNA-eigen
dupliziert, weil die CF01-Methode an deren Stations-Runtime gebunden ist.
Eine spätere Vereinheitlichung benötigt gemeinsame CF01-/DNA-Netzwerktests
und gehört nicht zu diesem Ausbau.

Das Referenzszenario führt Qubit 500 → angebotene Verdünnung 1+9 → neues
Messpaar → Abschluss über tatsächliche SiLA-Aufrufe aus:

```bash
python3 scripts/run_dna_sila2.py scenario \
  --ready-file exports/dna-server/ready.json \
  --login-input exports/private-dna-client-login.json \
  --run-id SYN.DNA.NetworkExample --out exports/dna-network-scenario.json
```

Eine vorhandene Ausgabedatei wird vor dem ersten Effekt abgelehnt.

Jedes ausdrücklich gewählte Serververzeichnis besitzt einen eigenen
Root-Store. Zwischen getrennten Stores oder unabhängigen Läufen findet keine
globale Bestandsübernahme statt. Ein neuer synthetischer Lauf darf deshalb
nicht als Fortsetzung eines realen Probenbestands ausgegeben werden.

## Quittungen und Wiederaufnahme

Die Properties `Status` und `Report` sind lesend. Die Befehle sind
`CreateRun`, `RunUntilDecision`, `ChooseDilution`, `AcceptResult`, `ResumeRun`,
`ReconcileInventory`, `CancelRun` und `FinishCancel`. Jeder Effektbefehl trägt
einen `RequestIdentifier` und einen `RunIdentifier`. Einzelne Geräteoperationen
wie `take`, `blank` oder `confirm_measurement` sind keine Netzwerkbefehle.
`pause_after` ist ausschließlich eine private Testinjektion am Server.

Die erste Root-Wirkung enthält im selben Commit die Quittung mit normalisierten
Argumenten, Fingerabdruck, Principal, ServerUUID, Boot-ID und Ausführungskennung.
Gleiche Kennung mit gleichen Argumenten und gleichem Principal liefert die
gespeicherte Antwort ohne neues Ereignis. Eine andere Verwendung derselben
Kennung wird abgelehnt. Weitere Transitionen tragen dieselben Korrelations-IDs;
`command_finished` protokolliert den Abschluss. Ein RPC-Timeout ist kein Ergebnis.

SiLA-Principal, verantwortliche Person und ausführender Agent sind verschiedene
Identitäten. Root-Evidenz unterscheidet `network_receipt`, `synthetic_backend`,
`synthetic_person_input` und `worker_claim`. Systemfelder werden nach dem
fachlichen Payload gesetzt. Synthetische Szenariowerte werden einmal im Root
gebunden; eine spätere Anfrage kann sie nicht still durch CLI-Vorgaben ersetzen.

`ResumeRun` übernimmt die Sitzung im Serverprozess. Offene Quittungen aus einem
früheren Boot werden `uncertain`; aktive Worker-Aufträge werden nicht erneut
gesendet. `ReconcileInventory` benötigt vollständige ausdrückliche Beobachtungen
und den passenden Ausgang jeder offenen Absicht. `unknown` hält Bestand und
Reservierungen. Auf gebundenen Läufen darf die alte lokale DNA-CLI nur
`status`/`report` lesen. Bestehende Laufbytes bleiben unverändert lesbar;
Quelländerungen sperren Fortsetzungen, statt Journale still zu migrieren.

`CancelController.CancelCommand` fordert das Ende der Ausführung an einer
Transitionsgrenze an. Es setzt keine Root-Abbruchabsicht. Offene Effekte
verlangen weiter einen Abgleich. `CancelRun` setzt dagegen `cancelling`;
erst `FinishCancel` mit vollständigem Inventar und aufgelösten Entnahmen
gibt Ressourcen frei. LockController v1.0 regelt den Netzwerkzugriff;
Sperrablauf oder Logout geben keine Laborressource frei.

Logische Prozesszeit, Serverzeit der Quittungen und Clientzeit bleiben getrennt.

## B0: generierte Action-Felder, lokaler Mock

`model/dna-quantification-tasks.protocol.json` definiert `TransferVessel` einmalig.
`scripts/build_dna_ros_interfaces.py` erzeugt das ignorierte
`ros2_ws/src/solidcraftbot_dna_interfaces` mit `ament_cmake`, `.action`,
Paketmetadaten und einem gehashten Transportbericht. Der reine Python-Decoder
`scripts/dna_quantification_tasks.py` prüft exakt dieselben Felder.
Im getesteten Pfad gibt es keinen `rclpy`-Import und keinen Zugriff auf
`ros2_ws/build` oder `install`.

Der Auftrag bindet Request-/Goal-/Lauf-/Versuchs-/Kontext-ID, Probe, Gefäß,
Inhaltsrevision und Quellpins. Rack-Endpunkte tragen Rack- und Platz-ID.
Für Agentengewahrsam gibt es eine ausdrückliche Ortsart `agent` mit Agent-ID;
ein Agent wird nicht als erfundenes Rack kodiert. B0 unterstützt nur
Rack → zugewiesener Agent und Agent → ursprünglicher Rackplatz.

Vor Dispatch speichert der Root die Absicht. Der Worker erhält weder Journal
noch Inventar und liefert nur `evidence=worker_claim`, `motion_executed=false`.
Diese Behauptung verändert weder Gewahrsam noch Verbrauch. Erst eine getrennte
Beobachtung über die bestehenden Handhabungsregeln ändert den kanonischen Ort.
Der synthetische Backend erzeugt diese Beobachtung ausdrücklich selbst; sie
ist kein Scan und kein Sensorsignal. Messwerte entstehen über einen getrennten
synthetischen Messwertanbieter aus den gespeicherten Szenariowerten.

Ein wiederholtes Goal erzeugt keinen zweiten Effekt. Unklare, abgebrochene
oder nach Neustart offene Aufträge werden nicht erneut versandt. Goal-Cancel
gibt weder Gewahrsam noch Reservierungen frei. Der Bericht weist
`worker=mock`, `ros_compiled=false`, `ros_executed=false` aus.
`ros_interface_generated` wird nur bei gültigen generierten Artefaktpins wahr.

Die spätere B1-Umgebung ist gemäß Eigentümerentscheidung RoboStack/pixi,
ROS 2 Jazzy, osx-arm64. Installation, Python-ABI-Entscheidung, zweite Lockdatei,
`colcon`-Build und DDS-Prozesstests gehören ausdrücklich nicht zu B0.

## Nachweise und Grenzen des Videos

`scripts/dna_evidence_manifest.py` exportiert die ursprünglichen Journalbytes,
Kettenköpfe und zugehörige CSV-Artefakte. `scripts/render_dna_evidence.py`
erstellt daraus eine neue schematische Darstellung ausschließlich unter
`exports/dna-evidence/<run>/`. Der historische CF01-Videoexporter wird dafür
nicht aufgerufen. Es werden keine Robotermodelle entlang erfundener Bahnen bewegt.

Das Manifest bindet Arbeitsstand und Quelldigests, FDL, Rohjournal und Rohdaten,
öffentliche Serveridentität und Zertifikatsfingerabdruck, Transportquittungen,
Testlogs, Werkzeugversionen sowie PNG/MP4. `--check` prüft Hashes und fachliche
Zuordnungen erneut; ein verändertes Byte darf nicht als derselbe Nachweis gelten.
Logische Zeit, gemessene Laufzeit und geraffte Videozeit sind sichtbar getrennt.
Das Video ist eine Erklärung des protokollierten Softwarelaufs; ein Bild belegt
weder Pipettierleistung noch eine reale Bewegung oder Probenidentität.

```bash
python3 -m unittest discover -s tests -p 'test_dna_quantification_*.py' -v
python3 -m unittest discover -s tests -p 'test_dna_sila2_contract.py' -v
SOLIDCRAFTBOT_SILA_NETWORK_TESTS=1 python3 -m unittest discover \
  -s tests -p 'test_dna_sila2_network.py' -v
python3 -m unittest discover -s tests -p 'test_dna_evidence.py' -v
```

Netzwerktests laufen in getrennten Prozessen über echte lokale TLS-Sockets.
Ohne Schalter übersprungene Tests sind kein bestandener Netzwerknachweis.
CF01, dessen .NET-Probe, UltraC-HTTP, GENtle, LockController v2 sowie
DNA-Transportbahnen und Hardwarequalifikation bleiben separate Aufgaben.
