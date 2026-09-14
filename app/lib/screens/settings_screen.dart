import 'package:flutter/material.dart';
import '../build_info.dart';
import '../state/plus_controller.dart';
import '../widgets/common.dart';
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
