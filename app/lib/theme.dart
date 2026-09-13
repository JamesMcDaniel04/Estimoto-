import 'package:flutter/material.dart';

abstract final class PlusColors {
  static const blue = Color(0xFF1565C0);
  static const navy = Color(0xFF0D3F7A);
  static const teal = Color(0xFF00B8A9);
  static const canvas = Color(0xFFF3F5F8);
  static const ink = Color(0xFF172B4D);
  static const muted = Color(0xFF53657D);
  static const line = Color(0xFFDEE5EE);
}

ThemeData plusTheme() {
  final scheme = ColorScheme.fromSeed(seedColor: PlusColors.blue).copyWith(
    primary: PlusColors.blue,
    secondary: PlusColors.teal,
    surface: Colors.white,
    onSurface: PlusColors.ink,
    onSurfaceVariant: PlusColors.muted,
  );
  final base = ThemeData(useMaterial3: true, colorScheme: scheme);
  return base.copyWith(
    scaffoldBackgroundColor: PlusColors.canvas,
    textTheme: base.textTheme.copyWith(
      headlineMedium: const TextStyle(
        fontSize: 28,
        height: 1.15,
        fontWeight: FontWeight.w700,
        letterSpacing: -.7,
        color: PlusColors.ink,
      ),
      titleLarge: const TextStyle(
        fontSize: 22,
        height: 1.2,
        fontWeight: FontWeight.w700,
        letterSpacing: -.4,
        color: PlusColors.ink,
      ),
      titleMedium: const TextStyle(
        fontSize: 17,
        height: 1.3,
        fontWeight: FontWeight.w600,
        color: PlusColors.ink,
      ),
      bodyLarge: const TextStyle(
        fontSize: 16,
        height: 1.5,
        color: PlusColors.ink,
      ),
      bodyMedium: const TextStyle(
        fontSize: 15,
        height: 1.4,
        color: PlusColors.ink,
      ),
      bodySmall: const TextStyle(
        fontSize: 13,
        height: 1.4,
        color: PlusColors.muted,
      ),
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: PlusColors.canvas,
      surfaceTintColor: Colors.transparent,
      centerTitle: false,
      elevation: 0,
    ),
    cardTheme: CardThemeData(
      color: Colors.white,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: const Color(0xFFF5F7FA),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: PlusColors.line),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: PlusColors.line),
      ),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(48, 50),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(48, 48),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        side: const BorderSide(color: PlusColors.line),
      ),
    ),
    dividerTheme: const DividerThemeData(
      color: PlusColors.line,
      thickness: 1,
      space: 1,
    ),
    bottomSheetTheme: const BottomSheetThemeData(
      backgroundColor: Colors.white,
      showDragHandle: true,
    ),
    snackBarTheme: const SnackBarThemeData(behavior: SnackBarBehavior.floating),
  );
}
