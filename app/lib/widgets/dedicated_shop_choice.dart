import 'package:flutter/material.dart';
import '../domain/models.dart';
import '../state/plus_controller.dart';
import '../services/customer_workspace.dart';

const discoverySpecialties = ['pdr', 'collision', 'maintenance', 'mechanical'];

Future<bool> chooseDedicatedShop(
  BuildContext context,
  PlusController controller, {
  required String source,
  required String sourceId,
  required String vehicleId,
}) async {
  final owner = CustomerWorkspace.forController(controller);
  bool valid() =>
      context.mounted &&
      owner.current &&
      controller.selectedVehicle?.id == vehicleId;
  if (!valid()) return false;
  final existing = await controller.repository.listDiscoveryFavorites(
    vehicleId,
  );
  if (!context.mounted || !valid()) return false;
  bool matches(String type) => existing.any(
    (f) =>
        f['specialty'] == type &&
        f['source'] == source &&
        f['source_id'] == sourceId,
  );
  final choice = await showDialog<String>(
    context: context,
    builder: (context) => ListenableBuilder(
      listenable: controller,
      builder: (context, _) => !valid()
          ? AlertDialog(
              content: const Text(
                'Your vehicle or account changed. Close this choice and start again.',
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text('Close'),
                ),
              ],
            )
          : SimpleDialog(
              title: Text(
                'Dedicated shop for ${controller.snapshot!.vehicle(vehicleId)?.title ?? 'your vehicle'}',
              ),
              children: [
                const Padding(
                  padding: EdgeInsets.fromLTRB(24, 0, 24, 12),
                  child: Text(
                    'Choose the work you use this shop for. Saving replaces your previous choice for that work. This stays private and does not verify services or contact the shop.',
                  ),
                ),
                for (final type in discoverySpecialties)
                  SimpleDialogOption(
                    onPressed: () => Navigator.pop(context, type),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      child: Text(
                        '${matches(type) ? 'Remove: ' : 'Save for: '}${specialtyLabel(type)}',
                      ),
                    ),
                  ),
              ],
            ),
    ),
  );
  if (choice == null || !valid()) return false;
  if (matches(choice)) {
    await controller.repository.deleteDiscoveryFavorite(choice, vehicleId);
  } else {
    await controller.repository.saveDiscoveryFavorite(choice, {
      'vehicle_id': vehicleId,
      'source': source,
      'source_id': sourceId,
    });
  }
  return valid();
}
