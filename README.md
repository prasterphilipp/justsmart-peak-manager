# JustSmart Peak Manager

Private Home-Assistant-Integration mit nativer JustSmart Card für die ab 2027 geplante leistungsbezogene Netzentgeltstruktur in Österreich.

## Was der Peak Manager macht

Der Peak Manager integriert den tatsächlichen Netzbezug in den festen lokalen Viertelstundenfenstern `00–15`, `15–30`, `30–45` und `45–60`. Er zeigt nicht nur die momentane Leistung, sondern berechnet:

- aktuellen Viertelstunden-Durchschnitt,
- Prognose bis zum Ende des laufenden 15-Minuten-Intervalls,
- verbleibenden Leistungsspielraum,
- empfohlenen Reduktionsbedarf,
- höchste abgeschlossene Viertelstundenleistung des Monats,
- aktive Maßnahme und Datenqualität.

Kurze Sekunden-Spitzen werden dadurch nicht mit einem falschen gleitenden Mittelwert verwechselt. Negative Netzwerte (Einspeisung) werden nie als negativer Import angerechnet.

## Sicherheitsmodell

Die Integration startet immer im **Monitor-Modus**. In diesem Modus werden keine neuen Reduktionen ausgelöst. Zuvor nachweislich vom Peak Manager veränderte Geräte werden beim Wechsel aus der Automatik einzeln und kontrolliert auf ihren ursprünglichen Zustand zurückgeführt.

Die **Automatik** wird erst über `select.justsmart_peak_manager_betriebsart` aktiviert. Sie darf ausschließlich Geräte verändern, die in den Integrationsoptionen ausdrücklich ausgewählt wurden:

1. Wallbox-Ladestrom wird stufenweise reduziert.
2. Eine Wallbox wird nur pausiert, wenn zusätzlich eine Freigabe-/Schaltentität konfiguriert wurde.
3. Danach werden bis zu drei priorisierte flexible Lasten pausiert.
4. Entspannte Intervalle geben ausschließlich zuvor vom Peak Manager beeinflusste Geräte kontrolliert wieder frei.

Batterie- oder Wechselrichterregister werden bewusst nicht generisch beschrieben. Unterschiedliche Hersteller interpretieren Strom-, Leistungs- und TOU-Register verschieden. Dafür stellt `sensor.justsmart_peak_manager_empfohlene_reduktion` eine herstellerneutrale Reduktionsanforderung bereit, die eine geprüfte Deye-/Solarman-Automation verwenden kann.

## Installation

### HACS (privates Repository)

1. HACS → Integrationen → Benutzerdefinierte Repositories.
2. Repository-URL hinzufügen und Kategorie **Integration** wählen.
3. `JustSmart Peak Manager` installieren.
4. Home Assistant neu starten.
5. Einstellungen → Geräte & Dienste → Integration hinzufügen → **JustSmart Peak Manager**.

Die Integration kopiert die gebündelte Card nach `/www/justsmart_peak_manager/justsmart-peak-manager-card.js` und registriert automatisch die Ressource `/local/justsmart_peak_manager/justsmart-peak-manager-card.js?v=0.1.1`.

### Manuell

Den Ordner `custom_components/justsmart_peak_manager` nach `/config/custom_components/` kopieren und Home Assistant neu starten.

## Einrichtung

Pflicht:

- Netzleistungs-Sensor mit `W` oder `kW`
- Vorzeichen: positiver oder negativer Wert für Netzbezug
- Zielspitze, z. B. `4,5 kW`
- Warnabstand, z. B. `0,5 kW`

Optional unter **Konfigurieren**:

- Wallbox-Ladestrom-Entität (`number`)
- Wallbox-Freigabe (`switch` oder `input_boolean`)
- 1- oder 3-phasig, Spannung, Min/Max-Ampere
- bis zu drei flexible Lasten mit geschätzter Leistung und Prioritätsreihenfolge

## Card

Nach der Einrichtung werden die tatsächlichen Entity-IDs in Home Assistant angezeigt. Beispiel:

```yaml
type: custom:justsmart-peak-manager-card
title: Netzspitzen Manager
projected_entity: sensor.justsmart_peak_manager_viertelstunden_prognose
average_entity: sensor.justsmart_peak_manager_viertelstundenmittel
target_entity: number.justsmart_peak_manager_zielspitze
headroom_entity: sensor.justsmart_peak_manager_leistungsspielraum
monthly_peak_entity: sensor.justsmart_peak_manager_monatsspitze
remaining_entity: sensor.justsmart_peak_manager_verbleibende_intervallzeit
status_entity: sensor.justsmart_peak_manager_status
action_entity: sensor.justsmart_peak_manager_aktive_massnahme
mode_entity: select.justsmart_peak_manager_betriebsart
grid_options:
  columns: 12
  rows: 5
```

### YAML-Anzeigeoptionen

Alle Bereiche bleiben standardmäßig sichtbar. Sie können einzeln ausgeblendet werden:

```yaml
type: custom:justsmart-peak-manager-card
title: Netzspitzen Manager
show_eyebrow: true
eyebrow: JustSmart Lastmanagement
show_title: true
show_status_badge: true
show_remaining: true
show_meter: true
show_average: true
show_target: true
show_headroom: true
show_monthly_peak: true
show_status_metric: true
show_action: true
```

Wie bei den übrigen JustSmart Cards werden für den Eyebrow auch die Aliase
`show_overline`/`overline` und `show_kicker`/`kicker` akzeptiert. Für die Restzeit
kann alternativ `show_timer` verwendet werden; `show_status` ist ein Alias für
`show_status_badge`. Werden alle vier seitlichen Kennzahlen ausgeblendet, nutzt
die Prognose automatisch die volle Kartenbreite.

Die Card ist für Home-Assistant-Sections optimiert, unterstützt Tastaturfokus und `prefers-reduced-motion` und aktualisiert Livewerte ohne vollständigen Shadow-DOM-Neuaufbau.

## Wichtige Genauigkeitshinweise

- Der Quellsensor sollte schnell genug aktualisieren; ideal sind lokale Smart-Meter-/Inverterdaten im Sekundenbereich.
- Beim allerersten Start mitten in einer Viertelstunde wird der aktuelle Messwert konservativ als Schätzung für den unbekannten Intervallanfang verwendet und die Datenqualität als `partial` markiert.
- Nach einem Home-Assistant-Neustart wird eine unbeobachtete Lücke nicht mit dem letzten alten Messwert aufgefüllt; auch dieses laufende Intervall bleibt `partial`.
- Geräte werden nur restauriert, solange Home Assistants Context-ID den letzten Eingriff eindeutig dem Peak Manager zuordnet. Eine zwischenzeitliche manuelle Änderung verwirft diese Berechtigung; die Integration schaltet das Gerät dann nicht eigenmächtig wieder ein.
- Der ursprüngliche Wallbox-Stromwert und die Aktor-Zuständigkeit werden gespeichert. Die Freigabe erfolgt mit Hysterese und höchstens einem Schritt pro Regelzyklus, nie pauschal bis zum konfigurierten Maximalstrom.
- Die Monatsspitze ist eine lokale Betriebsmetrik. Für die Rechnung bleiben die Daten und Regeln des Netzbetreibers maßgeblich.
- Konkrete Euro-Einsparungen werden nicht behauptet, solange die jährliche österreichische Tarifverordnung nicht feststeht.

## Tests

```bash
python -m pytest tests -q
npm test
npm run check
python -m compileall -q custom_components
```

## Lizenz

Proprietär und vertraulich. Alle Rechte vorbehalten.
