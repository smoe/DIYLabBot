# Manueller CUT&RUN-Vertrag: Waschfolgen und Reagenzverbrauch

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

## Gemeinsame Quellen und offene Parameter

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

## Erfasste Arbeitsgruppen

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

## Arbeitsmischungen und einmaliger Stockverbrauch

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

## Elementare Wirkungen und Wiederanlauf

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

## Säulen, Durchflüsse und Eluat

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

## Einstieg, Versionierung und Grenzen

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
