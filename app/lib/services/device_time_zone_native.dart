import 'package:flutter/services.dart';

Future<String?> readDeviceTimeZone() => const MethodChannel(
  'io.estimoto.plus/device_time_zone',
).invokeMethod<String>('getTimeZone');
