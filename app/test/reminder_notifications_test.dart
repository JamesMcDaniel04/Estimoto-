import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/data/demo_repository.dart';
import 'package:estimoto_plus/domain/models.dart';
import 'package:estimoto_plus/screens/settings_screen.dart';
import 'package:estimoto_plus/services/reminder_notifications.dart';
import 'package:estimoto_plus/state/plus_controller.dart';
import 'package:estimoto_plus/theme.dart';

ServiceReminder _reminder(String id, String date, {bool completed = false}) =>
    ServiceReminder.fromJson({
      'id': id,
      'vehicle_id': 'v1',
      'title': 'Oil change',
      'due_date': date,
      'completed': completed,
    });

class _LiveDemo extends DemoPlusRepository {
  @override
  bool get isDemo => false;
  @override
  Future<PlusSnapshot> bootstrap() async {
    final demo = await super.bootstrap();
    return PlusSnapshot.fromJson({
      'profile': demo.profile.json,
      'vehicles': demo.vehicles.map((v) => v.json).toList(),
      'reminders': demo.reminders.map((r) => r.json).toList(),
      'capabilities': {'demo': false},
    });
  }
}

void main() {
  final now = DateTime(2026, 9, 15, 12);

  test('a dated reminder gets a lead alert and a due-day alert at 9 AM', () {
    final plan = planReminderNotifications(
      [_reminder('r1', '2026-09-25')],
      now: now,
      leadDays: 7,
      vehicleTitle: (_) => '2022 Audi Q5',
    );
    expect(plan.map((p) => p.at), [
      DateTime(2026, 9, 18, 9),
      DateTime(2026, 9, 25, 9),
    ]);
    expect(plan.first.title, 'Coming up in 7 days');
    expect(plan.first.body, 'Oil change · 2022 Audi Q5 is due Sep 25.');
    expect(plan.last.title, 'Due today');
    expect(plan.first.id, isNot(plan.last.id));
    expect(plan.first.id, notificationId('r1', 'lead'));
  });

  test('past alerts, completed and undated reminders are skipped', () {
    final plan = planReminderNotifications(
      [
        _reminder('past', '2026-09-10'),
        _reminder('soon', '2026-09-17'),
        _reminder('done', '2026-10-01', completed: true),
        _reminder('mileage-only', ''),
      ],
      now: now,
      leadDays: 7,
      vehicleTitle: (_) => '',
    );
    expect(plan.map((p) => p.reminderId), ['soon']);
    expect(plan.single.title, 'Due today');
    expect(plan.single.body, startsWith('Oil change is due today.'));
  });

  test('identifiers are stable and positive', () {
    expect(notificationId('abc', 'lead'), notificationId('abc', 'lead'));
    expect(notificationId('abc', 'lead'), greaterThan(0));
    expect(notificationId('abc', 'due'), isNot(notificationId('abd', 'due')));
  });

  test('the plan is capped and nearest-first', () {
    final plan = planReminderNotifications(
      [
        for (var i = 0; i < 80; i++)
          _reminder(
            'r$i',
            '2027-01-${(i % 28 + 1).toString().padLeft(2, '0')}',
          ),
      ],
      now: now,
      leadDays: 1,
      vehicleTitle: (_) => '',
    );
    expect(plan, hasLength(maxScheduledReminders));
    for (var i = 1; i < plan.length; i++) {
      expect(plan[i].at.isBefore(plan[i - 1].at), isFalse);
    }
  });

  test('a refresh re-plans alerts and disposal clears them', () async {
    final notifier = MemoryReminderNotifier(clock: () => now);
    await notifier.savePreferences(
      const NotificationPreferences(enabled: true),
    );
    final controller = PlusController(_LiveDemo(), notifier: notifier);
    await controller.refresh();
    expect(notifier.syncs, 1);
    expect(notifier.scheduled, isNotEmpty);
    controller.dispose();
    await Future<void>.delayed(Duration.zero);
    expect(notifier.clears, 1);
    expect(notifier.scheduled, isEmpty);
  });

  test('the demo never schedules alerts', () async {
    final notifier = MemoryReminderNotifier();
    await notifier.savePreferences(
      const NotificationPreferences(enabled: true),
    );
    final controller = PlusController(DemoPlusRepository(), notifier: notifier);
    await controller.refresh();
    expect(notifier.syncs, 0);
    controller.dispose();
    await Future<void>.delayed(Duration.zero);
    expect(notifier.clears, 0);
  });

  group('settings', () {
    Future<PlusController> mount(
      WidgetTester tester,
      MemoryReminderNotifier notifier,
    ) async {
      final controller = PlusController(_LiveDemo(), notifier: notifier);
      await controller.refresh();
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        MaterialApp(
          theme: plusTheme(),
          home: SettingsScreen(controller: controller),
        ),
      );
      await tester.pumpAndSettle();
      return controller;
    }

    testWidgets('turning alerts on asks permission, saves and schedules', (
      tester,
    ) async {
      final notifier = MemoryReminderNotifier();
      await mount(tester, notifier);
      final toggle = find.byKey(const Key('settings-reminder-alerts'));
      await tester.ensureVisible(toggle);
      expect(tester.widget<SwitchListTile>(toggle).value, isFalse);
      await tester.tap(toggle);
      await tester.pumpAndSettle();
      expect(notifier.permissionRequests, 1);
      expect((await notifier.preferences()).enabled, isTrue);
      expect(notifier.scheduled, isNotEmpty);
      expect(find.byKey(const Key('settings-reminder-lead')), findsOneWidget);
      await tester.tap(find.text('3 days'));
      await tester.pumpAndSettle();
      expect((await notifier.preferences()).leadDays, 3);
      expect(notifier.scheduled.first.title, 'Coming up in 3 days');
    });

    testWidgets('a denied permission leaves alerts off with guidance', (
      tester,
    ) async {
      final notifier = MemoryReminderNotifier(granted: false);
      await mount(tester, notifier);
      final toggle = find.byKey(const Key('settings-reminder-alerts'));
      await tester.ensureVisible(toggle);
      await tester.tap(toggle);
      await tester.pumpAndSettle();
      expect((await notifier.preferences()).enabled, isFalse);
      expect(tester.widget<SwitchListTile>(toggle).value, isFalse);
      expect(find.textContaining('device settings'), findsOneWidget);
    });

    testWidgets('the demo explains that alerts need a signed-in phone', (
      tester,
    ) async {
      final controller = PlusController(
        DemoPlusRepository(),
        notifier: MemoryReminderNotifier(),
      );
      await controller.refresh();
      await tester.pumpWidget(
        MaterialApp(
          theme: plusTheme(),
          home: SettingsScreen(controller: controller),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('settings-reminder-alerts')), findsNothing);
      expect(
        find.textContaining('never schedules notifications'),
        findsOneWidget,
      );
    });
  });
}
