# MYACTUATOR-Referenzbibliothek

Herstellerdateien abgerufen am 28. Oktober 2026 über
[Downloads X-Series](https://www.myactuator.com/downloads-xseries).
Original-ZIP und extrahierte STEP-/PDF-Dateien bleiben unverändert. Das
[Manifest](manifest.json) enthält genaue Download-URLs, Dateinamen im Archiv,
Revisionen, Größen und SHA-256. Die Benennung `vendor-document-N.pdf` entspricht
der Reihenfolge im jeweiligen Archiv, nicht einer allgemeinen Dokumentklasse.

| Bevorzugtes Modell | Paket | Original-STEP | Referenz für CAD | Quader in Herstellerachsen | Zeichnung und Daten |
|---|---|---|---|---|---|
| RMD-X2-P28-7-E | 260920 | [STEP](RMD-X2-P28-7-E/260920/vendor-model-1.step) | [STEP](RMD-X2-P28-7-E/260920/derived/cad-reference.step) | [STEP](RMD-X2-P28-7-E/260920/derived/conservative-box.step) | [Zeichnung](RMD-X2-P28-7-E/260920/vendor-document-1.pdf), [Parameter](RMD-X2-P28-7-E/260920/vendor-document-2.pdf) |
| RMD-X4-P36-36-E-L | 261019 | [STEP](RMD-X4-P36-36-E-L/261019/vendor-model-1.step) | [STEP](RMD-X4-P36-36-E-L/261019/derived/cad-reference.step) | [STEP](RMD-X4-P36-36-E-L/261019/derived/conservative-box.step) | [Spezifikation mit Zeichnungen](RMD-X4-P36-36-E-L/261019/vendor-document-1.pdf), [Parameter](RMD-X4-P36-36-E-L/261019/vendor-document-2.pdf) |
| RMD-X6-P20-60-E | 260920 | [STEP](RMD-X6-P20-60-E/260920/vendor-model-1.step) | [STEP](RMD-X6-P20-60-E/260920/derived/cad-reference.step) | [STEP](RMD-X6-P20-60-E/260920/derived/conservative-box.step) | [Zeichnung](RMD-X6-P20-60-E/260920/vendor-document-1.pdf), [Parameter](RMD-X6-P20-60-E/260920/vendor-document-2.pdf) |

## Importprüfung

FreeCADs Kernbibliothek liest alle drei STEP-Dateien mit Längen in mm. Die
abgeleiteten Referenzen lassen sich erneut öffnen und bestehen die dokumentierte
Geometrieprüfung. Die Außenmaße in den unveränderten Herstellerachsen betragen:

| Modell | X × Y × Z, mm | Originale Volumenkörper → Referenz |
|---|---:|---:|
| X2 | 44,014 × 63,500 × 44,014 | 52 → 52 |
| X4-L | 55,960 × 55,349 × 61,001 | 43 → 41 |
| X6 | 80,000 × 67,500 × 80,000 | 54 → 54 |

Diese Quader sind keine Nenndurchmesser und legen keine Montageachse fest.
Der X4-Originalimport enthält zwei ungültige Kleinstkörper von je weniger als
0,000005 mm³ und maximal 0,150 mm Ausdehnung. Nur diese beiden Körper wurden in
der Referenz weggelassen. Vorhandene offene Schalen bleiben erhalten. Die
STEP-Wiederöffnung verändert die äußeren Grenzen um weniger als 0,00001 mm;
die numerische Volumendifferenz beim X4 beträgt rund 0,174 mm³ (4,27 ppm).
Die Referenz ist deshalb für Bauraum und Montageplanung freigegeben, nicht
als Toleranz- oder Fertigungsnachweis. Das Volumen gemischter Schalen und
Volumenkörper liefert insbesondere keine verlässliche Masse.

Details und die Nummern der ausgelassenen Körper stehen in
[geometry-check.json](geometry-check.json) und den Einzelberichten neben den
Referenzen. Die Rohdateien erhalten ihre ursprünglichen Prüfsummen.

## Reproduzieren

Für die Arm-Integration sind zusätzlich getrennte, vereinfachte Gehäuse- und
Ausgangsgeometrien unter `derived/registered-v1/` angelegt. Die
[Komponentenbibliothek](component-library.json) führt deren Frames, Prüfsummen
und nominale Motorplatten-Schnittstellen. Geschlossene äußere Schalen werden
zu Volumenkörpern; interne Teile und Kleinteile entfallen. Die Originale bleiben
unverändert. Der [Integrationsbericht](../../../docs/servo-integration.md)
dokumentiert die Integration und fehlende Fertigungsqualifikation.
Die [X6-Lochbildklärung](../../../docs/x6-interface-resolution.md) korrigiert
unsere frühere Zuordnung der Maßpfeile. Die X6-Ableitung `registered-v2` enthält
auch die beiden Zentrierhülsen und die korrigierten Motorplatten-Schnittstellen.

Im Projektordner mit normalem Python:

```powershell
python scripts/fetch_actuator_cad.py
```

Vorhandene Originale werden geprüft und nicht erneut heruntergeladen. Für die
Geometrieprüfung FreeCADs mitgeliefertes Python verwenden, beispielsweise:

```powershell
& "$env:LOCALAPPDATA/Programs/FreeCAD 27.1/bin/python.exe" scripts/inspect_actuator_cad.py
```

Die Prüfung importiert ausschließlich den FreeCAD-Kern und `Part`; sie startet
keinen FreeCADGui-/Qt-Prozess. Die geöffnete Armkonstruktion wird nicht ersetzt.
Der Prüfbericht nennt die konkrete FreeCAD-Version. Referenzdateien werden
angelegt, wenn sie fehlen; vorhandene Ableitungen werden erneut eingelesen.

Herstellerurheberrechte bleiben bestehen; eine Lizenz zur öffentlichen
Weiterverteilung wurde nicht festgestellt. Die Bibliothek ist lokal im Projekt
gespeichert und wurde nicht veröffentlicht. Registrierung der Montageframes,
Abgleich mit Musterteilen und die Einbindung in beide CAD-Generatoren folgen dem
[Integrationsplan](../../../docs/vendor-cad-plan.md).
