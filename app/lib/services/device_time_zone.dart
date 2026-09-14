import 'calendar_time.dart';
import 'device_time_zone_native.dart'
    if (dart.library.js_interop) 'device_time_zone_web.dart'
    as platform;

/// Only a named device zone is a safe default; abbreviations can be ambiguous.
Future<String?> deviceTimeZone() async {
  try {
    final value = await platform.readDeviceTimeZone();
    final zone = value == 'UTC' || value == 'GMT' ? 'Etc/UTC' : value;
    return zone != null && validCalendarZone(zone) ? zone : null;
  } catch (_) {
    return null;
  }
}
