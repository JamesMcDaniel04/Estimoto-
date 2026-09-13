import 'package:flutter/material.dart';
import '../screens/estimate_forms.dart';
import '../services/estimate_capture.dart';
import '../state/plus_controller.dart';

class PendingCaptureNotice extends StatefulWidget {
  const PendingCaptureNotice({super.key, required this.controller});
  final PlusController controller;
  @override
  State<PendingCaptureNotice> createState() => _PendingCaptureNoticeState();
}

class _PendingCaptureNoticeState extends State<PendingCaptureNotice> {
  PendingEstimateCapture? pending;
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
  }

  @override
  Widget build(BuildContext context) {
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
                builder: (_) => EstimateDetailScreen(
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
