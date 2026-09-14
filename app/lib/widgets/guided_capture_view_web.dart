import 'dart:async';
import 'dart:convert';
import 'dart:js_interop';
import 'package:flutter/material.dart';
import 'package:web/web.dart' as web;
import '../services/guided_capture_session.dart';
import '../services/guided_capture_document.dart';

@JS('JSON.stringify')
external JSString stringifyCapture(JSAny? value);

class GuidedCaptureView extends StatefulWidget {
  const GuidedCaptureView({
    super.key,
    required this.session,
    required this.onClose,
    required this.onError,
  });
  final GuidedCaptureSession session;
  final VoidCallback onClose;
  final ValueChanged<String> onError;
  @override
  State<GuidedCaptureView> createState() => _GuidedCaptureViewState();
}

class _GuidedCaptureViewState extends State<GuidedCaptureView> {
  web.HTMLIFrameElement? frame;
  late final JSFunction listener;
  late final GuidedCaptureDocument document;
  Timer? timer;
  bool ready = false, stopped = false;
  GuidedCaptureSession get session => widget.session;
  Uri get page => Uri.parse(web.window.location.origin).resolve('/capture/');
  bool valid(int run) => mounted && !stopped && session.valid(run);
  Object? readDocument() {
    try {
      final window = frame?.contentWindow;
      if (window == null || !trustedCapturePage(page, window.location.href)) {
        return null;
      }
      return window.document;
    } catch (_) {
      return null;
    }
  }

  void startTimer() {
    timer?.cancel();
    timer = Timer(const Duration(seconds: 30), () {
      if (mounted && !ready && !stopped) {
        widget.onError(
          'The photo guide is taking too long to load. Reopen it to try again.',
        );
      }
    });
  }

  void synchronizeDocument() {
    if (document.synchronize()) {
      setState(() => ready = false);
      startTimer();
    }
  }

  @override
  void initState() {
    super.initState();
    document = GuidedCaptureDocument(session, readDocument);
    listener = ((web.MessageEvent event) {
      unawaited(receive(event));
    }).toJS;
    web.window.addEventListener('message', listener);
  }

  Future<void> receive(web.MessageEvent event) async {
    if (!mounted ||
        stopped ||
        !session.current ||
        !session.foreground ||
        event.origin != page.origin ||
        event.source != frame?.contentWindow ||
        readDocument() == null) {
      return;
    }
    try {
      final raw = stringifyCapture(event.data).toDart;
      if (!boundedCaptureMessage(raw)) return;
      final value = jsonDecode(raw);
      if (value is Map &&
          value.length == 3 &&
          value['channel'] == captureChannel &&
          value['type'] == 'ready' &&
          value['version'] == 1) {
        synchronizeDocument();
        if (document.current && valid(session.epoch)) {
          setState(() {
            ready = true;
            timer?.cancel();
          });
        }
        return;
      }
      // A new page must identify itself before it can use the channel.
      if (!ready || !document.current) return;
      final run = session.epoch;
      final response = await session.receive(raw);
      if (response == null || !valid(run) || !document.current) return;
      frame!.contentWindow!.postMessage(response.jsify(), page.origin.toJS);
      if (valid(run) && session.closeRequested) widget.onClose();
    } catch (_) {
      /* Ignore foreign/malformed messages without private logging. */
    }
  }

  void create(Object element) {
    final iframe = element as web.HTMLIFrameElement;
    frame = iframe;
    iframe.title = 'Private vehicle photo guide';
    iframe.setAttribute(
      'sandbox',
      'allow-scripts allow-same-origin allow-forms',
    );
    iframe.setAttribute('allow', "camera 'self'; microphone 'none'");
    iframe.referrerPolicy = 'no-referrer';
    iframe.style
      ..border = '0'
      ..width = '100%'
      ..height = '100%';
    iframe.addEventListener(
      'load',
      ((web.Event _) {
        if (!mounted || stopped) return;
        if (readDocument() == null) {
          session.pause();
          widget.onError(
            'The photo guide was closed after a navigation change.',
          );
          return;
        }
        synchronizeDocument();
      }).toJS,
    );
    session.pause();
    iframe.src = page.toString();
    startTimer();
  }

  @override
  void dispose() {
    stopped = true;
    timer?.cancel();
    document.dispose();
    web.window.removeEventListener('message', listener);
    try {
      frame?.contentWindow?.postMessage(
        {'channel': captureChannel, 'type': 'pause'}.jsify(),
        page.origin.toJS,
      );
    } catch (_) {}
    frame?.src = 'about:blank';
    frame?.remove();
    frame = null;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Stack(
    children: [
      HtmlElementView.fromTagName(tagName: 'iframe', onElementCreated: create),
      if (!ready)
        const Align(
          alignment: Alignment.topCenter,
          child: LinearProgressIndicator(),
        ),
    ],
  );
}
