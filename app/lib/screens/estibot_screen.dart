import 'package:flutter/material.dart';
import '../domain/models.dart';
import '../state/plus_controller.dart';
import '../theme.dart';
import '../widgets/common.dart';
import 'find_help_screen.dart';
import 'request_sheet.dart';

class EstibotScreen extends StatefulWidget {
  const EstibotScreen({super.key, required this.controller});
  final PlusController controller;
  @override
  State<EstibotScreen> createState() => _EstibotScreenState();
}

class _EstibotScreenState extends State<EstibotScreen> {
  final message = TextEditingController();
  final scroll = ScrollController();
  @override
  void dispose() {
    message.dispose();
    scroll.dispose();
    super.dispose();
  }

  Future<void> send([String? prompt]) async {
    final value = prompt ?? message.text;
    if (value.trim().isEmpty || widget.controller.asking) return;
    message.clear();
    await widget.controller.ask(value);
    if (mounted && scroll.hasClients) {
      await scroll.animateTo(
        scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 220),
        curve: Curves.easeOut,
      );
    }
  }

  @override
  Widget build(BuildContext context) => Column(
    children: [
      Expanded(
        child: SingleChildScrollView(
          controller: scroll,
          keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 20),
          child: Align(
            alignment: Alignment.topCenter,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 760),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const PageHeading(
                    'A little clarity.\nThe right connection.',
                    'Ask Estibot about your car or find someone to help.',
                  ),
                  VehiclePicker(controller: widget.controller),
                  const SizedBox(height: 20),
                  if (widget.controller.messages.isEmpty) ...[
                    Container(
                      padding: const EdgeInsets.all(22),
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(20),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const CircleAvatar(
                            backgroundColor: Color(0xFFE5F5F2),
                            child: Icon(
                              Icons.support_agent,
                              color: Color(0xFF08796D),
                            ),
                          ),
                          const SizedBox(height: 16),
                          Text(
                            'What does your car need?',
                            style: Theme.of(context).textTheme.titleLarge,
                          ),
                          const SizedBox(height: 8),
                          const Text(
                            'Tell me what’s happening. I can explain common car-care topics and help you request the right technician.',
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 18),
                    for (final prompt in [
                      'Find mobile dent repair',
                      'Help me understand an estimate',
                      'How do I check tire pressure?',
                    ])
                      Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: SizedBox(
                          width: double.infinity,
                          child: OutlinedButton(
                            onPressed: () => send(prompt),
                            style: OutlinedButton.styleFrom(
                              alignment: Alignment.centerLeft,
                              backgroundColor: Colors.white,
                            ),
                            child: Padding(
                              padding: const EdgeInsets.symmetric(vertical: 4),
                              child: Text(prompt),
                            ),
                          ),
                        ),
                      ),
                  ],
                  for (final entry in widget.controller.messages)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 18),
                      child: Column(
                        crossAxisAlignment: entry.isUser
                            ? CrossAxisAlignment.end
                            : CrossAxisAlignment.start,
                        children: [
                          Align(
                            alignment: entry.isUser
                                ? Alignment.centerRight
                                : Alignment.centerLeft,
                            child: Container(
                              padding: const EdgeInsets.all(17),
                              decoration: BoxDecoration(
                                color: entry.isUser
                                    ? PlusColors.navy
                                    : Colors.white,
                                borderRadius: BorderRadius.circular(18),
                              ),
                              child: Text(
                                entry.text,
                                style: TextStyle(
                                  color: entry.isUser
                                      ? Colors.white
                                      : PlusColors.ink,
                                  height: 1.5,
                                ),
                              ),
                            ),
                          ),
                          if (!entry.isUser) ...[
                            for (final provider in entry.answer!.providers)
                              Padding(
                                padding: const EdgeInsets.only(top: 12),
                                child: ProviderCard(
                                  provider: provider,
                                  onRequest: () => requestProvider(
                                    context,
                                    widget.controller,
                                    provider,
                                    specialty: entry.answer!.specialty,
                                    description:
                                        widget.controller.messages
                                            .where((e) => e.isUser)
                                            .lastOrNull
                                            ?.text ??
                                        '',
                                  ),
                                ),
                              ),
                            for (final video in entry.answer!.videos)
                              Padding(
                                padding: const EdgeInsets.only(top: 10),
                                child: OutlinedButton.icon(
                                  onPressed: () => openExternal(
                                    context,
                                    textOf(video, 'url'),
                                    youtubeOnly: true,
                                  ),
                                  icon: const Icon(Icons.play_circle_outline),
                                  label: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text(textOf(video, 'title')),
                                      Text(
                                        textOf(video, 'source'),
                                        style: Theme.of(
                                          context,
                                        ).textTheme.bodySmall,
                                      ),
                                    ],
                                  ),
                                ),
                              ),
                          ],
                        ],
                      ),
                    ),
                  if (widget.controller.asking)
                    const Padding(
                      padding: EdgeInsets.all(12),
                      child: Row(
                        children: [
                          SizedBox.square(
                            dimension: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          ),
                          SizedBox(width: 12),
                          Text('Estibot is thinking…'),
                        ],
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
      Container(
        color: Colors.white,
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Expanded(
              child: TextField(
                key: const Key('assistant-message'),
                controller: message,
                minLines: 1,
                maxLines: 4,
                maxLength: 2000,
                textInputAction: TextInputAction.send,
                onSubmitted: (_) => send(),
                decoration: const InputDecoration(
                  hintText: 'Ask about your car…',
                  counterText: '',
                ),
              ),
            ),
            const SizedBox(width: 10),
            IconButton.filled(
              key: const Key('assistant-send'),
              tooltip: 'Send message',
              onPressed: widget.controller.asking ? null : send,
              icon: const Icon(Icons.arrow_upward),
              style: IconButton.styleFrom(minimumSize: const Size(48, 48)),
            ),
          ],
        ),
      ),
    ],
  );
}
