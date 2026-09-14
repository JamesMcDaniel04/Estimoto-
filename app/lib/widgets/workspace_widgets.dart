import 'package:flutter/material.dart';
import '../domain/models.dart';
import '../state/plus_controller.dart';
import '../services/customer_workspace.dart';

abstract class WorkspaceState<T extends StatefulWidget> extends State<T> {
  PlusController get controller;
  late final CustomerWorkspace workspace;
  bool get current =>
      identical(controller, workspace.controller) && workspace.current;
  bool get active => mounted && current;
  String? error;
  bool busy = false;
  @override
  void initState() {
    super.initState();
    workspace = CustomerWorkspace.forController(controller);
    controller.addListener(changed);
  }

  void changed() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    workspace.controller.removeListener(changed);
    super.dispose();
  }

  Future<void> perform(Future<void> Function() action) async {
    if (!active || busy) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await action();
    } catch (e) {
      if (active) {
        setState(() {
          error = PlusController.readableError(e);
        });
      }
    } finally {
      if (active) {
        setState(() {
          busy = false;
        });
      }
    }
  }

  Widget get unavailable => const UnavailableRecordScreen(
    message: 'Sign in to view your saved details.',
  );
}

class UnavailableRecordScreen extends StatelessWidget {
  const UnavailableRecordScreen({
    super.key,
    this.title = 'Saved details',
    this.message = 'This item is no longer available.',
  });
  final String title, message;

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text(title)),
    body: SafeArea(
      child: Center(
        child: Padding(padding: const EdgeInsets.all(24), child: Text(message)),
      ),
    ),
  );
}

class WorkspaceError extends StatelessWidget {
  const WorkspaceError(this.message, {super.key});
  final String message;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 12),
    child: Semantics(
      liveRegion: true,
      child: Text(
        message,
        style: TextStyle(color: Theme.of(context).colorScheme.error),
      ),
    ),
  );
}

class ReviewBlock extends StatelessWidget {
  const ReviewBlock(this.title, this.value, {super.key});
  final String title, value;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 18),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 5),
        SelectableText(value.isEmpty ? 'Not provided' : value),
      ],
    ),
  );
}

class SavedVehicleField extends StatelessWidget {
  const SavedVehicleField({
    super.key,
    required this.controller,
    required this.value,
    required this.onChanged,
    this.optional = false,
    this.optionalLabel = 'All my vehicles',
    this.enabled = true,
  });
  final PlusController controller;
  final String? value;
  final ValueChanged<String?> onChanged;
  final bool optional, enabled;
  final String optionalLabel;
  @override
  Widget build(BuildContext context) {
    final selected = controller.snapshot!.vehicles.any((v) => v.id == value)
        ? value
        : null;
    return DropdownButtonFormField<String>(
      key: ValueKey('saved-vehicle-$value-$enabled'),
      initialValue: selected ?? '',
      isExpanded: true,
      decoration: const InputDecoration(labelText: 'Saved vehicle'),
      items: [
        if (optional || selected == null)
          DropdownMenuItem(
            value: '',
            child: Text(optional ? optionalLabel : 'Choose a vehicle'),
          ),
        for (final vehicle in controller.snapshot!.vehicles)
          DropdownMenuItem(
            value: vehicle.id,
            child: Text(vehicle.title, overflow: TextOverflow.ellipsis),
          ),
      ],
      onChanged: enabled ? (id) => onChanged(id == '' ? null : id) : null,
      validator: (id) => !optional && (id == null || id.isEmpty)
          ? 'Choose a saved vehicle.'
          : null,
    );
  }
}

String serviceName(String value) =>
    const {
      'oil_change': 'Oil change',
      'tires': 'Tires',
      'brakes': 'Brakes',
      'battery': 'Battery',
      'maintenance': 'Maintenance',
      'repair': 'Repair',
      'modification': 'Modification',
      'diagnostics': 'Diagnostics',
      'collision': 'Collision repair',
      'pdr': 'Dent repair',
      'other': 'Other service',
    }[value] ??
    value;

List<String> stringRows(Json value, String key) =>
    (value[key] as List? ?? []).map((v) => v.toString()).toList();
