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

Die zusätzliche [Wasch- und Reagenzerweiterung](cutrun-manual-runtime.md#merged-cutrun-manual-recipe)
führt inzwischen die ausgewählten Waschfolgen, Arbeitsmischungen,
Fraktionsentnahmen und Säulenbeladungen über dasselbe Ledger. Ihr eigener
Engine-Typ `cutrun_manual_recipe/1` behält die offenen Laborparameter und die
bisherigen Laufverträge bei.

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
Der SOP-Vertrag ergänzt die Stufen- und Phasenfolge. Im reinen Stufenvertrag
werden Herstellerrezepte, einzelne Waschunterpunkte und Rezeptkomponenten
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
`cutrun_manual_capture/1`, `cutrun_manual_sop/1` und
[`cutrun_manual_recipe/1`](cutrun-manual-runtime.md#merged-cutrun-manual-recipe). Generische oder synthetische
Runner können diesen
Vertrag nicht übernehmen. Frühere `/1`-/`/2`-Läufe werden nicht umgedeutet oder
still migriert. Quellen und Laufzeitdateien sind gepinnt. Bei geänderten
Runtimebytes verlangt ein aktiver alter Lauf Inspektion statt stiller
Wiederaufnahme mit neuem Code.

Nachgewiesen wird der Softwarevertrag mit ausdrücklich gekennzeichneten
Testbeobachtungen. Die zusätzliche Rezeptfassung prüft die ausgewählten
Waschgruppen, Komponentenansätze und Istverbräuche. Reale
Rezeptur-/Konzentrationsbestätigung, Temperatur-/Zeitnachweis, native QC-Decoder,
Geräte-/Hardwareausführung,
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

<a id="merged-cutrun-manual-recipe"></a>

<a id="merged-cutrun-manual-recipe--manueller-cutrun-vertrag-waschfolgen-und-reagenzverbrauch"></a>

## Manueller CUT&RUN-Vertrag: Waschfolgen und Reagenzverbrauch

Der Engine-Vertrag `cutrun_manual_recipe/1` ergänzt die
[vollständige lokale SOP-Stufenfolge](cutrun-manual-runtime.md) um die
Wasch-, Zugabe-, Fraktions- und Säulenoperationen des gewählten frischen,
unfixierten Zweigs mit separatem Input und Reinigung nach VII-A. Er verwendet
weiterhin das gemeinsame Material-/3-Journal und Ledger. Es entsteht weder
eine zweite Mengenbilanz noch ein Geräteadapter.

Die operative Referenz bleibt die im [SOP-Entwurf 0.1](cutrun-manual-sop-draft.md)
gepinnte CST-Original-PDF, Revision 09/2026. Die Quelle enthält semantische
Arbeitsaufträge und Quellenstellen; die vollständigen quantitativen Rezepte
bleiben im mitzuführenden Original. Lokale Freigaben, Gerätequalifikation,
Konzentrationen und biologische Ergebnisse werden dadurch nicht bestätigt.
`execution_ready` und `reference_success` bleiben falsch.

<a id="merged-cutrun-manual-recipe--gemeinsame-quellen-und-offene-parameter"></a>

### Gemeinsame Quellen und offene Parameter

- [`cutrun-manual-recipe.protocol.json`](../model/cutrun-manual-recipe.protocol.json)
  beschreibt Reagenzrollen, Komponentenbeziehungen, die Reihenfolge der
  Arbeitsschritte und den jeweiligen Quellenbezug.
- [`cutrun-manual-recipe.profile.json`](../model/cutrun-manual-recipe.profile.json)
  bindet konkrete Materialien, Gefäße, Chargen, Vorbereitungen, Mengen,
  Wiederholungen und Nachweise. Die beiden zugehörigen Schemas beschreiben
  ausschließlich die unterstützten Felder.
- Das bisherige Basisprofil und das Zeit-/Temperaturprofil werden referenziert
  und gemeinsam gepinnt. Der lokale SOP-Entwurf bleibt bytegleich.

Alle neuen numerischen Profilwerte sind zunächst `null`. Dasselbe gilt für
noch nicht entschiedene Varianten, Istidentitäten und Nachweisbezüge.
Herstellerangaben wie zwei Waschzyklen stehen separat als `source_facts`;
sie werden nicht als bereits bestätigte lokale Durchführung oder gemessener
Verbrauch eingesetzt. Ein lokaler Wiederholungsplan muss zum ausdrücklich
gewählten Quellenzweig passen. Ein deaktivierter Pflichtschritt ist kein
Ersatz für einen fehlenden Beleg.

`incoming_preparation` unterscheidet noch durchzuführende Eingangsvorbereitung
(`perform`) von bereits extern durchgeführter Vorbereitung (`external`).
Externe Vorbereitung benötigt einen eigenen Originalbeleg; sie wird nicht
aus dem Vorhandensein eines Zellgefäßes angenommen. Die Wahl
`cell_wash_branch` unterscheidet die Standardwäsche von `low_cell_omit`.
Eine belegte Low-Cell-Entscheidung kann die dafür benannte Zellwäsche auslassen;
sie setzt keine anderen Waschgruppen außer Kraft. Ohne Wahl und Nachweis bleibt
der betroffene Arbeitsgang unvollständig.

`permeabilization` trifft dieselbe ausdrückliche Wahl für den
Permeabilisierungsbefund: `perform` führt einen separaten Prüfaliquotansatz im
Lauf, `external` verlangt dessen vorhandenen Originalbeleg. Bei Durchführung
werden Aliquotentnahme, Waschpuffer, Digitonin, Färbereagenz und beobachtete
Auswertung einzeln erfasst. Das Prüfaliquot besitzt sein eigenes tatsächliches
Gefäß; die Hauptprobe erhält keine erfundene Zellzahl aus einem Volumen.
Externe Evidenz ersetzt diese in diesem Lauf nicht durchgeführten Buchungen
und erzeugt keinen fiktiven Reagenzverbrauch.

<a id="merged-cutrun-manual-recipe--erfasste-arbeitsgruppen"></a>

### Erfasste Arbeitsgruppen

| Gruppe | Gepinnter Quellenbezug | Material- und Fraktionsvertrag |
|---|---|---|
| Eingangsvorbereitung | II-A.2–7, S. 4–5 | Ausgangstrennung, gewählte Zellwäsche, Resuspension und getrennt identifizierter Input; bereits extern erledigte Vorbereitung nur mit Beleg |
| Bead-Aktivierung | I.3–7, S. 4 | Eigene Bead-Fraktion, Aktivierungspuffer, Waschzyklen und abschließende Resuspension; einmalige gemeinsame Vorbereitung wird nicht für jeden Antikörperzweig erneut gebucht |
| Permeabilisierungsprüfung | Anhang A, S. 10 | Separates Prüfaliquot mit Waschpuffer, Digitonin, Färbereagenz und Originalbefund oder ausdrücklich zugeordnete externe Prüfung |
| Bead-/Antikörperansatz | III.2–7, S. 6 | Bead-Zugabe, Mischung, Abtrennung des Mediums, Antikörper-Arbeitsmix und rollenspezifischer Antikörper |
| Enzymbindung | IV.1–4, S. 6 | Antikörpermedium entfernen, Digitoninwäsche, Enzym-Arbeitsmix zugeben |
| Vor Aktivierung | V.1–5, S. 7 | Enzymmedium entfernen, wiederholte Digitoninwäsche und vorhandenen Aktivierungsbeleg übernehmen |
| Stopp und Freisetzung | V.7–10, S. 7 | Vorhandenen Stoppbeleg übernehmen, Mischung/Trennung erfassen und produktführenden Überstand getrennt von der Bead-/Zellfraktion führen |
| Input | VI, S. 7 | Eigener Extraktions-Arbeitsmix, Behandlung und geklärter Input; keine Antikörper-/Aktivierungs-/Stoppreaktion |
| Säulenreinigung | VII-A.1–13, S. 8 | Vorbereiteter Bindepuffer, tatsächliche Beladungen und Durchflüsse, Säulenwäsche, Trocknung und eindeutig zugeordnetes Eluat |

Die Bead-Aktivierung hat einen eigenen Materialträger; ihre Waschungen dürfen
nicht versehentlich gegen die Zellprobe gebucht werden. Ist aktivierte
Bead-Suspension bereits ausgegeben, ersetzt der ausdrückliche externe
Vorbereitungsbeleg ihre erneute Herstellung im Lauf.

Fixierte Proben, Entkreuzung, organische Reinigung und Spike-in-Normalisierung
sind keine stillen Alternativen dieses Vertrags. Insbesondere bleibt der im
SOP-Entwurf dokumentierte Reagenzkennungswiderspruch O10 offen, bis er mit einem
zugeordneten Beleg geklärt ist.

<a id="merged-cutrun-manual-recipe--arbeitsmischungen-und-einmaliger-stockverbrauch"></a>

### Arbeitsmischungen und einmaliger Stockverbrauch

Jede Reagenzrolle bindet `mode`, Material- und Gefäß-ID, Chargen-/
Vorbereitungsbezug und einen Originalbeleg. `components` enthält die
prospektiven Komponentenentnahmen; `output_quantity` beschreibt die geplante
Arbeitsmischung. Unbekannte Mengen bleiben unbekannt.

`issued` bezeichnet ein tatsächlich vorhandenes Anfangsaliquot. Ein bereits
vorbereiteter Arbeitsmix verlangt zusätzlich seinen Vorbereitungsbezug.
Beim späteren Dosieren wird dieses Aliquot belastet; seine ursprünglichen
Stockkomponenten werden nicht noch einmal im Lauf verbraucht. Das gilt auch
für die nachgewiesene Vorbereitung des Bindepuffers mit Isopropanol und des
Säulenwaschpuffers mit Ethanol.

`prepared` bezeichnet eine erst im Lauf herzustellende Arbeitsmischung.
Material-ID und anfänglich freies Gefäß werden vorab reserviert. Dies ist eine
Reservierung zukünftiger Identität, keine Behauptung, dass die Mischung bereits
physisch existiert. `begin_prepare_mix` speichert die Absicht vor einer Wirkung;
`confirm_prepare_mix` bucht die tatsächlichen Komponentenentnahmen und den
beobachteten Ansatz atomar. Der Ansatz entsteht als kanonisches
`intermediate` mit der Rolle `working_reagent` und seinen Komponenten als
Eltern. Spätere Dosen belasten diesen Ansatz. Sollmenge und tatsächliche
Ausbeute bleiben getrennt; eine abweichende oder unbekannte Herstellung
liefert keine automatische Freigabe zum Dosieren.

Der optionale Vertrag für geplante Schutzstoppmischungen gilt nur in diesem
Engine-Typ. Andere Material-/3-Läufe erhalten dadurch keine zukünftigen
Reagenzquellen. Ein vorbereiteter Stoppweg benötigt vor Aktivierung einen
tatsächlich verfügbaren, nachvollziehbar hergestellten oder ausgegebenen
Ansatz; eine Identitätsreservierung allein genügt nicht.

<a id="merged-cutrun-manual-recipe--elementare-wirkungen-und-wiederanlauf"></a>

### Elementare Wirkungen und Wiederanlauf

`recipe_next(stage_run_id)` zeigt den nächsten erforderlichen Schritt,
Zyklus und die nächste elementare Operation. Eine Wäsche besteht aus
getrennter Zugabe, Mischung, beobachteter Trennung und Fraktionsentnahme.
Die Säulenwäsche hat keine erfundene Pipettenmischung. Die Trocknung hat
keine zusätzliche Waschpufferdosis.

`begin_recipe_operation` speichert die Absicht einschließlich ihrer
Materialwirkung oder der noch erforderlichen physischen Beobachtung.
`confirm_recipe_operation` erfasst Istmengen beziehungsweise die ausdrückliche
Misch-, Trenn- oder Trocknungsbestätigung. Eine verstrichene Wartezeit bestätigt
keine physische Trennung. Beibehaltene und entfernte Fraktionen erhalten eigene
Material- und tatsächliche Gefäßkennungen; eine Entnahme in dasselbe Gefäß
ist keine Trennung. Entfernung wird nicht automatisch als Entsorgung gebucht.
Enddisposition und Ort bleiben gesonderte bestätigte Beobachtungen.

Aktivierung und Stopp verwenden ihre vorhandenen Absichten und Belege.
Der Rezeptfortschritt übernimmt diese Buchung; er erzeugt keine zweite Dosis.
Der Schutzstopp bleibt auch bei fehlender Nominalkonformität zugänglich.

Nach Unterbrechung bleiben Materialbuchung und Rezeptfortschritt erhalten.
Unklare Mischungen, Trennungen oder Entnahmen werden mit `mark_recipe_unknown`
und `resolve_recipe_operation` als unbekannt, durchgeführt oder nicht
durchgeführt abgeglichen. Weder ein erneuter Start noch ein Inventarabgleich
bestätigt die Wirkung. Ohne Klärung erfolgt kein automatisches Wiederholen,
kein Zyklusfortschritt und keine Freigabe der betreffenden Verantwortung.
Ein unbekannter Istverbrauch ist kein Nullverbrauch und kann weitere
Anweisungen sperren.
Eine zunächst unbekannte, später tatsächlich belegte Ansatzmenge wird mit
`resolve_prepared_output` geklärt. Ursprünglicher Beleg und neue Bestätigung
bleiben erhalten; Stocks werden dabei nicht erneut belastet. Nach ausdrücklich
bestätigter Nichtdurchführung darf ein neuer Ansatzversuch dieselbe reservierte
Mischungsidentität verwenden, ohne eine zweite Zuteilung oder eine frühere
physische Herstellung zu behaupten.

<a id="merged-cutrun-manual-recipe--säulen-durchflüsse-und-eluat"></a>

### Säulen, Durchflüsse und Eluat

Säule, Sammelgefäß und Eluatgefäß werden je Rolle als konkrete physische
Instanzen gebunden. Sie sind keine Flüssigkeitsmengen. Vorbereitungs- und
Zuordnungsbelege gehören zur Bindung; eine Säule darf nicht unbemerkt zwischen
Reaktionen wechseln.
Ihre Identität wird im bestehenden dauerhaften Zuteilungsindex reserviert,
ohne eine Flüssigkeitsmenge oder einen zweiten Bestand anzulegen. Ein späterer
unabhängiger Lauf kann dieselbe verbrauchte Säulenkennung daher nicht wieder
als frische Säule einführen.

Die Beladung verwendet die bekannte tatsächliche Restmenge des angesetzten
Gemischs. Die nächste geplante Portion darf die lokal gebundene Kapazität
nicht überschreiten. Der Zyklus wird fortgeführt, bis der kanonische Rest
beobachtet vollständig verarbeitet ist. Eine feste Zahl von Beladungen wird
nicht aus einem Herstellerbeispiel übernommen. Jeder Durchfluss bleibt eine
ausdrücklich zugeordnete Fraktion. Unbekannter Rest oder unklare Beladung
beendet die Schleife nicht erfolgreich.

Wasch-, Rest- und Elutionsfraktionen bleiben unterscheidbar. Erst die
bestätigte Elution in das gebundene Produktgefäß liefert das gereinigte
Produkt für die vorhandene QC. Ein freier Textbefund oder eine generische
Materialaktion ersetzt keine fehlende Waschung oder Beladung.

<a id="merged-cutrun-manual-recipe--einstieg-versionierung-und-grenzen"></a>

### Einstieg, Versionierung und Grenzen

Die API verwendet `cutrun_manual_recipe_sources.compile_profile(...)` und
`CutRunManualRecipeWorkflow.create(...)`. Die gemeinsame Auswahl hat genau
die Schlüssel `base_profile`, `sop_profile` und `recipe_profile`; jeder Wert
wählt eine ausdrücklich übergebene Quelle oder die jeweilige Vorlage.
`compile_profile` erzeugt keine Laufzeitwirkung.

Der gemeinsame CLI-Einstieg bleibt `python3 scripts/run_cutrun_manual.py`.
`--profile`, `--sop-profile` und `--recipe-profile` wählen die drei Quellen;
Original-PDF und Evidenzmanifest werden weiter ausdrücklich übergeben.
Die Unterbefehle `prepare`, `create`, `status`, `report`, `resume` und `act`
verwenden denselben Store und dieselben Ausgaberegeln wie bisher.

Die neuen Profile und Laufzeitquellen werden gepinnt und ihre Originalbytes
archiviert. Alte `cutrun_manual_capture/1`- und `cutrun_manual_sop/1`-Läufe
bleiben eigene Verträge. Sie werden beim Lesen erkannt, aber nicht als
vollständige Rezeptläufe umgedeutet. Geänderte Laufzeitdateien erfordern bei
aktiven alten Läufen eine Prüfung statt stiller Migration.

Geprüft wird der Softwarevertrag mit ausdrücklich gekennzeichneten
Testbeobachtungen. Reale Rezeptur-/Konzentrationsbestätigung,
Geräte-/Pipettierleistung, Temperatur-/Zeitqualifikation und biologische
Eignung benötigen weiterhin ihre eigenen Nachweise. Der Herstelleranhang
bleibt mitzuführen; ein vollständig aufgezeichneter manueller Lauf ist keine
behauptete Geräteausführung oder abgeschlossene E4-Abnahme.
Der Bericht unterscheidet deshalb `selected_wash_and_reagent_contract_checked`
von `vendor_recipe_completeness_checked`: Der ausgewählte manuelle Vertrag
wird geprüft; die unabhängige Vollständigkeit aller Herstelleranweisungen
wird weiterhin nicht behauptet.
