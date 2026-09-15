import 'package:flutter/material.dart';
import '../build_info.dart';
import '../domain/models.dart';
import '../state/plus_controller.dart';
import '../widgets/common.dart';
import '../widgets/workspace_widgets.dart';
import 'calendar_screen.dart';
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
                      const ListTile(
                        leading: Icon(
                          Icons.mail_outline,
                          color: Color(0xFFEA4335),
                        ),
                        title: Text('Gmail'),
                        subtitle: Text(
                          'Car-service appointments, estimates and receipts\nNot configured',
                        ),
                      ),
                    ],
                  ),
                ),
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
