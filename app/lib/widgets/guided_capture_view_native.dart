import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';
import 'package:webview_flutter_wkwebview/webview_flutter_wkwebview.dart';
import '../services/guided_capture_session.dart';

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
  WebViewController? webView;
  bool ready = false, stopped = false;
  Timer? timer;
  int pageGeneration = 0;
  GuidedCaptureSession get session => widget.session;
  @override
  void initState() {
    super.initState();
    setup();
  }

  bool valid(int run) => mounted && !stopped && session.valid(run);
  Future<bool> authorized(int run) async {
    if (!valid(run)) return false;
    final url = await webView?.currentUrl();
    return valid(run) &&
        url != null &&
        trustedCapturePage(session.pageUri, url);
  }

  Future<void> setup() async {
    if (!Platform.isAndroid && !Platform.isIOS) {
      widget.onError('Open the guided camera on your phone or in the web app.');
      return;
    }
    try {
      final params = WebViewPlatform.instance is WebKitWebViewPlatform
          ? WebKitWebViewControllerCreationParams(
              allowsInlineMediaPlayback: true,
              mediaTypesRequiringUserAction: const {},
            )
          : const PlatformWebViewControllerCreationParams();
      final view = WebViewController.fromPlatformCreationParams(
        params,
        onPermissionRequest: (request) async {
          final run = session.epoch;
          if (request.types.length != 1 ||
              !request.types.contains(WebViewPermissionResourceType.camera) ||
              !await authorized(run)) {
            await request.deny();
            return;
          }
          final permission = await Permission.camera.request();
          if (permission.isGranted && await authorized(run)) {
            await request.grant();
          } else {
            await request.deny();
          }
        },
      );
      webView = view;
      session.stopMedia = () {
        unawaited(
          view
              .runJavaScript(
                'document.querySelectorAll("video").forEach(v=>v.srcObject?.getTracks().forEach(t=>t.stop()));',
              )
              .catchError((_) {}),
        );
      };
      await view.setJavaScriptMode(JavaScriptMode.unrestricted);
      if (!mounted || stopped || !session.current) return;
      await view.addJavaScriptChannel(
        'CaptureHost',
        onMessageReceived: (message) async {
          if (!boundedCaptureMessage(message.message)) return;
          final run = session.epoch;
          try {
            if (!await authorized(run)) return;
            final raw = jsonDecode(message.message);
            if (raw is Map &&
                raw.length == 3 &&
                raw['channel'] == captureChannel &&
                raw['type'] == 'ready' &&
                raw['version'] == 1) {
              if (valid(run)) {
                setState(() {
                  ready = true;
                  timer?.cancel();
                });
              }
              return;
            }
            final response = await session.receive(message.message);
            if (response == null || !await authorized(run)) return;
            await view.runJavaScript(
              'window.EstimotoPlusCapture?.receive(${jsonEncode(response)});',
            );
            if (valid(run) && session.closeRequested) widget.onClose();
          } catch (_) {
            /* Private page/provider errors never enter platform logs. */
          }
        },
      );
      await view.setNavigationDelegate(
        NavigationDelegate(
          onNavigationRequest: (request) {
            if (stopped) {
              return request.url == 'about:blank'
                  ? NavigationDecision.navigate
                  : NavigationDecision.prevent;
            }
            if (!request.isMainFrame ||
                !trustedCapturePage(session.pageUri, request.url)) {
              return NavigationDecision.prevent;
            }
            session.pause();
            return NavigationDecision.navigate;
          },
          onPageStarted: (url) {
            pageGeneration++;
            if (!mounted || stopped || !session.current) return;
            if (!trustedCapturePage(session.pageUri, url)) {
              session.pause();
              widget.onError(
                'The guided camera could not open securely. Reopen it from your estimate.',
              );
              return;
            }
            session.activate();
          },
          onUrlChange: (change) {
            if (!mounted || stopped || change.url == null) return;
            if (!trustedCapturePage(session.pageUri, change.url!)) {
              session.pause();
              widget.onError(
                'The guided camera was closed after a navigation change.',
              );
            }
          },
          onWebResourceError: (error) {
            if (mounted && !stopped && error.isForMainFrame == true) {
              session.pause();
              widget.onError(
                'The photo guide could not load. Check your connection and reopen it.',
              );
            }
          },
        ),
      );
      if (view.platform is AndroidWebViewController) {
        final android = view.platform as AndroidWebViewController;
        await android.setAllowFileAccess(false);
        await android.setMixedContentMode(MixedContentMode.neverAllow);
        await android.setMediaPlaybackRequiresUserGesture(false);
        await android.setOnShowFileSelector((params) async {
          final run = session.epoch;
          if (!await authorized(run) ||
              params.acceptTypes.isEmpty ||
              params.acceptTypes.any(
                (type) => !const [
                  'image/*',
                  'image/jpeg',
                  'image/png',
                  'image/webp',
                ].contains(type),
              )) {
            return [];
          }
          try {
            final document = pageGeneration;
            session.selectingPhoto = true;
            final file = await ImagePicker().pickImage(
              source: ImageSource.gallery,
            );
            if (file == null ||
                !await session.waitForForeground() ||
                document != pageGeneration ||
                !await authorized(session.epoch)) {
              return [];
            }
            return [Uri.file(file.path).toString()];
          } catch (_) {
            return [];
          } finally {
            session.selectingPhoto = false;
          }
        });
      }
      if (!mounted || stopped || !session.current) return;
      session.activate();
      await view.loadRequest(session.pageUri);
      if (!mounted || stopped) return;
      setState(() {});
      timer = Timer(const Duration(seconds: 30), () {
        if (mounted && !ready && !stopped) {
          widget.onError(
            'The photo guide is taking too long to load. Reopen it to try again.',
          );
        }
      });
    } catch (_) {
      if (mounted && !stopped) {
        widget.onError(
          'The guided camera could not open. Reopen it to try again.',
        );
      }
    }
  }

  @override
  void dispose() {
    stopped = true;
    timer?.cancel();
    session.pause();
    session.stopMedia = null;
    final view = webView;
    if (view != null) {
      unawaited(
        view
            .runJavaScript(
              'window.EstimotoPlusCapture?.receive({channel:"estimoto-plus-capture",type:"pause"}); document.querySelectorAll("video").forEach(v=>v.srcObject?.getTracks().forEach(t=>t.stop()));',
            )
            .catchError((_) {}),
      );
      unawaited(view.removeJavaScriptChannel('CaptureHost').catchError((_) {}));
      unawaited(view.loadRequest(Uri.parse('about:blank')).catchError((_) {}));
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Stack(
    children: [
      if (webView != null) WebViewWidget(controller: webView!),
      if (!ready)
        const Align(
          alignment: Alignment.topCenter,
          child: LinearProgressIndicator(),
        ),
    ],
  );
}
