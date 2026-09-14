import 'package:flutter/material.dart';
import '../state/plus_controller.dart';
import '../services/estimate_capture_steps.dart';
import '../services/guided_capture_pending.dart';
import '../services/guided_capture_session.dart';
import '../widgets/common.dart';
import '../widgets/guided_capture_view.dart';
import '../widgets/workspace_widgets.dart';

typedef GuidedCaptureViewBuilder =
    Widget Function(
      GuidedCaptureSession session,
      VoidCallback onClose,
      ValueChanged<String> onError,
    );

class GuidedCaptureScreen extends StatefulWidget {
  const GuidedCaptureScreen({
    super.key,
    required this.controller,
    required this.estimateId,
    this.store,
    this.viewBuilder,
  });
  final PlusController controller;
  final String estimateId;
  final GuidedCapturePendingStore? store;
  final GuidedCaptureViewBuilder? viewBuilder;
  @override
  State<GuidedCaptureScreen> createState() => _GuidedCaptureScreenState();
}

class _GuidedCaptureScreenState extends WorkspaceState<GuidedCaptureScreen>
    with WidgetsBindingObserver {
  @override
  PlusController get controller => widget.controller;
  late final GuidedCaptureSession session;
  GuidedCapturePending? saved;
  bool checking = true, showing = false, corrupt = false, background = false;
  int generation = 0;

  @override
  void initState() {
    super.initState();
    session = GuidedCaptureSession(
      controller: controller,
      estimateId: widget.estimateId,
      store: widget.store ?? createGuidedCapturePendingStore(),
    );
    WidgetsBinding.instance.addObserver(this);
    load();
  }

  @override
  void changed() {
    if (!current) session.dispose();
    super.changed();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.hidden ||
        state == AppLifecycleState.detached) {
      background = true;
      session.foreground = false;
      session.pause();
      generation++;
      if (mounted && !session.selectingPhoto) {
        setState(() {
          showing = false;
          checking = true;
        });
      }
    } else if (state == AppLifecycleState.resumed && background) {
      background = false;
      session.foreground = true;
      if (session.selectingPhoto && showing) {
        session.activate();
      } else {
        load();
      }
    }
  }

  bool valid(int run) => active && !background && run == generation;
  Future<void> load({String? notice}) async {
    if (!active || background) return;
    final run = ++generation;
    session.pause();
    setState(() {
      checking = true;
      showing = false;
      error = notice;
      corrupt = false;
    });
    if (controller.isDemo) {
      setState(() => checking = false);
      return;
    }
    try {
      final value = await session.pending();
      if (!valid(run)) return;
      setState(() {
        saved = value;
        checking = false;
        showing = value == null && notice == null;
      });
    } on GuidedCapturePendingException catch (e) {
      if (!valid(run)) return;
      setState(() {
        checking = false;
        corrupt = e.failure == GuidedCapturePendingFailure.corrupt;
        error = e.toString();
      });
    } catch (_) {
      if (valid(run)) {
        setState(() {
          checking = false;
          error =
              'Your saved photo could not be checked. Try again before opening the camera.';
        });
      }
    }
  }

  Future<void> retry() async {
    final value = saved;
    if (!active ||
        busy ||
        value == null ||
        value.estimateId != widget.estimateId) {
      return;
    }
    final run = generation;
    setState(() {
      busy = true;
      error = null;
    });
    session.activate();
    String? notice;
    try {
      await session.save(value, session.epoch);
      if (!valid(run)) return;
      await controller.refresh();
      if (!valid(run)) return;
    } catch (e) {
      notice = PlusController.readableError(e);
    } finally {
      if (valid(run)) {
        setState(() => busy = false);
        await load(notice: notice);
      }
    }
  }

  Future<void> discard() async {
    if (!active || busy) return;
    final run = generation;
    setState(() => busy = true);
    try {
      if (corrupt) {
        await session.discardCorrupt();
      } else if (saved != null) {
        await session.discard(saved!);
      }
      if (!valid(run)) return;
      await load();
    } catch (e) {
      if (valid(run)) setState(() => error = PlusController.readableError(e));
    } finally {
      if (active) setState(() => busy = false);
    }
  }

  Future<void> close() async {
    if (!active) return;
    session.pause();
    setState(() {
      showing = false;
      checking = true;
    });
    await controller.refresh();
    if (!active || !mounted) return;
    Navigator.of(context).pop();
  }

  void failed(String message) {
    if (!active) return;
    // Platform callbacks can occur while their widget is being built.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (active) load(notice: message);
    });
  }

  @override
  void dispose() {
    generation++;
    session.dispose();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!current) return unavailable;
    final estimate = controller.snapshot!.estimates
        .where((e) => e.id == widget.estimateId)
        .firstOrNull;
    final other = saved != null && saved!.estimateId != widget.estimateId;
    return Scaffold(
      appBar: AppBar(title: const Text('Guided photos')),
      body: estimate == null
          ? const Center(child: Text('This estimate is no longer available.'))
          : controller.isDemo
          ? const PageBody(
              children: [
                PageHeading('Your vehicle, step by step', 'Sample preview'),
                Text(
                  'In your signed-in workspace, the 3D guide shows where to stand, checks photo framing and helps with each step. Photograph the driver-door VIN label, then confirm any suggested VIN yourself.',
                ),
                SizedBox(height: 20),
                Text(
                  'This preview does not open a live camera or send an estimate.',
                ),
              ],
            )
          : checking
          ? const Center(child: CircularProgressIndicator())
          : showing
          ? widget.viewBuilder?.call(session, close, failed) ??
                GuidedCaptureView(
                  key: ValueKey(generation),
                  session: session,
                  onClose: close,
                  onError: failed,
                )
          : PageBody(
              children: [
                PageHeading(
                  saved == null
                      ? 'Continue guided photos'
                      : 'A photo is waiting to finish',
                  other
                      ? 'Saved to another estimate in your garage'
                      : controller.snapshot!
                                .vehicle(estimate.vehicleId)
                                ?.title ??
                            'Your vehicle',
                ),
                if (saved != null && !other) ...[
                  Text(
                    captureLabel(saved!.captureKey),
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                  const SizedBox(height: 12),
                  const Text(
                    'Retry this exact photo, or discard it and take a new one. Nothing is sent automatically.',
                  ),
                  const SizedBox(height: 20),
                  BusyButton(
                    key: const Key('guided-retry'),
                    busy: busy,
                    label: 'Retry saved photo',
                    onPressed: busy ? null : retry,
                  ),
                ],
                if (other) ...[
                  const Text(
                    'Finish the saved photo in its original estimate before taking another. It will never be attached to this estimate.',
                  ),
                  const SizedBox(height: 20),
                  FilledButton(
                    onPressed: busy
                        ? null
                        : () {
                            final id = saved!.estimateId;
                            if (!active ||
                                !controller.snapshot!.estimates.any(
                                  (e) => e.id == id,
                                )) {
                              return;
                            }
                            Navigator.of(context).pushReplacement(
                              MaterialPageRoute<void>(
                                builder: (_) => GuidedCaptureScreen(
                                  controller: controller,
                                  estimateId: id,
                                  store: session.store,
                                  viewBuilder: widget.viewBuilder,
                                ),
                              ),
                            );
                          },
                    child: const Text('Open original estimate photos'),
                  ),
                ],
                if (error != null) WorkspaceError(error!),
                if (saved != null || corrupt)
                  OutlinedButton(
                    key: const Key('guided-discard'),
                    onPressed: busy ? null : discard,
                    child: Text(
                      corrupt
                          ? 'Discard unreadable saved photo'
                          : 'Discard saved photo & retake',
                    ),
                  ),
                if (saved == null && !corrupt)
                  FilledButton(
                    onPressed: busy ? null : load,
                    child: const Text('Reopen photo guide'),
                  ),
                const SizedBox(height: 16),
                TextButton(
                  onPressed: busy ? null : close,
                  child: const Text('Return to estimate review'),
                ),
              ],
            ),
    );
  }
}
