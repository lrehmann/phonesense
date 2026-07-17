# Changelog

## 0.1.3

- Reflect an authenticated live camera frame immediately in Home Assistant instead of waiting for the phone's next periodic health upload.
- On iOS, atomically mark the prior lens idle when a frame proves that the single capture session has switched to the other camera.
- Preserve simultaneous camera-session state for Android devices that support concurrent streams.

## 0.1.2

- Add capability-driven iOS telemetry for magnetometer, device motion and attitude, barometer, pedometer, motion activity, proximity, orientation, heading, screen brightness, storage, low-power mode, and audio levels.
- Add per-camera iOS brightness, motion, person-detection, and occupancy telemetry when the camera and operating system support it.
- Generate Home Assistant enable switches from each phone's reported capabilities and remove duplicate module-level switches.
- Keep each supported camera's stream switch available independently so front and rear camera controls are clear.
- Refresh Home Assistant entities automatically when a phone uploads a changed capability document.

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
