# NanoDrop UltraC: lesender Netzwerkadapter und synthetisches Gerätemodell

Ein gemeinsamer HTTP-Client kann Ergebnisse beim ausdrücklich konfigurierten
UltraC-Host oder beim synthetischen NanoDrop-Modell abrufen. Das Modell bietet
denselben ausgewählten GET-Vertrag über einen wirklichen HTTP-Server an.
**Geprüft ist der lokale synthetische Netzwerkverkehr; ein Originalgerät wurde
noch nicht angeschlossen.** Der manuelle Ablauf und seine Verbrauchsbuchungen
werden durch einen Abruf nicht verändert.

## Herstellervertrag und führende Quellen

Maßgeblich sind das [NanoDrop Ultra API Reference Manual, M024 01/25](https://assets.thermofisher.com/TFS-Assets/CAD/manuals/nanodrop-ultra-api-reference-manual-m024.pdf)
und für die Tokenbereitstellung der [SciVault-2-Leitfaden, Revision E, August 2025, Seiten 50–51](https://documents.thermofisher.com/TFS-Assets/CAD/Product-Guides/scivault-2-user-guide-en.pdf).
Das API-Handbuch nennt HTTP auf Port `54011` und Bearer-Authentifizierung bei
aktiviertem SciVault 2. Der Client kann außerdem eine ausdrücklich konfigurierte
HTTPS-URL mit der normalen Zertifikatsprüfung verwenden; HTTPS-Unterstützung des
konkreten Geräts ist damit nicht nachgewiesen. Es gibt keinen implementierten
Login-, OAuth- oder Token-Erneuerungsvorgang.

| Quelle | Verantwortung |
|---|---|
| `model/nanodrop-ultra-network.protocol.json` | Einmalige Beschreibung der unterstützten Pfade, Querynamen/-typen, dokumentierten Measurement-Felder und Prüfgrenzen |
| `model/nanodrop-ultra-network.synthetic.json` | Explizit synthetisches Gerätemodell; bindet UltraC-Katalogtyp und Protokoll über Pfad und SHA-256 |
| `scripts/nanodrop_ultra_network.py` | Derselbe GET-Client für Modell und konfiguriertes Gerät; unveränderte Antwortarchivierung |
| `scripts/nanodrop_ultra_model.py` | HTTP-Adapter des synthetischen Modells, unabhängig von FreeCAD und SolidCraft |
| `scripts/run_nanodrop_ultra_network.py` | Einstieg für Modellserver und einzelnen Abruf |

Das Netzwerkmodell referenziert `nanodrop_ultrac` im bestehenden Gerätekatalog.
Es ist eine logische Gerätefassung; die API benötigt keine CAD-Datei. Eine
Illustration des Messgeräts liefert keinen Nachweis seiner Optik oder Elektronik.
Für **NanoDrop One** wird aus dem gemeinsamen manuellen Messprotokoll keine
Ultra-Web-API-Unterstützung abgeleitet.

## Unterstützter lesender Ausschnitt

| Clientmethode | HTTP-Route | Querynamen laut Handbuch |
|---|---|---|
| `system()` | `GET /System` | keine |
| `query_experiments(**params)` | `GET /Experiment/Query` | `NameFilter`, `ApplicationFilter`, `PageNumber`, `PageSize`, `StartTimeStamp`, `EndTimeStamp`, `StartTime`, `EndTime` |
| `experiment(id)` | `GET /Experiment/Id/{id}` | keine |
| `experiment_detail(id)` | `GET /Experiment/Detail/Id/{id}` | keine |
| `measurements(experiment_id=None, start_page=None, page_count=None)` | `GET /Measurement` | `experimentId`, `startPage`, `pageCount` |

UUIDs, Integerbreiten und Datum/Zeit mit Zeitzone werden geprüft; Querynamen
behalten ihre exakte Schreibweise. Nicht angegebene Werte werden weggelassen,
ausdrücklich angegebene `0` bleibt erhalten. Der Client macht einen Abruf ohne
automatische Wiederholung oder Pagination. Er interpretiert weder Seitenbasis
noch Timestamp-Einheit. Schreibende Aufrufe sind nicht implementiert. Weitere
Hersteller-Leserouten wie `FindPeak`, `StandardReference` und `UserMethod` gehören
nicht zu diesem Ausschnitt; der Modellserver meldet dafür `501`, für unbekannte
Pfade `404` und für schreibende Methoden `405`.

Das Handbuch definiert keine vollständigen System-/Experimentantworten oder
Erfolgs-Envelopes. Auch die Inhalte von `SettingJson`, `DataJson` und `ExtraJson`
bleiben offen. Der Client nimmt JSON daher ohne erfundene Ergebnishülle entgegen:
Objekt, Array, Skalar und `null` bleiben möglich. Die dokumentierten
Measurement-Felder begründen noch keinen qualifizierten Konzentrationsparser.

## Modell lokal starten und abrufen

Im ersten Terminal, vom Projektordner aus:

```sh
python3 scripts/run_nanodrop_ultra_network.py serve
```

Der Server bindet standardmäßig an `127.0.0.1:54011`. `--port 0` wählt einen freien
Port; die erste Ausgabe enthält dessen URL und die Modellprüfsumme.
Ein bereits belegter Port wird nicht übernommen. In einem zweiten Terminal:

```sh
python3 scripts/run_nanodrop_ultra_network.py read \
  --base-url http://127.0.0.1:54011/ --endpoint system \
  --out exports/nanodrop-network/system-01

python3 scripts/run_nanodrop_ultra_network.py read \
  --base-url http://127.0.0.1:54011/ --endpoint query_experiments \
  --query '{"NameFilter":"Batch A","PageNumber":0,"PageSize":10}' \
  --out exports/nanodrop-network/experiments-01

python3 scripts/run_nanodrop_ultra_network.py read \
  --base-url http://127.0.0.1:54011/ --endpoint measurements \
  --query '{"experimentId":"11111111-1111-4111-8111-111111111111","startPage":0,"pageCount":1}' \
  --out exports/nanodrop-network/measurements-01
```

`--endpoint experiment` beziehungsweise `experiment_detail` benötigt `--id UUID`.
Jeder Abruf verwendet einen **neuen** Archivordner. Ein vorhandenes Archiv wird
nicht überschrieben. Mit einem anderen expliziten `--base-url` spricht derselbe
Client das konfigurierte Gerät an; es gibt keine automatische Netzwerksuche.

Die Modellquelle enthält zwei fiktive Experimente und drei fiktive Messungen.
Ihre eigenen, ausdrücklich deklarierten Regeln sind: nullbasierte Seiten,
Experiment-Seitengröße standardmäßig 100, zwei Messungen je Messungsseite,
`pageCount` als Seitenanzahl, Unix-Millisekunden für Timestamp-Filter,
Groß-/Kleinschreibung ignorierender Namens-Teilstring und exakter Anwendungsfilter.
Zeitgrenzen sind einschließlich. Queryantworten sind nackte Arrays;
Experimentdetails enthalten zusätzlich `Measurements`. Diese Regeln und Felder
sind **synthetische Modellentscheidungen**, keine belegten Eigenschaften des
Originals. `DataJson` enthält ausdrücklich benannte synthetische Beispielwerte.
Es werden keine Messungen ausgelöst oder optisch simuliert.

Optional kann ein Modelltoken über eine Umgebungsvariable gesetzt werden.
Beispiel für ein ausdrücklich fiktives Testtoken:

```sh
export SYN_ULTRAC_KEY='synthetic-local-test-only'
python3 scripts/run_nanodrop_ultra_network.py serve --api-key-env SYN_ULTRAC_KEY
# Im Abrufterminal dieselbe Testvariable setzen und ergänzen:
# --api-key-env SYN_ULTRAC_KEY
```

Am Original wird der administrativ bereitgestellte SciVault-Token über eine
eigene Umgebungsvariable referenziert. Token gehören weder in Kommandoargumente
noch in Modellquellen oder Repositorydateien. Authentifizierung ist am Modell
optional; mit konfiguriertem Token werden fehlende/falsche Bearer-Header abgewiesen.

## Originalbytes und Nachweise

Ein vollständiger Abruf erzeugt `response.bin` mit unveränderten Bodybytes und
`metadata.json` mit SHA-256, Status, Pfad/Query, Abrufzeit und Protokollprüfsumme.
Herkunfts-URL und ausgewählte Antwortheader ergänzen die Zuordnung;
Authentifizierungsheader werden nicht archiviert. Das Modell kennzeichnet sich
über `X-DIYLabBot-Synthetic` und seine Modellprüfsumme; das ist eine
Selbstauskunft des Peers, keine Geräteauthentifizierung. `hardware_verified`
bleibt immer `false`. Fehlender Modellheader beweist kein Originalgerät.

HTTP-Fehler und vollständige ungültige JSON-Antworten bleiben archivierungsfähig;
der CLI-Abruf endet dabei erfolglos. Leeres `204` ist zulässig. Antwortgröße und
Timeout sind begrenzt; eine abgebrochene Antwort wird, soweit noch erfassbar,
ausdrücklich mit `body_complete: false` archiviert. Zu große Antworten liefern
kein vollständiges Artefakt. Redirects werden nicht verfolgt. Es werden
keine Zugangsdaten an ein Umleitungsziel weitergereicht.

Abruf ist von fachlichem Import getrennt: `SampleName`, Reihenfolge und Zeit
beweisen keine durchgängige Proben-/Gefäßidentität. `IsDiscarded` wird nicht als
physische Entsorgung gewertet. Es gibt keine automatische Workflowfortsetzung,
Ergebnisannahme, Gefäßbewegung oder Verbrauchsbuchung. Die bestehenden CSV-Imports
bleiben ausdrücklich synthetisch qualifiziert.

## Prüfungen und verbleibende Qualifikation

```sh
python3 -m unittest discover -s tests -p 'test_nanodrop_ultra*.py' -v
python3 -m unittest discover -s tests -v
```

Die Tests verwenden einen echten Loopback-HTTP-Server und den gemeinsamen Client:
fünf Routen, Parameterkodierung/-typen, Modellfilter und Seiten, Authentifizierung,
HTTP-/JSON-Fehler, Redirects, Größenlimit, unveränderte Archivbytes und ausbleibende
Workflowwirkung. Quellenbindungen und unzulässige Modelländerungen werden geprüft.

Der Einführungsprüflauf am 9. November 2026 im frischen isolierten Worktree
umfasste 438 Tests: 417 bestanden, 21 mangels lokaler CAD-/ROS-Builds übersprungen.
Alle 33 neuen Client-/Modelltests wurden ausgeführt und bestanden. Zusätzlich
wurden alle fünf GET-Routen über Server- und Abruf-CLI mit einem fiktiven
Bearer-Token archiviert. Für diese Netzwerkänderung wurde kein CAD neu aufgebaut.

Für die Gerätequalifikation fehlen weiterhin ein benannter UltraC-Softwarestand,
unveränderte aufgezeichnete Originalantworten sowie Nachweise der tatsächlichen
Pagination, Filter-/Timestamp-Semantik und Fehlerantworten. Erst daraus kann ein
versionierter Ergebnisdecoder mit expliziter Messungs-/Workflowzuordnung entstehen.
Netzwerklesetests ersetzen keine Mess-, Mengen-, SOP- oder Sicherheitsqualifikation.
