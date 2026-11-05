# ROS-2-Interface, RViz und Gazebo

Für die Zentrifuge CF01 liegt inzwischen ein getrenntes generiertes Paket
`solidcraftbot_cf01_interfaces` mit Zustandsnachricht, sieben Actions und neun
Services vor. Es enthält keine ROS-Node; Kompilierung und ROS-Laufzeit sind
ungeprüft. Gemeinsame SiLA-Zuordnung, Ablauf, SI-Einheiten und Mock-Prüfungen:
[CF01-Protokoll](centrifuge-cf01-protocol.md).

Die gemeinsame Quelle enthält zusätzlich Servo- und Leitungsanforderungen.
`config/services.json` hält die geprüfte logische Zuordnung zu den ROS-Gelenken
und die offenen Hardware-/Kabelfragen fest. Der ROS-Laufzeitcode setzt diesen
Vertrag noch nicht um; der Backend bleibt Mock-Hardware. Details stehen in
[servo-cables.md](servo-cables.md).

Die vorbereitete Schnittstelle liegt unter
`ros2_ws/src/solidcraftbot_ros`. Zielumgebung ist ROS 2 Jazzy mit den
passenden `ros2_control`-Paketen, beispielsweise unter Ubuntu 24.04.
Auf dem Windows-Entwicklungsrechner ist keine nutzbare ROS-2-Laufzeit vorhanden;
auch der Zugriff auf die WSL-Distributionen war hier nicht möglich.
Die folgenden Startbefehle sind vorbereitet, bisher aber nicht im laufenden
ROS-System geprüft.

## Erzeugen

Im Projektverzeichnis unter PowerShell:

```powershell
python scripts/build_models.py --ros2
python -m unittest discover -s tests -v
```

Dies erzeugt aus `model/robot.json` beide CAD-Fassungen sowie:

- URDF mit sechs Drehgelenken und der Flanschreferenz `tool0`;
- Visualisierungsmeshes in m, einschließlich dunkler UMR-Buchstaben;
- sechs einfache Servo-Gehäusequader; Vendor-Details werden nicht zusätzlich
  in die Strukturmeshes aufgenommen;
- konservative Kollisionsquader je Körper;
- Konfiguration für Mock-Hardware, Joint-State-Broadcaster und Trajektoriencontroller;
- dieselben Protokollwegpunkte in rad.

Seit Kamerastand V02 enthält die Beschreibung außerdem zwei Kamerabauräume
mit provisorischen Haltern und transparenten Sichtkegeln. Die Kamera- und
Halterkörper haben Kollisionsquader; die rein visuellen Kegel ausdrücklich
nicht. Getrennte Mesh-Visuals erhalten Türkis für C_tip und Blau für C_scene,
einschließlich der in der Quelle erklärten Kegelopazität.
Die optischen Frames `c_tip_optical` an `l6_bareflange` und `c_scene_optical`
an `l1_turret` sind feste, unkalibrierte Entwurfsrahmen (+Z vorwärts, +X rechts,
+Y unten). `config/cameras.json` hält deren Herkunft, Kegelmaße und offene
Kabel-/Kalibrierfragen fest. Es sind keine Kameratreiber, Bildthemen oder
Gazebo-Sensoren angelegt; RViz zeigt hier nur die geometrische Konzeption.

Die Zuordnung von Konstruktionsrahmen zu URDF-Gelenkrahmen wird geprüft.
Die zwölf Vendor-Gehäuse-/Ausgangsgeometrien bleiben in der CAD-Kollisionsprüfung
getrennt. URDF enthält deren konservative Kollisionsquader am jeweiligen starren
Glied; die Ausgangsplatten und Kupplungen bleiben im sichtbaren Strukturmesh.
Die neue Flanschreferenz berücksichtigt das verlängerte J6-Paket. Siehe
[Servo-Integration](servo-integration.md).
Die ursprünglichen mm/° werden ausdrücklich in m/rad umgerechnet.
Die Kollisionsquader schließen die jeweilige Körpergeometrie ein, füllen
dadurch aber auch Löcher und Freiräume. Sie können deshalb gegenüber der
genaueren CAD-Prüfung zusätzliche Kollisionsmeldungen verursachen.

## Start unter ROS 2 Jazzy

In einem ROS-2-Terminal mit vorhandener Jazzy-Installation und `rosdep`/`colcon`:

```bash
source /opt/ros/jazzy/setup.bash
cd /mnt/c/Users/u005069/GitHub/SolidCraftBot/ros2_ws
rosdep install --from-paths src --ignore-src -r --rosdistro jazzy -y
colcon build --symlink-install --packages-select solidcraftbot_ros
source install/setup.bash
ros2 launch solidcraftbot_ros mock.launch.py
```

Auf einem anderen Linux-Rechner den Projektpfad entsprechend einsetzen.
Der Start lädt RViz, den Robot-State-Publisher, `controller_manager`, den
Joint-State-Broadcaster und `arm_controller`. Standard-Namespace ist `/umr`.
Ohne RViz: `ros2 launch solidcraftbot_ros mock.launch.py rviz:=false`.

In einem zweiten entsprechend eingerichteten Terminal die Sequenz ausführen:

```bash
source /opt/ros/jazzy/setup.bash
cd /mnt/c/Users/u005069/GitHub/SolidCraftBot/ros2_ws
source install/setup.bash
ros2 run solidcraftbot_ros run_protocol --ros-args -r __ns:=/umr
```

Der Client wartet auf vollständige Gelenkzustände und verweigert den Start,
wenn die aktuelle Pose mehr als 0,05 rad von der erklärten Anfangspose abweicht.
Er prüft alle sechs Winkel, die zeitliche Reihenfolge und die konfigurierte
Geschwindigkeitsgrenze, sendet ein Action-Ziel und wertet dessen Ergebnis aus.
Bei Abbruch wird die Stornierung des laufenden Ziels angefordert.

Für eine reine Datenprüfung ohne ROS-Importe kann `demo.py` mit `--dry-run`
und explizitem `--config` ausgeführt werden; der Pfad zur Paketquelle muss
dabei im Python-Suchpfad liegen.

## Schnittstellen

Die ergänzenden `urdf/robot_mb01_working.urdf` und
`urdf/robot_mb01_manual_reposition.urdf` kombinieren den unveränderten
Sechsachsencontroller mit der mobilen Basis aus derselben gemeinsamen Quelle.
Basis und Stützen sind darin feste manuelle Zustandsbilder in m/rad. Der normale
Mock-Start verwendet weiterhin `robot.urdf`; die mobilen Beschreibungen sind
separate Anzeigeeingaben, keine Fahrsteuerung. `config/mobile-base.json` hält
Quelle, Zustände und Anforderungen der visuellen Wiederaufnahme fest. ROS/RViz-
Laufzeit und Kameraregelung bleiben ungeprüft. Details: [MB01](mobile-base-mb01.md).

| ROS-Name | Typ und Bedeutung |
|---|---|
| `/umr/arm_controller/follow_joint_trajectory` | `control_msgs/action/FollowJointTrajectory` |
| `/umr/joint_states` | `sensor_msgs/msg/JointState`, Winkel in rad |
| `/umr/robot_description` | URDF-Beschreibung des erzeugten Roboters |
| TF-Frames | `base_link`, sechs Glieder, `tool0`, `c_tip_optical`, `c_scene_optical` |

Die ROS-Gelenknamen sind die kleingeschriebenen gemeinsamen Gelenk-IDs.
Die Paketkonfiguration legt die Reihenfolge fest; der Client verlangt
vollständige Sechsachsen-Ziele. Ein anderer Namespace kann beim Start gewählt
werden und muss beim Client identisch sein. Mehrere gleichzeitig angezeigte
Arme benötigen zusätzlich eine eindeutige TF-Rahmenbenennung; das ist noch nicht
als Mehrarmstation konfiguriert.

## Was die aktuelle Simulation aussagt

`mock_components/GenericSystem` spiegelt idealisierte Positionskommandos in
Gelenkzustände. Das ist für Schnittstellen- und Ablaufprüfungen gedacht.
Es berechnet keine realistische Schwerkraft-, Kontakt- oder Antriebsdynamik.
Das entspricht dem Zweck der offiziellen
[Mock Components](https://control.ros.org/jazzy/doc/ros2_control/hardware_interface/doc/mock_components_userdoc.html).

URDF verlangt für Drehgelenke auch Geschwindigkeits- und Kraftgrenzen.
Die eingetragenen 0,5 rad/s und 1 N·m sind ausdrücklich Einstellungen für diesen
Mock-Aufbau und keine ausgewählten oder berechneten Motorgrenzwerte.
Es wurden keine erfundenen Robotermassen oder Trägheitstensoren eingetragen.
Der ROS-Client führt keine Online-Kollisionsprüfung aus. Der Offlinebericht
prüft nur die dort dokumentierten Posen derselben Sequenz.

Die Trajektorienschnittstelle folgt dem offiziellen
[Joint Trajectory Controller](https://control.ros.org/jazzy/doc/ros2_controllers/joint_trajectory_controller/doc/userdoc.html).
Ein späterer realer Hardwaretreiber oder eine Gazebo-Anbindung kann diese
ROS-Schnittstelle wiederverwenden; die zugehörigen Regelungs- und
Hardwareeigenschaften müssen separat entwickelt und geprüft werden.

## RViz gegenüber Gazebo

| Werkzeug | Rolle im Projekt |
|---|---|
| SolidCraft / FreeCAD | Konstruktion, Geometrie und mechanische Schnittstellen |
| ROS 2 | Nachrichten, Koordinatenrahmen, Controller und Protokollanbindung |
| RViz | Darstellung veröffentlichter Roboterzustände und Sensordaten |
| Gazebo | Später mögliche Physik- und Sensorsimulation |

[RViz](https://github.com/ros2/rviz) ist ein 3D-Visualisierer. Es kann die
Gelenkzustände des Mock-Aufbaus ebenso darstellen wie spätere Zustände eines
Gazebo-Modells oder eines realen Roboters.

[Gazebo](https://gazebosim.org/docs/harmonic/getstarted/) kann etwa Schwerkraft,
Kontakte und simulierte Sensoren bereitstellen. Für eine belastbare Untersuchung
dieses Arms wären Massen, Trägheiten, Antriebseigenschaften, Reibung und
Kontaktannahmen zu bestimmen. Die Anbindung an die Controller ist später über
[gz_ros2_control](https://control.ros.org/jazzy/doc/gz_ros2_control/doc/index.html)
möglich. Für die gewählte Jazzy-Zielumgebung ist Gazebo Harmonic eine passende
dokumentierte Kombination. Es ist hier noch kein Gazebo-Modell gestartet oder
physikalisch validiert worden.

Der Tropfenversuch mit 1 µl Wasser erfordert zusätzliche Modelle oder reale
Versuche für Benetzung, Kapillarkräfte, Verdunstung und optische Erkennung.
Eine gewöhnliche Starrkörpersimulation dieses Arms liefert dafür noch keinen
Nachweis.
