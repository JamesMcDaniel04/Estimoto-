import 'package:flutter/material.dart';
import '../build_info.dart';
import '../theme.dart';
import '../domain/models.dart';
import '../services/reminder_notifications.dart';
import '../state/plus_controller.dart';
import '../widgets/common.dart';
import '../widgets/workspace_widgets.dart';
import 'calendar_screen.dart';
import 'gmail_screen.dart';
import 'garage_forms.dart';

/// Account, profile, session and version in one place.
///
/// Email is read-only because it is the sign-in identity. Profile fields
/// reuse [ProfileForm] so validation lives in one widget. Signing out
/// always asks first; the exit itself belongs to the caller.
class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key, required this.controller, this.onExit});
  final PlusController controller;
  final VoidCallback? onExit;

  static Future<void> open(
    BuildContext context,
    PlusController controller, {
    VoidCallback? onExit,
  }) => Navigator.of(context).push(
    MaterialPageRoute(
      builder: (_) => SettingsScreen(controller: controller, onExit: onExit),
    ),
  );

  Future<void> _confirmExit(BuildContext context) async {
    final demo = controller.isDemo;
    final leave = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(demo ? 'Leave the demo?' : 'Sign out?'),
        content: Text(
          demo
              ? 'Demo changes are not kept once you leave.'
              : 'Your saved details stay in your account. Sign in again with your email to return.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Stay'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text(demo ? 'Leave demo' : 'Sign out'),
          ),
        ],
      ),
    );
    if (leave == true) onExit?.call();
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: controller,
    builder: (context, _) {
      final snapshot = controller.snapshot;
      if (snapshot == null) {
        return Scaffold(
          appBar: AppBar(title: const Text('Settings')),
          body: const Center(child: Text('Sign in to view your settings.')),
        );
      }
      final theme = Theme.of(context);
      final demo = controller.isDemo;
      return Scaffold(
        appBar: AppBar(title: const Text('Settings')),
        body: SafeArea(
          top: false,
          child: PageBody(
            children: [
              const SectionHeading('Account'),
              Text('Signed in as', style: theme.textTheme.bodySmall),
              const SizedBox(height: 4),
              Text(snapshot.profile.email, style: theme.textTheme.titleMedium),
              const SizedBox(height: 8),
              Text(
                demo
                    ? 'Demo session · sample data that resets when you leave.'
                    : 'To change your email, sign in with the new address. Your email is how shops reach you and how you sign in.',
                style: theme.textTheme.bodySmall,
              ),
              const SectionHeading('Connections'),
              Card(
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  child: Column(
                    children: [
                      CalendarConnectionTile(
                        key: ValueKey('calendar-${snapshot.profile.id}'),
                        controller: controller,
                      ),
                      const Divider(indent: 16, endIndent: 16),
                      GmailConnectionTile(
                        key: ValueKey('gmail-${snapshot.profile.id}'),
                        controller: controller,
                      ),
                    ],
                  ),
                ),
              ),
              const SectionHeading('Notifications'),
              ReminderNotificationSettings(
                key: ValueKey('notifications-${snapshot.profile.id}'),
                controller: controller,
              ),
              const SectionHeading('Profile'),
              Text(
                'Shops see these details only when you choose to share a request.',
                style: theme.textTheme.bodySmall,
              ),
              const SizedBox(height: 12),
              ProfileForm(
                key: ValueKey(snapshot.profile.id),
                controller: controller,
                inline: true,
                onSaved: () => showMessage(context, 'Profile saved'),
              ),
              if (onExit != null) ...[
                const SectionHeading('Session'),
                OutlinedButton.icon(
                  onPressed: () => _confirmExit(context),
                  icon: const Icon(Icons.logout, size: 19),
                  label: Text(demo ? 'Leave demo' : 'Sign out'),
                ),
              ],
              const SectionHeading('About'),
              Text(PlusBuildInfo.label, style: theme.textTheme.bodyMedium),
              if (PlusBuildInfo.sourceSha.isNotEmpty)
                Text(
                  'Source ${PlusBuildInfo.sourceSha.substring(0, 7)}',
                  style: theme.textTheme.bodySmall,
                ),
            ],
          ),
        ),
      );
    },
  );
}

/// Live Google Calendar connection state, read from the customer API.
///
/// The tile never shows a connection it has not confirmed: while the status
/// is loading or failed it says so, and every state opens the Calendar screen
/// where connecting, choosing calendars and disconnecting live.
class CalendarConnectionTile extends StatefulWidget {
  const CalendarConnectionTile({super.key, required this.controller});
  final PlusController controller;
  @override
  State<CalendarConnectionTile> createState() => _CalendarConnectionTileState();
}

class _CalendarConnectionTileState extends State<CalendarConnectionTile> {
  Json? status;
  bool loading = true, failed = false;
  int run = 0;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    final current = ++run;
    setState(() {
      loading = true;
      failed = false;
    });
    try {
      final value = await widget.controller.repository.getCalendarStatus();
      if (!mounted || current != run) return;
      setState(() => status = value);
    } catch (_) {
      if (!mounted || current != run) return;
      setState(() => failed = true);
    } finally {
      if (mounted && current == run) setState(() => loading = false);
    }
  }

  Future<void> open() async {
    await openCalendar(context, widget.controller);
    if (mounted) load();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final demo = widget.controller.isDemo;
    final state = textOf(status ?? {}, 'status');
    final connected = status?['connected'] == true;
    final calendars = stringRows(status ?? {}, 'selected_calendar_ids').length;
    final issues = rowsOf(status ?? {}, 'sync_issues').length;
    final (String label, Color color, IconData icon) = switch (true) {
      _ when loading => (
        'Checking…',
        theme.colorScheme.onSurfaceVariant,
        Icons.sync,
      ),
      _ when failed => (
        'Status unavailable · tap to retry',
        theme.colorScheme.error,
        Icons.error_outline,
      ),
      _ when demo => (
        'Sample calendar · fictional availability only',
        theme.colorScheme.onSurfaceVariant,
        Icons.science_outlined,
      ),
      _ when connected && issues > 0 => (
        'Connected · $issues ${issues == 1 ? 'appointment needs' : 'appointments need'} attention',
        const Color(0xFFB26A00),
        Icons.warning_amber_outlined,
      ),
      _ when connected => (
        'Connected · $calendars ${calendars == 1 ? 'calendar' : 'calendars'} marking you busy',
        const Color(0xFF08796D),
        Icons.check_circle_outline,
      ),
      _ when state == 'connecting' => (
        'Finish Google consent, then return here',
        theme.colorScheme.onSurfaceVariant,
        Icons.hourglass_top,
      ),
      _ when state == 'reconnect_required' => (
        'Google access needs renewing',
        const Color(0xFFB26A00),
        Icons.link_off,
      ),
      _ when state == 'disconnecting' || state == 'disconnect_uncertain' => (
        'Disconnection not yet confirmed',
        const Color(0xFFB26A00),
        Icons.link_off,
      ),
      _ when status?['configured'] == true => (
        'Not connected · tap to connect',
        theme.colorScheme.onSurfaceVariant,
        Icons.link,
      ),
      _ => (
        'Not available yet · offer times manually',
        theme.colorScheme.onSurfaceVariant,
        Icons.link_off,
      ),
    };
    return ListTile(
      key: const Key('settings-calendar-connection'),
      onTap: failed ? load : open,
      leading: Icon(
        Icons.calendar_month_outlined,
        color: theme.colorScheme.primary,
      ),
      title: const Text('Google Calendar'),
      subtitle: Padding(
        padding: const EdgeInsets.only(top: 2),
        child: Row(
          children: [
            Icon(icon, size: 16, color: color),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                label,
                style: theme.textTheme.bodySmall?.copyWith(color: color),
              ),
            ),
          ],
        ),
      ),
      trailing: const Icon(Icons.chevron_right),
    );
  }
}

/// Reminder alerts scheduled on this device from the customer's garage.
class ReminderNotificationSettings extends StatefulWidget {
  const ReminderNotificationSettings({super.key, required this.controller});
  final PlusController controller;
  @override
  State<ReminderNotificationSettings> createState() =>
      _ReminderNotificationSettingsState();
}

class _ReminderNotificationSettingsState
    extends State<ReminderNotificationSettings> {
  NotificationPreferences? preferences;
  bool busy = false;
  String? note;
  ReminderNotifier get notifier => widget.controller.notifier;
  bool get available => notifier.supported && !widget.controller.isDemo;

  @override
  void initState() {
    super.initState();
    if (available) {
      notifier.preferences().then((value) {
        if (mounted) setState(() => preferences = value);
      });
    }
  }

  Future<void> update(NotificationPreferences next) async {
    if (busy) return;
    setState(() {
      busy = true;
      note = null;
    });
    try {
      if (next.enabled && !(preferences?.enabled ?? false)) {
        if (!await notifier.requestPermission()) {
          setState(
            () => note =
                'Notifications are turned off for Estimoto + in your device settings. Allow them there, then try again.',
          );
          return;
        }
      }
      await notifier.savePreferences(next);
      await widget.controller.syncNotifications();
      if (mounted) setState(() => preferences = next);
    } catch (_) {
      if (mounted) {
        setState(
          () => note = 'Reminder alerts could not be updated. Try again.',
        );
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (!available) {
      return Text(
        widget.controller.isDemo
            ? 'Reminder alerts are available once you sign in on your phone. The demo never schedules notifications.'
            : 'Reminder alerts arrive on your phone. Install the iOS or Android app to turn them on.',
        style: theme.textTheme.bodySmall,
      );
    }
    final value = preferences;
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(4, 4, 4, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SwitchListTile.adaptive(
              key: const Key('settings-reminder-alerts'),
              title: const Text('Reminder alerts on this device'),
              subtitle: const Text(
                'A heads-up before each reminder is due, and again on the day. Scheduled on this phone; nothing is sent to a server.',
              ),
              value: value?.enabled ?? false,
              onChanged: value == null || busy
                  ? null
                  : (enabled) => update(value.copyWith(enabled: enabled)),
            ),
            if (value?.enabled ?? false) ...[
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
                child: Text(
                  'Remind me ahead by',
                  style: theme.textTheme.bodySmall,
                ),
              ),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                child: SizedBox(
                  width: double.infinity,
                  child: SegmentedButton<int>(
                    key: const Key('settings-reminder-lead'),
                    showSelectedIcon: false,
                    segments: [
                      for (final days in reminderLeadChoices)
                        ButtonSegment(
                          value: days,
                          label: Text('$days ${days == 1 ? 'day' : 'days'}'),
                        ),
                    ],
                    selected: {value!.leadDays},
                    onSelectionChanged: busy
                        ? null
                        : (choice) =>
                              update(value.copyWith(leadDays: choice.first)),
                  ),
                ),
              ),
              const Padding(
                padding: EdgeInsets.fromLTRB(16, 10, 16, 0),
                child: Text(
                  'Alerts arrive at 9:00 AM. Reminders with only a mileage target are not scheduled.',
                  style: TextStyle(fontSize: 12, color: PlusColors.muted),
                ),
              ),
            ],
            if (note != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                child: Text(
                  note!,
                  style: TextStyle(
                    color: theme.colorScheme.error,
                    fontSize: 13,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// Live Gmail connection state, read from the customer API.
class GmailConnectionTile extends StatefulWidget {
  const GmailConnectionTile({super.key, required this.controller});
  final PlusController controller;
  @override
  State<GmailConnectionTile> createState() => _GmailConnectionTileState();
}

class _GmailConnectionTileState extends State<GmailConnectionTile> {
  Json? status;
  bool loading = true, failed = false;
  int run = 0;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    final current = ++run;
    setState(() {
      loading = true;
      failed = false;
    });
    try {
      final value = await widget.controller.repository.getGmailStatus();
      if (!mounted || current != run) return;
      setState(() => status = value);
    } catch (_) {
      if (!mounted || current != run) return;
      setState(() => failed = true);
    } finally {
      if (mounted && current == run) setState(() => loading = false);
    }
  }

  Future<void> open() async {
    await openGmail(context, widget.controller);
    if (mounted) load();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final demo = widget.controller.isDemo;
    final state = textOf(status ?? {}, 'status');
    final connected = status?['connected'] == true;
    final address = textOf(status ?? {}, 'email_address');
    final counts = Map<String, dynamic>.from(
      status?['message_counts'] as Map? ?? {},
    );
    final waiting = (counts['new'] as num?)?.toInt() ?? 0;
    final (String label, Color color, IconData icon) = switch (true) {
      _ when loading => (
        'Checking…',
        theme.colorScheme.onSurfaceVariant,
        Icons.sync,
      ),
      _ when failed => (
        'Status unavailable · tap to retry',
        theme.colorScheme.error,
        Icons.error_outline,
      ),
      _ when demo => (
        'Sample mode · connect your inbox after signing in',
        theme.colorScheme.onSurfaceVariant,
        Icons.science_outlined,
      ),
      _ when connected && waiting > 0 => (
        '${address.isEmpty ? 'Connected' : address} · $waiting ${waiting == 1 ? 'message' : 'messages'} to file',
        const Color(0xFFB26A00),
        Icons.mark_email_unread_outlined,
      ),
      _ when connected => (
        '${address.isEmpty ? 'Connected' : address} · read-only',
        const Color(0xFF08796D),
        Icons.check_circle_outline,
      ),
      _ when state == 'connecting' => (
        'Finish Google consent, then return here',
        theme.colorScheme.onSurfaceVariant,
        Icons.hourglass_top,
      ),
      _ when state == 'reconnect_required' => (
        'Google access needs renewing',
        const Color(0xFFB26A00),
        Icons.link_off,
      ),
      _ when status?['configured'] == true => (
        'Not connected · estimates, receipts and appointments',
        theme.colorScheme.onSurfaceVariant,
        Icons.link,
      ),
      _ => (
        'Not available yet · add history by hand',
        theme.colorScheme.onSurfaceVariant,
        Icons.link_off,
      ),
    };
    return ListTile(
      key: const Key('settings-gmail-connection'),
      onTap: failed ? load : open,
      leading: const Icon(Icons.mail_outline, color: Color(0xFFEA4335)),
      title: const Text('Gmail'),
      subtitle: Padding(
        padding: const EdgeInsets.only(top: 2),
        child: Row(
          children: [
            Icon(icon, size: 16, color: color),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                label,
                style: theme.textTheme.bodySmall?.copyWith(color: color),
              ),
            ),
          ],
        ),
      ),
      trailing: const Icon(Icons.chevron_right),
    );
  }
}
