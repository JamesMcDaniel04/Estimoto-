import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/domain/models.dart';
import 'package:estimoto_plus/services/reminder_due.dart';

void main() {
  final now = DateTime(2026, 9, 15, 10, 30);
  ServiceReminder reminder({String date = '', int? mileage}) =>
      ServiceReminder.fromJson({
        'id': 'r',
        'title': 'Oil',
        'due_date': date,
        'due_mileage': mileage,
      });

  test('date urgency is computed by calendar day', () {
    expect(
      ReminderDue.of(reminder(date: '2026-09-15'), now: now).label,
      'Due today',
    );
    expect(
      ReminderDue.of(reminder(date: '2026-09-16'), now: now).label,
      'Due tomorrow',
    );
    final soon = ReminderDue.of(reminder(date: '2026-09-25'), now: now);
    expect(soon.label, 'Due in 10 days');
    expect(soon.urgency, ReminderUrgency.soon);
    final later = ReminderDue.of(reminder(date: '2026-11-01'), now: now);
    expect(later.urgency, ReminderUrgency.later);
    expect(
      ReminderDue.of(reminder(date: '2026-09-14'), now: now).label,
      'Due yesterday',
    );
    final overdue = ReminderDue.of(reminder(date: '2026-09-01'), now: now);
    expect(overdue.label, '14 days overdue');
    expect(overdue.urgency, ReminderUrgency.overdue);
  });

  test('mileage urgency uses the saved odometer', () {
    expect(ReminderDue.of(reminder(mileage: 30000), now: now).label, isEmpty);
    final soon = ReminderDue.of(
      reminder(mileage: 30000),
      now: now,
      vehicleMileage: 29800,
    );
    expect(soon.label, 'Due in 200 miles');
    expect(soon.urgency, ReminderUrgency.soon);
    final past = ReminderDue.of(
      reminder(mileage: 30000),
      now: now,
      vehicleMileage: 30500,
    );
    expect(past.label, 'Past due mileage');
    expect(past.urgency, ReminderUrgency.overdue);
  });

  test('the earlier of date and mileage wins', () {
    final due = ReminderDue.of(
      reminder(date: '2026-12-01', mileage: 30000),
      now: now,
      vehicleMileage: 30001,
    );
    expect(due.label, 'Past due mileage');
    final byDate = ReminderDue.of(
      reminder(date: '2026-09-10', mileage: 30000),
      now: now,
      vehicleMileage: 20000,
    );
    expect(byDate.label, '5 days overdue');
  });
}
