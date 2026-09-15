import 'package:flutter/material.dart';
import '../state/plus_controller.dart';
import '../theme.dart';
import '../widgets/common.dart';
import 'estimate_forms.dart';

class EstimatesScreen extends StatelessWidget {
  const EstimatesScreen({super.key, required this.controller});
  final PlusController controller;
  @override
  Widget build(BuildContext context) {
    final data = controller.snapshot!;
    final estimates = data.estimates
        .where((e) => e.discipline == controller.discipline)
        .toList();
    final otherCount = data.estimates.length - estimates.length;
    final pdr = controller.discipline == 'pdr';
    final currentLabel = pdr ? 'PDR' : 'Collision';
    final otherLabel = pdr ? 'Collision' : 'PDR';
    return PageBody(
      onRefresh: controller.refresh,
      children: [
        const PageHeading(
          'Know where you stand.',
          'Your estimates, photos and next steps.',
        ),
        SizedBox(
          width: double.infinity,
          child: SegmentedButton<String>(
            segments: const [
              ButtonSegment(
                value: 'pdr',
                label: Text('PDR'),
                icon: Icon(Icons.auto_fix_high_outlined),
              ),
              ButtonSegment(
                value: 'collision',
                label: Text('Collision'),
                icon: Icon(Icons.car_crash_outlined),
              ),
            ],
            selected: {controller.discipline},
            onSelectionChanged: (value) =>
                controller.selectDiscipline(value.first),
          ),
        ),
        const SizedBox(height: 20),
        SizedBox(
          width: double.infinity,
          child: FilledButton.icon(
            onPressed: () => newEstimate(context, controller),
            icon: const Icon(Icons.add_a_photo_outlined),
            label: const Text('Start an estimate'),
          ),
        ),
        const SectionHeading('Your estimates'),
        if (estimates.isEmpty)
          EmptyState(
            icon: Icons.receipt_long_outlined,
            title: 'Your next estimate starts here',
            message: otherCount > 0
                ? 'No $currentLabel estimates yet. You have $otherCount under $otherLabel.'
                : 'Choose your saved vehicle, tell us about the damage and add a few photos.',
            action: otherCount > 0 ? 'Show $otherLabel' : null,
            onAction: otherCount > 0
                ? () => controller.selectDiscipline(pdr ? 'collision' : 'pdr')
                : null,
          )
        else
          for (final estimate in estimates)
            Padding(
              padding: const EdgeInsets.only(bottom: 14),
              child: Card(
                child: InkWell(
                  borderRadius: BorderRadius.circular(20),
                  onTap: () => Navigator.push(
                    context,
                    MaterialPageRoute<void>(
                      builder: (_) => EstimateDetailScreen(
                        controller: controller,
                        estimateId: estimate.id,
                      ),
                    ),
                  ),
                  child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const Icon(
                              Icons.receipt_long_outlined,
                              color: PlusColors.blue,
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Text(
                                data.vehicle(estimate.vehicleId)?.title ??
                                    'Your vehicle',
                                style: const TextStyle(
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ),
                            const Icon(
                              Icons.chevron_right,
                              color: PlusColors.muted,
                            ),
                          ],
                        ),
                        const SizedBox(height: 16),
                        Text(
                          estimate.description,
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                        const SizedBox(height: 14),
                        Wrap(
                          spacing: 12,
                          runSpacing: 10,
                          crossAxisAlignment: WrapCrossAlignment.center,
                          children: [
                            StatusPill(
                              estimate.statusLabel,
                              color: estimate.status == 'approved'
                                  ? const Color(0xFF08796D)
                                  : PlusColors.blue,
                            ),
                            if (estimate.amountCents != null)
                              Text(
                                moneyText(estimate.amountCents!),
                                style: const TextStyle(
                                  fontSize: 22,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                          ],
                        ),
                        if (estimate.providerName.isNotEmpty ||
                            estimate.updatedAt.isNotEmpty ||
                            estimate.photos.isNotEmpty) ...[
                          const SizedBox(height: 12),
                          Text(
                            [
                              if (estimate.providerName.isNotEmpty)
                                estimate.providerName,
                              if (estimate.photos.isNotEmpty)
                                '${estimate.photos.length} photo${estimate.photos.length == 1 ? '' : 's'}',
                              if (estimate.updatedAt.isNotEmpty)
                                'Updated ${dateText(estimate.updatedAt)}',
                            ].join(' · '),
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
              ),
            ),
      ],
    );
  }
}
