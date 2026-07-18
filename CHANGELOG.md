# Changelog

## 0.1.15

- Make capability-backed sensors unavailable until the phone supplies a real value, including literal `unknown`, `unavailable`, `none`, or `null` payloads.
- Preserve requested capability switches and effective configuration while older phone builds are upgraded.
- Add a lightweight freshness tick so an offline phone transitions restored entity values to unavailable without network polling.
- Harden camera-control selectors so each lens exposes only supported choices and stale selections recover cleanly.
- Keep empty telemetry queues numeric at zero rather than ambiguous.

## 0.1.9

- Keep camera and microphone activity entities tied to current runtime state instead of stale telemetry.
- Preserve first-frame and recovery camera availability while supporting Android concurrent sessions and iOS exclusive front/rear handoff.
- Add per-camera snapshot, recording, clip-length, and hardware-discovered control entities with clearer names and capability gating.
- Expose iOS per-sensor switches, screen light controls, extended numeric telemetry, and stable camera analytics.
- Add Android media-browser recording support, Bluetooth health diagnostics, and truthful unavailable sound-level handling.
- Harden durable sequence acknowledgement, queue-floor recovery, diagnostic redaction, and instance-bound command delivery.

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
