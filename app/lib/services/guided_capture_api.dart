import 'dart:typed_data';
import '../domain/models.dart';
import 'guided_capture_pending_types.dart';

/// The native/web host binds the estimate and account guard once, outside JS.
abstract class GuidedCaptureApi {
  Uri get pageUri;
  Future<Json> state();
  Future<Json> checkFrame({
    required Uint8List bytes,
    required String mimeType,
    required String captureKey,
    required String bodyStyle,
  });
  Future<Json> save(GuidedCapturePending photo);
  Future<Json> recognize(String photoId);
  Future<Json> confirm(Json body);
  Future<Json> help(String captureKey, String question);
}
