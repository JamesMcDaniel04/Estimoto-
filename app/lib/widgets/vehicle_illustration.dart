import 'dart:math' as math;
import 'package:flutter/material.dart';

/// An original vector silhouette, sized independently of the actual vehicle.
class VehicleIllustration extends StatelessWidget {
  const VehicleIllustration({super.key, this.color = const Color(0xFFB9D9F1)});
  final Color color;
  @override
  Widget build(BuildContext context) => ExcludeSemantics(
    child: SizedBox(
      height: 125,
      width: double.infinity,
      child: CustomPaint(painter: _CarPainter(color)),
    ),
  );
}

class _CarPainter extends CustomPainter {
  _CarPainter(this.color);
  final Color color;
  @override
  void paint(Canvas canvas, Size size) {
    final s = math.min(size.width / 320, size.height / 110);
    canvas.save();
    canvas.translate((size.width - 320 * s) / 2, (size.height - 110 * s) / 2);
    canvas.scale(s);
    canvas.drawOval(
      const Rect.fromLTWH(17, 91, 285, 11),
      Paint()..color = Colors.black.withValues(alpha: .16),
    );
    final body = Path()
      ..moveTo(18, 66)
      ..quadraticBezierTo(24, 57, 47, 54)
      ..lineTo(87, 25)
      ..quadraticBezierTo(98, 16, 125, 17)
      ..lineTo(216, 20)
      ..quadraticBezierTo(229, 20, 242, 40)
      ..lineTo(255, 57)
      ..lineTo(290, 63)
      ..quadraticBezierTo(304, 66, 305, 79)
      ..lineTo(302, 87)
      ..lineTo(278, 87)
      ..quadraticBezierTo(274, 64, 253, 64)
      ..quadraticBezierTo(232, 64, 229, 88)
      ..lineTo(93, 88)
      ..quadraticBezierTo(90, 64, 69, 64)
      ..quadraticBezierTo(48, 64, 46, 88)
      ..lineTo(21, 86)
      ..quadraticBezierTo(12, 80, 18, 66)
      ..close();
    canvas.drawPath(body, Paint()..color = color);
    final windows = Path()
      ..moveTo(65, 53)
      ..lineTo(101, 29)
      ..quadraticBezierTo(107, 26, 121, 26)
      ..lineTo(152, 27)
      ..lineTo(150, 54)
      ..close()
      ..moveTo(159, 27)
      ..lineTo(214, 29)
      ..quadraticBezierTo(223, 30, 228, 38)
      ..lineTo(239, 54)
      ..lineTo(158, 54)
      ..close();
    canvas.drawPath(windows, Paint()..color = const Color(0xFF173F6A));
    canvas.drawLine(
      const Offset(156, 58),
      const Offset(155, 83),
      Paint()
        ..color = const Color(0xFF729EBD)
        ..strokeWidth = 1,
    );
    canvas.drawLine(
      const Offset(104, 63),
      const Offset(116, 63),
      Paint()
        ..color = const Color(0xFF4A7494)
        ..strokeWidth = 2
        ..strokeCap = StrokeCap.round,
    );
    canvas.drawLine(
      const Offset(204, 63),
      const Offset(216, 63),
      Paint()
        ..color = const Color(0xFF4A7494)
        ..strokeWidth = 2
        ..strokeCap = StrokeCap.round,
    );
    for (final x in [69.0, 253.0]) {
      canvas.drawCircle(
        Offset(x, 85),
        19,
        Paint()..color = const Color(0xFF132C46),
      );
      canvas.drawCircle(
        Offset(x, 85),
        11,
        Paint()..color = const Color(0xFFE4EEF5),
      );
      canvas.drawCircle(
        Offset(x, 85),
        5,
        Paint()..color = const Color(0xFF7395AE),
      );
    }
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        const Rect.fromLTWH(280, 66, 20, 6),
        const Radius.circular(3),
      ),
      Paint()..color = const Color(0xFFE2FFF6),
    );
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        const Rect.fromLTWH(19, 65, 9, 6),
        const Radius.circular(2),
      ),
      Paint()..color = const Color(0xFFEF8B85),
    );
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant _CarPainter oldDelegate) =>
      oldDelegate.color != color;
}
