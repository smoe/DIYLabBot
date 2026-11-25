# O08 · Roh-DNA-QC für den manuellen CUT&RUN-Referenzlauf

**Entwurf zur Entscheidung, 25. November 2026. O08 ist offen.** Der Vorschlag
gilt für S11 des SK-Mel-29/H3K4me3-Referenzlaufs mit dem CST CUT&RUN Assay Kit
#86652. Gegenstand sind die gereinigten H3K4me3-, IgG- und Input-Produkte. Die
Größenprüfung des Input in S09 bleibt ein eigener Beleg. Die in der Publikation
beschriebene Qubit-/Agilent-QC betrifft Libraries. Lokale Roh-DNA-Kriterien
werden für S11 gesondert festgelegt.
[Lokaler SOP-Entwurf](../cutrun-manual-sop-draft.md#7-produkt-qc-und-abschlusskriterien),
[Möller et al., Methoden 2.4](https://pmc.ncbi.nlm.nih.gov/articles/PMC12839168/)

## Synthetische Umsetzung

Der qPCR-Vertrag `/1` und der Qubit-Vertrag `solidcraftbot.cutrun-qubit-results/1`
lassen sich mit ausdrücklich als `test_fixture` markierten JSON-Exporten
prüfen. Die Beispiele enthalten erfundene Messwerte und Einstellungen.

```sh
python3 scripts/run_cutrun_o08.py inspect \
  --plan tests/fixtures/cutrun-o08/qpcr-plan.json \
  --export tests/fixtures/cutrun-o08/qpcr-export.json
python3 scripts/run_cutrun_o08.py inspect \
  --plan tests/fixtures/cutrun-o08/qubit-plan.json \
  --export tests/fixtures/cutrun-o08/qubit-export.json
```

`inspect` liest und normalisiert die Dateien ohne Journal. Für die Erfassung
im bestehenden E4-Testlauf des Rezeptvertrags `/2` stehen `bind`, `import`
und `report` zur Verfügung. Dazu in S11 mit `begin_qc_withdrawal` und
`confirm_material_action` die simulierten Entnahmen erfassen. Im Plan die
tatsächlichen IDs des Testlaufs und die bestätigten Entnahmen referenzieren.
Der Export muss die SHA-256 der gebundenen Plandatei und ihre Geräte- und
Assaykennungen führen. Der qPCR-Plattenbezug und der Qubit-Messserienbezug
stehen in `acquisition.container_id`. `qc_bindings` referenziert je Rolle den
E4-Assaybezug und den Kriterienbeleg. Die Kennung des Messassays bleibt in
`acquisition.assay_id` erhalten.

- `bind RUN --session SESSION --actor ACTOR --observation OBS.json --plan PLAN.json`
  archiviert den Plan und bindet seine Positionen, Präparationen und
  tatsächlichen Entnahmen. Mehrere Wells dürfen eine Präparation teilen. Das
  insgesamt verwendete Eluat wird gegen die bestätigte Entnahme geprüft.
- `import RUN --session SESSION --actor ACTOR --observation OBS.json --plan-id ID --export EXPORT.json`
  archiviert Originalbytes und Zeilenfundstellen im selben Journal. Fehlende
  Positionen, unklare Kontrollen und Ergebnisse außerhalb des Bereichs bleiben
  als Befunde sichtbar und erzeugen keine E4-Zuordnung aus diesem Export.
  Identitätskonflikte gehen in die bestehende QC-Quarantäne. Ein verwendbarer
  Export erzeugt atomare `map_qc`-Zuordnungen. Die technische Prüfung und
  fachliche Bewertung bleiben eigene Handlungen im bestehenden E4-Runner.
- `report RUN` zeigt den gebundenen Plan, Originalprüfsummen, aktuelle und
  frühere Auswertungen sowie die zugehörigen Mapping-IDs. Ein bytegleicher
  Wiederimport ist idempotent. Eine Neuauswertung braucht eine eigene
  `analysis_revision` und den SHA-256 des abgelösten aktiven Exports in
  `supersedes_sha256`. Frühere Zuordnungen und technische Prüfungen verlieren
  dabei ihre Gültigkeit. Das Materialjournal wird durch Importe und
  Neuauswertungen nicht erneut belastet.

Für ein außerhalb des Bereichs liegendes Qubit-Ergebnis ist eine neue
Messserie mit eigenem Plan und bestätigter Entnahme möglich. Die drei
Konzentrationsbezüge `assay_solution`, `prepared_sample` und `original_eluate`
bestimmen, welche Volumenfaktoren einmalig angewandt werden. Der Bericht
enthält den Gerätewert, den Bezugswert in `ng/uL` und die verwendeten Faktoren.

Die Erweiterung akzeptiert ausschließlich E4-Testläufe. Reale Exportformate,
Gerätebindungen, Grenzwerte und übrige Laborparameter bleiben offen.

## qPCR-Vorschlag

Für den ersten Referenzlauf genügt als vorgeschlagener Umfang ein Positivlocus,
**humanes RPL30 Exon 3 mit den Kit-Primern CST #7014**. Die H3K4me3-Reaktion,
die IgG-Kontrolle, der aufbereitete Input und die PCR-Leerkontrolle (NTC)
liegen auf derselben Platte unter denselben Assaybedingungen. Für die
Farbstoff-qPCR mit Schmelzkurvenanalyse ist CST SimpleChIP Universal qPCR
Master Mix #88989 der Vorschlag, vorbehaltlich der lokalen Gerätebindung.
Drei technische Wells je Rolle sind der Ausgangspunkt. Zwei Wells kommen
bei knappem Material als vorab festgelegte Variante in Frage. Die Anzahl
unabhängiger CUT&RUN-Ansätze wird in O02 festgelegt.
[CST #86652, Abschnitt VIII](https://media.cellsignal.com/pdf/86652.pdf#page=8),
[CST #88989](https://media.cellsignal.com/pdf/88989.pdf)

### Ergebnisvertrag `solidcraftbot.cutrun-qpcr-results/1`

Der normalisierte Beleg enthält einen Datensatz pro geplantem Well. Der
Plattenplan wird mit Revision und Prüfsumme vor der Auswertung gebunden.
Die Spalten realer Exporte werden anhand eines Geräteoriginals festgelegt.

| Bereich | Pflichtangaben und Zuordnung |
| --- | --- |
| Lauf und Assay | `run_id`, `attempt_id`, `instrument_run_id`, `plate_id`, Gerätekennung, Software und Auswertungsrevision, Assay-/Primerkennung, Reagenzchargen, Auswertungsparameter für Baseline und Schwelle sowie gegebenenfalls Kalibrierreferenz. |
| Original | Unveränderte Exportdateien mit Dateiformat, SHA-256 und Fundstelle für jeden Messwert. Amplifikations- und Schmelzkurven sowie Geräteflags im verfügbaren Originalformat archivieren. Eine spätere Auswertung erhält eine eigene Revision mit Bezug zum Original. |
| Well | Eindeutige Kombination aus Gerätelauf, Platte und Well. Der Plattenplan verknüpft sie mit Assay, Rolle und technischer Wiederholung. H3K4me3, IgG und Input führen Reaktions-, Produkt- und Entnahme-ID sowie Bezüge zur bestätigten Aliquotvorbereitung und tatsächlichen Verdünnung. Bei der NTC sind Reaktions-, Produkt- und Entnahme-ID `null`. |
| Messwert | `raw_cq` erhält den Originaleintrag. `cq_status` unterscheidet `determined`, `undetermined`, `invalid`, `not_run` und `missing`. Ein numerischer `cq` ist nur bei `determined` zulässig. Geräteangaben, Schmelzbefund und fachlicher Quantifizierungsstatus sind eigene Felder. Ein Gerät kann einen Cq melden, während der Befund nach den Assaykriterien unter der Quantifizierungsgrenze liegt. |
| Gültigkeit | Der Beleg führt Kriterienrevision, Well-Bewertung und Abweichungsgrund. Die geplanten Wells müssen einzeln nachweisbar sein. Ein fehlendes Well ist eine Beleglücke. Wiederholungen und begründete Ausschlüsse bleiben nachvollziehbar. |

`attach_qc` archiviert die Originale. `map_qc` bindet den daraus geprüften
Befund an die vorhandene E4-Rolle und die Fundstelle. Ein beobachteter Cq unter
der Quantifizierungsgrenze bleibt im Original und im Well-Datensatz erhalten.
Die E4-Zuordnung erhält `below_loq` mit `value=null`. `undetermined` kann erst
nach Prüfung der Kontrollen und der gebundenen Detektionsregel zu
`not_detected` werden. Ein erneuter Import erzeugt keine Materialbuchung.
Mehrere Wells dürfen auf dieselbe bestätigte Produktentnahme verweisen.
Eine neue Produktentnahme erhält eine eigene Absicht und Buchung. Widersprüche
in der Zuordnung folgen der vorhandenen QC-Quarantäne. Technische Prüfung
und fachliche Bewertung folgen weiterhin `review_qc` und `review_biology`.
[E4-Aufzeichnungskern](../cutrun-manual-runtime.md#original-qc-zuordnung-und-abschluss)

### Auswertung und Abnahme

| Rolle | Vorgeschlagene Beurteilung |
| --- | --- |
| H3K4me3 | Erwartetes RPL30-Amplifikations- und Schmelzprofil sowie vorab definierte Replikatübereinstimmung. Die fachliche Bewertung prüft die Anreicherung gegenüber IgG anhand der vorher gebundenen Kriterien. |
| IgG | Erwartet wird geringer Hintergrund. Ein nach den Assaykriterien nicht nachweisbares Signal kann zur Kontrollrolle passen. Der Quotient gegenüber einem nicht quantifizierbaren IgG bleibt ohne Zahlenwert. |
| Input | Nachvollziehbarer Positiv- und Vergleichsbezug für denselben Locus mit tatsächlicher Aufbereitung und Verdünnung. Für `% Input` zusätzlich die ursprüngliche Input-Fraktion beziehungsweise den Zellmengenbezug, die PCR-Effizienz und den gültigen Messbereich belegen. |
| NTC | Im erwarteten Produktbereich der Schmelzkurve ist kein spezifisches Amplifikationssignal vorgesehen. Ein Signal im Zielbereich oder ein unklarer NTC-Befund sperrt die technische Annahme bis zur Klärung. |

Für den ersten Lauf sind dokumentierte Cq-Werte und ein vorab definierter
Vergleich H3K4me3/IgG der Vorschlag. Eine quantitative Angabe wie `% Input`
benötigt zusätzlich eine geeignete Effizienz- und Bereichsprüfung, etwa mit
einer Input-Verdünnungsreihe, und die tatsächlichen Bezugsgrößen der Proben.
Cq-Grenzen, Schmelzbereich, Replikatstreuung, LoD, LoQ und numerische
Anreicherungsgrenzen bleiben offen, bis lokale Belege und festgelegte
Kriterien vorliegen. Ergebnisse außerhalb des belegten Bereichs bleiben
als solche erkennbar. [MIQE 2.0](https://academic.oup.com/clinchem/article/71/6/634/8119148)

## Fluorometrie-Vorschlag

**Qubit 4 mit Qubit 1X dsDNA High Sensitivity, Thermo Fisher #Q33230.** Der
Assay erfasst Gesamt-dsDNA und passt als Kandidat zu kleinen Roh-DNA-Mengen.
Der Hersteller nennt einen Kernbereich von 0,2–100 ng dsDNA **im Assay**.
Die lokale Nachweis- und Quantifizierungsgrenze hängt von Probe, Fragmenten,
Elutionsmatrix und Geräteeinsatz ab. Sie ist für diese Produkte noch zu
belegen. Die Konzentration beschreibt die DNA-Menge. Die Anreicherung am
RPL30-Locus wird durch die qPCR beurteilt.
[Thermo Fisher MAN0017455](https://documents.thermofisher.com/TFS-Assets/LSG/manuals/MAN0017455_Qubit_1X_dsDNA_HS_Assay_Kit_UG.pdf)

- H3K4me3, IgG und Input nach dem vorab gebundenen Entnahmebudget messen.
  Bei knappem Material zuerst die qPCR und die vereinbarte Produktreserve
  absichern. Fehlende Messungen ausdrücklich dokumentieren. Ein IgG-Befund
  unter der Quantifizierungsgrenze kann zur Kontrollrolle passen. Die PCR-NTC
  hat kein Produkt für eine fluorometrische Entnahme.
- Gerätemodell und Software, Originalexport, Assay-/Kit-Charge, beide
  Herstellerstandards und deren Kalibrierbezug, Proben- und Gefäßkennung,
  tatsächliche Entnahme und Vorverdünnung erfassen. Falls verfügbar, das
  Rohsignal mitführen. Zu jeder Konzentration die Einheit und den Bezug auf
  Assaylösung, vorverdünnte Probe oder ursprüngliches Eluat angeben.
- Eine Korrektur auf das ursprüngliche Eluat höchstens einmal aus belegten
  Volumina ableiten. Gesamt- oder Restmasse erfordern jeweils einen passenden
  bestätigten Produktvolumenstand. Unterhalb der lokalen LoQ bleibt die
  Konzentration leer. Eine Messung oberhalb des Bereichs behält ihren
  Gerätebefund. Eine etwaige Wiederholung mit weiterer Verdünnung erhält
  einen separaten Beleg mit der tatsächlichen Verdünnung und Entnahme.
  [Qubit-Volumenbezug im vorhandenen synthetischen Vertrag](../qubit-4-manual-workflow.md)

## Entscheidungen und Nachweise vor der Bindung

| Entscheidung | Vorschlag und benötigter Nachweis |
| --- | --- |
| qPCR-Umfang | RPL30 als einziger Positivlocus, drei technische Wells je Rolle. Eine vorab definierte Zwei-Well-Variante bei knappem Material, falls gewünscht. `% Input` nur aufnehmen, wenn der Referenzlauf diese quantitative Aussage liefern soll. |
| Geräte und Reagenzien | qPCR-Gerät und Softwareversion, CST #88989 oder bereits qualifizierte lokale Alternative, vorgesehener Qubit 4 und vorhandenes #Q33230-Kit. Von beiden Geräten je ein anonymisierbarer Originalexport. Beim qPCR-Beispiel möglichst Plattenplan, Cq-, Amplifikations- und Schmelzdaten mitliefern. |
| Materialzuteilung | Produktreserve für Übergabe beziehungsweise Folgearbeiten und maximales QC-Entnahmebudget je Rolle mit O02/O07 abstimmen. Vorab entscheiden, welche Fluorometriebefunde bei knappem Material entfallen dürfen. |
| Abnahmekriterien | Geeignete lokale Referenzdaten bereitstellen oder eine vorgelagerte Methodenprüfung zur Begründung der Kriterien einplanen. Vor dem Referenzlauf Auswertungsrevision, Nachweis- und Quantifizierungsgrenzen, Regeln für Replikate und alle vier qPCR-Rollen sowie die verantwortliche fachliche Freigabe dokumentieren. |
