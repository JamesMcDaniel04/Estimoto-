import 'package:flutter/material.dart';
import '../domain/models.dart';
import '../theme.dart';

/// How pressing a reminder is, derived from its due date and mileage.
enum ReminderUrgency { overdue, soon, later }

/// A short, human label for when a reminder is due, plus its urgency.
///
/// Dates are compared by calendar day in the device's local time. Mileage
/// is compared to the vehicle's saved odometer reading when one is known.
/// The label is empty when the reminder has no usable due information.
class ReminderDue {
  const ReminderDue(this.label, this.urgency);
  final String label;
  final ReminderUrgency urgency;

  static const _soonDays = 14;
  static const _soonMiles = 500;

  Color get color => switch (urgency) {
    ReminderUrgency.overdue => const Color(0xFFB3261E),
    ReminderUrgency.soon => const Color(0xFFB26A00),
    ReminderUrgency.later => PlusColors.blue,
  };

  static ReminderDue of(
    ServiceReminder reminder, {
    required DateTime now,
    int? vehicleMileage,
  }) {
    final today = DateTime(now.year, now.month, now.day);
    final due = DateTime.tryParse(reminder.dueDate);
    ReminderDue? byDate;
    if (due != null) {
      final day = DateTime(due.year, due.month, due.day);
      final days = day.difference(today).inDays;
      byDate = switch (days) {
        -1 => const ReminderDue('Due yesterday', ReminderUrgency.overdue),
        < 0 => ReminderDue('${-days} days overdue', ReminderUrgency.overdue),
        0 => const ReminderDue('Due today', ReminderUrgency.soon),
        1 => const ReminderDue('Due tomorrow', ReminderUrgency.soon),
        <= _soonDays => ReminderDue('Due in $days days', ReminderUrgency.soon),
        _ => ReminderDue('Due in $days days', ReminderUrgency.later),
      };
    }
    ReminderDue? byMileage;
    final dueMileage = reminder.dueMileage;
    if (dueMileage != null && vehicleMileage != null) {
      final miles = dueMileage - vehicleMileage;
      byMileage = miles <= 0
          ? const ReminderDue('Past due mileage', ReminderUrgency.overdue)
          : miles <= _soonMiles
          ? ReminderDue('Due in $miles miles', ReminderUrgency.soon)
          : ReminderDue('Due in $miles miles', ReminderUrgency.later);
    }
    if (byDate == null) {
      return byMileage ?? const ReminderDue('', ReminderUrgency.later);
    }
    if (byMileage == null) return byDate;
    // Whichever comes first wins; a reminder is due at the earlier of the two.
    return byMileage.urgency.index < byDate.urgency.index ? byMileage : byDate;
  }
}
