import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:timezone/timezone.dart' as tz;
import '../domain/models.dart';
import 'calendar_time.dart';
import 'device_time_zone.dart';

/// Lead times a customer can choose, in days before the due date.
const reminderLeadChoices = [1, 3, 7, 14];

/// The hour of the day, in the device's zone, when reminder alerts arrive.
const reminderAlertHour = 9;

/// iOS keeps at most 64 pending local notifications per app.
const maxScheduledReminders = 60;

class NotificationPreferences {
  const NotificationPreferences({this.enabled = false, this.leadDays = 7});
  factory NotificationPreferences.fromJson(Json value) =>
      NotificationPreferences(
        enabled: value['enabled'] == true,
        leadDays: reminderLeadChoices.contains(value['lead_days'])
            ? value['lead_days'] as int
            : 7,
      );
  final bool enabled;
  final int leadDays;
  Json toJson() => {'enabled': enabled, 'lead_days': leadDays};
  NotificationPreferences copyWith({bool? enabled, int? leadDays}) =>
      NotificationPreferences(
        enabled: enabled ?? this.enabled,
        leadDays: leadDays ?? this.leadDays,
      );
}

/// One alert to deliver: [at] is wall-clock time in the device's zone.
class PlannedNotification {
  const PlannedNotification({
    required this.id,
    required this.reminderId,
    required this.title,
    required this.body,
    required this.at,
  });
  final int id;
  final String reminderId, title, body;
  final DateTime at;
}

/// Stable 31-bit identifier so a rescheduled reminder replaces its old alert.
int notificationId(String reminderId, String kind) {
  var hash = 0x811C9DC5;
  for (final unit in utf8.encode('$kind:$reminderId')) {
    hash = ((hash ^ unit) * 0x01000193) & 0xFFFFFFFF;
  }
  return hash & 0x7FFFFFFF;
}

/// Plans a lead-day and a due-day alert for every open, dated reminder.
///
/// Alerts already in the past are dropped, nearest alerts come first, and
/// the list is capped so the platform never silently discards the rest.
List<PlannedNotification> planReminderNotifications(
  Iterable<ServiceReminder> reminders, {
  required DateTime now,
  required int leadDays,
  required String Function(String vehicleId) vehicleTitle,
}) {
  final planned = <PlannedNotification>[];
  for (final reminder in reminders) {
    if (reminder.completed) continue;
    final due = DateTime.tryParse(reminder.dueDate);
    if (due == null) continue;
    final dueAt = DateTime(due.year, due.month, due.day, reminderAlertHour);
    final vehicle = vehicleTitle(reminder.vehicleId);
    final label = vehicle.isEmpty
        ? reminder.title
        : '${reminder.title} · $vehicle';
    final leadAt = dueAt.subtract(Duration(days: leadDays));
    if (leadDays > 0 && leadAt.isAfter(now)) {
      planned.add(
        PlannedNotification(
          id: notificationId(reminder.id, 'lead'),
          reminderId: reminder.id,
          title: 'Coming up in $leadDays ${leadDays == 1 ? 'day' : 'days'}',
          body: '$label is due ${_dateLabel(dueAt)}.',
          at: leadAt,
        ),
      );
    }
    if (dueAt.isAfter(now)) {
      planned.add(
        PlannedNotification(
          id: notificationId(reminder.id, 'due'),
          reminderId: reminder.id,
          title: 'Due today',
          body: '$label is due today. Open your garage to mark it done.',
          at: dueAt,
        ),
      );
    }
  }
  planned.sort((a, b) => a.at.compareTo(b.at));
  return planned.take(maxScheduledReminders).toList();
}

String _dateLabel(DateTime value) {
  const months = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ];
  return '${months[value.month - 1]} ${value.day}';
}

/// Delivers garage reminders as notifications on this device.
///
/// Reminders are scheduled locally from the customer's own saved data, so no
/// server, push token or third-party project is involved and nothing about
/// the customer's vehicles leaves the device.
abstract class ReminderNotifier {
  /// Whether this platform can show scheduled notifications at all.
  bool get supported;
  Future<NotificationPreferences> preferences();
  Future<void> savePreferences(NotificationPreferences value);

  /// Asks the system for permission; returns whether alerts may be shown.
  Future<bool> requestPermission();

  /// Replaces every scheduled alert with the plan for [snapshot].
  Future<void> sync(PlusSnapshot snapshot);

  /// Removes every scheduled alert, for sign-out.
  Future<void> clear();
}

/// Web and demo sessions: preferences live in memory and nothing is shown.
class NoReminderNotifier extends ReminderNotifier {
  NotificationPreferences _preferences = const NotificationPreferences();
  @override
  bool get supported => false;
  @override
  Future<NotificationPreferences> preferences() async => _preferences;
  @override
  Future<void> savePreferences(NotificationPreferences value) async =>
      _preferences = value;
  @override
  Future<bool> requestPermission() async => false;
  @override
  Future<void> sync(PlusSnapshot snapshot) async {}
  @override
  Future<void> clear() async {}
}

/// Records what would be scheduled; used by tests and the demo.
class MemoryReminderNotifier extends ReminderNotifier {
  MemoryReminderNotifier({this.granted = true, DateTime Function()? clock})
    : clock = clock ?? DateTime.now;
  bool granted;
  final DateTime Function() clock;
  NotificationPreferences _preferences = const NotificationPreferences();
  List<PlannedNotification> scheduled = const [];
  int syncs = 0, clears = 0, permissionRequests = 0;
  @override
  bool get supported => true;
  @override
  Future<NotificationPreferences> preferences() async => _preferences;
  @override
  Future<void> savePreferences(NotificationPreferences value) async =>
      _preferences = value;
  @override
  Future<bool> requestPermission() async {
    permissionRequests++;
    return granted;
  }

  @override
  Future<void> sync(PlusSnapshot snapshot) async {
    syncs++;
    scheduled = _preferences.enabled && granted
        ? planReminderNotifications(
            snapshot.reminders,
            now: clock(),
            leadDays: _preferences.leadDays,
            vehicleTitle: (id) => snapshot.vehicle(id)?.title ?? '',
          )
        : const [];
  }

  @override
  Future<void> clear() async {
    clears++;
    scheduled = const [];
  }
}

/// Native iOS and Android delivery through the platform notification center.
class LocalReminderNotifier extends ReminderNotifier {
  LocalReminderNotifier();
  static const _storage = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
  );
  static const _key = 'estimoto_plus_notifications';
  static const _channel = AndroidNotificationDetails(
    'service_reminders',
    'Service reminders',
    channelDescription: 'Reminders you saved in your garage.',
    importance: Importance.defaultImportance,
    priority: Priority.defaultPriority,
  );
  final _plugin = FlutterLocalNotificationsPlugin();
  bool _initialized = false;

  @override
  bool get supported => !kIsWeb;

  Future<void> _initialize() async {
    if (_initialized) return;
    await _plugin.initialize(
      settings: const InitializationSettings(
        android: AndroidInitializationSettings('@mipmap/ic_launcher'),
        iOS: DarwinInitializationSettings(
          requestAlertPermission: false,
          requestBadgePermission: false,
          requestSoundPermission: false,
        ),
      ),
    );
    _initialized = true;
  }

  @override
  Future<NotificationPreferences> preferences() async {
    try {
      final raw = await _storage.read(key: _key);
      if (raw != null) {
        return NotificationPreferences.fromJson(jsonDecode(raw) as Json);
      }
    } catch (_) {}
    return const NotificationPreferences();
  }

  @override
  Future<void> savePreferences(NotificationPreferences value) =>
      _storage.write(key: _key, value: jsonEncode(value.toJson()));

  @override
  Future<bool> requestPermission() async {
    if (!supported) return false;
    await _initialize();
    final android = _plugin
        .resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin
        >();
    if (android != null) {
      return await android.requestNotificationsPermission() ?? false;
    }
    final ios = _plugin
        .resolvePlatformSpecificImplementation<
          IOSFlutterLocalNotificationsPlugin
        >();
    if (ios != null) {
      return await ios.requestPermissions(
            alert: true,
            badge: true,
            sound: true,
          ) ??
          false;
    }
    return false;
  }

  @override
  Future<void> sync(PlusSnapshot snapshot) async {
    if (!supported) return;
    final settings = await preferences();
    await _initialize();
    await _plugin.cancelAll();
    if (!settings.enabled) return;
    final zone = await deviceTimeZone();
    final location = zone == null ? tz.local : calendarLocation(zone);
    final plan = planReminderNotifications(
      snapshot.reminders,
      now: DateTime.now(),
      leadDays: settings.leadDays,
      vehicleTitle: (id) => snapshot.vehicle(id)?.title ?? '',
    );
    for (final item in plan) {
      await _plugin.zonedSchedule(
        id: item.id,
        title: item.title,
        body: item.body,
        payload: item.reminderId,
        scheduledDate: tz.TZDateTime(
          location,
          item.at.year,
          item.at.month,
          item.at.day,
          item.at.hour,
          item.at.minute,
        ),
        notificationDetails: const NotificationDetails(
          android: _channel,
          iOS: DarwinNotificationDetails(),
        ),
        androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
      );
    }
  }

  @override
  Future<void> clear() async {
    if (!supported) return;
    await _initialize();
    await _plugin.cancelAll();
  }
}

/// The notifier for a signed-in customer on this platform.
ReminderNotifier defaultReminderNotifier() =>
    kIsWeb ? NoReminderNotifier() : LocalReminderNotifier();
