import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/rendering.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

Future<void> loadReceiptProofFonts() async {
  const directory = String.fromEnvironment('RECEIPT_FONT_DIR');
  if (directory.isEmpty) return;
  for (final pair in [
    ('Roboto', 'Roboto-Regular.ttf'),
    ('MaterialIcons', 'MaterialIcons-Regular.otf'),
  ]) {
    final loader = FontLoader(pair.$1)
      ..addFont(
        Future.value(
          ByteData.sublistView(
            await File('$directory/${pair.$2}').readAsBytes(),
          ),
        ),
      );
    await loader.load();
  }
}

Future<void> saveReceiptProof(WidgetTester tester, String name) async {
  const directory = String.fromEnvironment('RECEIPT_CAPTURE_DIR');
  if (directory.isEmpty) return;
  final boundary = tester.renderObject<RenderRepaintBoundary>(
    find.byKey(const ValueKey('receipt-proof')),
  );
  await tester.runAsync(() async {
    final image = await boundary.toImage(pixelRatio: 1);
    final data = await image.toByteData(format: ui.ImageByteFormat.png);
    await Directory(directory).create(recursive: true);
    await File('$directory/$name.png').writeAsBytes(data!.buffer.asUint8List());
    image.dispose();
  });
}
