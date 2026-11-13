# L01 / 3.003 · Fensterfront nach Nordwest

Die Fensterfront von 3.003 ist durch den Eigentümer als **Nordwest** bestätigt.
Für die achtteilige Kompassreferenz entspricht das nominal **315°**, im
Uhrzeigersinn ab geografischem Nord. Ein gemessener Fassadenazimut bleibt
unbekannt. Die gekrümmte Front hat zudem nicht überall dieselbe Flächennormale.

## Abgleich von Grundriss und Karte

Der [bereitgestellte Google-Maps-Punkt](https://maps.app.goo.gl/7GY7XLHJsBtBYQWr6)
markiert laut Eigentümer das Gebäude, nicht den Ursprung oder die Lage von L01.
Die Kartenansicht zeigt einen gerundeten Baukörper; dessen Außenform wurde mit
der freigegebenen F03-Vektorableitung visuell verglichen. Die Karte enthält
keine Zuordnung der Raumnummer 3.003. Der genaue Fensterbezug ist deshalb
**Eigentümerbestätigung**, keine unabhängig aus Google Maps gemessene Richtung.
Insbesondere wird der in F03 unklare externe Anschluss nicht als gesicherter
Passpunkt einer Registrierung verwendet.

Im F03-Grundriss liegt `R3_003` am gekrümmten Außenrand. Seine beiden äußeren
Segmente sind `W037` und `W061`; die anderen drei Grenzen werden mit benachbarten
Bereichen geteilt. Der Helfer prüft diese Außenlage aus dem gemeinsamen
Grenzgraphen. Die Richtungsnamen „Nord/Süd“ in älteren F03-Beschreibungen
bezeichnen die Zeichnungslage und begründen keinen geografischen Nordbezug.

## Bezugssystem für die spätere Tageslichtsimulation

Die vorhandene L01-Konvention bleibt erhalten: +Y zeigt von den Türen zu den
Fenstern, +X beim Blick zu den Fenstern nach rechts und +Z nach oben. Daraus
folgt für den bestätigten nominalen Nordwestbezug:

| Lokale Achse | Nominale geografische Richtung | Azimut |
|---|---|---:|
| +Y · zu den Fenstern | Nordwest | 315° |
| +X · rechts beim Blick zu den Fenstern | Nordost | 45° |
| +Z | oben | – |

Geografisch Nord liegt damit im lokalen L01-System auf der Diagonalen zwischen
+X und +Y. Die reine Rotationsmatrix zu East/North/Up wird automatisch aus dem
Kompasssektor abgeleitet. Sie enthält weder eine reale Translation noch einen
Maßstab und wird nicht als vollständige geodätische Raumlage ausgegeben.

Die führende Referenz ist
[model/l01-orientation.reference.json](../model/l01-orientation.reference.json).
Sie pinnt die vorhandenen F03- und L01-Quellen; ihre Quellgeometrie bleibt
bytegleich. Eine unabhängige Kopie von Wand-, Möbel- oder Gerätedaten wird
nicht angelegt. Ableitung und Prüfung:

```sh
python3 scripts/l01_orientation.py
python3 -m unittest discover -s tests -p 'test_l01_orientation.py' -v
```

Die lokale Auswertung steht in `exports/tr01-workcell/orientation-review.json`.
Der geografische Gebäudepunkt bleibt von der unbekannten Lage des lokalen
Raumursprungs getrennt. F03 behält `calibration: null`; eine metrische
Übertragung von L01 nach F03 oder Google Maps ist nicht implementiert.

Für die bestehende Animation ändert sich dadurch keine Geometrie und keine
Bewegungsbahn. Die Tageslichtdarstellung verwendet weiterhin angenähertes
Fenster- und Umgebungslicht im lokalen Raumrahmen. Das darauf aufbauende [Echtzeit-Tageslichtmodell](tr01-workcell-animation.md#orientiertes-tageslicht-und-geworfene-schatten)
berechnet inzwischen Sonnenstand, Fensterlicht und angenäherte geworfene
Schatten in der Animation. Eine kalibrierte Luxsimulation und die Umsetzung
in FreeCAD-, SolidCraft- oder ROS-Weltframes bleiben offen.
