# Festgehaltene Regressionsevidenz

Diese kleinen historischen Referenzen sind bewusst versionierte Testeingaben,
keine aktuellen Build-Berichte. Nicht beim normalen Build überschreiben.

- `c01-geometry-reference.json`: unverändert aus dem zuvor versionierten
  `cad/tube-station-c01/geometry-reference.json`; geprüfte C01-Volumina.
- `t01-cad-check-evidence.json`: unverändert aus dem zuvor versionierten
  `cad/tip-collector-t01/cad-check-evidence.json`; T01-Körpervolumina und Schwerpunkte.

Die Tests vergleichen die heutige gemeinsame Quelle mit diesen unabhängigen
Referenzständen. Neue CAD-Ausgaben und ihre Prüfberichte bleiben lokal.

- `l01-before-layer-split.json`: evaluated primitives, CSG order, appearances,
  named frames and equipment/transfer poses from the pre-split L01 generator;
  five parameter cases. This is regression evidence, not editable construction
  intent. Native comparison is recorded separately in local build reports.

- `cf01-before-workspace.json`: Bank, Geräteposen, Rackparameter und alle 241
  Entnahmeschritte vor der Ableitung aus der synthetischen Umgebung. Unabhängige
  Regressionsevidenz; keine zusätzliche führende Gerätebeschreibung.
  Herkunft: letzter Stand vor der Umstellung, Commit `ad9de56`, bestehende
  Szene `05dba7428daa`; erzeugt mit der bisherigen Szenenauswertung. Der exakte
  Vergleich ist bewusst streng, da diese Umstellung keine Bewegungsänderung
  zulässt.
