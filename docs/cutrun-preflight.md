# Wirkungsfreier CUT&RUN-Preflight

**Stand 12. November 2026: E1 für das synthetische SK-Mel-29/H3K4me3-Profil
implementiert.** Der Preflight prüft und beschreibt eine Planung. Er führt keine
Laborhandlung aus, öffnet kein Journal und reserviert oder bucht nichts.
Die historische SOP-Bindung aus [E0](cutrun-reference-profile.md) bleibt offen.
Die [Roadmap](../ROADMAP.md) und der
[Architekturvertrag](../ARCHITECTURE.md#cutrun) unterscheiden diese Vorbereitung
von Lebenszyklus, Ausführung, Wiederanlauf und realer Qualifikation.

## Einstieg und Quellen

```sh
python3 scripts/prepare_cutrun_automation.py
python3 scripts/prepare_cutrun_automation.py --require-complete
python3 scripts/prepare_cutrun_automation.py --out exports/cutrun-preflight/plan.json
```

Der normale Aufruf schreibt nur JSON nach stdout. `--out` erzeugt auf ausdrückliche
Anforderung eine **neue** JSON-Berichtdatei im ignorierten `exports/`-Bereich;
bestehende Dateien und Pfade außerhalb dieses Bereichs werden abgewiesen,
auch bei aufgelösten Symlinks. Für einen weiteren Bericht einen neuen Dateinamen
verwenden. Es gibt keinen Ausführungs-, Store- oder Geräteschalter.

| Quelle | Inhalt |
|---|---|
| `model/cutrun-automation.catalog.json` | Literatur-/Eigentümerbezüge und vorgeschlagene Material-/Kitrollen |
| `model/cutrun-automation.protocol.json` | Abstrakte Operationen, Kontroll-/Inputketten, Fraktionen, Einheiten sowie Stopp-, Inputgrößen- und QC-Anforderungen |
| `model/cutrun-automation.preparation.json` | Synthetische Identitäten, konkrete Modellannahmen, vorgeschlagene Provider und deren unqualifizierte Grenzen |
| `model/cutrun-automation.schema.json` | Formales Schema mit dem bestehenden gemeinsamen Quellenreferenzvertrag |
| `scripts/cutrun_preparation.py` | Unverändernde Momentaufnahme, semantische Prüfung und Ableitung |

Das Profil pinnt Katalog und Protokoll. Der Bericht bindet zusätzlich Schema,
Compiler und verwendete technische Hilfen über SHA-256; die Quellen werden
am Ende nochmals geprüft. Bei einem in-memory geänderten Profil bezeichnet
`effective_preparation_sha256` den tatsächlich ausgewerteten Inhalt.
Diese lokalen Quellenpins sind keine Prüfsumme der unbekannten historischen SOP.

## Was „vollständig“ bedeutet

Der mitgelieferte Fall hat `planning_complete: true`, aber **immer
`execution_ready: false`**. Vollständigkeit bedeutet ausschließlich, dass die
benötigten E1-Planfelder unter den deklarierten Annahmen ausgefüllt und konsistent
sind. Die Planung ist kein vollständiges Laborrezept. Mehrere reale Zugaben,
Mischvorgänge, Gefäßwechsel und Beobachtungen sind erst später in die konkrete
SOP und einzeln bestätigbare Schritte aufzulösen.

Jeder Parameter enthält `value`, `unit`, `basis`, `source_refs` und `note`.
`owner_confirmed` bezeichnet hier bestätigte Rahmenangaben, keine Durchführung;
`publication_reported` ist eine Literaturangabe. Nicht bestätigte Prozesswerte,
Zelllinienauswahl und Providergrenzen stehen als `synthetic_assumption` mit
Begründung im Profil und mit ihrem Feldpfad in `assumptions` im Bericht.
Das macht sie weder zu Messdaten noch zu qualifizierten Fähigkeiten.

Die Bindung an CST-Kit-/Artikelrollen ist ein synthetischer Vorschlag auf Basis
des dokumentierten Vergleichsstands. Sie belegt keinen Bestand und rekonstruiert
nicht den ursprünglichen Studienablauf. Zellzahl wird nicht aus Volumen abgeleitet.
Eine erwartete DNA-Ausbeute oder ein biologischer Erfolg wird nicht berechnet.

Wird ein erforderlicher Wert offen gelassen, bleibt er `null` mit `basis: unknown`.
Auch ganz fehlende Prozessparameter werden im abgeleiteten Schritt als unbekannt
mit Einheit geführt, statt einen Default anzunehmen. Die betroffenen Pfade
stehen in `open_requirements`; `planning_complete` wird falsch. Bei
`--require-complete` folgt Exitcode **2**, bei widersprüchlichen/ungültigen Quellen
Exitcode **1** mit JSON-Fehler. Ohne diesen Schalter sind gültige Teilplanungen
mit Exitcode **0** zulässig.

Unbekannte historische SOP-Revision, Original-SOP-Prüfsumme und biologische
Abnahmeschwelle bleiben ausdrücklich ungelöst. Sie sind keine für die
synthetische Feldvollständigkeit erfundenen Werte.
Der [E2-Materialvertrag](material-lifecycle.md) ist für explizite synthetische
Materialvorgänge implementiert; seine Bindung an eine biochemische Ausführung,
reale SOP-Nachweise, Providerqualifikation, QC-Anbindung und CUT&RUN-Laufzeit bleiben als
`execution_blockers` erhalten. Ein Quellenwechsel kann diese Sperren nicht
durch ein zusätzliches `execution_ready`-Feld umgehen.

## Geprüfte Zusammenhänge

- Genau ein H3K4me3-Referenzzweig, ein IgG-Negativkontrollzweig und ein separater
  Input mit unterschiedlichen Material-/Gefäßidentitäten. Der Input durchläuft
  keine Antikörperbindung oder Aktivierung. Die PCR-Leerkontrolle bleibt eine
  eigene QC-Rolle, keine zusätzliche CUT&RUN-Reaktion.
- Pflichtphasen und deren Reihenfolge, einschließlich Input-Sonikation und
  Input-Größenprüfung sowie Säulenwäsche/Trocknung. Eine neu gepinnte Quelle
  kann die Parameter- oder Gefäßanforderungen dieser Vertragsversion nicht entfernen.
- Erhaltung der Bead-/Zellfraktion vor Freisetzung, des Produktüberstands danach,
  der Säulenfraktion während der Reinigung und des Eluats/Produkts bei Übergabe.
  Es werden keine Entsorgungen oder abgeschlossenen Transfers behauptet.
- Typisierte Zellzahl, Volumina, Zeiten, Temperaturen, RCF, Wiederholungen und
  Größenbereiche. Boolesche Zahlen, NaN/Inf, falsche Einheiten und unbekannte
  Felder werden abgewiesen. Für den ausgewählten Säulen-Input wird das geplante
  Größenintervall gegen die im Protokoll deklarierte Modellgrenze geprüft.
- Fähigkeitszuordnung, benötigte Gefäßklassen und vorgeschlagene Volumen-,
  Temperatur- und RCF-Grenzen. Ein fehlender Vorschlag bleibt offen, ein
  widersprüchlicher Vorschlag wird abgewiesen. Eine allgemeine Geräteverfügbarkeit
  oder der Name CF01 bestätigt keine dieser Fähigkeiten.
- Stoppmaterial, Zugang, Durchmischung, manueller Ersatzweg und Abdeckung beider
  aktiven Zweige. Dosierung und Zeitbedarf müssen mit den Zweigparametern
  zusammenpassen; der gesamte deklarierte Servicebedarf muss ins Zeitbudget
  passen. Dies ist eine Planprüfung, kein Ablaufplaner, Watchdog oder chemischer
  Stoppnachweis. Ein Software-Halt bleibt davon getrennt.
- Fluorometrie und qPCR mit passenden Kontrollbezügen. QC-Entnahmen werden
  ausschließlich als Vorschläge gegen die **DNA-Produkte** ausgegeben und gegen
  das vorgeschlagene Elutionsvolumen geprüft. Es findet keine Verbrauchsbuchung
  statt; die Eingänge werden nicht erneut belastet. Library-QC oder Konzentration
  allein ersetzen keine profilgerechte biologische Bewertung.

## Prüfung und Grenzen

```sh
python3 -B -m unittest discover -s tests -p 'test_cutrun_*.py' -v
```

Die Schematests benötigen die optionale Entwicklungsabhängigkeit `jsonschema`;
übersprungene Schematests zählen nicht als Nachweis. Die semantischen Tests
benötigen diese Abhängigkeit nicht. Die Tests verbieten Journal-, Datenbank-,
Netzwerk- und Subprozesswirkungen bei der Kompilierung und prüfen unveränderte
Eingaben/Dateien sowie voneinander unabhängige Rückgabewerte.

Vorhandene Quellenprüfung, Hashfunktionen und Validierungshilfen werden
wiederverwendet. Der Extraktionscompiler bleibt unverändert. Journal, Ledger
und gemeinsame Ablaufhülle sind ausschließlich referenzierte Integrationsziele;
E1 erweitert diese Verträge nicht. CAD-Geometrie, Roboterbewegung, Geräteadapter,
Hardware, biologische Abnahme und die E3-Reaktionszustandsmaschine sind nicht
Bestandteil dieses Preflights.
