import 'package:flutter/material.dart';
import 'package:timezone/timezone.dart' as tz;
import '../data/repository.dart';
import '../domain/models.dart';
import '../screens/calendar_screen.dart';
import '../services/calendar_time.dart';
import '../state/plus_controller.dart';
import 'common.dart';
import 'workspace_widgets.dart';

Future<CalendarSelection?> pickCalendarSlots(
  BuildContext context,
  PlusController controller,
) => Navigator.of(context).push<CalendarSelection>(
  MaterialPageRoute(builder: (_) => CalendarSlotPicker(controller: controller)),
);

class CalendarSlotPicker extends StatefulWidget {
  const CalendarSlotPicker({
    super.key,
    required this.controller,
    this.now = DateTime.now,
  });
  final PlusController controller;
  final DateTime Function() now;
  @override
  State<CalendarSlotPicker> createState() => _CalendarSlotPickerState();
}

class _CalendarSlotPickerState extends WorkspaceState<CalendarSlotPicker>
    with WidgetsBindingObserver {
  @override
  PlusController get controller => widget.controller;
  Json? status, result;
  final selected = <int>{};
  DateTime? startDate;
  int days = 7, duration = 60, dayStart = 9, dayEnd = 17, epoch = 0;
  bool loading = true;
  String get timeZone => textOf(status ?? {}, 'time_zone', 'Etc/UTC');
  bool get ready =>
      status?['connected'] == true &&
      stringRows(status!, 'selected_calendar_ids').isNotEmpty &&
      validCalendarZone(timeZone);
  bool valid(int run) => active && run == epoch;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    load();
  }

  @override
  void dispose() {
    epoch++;
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && active) load();
  }

  void clearChoices() {
    ++epoch;
    result = null;
    selected.clear();
    error = null;
    busy = false;
  }

  Future<void> load() async {
    if (!active) return;
    setState(() {
      clearChoices();
      loading = true;
    });
    final run = epoch;
    try {
      final value = await controller.repository.getCalendarStatus();
      if (!valid(run)) return;
      setState(() {
        if (value['time_zone'] != status?['time_zone']) startDate = null;
        status = value;
        if (validCalendarZone(timeZone)) {
          final (first, last) = dateBounds();
          startDate = boundedDate(first, last);
        }
      });
    } catch (e) {
      if (valid(run)) {
        setState(() {
          status = null;
          error = PlusController.readableError(e);
        });
      }
    } finally {
      if (valid(run)) {
        setState(() {
          loading = false;
        });
      }
    }
  }

  (DateTime, DateTime) dateBounds() {
    final today = tz.TZDateTime.from(widget.now(), calendarLocation(timeZone));
    return (
      DateTime(today.year, today.month, today.day + 1),
      DateTime(today.year, today.month, today.day + 89),
    );
  }

  DateTime boundedDate(DateTime first, DateTime last) {
    final value = startDate;
    if (value == null || value.isBefore(first)) return first;
    return value.isAfter(last) ? last : value;
  }

  Future<void> date() async {
    if (!active || !ready || busy || loading) return;
    // A foregrounded picker can cross midnight without a resume event.
    final (first, last) = dateBounds();
    final initial = boundedDate(first, last);
    if (initial != startDate) {
      setState(() {
        clearChoices();
        startDate = initial;
      });
    }
    final run = epoch;
    final value = await showDatePicker(
      context: context,
      initialDate: initial,
      firstDate: first,
      lastDate: last,
    );
    if (value == null || !valid(run)) return;
    setState(() {
      clearChoices();
      startDate = value;
    });
  }

  Future<void> findTimes() async {
    if (!active || !ready || busy || loading || startDate == null) return;
    setState(clearChoices);
    final run = epoch;
    if (dayEnd <= dayStart || duration > (dayEnd - dayStart) * 60) {
      setState(() {
        error = 'Choose business hours that fit the full appointment duration.';
      });
      return;
    }
    final body = calendarAvailabilityBody(
      date: startDate!,
      days: days,
      timeZone: timeZone,
      duration: duration,
      dayStart: dayStart,
      dayEnd: dayEnd,
    );
    final start = calendarInstant(body['time_min'] as String),
        end = calendarInstant(body['time_max'] as String);
    final now = widget.now().toUtc();
    if (!start.isAfter(now.add(const Duration(hours: 1))) ||
        end.isAfter(now.add(const Duration(days: 90))) ||
        end.difference(start) > const Duration(days: 14)) {
      setState(() {
        error = 'Choose a future window up to 14 days, ending within 90 days.';
      });
      return;
    }
    setState(() {
      busy = true;
    });
    try {
      final value = await controller.repository.findCalendarAvailability(body);
      if (!valid(run)) return;
      if (value['generation'] != status?['generation'] ||
          value['time_zone'] != timeZone ||
          value['duration_minutes'] != duration) {
        throw const PlusApiException(
          'Calendar preferences changed. Refresh and find times again.',
        );
      }
      final rows = rowsOf(value, 'slots');
      if (rows.length > 12) {
        throw const PlusApiException(
          'Available times could not be read. Try again.',
        );
      }
      // Validate the shape/interval before it can become a selectable offer.
      for (final row in rows) {
        CalendarSelection.fromResponse(value, [row], sample: controller.isDemo);
      }
      setState(() {
        result = value;
      });
    } catch (e) {
      if (valid(run)) {
        setState(() {
          error = PlusController.readableError(e);
        });
      }
    } finally {
      if (valid(run)) {
        setState(() {
          busy = false;
        });
      }
    }
  }

  Future<void> useTimes() async {
    if (!active || busy || result == null || selected.isEmpty) return;
    final run = epoch;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final latest = await controller.repository.getCalendarStatus();
      if (!valid(run)) return;
      if (latest['connected'] != true ||
          latest['generation'] != result!['generation'] ||
          latest['time_zone'] != result!['time_zone']) {
        setState(() {
          clearChoices();
          status = latest;
          error = 'Calendar preferences changed. Find available times again.';
        });
        return;
      }
      final rows = rowsOf(result!, 'slots');
      final choice = CalendarSelection.fromResponse(
        result!,
        (selected.toList()..sort()).map((i) => rows[i]).toList(),
        sample: controller.isDemo,
      );
      if (!mounted || !valid(run)) return;
      Navigator.of(context).pop(choice);
    } catch (e) {
      if (valid(run)) {
        setState(() {
          error = PlusController.readableError(e);
        });
      }
    } finally {
      if (valid(run)) {
        setState(() {
          busy = false;
        });
      }
    }
  }

  Widget numberChoice(
    String key,
    String label,
    int value,
    List<int> values,
    ValueChanged<int> change,
    String Function(int) display,
  ) => Padding(
    padding: const EdgeInsets.only(bottom: 16),
    child: DropdownButtonFormField<int>(
      key: ValueKey(key),
      initialValue: value,
      isExpanded: true,
      decoration: InputDecoration(labelText: label),
      items: values
          .map((v) => DropdownMenuItem(value: v, child: Text(display(v))))
          .toList(),
      onChanged: busy || loading
          ? null
          : (v) => setState(() {
              clearChoices();
              change(v!);
            }),
    ),
  );

  @override
  Widget build(BuildContext context) {
    if (!current) return unavailable;
    final rows = result == null ? <Json>[] : rowsOf(result!, 'slots');
    return Scaffold(
      appBar: AppBar(title: const Text('Find available times')),
      body: PageBody(
        children: [
          const PageHeading(
            'Room in your schedule.',
            'Choose times to offer. Your shop still needs to confirm.',
          ),
          if (controller.isDemo)
            const Text(
              'Sample availability • fictional times, with no Google check.',
            ),
          if (loading) const LinearProgressIndicator(),
          if (!loading && !ready) ...[
            Text(switch (status?['status']) {
              'unavailable' =>
                'Google Calendar is not available yet. You can return and offer a time manually.',
              'reconnect_required' =>
                'Reconnect Google Calendar before checking times.',
              'connecting' =>
                'Finish connecting Google Calendar, then choose the calendars that make you busy.',
              _ =>
                'Connect Google Calendar and choose calendars to check, or return to offer times manually.',
            }),
          ],
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: busy
                ? null
                : () async {
                    await openCalendar(context, controller);
                    if (active) load();
                  },
            icon: const Icon(Icons.settings_outlined),
            label: const Text('Calendar settings'),
          ),
          if (ready) ...[
            const SizedBox(height: 12),
            Text(
              'All times use $timeZone. Your device time zone will not change these offers.',
            ),
            const SizedBox(height: 20),
            OutlinedButton.icon(
              key: const Key('calendar-start-date'),
              onPressed: busy ? null : date,
              icon: const Icon(Icons.date_range_outlined),
              label: Text(
                'Starting ${startDate!.month}/${startDate!.day}/${startDate!.year}',
              ),
            ),
            const SizedBox(height: 16),
            numberChoice(
              'calendar-days',
              'Search window',
              days,
              [1, 3, 5, 7, 10, 14],
              (v) => days = v,
              (v) => '$v ${v == 1 ? 'day' : 'days'}',
            ),
            numberChoice(
              'calendar-duration',
              'Appointment duration',
              duration,
              [30, 60, 90, 120, 180, 240, 360, 480],
              (v) => duration = v,
              (v) => '$v minutes',
            ),
            const Text(
              'This is the time you want to reserve, not an estimate of how long the repair will take.',
            ),
            const SizedBox(height: 16),
            numberChoice(
              'calendar-day-start',
              'Weekday start hour',
              dayStart,
              List.generate(24, (i) => i),
              (v) => dayStart = v,
              (v) => '${v.toString().padLeft(2, '0')}:00',
            ),
            numberChoice(
              'calendar-day-end',
              'Weekday end hour',
              dayEnd,
              List.generate(24, (i) => i + 1),
              (v) => dayEnd = v,
              (v) => '${v.toString().padLeft(2, '0')}:00',
            ),
            BusyButton(
              key: const Key('calendar-find-times'),
              busy: busy,
              label: controller.isDemo
                  ? 'Find sample times'
                  : 'Find available times',
              onPressed: findTimes,
              icon: Icons.search,
            ),
          ],
          if (error != null) WorkspaceError(error!),
          if (result != null) ...[
            const SectionHeading('Choose up to three times'),
            Text(
              controller.isDemo
                  ? 'Fictional suggestions for trying the review flow.'
                  : 'Free when checked. Availability is checked again before the request is sent and confirmed.',
            ),
            if (rows.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 18),
                child: Text(
                  'No times fit this window. Try another date range, duration or business hours.',
                ),
              ),
            for (final (index, slot) in rows.indexed)
              CheckboxListTile(
                key: ValueKey('calendar-slot-$index'),
                controlAffinity: ListTileControlAffinity.leading,
                contentPadding: EdgeInsets.zero,
                value: selected.contains(index),
                title: Text(calendarSlotLabel(textOf(slot, 'start'), timeZone)),
                subtitle: Text(
                  'Ends ${calendarSlotLabel(textOf(slot, 'end'), timeZone)}',
                ),
                onChanged: busy
                    ? null
                    : (value) => setState(() {
                        if (value == true && selected.length >= 3) {
                          error = 'Choose up to three times.';
                          return;
                        }
                        if (value == true) {
                          selected.add(index);
                        } else {
                          selected.remove(index);
                        }
                        error = null;
                      }),
              ),
            if (selected.isNotEmpty) ...[
              const SizedBox(height: 12),
              BusyButton(
                key: const Key('calendar-use-times'),
                busy: busy,
                label:
                    'Use ${selected.length} ${selected.length == 1 ? 'time' : 'times'}',
                onPressed: useTimes,
                icon: Icons.check,
              ),
            ],
          ],
        ],
      ),
    );
  }
}
