import 'package:flutter/material.dart';
import 'screens/garage_screen.dart';
import 'screens/estimates_screen.dart';
import 'screens/estibot_screen.dart';
import 'screens/repairs_screen.dart';
import 'screens/find_help_screen.dart';
import 'state/plus_controller.dart';
import 'theme.dart';
import 'widgets/common.dart';

class EstimotoPlusApp extends StatelessWidget {
  const EstimotoPlusApp({super.key, required this.controller, this.onExit});
  final PlusController controller;
  final VoidCallback? onExit;
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'Estimoto +',
    debugShowCheckedModeBanner: false,
    theme: plusTheme(),
    home: _HomeShell(controller: controller, onExit: onExit),
  );
}

class _HomeShell extends StatefulWidget {
  const _HomeShell({required this.controller, this.onExit});
  final PlusController controller;
  final VoidCallback? onExit;
  @override
  State<_HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<_HomeShell> {
  @override
  void initState() {
    super.initState();
    if (widget.controller.snapshot == null) widget.controller.refresh();
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.controller,
    builder: (context, _) {
      final c = widget.controller;
      return Scaffold(
        appBar: AppBar(
          toolbarHeight: 62,
          titleSpacing: 20,
          title: Row(
            children: [
              Container(
                width: 29,
                height: 29,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: PlusColors.blue,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Text(
                  'E',
                  style: TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.w800,
                    fontSize: 22,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              const Expanded(
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: Alignment.centerLeft,
                  child: Text(
                    'Estimoto +',
                    style: TextStyle(
                      fontSize: 22,
                      letterSpacing: -.65,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ),
            ],
          ),
          actions: [
            IconButton(
              tooltip: 'Refresh',
              onPressed: c.loading ? null : c.refresh,
              icon: const Icon(Icons.refresh, size: 22),
            ),
            if (widget.onExit != null)
              PopupMenuButton<String>(
                tooltip: 'Account options',
                itemBuilder: (_) => [
                  PopupMenuItem(
                    value: 'exit',
                    child: Text(c.isDemo ? 'Leave demo' : 'Sign out'),
                  ),
                ],
                onSelected: (_) => widget.onExit!(),
              ),
          ],
        ),
        body: Column(
          children: [
            if (c.isDemo)
              Container(
                width: double.infinity,
                color: const Color(0xFFE5F0F7),
                padding: const EdgeInsets.symmetric(
                  horizontal: 16,
                  vertical: 7,
                ),
                child: const Text(
                  'Demo · sample data, no real requests',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 12,
                    color: PlusColors.navy,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ),
            if (c.loading && c.snapshot != null)
              const LinearProgressIndicator(minHeight: 2),
            if (c.error != null && c.snapshot != null)
              MaterialBanner(
                content: Text(c.error!),
                actions: [
                  TextButton(
                    onPressed: c.loading ? null : c.refresh,
                    child: const Text('Retry'),
                  ),
                ],
              ),
            Expanded(
              child: c.snapshot == null
                  ? Center(
                      child: c.loading
                          ? const CircularProgressIndicator()
                          : Padding(
                              padding: const EdgeInsets.all(24),
                              child: EmptyState(
                                icon: Icons.cloud_off_outlined,
                                title: 'Let’s reconnect',
                                message:
                                    c.error ??
                                    'Your account is not available yet.',
                                action: 'Try again',
                                onAction: c.refresh,
                              ),
                            ),
                    )
                  : IndexedStack(
                      index: c.tab,
                      children: [
                        GarageScreen(controller: c),
                        EstimatesScreen(controller: c),
                        EstibotScreen(controller: c),
                        RepairsScreen(controller: c),
                        FindHelpScreen(controller: c),
                      ],
                    ),
            ),
          ],
        ),
        bottomNavigationBar: _Navigation(controller: c),
      );
    },
  );
}

class _Navigation extends StatelessWidget {
  const _Navigation({required this.controller});
  final PlusController controller;
  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: const BoxDecoration(
      color: Colors.white,
      border: Border(top: BorderSide(color: PlusColors.line)),
    ),
    child: SafeArea(
      top: false,
      child: SizedBox(
        height: 70 + MediaQuery.textScalerOf(context).scale(11) * 1.2,
        child: Row(
          children: [
            for (final (i, label, key, icon, selectedIcon) in [
              (
                0,
                'Garage',
                'garage',
                Icons.directions_car_outlined,
                Icons.directions_car,
              ),
              (
                1,
                'Estimates',
                'estimates',
                Icons.receipt_long_outlined,
                Icons.receipt_long,
              ),
              (
                2,
                'Estibot',
                'estibot',
                Icons.support_agent_outlined,
                Icons.support_agent,
              ),
              (3, 'Repairs', 'repairs', Icons.build_outlined, Icons.build),
              (4, 'Find Help', 'find-help', Icons.place_outlined, Icons.place),
            ])
              Expanded(
                child: Semantics(
                  selected: controller.tab == i,
                  button: true,
                  child: Tooltip(
                    message: label,
                    excludeFromSemantics: true,
                    child: InkWell(
                      key: Key('nav-$key'),
                      onTap: () => controller.selectTab(i),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(
                          vertical: 9,
                          horizontal: 2,
                        ),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (i == 2)
                              Container(
                                width: 42,
                                height: 38,
                                decoration: BoxDecoration(
                                  color: controller.tab == 2
                                      ? PlusColors.navy
                                      : PlusColors.blue,
                                  borderRadius: BorderRadius.circular(16),
                                ),
                                child: const Icon(
                                  Icons.support_agent,
                                  size: 26,
                                  color: Colors.white,
                                ),
                              )
                            else
                              SizedBox(
                                height: 38,
                                child: Icon(
                                  controller.tab == i ? selectedIcon : icon,
                                  size: 25,
                                  color: controller.tab == i
                                      ? PlusColors.blue
                                      : PlusColors.muted,
                                ),
                              ),
                            const SizedBox(height: 4),
                            Text(
                              label,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                fontSize: 11,
                                fontWeight: controller.tab == i
                                    ? FontWeight.w700
                                    : FontWeight.w500,
                                color: controller.tab == i
                                    ? PlusColors.blue
                                    : PlusColors.muted,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    ),
  );
}
