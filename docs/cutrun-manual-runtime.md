# Manueller CUT&RUN-Aufzeichnungskern

Stand 12. November 2026: Ein erster manueller Aufzeichnungskern für
SK-Mel-29/H3K4me3 ist implementiert. Er bindet den
[SOP-Entwurf 0.1](cutrun-manual-sop-draft.md), bewahrt Beobachtungen und
Originaldateien und verwendet den gemeinsamen Materiallebenszyklus. Er führt
keine vollständige biochemische SOP aus. **`execution_ready`,
`reference_success` und `passed` bleiben im Bericht falsch.** Ein geschlossenes
Aufzeichnungsprotokoll ist kein erfolgreicher E4-Referenzlauf. Die vollständige
E4-Abnahme und O12 aus dem SOP-Entwurf bleiben offen.

## Quellen und offene Bindungen

Die neue Quelle
[`cutrun-manual-runtime.profile.json`](../model/cutrun-manual-runtime.profile.json)
mit ihrem [Schema](../model/cutrun-manual-runtime.schema.json) verwendet
`manual_observation` und `synthetic: false`. Sie bindet die SOP-Fassung über
ID, Revision und Prüfsumme. Die Herstellerreferenz bleibt die im SOP-Entwurf
benannte aktuelle CST-Fassung; historische Gleichheit mit dem Paper wird nicht
behauptet. Die Original-PDF wird ausdrücklich übergeben. Ohne diese Datei kann
die Vorbereitung gelesen werden, aber keine Stufe wird bereit. Eine übergebene
PDF muss sowohl zur Profilprüfsumme als auch zur Originalprüfsumme im gebundenen
SOP-Text passen. Es gibt keinen automatischen Abruf oder impliziten Zugriff auf
eine frühere Datei unter `exports/`.

Alle lokalen Laborparameter sind in der Vorlage `null`: Kultur/Bedingung,
Istidentitäten, Eingangsmengen, Zeit-/Temperaturbindungen, Assays,
Bewertungskriterien und Übergabe bleiben offen. E1-/E3-Werte, erwartete Ausbeuten
und erfundene Gefäßkennungen werden nicht übernommen. Ein `manufacturer_reported`
oder `local_proposal` kennzeichnet eine lesbare Angabe, keine bestätigte lokale
Parameterwahl. Stufenbereitschaft verlangt die ausdrücklich belegte lokale
Bindung. Bestätigte Entscheidungen O01–O11 benötigen Inhalt, Personenkennung,
Zeitzonenzeit und registrierten Originalbeleg. Diese Metadaten sind keine
Authentifizierung oder unabhängige Prüfung der fachlichen Freigabe.

`stage_readiness` beschreibt die hinterlegten Voraussetzungen für S01–S12;
`open_requirements` benennt fehlende Angaben mit ihren betroffenen Stufen.
Offene Bindungen sperren neue betroffene Absichten. Tatsächliche Beobachtungen,
Originaldateien und nachträgliche Belege werden dadurch nicht verworfen.
Der Kernel prüft noch keine vollständige Reihenfolge sämtlicher Wasch-,
Temperierungs-, Trenn- und Reinigungsoperationen. Insbesondere beweist ein
Stufenbeleg weder erreichte Probentemperatur noch SOP-Vollständigkeit.

## Einstieg und gemeinsame Speicherung

```sh
python3 scripts/run_cutrun_manual.py --help
python3 scripts/run_cutrun_manual.py prepare
```

`prepare` liest Quellen und Bereitschaft ohne Store, Reservierung oder
Materialbuchung. Ohne weitere Eingaben bleibt die Vorlage unvollständig.
`--profile`, `--original-pdf` und `--evidence-manifest` wählen ausdrücklich
bereitgestellte lokale Dateien. Das Evidenzmanifest ist ein JSON-Objekt mit
Belegkennung als Schlüssel und Dateipfad als Wert.

```sh
python3 scripts/run_cutrun_manual.py prepare \
  --profile exports/cutrun-manual/profile.json \
  --original-pdf exports/cutrun-manual/manufacturer.pdf \
  --evidence-manifest exports/cutrun-manual/evidence.json
```

Diese Pfade sind Beispiele für selbst bereitgestellte Unterlagen; die Dateien
werden nicht aus der Vorlage erzeugt. Mit `--out` wird zusätzlich eine **neue**
JSON-Datei unter dem Projektverzeichnis `exports/` geschrieben; vorhandene
Dateien werden nicht überschrieben. Fehler liefern Exitcode 1 und eine
JSON-Fehlermeldung.

`create --inventory ...` verlangt ein JSON-Objekt mit genau `materials`,
`vessels`, `reactions` und `actors`. Material- und Gefäßdeklarationen folgen dem
[gemeinsamen Materialvertrag](material-lifecycle.md); Mengen sind ausdrücklich
angegeben oder unbekannt. Eine Reaktionsbindung enthält `role` (`h3k4me3`,
`igg` oder `input`), `material_id`, `vessel_id`, `activation_material_id` und
`stop_material_id`. Input hat keine Aktivierungs-/Stoppaliquots. Aktive Zweige
benötigen getrennt identifizierte, ausgegebene Reagenzaliquots; ein unbekannter
Saldo beweist keine ausreichende Stoppmenge. Die PCR-Leerkontrolle bleibt eine
separate QC-Rolle ohne Probenverbrauch. Personenkennungen werden ausdrücklich
angegeben; sie ersetzen keine Anmeldung.

`create` darf einen noch unvollständigen Aufzeichnungskopf mit explizitem
Inventar anlegen. Es reserviert dessen Ressourcen im vorhandenen Journal und
archiviert die beim Erzeugen bereitgestellten SOP-/Profil-/Original- und
Entscheidungsbytes atomar mit dem Anfangsereignis. Es startet kein Gerät und
keine Reaktion. Ein gepinntes Artefaktmanifest wird bei Wiederaufnahme,
Bericht und Abschluss gegen die gespeicherten Originalbytes geprüft.
Der Standard-Store ist derselbe wie bei den übrigen manuellen
Workflows; die bestehende Auswahl eines alten `nanodrop.sqlite3` bleibt erhalten.
Ein explizites `--store` steht vor dem Unterbefehl und muss unter `exports/`
liegen.

```sh
python3 scripts/run_cutrun_manual.py create \
  --inventory exports/cutrun-manual/inventory.json
python3 scripts/run_cutrun_manual.py status RUN_ID
python3 scripts/run_cutrun_manual.py report RUN_ID
python3 scripts/run_cutrun_manual.py resume RUN_ID
```

`create` und `resume` geben die aktuelle Sitzungskennung zurück. `act` benötigt
`--session`, `--actor`, `--action`, `--observation` und optional `--data` mit
einem JSON-Objekt sowie `--artifact` mit Originalbytes. Die API-Einstiege sind
`cutrun_manual_sources.compile_profile(...)`,
`CutRunManualWorkflow.create(...)`, `.open(..., resume=True)` und
`.act(..., observation=...)`. `compile_profile` liefert zusätzlich transiente
Artefaktbytes für die atomare Archivierung; sie sind kein zusätzlicher
JSON-Bestand. Der `load`-Adapter kennzeichnet diese Übergabe mit
`_initial_artifacts`, die der gemeinsame Erzeugungspfad verarbeitet.

## Beobachtung, Material und Wiederaufnahme

Jede Beobachtung hat eine dauerhafte `observation_id`, `source_kind`,
`observed_at`, `source_ref` und `artifact_sha256`. Zulässige Herkünfte sind
`human_observation`, `device_export`, `external_record` und `test_fixture`.
Der beobachtete Zeitpunkt ist ein Intervall aus `earliest_utc` und
`latest_utc`; fehlende Zeit bleibt `null`. Der Erfassungszeitpunkt wird getrennt
aufgezeichnet. Dieselbe Beobachtungskennung mit gleichem Inhalt ist
idempotent; eine widersprüchliche Wiederverwendung wird abgelehnt.
Auch bei einer im Journal protokollierten Zurückweisung bleiben mitgelieferte
Originalbytes atomar erhalten. Ein automatisch erfasster Fristablauf ist dagegen ein reines
Uhrereignis; er bestätigt keine noch nicht ausgeführte Benutzeranweisung.

Inventarannahme, Verantwortungsübernahme und Arbeitsplatzabgleich verwenden die
gemeinsame Ablaufhülle. Materialabsicht und bestätigter Istverbrauch bleiben
getrennt; Umwandlungen und Produktaliquots benutzen dieselbe Bilanz und
Abstammung. Unbekannt ist kein Nullverbrauch. Bei mehreren weiterzuführenden
Produkten muss die aktuelle Reaktionsfraktion mit `retained_material_id` bei
`begin_material_action` ausdrücklich gewählt werden; eine Listenposition ist
kein Identitätsnachweis. Bei genau einem Produkt beziehungsweise Intermediat
ist die Auswahl eindeutig.

Aktivierung und Stopp besitzen eigene Befehle. Die erste Version erlaubt neue
Aktivierungen seriell und verlangt aktuelle Stoppzugänglichkeit, Mischung,
bekannte ausreichende zugeteilte Stoppmenge sowie gebundene Prozesszeit.
Eine Aktivierungsabsicht bedeutet bereits möglicherweise erfolgten Kontakt.
Zugabebeleg und Mischbeleg bleiben getrennt. Der Schutzstopp verwendet den
vorhandenen separaten Buchungskanal, sodass eine offene gewöhnliche Wirkung
seinen Nachweis nicht verdrängt. Ein später Mischbeleg belastet die bereits
bestätigte Stoppdosis nicht erneut.

`record_external_activation` und `record_external_stop` bewahren nachträglich
zugeordnete Handlungen mit ausdrücklicher Herkunft. Sie erzeugen keine fiktive
frühere elektronische Absicht und rechtfertigen kein blindes Wiederholen.
Offene Wirkungen werden über `resolve_action` als durchgeführt, nicht
durchgeführt oder weiterhin unbekannt abgeglichen. Ein organisatorischer Halt
stoppt keine Chemie. Quarantäne, expliziter Abbruch und Materialübergabe bleiben
von bestätigtem chemischem Stopp getrennt.

## Reale Zeit mit ausgewiesenen Grenzen

`manual_process_clock.py` erfasst UTC und monotone Beobachtungen einschließlich
Quellenkennung, Kontinuitätsbereich, Prozesskennung, Unsicherheit und
Suspend-Vertrag. Der Zustand enthält eine untere und eine gegebenenfalls
unbekannte obere Grenze verstrichener Zeit. UTC-Differenzen werden nicht als
Beweis einer verstrichenen Unterbrechung verwendet.

Der Standardanbieter `SystemClock` ist **unqualifiziert**: keine bezifferte
Unsicherheit, kein Nachweis suspend-inklusiver Kontinuität und deshalb keine
endliche obere Zeitgrenze. Er ermöglicht Aufzeichnung, aber keine qualifizierte
zeitkritische Aktivierungsfreigabe. Jede neue Anbieterinstanz, insbesondere ein
neuer CLI-Prozess, besitzt einen neuen Kontinuitätsbereich und öffnet eine
abzugleichende Lücke. Ein getesteter Provider mit `test_clock` bleibt im Lauf
und in jedem Beleg ausdrücklich Testquelle; er wird nicht zum realen Nachweis
umbenannt. Ein qualifizierter realer Zeitprovider ist damit nicht nachgewiesen.

`resume` erneuert die Sitzung, behält Material- und Reaktionszustand und fordert
Abgleich; es spielt keine Wirkung erneut ab. `resolve_clock_gap` benötigt eine
begründete Zeitspanne mit Evidenzbezug. Ein unbekanntes Maximum bleibt
unbekannt; eine schon vorher unbegrenzte Obergrenze wird nicht durch eine
spätere gute Beobachtung endlich. `reconcile` setzt weder die Aufgabenfrist
noch eine Reaktionsfrist zurück. Zeit schreitet auch bei Halt weiter.
Der Bericht trennt den zuletzt gespeicherten Uhrzustand von einer aktuellen,
**nicht gespeicherten** Schätzung.
Bei einem nachträglich erfassten Stopp wird die Erfassung nicht als Zeitpunkt
des physischen Stopps ausgegeben. Ohne belastbare Zuordnung der beobachteten
Zeit zur Prozessuhr bleibt die Mindestexposition konservativ null; das ist
keine Behauptung einer tatsächlich sofortigen Beendigung.

## Original-QC, Zuordnung und Abschluss

`attach_qc` beziehungsweise `import_results` archiviert unveränderte Dateibytes
mit Prüfsumme und Herkunft. Die erste Implementierung behandelt sie als opake
Originale; sie enthält keinen Herstellerdecoder. `map_qc` ordnet einen Befund
manuell über Lauf/Reaktion, tatsächliches Produkt, Rolle, Methode, Assay,
Kalibrier-/Primerbezug und Originalzeile beziehungsweise Well zu. Zeitstempel
und Zeilenreihenfolge allein beweisen keine Probenidentität.

Die Zustände `quantified`, `below_loq`, `not_detected`, `invalid` und `unknown`
bleiben unterscheidbar. Nicht quantifizierbare Werte erhalten keinen erfundenen
Nullwert. Regeln werden nach H3K4me3, IgG, Input und NTC getrennt gebunden;
die NTC belastet kein Probenmaterial. `begin_qc_withdrawal` bucht eine Entnahme
gegen das tatsächliche Produkt, nicht erneut gegen den verbrauchten Eingang.
Manuelle Verdünnungsangaben bleiben belegte Angaben; eine zweite automatische
Korrektur der Originalkonzentration wird nicht unterstellt.

Widersprüchliche Zuordnungen bleiben mit dem Originalbeleg erhalten und führen
zur Quarantäne. `clarify_qc` erlaubt mit begründetem Beleg entweder eine neue
Zuordnung (`allow_remap`) oder den Ausschluss (`exclude`). Frühere Zuordnungen
werden entwertet und müssen erneut geprüft werden; Originalbytes und frühere
Versuche bleiben erhalten. `resolve_deviation` dokumentiert eine gesonderte
Abweichungsentscheidung erst nach Klärung offener Wirkungen, aktiver Reaktionen,
Zeitlücken und QC-Quarantäne. Der vollständige Inventar-/Arbeitsplatzabgleich
bleibt anschließend erforderlich.

`review_qc` bewertet die technische Zuordnung, `review_biology` hält eine
separate fachliche Entscheidung gegen vorab gebundene Kriterien fest. Eine
gute spätere Messung löscht einen früheren Abweichungsbefund nicht.
Der Bericht zeigt außerdem, ob eine frühere biologische Entscheidung noch auf
den aktuell gültigen technischen Belegen beruht.

`close_capture` verlangt vollständigen Materialabgleich, ausdrückliche
Dispositionen und bestätigte Übergabe. `capture_completed` bedeutet den
Abschluss dieses Aufzeichnungskopfes. Es bedeutet keine vollständige
SOP-Ausführung, biologische Eignung oder abgeschlossene E4-Abnahme.

## Versionierung und Prüfgrenzen

Zustand und Definition bilden das geschlossene Paar
`solidcraftbot.material-workflow-state/3` und
`solidcraftbot.material-workflow-definition/3`, mit dem Engine-Typ
`cutrun_manual_capture/1`. Generische oder synthetische Runner können diesen
Vertrag nicht übernehmen. Frühere `/1`-/`/2`-Läufe werden nicht umgedeutet oder
still migriert. Quellen und Laufzeitdateien sind gepinnt. Bei geänderten
Runtimebytes verlangt ein aktiver alter Lauf Inspektion statt stiller
Wiederaufnahme mit neuem Code.

Nachgewiesen wird der Softwarevertrag mit ausdrücklich gekennzeichneten
Testbeobachtungen. Vollständige SOP-Stufenfolge und sämtliche Reagenzverbräuche,
realer Temperatur-/Zeitnachweis, native QC-Decoder, Geräte-/Hardwareausführung,
Personenauthentifizierung und biologische Akzeptanz sind gesonderte Arbeiten.
Der SOP-Entwurf bleibt bytegleich gebunden; O12 und die vollständige E4-Abnahme
werden durch diesen ersten Kernel nicht geschlossen.

Gezielte Prüfungen starten mit:

```sh
python3 -B -m unittest discover -s tests -p 'test_cutrun_manual_*.py' -v
python3 -B -m unittest discover -s tests -p 'test_manual_process_clock.py' -v
python3 -B -m unittest discover -s tests -p 'test_material_v3.py' -v
```

Die Schemafälle benötigen die optionale Entwicklungsabhängigkeit `jsonschema`.
Die Laufzeittests verwenden ausdrücklich gekennzeichnete Testquellen; die
CLI-Tests prüfen zusätzliche echte Prozesswechsel mit der Systemuhr.
