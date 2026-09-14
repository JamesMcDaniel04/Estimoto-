import 'package:flutter/material.dart';
import '../domain/models.dart';
import '../screens/calendar_screen.dart';
import '../services/calendar_time.dart';
import '../state/plus_controller.dart';
import 'workspace_widgets.dart';

/// Calendar-copy state is separate from the shop's authoritative booking state.
class CalendarBookingDetails extends StatefulWidget {
  const CalendarBookingDetails({
    super.key,
    required this.controller,
    required this.source,
    required this.sourceKind,
  });
  final PlusController controller;
  final Json source;
  final String sourceKind;
  @override
  State<CalendarBookingDetails> createState() => _CalendarBookingDetailsState();
}

class _CalendarBookingDetailsState
    extends WorkspaceState<CalendarBookingDetails> {
  @override
  PlusController get controller => widget.controller;
  Json? retryResult;
  @override
  void didUpdateWidget(covariant CalendarBookingDetails oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(widget.source, oldWidget.source)) retryResult = null;
  }

  Future<void> retry() => perform(() async {
    final result = await controller.repository.retryCalendarSync({
      'source_kind': widget.sourceKind,
      'source_id': widget.source['id'],
    });
    if (!active) return;
    setState(() {
      retryResult = result;
    });
    await controller.refresh(quiet: true);
  });
  @override
  Widget build(BuildContext context) {
    if (!current ||
        (widget.source['calendar_check'] != true &&
            widget.source['calendar_sample'] != true)) {
      return const SizedBox.shrink();
    }
    final value = {...widget.source, ...?retryResult};
    final status = textOf(value, 'calendar_sync_status', 'not_enabled');
    final recoverable = [
      'conflict',
      'reconnect_required',
      'attention_needed',
    ].contains(status);
    final confirmed =
        widget.source['status'] == 'confirmed' ||
        widget.source['status'] == 'scheduled';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${intOf(value, 'duration_minutes')} minutes per offer',
            style: Theme.of(context).textTheme.titleSmall,
          ),
          Text(
            value['calendar_sample'] == true
                ? 'Sample availability; no Google check.'
                : 'Times were checked against your selected calendars. The shop’s confirmation determines your appointment.',
          ),
          const SizedBox(height: 8),
          Text(calendarSyncLabel(status)),
          if (textOf(value, 'calendar_sync_message').isNotEmpty)
            Text(textOf(value, 'calendar_sync_message')),
          if (recoverable) ...[
            const Text(
              'Your booking status is unchanged. Resolve the Calendar issue before retrying this copy.',
            ),
            Wrap(
              spacing: 12,
              runSpacing: 6,
              children: [
                OutlinedButton(
                  onPressed: busy
                      ? null
                      : () => openCalendar(context, controller),
                  child: const Text('Calendar settings'),
                ),
                if (confirmed)
                  OutlinedButton(
                    onPressed: busy ? null : retry,
                    child: Text(busy ? 'Retrying…' : 'Retry Calendar copy'),
                  ),
              ],
            ),
          ],
          if (error != null) WorkspaceError(error!),
        ],
      ),
    );
  }
}
