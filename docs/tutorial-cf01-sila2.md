# Tutorial: SiLA-2-Schnittstelle des CF01-Simulators

## Deutsch: Bedienung und Grenzen

Diese deutsche Fassung ist maßgeblich; die [englische Übersetzung](#english-translation) folgt unten. Ziel ist ein lokaler Rack–CF01–Rack-Lauf über TLS/gRPC mit zwölf synthetischen Proben. Benötigt werden Python **3.13**, `uv` und ein Checkout mit konsistenten Quellenbindungen; ROS, CAD, FreeCAD und reale Laborgeräte werden nicht benötigt.

Die folgenden Befehle wurden am 21.11.2026 mit Python 3.13.12 ausgeführt. Lokale Nachweise liegen unter `exports/tutorials/cf01-sila2-2026-11-21-run02/`; Zugangsdaten, Schlüssel, Journale und Ausgaben bleiben gitignored. Die CLI in [run_cf01_sila2.py](../scripts/run_cf01_sila2.py) ist maßgeblich. Auszüge lassen wechselnde UUIDs und absolute Pfade weg.

### 1. Umgebung aufsetzen

Im Repository-Hauptverzeichnis beginnen. Alle folgenden Befehle verwenden dieselbe Shell und deren aktivierte Umgebung, außer dem ausdrücklich getrennten Server-Terminal.

```sh
export CF01_REPO="$PWD"
export CF01_RUN="$CF01_REPO/exports/tutorials/cf01-sila2-$(date +%Y%m%d-%H%M%S)"
umask 077
mkdir -p "$CF01_REPO/exports/tutorials"
mkdir "$CF01_RUN"
cd "$CF01_RUN"
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python --require-hashes -r "$CF01_REPO/requirements/sila2.lock"
. .venv/bin/activate
cd "$CF01_REPO"
```

**Erwartet:** Die Umgebung verwendet Python 3.13; der Lauf installierte 13 Produktionspakete, darunter `unitelabs-sila==0.14.0`. **Falls es nicht klappt:** Arbeitsverzeichnis und Lockfile-Pfad prüfen; DNS-/Downloadfehler müssen vor dem Fortfahren behoben sein, ohne die Hashprüfung abzuschalten.

### 2. SiLA-Verträge erzeugen

```sh
python scripts/build_cf01_sila2.py
```

**Erwartet:** Die Ausgabe endet auf `exports/generated/cf01-sila2/contracts/CentrifugeControl-v2_0.sila.xml`; dort entstehen die abgeleiteten Verträge. **Falls es nicht klappt:** Bei einem Quellenfehler anhalten und den Quellstand abgleichen; `interfaces/sila2/standard/` enthält unveränderte Standard-FDLs und ist kein Ausgabeordner.

### 3. Benutzer und Login-Dateien anlegen

Die folgenden Dateien unter `$CF01_RUN` speichern. Platzhalter durch eigene, unterschiedliche Passwörter mit mindestens zwölf Zeichen ersetzen; dieselben Werte in die jeweilige Login-Datei übernehmen. Keine echten Zugangsdaten in Git oder Befehlsargumente schreiben.

`users-input.json`:
```json
[{"username":"observer","password":"<OBSERVER_PASSWORD>","role":"observer"},{"username":"operator","password":"<OPERATOR_PASSWORD>","role":"operator"}]
```
`observer-login.json`:
```json
{"username":"observer","password":"<OBSERVER_PASSWORD>"}
```
`operator-login.json`:
```json
{"username":"operator","password":"<OPERATOR_PASSWORD>"}
```

```sh
chmod 600 "$CF01_RUN/users-input.json" "$CF01_RUN/observer-login.json" "$CF01_RUN/operator-login.json"
python scripts/run_cf01_sila2.py init --credentials-input "$CF01_RUN/users-input.json" \
  --credentials "$CF01_RUN/users.json" --store "$CF01_RUN/station.sqlite3"
```

**Erwartet:** Die Ausgabe enthält `"initialized": true` und `"simulation_only": true`; `users.json` enthält Passwort-Hashes. **Falls es nicht klappt:** Bei `Pinned assembly source changed` anhalten; der erste Versuch scheiterte tatsächlich an einer veralteten Arm-Prüfsumme, die separat repariert wurde. Bereits angelegte Dateien und Datenbanken erhalten, für einen neuen Versuch nach der Reparatur einen frischen Laufordner verwenden.

### 4. Server starten

In einem zweiten Terminal ins gleiche Repository wechseln und `CF01_RUN` auf den absoluten Laufordner aus Schritt 1 setzen. Dort die Umgebung aktivieren und den Server im Vordergrund laufen lassen:

```sh
. "$CF01_RUN/.venv/bin/activate"
python scripts/run_cf01_sila2.py serve --store "$CF01_RUN/station.sqlite3" \
  --credentials "$CF01_RUN/users.json" --tls-directory "$CF01_RUN/tls" --ready-file "$CF01_RUN/ready.json"
```

**Erwartet:** `ready.json` wird angelegt; der Server bindet standardmäßig an `127.0.0.1` und einen freien Port, mit `tls: true`. **Falls es nicht klappt:** Serverfehler prüfen und keine alte Bereitschaftsdatei übernehmen; `serve` überschreibt sie nicht. Die Datei und ihr Zertifikat stammen hier vom eigenen lokalen Server; der Client prüft Zertifikatsvertrauen und Server-UUID beim Verbindungsaufbau in Schritt 5.

### 5. Live-Status als Observer lesen

Zur ersten Shell zurückkehren:

```sh
python scripts/run_cf01_sila2.py status --ready-file "$CF01_RUN/ready.json" \
  --login-input "$CF01_RUN/observer-login.json" --out "$CF01_RUN/status-observer.json"
```

**Erwartet:** Der Lauf meldete `"observation": "authenticated_live_status"`, `"boot_changed": false` und `"process_effects_dispatched": false`. Die neue Beobachtungsdatei entsteht ohne Batch-Journal; `inspect` liest dagegen einen gespeicherten Prüfpunkt, keinen Live-Zustand. **Falls es nicht klappt:** Laufenden Server, Login-Datei und vertrauenswürdige Bereitschaftsdatei prüfen; für weitere Beobachtungen einen neuen `--out`-Dateinamen wählen.

### 6. Batch als Operator ausführen

```sh
python scripts/run_cf01_sila2.py batch --ready-file "$CF01_RUN/ready.json" \
  --login-input "$CF01_RUN/operator-login.json" --journal "$CF01_RUN/batch.jsonl" --out "$CF01_RUN/batch.json"
```

**Erwartet:** Beobachtet wurde `{"passed": true, "mode": "network_mock_only", "order_restored": true, "spin_completed": true, "network_executed": true, "hardware_executed": false}`. `Sample01` bis `Sample12` standen anschließend wieder in ihrer ursprünglichen Rackreihenfolge. **Falls es nicht klappt:** Stationsdatenbank, Client-Journal und Fehler erhalten und unklare Übergaben ausdrücklich abgleichen; keine unsicheren Effekte wiederholen. Der Client speichert jede Absicht vor dem Versand und setzt alte Batches nicht automatisch fort; die CLI bietet bewusst keinen Unterbefehl `command` für Einzelbefehle.

### 7. Prüfen und aufräumen

Nach dem abgeschlossenen Batch den Server im zweiten Terminal mit Strg-C stoppen. In der ersten Shell:

```sh
python scripts/run_cf01_sila2.py inspect --store "$CF01_RUN/station.sqlite3"
uv pip install --python "$CF01_RUN/.venv/bin/python" --require-hashes -r requirements/sila2-test.lock
python3 -m unittest discover -s tests -v
SOLIDCRAFTBOT_SILA_NETWORK_TESTS=1 python3 -m unittest discover -s tests -p 'test_cf01_sila2*.py' -v
```

**Erwartet:** `inspect` meldete `"observation": "stored_checkpoint_not_live_state"` und keine offenen Absichten. Die Testergebnisse werden unten getrennt ausgewiesen; übersprungene Netzwerkprüfungen sind kein Nachweis. **Falls es nicht klappt:** Fehler und Skips auswerten, statt aus einem erfolgreichen Batch eine grüne Gesamtsuite abzuleiten; die .NET-Prüfungen benötigen zusätzlich eine gebaute unabhängige Probe und ihren eigenen Schalter.

Nach erfolgreichem Abschluss und beendetem Server kann ausschließlich der eigene `$CF01_RUN`-Ordner gelöscht werden, wenn seine Nachweise nicht mehr gebraucht werden. Bei ungeklärten Läufen die Journale behalten; niemals pauschal `exports/` löschen oder Laufzeitdaten committen. Für dieses Tutorial wurden die Nachweise aufbewahrt.

### Prüfstand und Grenzen

Die 51 CF01-Prüfungen ergaben **49 bestanden, zwei optionale .NET-Prüfungen übersprungen**; alle 18 TLS-Netzwerk- und beide Prozesstests liefen tatsächlich. Zusätzlich bestanden 29 Arbeitsbereichstests und neun Markdown-Linktests.

**Die Gesamtsuite ist nicht grün und wurde nicht vollständig ausgeführt.** Sie wurde nach über 30 Minuten während eines langen CUT&RUN-Tests unterbrochen. Fehler der separaten Analytics-Arm-Bindung, der Gebäudefixture (`D3_002_003`) und der Gebäudemedien wurden auch auf dem Ausgangsstand bestätigt. Zwei zusätzlich gefundene BF01-Prüfsummenbindungen wurden anschließend korrigiert und separat geprüft; das ersetzt keinen abgeschlossenen Gesamtlauf.

Die Ausführung belegt den Simulator über lokales Loopback-TLS, keine Hardware, LAN-Qualifikation, native Ladebahn oder formale SiLA-Zertifizierung. Der implementierte `LockController` ist v1.0 (`Verified`); die GENtle-Fähigkeits-/Ressourcenbindung mit v2 `Draft` ist nicht implementiert. Die separate Quellenreparatur erneuert keine historischen CAD- oder Bewegungsnachweise.

[DNA-Quantifizierung](dna-sila2-network.md), [Extraktionsanalytik](extraction-analytics-sila2.md) und [Inputsonikation](sonication-sila2-network.md) haben eigene Lauf-Roots und dokumentierte Einstiege; sie sind nicht dieser CF01-Batch. Extraktionsanalytik teilt den DNA-Server, nicht den CF01-Root. Der [UltraC-HTTP-Leseadapter](nanodrop-ultra-network.md) ist kein SiLA. Ein ROS-Tutorial bleibt bis zur RoboStack/pixi-Phase zurückgestellt.

## English translation

This is a translation of the authoritative German instructions above. It runs twelve synthetic samples from rack to CF01 and back using local TLS/gRPC. Prerequisites are **Python 3.13**, `uv` and consistent source pins; no ROS, CAD, FreeCAD or physical instrument is required. The commands were executed on 21 November 2026 with Python 3.13.12; local evidence is under `exports/tutorials/cf01-sila2-2026-11-21-run02/`. Credentials, keys, journals and outputs remain ignored by Git. The existing CLI is authoritative; output excerpts omit variable UUIDs and absolute paths.

### 1. Set up the environment

Run the shared command block in German step 1 from the repository root, then keep that shell and its activated environment. It creates a fresh private run directory and installs the production lockfile with hash verification.

**Expected:** Python 3.13 and 13 installed production packages, including `unitelabs-sila==0.14.0`. **If it fails:** Check the working directory and lockfile path; resolve DNS/download errors without disabling hash verification.

### 2. Generate the contracts

Run the command in step 2. **Expected:** The printed path ends in `exports/generated/cf01-sila2/contracts/CentrifugeControl-v2_0.sila.xml`. **If it fails:** Stop on source errors and reconcile the checkout; `interfaces/sila2/standard/` holds unchanged standard FDLs, not generated output.

### 3. Create users and login files

Save the three JSON examples from step 3 under `$CF01_RUN`. Replace placeholders with distinct passwords of at least twelve characters, matching each login file to its user; restrict file permissions as shown. Do not put real credentials in Git or command arguments.

**Expected:** `initialized: true` and `simulation_only: true`; the output credential file stores password hashes. **If it fails:** Stop on `Pinned assembly source changed`; the initial run encountered a stale arm pin that was repaired separately. Retain partially created files and databases, and use a fresh run directory after repair.

### 4. Start the server

In a second terminal, enter the same repository, set `CF01_RUN` to the absolute directory from step 1, activate its environment and run step 4 in the foreground. **Expected:** A new `ready.json`, TLS enabled, default loopback address `127.0.0.1` and a dynamically allocated port. **If it fails:** Inspect the server error; it refuses an existing ready file. Trust only the file/certificate from your own local server; the client verifies certificate trust and server UUID in step 5.

### 5. Read live status as observer

Return to the first shell and run step 5. **Expected:** `authenticated_live_status`, `boot_changed: false`, `process_effects_dispatched: false`; a new observation file without a batch journal. `inspect` instead reads a stored checkpoint. **If it fails:** Check the running server, login and trusted ready file; use a new output filename for each observation.

### 6. Run the batch as operator

Run step 6. **Expected:** The recorded result reports `passed`, `order_restored`, `spin_completed` and `network_executed` as true, `mode: network_mock_only` and `hardware_executed: false`; Sample01–12 return in their original rack order. **If it fails:** Preserve the station database, client journal and error, and reconcile uncertain handoffs explicitly. The client persists intents before transmission, never retries uncertain effects or automatically resumes old batches; there is deliberately no `command` subcommand.

### 7. Check and clean up

After batch completion, stop the server with Ctrl-C in its terminal and run step 7 in the original shell. **Expected:** `stored_checkpoint_not_live_state` and no pending intents; evaluate standard and explicitly enabled network tests separately. **If it fails:** Inspect failures and skips; a successful batch does not prove the whole suite passes, and skipped network tests are not evidence. The .NET tests additionally require the built independent probe and their own switch.

Only delete your own completed `$CF01_RUN` directory after stopping the server and deciding its evidence is no longer needed. Retain unresolved journals; never remove all of `exports/` or commit runtime data. Evidence for this tutorial was retained.

### Verification scope

The 51 CF01 checks yielded **49 passes and two optional .NET skips**, with all 18 TLS network tests and both process tests actually executed. Another 29 workspace tests and nine Markdown-link tests passed.

**The whole suite is not green and did not finish.** It was interrupted after more than 30 minutes during a long CUT&RUN test. Separate Analytics arm-pin, building-fixture (`D3_002_003`) and building-media failures were also confirmed on the baseline. Two additional BF01 source-pin dependencies were then repaired and checked separately; this does not replace a completed whole-suite run.

This is local loopback TLS against a simulator, without hardware, LAN qualification, native loading motion or formal SiLA certification. `LockController` v1.0 is `Verified`; the GENtle capability/resource binding using v2 `Draft` is not implemented. Refreshing source pins does not renew historical CAD/motion evidence. DNA quantification, extraction analytics and input sonication have their own run roots and entry points in the linked documents; extraction shares the DNA server, not the CF01 root. UltraC's HTTP reader is not SiLA. The ROS tutorial remains deferred until the RoboStack/pixi phase.
