# Changelog

## 0.1.1

- Prevent camera start/stop commands from blocking the Android service main thread behind encrypted-media database work.
- Fix the resulting camera-service ANR and foreground-service crash when switching front and rear streams.
- Preserve Android 6.0/API 23 compatibility in camera capability enumeration.

## 0.1.0

- Initial HACS-compatible PhoneSense Home Assistant integration.
- Capability-driven sensor, camera, light, switch, number, select, button, media-player, and device-tracker entities.
- Outbound live camera frames and segmented recording access without inbound phone ports.
- Android remote Bluetooth scanner and numeric statistics backfill.
- Home Assistant command and configuration delivery to paired PhoneSense phones.
