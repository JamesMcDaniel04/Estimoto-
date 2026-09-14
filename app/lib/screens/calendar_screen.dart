import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../data/repository.dart';
import '../domain/models.dart';
import '../services/calendar_time.dart';
import '../services/device_time_zone.dart';
import '../state/plus_controller.dart';
import '../widgets/common.dart';
import '../widgets/workspace_widgets.dart';

Future<void> openCalendar(BuildContext context, PlusController controller) =>
    Navigator.of(context).push<void>(
      MaterialPageRoute(builder: (_) => CalendarScreen(controller: controller)),
    );

Uri? calendarConnectUri(String value) {
  final uri = Uri.tryParse(value);
  if (uri == null ||
      uri.scheme != 'https' ||
      uri.host != 'connect.nango.dev' ||
      uri.userInfo.isNotEmpty ||
      uri.port != 443 ||
      uri.hasFragment) {
    return null;
  }
  return uri;
}

class CalendarScreen extends StatefulWidget {
  const CalendarScreen({super.key, required this.controller});
  final PlusController controller;
  @override
  State<CalendarScreen> createState() => _CalendarScreenState();
}

class _CalendarScreenState extends WorkspaceState<CalendarScreen>
    with WidgetsBindingObserver {
  @override
  PlusController get controller => widget.controller;
  Json? status;
  List<Json> calendars = [];
  final selected = <String>{};
  final zone = TextEditingController();
  String? localZone;
  bool sync = false, loading = true, dirty = false, resumePending = false;
  int epoch = 0;
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
    zone.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed || !active) return;
    if (busy || loading) {
      resumePending = true;
    } else {
      load();
    }
  }

  void finish(int run) {
    if (!valid(run)) return;
    setState(() {
      busy = false;
      loading = false;
    });
    if (resumePending) {
      resumePending = false;
      load();
    }
  }

  void applyStatus(Json value, {List<Json>? rows, bool reset = false}) {
    if (reset || !dirty || value['generation'] != status?['generation']) {
      selected
        ..clear()
        ..addAll(stringRows(value, 'selected_calendar_ids'));
      final savedZone = textOf(value, 'time_zone');
      zone.text = savedZone.isEmpty ? localZone ?? '' : savedZone;
      sync = value['sync_confirmed'] == true;
      dirty = false;
    }
    status = value;
    if (rows != null) calendars = rows;
    if (value['connected'] != true) calendars = [];
  }

  Future<void> load() async {
    if (!active || busy) return;
    final run = ++epoch;
    setState(() {
      loading = true;
      error = null;
    });
    try {
      var value = await controller.repository.getCalendarStatus();
      if (!valid(run)) return;
      if (textOf(value, 'time_zone').isEmpty && localZone == null) {
        localZone = await deviceTimeZone().timeout(
          const Duration(seconds: 2),
          onTimeout: () => null,
        );
        if (!valid(run)) return;
      }
      setState(() => applyStatus(value));
      final attempt = textOf(value, 'attempt_id');
      if (!controller.isDemo &&
          value['status'] == 'connecting' &&
          attempt.isNotEmpty) {
        value = await controller.repository.reconcileGoogleCalendar(attempt);
        if (!valid(run)) return;
        setState(() => applyStatus(value));
      }
      if (value['connected'] == true) {
        final list = await controller.repository.listGoogleCalendars();
        if (!valid(run)) return;
        setState(() => applyStatus(value, rows: rowsOf(list, 'calendars')));
      }
    } catch (e) {
      if (valid(run)) {
        setState(() {
          error = PlusController.readableError(e);
        });
      }
    } finally {
      finish(run);
    }
  }

  Future<void> connect() async {
    if (!active || busy || controller.isDemo) return;
    final run = ++epoch;
    setState(() {
      busy = true;
      loading = false;
      error = null;
      calendars = [];
      selected.clear();
    });
    try {
      final result = await controller.repository.connectGoogleCalendar();
      if (!valid(run)) return;
      final uri = calendarConnectUri(textOf(result, 'connect_link'));
      if (uri == null) {
        throw const PlusApiException(
          'The secure Google connection could not be opened. Try again.',
        );
      }
      setState(() {
        status = {
          ...?status,
          'connected': false,
          'status': 'connecting',
          'attempt_id': result['attempt_id'],
        };
      });
      final opened = await launchUrl(uri, mode: LaunchMode.externalApplication);
      if (!valid(run)) return;
      if (!opened) {
        throw const PlusApiException(
          'Your browser could not open Google consent. Try connecting again.',
        );
      }
    } catch (e) {
      if (valid(run)) {
        setState(() {
          error = PlusController.readableError(e);
        });
      }
    } finally {
      finish(run);
    }
  }

  Future<void> save() async {
    if (!active || busy || loading) return;
    if (selected.isEmpty ||
        selected.length > 10 ||
        !validCalendarZone(zone.text.trim())) {
      setState(() {
        error = selected.isEmpty || selected.length > 10
            ? 'Choose 1–10 calendars to check.'
            : 'Enter an IANA time zone, such as America/Denver.';
      });
      return;
    }
    final body = <String, dynamic>{
      'selected_calendar_ids': selected.toList()..sort(),
      'time_zone': zone.text.trim(),
      'sync_confirmed': sync,
    };
    final run = ++epoch;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final value = await controller.repository.saveCalendarPreferences(body);
      if (!mounted || !valid(run)) return;
      setState(() => applyStatus(value, reset: true));
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Calendar preferences saved.')),
      );
    } catch (e) {
      if (valid(run)) {
        setState(() {
          error = PlusController.readableError(e);
        });
      }
    } finally {
      finish(run);
    }
  }

  Future<void> disconnect() async {
    if (!active || busy) return;
    final run = ++epoch;
    setState(() {
      busy = true;
      loading = false;
      error = null;
      dirty = false;
      calendars = [];
      selected.clear();
      sync = false;
      status = {
        ...?status,
        'connected': false,
        'status': 'disconnecting',
        'attempt_id': null,
      };
    });
    try {
      await controller.repository.disconnectGoogleCalendar();
      if (!valid(run)) return;
      setState(() {
        status = {...?status, 'status': 'disconnected'};
      });
    } catch (e) {
      if (valid(run)) {
        setState(() {
          status = {...?status, 'status': 'disconnect_uncertain'};
          error = PlusController.readableError(e);
        });
      }
    } finally {
      finish(run);
    }
  }

  Future<void> retry(Json issue) async {
    if (!active || busy || loading) return;
    final run = ++epoch;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await controller.repository.retryCalendarSync({
        'source_kind': issue['source_kind'],
        'source_id': issue['source_id'],
      });
      if (!valid(run)) return;
      await controller.refresh(quiet: true);
      if (!valid(run)) return;
      resumePending = true;
    } catch (e) {
      if (valid(run)) {
        setState(() {
          error = PlusController.readableError(e);
        });
      }
    } finally {
      finish(run);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!current) return unavailable;
    final state = textOf(status ?? {}, 'status');
    final connected = status?['connected'] == true;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Calendar'),
        actions: [
          IconButton(
            tooltip: 'Refresh Calendar',
            onPressed: busy ? null : load,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: PageBody(
        children: [
          const PageHeading(
            'Google Calendar',
            'Make room for your car without overlooking your plans.',
          ),
          const Text(
            'Choose which calendars mark you busy. Estibot can help you offer open times, then you review the request and the shop confirms an appointment.',
          ),
          const SizedBox(height: 12),
          const Text(
            'Event titles, guests and other event details are not shared with Estibot or shops.',
          ),
          if (controller.isDemo) ...[
            const SizedBox(height: 16),
            const Text(
              'Sample Calendar • fictional availability only. No Google account is connected and no events are created.',
            ),
          ],
          if (loading)
            const Padding(
              padding: EdgeInsets.all(20),
              child: LinearProgressIndicator(),
            ),
          if (error != null) WorkspaceError(error!),
          if (status != null && !connected) ...[
            const SizedBox(height: 24),
            Text(switch (state) {
              'disconnecting' => 'Checking that Google access is disconnected…',
              'disconnect_uncertain' =>
                'Disconnection is not confirmed. Google access and automatic copies may still be active. Refresh or retry disconnect.',
              'unavailable' =>
                'Google Calendar connections are not available yet. You can still offer times manually.',
              'connecting' =>
                'Finish Google consent in your browser, then return here. Refresh to check the connection.',
              'reconnect_required' =>
                'Google access needs to be renewed before checking times or copying appointments.',
              _ => 'Connect your Google account to check availability.',
            }),
            const SizedBox(height: 16),
            if (!controller.isDemo &&
                status?['configured'] == true &&
                state != 'disconnecting' &&
                state != 'disconnect_uncertain')
              BusyButton(
                busy: busy,
                onPressed: connect,
                icon: Icons.link,
                label: state == 'reconnect_required' || state == 'connecting'
                    ? 'Reconnect Google Calendar'
                    : 'Connect Google Calendar',
              ),
          ],
          if (connected) ...[
            const SectionHeading('Calendars that make you busy'),
            const Text(
              'Choose 1–10 calendars. These names stay in your private Calendar settings.',
            ),
            const SizedBox(height: 12),
            if (calendars.isEmpty && !loading)
              const Text(
                'No accessible calendars were found. Refresh or reconnect with a Google account that has a calendar.',
              ),
            for (final calendar in calendars)
              CheckboxListTile(
                key: ValueKey('calendar-choice-${calendar['id']}'),
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                value: selected.contains(calendar['id']),
                title: Text(textOf(calendar, 'summary', 'Calendar')),
                subtitle: calendar['primary'] == true
                    ? const Text('Primary calendar')
                    : null,
                onChanged: busy || loading
                    ? null
                    : (value) => setState(() {
                        if (value == true && selected.length >= 10) {
                          error = 'Choose up to 10 calendars.';
                          return;
                        }
                        if (value == true) {
                          selected.add(calendar['id'] as String);
                        } else {
                          selected.remove(calendar['id']);
                        }
                        dirty = true;
                        error = null;
                      }),
              ),
            const SectionHeading('Appointment time zone'),
            DropdownButtonFormField<String>(
              key: ValueKey('common-zone-${zone.text}'),
              initialValue: commonCalendarZones.contains(zone.text)
                  ? zone.text
                  : 'custom',
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Common time zones'),
              items: [
                ...commonCalendarZones.map(
                  (v) => DropdownMenuItem(value: v, child: Text(v)),
                ),
                const DropdownMenuItem(
                  value: 'custom',
                  child: Text('Other IANA time zone'),
                ),
              ],
              onChanged: busy || loading
                  ? null
                  : (value) => setState(() {
                      if (value != 'custom') {
                        zone.text = value!;
                      } else {
                        zone.clear();
                      }
                      dirty = true;
                    }),
            ),
            const SizedBox(height: 12),
            TextFormField(
              key: const Key('calendar-zone'),
              controller: zone,
              enabled: !busy && !loading,
              autocorrect: false,
              decoration: const InputDecoration(
                labelText: 'IANA time zone',
                hintText: 'America/Denver',
              ),
              onChanged: (_) {
                dirty = true;
              },
            ),
            const SizedBox(height: 18),
            SwitchListTile(
              key: const Key('calendar-sync'),
              contentPadding: EdgeInsets.zero,
              title: const Text(
                'Copy checked, confirmed appointments to Google',
              ),
              subtitle: const Text(
                'Only appointments scheduled using Calendar availability are added to an Estimoto + calendar after confirmation. Existing and manually offered appointments are not imported.',
              ),
              value: sync,
              onChanged: busy || loading
                  ? null
                  : (value) => setState(() {
                      sync = value;
                      dirty = true;
                    }),
            ),
            const SizedBox(height: 16),
            BusyButton(
              key: const Key('calendar-save'),
              busy: busy,
              label: 'Save Calendar preferences',
              onPressed: loading ? null : save,
              icon: Icons.check,
            ),
          ],
          if ((connected ||
              state == 'connecting' ||
              state == 'reconnect_required' ||
              state == 'disconnecting' ||
              state == 'disconnect_uncertain')) ...[
            const SizedBox(height: 20),
            OutlinedButton.icon(
              key: const Key('calendar-disconnect'),
              onPressed: busy ? null : disconnect,
              icon: const Icon(Icons.link_off),
              label: const Text('Disconnect Google Calendar'),
            ),
            const SizedBox(height: 8),
            const Text(
              'Disconnect stops availability checks and automatic copies. Existing Google copies remain in Google Calendar.',
            ),
          ],
          for (final issue in rowsOf(status ?? {}, 'sync_issues')) ...[
            const SizedBox(height: 20),
            Text(
              calendarSyncLabel(textOf(issue, 'status')),
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const Text(
              'Your booking status is unchanged. After reconnecting or resolving the conflict, retry this appointment’s Calendar copy.',
            ),
            OutlinedButton.icon(
              onPressed: connected && !busy && !loading
                  ? () => retry(issue)
                  : null,
              icon: const Icon(Icons.refresh),
              label: const Text('Retry Calendar copy'),
            ),
          ],
        ],
      ),
    );
  }
}
