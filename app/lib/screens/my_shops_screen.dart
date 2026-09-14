import 'package:flutter/material.dart';
import '../domain/models.dart';
import '../state/plus_controller.dart';
import '../widgets/common.dart';
import '../navigation/route_observer.dart';
import '../widgets/outreach_actions.dart';
import '../widgets/workspace_widgets.dart';
import 'shop_outreach_screen.dart';
import '../widgets/dedicated_shop_choice.dart';

void openMyShops(
  BuildContext context,
  PlusController controller, {
  String initialSummary = '',
}) {
  Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) =>
          MyShopsScreen(controller: controller, initialSummary: initialSummary),
    ),
  );
}

class MyShopsScreen extends StatefulWidget {
  const MyShopsScreen({
    super.key,
    required this.controller,
    this.initialSummary = '',
  });
  final PlusController controller;
  final String initialSummary;
  @override
  State<MyShopsScreen> createState() => _MyShopsScreenState();
}

class _MyShopsScreenState extends WorkspaceState<MyShopsScreen>
    with RouteAware {
  @override
  PlusController get controller => widget.controller;
  ModalRoute<void>? _route;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final route = ModalRoute.of(context);
    if (route != null && !identical(route, _route)) {
      if (_route != null) plusRouteObserver.unsubscribe(this);
      _route = route;
      plusRouteObserver.subscribe(this, route);
    }
  }

  @override
  void dispose() {
    plusRouteObserver.unsubscribe(this);
    super.dispose();
  }

  // A review screen that replaced the composer pops straight back here, so
  // the push future that normally triggers a reload has long since completed.
  @override
  void didPopNext() {
    if (active) load();
  }

  List<Json> shops = [], requests = [];
  bool loading = true;
  bool pendingDraft = false;
  int generation = 0;
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    final run = ++generation;
    if (!active) return;
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final results = await Future.wait<Object?>([
        controller.repository.listMyShops(),
        controller.repository.listShopOutreach(),
        workspace.pending('outreach-draft'),
      ]);
      if (!active || run != generation) return;
      setState(() {
        shops = results[0] as List<Json>;
        requests = results[1] as List<Json>;
        pendingDraft = results[2] != null;
      });
    } catch (e) {
      if (active && run == generation) {
        setState(() {
          error = PlusController.readableError(e);
        });
      }
    } finally {
      if (active && run == generation) {
        setState(() {
          loading = false;
        });
      }
    }
  }

  Future<void> edit([Json? shop]) async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ShopEditor(controller: controller, shop: shop),
      ),
    );
    if (active) await load();
  }

  Future<void> schedule([Json? shop]) async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ShopOutreachComposer(
          controller: controller,
          shops: shops,
          initialShop: shop,
          initialSummary: widget.initialSummary,
        ),
      ),
    );
    if (active) await load();
  }

  Future<void> review(Json draft) async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ShopOutreachReview(
          controller: controller,
          draftId: draft['id'] as String,
        ),
      ),
    );
    if (active) await load();
  }

  Future<void> discardDeviceDraft() async {
    if (!await confirmDiscardDeviceDraft(context) || !active) return;
    await perform(() async {
      await workspace.discardPending('outreach-draft');
      if (active) await load();
    });
  }

  Future<void> discard(Json draft) async {
    if (!await confirmDiscardOutreach(context) || !active) return;
    await perform(() async {
      await controller.repository.deleteShopOutreach(draft['id'] as String);
      if (active) await load();
    });
  }

  Future<void> withdraw(Json draft) async {
    if (!await confirmWithdrawOutreach(context) || !active) return;
    await perform(() async {
      await controller.repository.withdrawShopOutreach(draft['id'] as String);
      if (active) await load();
    });
  }

  Future<void> remove(Json shop) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Remove ${textOf(shop, 'name')}?'),
        content: const Text(
          'Existing scheduling requests and your service history will remain available.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Keep shop'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Remove shop'),
          ),
        ],
      ),
    );
    if (confirmed != true || !active) return;
    await perform(() async {
      await controller.repository.deleteMyShop(shop['id'] as String);
      if (active) await load();
    });
  }

  @override
  Widget build(BuildContext context) {
    if (!current) return unavailable;
    return Scaffold(
      appBar: AppBar(
        title: const Text('My shops'),
        actions: [
          IconButton(
            tooltip: 'Refresh shops and requests',
            onPressed: loading ? null : load,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: PageBody(
        children: [
          const PageHeading(
            'People who know your car.',
            'Save your own shops and ask about a service time when you’re ready.',
          ),
          FilledButton.icon(
            onPressed: busy ? null : () => edit(),
            icon: const Icon(Icons.add),
            label: const Text('Add a shop'),
          ),
          if (error != null) WorkspaceError(error!),
          if (loading)
            const Padding(
              padding: EdgeInsets.all(24),
              child: Center(child: CircularProgressIndicator()),
            ),
          if (pendingDraft) ...[
            const SectionHeading('Finish your saved request'),
            const Text(
              'A draft was interrupted. Recover its original details before starting another.',
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              children: [
                OutlinedButton(
                  onPressed: busy ? null : schedule,
                  child: const Text('Recover scheduling draft'),
                ),
                TextButton(
                  onPressed: busy ? null : discardDeviceDraft,
                  child: const Text('Discard draft'),
                ),
              ],
            ),
          ],
          const SectionHeading('Your saved shops'),
          if (!loading && shops.isEmpty)
            const EmptyState(
              icon: Icons.storefront_outlined,
              title: 'Keep a trusted shop close',
              message:
                  'Add the shop’s email or phone. You choose when to contact them.',
            ),
          for (final shop in shops)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(
                            child: Text(
                              textOf(shop, 'name'),
                              style: Theme.of(context).textTheme.titleLarge,
                            ),
                          ),
                          PopupMenuButton<String>(
                            tooltip: 'Manage ${textOf(shop, 'name')}',
                            onSelected: (action) =>
                                action == 'edit' ? edit(shop) : remove(shop),
                            itemBuilder: (_) => const [
                              PopupMenuItem(
                                value: 'edit',
                                child: Text('Edit shop'),
                              ),
                              PopupMenuItem(
                                value: 'delete',
                                child: Text('Remove shop'),
                              ),
                            ],
                          ),
                        ],
                      ),
                      if (textOf(shop, 'email').isNotEmpty)
                        Text(textOf(shop, 'email')),
                      if (textOf(shop, 'phone').isNotEmpty)
                        Text(textOf(shop, 'phone')),
                      if (textOf(shop, 'address').isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: Text(textOf(shop, 'address')),
                        ),
                      if (shop['vehicle_id'] != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: Text(
                            controller.snapshot!
                                    .vehicle(shop['vehicle_id'] as String)
                                    ?.title ??
                                'Saved vehicle',
                          ),
                        ),
                      const SizedBox(height: 16),
                      OutlinedButton.icon(
                        onPressed: busy || controller.selectedVehicle == null
                            ? null
                            : () => perform(() async {
                                final saved = await chooseDedicatedShop(
                                  context,
                                  controller,
                                  source: 'my_shop',
                                  sourceId: textOf(shop, 'id'),
                                  vehicleId: controller.selectedVehicle!.id,
                                );
                                if (mounted &&
                                    context.mounted &&
                                    active &&
                                    saved) {
                                  showMessage(
                                    context,
                                    'Dedicated shop preference updated.',
                                  );
                                }
                              }),
                        icon: const Icon(Icons.bookmark_outline),
                        label: Text(
                          'Dedicated shop for ${controller.selectedVehicle?.title ?? 'a saved vehicle'}',
                        ),
                      ),
                      OutlinedButton.icon(
                        onPressed: busy ? null : () => schedule(shop),
                        icon: const Icon(Icons.event_outlined),
                        label: const Text('Prepare a scheduling request'),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          const SectionHeading('Scheduling requests'),
          if (!loading && requests.isEmpty)
            const Text(
              'Requests you prepare will appear here. A time is booked only after the shop confirms it.',
            ),
          for (final draft in requests)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Card(
                child: InkWell(
                  onTap: () => review(draft),
                  borderRadius: BorderRadius.circular(20),
                  child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Expanded(
                              child: Text(
                                textOf(draft, 'shop_name'),
                                style: Theme.of(context).textTheme.titleMedium,
                              ),
                            ),
                            if (outreachDiscardable(draft) ||
                                outreachWithdrawable(draft))
                              PopupMenuButton<String>(
                                tooltip: 'Request options',
                                itemBuilder: (_) => [
                                  if (outreachDiscardable(draft))
                                    const PopupMenuItem(
                                      value: 'discard',
                                      child: Text('Discard request'),
                                    ),
                                  if (outreachWithdrawable(draft))
                                    const PopupMenuItem(
                                      value: 'withdraw',
                                      child: Text('Withdraw request'),
                                    ),
                                ],
                                onSelected: (value) => value == 'discard'
                                    ? discard(draft)
                                    : withdraw(draft),
                              ),
                          ],
                        ),
                        const SizedBox(height: 10),
                        StatusPill(outreachStatusLabel(draft)),
                        if (textOf(draft, 'vehicle_summary').isNotEmpty)
                          Padding(
                            padding: const EdgeInsets.only(top: 10),
                            child: Text(textOf(draft, 'vehicle_summary')),
                          ),
                        const SizedBox(height: 10),
                        const Text(
                          'View request',
                          style: TextStyle(fontWeight: FontWeight.w600),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class ShopEditor extends StatefulWidget {
  const ShopEditor({
    super.key,
    required this.controller,
    this.shop,
    this.initialContact,
  });
  final PlusController controller;
  final Json? shop, initialContact;
  @override
  State<ShopEditor> createState() => _ShopEditorState();
}

class _ShopEditorState extends WorkspaceState<ShopEditor> {
  @override
  PlusController get controller => widget.controller;
  final form = GlobalKey<FormState>();
  final fields = <String, TextEditingController>{};
  String? vehicleId;
  @override
  void initState() {
    super.initState();
    for (final key in [
      'name',
      'email',
      'phone',
      'address',
      'website',
      'notes',
    ]) {
      fields[key] = TextEditingController(
        text: textOf(widget.shop ?? widget.initialContact ?? {}, key),
      );
    }
    vehicleId =
        (widget.shop ?? widget.initialContact)?['vehicle_id'] as String?;
  }

  @override
  void dispose() {
    for (final field in fields.values) {
      field.dispose();
    }
    super.dispose();
  }

  Future<void> save() async {
    if (!form.currentState!.validate()) return;
    if (fields['email']!.text.trim().isEmpty &&
        fields['phone']!.text.trim().isEmpty) {
      setState(() {
        error = 'Add an email or phone for this shop.';
      });
      return;
    }
    await perform(() async {
      await controller.repository.saveMyShop({
        for (final entry in fields.entries) entry.key: entry.value.text.trim(),
        'vehicle_id': vehicleId,
      }, id: widget.shop?['id'] as String?);
      if (mounted && active) Navigator.pop(context);
    });
  }

  @override
  Widget build(BuildContext context) {
    if (!current) return unavailable;
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.shop == null ? 'Add a shop' : 'Edit shop'),
      ),
      body: PageBody(
        children: [
          const PageHeading(
            'Your trusted contact.',
            'Shop details stay in your private garage.',
          ),
          Form(
            key: form,
            child: Column(
              children: [
                for (final key in fields.keys)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 18),
                    child: TextFormField(
                      key: ValueKey('shop-$key'),
                      controller: fields[key],
                      enabled: !busy,
                      maxLength: switch (key) {
                        'phone' => 50,
                        'address' || 'website' => 300,
                        'notes' => 2000,
                        _ => 200,
                      },
                      maxLines: key == 'notes' || key == 'address' ? 3 : 1,
                      keyboardType: key == 'email'
                          ? TextInputType.emailAddress
                          : key == 'phone'
                          ? TextInputType.phone
                          : TextInputType.text,
                      decoration: InputDecoration(
                        labelText: const {
                          'name': 'Shop name',
                          'email': 'Shop email',
                          'phone': 'Shop phone',
                          'address': 'Address (optional)',
                          'website': 'Website (optional)',
                          'notes': 'Notes (optional)',
                        }[key],
                        counterText: '',
                      ),
                      validator: (value) {
                        final text = value?.trim() ?? '';
                        if (key == 'name' && text.isEmpty) {
                          return 'Add the shop’s name.';
                        }
                        if (key == 'email' &&
                            text.isNotEmpty &&
                            !RegExp(
                              r'^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$',
                            ).hasMatch(text)) {
                          return 'Enter a valid shop email.';
                        }
                        if (key == 'phone' &&
                            text.isNotEmpty &&
                            (!RegExp(r'^\+?[0-9 ()-]{7,50}$').hasMatch(text) ||
                                text.replaceAll(RegExp(r'\D'), '').length <
                                    7)) {
                          return 'Enter a valid shop phone.';
                        }
                        return null;
                      },
                    ),
                  ),
                SavedVehicleField(
                  controller: controller,
                  value: vehicleId,
                  optional: true,
                  enabled: !busy,
                  onChanged: (value) => setState(() {
                    vehicleId = value;
                  }),
                ),
                if (error != null) WorkspaceError(error!),
                const SizedBox(height: 24),
                BusyButton(busy: busy, label: 'Save shop', onPressed: save),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
