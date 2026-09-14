import 'guided_capture_pending_types.dart';

GuidedCapturePendingStore createStore() =>
    throw const GuidedCapturePendingException(
      GuidedCapturePendingFailure.storage,
    );
