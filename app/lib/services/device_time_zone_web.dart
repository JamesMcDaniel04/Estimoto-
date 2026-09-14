import 'dart:js_interop';

@JS('Intl.DateTimeFormat')
extension type _DateTimeFormat._(JSObject _) implements JSObject {
  external factory _DateTimeFormat();
  external _Options resolvedOptions();
}

extension type _Options._(JSObject _) implements JSObject {
  external String get timeZone;
}

Future<String?> readDeviceTimeZone() async =>
    _DateTimeFormat().resolvedOptions().timeZone;
