import 'dart:convert';

// Exact static application messages only. Never surface arbitrary provider text.
const _calendarMessages = {
  'Google Calendar is unavailable.',
  'Google Calendar connection could not be started. Try again.',
  'Google Calendar connection could not be verified. Try again.',
  'The connection session expired. Try again.',
  'This connection attempt expired or is not current.',
  'This connection attempt is not current.',
  'Connect Google Calendar first.',
  'Reconnect Google Calendar.',
  'Choose calendars to check.',
  'Calendar preferences changed. Try again.',
  'This connection attempt is no longer current.',
  'A unique authorized Calendar connection was not found.',
  'Choose calendars available to this Google account.',
  'Use the saved Calendar time zone or change Calendar preferences first.',
  'Calendar access changed. Choose new appointment times.',
  'Calendar preferences changed. Choose new appointment times.',
  'Choose one to three future appointment times.',
  'Choose appointment times within one 14-day window.',
  'A proposed time is now busy. Choose new appointment times.',
  'Appointment availability could not be verified completely.',
  'Reconnect Google Calendar before checking appointment availability.',
  'Calendar availability could not be verified. Try again.',
  'Retry is available only for a confirmed appointment.',
  'Enable confirmed appointment copies in Calendar preferences first.',
  'Calendar sync is already in progress.',
  'The previous Calendar copy cannot be verified. Review the original Google account.',
  'Reconnect the Google account that owns the existing Estimoto + calendar. A second copy will not be created.',
  'Choose a valid IANA time zone.',
  'Choose a future window within 90 days.',
  'Choose a valid window up to 14 days.',
};

String? safeCalendarError(int status, String body) {
  if (![409, 422, 503].contains(status)) return null;
  try {
    final decoded = jsonDecode(body);
    if (decoded is! Map) return null;
    final detail = decoded['detail'];
    if (detail is String && _calendarMessages.contains(detail)) return detail;
    if (status == 422 && detail is List) {
      for (final item in detail) {
        if (item is! Map || item['msg'] is! String) continue;
        final message = (item['msg'] as String).replaceFirst(
          RegExp(r'^Value error, '),
          '',
        );
        if (_calendarMessages.contains(message)) return message;
      }
    }
  } on FormatException {
    return null;
  }
  return null;
}
