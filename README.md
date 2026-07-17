# PhoneSense for Home Assistant

PhoneSense turns a spare Android phone or iPhone into a local-first Home Assistant sensor, camera, media, and control node.

[Download the latest Android APK](https://github.com/lrehmann/phonesense/releases/latest/download/PhoneSense-Android.apk)

## Install with HACS

1. In HACS, open the three-dot menu and choose **Custom repositories**.
2. Add `https://github.com/lrehmann/phonesense` with category **Integration**.
3. Open **PhoneSense**, choose **Download**, and restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration → PhoneSense**.
5. Install and open the PhoneSense app on the phone. Let it discover Home Assistant, enter or scan a long-lived access token, then choose **Next: Pair with Home Assistant**.

You can also open the repository in HACS directly:

[![Open your Home Assistant instance and add this repository to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=lrehmann&repository=phonesense&category=integration)

## Manual Home Assistant installation

Download `PhoneSense-HomeAssistant.zip` from the latest GitHub release and extract it into the root of the Home Assistant configuration directory. Confirm that the resulting path is:

```text
config/custom_components/phonesense/manifest.json
```

Restart Home Assistant, then add **PhoneSense** from **Settings → Devices & services**.

## Android app

The GitHub release includes `PhoneSense-Android.apk`, the latest Pixel-tested Android build. It is debug-signed for direct testing and sideloading, not Play Store distribution. Android may ask you to allow installation from the browser or file manager used to open it.

SHA-256 checksums are included in the release notes.

## What PhoneSense exposes

- Numeric motion, rotation, magnetometer, attitude, heading, barometer, pedometer, activity, location, battery, charging, thermal, light, proximity, sound-level, screen, storage, and network telemetry when supported by the phone.
- Per-camera stream switches, live Home Assistant camera entities, snapshots, brightness and motion analysis, local segmented recording, and hardware-discovered controls.
- Phone flashlight and iOS display as Home Assistant lights.
- Android speaker as a media player and optional continuous vibration control.
- Android Bluetooth advertisements as a Home Assistant remote Bluetooth scanner.
- Outbound authenticated communication, so the phone does not need an inbound port or port forwarding.

PhoneSense discovers capabilities from each phone. Unsupported sensors, cameras, resolutions, and controls are not created.

## Pairing and security

PhoneSense currently uses a Home Assistant long-lived access token; OAuth is disabled. The token is masked during entry, cleared from the form after pairing, and stored using Android Keystore-backed encrypted storage or iOS Keychain. The app can try HTTP and HTTPS endpoints and offers an **Allow insecure HTTP** option for installations that intentionally use cleartext connections.

Sensitive actions remain subject to the app's local permissions and arming policy. Unpairing from the app erases its locally stored credentials, queue, and encryption keys; it does not erase Home Assistant history.

## Support

Report integration or app problems in [GitHub Issues](https://github.com/lrehmann/phonesense/issues).
