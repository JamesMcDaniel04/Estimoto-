import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../data/repository.dart';
import '../domain/models.dart';
import '../state/plus_controller.dart';
import '../theme.dart';
import '../widgets/common.dart';
import '../widgets/workspace_widgets.dart';
import 'calendar_screen.dart' show calendarConnectUri;
import 'history_screen.dart';

Future<void> openGmail(BuildContext context, PlusController controller) =>
    Navigator.of(context).push<void>(
      MaterialPageRoute(builder: (_) => GmailScreen(controller: controller)),
    );

const gmailCategoryLabels = {
  'receipt': 'Receipt',
  'estimate': 'Estimate',
  'appointment': 'Appointment',
  'service': 'Service',
};

/// A scanned message becomes a prefilled service history entry.
///
/// Only the message's own metadata is used. The customer reviews every
/// field before anything is saved.
Json historyDraftFromMessage(Json message, {String? vehicleId}) {
  final category = textOf(message, 'category');
  final received = DateTime.tryParse(textOf(message, 'received_at'));
  final subject = textOf(message, 'subject');
  final snippet = textOf(message, 'snippet');
  final today = DateTime.now();
  final date = received == null || received.isAfter(today) ? today : received;
  return {
    'vehicle_id': ?vehicleId,
    'service_type': switch (category) {
      'estimate' => 'repair',
      'receipt' => 'repair',
      _ => 'maintenance',
    },
    'service_date': date.toIso8601String().substring(0, 10),
    'shop_name': textOf(message, 'sender_name'),
    'notes': [
      subject,
      if (snippet.isNotEmpty) snippet,
      'From Gmail on ${dateText(textOf(message, 'received_at'))}.',
    ].join('\n'),
  };
}

class GmailScreen extends StatefulWidget {
  const GmailScreen({super.key, required this.controller});
  final PlusController controller;
  @override
  State<GmailScreen> createState() => _GmailScreenState();
}

class _GmailScreenState extends WorkspaceState<GmailScreen>
    with WidgetsBindingObserver {
  @override
  PlusController get controller => widget.controller;
  Json? status;
  List<Json> messages = [];
  bool loading = true, resumePending = false;
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

  Future<void> load() async {
    if (!active || busy) return;
    final run = ++epoch;
    setState(() {
      loading = true;
      error = null;
    });
    try {
      var value = await controller.repository.getGmailStatus();
      if (!valid(run)) return;
      setState(() => status = value);
      final attempt = textOf(value, 'attempt_id');
      if (!controller.isDemo &&
          value['status'] == 'connecting' &&
          attempt.isNotEmpty) {
        value = await controller.repository.reconcileGmail(attempt);
        if (!valid(run)) return;
        setState(() => status = value);
      }
      if (value['connected'] == true) {
        final list = await controller.repository.listGmailMessages();
        if (!valid(run)) return;
        setState(() => messages = rowsOf(list, 'messages'));
      } else {
        setState(() => messages = []);
      }
    } catch (e) {
      if (valid(run)) setState(() => error = PlusController.readableError(e));
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
      messages = [];
    });
    try {
      final result = await controller.repository.connectGmail();
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
      if (valid(run)) setState(() => error = PlusController.readableError(e));
    } finally {
      finish(run);
    }
  }

  Future<void> scan() async {
    if (!active || busy || loading) return;
    final run = ++epoch;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await controller.repository.scanGmail();
      if (!valid(run)) return;
      final found = intOf(result, 'scanned');
      setState(() => messages = rowsOf(result, 'messages'));
      final refreshed = await controller.repository.getGmailStatus();
      if (!valid(run)) return;
      setState(() => status = refreshed);
      if (mounted) {
        showMessage(
          context,
          found == 0
              ? 'No new car-service mail found.'
              : 'Found $found new ${found == 1 ? 'message' : 'messages'}.',
        );
      }
    } catch (e) {
      if (valid(run)) {
        setState(() => error = PlusController.readableError(e));
        load();
      }
    } finally {
      finish(run);
    }
  }

  Future<void> setStatus(Json message, String state, {String? recordId}) async {
    if (!active || busy) return;
    final run = ++epoch;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final updated = await controller.repository.setGmailMessageStatus(
        textOf(message, 'id'),
        state,
        knowledgeRecordId: recordId,
      );
      if (!valid(run)) return;
      setState(() {
        messages = [
          for (final row in messages)
            if (row['id'] == updated['id']) updated else row,
        ];
      });
    } catch (e) {
      if (valid(run)) setState(() => error = PlusController.readableError(e));
    } finally {
      finish(run);
    }
  }

  Future<void> addToHistory(Json message) async {
    final saved = await Navigator.of(context).push<Json?>(
      MaterialPageRoute(
        builder: (_) => HistoryEditor(
          controller: controller,
          initial: historyDraftFromMessage(
            message,
            vehicleId: controller.selectedVehicle?.id,
          ),
        ),
      ),
    );
    if (saved != null && textOf(saved, 'id').isNotEmpty && active) {
      await setStatus(message, 'saved', recordId: textOf(saved, 'id'));
    }
  }

  Future<void> disconnect() async {
    if (!active || busy) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Disconnect Gmail?'),
        content: const Text(
          'Estimoto + stops reading your mail and forgets every scanned message. History entries you already saved stay in your garage.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Keep connected'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Disconnect'),
          ),
        ],
      ),
    );
    if (confirmed != true || !active) return;
    final run = ++epoch;
    setState(() {
      busy = true;
      loading = false;
      error = null;
      messages = [];
      status = {
        ...?status,
        'connected': false,
        'status': 'disconnecting',
        'attempt_id': null,
      };
    });
    try {
      await controller.repository.disconnectGmail();
      if (!valid(run)) return;
      setState(() => status = {...?status, 'status': 'disconnected'});
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

  @override
  Widget build(BuildContext context) {
    if (!current) return unavailable;
    final state = textOf(status ?? {}, 'status');
    final connected = status?['connected'] == true;
    final address = textOf(status ?? {}, 'email_address');
    final open = messages.where((m) => m['status'] == 'new').toList();
    final handled = messages.where((m) => m['status'] != 'new').toList();
    return Scaffold(
      appBar: AppBar(
        title: const Text('Gmail'),
        actions: [
          IconButton(
            tooltip: 'Refresh Gmail',
            onPressed: busy ? null : load,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: PageBody(
        children: [
          const PageHeading(
            'Your car mail, sorted.',
            'Estimates, receipts and appointments from your inbox, ready to file in your service history.',
          ),
          const Text(
            'Read-only access. Estimoto + looks at the sender, subject, date and a short preview of car-service mail from the last 90 days. Nothing is sent, moved or deleted, and message bodies are never read.',
          ),
          if (controller.isDemo) ...[
            const SizedBox(height: 16),
            const Text(
              'Sample mode • Gmail cannot be connected in the demo. Sign in on your phone to connect your own inbox.',
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
              'disconnecting' => 'Checking that Gmail access is disconnected…',
              'disconnect_uncertain' =>
                'Disconnection is not confirmed. Refresh or try disconnecting again.',
              'unavailable' =>
                'Gmail connections are not available yet. You can still add service history by hand.',
              'connecting' =>
                'Finish Google consent in your browser, then return here. Refresh to check the connection.',
              'reconnect_required' =>
                'Google access needs to be renewed before your mail can be scanned again.',
              _ => 'Connect your Google account to find car-service mail.',
            }),
            const SizedBox(height: 16),
            if (!controller.isDemo &&
                status?['configured'] == true &&
                state != 'disconnecting' &&
                state != 'disconnect_uncertain')
              BusyButton(
                key: const Key('gmail-connect'),
                busy: busy,
                onPressed: connect,
                icon: Icons.link,
                label: state == 'reconnect_required' || state == 'connecting'
                    ? 'Reconnect Gmail'
                    : 'Connect Gmail',
              ),
          ],
          if (connected) ...[
            const SizedBox(height: 20),
            Card(
              child: ListTile(
                leading: const Icon(
                  Icons.mark_email_read_outlined,
                  color: Color(0xFF08796D),
                ),
                title: Text(address.isEmpty ? 'Connected' : address),
                subtitle: Text(
                  textOf(status!, 'last_scan_at').isEmpty
                      ? 'Not scanned yet'
                      : 'Last scan ${dateText(textOf(status!, 'last_scan_at'))}',
                ),
              ),
            ),
            const SizedBox(height: 12),
            BusyButton(
              key: const Key('gmail-scan'),
              busy: busy,
              onPressed: scan,
              icon: Icons.manage_search_outlined,
              label: 'Scan for car-service mail',
            ),
            SectionHeading(
              open.isEmpty ? 'Nothing waiting' : 'Waiting for you',
            ),
            if (open.isEmpty)
              const EmptyState(
                icon: Icons.inbox_outlined,
                title: 'No unfiled mail',
                message:
                    'Scan your inbox and any estimate, receipt or appointment from a shop will show up here.',
              ),
            for (final message in open)
              _MessageCard(
                message: message,
                busy: busy,
                onAdd: () => addToHistory(message),
                onDismiss: () => setStatus(message, 'dismissed'),
              ),
            if (handled.isNotEmpty) ...[
              const SectionHeading('Handled'),
              for (final message in handled)
                _MessageCard(
                  message: message,
                  busy: busy,
                  onRestore: () => setStatus(message, 'new'),
                ),
            ],
            const SizedBox(height: 24),
            OutlinedButton.icon(
              key: const Key('gmail-disconnect'),
              onPressed: busy ? null : disconnect,
              icon: const Icon(Icons.link_off),
              label: const Text('Disconnect Gmail'),
            ),
          ],
        ],
      ),
    );
  }
}

class _MessageCard extends StatelessWidget {
  const _MessageCard({
    required this.message,
    required this.busy,
    this.onAdd,
    this.onDismiss,
    this.onRestore,
  });
  final Json message;
  final bool busy;
  final VoidCallback? onAdd, onDismiss, onRestore;
  @override
  Widget build(BuildContext context) {
    final category = textOf(message, 'category');
    final state = textOf(message, 'status');
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Wrap(
                spacing: 8,
                runSpacing: 6,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  StatusPill(
                    gmailCategoryLabels[category] ?? 'Mail',
                    color: switch (category) {
                      'receipt' => const Color(0xFF08796D),
                      'estimate' => PlusColors.blue,
                      'appointment' => const Color(0xFFB26A00),
                      _ => PlusColors.muted,
                    },
                  ),
                  if (state == 'saved')
                    const StatusPill('In history', color: Color(0xFF08796D)),
                  if (state == 'dismissed')
                    const StatusPill('Dismissed', color: PlusColors.muted),
                  Text(
                    dateText(textOf(message, 'received_at')),
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ],
              ),
              const SizedBox(height: 10),
              Text(
                textOf(message, 'subject'),
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 4),
              Text(
                textOf(message, 'sender_name').isEmpty
                    ? textOf(message, 'sender_address')
                    : '${textOf(message, 'sender_name')} · ${textOf(message, 'sender_address')}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              if (textOf(message, 'snippet').isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(
                  textOf(message, 'snippet'),
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 4,
                children: [
                  if (onAdd != null)
                    FilledButton.tonalIcon(
                      onPressed: busy ? null : onAdd,
                      icon: const Icon(Icons.history_outlined, size: 18),
                      label: const Text('Add to history'),
                    ),
                  if (onDismiss != null)
                    TextButton(
                      onPressed: busy ? null : onDismiss,
                      child: const Text('Dismiss'),
                    ),
                  if (onRestore != null)
                    TextButton(
                      onPressed: busy ? null : onRestore,
                      child: const Text('Move back'),
                    ),
                  TextButton.icon(
                    onPressed: () =>
                        openExternal(context, textOf(message, 'gmail_url')),
                    icon: const Icon(Icons.open_in_new, size: 16),
                    label: const Text('Open in Gmail'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
