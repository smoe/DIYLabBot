# Laufübergreifende Bestandsführung: Umsetzungsplan

**Status: geplant, nicht implementiert.** Ausgangspunkt ist der gemeinsame
synthetische Ablauf in Commit `70fc134`. Dieser führt eine durchgängige Bilanz
innerhalb eines Rootlaufs; seine Berichte melden weiterhin
`cross_run_volume_ledger: false`. Der nachfolgende Entwurf erweitert weder
Gerätekommunikation noch Hardware-, Mengenmessungs- oder Sicherheitsnachweise.

## Ziel und feste Bilanzregel

Ein dauerhafter Bestand verbindet dieselben Proben, Gefäße und Rackplätze über
mehrere Rootläufe. Anfangsmengen werden genau einmal eingeführt. Ein Folgelauf
übernimmt den bestätigten Bestandskopf, niemals erneut die Mengen seines Profils.

| Zustand des fiktiven Originalgefäßes | Bekannte Entnahmen | Restmenge |
|---|---:|---:|
| Erstmalige Einführung | keine | 40 µl |
| Ende des ersten CF01–NanoDrop–Qubit-Laufs | 1,5 + 2 µl | 36,5 µl |
| Ende eines entsprechenden zweiten Laufs | weitere 1,5 + 2 µl | 33 µl |
| Anfangsmenge unbekannt | dieselben tatsächlichen Entnahmen dokumentiert | weiterhin `null` |

CF01 verschiebt Gefäße und bestätigt Stationszustände, bucht jedoch keine
Originalentnahme. NanoDrop bucht bei der Messbestätigung, Qubit beim bestätigten
Ansatztransfer; Messung und Entsorgung des Qubit-Ansatzes buchen nicht nochmals.
Die Zahlen sind ausschließlich synthetische Testdaten, keine Arbeitsanweisung.

## Unveränderte Quellen und neue Runtime-Verträge

Manifest und Protokolle bleiben unveränderte, prüfsummengebundene Quellen für
Identitäten, Platzbindungen und Abläufe. Historische Rootzustände, Ereignisse,
Artefakte und deren Prüfsummen werden nicht nachträglich überschrieben.
Die Mengen eines neuen bestandsgeführten Laufs stammen aus einem ausdrücklich
referenzierten Stockzustand. Eine Kopie von `36.5` in ein weiteres Laufprofil
würde eine zweite Mengenquelle erzeugen und ist kein Fortsetzungsvertrag.

Vorgesehene neue Verträge, deren genaue Schemata erst zu implementieren sind:

- Ein neuer Rootzustand, beispielsweise `solidcraftbot.synthetic-lab-state/2`,
  bindet `store_id`, `stock_id`, Eingangs-Kopfversion/-hash und die aktive Lease.
- Stockereignisse und Bestandsansichten bekommen eigene versionierte Formate.
  Jeder Bestand besitzt eine unveränderliche ID; die Kopfversion steigt monoton.
- Eine ausdrücklich versionierte Store-Erweiterung ergänzt die nötigen Tabellen.
  Bestehende Root-/Ereigniszeilen werden dabei nicht umgeschrieben. Ein alter
  Root vom Format `/1` bleibt historisch lesbar und wird nicht still auf `/2`
  migriert. Laufzeitquellen und unterstützte Schreiberversionen werden geprüft.

## Führender Stock und seine Projektion

Die folgenden Namen bezeichnen geplante Tabellenrollen, noch keine vorhandenen APIs.

| Rolle | Notwendiger Inhalt |
|---|---|
| Stockereignisse | `stock_id`, Sequenz, Vorgängerhash, Ereignis-ID/-art, Transaktions-ID, Root-/Absichtsbezug und unveränderte Evidenz |
| Stockkopf | aktuelle Version, Ereignishash und daraus abgeleitete Bestandsansicht; per Compare-and-swap aktualisiert |
| Gefäßzuordnung | dauerhafte eindeutige Zuordnung einer `vessel_id` zum Bestand, einschließlich stillgelegter Gefäße |
| Persistente Lease | Bestand, haltender Root, Root-Sitzung und monoton steigende Fencing-Epoche |

Der Stock führt Proben-/Gefäßidentitäten, Inhalt und Inhaltsrevision, kanonischen
Ort `(rack_instance, place_id)`, Verantwortung, Mengenwissen, offene Entnahmen
und Massenbestätigungsbezüge. Historische geometrische Platz-IDs bleiben
abgeleitete Referenzen. Qubit-Ansatz- und Standardgefäße behalten eindeutige IDs,
Abstammung und bestätigte Disposition; sie werden nicht zu neuen Originalproben.
Reagenzvorräte bleiben zunächst außerhalb der Bilanz.

Die Restmenge ist eine geprüfte Projektion aus einmaligem Anfang und eindeutigen
Istbuchungen. Stockkopf und gegebenenfalls gecachte Restmengen sind abgeleitet,
keine zweite führende Bilanz. Ein vollständiger Audit prüft Ereigniskette,
Projektion, Kopf und Rootbezüge. Gleiche Buchungs-ID mit anderem Inhalt ist ein
Konflikt; Wiederholung eines bereits bestätigten Vorgangs darf keinen weiteren
Abzug erzeugen. Eine spätere Korrektur erfolgt durch ein neues verknüpftes
Ereignis mit Evidenz und Grund, nicht durch Editieren früherer Buchungen.

## Einführung und ausdrückliche Übernahme eines abgeschlossenen `/1`-Laufs

Die erstmalige Einführung bislang nicht registrierter Gefäße bestätigt genau
einmal deren Anfangsbestand. Bereits stockgeführte IDs dürfen diesen Weg nicht
erneut verwenden, auch nicht unter anderem Racknamen oder anderem Laufprofil.

Für vorhandene Daten ist ein eigener Übernahmebefehl vorgesehen:

1. Den abgeschlossenen `/1`-Root direkt aus demselben Journal vollständig prüfen:
   endgültiger Ereignishash, Quellenbindung, Originalartefakte, alle Stufen,
   eindeutige Buchungen, Rückgaben und Entsorgungsbestätigungen. Ein externes
   JSON-Ergebnis allein ist keine Übernahmequelle.
2. Nur `completed` mit vollständig aufgelösten Entnahmeausgängen übernehmen.
   Ursprünglich unbekannte Mengen sind zulässig; ein ungeklärter Verbrauch oder
   eine offene Übergabe nicht. Aktuelle Reservierungen müssen die Übernahme erlauben.
3. Akteur, Grund, Bestands-ID und erwarteten historischen Rootkopf ausdrücklich
   angeben. Für die Originale Zuordnung und Platzbindungen überprüfen.
4. In einer Transaktion die eindeutige Gefäßzuordnung, das Übernahmeereignis und
   den ersten Stockkopf anlegen. Eine bereits erfolgte Übernahme darf keine
   zweite Einführung desselben Bestands erzeugen.

Das Übernahmeereignis bindet den ursprünglichen Anfang `40`, die geprüften alten
Entnahmen `1,5` und `2`, deren Root-/Buchungskennungen und die Projektion `36,5`.
Diese historische Ableitung wird einmal übernommen: **kein zweites Startguthaben
von 40 und kein zusätzlicher Abzug derselben alten Entnahmen**. Der alte Root
bleibt unverändert. Der Übernahmezeitpunkt ist ein heutiges Auditereignis; er
behauptet keine damalige Live-Stockführung. Ein eindeutiger Übernahmeschlüssel
aus Store, Quellroot und terminalem Ereignishash verhindert erneuten Import.

## Eine Transaktion für Root, Stock, Kopf und Ressourcen

Jede stockrelevante Änderung muss unmittelbar mit dem zugehörigen Rootereignis
gespeichert werden. Das spätere Addieren fertiger Laufberichte ist ausdrücklich
kein Schreibpfad für laufübergreifenden Verbrauch.

Unter **einem SQLite-`BEGIN IMMEDIATE` auf derselben Verbindung**:

1. Erwartete Rootrevision und Root-Sitzung prüfen; Stockkopfversion/-hash,
   persistente Lease und Fencing-Epoche aus der Datenbank vergleichen.
2. Vorgang gegen den aktuellen Stock prüfen, einschließlich Gefäßzuordnung,
   eindeutiger Absicht, Ort, Mengenzustand und verfügbarer bekannter Menge.
3. Rootereignis/-projektion, Stockereignis/-projektion, neue Kopfversion und
   Reservierungsänderungen gemeinsam schreiben; Originalartefakte gehören
   gegebenenfalls in dieselbe Transaktion.
4. Genau einmal committen. Bei jedem Fehler sämtliche Schreibungen zurückrollen
   und betroffene Caches verwerfen; keinen Erfolg oder neuen Kopf veröffentlichen.

Gemeinsame Transaktions-/Vorgangskennungen verbinden die beiden Ereignisketten.
Ihre Hashbezüge müssen ohne zyklische Abhängigkeit definiert werden, etwa über
vorab vergebene Ereignis-IDs und eindeutig prüfbare Root-/Stockrevisionen.

Der neue Schreibpfad benötigt eine gemeinsam genutzte Transaktionsprimitive.
Das heutige `Journal.append`, das selbst eine Transaktion beginnt und committet,
darf nicht lediglich zwischen zwei unabhängige Stock-Commits gestellt werden.
Head-Caches ersetzen den Vergleich innerhalb der Schreibtransaktion nicht.

Das gilt für Entnahmeabsicht und deren spätere Auflösung, Änderungen von
Inhaltsrevision/Massengültigkeit, stockrelevante Orts-/Verantwortungswechsel
sowie Übernahme, Leasewechsel und endgültige Freigabe. Ein Messdateiimport allein
erzeugt keine weitere Entnahme, benötigt aber weiterhin eine gültige Schreibberechtigung.

## Fortsetzung, persistente Lease und veraltete Worker

Der erste Ausbau reserviert den ganzen Zwölferbestand exklusiv für einen Root.
Eine Aufteilung in parallel bearbeitbare Teilbestände gehört nicht zu diesem Schritt.

Der Fortsetzungsbefehl nennt den erwarteten Stockkopf. Er legt den neuen Root,
seine gebundene Eingangsansicht, die Lease und die benötigten Reservierungen in
derselben Transaktion an. Zwei gleichzeitige Fortsetzungen desselben Kopfs:
genau eine gewinnt; die andere hinterlässt weder Rootereignis noch Lease,
Reservierung, Buchung oder Kopfänderung. Anfangsmenge und Inhaltsrevision werden
beim erfolgreichen Start nicht zurückgesetzt.

Eine Lease enthält mindestens `root_id`, `session_id` und `lease_epoch`.
Die Epoche steigt bei Neuzuweisung, Sitzungsübernahme und endgültiger Freigabe;
alte Token werden niemals erneut gültig. Jeder mutierende Schreibpfad prüft
Root-Sitzung **und** Epoche innerhalb seiner Transaktion. Ein früherer Worker
kann dadurch weder nach Wiederaufnahme desselben Roots noch nach Übergang an
einen neuen Root Buchungen oder verspätete Antworten verbuchen.

Es gibt keine automatische Freigabe nach TTL, Heartbeatausfall oder Prozessende.
Eine verwaiste Lease bleibt bestehen, bis ein ausdrücklich dokumentierter
Abgleich im zugehörigen Root den Bestand klärt. Eine Sitzungsübernahme erhöht
die Epoche atomar und erhält Reservierungen und offene Absichten. Eine
unbekannte Durchführung wird nicht durch Neuanlegen eines Roots umgangen.

Vor Nebenwirkungen und beim Verbuchen ihrer Antworten ist die aktuelle
Ausführungsberechtigung zu beachten. SQLite-Fencing allein kann einen bereits
abgesandten physischen Befehl nicht zurücknehmen. Der erste synthetische Ausbau
ist daher keine Hardwareverriegelung oder Sicherheitsfunktion; spätere schreibende
Geräteadapter brauchen einen dazu passenden Ausführungs-/Tokenvertrag.

## Unbekannte Mengen und frische CF01-Massen

Zwei Fälle sind ausdrücklich verschieden:

- **Anfang unbekannt:** Anfang und Rest bleiben `null`; bestätigte Istentnahmen
  werden trotzdem vollständig geführt. Ohne offene Durchführung kann dieser
  Bestand nach der bisherigen synthetischen Mengenpolitik weitergeführt werden.
- **Entnahmeausgang ungeklärt:** Istmenge und gegebenenfalls Rest sind ungewiss,
  die ursprüngliche Absicht bleibt erhalten. Eine Sollmenge ist keine Obergrenze.
  Folgelauf und Leasefreigabe bleiben gesperrt, bis der Ausgang mit Evidenz als
  `performed` oder `not_performed` aufgelöst ist. Ein einfacher Override genügt nicht.

Das Mengenwissen braucht deshalb einen ausdrücklichen Grund/Zustand neben
einem eventuell `null`en Zahlenwert. Historische unbekannte Anfangsmengen dürfen
nicht als ungeklärte Entnahme behandelt werden und umgekehrt.

Inhaltsrevisionen steigen über die Laufgrenzen hinweg. Offene Entnahmeabsichten
entwerten Massenbestätigungen; bestätigter Verbrauch erhöht die Inhaltsrevision
genau einmal. `not_performed` erhöht sie nicht, stellt aber eine alte
Massenbestätigung nicht still wieder her. Ein Folgelauf übernimmt diese
Zustände und verlangt vor CF01 neue synthetische Gesamtgefäßmassen, gebunden an
Gefäß, aktuelle Inhaltsrevision und neuen Root. Weder die Masse `2,0 g` aus dem
alten Demolauf noch eine aus Volumen/Dichte berechnete Masse gilt als neue Bestätigung.

## Gegen Profilneustarts und Storewechsel abgrenzen

Die dauerhafte Gefäßregistrierung gilt auch nach Leasefreigabe. Sämtliche
unterstützten schreibenden Einstiege müssen sie prüfen: integrierter Root,
Standalone-NanoDrop/Qubit, Fixture-Runner und gemeinsame Journal-/Ressourcenpfade.
Ein neuer `/1`-Lauf mit registrierter `vessel_id` muss an der ersten zulässigen
Bestandsübernahme scheitern; ein anderer Rackname oder `initial_volume_ul: 40`
ist kein Ausweg. Die Sperre darf nicht nur in einer einzelnen CLI stehen.
Eine Gefäßumbenennung benötigt einen eigenen nachvollziehbaren Identitätsvertrag.

Unabhängige historische Fixtures dürfen weiterhin mit ihren deklarierten Mengen
laufen, verwenden dafür aber ausdrücklich private Testdatenbanken. Sie erzeugen
keinen Stock und dürfen nicht als Fortsetzung eines registrierten Gefäßes gelten.

„Global“ bedeutet hier **alle Rootläufe in einem gemeinsamen SQLite-Store**.
Der bestehende historische Standardpfad kann erhalten bleiben. Eine andere
`--store`-Datei koordiniert weder Leases noch Mengen mit der ersten. `store_id`
und Stockbindung müssen in Berichten/Übernahmereferenzen stehen; Dateien,
Backups oder Berichte aus anderen Stores werden nicht automatisch zusammengeführt.
Die produktiv gemeinte Bestandsführung muss denselben autoritativen Store nutzen;
parallele beschreibbare Datenbankkopien sind damit nicht abgesichert.

## Vorgesehene CLI und Umsetzungsreihenfolge

**Die folgenden Unterbefehle sind Vorschläge und noch nicht verfügbar.**
Erweiterung des bestehenden `scripts/run_lab_workflow.py` im selben Store:

```text
--store STORE stock-init --stock-id STOCK --manifest MANIFEST --actor-id ACTOR --reason TEXT
--store STORE stock-adopt --stock-id STOCK --from-run ROOT_V1 --expected-root-head HASH --actor-id ACTOR --reason TEXT
--store STORE stock-status STOCK
--store STORE continue --stock-id STOCK --expected-stock-version VERSION --expected-stock-head HASH --run-id ROOT_V2 --profile PROFILE
--store STORE session ROOT_V2 --resume
--store STORE stock-report STOCK
```

`stock-init` akzeptiert nur noch nicht registrierte Gefäße; `stock-adopt` prüft
den vorhandenen abgeschlossenen Root desselben Stores. `continue` liest Mengen
ausschließlich aus dem erwarteten Kopf. `session --resume` braucht die neue
atomare Sitzungs-/Fencing-Übernahme und weiterhin den fachlichen Inventarabgleich.
Private Legacy-Demos nennen eine getrennte Fixture-Datei über `--store`.

1. Versionierte Stock-/Root-/Storeverträge und Mengenwissenszustände festlegen;
   danach die atomare Transaktionsprimitive, CAS und Fencing implementieren.
2. Registrierung, erstmalige Einführung und überprüfte `/1`-Übernahme ergänzen.
   Historische Leser und Fixtures unverändert absichern.
3. Den neuen Root aus dem Stock starten und seine Buchungen, Revisionen,
   Massengültigkeit und Reservierungen unmittelbar gemeinsam fortschreiben.
4. Sämtliche schreibenden Einstiege gegen Profilneustarts absichern; Wiederaufnahme,
   Klärung, endgültigen Abschluss und vollständige Audits ergänzen.
5. CLI, Regressionen, Lastmessung und Dokumentation abschließen. Erst nach
   bestandenem Nachweis darf ein neuer Bericht laufübergreifende Bilanzierung
   als ausgeführt bezeichnen. Netzwerkadapter sind dafür keine Voraussetzung.

## Abnahme und vorhandene Belege

Notwendige neue Tests:

- Zwei komplette Rootläufe: `40 → 36,5 → 33`; `null → null → null`, bekannte
  Entnahmen dennoch erfasst. Inhaltsrevision `0 → 2 → 4`; neue CF01-Massen je Lauf.
- Explizite `/1`-Übernahme liefert `36,5`, wiederholte Übernahme keinen zweiten
  Anfang oder Debit. Abgebrochene/ungeklärte Quellen, falscher Rootkopf,
  beschädigte Artefakte und fremde Storebezüge werden abgelehnt.
- Zwei echte SQLite-Verbindungen starten denselben Kopf gleichzeitig: genau
  eine Fortsetzung; vollständiger Rollback aller fünf Komponenten beim Verlierer.
- Fehler nach jedem Root-/Stock-/Head-/Ressourcen-/Artefaktschreibschritt sowie
  Prozessabbruch an Transaktionsgrenzen: entweder alles oder nichts; nach Neustart
  konsistente Ketten, Kopfprojektion und persistente Reservierung.
- Alte Root-Sitzung oder Epoche nach Übernahme/Freigabe: kein Debit, keine
  Ressourcenfreigabe und keine verspätete Ergebnisannahme. Kein TTL-Freigabepfad.
- Wiederholte Absichten/Bestätigungen/Importe, gleicher Schlüssel mit anderem
  Inhalt, veralteter Kopf und unzureichender Restbestand erzeugen keinen Mehrverbrauch.
- Ungeklärter Entnahmeausgang sperrt Fortsetzung; spätere explizite Auflösung
  funktioniert ohne geschätzte Obergrenze. Unbekannter Anfang allein ist kein solcher Halt.
- Profilneustarts und andere Racknamen mit registrierten Gefäß-IDs scheitern
  auch nach Leasefreigabe. Historische `/1`-Berichte bleiben lesbar; private
  Standalone-Fixtures behalten ihr Verhalten ohne Zugriff auf den Stock.
- Vollständige Root-/Stock-/Artefaktaudits und ein gemessener Mehrlauflasttest;
  keine Leistungsaussage allein aus einem warmen Tailcache.

Vorhandene Grundlage, noch kein Nachweis der neuen Stockfunktion:

| Quelle/Test | Bereits vorhandene Eigenschaft |
|---|---|
| [lab_workflow_ledger.py](../scripts/lab_workflow_ledger.py), `remaining`/`begin_withdrawal`/`confirm_withdrawal` | Einmaliger Anfang und eindeutige Entnahmen innerhalb eines Roots; Sollmenge ist keine Obergrenze |
| [lab_workflow.py](../scripts/lab_workflow.py), `open`/`_transition`/`_audit` | Sitzungsprüfung, Quellenbindung und Abschlussaudit eines Roots |
| [manual_tasks.py](../scripts/manual_tasks.py), `append`/`history` | Atomare Rootereignisse, Artefakte, Ressourcen und CAS; noch kein gemeinsamer Root-/Stock-Commit |
| [test_lab_workflow.py](../tests/test_lab_workflow.py), `test_full_twelve_vessel_workflow_has_one_balance_and_independent_stage_results` | 36,5 µl, unbekannter Anfang, Inhaltsrevision 2 und unverbrauchte Qubit-Messung im Einzellauf |
| [test_lab_workflow.py](../tests/test_lab_workflow.py), Ressourcen-, Wiederaufnahme-, Mengen- und Massenregressionen | Bestehende Root-Invarianten, die beim Ausbau erhalten bleiben müssen |
| [test_lab_workflow_ledger.py](../tests/test_lab_workflow_ledger.py) | Keine Doppelbuchung und keine Nullbuchung bei unbekanntem Ausgang |
| [test_manual_journal.py](../tests/test_manual_journal.py) | CAS gegen Fremdschreiber, Ressourcenkonflikt und vollständiger Rollback bei partiellen Schreibfehlern |

Die aktuelle Implementierung und ihre Grenzen stehen in
[Gemeinsamer synthetischer Laborablauf](synthetic-lab-workflow.md). Dieser Plan
führt noch keine Stocktabellen, Befehle, Formatmigration oder Netzwerkfunktion ein.
