# Synthetische NanoDrop-Testdaten

Beide CSV-Dateien wurden für die Offline-Tests von Hand erstellt. Sie stammen
aus keinem Gerät und enthalten keine realen Proben, Seriennummern oder Messungen.
Auch die SOP und sämtliche Volumina im Profil sind fiktive Testeingaben.

Die Dateien prüfen ausdrücklich unterschiedliche Zeilenfolgen, mehrere Messgrößen,
Unicode-Einheiten, Komma- beziehungsweise Semikolon-Trennung und Dezimalkomma.
Die Messnamen passen ausschließlich zum Testlauf `SYN-ND-FIXTURE`; sie sind keine
allgemeinen Probenkennungen. Die Originalbytes werden beim Import in SQLite
unverändert mit SHA-256 archiviert.

Das Herstellerhandbuch dokumentiert CSV-Exporte für Messwerte und TSV für
Spektren beim [NanoDrop One](https://documents.thermofisher.com/TFS-Assets/MSD/manuals/nanodrop-one-c-user-guide-EN_20211102.pdf).
Die hier gewählten Spalten sind ein enger synthetischer Adaptervertrag, kein
Nachweis für alle Geräteversionen oder Exportlayouts. Ein unveränderter echter
Export, dessen Bezeichnungslängen und Softwarestand wurden noch nicht geprüft.
TSV wird in diesem Adapter nur als tabulatorgetrennte Ergebnistabelle gelesen;
ein reiner Spektrenexport ist noch kein unterstützter Ergebnisimport.
