import 'package:flutter/material.dart';
import '../domain/models.dart';

/// Requests that were never sent can be discarded outright.
const discardableOutreachStatuses = {
  'draft',
  'call_required',
  'delivery_failed',
};

/// Requests already on their way, or waiting on the shop, can be withdrawn.
const withdrawableOutreachStatuses = {
  'queued',
  'delivery_unknown',
  'waiting_for_reply',
};

bool outreachDiscardable(Json draft) =>
    discardableOutreachStatuses.contains(draft['status']) &&
    !(draft['status'] == 'draft' &&
        draft['delivery_status'] == 'local_preview');

bool outreachWithdrawable(Json draft) =>
    withdrawableOutreachStatuses.contains(draft['status']) ||
    (draft['status'] == 'draft' && draft['delivery_status'] == 'local_preview');

Future<bool> confirmDiscardOutreach(BuildContext context) async =>
    await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Discard this request?'),
        content: const Text(
          'It was never sent. You can prepare a new one any time.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Keep'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Discard'),
          ),
        ],
      ),
    ) ==
    true;

Future<bool> confirmWithdrawOutreach(BuildContext context) async =>
    await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Withdraw this request?'),
        content: const Text(
          'The shop’s confirmation link stops working. No message is sent to the shop, so call them if a time was already discussed.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Keep'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Withdraw'),
          ),
        ],
      ),
    ) ==
    true;

Future<bool> confirmDiscardDeviceDraft(BuildContext context) async =>
    await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Discard the saved draft?'),
        content: const Text(
          'Its details are removed from this device. Nothing was sent to the shop.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Keep'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Discard'),
          ),
        ],
      ),
    ) ==
    true;
