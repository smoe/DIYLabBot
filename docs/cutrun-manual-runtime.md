# Manueller CUT&RUN-Aufzeichnungskern

Stand 12. November 2026: Der manuelle Aufzeichnungskern für
SK-Mel-29/H3K4me3 ist um einen eigenen SOP-Stufenvertrag erweitert. Er bindet den
[SOP-Entwurf 0.1](cutrun-manual-sop-draft.md), bewahrt Beobachtungen und
Originaldateien und verwendet den gemeinsamen Materiallebenszyklus. Er erzwingt
die vollständige lokale Stufenfolge S01–S12 und prüft phasenbezogene Zeit- und
Temperaturbelege. Er führt keine Geräte oder biochemischen Arbeitsgänge aus.
**`execution_ready`,
`reference_success` und `passed` bleiben im Bericht falsch.** Ein geschlossenes
Aufzeichnungsprotokoll ist kein erfolgreicher E4-Referenzlauf. Die vollständige
E4-Abnahme und O12 aus dem SOP-Entwurf bleiben offen.

Der neue Engine-Typ `cutrun_manual_sop/1` ist vom bisherigen
`cutrun_manual_capture/1` getrennt. Beide verwenden denselben Material-/3-Vertrag,
dasselbe Journal und dieselbe Bilanz. Vorhandene Aufzeichnungsläufe werden
nicht zu SOP-Läufen migriert. Die CLI legt neue Läufe mit dem SOP-Vertrag an;
beim Lesen wird der gespeicherte Engine-Typ geprüft.

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
Der SOP-Vertrag ergänzt die Stufen- und Phasenfolge. Die vollständigen
Herstellerrezepte, einzelne Waschunterpunkte und alle Rezeptkomponenten werden
weiterhin aus dem gebundenen Original bezogen und nicht durch einen Decoder
geprüft. Eine freie Notiz beweist keinen Stufenabschluss oder erfolgreichen
Gerätevorgang.

## Einstieg und gemeinsame Speicherung

Die gemeinsame Erweiterung liegt in
[`cutrun-manual-sop.protocol.json`](../model/cutrun-manual-sop.protocol.json)
mit [Protokollschema](../model/cutrun-manual-sop.protocol.schema.json) und
[`cutrun-manual-sop.profile.json`](../model/cutrun-manual-sop.profile.json)
mit [Profilschema](../model/cutrun-manual-sop.profile.schema.json).
Die bisherige Profilquelle führt weiterhin Rollen, Reagenzzuteilung, QC und
neun offene Basisparameter. Das SOP-Profil ergänzt acht Phasen mit insgesamt
32 ebenfalls offenen numerischen Dauer-/Temperaturgrenzen sowie offenen
Qualifikations- und Originalbezügen. Es setzt keine Herstellerbeispiele als
bestätigte Laborwerte ein.

```sh
python3 scripts/run_cutrun_manual.py --help
python3 scripts/run_cutrun_manual.py prepare
```

`prepare` liest Quellen und Bereitschaft ohne Store, Reservierung oder
Materialbuchung. Ohne weitere Eingaben bleibt die Vorlage unvollständig.
`--profile`, `--sop-profile`, `--original-pdf` und `--evidence-manifest` wählen ausdrücklich
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
`cutrun_manual_sop_sources.compile_profile(...)`,
`CutRunManualSopWorkflow.create(...)`, `.open(..., resume=True)` und
`.act(..., observation=...)`. `compile_profile` liefert zusätzlich transiente
Artefaktbytes für die atomare Archivierung; sie sind kein zusätzlicher
JSON-Bestand. Der `load`-Adapter kennzeichnet diese Übergabe mit
`_initial_artifacts`, die der gemeinsame Erzeugungspfad verarbeitet.

Die SOP-API erhält als `source` entweder `None` für beide Vorlagen oder
`{"base_profile": ..., "sop_profile": ...}` mit expliziten Dateipfaden oder
Profilobjekten. Der bisherige `CutRunManualWorkflow` bleibt ein eigener
Aufzeichnungskern ohne nachträglich eingeschaltete Stufenpflicht.

## Vollständige lokale Stufenfolge

| Bereich | Verbindlicher Pfad |
|---|---|
| Lauföffnung | S01 vor jeder Materialstufe |
| H3K4me3 und IgG, jeweils getrennt | S02 → S03 → S04 → S05 → S06 → S07 → S08 → S10 |
| Input | S02 → S09 → S10; S09 darf vor den CUT&RUN-Reaktionen stattfinden |
| Gemeinsamer QC-Abschluss | S11 erst nach allen drei gereinigten Produkten, einschließlich NTC-Befund |
| Übergabe | S12 nach aktueller technischer und separater biologischer Bewertung |

`begin_stage(stage_id, reaction_id, stage_run_id)` speichert die Stufenabsicht
vor neuen Wirkungen. Für S01/S11/S12 ist `reaction_id: null` erforderlich.
Jede Stufe erhält einen dauerhaften Datensatz mit dem tatsächlichen Material
und Gefäß bei Beginn. `complete_stage(stage_run_id, receipts, action_ids,
reason)` verlangt genau die im Protokoll benannten Belegkategorien. Die Werte
von `receipts` sind registrierte Originalkennungen beziehungsweise im selben
Lauf archivierte Prüfsummen. `action_ids` verweist auf tatsächlich bestätigte
Buchungen dieses Stufenlaufs. Eine freie `record_observation`-Notiz ersetzt
diese Voraussetzungen nicht und verschiebt keinen Fortschritt.

Neue Material-, Aktivierungs- und QC-Entnahmeabsichten benötigen die passende
offene Stufe. S08 verlangt einen bestätigten Stopp einschließlich Mischung
und eine gebuchte erhaltene Zwischenfraktion; S10 ein gebuchtes gereinigtes
Produkt. Stufenabschlüsse erzeugen selbst keine Zugabe, Mischung, Fraktion
oder Verbrauchsbuchung. S11 prüft jede gebundene Rollen-/Methodenkombination,
zugehörige Produktentnahmen, gültige technische Befunde und eine aktuelle
separate fachliche Bewertung. Dabei kann beispielsweise ein zensierter
IgG-Befund erhalten bleiben; ein erfolgreicher biologischer Referenznachweis
wird daraus nicht automatisch abgeleitet.

Ein Schutzstopp bleibt unabhängig von der normalen Stufenfolge möglich,
auch zu früh, verspätet oder bei Dokumentationsausfall. S07 kann erst nach
belegtem tatsächlichem Stopp abschließen, damit ein bloß notiertes Phasenende
keine weiterhin aktive Reaktion beendet. Ein bereits gespeicherter Schutzstopp
darf als Beleg für S08 referenziert werden; er wird dabei nicht erneut gebucht
oder nachträglich als früherer Stufenauftrag ausgegeben.

## Phasenbezogene Zeit- und Temperaturbelege

Vorbereitung, Antikörperbindung, Enzymbindung, Verdau, Freisetzung, Abtrennung,
Input-Aufbereitung und Reinigung besitzen eigene Phasenkennungen. S08 enthält
Freisetzung und Abtrennung als zwei aufeinanderfolgende Phasen, damit ihre
unterschiedlichen Temperaturbezüge nicht zu einem einzigen Wert verschmelzen.

`record_phase_time(stage_run_id, phase_id, record)` erfasst den beobachteten
Beginn und das beobachtete Ende jeweils als früheste/späteste mögliche
Sekunde in einer ausdrücklich benannten, vorab gebundenen Zeitdomäne.
Die mögliche Dauer lautet `[max(0, Ende_früh − Beginn_spät),
Ende_spät − Beginn_früh]`. Fehlende Grenzen bleiben unbekannt. UTC-Zeitstempel
der Erfassung werden dafür nicht subtrahiert. Bei derselben Prozessuhr kann
eine Phase nicht vor der gespeicherten Stufenabsicht oder in der Zukunft
stattgefunden haben. Bei mehreren Phasen und aufeinanderfolgenden Stufen
muss auch ihre tatsächliche Zeitfolge belegt sein; verschiedene Zeitdomänen
werden ohne belegte Zuordnung nicht gleichgesetzt.

`record_phase_temperature(...)` bindet Beobachtungsintervall, beobachtetes
Minimum/Maximum, Unsicherheit, Zeitdomäne, tatsächlichen Temperaturgeber und
vorab gebundenen Probenbezug. Ein Gerätesollwert oder kalter Ablageplatz
qualifiziert keine Probentemperatur. Zulässig sind direkte Probenmessung und
ausdrücklich qualifizierter Stellvertreter. Die garantierte Abdeckung reicht
vom spätesten möglichen Messbeginn bis zum frühesten möglichen Messende;
ihre Intervallvereinigung muss die gesamte mögliche Prozessspanne abdecken.
Zwei einzelne Temperaturpunkte belegen keine kontinuierliche Abdeckung.
Auch die vollständige Unsicherheitshülle muss innerhalb der lokal gebundenen
Grenzen liegen. Ein später guter Abschnitt löscht einen widersprüchlichen
früheren Befund nicht.

Beide Belegarten enthalten stabile Identitäten für Beleg, Stufenlauf, Phase,
Reaktion, Material und Gefäß sowie Herkunft und Originalprüfsumme.
`attach_sop_evidence(file_name, origin)` mit Originalbytes in `act(artifact=...)`
archiviert auch erst während des Laufs entstandene Stufen- und Gerätedateien
atomar. Diese Dateien können anschließend per Prüfsumme referenziert werden;
die unveränderliche Definition wird dafür nicht umgeschrieben. Prospektive
Grenz- und Qualifikationsentscheidungen bleiben vor dem Lauf gebunden.

Wiederanlauf behält offene Stufen, ursprüngliche Absichten und alle Belege.
Er startet keine Stufe erneut und erneuert keine Frist. Eine extern belegte
Phasendauer qualifiziert nicht still die globale Prozessuhr und schließt keine
unbekannte Neustartlücke. Späte Widersprüche entwerten die aktuelle Konformität
auch bereits abgeschlossener Stufen und sperren normalen Fortschritt und
Abschluss. Belege und frühere Abschlüsse bleiben erhalten. Ein expliziter
Abbruch mit Inventar-/Quarantäneübergabe bleibt getrennt davon möglich.

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
`solidcraftbot.material-workflow-definition/3`, mit den getrennten Engine-Typen
`cutrun_manual_capture/1` und `cutrun_manual_sop/1`. Generische oder synthetische Runner können diesen
Vertrag nicht übernehmen. Frühere `/1`-/`/2`-Läufe werden nicht umgedeutet oder
still migriert. Quellen und Laufzeitdateien sind gepinnt. Bei geänderten
Runtimebytes verlangt ein aktiver alter Lauf Inspektion statt stiller
Wiederaufnahme mit neuem Code.

Nachgewiesen wird der Softwarevertrag mit ausdrücklich gekennzeichneten
Testbeobachtungen. Sämtliche einzelnen Herstellerrezept- und Waschunterpunkte,
alle Reagenzkomponentenverbräuche,
realer Temperatur-/Zeitnachweis, native QC-Decoder, Geräte-/Hardwareausführung,
Personenauthentifizierung und biologische Akzeptanz sind gesonderte Arbeiten.
Der SOP-Entwurf bleibt bytegleich gebunden; O12 und die vollständige E4-Abnahme
werden durch die Softwareprüfung nicht geschlossen.

Gezielte Prüfungen starten mit:

```sh
python3 -B -m unittest discover -s tests -p 'test_cutrun_manual_*.py' -v
python3 -B -m unittest discover -s tests -p 'test_manual_process_clock.py' -v
python3 -B -m unittest discover -s tests -p 'test_cutrun_sop_evidence.py' -v
python3 -B -m unittest discover -s tests -p 'test_material_v3.py' -v
```

Die Schemafälle benötigen die optionale Entwicklungsabhängigkeit `jsonschema`.
Die Laufzeittests verwenden ausdrücklich gekennzeichnete Testquellen; die
CLI-Tests prüfen zusätzliche echte Prozesswechsel mit der Systemuhr.
