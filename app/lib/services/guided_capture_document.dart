import 'guided_capture_session.dart';

/// Tracks a real page Document, not the WindowProxy that survives navigation.
/// The platform calls [synchronize] for a trusted ready handshake or load event.
class GuidedCaptureDocument {
  GuidedCaptureDocument(this.session, this.readDocument);
  final GuidedCaptureSession session;
  final Object? Function() readDocument;
  Object? _document;
  bool Function()? _guard;

  bool get current {
    final document = _document;
    return document != null && identical(document, readDocument());
  }

  /// Returns true only when this is a replacement document. A ready handshake
  /// may arrive before load; observing its later load must not invalidate it.
  bool synchronize() {
    final document = readDocument();
    if (!session.current ||
        !session.foreground ||
        document == null ||
        identical(document, _document)) {
      return false;
    }
    session.pause();
    _document = document;
    _guard = () => identical(document, readDocument());
    session.activate(newDocument: true, documentIsCurrent: _guard);
    return true;
  }

  void dispose() {
    session.pause();
    if (identical(session.documentIsCurrent, _guard)) {
      session.documentIsCurrent = null;
    }
    _document = null;
  }
}
