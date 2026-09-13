import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../domain/models.dart';
import '../services/customer_workspace.dart';
import '../state/plus_controller.dart';
import '../widgets/common.dart';
import '../widgets/workspace_widgets.dart';
import 'garage_forms.dart';

String outreachStatusLabel(Json draft) {
  if (draft['delivery_status'] == 'local_preview') {
    return 'Demo preview • no shop contacted';
  }
  if (draft['delivery_status'] == 'retrying') return 'Retrying delivery';
  return switch (draft['status']) {
    'draft' => 'Draft • not sent',
    'queued' => 'Queued for delivery',
    'waiting_for_reply' => 'Waiting for shop response',
    'confirmed' => 'Shop confirmed',
    'declined' => 'Shop declined',
    'call_required' => 'Call the shop • not sent',
    'delivery_failed' => 'Delivery failed',
    'delivery_unknown' => 'Delivery unconfirmed',
    _ => 'Checking request status',
  };
}

String _statusDescription(Json draft) {
  if (draft['delivery_status'] == 'local_preview') {
    return 'This is a local demo preview. No message was sent and no appointment was booked.';
  }
  return switch (draft['status']) {
    'draft' =>
      'Review every detail before authorizing. This request has not been sent.',
    'queued' =>
      'Your request is queued. Refresh here for delivery updates. The shop has not confirmed a time.',
    'waiting_for_reply' =>
      'The email service accepted your request. The shop still needs to confirm an offered time.',
    'confirmed' => 'The shop confirmed the time shown below.',
    'declined' =>
      'The shop declined this request. Contact the shop to discuss another time.',
    'call_required' =>
      'This shop has no saved email. No message was sent. Call them to discuss your preferred times.',
    'delivery_failed' =>
      'The email could not be delivered. Check the saved shop contact before preparing a new request.',
    'delivery_unknown' =>
      'Delivery could not be confirmed. Contact the shop before preparing another request to avoid a duplicate.',
    _ => 'Refresh to check the latest status before taking another action.',
  };
}

class ShopOutreachComposer extends StatefulWidget {
  const ShopOutreachComposer({
    super.key,
    required this.controller,
    required this.shops,
    this.initialShop,
    this.initialSummary = '',
  });
  final PlusController controller;
  final List<Json> shops;
  final Json? initialShop;
  final String initialSummary;
  @override
  State<ShopOutreachComposer> createState() => _ShopOutreachComposerState();
}

class _ShopOutreachComposerState extends WorkspaceState<ShopOutreachComposer> {
  @override
  PlusController get controller => widget.controller;
  final form = GlobalKey<FormState>();
  final summary = TextEditingController(), note = TextEditingController();
  String? shopId, vehicleId;
  List<String> slots = [];
  PendingWorkspaceWrite? pending;
  bool restoring = true;
  @override
  void initState() {
    super.initState();
    summary.text = widget.initialSummary.length > 500
        ? widget.initialSummary.substring(0, 500)
        : widget.initialSummary;
    shopId =
        widget.initialShop?['id'] as String? ??
        widget.shops.firstOrNull?['id'] as String?;
    vehicleId =
        widget.initialShop?['vehicle_id'] as String? ??
        controller.selectedVehicle?.id;
    restore();
  }

  Future<void> restore() async {
    try {
      final saved = await workspace.pending('outreach-draft');
      if (!active) return;
      setState(() {
        pending = saved;
        if (saved != null) {
          shopId = saved.body['shop_id'] as String?;
          vehicleId = saved.body['vehicle_id'] as String?;
          summary.text = textOf(saved.body, 'service_summary');
          note.text = textOf(saved.body, 'customer_message');
          slots = stringRows(saved.body, 'proposed_slots');
        }
        restoring = false;
      });
    } catch (e) {
      if (active) {
        setState(() {
          error = PlusController.readableError(e);
        });
      }
    }
  }

  @override
  void dispose() {
    summary.dispose();
    note.dispose();
    super.dispose();
  }

  Future<void> addSlot() async {
    final now = DateTime.now();
    final date = await showDatePicker(
      context: context,
      initialDate: now.add(const Duration(days: 1)),
      firstDate: now,
      lastDate: now.add(const Duration(days: 90)),
    );
    if (date == null || !mounted || !active) return;
    final time = await showTimePicker(
      context: context,
      initialTime: const TimeOfDay(hour: 9, minute: 0),
    );
    if (time == null || !active) return;
    final selected = DateTime(
      date.year,
      date.month,
      date.day,
      time.hour,
      time.minute,
    );
    final current = DateTime.now();
    if (!selected.isAfter(current.add(const Duration(hours: 1))) ||
        selected.isAfter(current.add(const Duration(days: 90)))) {
      setState(() {
        error =
            'Choose a time more than one hour and less than 90 days from now.';
      });
      return;
    }
    final value = offsetTimestamp(selected);
    if (slots.contains(value)) {
      setState(() {
        error = 'That time is already on your list.';
      });
      return;
    }
    setState(() {
      slots.add(value);
      error = null;
    });
  }

  Future<void> prepare() async {
    if (restoring) return;
    if (pending == null && !form.currentState!.validate()) return;
    if (slots.isEmpty || shopId == null) {
      setState(() {
        error = 'Choose a saved shop and at least one preferred time.';
      });
      return;
    }
    await perform(() async {
      final body =
          pending?.body ??
          <String, dynamic>{
            'shop_id': shopId,
            'vehicle_id': vehicleId,
            'service_summary': summary.text.trim(),
            'customer_message': note.text.trim(),
            'proposed_slots': List<String>.from(slots),
          };
      try {
        final result = await workspace.createDraft(body);
        if (!mounted || !active) return;
        Navigator.of(context).pushReplacement(
          MaterialPageRoute<void>(
            builder: (_) => ShopOutreachReview(
              controller: controller,
              draftId: result['id'] as String,
            ),
          ),
        );
      } catch (_) {
        if (active) {
          final saved = await workspace.pending('outreach-draft');
          if (active) {
            setState(() {
              pending = saved;
              if (saved == null) {
                if (!widget.shops.any((s) => s['id'] == shopId)) {
                  shopId = null;
                }
                if (controller.snapshot!.vehicle(vehicleId ?? '') == null) {
                  vehicleId = null;
                }
              }
            });
          }
        }
        rethrow;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    if (!current) return unavailable;
    final profile = controller.snapshot!.profile;
    final contactReady =
        profile.name.trim().isNotEmpty && profile.email.contains('@');
    final locked = busy || restoring || pending != null;
    return Scaffold(
      appBar: AppBar(title: const Text('Prepare a request')),
      body: PageBody(
        children: [
          const PageHeading(
            'Find a time that works.',
            'Choose up to three preferred times. The next step shows the exact message and saved contact details.',
          ),
          if (!contactReady) ...[
            const Text(
              'Save your name and account email in your profile before preparing a request.',
            ),
            OutlinedButton(
              onPressed: () => editProfile(context, controller),
              child: const Text('Edit saved profile'),
            ),
          ],
          if (pending != null)
            const Padding(
              padding: EdgeInsets.only(bottom: 18),
              child: Text(
                'Recovering your original draft. Its details stay fixed until the saved result is known.',
              ),
            ),
          if (restoring && error == null) const CircularProgressIndicator(),
          if (restoring && error != null)
            OutlinedButton(
              onPressed: restore,
              child: const Text('Retry draft recovery'),
            ),
          Form(
            key: form,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (pending != null)
                  ReviewBlock(
                    'Saved shop',
                    widget.shops
                            .where((s) => s['id'] == shopId)
                            .map((s) => textOf(s, 'name'))
                            .firstOrNull ??
                        'Previously selected shop',
                  )
                else
                  DropdownButtonFormField<String>(
                    initialValue: widget.shops.any((s) => s['id'] == shopId)
                        ? shopId
                        : null,
                    isExpanded: true,
                    decoration: const InputDecoration(labelText: 'Your shop'),
                    items: [
                      for (final shop in widget.shops)
                        DropdownMenuItem(
                          value: shop['id'] as String,
                          child: Text(
                            textOf(shop, 'name'),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                    ],
                    onChanged: locked
                        ? null
                        : (value) => setState(() {
                            shopId = value;
                          }),
                    validator: (value) =>
                        value == null ? 'Choose a saved shop.' : null,
                  ),
                const SizedBox(height: 18),
                if (pending != null)
                  ReviewBlock(
                    'Saved vehicle',
                    controller.snapshot!.vehicle(vehicleId ?? '')?.title ??
                        'No vehicle selected',
                  )
                else
                  SavedVehicleField(
                    controller: controller,
                    value: vehicleId,
                    optional: true,
                    optionalLabel: 'No specific vehicle',
                    enabled: !locked,
                    onChanged: (value) => setState(() {
                      vehicleId = value;
                    }),
                  ),
                const SizedBox(height: 18),
                TextFormField(
                  key: const Key('outreach-summary'),
                  controller: summary,
                  enabled: !locked,
                  maxLength: 500,
                  minLines: 2,
                  maxLines: 5,
                  decoration: const InputDecoration(
                    labelText: 'What service do you need?',
                  ),
                  validator: (value) => value == null || value.trim().isEmpty
                      ? 'Describe the service you need.'
                      : null,
                ),
                const SizedBox(height: 18),
                TextFormField(
                  key: const Key('outreach-note'),
                  controller: note,
                  enabled: !locked,
                  maxLength: 1000,
                  minLines: 2,
                  maxLines: 4,
                  decoration: const InputDecoration(
                    labelText: 'Message to the shop (optional)',
                  ),
                ),
                const SectionHeading('Preferred appointment times'),
                const Text(
                  'Times use your device’s local time zone. Each offer includes its UTC offset and will need the shop’s confirmation.',
                ),
                const SizedBox(height: 12),
                for (final slot in slots)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(child: Text(localSlotLabel(slot))),
                        if (!locked)
                          IconButton(
                            tooltip: 'Remove preferred time',
                            onPressed: () => setState(() {
                              slots.remove(slot);
                            }),
                            icon: const Icon(Icons.close),
                          ),
                      ],
                    ),
                  ),
                if (slots.length < 3 && !locked)
                  OutlinedButton.icon(
                    onPressed: addSlot,
                    icon: const Icon(Icons.add),
                    label: const Text('Add a preferred time'),
                  ),
                if (error != null) WorkspaceError(error!),
                const SizedBox(height: 24),
                BusyButton(
                  busy: busy,
                  label: pending != null
                      ? 'Recover saved review'
                      : 'Review request',
                  onPressed: contactReady && !restoring ? prepare : null,
                  icon: Icons.preview_outlined,
                ),
                const SizedBox(height: 12),
                const Text('Preparing a draft does not contact the shop.'),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class ShopOutreachReview extends StatefulWidget {
  const ShopOutreachReview({
    super.key,
    required this.controller,
    required this.draftId,
  });
  final PlusController controller;
  final String draftId;
  @override
  State<ShopOutreachReview> createState() => _ShopOutreachReviewState();
}

class _ShopOutreachReviewState extends WorkspaceState<ShopOutreachReview> {
  @override
  PlusController get controller => widget.controller;
  Json? draft;
  bool loading = true, consent = false, hasPending = false;
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
        controller.repository.getShopOutreach(widget.draftId),
        workspace.pending('outreach-authorize/${widget.draftId}'),
      ]);
      if (!active || generation != run) return;
      setState(() {
        draft = results[0] as Json;
        hasPending = results[1] != null;
      });
    } catch (e) {
      if (active && generation == run) {
        setState(() {
          error = PlusController.readableError(e);
        });
      }
    } finally {
      if (active && generation == run) {
        setState(() {
          loading = false;
        });
      }
    }
  }

  Future<void> authorize() async {
    if (draft == null || (!consent && !hasPending)) return;
    await perform(() async {
      try {
        final result = await workspace.authorize(draft!);
        if (active) {
          setState(() {
            draft = result;
            hasPending = false;
            consent = false;
          });
        }
      } catch (_) {
        if (active) {
          final saved = await workspace.pending(
            'outreach-authorize/${widget.draftId}',
          );
          if (active) {
            setState(() {
              hasPending = saved != null;
            });
          }
        }
        rethrow;
      }
    });
  }

  Future<void> callShop() async {
    final value = Uri.tryParse(textOf(draft!, 'call_link'));
    if (value == null ||
        value.scheme != 'tel' ||
        !RegExp(r'^\+?\d{7,15}$').hasMatch(value.path)) {
      return;
    }
    await perform(() async {
      if (!await launchUrl(value) && active) {
        setState(() {
          error =
              'Your device could not open the phone app. Call the shop using the number above.';
        });
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    if (!current) return unavailable;
    final value = draft;
    final email = value == null ? '' : textOf(value, 'recipient_email');
    final contact = Map<String, dynamic>.from(
      value?['shared_contact'] as Map? ?? {},
    );
    final canAuthorize =
        value?['status'] == 'draft' &&
        value?['delivery_status'] != 'local_preview';
    final expiredOffers =
        value != null &&
        stringRows(value, 'proposed_slots').any((slot) {
          final time = DateTime.tryParse(slot);
          return time == null ||
              !time.isAfter(DateTime.now().add(const Duration(hours: 1)));
        });
    return Scaffold(
      appBar: AppBar(
        title: const Text('Scheduling request'),
        actions: [
          IconButton(
            tooltip: 'Refresh request status',
            onPressed: busy || loading ? null : load,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: PageBody(
        children: [
          if (loading)
            const Padding(
              padding: EdgeInsets.all(24),
              child: Center(child: CircularProgressIndicator()),
            ),
          if (value != null) ...[
            PageHeading(textOf(value, 'shop_name'), _statusDescription(value)),
            StatusPill(outreachStatusLabel(value)),
            const SizedBox(height: 24),
            if (value['status'] == 'confirmed' &&
                textOf(value, 'confirmed_slot').isNotEmpty)
              ReviewBlock(
                'Confirmed appointment',
                localSlotLabel(textOf(value, 'confirmed_slot')),
              ),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    ReviewBlock(
                      email.isEmpty ? 'Shop phone' : 'Email recipient',
                      email.isEmpty ? textOf(value, 'recipient_phone') : email,
                    ),
                    if (email.isNotEmpty &&
                        textOf(value, 'recipient_phone').isNotEmpty)
                      ReviewBlock(
                        'Shop phone',
                        textOf(value, 'recipient_phone'),
                      ),
                    ReviewBlock(
                      'Your saved contact',
                      ['name', 'email', 'phone']
                          .map((key) => textOf(contact, key))
                          .where((text) => text.isNotEmpty)
                          .join('\n'),
                    ),
                    if (textOf(value, 'vehicle_summary').isNotEmpty)
                      ReviewBlock(
                        'Vehicle shared with this request',
                        textOf(value, 'vehicle_summary'),
                      ),
                    ReviewBlock(
                      'Preferred times in your local time zone',
                      stringRows(
                        value,
                        'proposed_slots',
                      ).map(localSlotLabel).join('\n\n'),
                    ),
                    ReviewBlock('Subject', textOf(value, 'subject')),
                    ReviewBlock(
                      'Message',
                      'Hello ${textOf(value, 'shop_name')},\n\n${textOf(value, 'message')}',
                    ),
                    Text(
                      email.isEmpty
                          ? 'This shop can be contacted by phone. The app will not send a message.'
                          : 'A secure appointment-response link and the saved contact details shown above are added to this message.',
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 20),
            if (canAuthorize && expiredOffers && !hasPending)
              const Text(
                'These preferred times are too near or have passed. Go back to My shops and prepare a new request with times more than one hour ahead.',
              ),
            if (canAuthorize && !expiredOffers && !hasPending) ...[
              CheckboxListTile(
                key: const Key('outreach-consent'),
                value: consent,
                onChanged: busy || loading
                    ? null
                    : (value) => setState(() {
                        consent = value == true;
                      }),
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                title: Text(
                  email.isEmpty
                      ? 'I reviewed these details and want to contact this shop by phone.'
                      : 'I authorize this exact request and sharing my saved contact and vehicle details with this shop.',
                ),
              ),
              const SizedBox(height: 12),
              BusyButton(
                busy: busy,
                label: email.isEmpty
                    ? 'Continue to call'
                    : 'Authorize and send request',
                onPressed: consent && !loading ? authorize : null,
                icon: email.isEmpty
                    ? Icons.phone_outlined
                    : Icons.send_outlined,
              ),
            ],
            if (hasPending) ...[
              const Text(
                'Your previous authorization is saved. Recover its result using the same details before preparing another request.',
              ),
              const SizedBox(height: 12),
              BusyButton(
                busy: busy,
                label: 'Recover authorized request',
                onPressed: loading ? null : authorize,
                icon: Icons.refresh,
              ),
            ],
            if (value['status'] == 'call_required')
              BusyButton(
                busy: busy,
                label: 'Call ${textOf(value, 'shop_name')}',
                onPressed: callShop,
                icon: Icons.phone_outlined,
              ),
          ],
          if (error != null) WorkspaceError(error!),
        ],
      ),
    );
  }
}
