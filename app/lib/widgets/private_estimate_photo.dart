import 'dart:typed_data';
import 'package:flutter/material.dart';
import '../state/plus_controller.dart';

/// Bytes are fetched with the signed-in repository, never with URL credentials.
class PrivateEstimatePhoto extends StatefulWidget {
  const PrivateEstimatePhoto({
    super.key,
    required this.controller,
    required this.customerId,
    required this.estimateId,
    required this.photoId,
    required this.label,
    this.large = false,
  });
  final PlusController controller;
  final String customerId, estimateId, photoId, label;
  final bool large;
  @override
  State<PrivateEstimatePhoto> createState() => _PrivateEstimatePhotoState();
}

class _PrivateEstimatePhotoState extends State<PrivateEstimatePhoto> {
  late Future<Uint8List> _bytes;
  MemoryImage? _image;
  @override
  void initState() {
    super.initState();
    _bytes = _load();
  }

  Future<Uint8List> _load() async {
    if (!widget.controller.isCurrentCustomer(widget.customerId)) {
      throw StateError('scope');
    }
    final bytes = await widget.controller.repository.getPhoto(
      widget.estimateId,
      widget.photoId,
    );
    if (!widget.controller.isCurrentCustomer(widget.customerId)) {
      throw StateError('scope');
    }
    return bytes;
  }

  @override
  void dispose() {
    _image?.evict();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.controller,
    builder: (context, _) =>
        !widget.controller.isCurrentCustomer(widget.customerId)
        ? const SizedBox.shrink()
        : FutureBuilder<Uint8List>(
            future: _bytes,
            builder: (context, state) {
              if (!widget.controller.isCurrentCustomer(widget.customerId)) {
                return const SizedBox.shrink();
              }
              if (state.hasError) {
                return Center(
                  child: IconButton(
                    tooltip: 'Reload ${widget.label} photo',
                    icon: const Icon(Icons.refresh),
                    onPressed: () => setState(() => _bytes = _load()),
                  ),
                );
              }
              if (!state.hasData) {
                return const Center(
                  child: SizedBox.square(
                    dimension: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                );
              }
              _image ??= MemoryImage(state.data!);
              final photo = Image(
                image: _image!,
                fit: widget.large ? BoxFit.contain : BoxFit.cover,
                width: double.infinity,
                height: double.infinity,
                semanticLabel: widget.label,
                errorBuilder: (_, _, _) =>
                    const Icon(Icons.broken_image_outlined),
              );
              if (widget.large) return InteractiveViewer(child: photo);
              return InkWell(
                onTap: () => showDialog<void>(
                  context: context,
                  builder: (context) => Dialog.fullscreen(
                    child: Scaffold(
                      appBar: AppBar(
                        title: Text(widget.label),
                        leading: IconButton(
                          tooltip: 'Close photo',
                          icon: const Icon(Icons.close),
                          onPressed: () => Navigator.pop(context),
                        ),
                      ),
                      body: PrivateEstimatePhoto(
                        controller: widget.controller,
                        customerId: widget.customerId,
                        estimateId: widget.estimateId,
                        photoId: widget.photoId,
                        label: widget.label,
                        large: true,
                      ),
                    ),
                  ),
                ),
                child: photo,
              );
            },
          ),
  );
}
