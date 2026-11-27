# Stationäre Kameras

Der [Kamerakatalog](../model/stationary-camera.catalog.json) beschreibt eine
Kamerafamilie mit gemeinsamem Gehäuse, Objektiv und Montageplatte. Die
Konstruktion bietet zwei Varianten für eine stationäre Montage.

| Variante | Aufbau | Zielrichtung |
|---|---|---|
| `fixed` | Starrer Halter auf der Montageplatte | Durch die Aufstellung festgelegt |
| `pan_tilt` | Drehteller und Neigegabel mit zwei Drehgelenken | Am Modell über `Pan` und `Tilt` einstellbar |

Die Montageplatte bleibt bei beiden Varianten ortsfest. Im unverdrehten
Modell liegt die Blickrichtung auf der Modellachse +X. `Pan` dreht um die
vertikale Modellachse +Z, `Tilt` neigt den Kopf um die mitgedrehte Querachse.
Die angenommene Auslenkung reicht in der Standardkonfiguration von 0° bis
120° bei `Pan` und von 0° bis 55° nach unten bei `Tilt`. Der optische Rahmen
folgt der Objektivfront. Seine optischen Achsen sind +Z in Blickrichtung,
+X nach rechts und +Y nach unten.

Der [Modellableiter](../scripts/stationary_camera.py) erzeugt die Geometrie und
Gelenkbezüge für beide Varianten. Der [Bau-Einstieg](../scripts/build_stationary_cameras.py)
unterstützt die einzelnen Ziele `freecad` und `solidcraft` sowie `both`.

```bash
python3 scripts/build_stationary_cameras.py --backend both
```

Instanzen in einer Umgebung benötigen später eine eigene Aufstellung mit
Position und Ausrichtung. Sichtfelder, Kalibrierung, Kamerabilder und
Ansteuerung bleiben Aufgaben einer späteren Sensorintegration. Die Modelle
beschreiben angenommene Bauteilabmessungen und Gelenkgrenzen für die
Konstruktion. Montagefestigkeit, Leitungsführung, durchgängige Kollisionsfreiheit
und Fertigung bleiben unqualifiziert.
