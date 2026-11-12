# Gemeinsamer synthetischer Materiallebenszyklus

**Stand 12. November 2026: E2 als gemeinsamer Materialvertrag für Extraktion
und CUT&RUN implementiert.** Die bestehende Ablaufhülle und dasselbe Journal
werden wiederverwendet. Die neuen Läufe führen ausdrücklich synthetische
Materialbeobachtungen aus; weder Extraktionschemie noch CUT&RUN-Reaktionen
werden damit ausgeführt. Die bisherigen NanoDrop-/Qubit- und integrierten
CF01-Läufe behalten ihre Formate und Abschlussregeln.

## Einstieg und Grenze zur Vorbereitung

```sh
python3 scripts/run_material_lifecycle.py --store exports/material-e2-demo/workflows.sqlite3 demo --domain cutrun --run-id SYN.E2.CUTRUN
python3 scripts/run_material_lifecycle.py --store exports/material-e2-demo/workflows.sqlite3 demo --domain extraction --run-id SYN.E2.EXTRACTION
python3 scripts/run_material_lifecycle.py --store exports/material-e2-demo/workflows.sqlite3 status SYN.E2.CUTRUN
python3 scripts/run_material_lifecycle.py --store exports/material-e2-demo/workflows.sqlite3 report SYN.E2.CUTRUN --out exports/material-e2-demo/cutrun-report.json
```

Die Beispiele verwenden einen privaten Demo-Store. Ohne `--store` wird derselbe
Standard-Store wie bei den bisherigen manuellen Workflows gewählt, einschließlich
der vorhandenen Legacy-Pfadauflösung. Eine andere Datenbank koordiniert keine
Aliquotzuordnungen mit dieser Datei. Berichtziele sind neue JSON-Dateien unter
`exports/`; bestehende Dateien werden nicht überschrieben.

`demo` erfindet ausschließlich dort als Testdaten Anfangsmengen, Reagenzaliquots,
Durchführungsbestätigungen und Produktmengen. Die fiktiven Zahlen sind keine
Rezeptparameter oder Ertragsprognose. Jede Demo ist ein unabhängiges synthetisches
Fixture; sie ist keine Bestandsfortsetzung. Feste Lauf- oder Aliquotkennungen
lassen sich nicht erneut frisch einführen. Das Umbenennen einer realen Probe
oder eines realen Gefäßes ist kein zulässiger Ersatz für eine Bestandsübernahme.

Die E1-Quellen bleiben führend für die vorbereiteten Materialrollen:
[Extraktion](extraction-automation.md) und [CUT&RUN](cutrun-preflight.md).
`material_workflow_sources.py` kompiliert diese Quellen selbst, friert den Plan
ein und prüft Eingangs-/Produktbindungen. Es akzeptiert keinen selbst deklarierten
fertigen Plan als Vertrauensnachweis. Reagenzmengen werden nicht aus abstrakten
Phasenvolumina abgeleitet. Anfangsmaterialien, ausgegebene Reagenzaliquots und
physische Gefäße müssen ausdrücklich als synthetische Eingaben bereitstehen.
Auch ein unvollständiger E1-Rezeptentwurf kann Materialprimitive testen;
sein `execution_ready: false` und seine offenen Rezeptbindungen bleiben erhalten.

## Versionierter Vertrag und eine führende Bilanz

| Vertrag/Quelle | Aufgabe |
|---|---|
| `solidcraftbot.material-workflow-definition/1` | Unveränderlicher Vorbereitungsplan, Anfangsdeklarationen, Quellenpins und Reagenzzuteilungen |
| `solidcraftbot.material-workflow-state/1` | Ein Root mit `inventory.materials`, `inventory.vessels`, `bookings` und höchstens einer offenen Materialoperation |
| `solidcraftbot.material-workflow-report/1` | Abgeleitete Restmengen, Abstammung, Messgültigkeit und vollständige Ereignisspur |
| `scripts/material_ledger.py` | Gemeinsame typisierte Buchungs-/Projektionsregeln |
| `scripts/material_workflow.py` | Opt-in-Variante der vorhandenen `ManualWorkflow`-Hülle |
| `scripts/material_workflow_sources.py` | Bindung beider vorhandenen Vorbereitungsquellen an diesen Vertrag |

Es gibt keine daneben beschreibbaren `samples`-/`derived_vessels`-Kopien und
keine zweite Mengen-Datenbank. Anfangsdeklarationen und bestätigte Ereignisse
sind die führenden Belege; Inventar und Restmengen sind geprüfte Projektionen.
Alte Ereignisse werden weder migriert noch neu gehasht. Historische terminale
Läufe bleiben lesbar. Für aktive alte Läufe gelten weiterhin deren bestehende
Quellenpins und ausdrücklichen Wiederaufnahmeregeln.

Material und physisches Gefäß sind unterschiedliche Identitäten. Eine bestätigte
Umwandlung verbraucht Eltern und führt ein oder mehrere Kinder mit Elternbezügen
ein. Bleibt ein Produkt im bisherigen Gefäß, entsteht kein zusätzliches Gefäß.
Bereits vorhandene Gefäße müssen zuvor als physische Prozessgegenstände deklariert
sein. Ein Gefäß kann nur einen aktuellen Materialinhalt tragen; verbrauchte und
entsorgte Materialien bleiben in der Historie, verlieren aber ihren aktuellen
Gefäßbezug. Ein bekanntes leeres Gefäß darf im Inventar bleiben.

## Mengen und synthetische Beobachtungen

Eine buchbare Menge ist `{value, unit}` mit `uL`, `mg`, `ng` oder ganzzahliger
Zellzahl `cells`. Die Einheiten müssen bei der Entnahme übereinstimmen. Es gibt
keine stillen Umrechnungen und keine Ableitung von Zellzahl aus Volumen oder von
Produktmenge aus Eingangsmenge. Produktmengen können unbekannt bleiben.
Der ausgewiesene Buchungssaldo ist nicht automatisch verfügbarer Bestand:
verbrauchte, entsorgte und quarantänisierte Materialien sind für weitere
Entnahmen gesperrt, auch wenn ihr früherer Mengensaldo bekannt ist.

Konzentration (`ng/uL`) und Gesamtgefäßmasse (`mg`/`g`) sind gesonderte
Messbeobachtungen mit Inhaltsrevision, keine Verbrauchswährung. Entnahmeabsichten
entwerten Massenbestätigungen bereits vor Durchführung. Eine spätere
Nichtdurchführung oder Wiederholung einer alten Messkennung macht den alten
Beleg nicht erneut gültig. Diese Metadaten binden noch keinen CF01-Adapter.

Drei Fälle bleiben getrennt:

- **Anfang unbekannt:** Wert und Rest bleiben `null`; bekannte Istentnahmen
  werden trotzdem dokumentiert.
- **Wirkung unbekannt:** Die Absicht bleibt offen, der Lauf benötigt Abgleich
  und behält seine Ressourcen. Es wird keine Durchführung angenommen oder wiederholt.
- **Durchführung bestätigt, Istmenge unbekannt:** Der Verbrauch wird nicht
  zu Null. Ein nicht vollständig verbrauchtes Ausgangsmaterial wird quarantänisiert;
  eine weitere Entnahme bleibt bis zur Mengenklärung gesperrt. Die Menge kann
  später mit eigener Evidenz genau einmal geklärt werden. Vollständig verbrauchtes
  Material kann ausdrücklich als verbraucht geführt werden, ohne seine unbekannte
  Ausgangsmenge zu erfinden.

## Absicht, Bestätigung und Abschluss

Die Python-API `MaterialWorkflow.create(...)` verlangt `domain`, vorhandene
Vorbereitungsquelle und explizite `materials`/`vessels`. Über `act(...)` werden
Inventarannahme, Arbeitsplatzfreigabe und verantwortliche Person bestätigt.
Die Befehle `begin_effect` und `confirm_effect` trennen Absicht und Beobachtung.
Ein Vorgang kann eine Entnahme oder eine Materialumwandlung sein. Reagenzien
sind dabei eigene Eingänge mit eigenem Istverbrauch; ihre Mengen gehören zum
selben Root wie Proben und Produkte.

Identische Absichten/Bestätigungen bewirken keine weitere Buchung oder ein
zusätzliches Ereignis. Gleiche Kennung mit verändertem Inhalt wird abgewiesen.
Bestätigter Mehrverbrauch über eine bekannte Restmenge führt zum protokollierten
Beobachtungs-Halt; die ursprüngliche Absicht bleibt erhalten. QC entnimmt aus
dem Produkt und belastet das verbrauchte Original nicht erneut. Ein solcher
Aliquottransfer erzeugt für sich noch kein zusätzliches Gefäß.

Nach Neustart oder Kontaktverlust verlangt die gemeinsame Hülle eine neue
Sitzung und vollständigen Inventarabgleich. Für offene Effekte muss
`reconcile` ausdrücklich `performed`, `not_performed` oder `unknown` samt
entsprechenden Belegen angeben. Ressourcen werden nicht nach Zeitablauf freigegeben.

Zum Abschluss braucht jedes Material eine bestätigte Disposition: `retained`,
`consumed`, `quarantined` oder `discarded`. Produkte und Nebenfraktionen dürfen
behalten werden; Originalrückgabe und pauschale Produktentsorgung sind in diesem
Vertrag keine Abschlussvoraussetzung. Eine frische vollständige Inventarbestätigung,
Journal-/Artefaktprüfung und Zuteilungsprüfung gehen der Ressourcenfreigabe voraus.
Dasselbe gilt für Abbruch. `passed` bezeichnet hier nur den abgeschlossenen
synthetischen Materialvertrag, keine biologische oder analytische Abnahme.

## Dauerhaft laufexklusive Reagenzaliquots

`Journal.create(..., material_allocations=[...])` aktiviert ausdrücklich die
Store-Komponente **`solidcraftbot.material-allocations/1`**. Die Tabellen
`journal_components` und `material_allocations` werden erst in derselben
Transaktion wie das erste Material-Ereignis angelegt; das Öffnen eines alten
Stores migriert seine Ereignisse nicht.

Der permanente Index bindet Material-ID und Gefäß-ID eines ausgegebenen Aliquots,
Eigentümerlauf, Deklarationshash und Einführungsereignis. Er enthält keine
Mengenbilanz. `audit_material_allocations()` gleicht ihn gegen die gebundenen
Einführungen ab. Beide Aliasidentitäten bleiben nach Verbrauch, Abschluss und
Abbruch zugeordnet; eine Freigabe temporärer Ressourcen löscht sie nicht.
Ein anderer Materialname mit demselben Gefäß oder derselbe Aliquotname mit einem
anderen Gefäß umgeht die Zuteilung nicht. Auch der normale Journal-Ressourcenerwerb
bisheriger Runner respektiert permanente Fremdzuordnungen.

Ereignis, Buchung/Projektion, neue Zuteilungen, Ressourcen und Originalartefakte
werden unter demselben SQLite-Schreiblock mit Revisionsprüfung gespeichert.
Bei Fehlern wird die gesamte Transaktion zurückgerollt. Zwei Verbindungen können
daher nicht dasselbe Aliquot erfolgreich unterschiedlichen Läufen zuteilen.
Eine globale Mengenfortschreibung, Nachfüllung oder Übergabe eines Restaliquots
an einen neuen Lauf ist damit noch nicht verfügbar; sie bleibt Teil des
[Stock-Ausbaus](stock-continuation.md) beziehungsweise E7.

## Prüfung und Grenzen

Die Tests `test_material_allocations.py`, `test_material_lifecycle.py` und
`test_material_lifecycle_cli.py` prüfen Konkurrenz und Persistenz, typisierte
Mengen, 1:n-Abstammung, gleiche Gefäße, Produkt-/Reagenzverbrauch, Idempotenz,
Wiederanlauf, Abbruch, Artefakte und vollständigen Rollback. Die bisherigen
Journal-, NanoDrop-, Qubit- und integrierten Workflowtests sichern die alten
Verträge ab. E1 bleibt wirkungsfrei.

E2 startet keine Geräte, Pipetten oder Roboter, führt keine Extraktions-SOP und
keine Aktivierungs-/Stoppchemie aus und importiert keine echten QC-Dateien.
Die [E3-Reaktionszustandsmaschine](cutrun-synthetic-workflow.md) ergänzt dafür
ein eigenes `/2`-Formatpaar mit synthetischen Zeit-/Temperaturregeln und
gefäßbezogenen Schutzstopps im selben Ledger. Der generische E2-Runner bleibt
bei `/1` und kann diese Prozessregeln nicht umgehen.
Quellenfreigabe, reale Ausführung und biologische Bewertung bleiben
die weiteren Abnahmen der [Roadmap](../ROADMAP.md).
