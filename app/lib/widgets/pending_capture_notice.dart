import 'package:flutter/material.dart';
import '../screens/estimate_forms.dart';
import '../screens/vehicle_photo_screen.dart';
import '../screens/history_receipts_screen.dart';
import '../services/receipt_pending.dart';
import '../services/estimate_capture.dart';
import '../state/plus_controller.dart';
import '../services/guided_capture_pending.dart';
import '../screens/guided_capture_screen.dart';
import 'workspace_widgets.dart';

class PendingCaptureNotice extends StatefulWidget {
  const PendingCaptureNotice({super.key, required this.controller});
  final PlusController controller;
  @override
  State<PendingCaptureNotice> createState() => _PendingCaptureNoticeState();
}

class _PendingCaptureNoticeState extends WorkspaceState<PendingCaptureNotice> {
  @override
  PlusController get controller => widget.controller;
  PendingEstimateCapture? pending;
  GuidedCapturePending? guided;
  ReceiptPending? receipt;
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final id = widget.controller.snapshot?.profile.id;
    if (id == null || widget.controller.isDemo) return;
    try {
      final saved = await pendingEstimateCaptureFor(id);
      if (mounted && widget.controller.isCurrentCustomer(id)) {
        setState(() => pending = saved);
      }
    } catch (_) {
      // Capture itself fails closed if encrypted storage is unavailable.
    }
    if (!active) return;
    try {
      final value = await createReceiptPendingStore().read(id);
      if (active) setState(() => receipt = value);
    } catch (_) {}
    if (!active) return;
    try {
      final value = await createGuidedCapturePendingStore().read(id);
      if (active) setState(() => guided = value);
    } catch (_) {
      // The camera entry provides explicit unreadable-storage recovery.
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!current) return const SizedBox.shrink();
    final capture = guided;
    if (capture != null) {
      return MaterialBanner(
        content: const Text('A guided photo is waiting to finish.'),
        actions: [
          TextButton(
            onPressed: () async {
              if (!active ||
                  !controller.snapshot!.estimates.any(
                    (e) => e.id == capture.estimateId,
                  )) {
                return;
              }
              await Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => GuidedCaptureScreen(
                    controller: controller,
                    estimateId: capture.estimateId,
                  ),
                ),
              );
              if (active) await _load();
            },
            child: const Text('Review saved photo'),
          ),
        ],
      );
    }
    if (receipt != null) {
      final saved = receipt!;
      return MaterialBanner(
        content: const Text('A receipt is waiting to finish.'),
        actions: [
          TextButton(
            onPressed: () async {
              if (!active) return;
              await Navigator.push(
                context,
                MaterialPageRoute<void>(
                  builder: (_) => HistoryReceiptsScreen(
                    controller: controller,
                    recordId: saved.recordId,
                  ),
                ),
              );
              if (active) await _load();
            },
            child: const Text('Review saved receipt'),
          ),
        ],
      );
    }
    final saved = pending;
    if (saved == null) return const SizedBox.shrink();
    return MaterialBanner(
      content: const Text('A photo is waiting to finish uploading.'),
      actions: [
        TextButton(
          onPressed: () async {
            if (!widget.controller.isCurrentCustomer(saved.customerId)) return;
            await Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => saved.targetKind == 'receipt'
                    ? HistoryReceiptsScreen(
                        controller: controller,
                        recordId: saved.estimateId,
                      )
                    : saved.targetKind == 'vehicle'
                    ? VehiclePhotoScreen(
                        controller: widget.controller,
                        vehicleId: saved.estimateId,
                      )
                    : EstimateDetailScreen(
                        controller: widget.controller,
                        estimateId: saved.estimateId,
                      ),
              ),
            );
            if (mounted) await _load();
          },
          child: const Text('Continue photos'),
        ),
      ],
    );
  }
}
