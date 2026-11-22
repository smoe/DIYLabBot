# Eiswürfelmaschine IM01

IM01 ist ein 3D-Modell für die Laboraufstellung. Das Gehäuse hat eine geneigte
Front am Eisfach, eine offene Klappe, eine blaue Behälterauskleidung und ein
Lüftungsgitter in der Edelstahlfront. Das [VEVOR-Produktfoto](https://img.vevorstatic.com/de%2FYTSZBJFB100LH5H89001V2%2Fgoods_img_big-v3%2Fcommercial-ice-maker-m100-1.2.jpg)
zeigt die Referenz `YTSZBJFB100LH5H89001V2`. VEVOR nennt in den
[technischen Daten zur verwandten V1](https://www.vevor.com/other-c_45583/vevor-commercial-ice-maker-machine-100-lbs-24h-with-30-lbs-storage-capacity-built-in-freestanding-under-counter-stainless-steel-ice-maker-with-led-display-self-cleaning-for-home-bar-restaurant-p_010982478769)
mit derselben Modellnummer CIM-360T Außenmaße von 400 × 385 × 759 mm. Das sind
die Nennmaße des modellierten Standgeräts. Innenmaße, Details und die kompakte
Tischvariante sind Annahmen für die Aufstellung.

| Variante | Breite × Tiefe × Höhe | Freies Eisfach unter der Entnahmekante |
| --- | --- | --- |
| `floor_standing` · Standgerät | 400 × 385 × 759 mm | 18,15 l |
| `countertop` · Tischgerät | 400 × 385 × 599 mm | 8,76 l |

Beide Varianten haben dieselben vier 34 mm hohen Füße. Die größere Höhe des
Standgeräts entsteht im Eisfach. Das freie Volumen ist aus der ausgekleideten
Innenbreite, Innentiefe und Höhe bis zur Unterkante der Öffnung berechnet. Es
ist ein geometrischer Wert. Die tatsächlich lagerbare Eismenge hängt unter
anderem von Form und Packung der Eiswürfel ab.

Die [gemeinsame Modellquelle](../model/ice-maker-im01.shared.json) bestimmt
beide Varianten über die Höhe des Eisfachs. X verläuft über die Gerätebreite,
Y von der Front zur Rückwand und Z ab der Auflage nach oben. Für eine spätere
Aufstellung liegt `Z=0` beim Standgerät auf dem Boden und beim Tischgerät auf
der Arbeitsplatte. Das Modell zeigt die Entnahmeklappe in einer festen offenen
Position. Eisproduktion, Versorgung, Gerätelast und Einbaufreiräume sind offen.

Der [Generator](../scripts/build_ice_maker.py) baut beide Varianten unabhängig
für FreeCAD und SolidCraft. `--backend freecad` oder `--backend solidcraft`
wählt nur eines der beiden CAD-Systeme. Der lokale Build-Bericht unter
`exports/generated/ice-maker-im01-*/` enthält die Dateipfade, Prüfsummen und
Prüfergebnisse.

```sh
python3 scripts/build_ice_maker.py
```
