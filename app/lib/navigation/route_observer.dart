import 'package:flutter/widgets.dart';

/// Lets list screens reload when a route pushed above them pops, including
/// routes that replaced an intermediate screen (which completes the original
/// push future early).
final RouteObserver<ModalRoute<void>> plusRouteObserver =
    RouteObserver<ModalRoute<void>>();
