# Protokolle und biologische Workflows

Dieser Bereich führt die Dokumentation von Protokollen und biologischen
Laborabläufen. Die [biologische Roadmap](ROADMAP.md) beschreibt ihre Etappen,
Abhängigkeiten und Abnahmen. Der [Projekt- und mechanische Entwicklungsplan](../../ROADMAP.md)
bleibt davon getrennt.

In dieser Etappe ist die biologische Roadmap hierher überführt. Weitere
bestehende Ablaufdokumente werden mit ihrer jeweiligen fachlichen Konsolidierung
migriert; die folgenden Verweise führen bis dahin zu ihren führenden Fassungen.
Prüfsummengebundene Archive behalten Bytes und Pfade.

## Führende Ablaufbeschreibungen

| Thema | Einstieg |
|---|---|
| Gemeinsamer Laborworkflow | [CF01, NanoDrop und Qubit](../synthetic-lab-workflow.md) |
| DNA-Aufreinigung und Analytik | [Vorbereitung](../extraction-automation.md), [integrierte Extraktionsanalytik](../extraction-analytics.md) |
| CUT&RUN | [Referenz und Preflight](../cutrun-reference-profile.md), [synthetischer Lauf](../cutrun-synthetic-workflow.md), [manuelle Vorbereitung](../cutrun-manual-reference.md), [Aufzeichnungskern](../cutrun-manual-runtime.md), [Sonikationsvorbereitung und S09-Fixture](../dna-sonication.md), [S09-SiLA-Loopback](../sonication-sila2-network.md) |
| Manuelle Messungen | [Gemeinsamer Kern](../manual-tasks.md), [NanoDrop](../nanodrop-manual-workflow.md), [Qubit 4](../qubit-4-manual-workflow.md) |
| Stationsübergreifende Übergaben | [Asynchroner Labortransport](../async-lab-transport.md) |
| Geräteprotokolle | [CF01-Vertrag](../centrifuge-cf01.md#cf01-protocol), [CF01-SiLA-Netzwerk](../sila2-network.md) |

## Quellen und Nachweisgrenzen

Die maschinenlesbaren Modell- und Protokollquellen bleiben unter `model/`.
Diese Übersicht erzeugt weder einen neuen Laufzeitvertrag noch eine zusätzliche
Bestandsführung. Synthetischer Ablauf, manuelle Aufzeichnung, Netzwerktransport,
native Geometrieprüfung und reale Geräte- oder biologische Qualifikation bleiben
unterschiedliche Nachweise. Die jeweiligen Dokumente benennen ihre Grenzen;
eine redaktionelle Zusammenführung oder Verlagerung hebt diese nicht auf.
