# Ausschließlich synthetische Qubit-Testdaten

`synthetic-report.csv` ist eine bewusst erzeugte interne Testtabelle mit dem
Formatmarker `solidcraftbot.synthetic-qubit-report/1`, kein Geräteexport.
Assay, SOP, Chargen, Seriennummer und sämtliche Zahlen sind fiktiv. Zwei
Standard- und drei Probenzeilen stehen absichtlich in anderer Reihenfolge als
die Ausführung. Die Messungskennungen gehören nur zu `SYN-QB-FIXTURE`.

Die Beispieldatei wurde einmal aus der explizit synthetischen Demo erzeugt;
Tests lesen sie anschließend als festen Input und prüfen konkrete Zuordnungen,
berichtet belassene Originalkonzentrationen sowie separat abgeleitete Größen.
Sie benutzt gemischte Einheiten und enthält keine vorgetäuschte native
Kalibrierungs-ID. Der Kalibrierungsbezug stammt aus dem Laufprotokoll.
Originalbytes und Prüfsumme bleiben bei jedem Import im SQLite-Artefaktarchiv.

Es wurde keine echte Exportdatei validiert. Netzwerkkommunikation, Messleistung
und Hersteller-SOPs sind damit nicht nachgewiesen. Siehe
[Ablauf und Grenzen](../../../docs/qubit-4-manual-workflow.md).
