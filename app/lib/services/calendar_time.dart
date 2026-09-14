import 'package:timezone/data/latest.dart' as data;
import 'package:timezone/timezone.dart' as tz;
import '../data/pending_request_store.dart';
import '../data/repository.dart';
import '../domain/models.dart';

bool _initialized = false;
const commonCalendarZones = [
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Phoenix',
  'America/Los_Angeles',
  'America/Anchorage',
  'Pacific/Honolulu',
  'Etc/UTC',
];

tz.Location calendarLocation(String name) {
  if (!_initialized) {
    data.initializeTimeZones();
    _initialized = true;
  }
  // Require a named IANA region; never infer a zone from a device abbreviation.
  if (!name.contains('/')) {
    throw const FormatException('Use an IANA time zone.');
  }
  return tz.getLocation(name);
}

bool validCalendarZone(String name) {
  try {
    calendarLocation(name);
    return true;
  } catch (_) {
    return false;
  }
}

DateTime calendarInstant(String value) {
  if (!RegExp(r'(Z|[+-]\d{2}:\d{2})$').hasMatch(value)) {
    throw const FormatException('An appointment needs an offset-aware time.');
  }
  return DateTime.parse(value).toUtc();
}

String calendarSlotLabel(String value, String timeZone) {
  try {
    final local = tz.TZDateTime.from(
      calendarInstant(value),
      calendarLocation(timeZone),
    );
    final hour = local.hour % 12 == 0 ? 12 : local.hour % 12;
    final minutes = local.timeZoneOffset.inMinutes.abs();
    final offset =
        '${local.timeZoneOffset.isNegative ? '-' : '+'}${(minutes ~/ 60).toString().padLeft(2, '0')}:${(minutes % 60).toString().padLeft(2, '0')}';
    const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    return '${days[local.weekday - 1]}, ${local.month}/${local.day}/${local.year} at $hour:${local.minute.toString().padLeft(2, '0')} ${local.hour >= 12 ? 'PM' : 'AM'} ($timeZone, UTC$offset)';
  } catch (_) {
    // Preserve the original qualified instant rather than silently using the device zone.
    return '$value (time zone unavailable)';
  }
}

Json calendarAvailabilityBody({
  required DateTime date,
  required int days,
  required String timeZone,
  required int duration,
  required int dayStart,
  required int dayEnd,
}) {
  final location = calendarLocation(timeZone);
  final start = tz.TZDateTime(location, date.year, date.month, date.day);
  final localEnd = tz.TZDateTime(
    location,
    date.year,
    date.month,
    date.day + days,
  ).toUtc();
  final limit = start.toUtc().add(const Duration(days: 14));
  final end = localEnd.isAfter(limit) ? limit : localEnd;
  return {
    'time_min': start.toUtc().toIso8601String(),
    'time_max': end.toUtc().toIso8601String(),
    'duration_minutes': duration,
    'time_zone': timeZone,
    'day_start_hour': dayStart,
    'day_end_hour': dayEnd,
  };
}

class CalendarSelection {
  CalendarSelection._(
    this.timeZone,
    this.duration,
    this.generation,
    this.checkedAt,
    this.slots,
    this.sample,
  );
  factory CalendarSelection.fromResponse(
    Json response,
    List<Json> selected, {
    bool sample = false,
  }) {
    final zone = textOf(response, 'time_zone');
    final duration = intOf(response, 'duration_minutes');
    final generation = response['generation'];
    final candidates = rowsOf(response, 'slots');
    if (!validCalendarZone(zone) ||
        duration < 30 ||
        duration > 480 ||
        generation is! int ||
        generation < 0 ||
        selected.isEmpty ||
        selected.length > 3 ||
        selected.map((s) => s['start']).toSet().length != selected.length) {
      throw const PlusApiException('Choose available times again.');
    }
    for (final slot in selected) {
      if (!candidates.any(
            (s) => s['start'] == slot['start'] && s['end'] == slot['end'],
          ) ||
          calendarInstant(
                textOf(slot, 'end'),
              ).difference(calendarInstant(textOf(slot, 'start'))).inMinutes !=
              duration) {
        throw const PlusApiException('Choose available times again.');
      }
    }
    return CalendarSelection._(
      zone,
      duration,
      generation,
      textOf(response, 'checked_at'),
      List<Json>.unmodifiable(selected.map(freezeJson)),
      sample,
    );
  }
  final String timeZone, checkedAt;
  final int duration, generation;
  final List<Json> slots;
  final bool sample;
  List<String> get starts =>
      List<String>.unmodifiable(slots.map((s) => textOf(s, 'start')));
  Json get requestFields => freezeJson({
    'calendar_check': !sample,
    'duration_minutes': duration,
    if (!sample) 'calendar_generation': generation,
    'proposed_slots': starts,
  });
  String get label =>
      starts.map((s) => calendarSlotLabel(s, timeZone)).join('\n\n');
  String get preferredTime =>
      '$duration min; $timeZone; ${starts.map((s) => calendarInstant(s).toIso8601String()).join(', ')}';
}

String calendarSyncLabel(String status) => switch (status) {
  'pending' => 'Google Calendar copy pending',
  'synced' => 'Copied to Google Calendar',
  'conflict' => 'Google Calendar conflict',
  'reconnect_required' => 'Reconnect Google Calendar',
  'attention_needed' => 'Google Calendar copy needs attention',
  'removed' => 'Google Calendar copy removed',
  _ => 'Google Calendar copy not enabled',
};
