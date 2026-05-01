# Project Spec Validation

Verdict: `FAIL`

| Status | Check | Message |
|---|---|---|
| PASS | schema-version | schema_version is 1. |
| PASS | project-name | project_name is present and slug-safe. |
| PASS | description | description is present. |
| PASS | input-power-source | input_power.source=usb_c is supported. |
| PASS | input-power-voltage | input_power.voltage=5.0V is valid. |
| PASS | battery-mode | No battery path requested. |
| PASS | main-regulator | main_regulator TLV75533PDBVR exists in the library. |
| PASS | power-rails | 1 power rail(s) declared. |
| PASS | power-budget | +3V3 current budget 250mA fits within TLV75533PDBVR 500mA. |
| PASS | mcu | MCU ESP32-C3-MINI-1 exists in the library. |
| PASS | sensors | 1 sensor entry(ies) declared. |
| PASS | sensor-part | Sensor part SHT31-DIS exists in the library. |
| PASS | sensor-interface | Sensor SHT31-DIS uses supported i2c interface. |
| PASS | sensor-ref | Sensor ref U3 is unique. |
| PASS | radio-count | 0 radio module entry(ies) declared. |
| PASS | debug | debug.uart_header is boolean. |
| PASS | debug | debug.boot_button is boolean. |
| PASS | debug | debug.reset_button is boolean. |
| PASS | debug-uart | MCU ESP32-C3-MINI-1 exposes UART pins for debug header. |
| FAIL | debug-boot | debug.boot_button uses reserved MCU pin GPIO9. |
| PASS | rf-enabled | rf.enabled=True. |
| PASS | rf-antenna | RF antenna PCB_ANT_2G4 exists in the library. |
| PASS | rf-connector | RF test connector U.FL exists in the library. |
| PASS | indicator-name | Indicator STATUS is unique. |
| PASS | indicator-gpio-format | indicators[1].gpio: pin GPIO3 matches MCU naming. |
| PASS | indicator-gpio-claim | indicators[1].gpio uses MCU pin GPIO3. |
| PASS | reserved-pins | No additional reserved_pins override provided. |
