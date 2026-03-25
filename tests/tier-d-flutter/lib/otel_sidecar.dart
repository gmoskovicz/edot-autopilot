/// OTel Sidecar client for Flutter.
///
/// Flutter has no official EDOT/OpenTelemetry SDK (as of 2025).
/// This thin client POSTs JSON to the otel-sidecar, which translates
/// to OTLP spans and forwards to Elastic APM.
///
/// Usage:
///   final otel = OtelSidecar(endpoint: 'https://your-api.example.com/otel');
///   await otel.event('checkout.complete', {
///     'order.value_usd': 42.00,
///     'customer.tier': 'enterprise',
///   });

library otel_sidecar;

import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:uuid/uuid.dart';

class OtelSidecar {
  final String endpoint;
  final Duration timeout;
  static const _uuid = Uuid();

  const OtelSidecar({
    required this.endpoint,
    this.timeout = const Duration(seconds: 2),
  });

  /// Fire-and-forget event span.
  /// Never throws — telemetry must not crash the app.
  Future<void> event(String name, [Map<String, dynamic>? attributes]) async {
    await _post({
      'action': 'event',
      'name': name,
      'attributes': attributes ?? {},
    });
  }

  /// Start a multi-step span. Returns a [SpanHandle] to close later.
  Future<SpanHandle> startSpan(
    String name, {
    Map<String, dynamic>? attributes,
    String? traceparent,
  }) async {
    final body = <String, dynamic>{
      'action': 'start_span',
      'name': name,
      'attributes': attributes ?? {},
      'span_id': _uuid.v4(),
    };
    if (traceparent != null) body['traceparent'] = traceparent;

    final resp = await _post(body);
    final spanId = resp?['span_id'] as String? ?? '';
    final tp = resp?['traceparent'] as String?;
    return SpanHandle(sidecar: this, spanId: spanId, traceparent: tp);
  }

  Future<void> endSpan(
    String spanId, {
    Map<String, dynamic>? attributes,
    String? error,
  }) async {
    final body = <String, dynamic>{
      'action': 'end_span',
      'span_id': spanId,
      'attributes': attributes ?? {},
    };
    if (error != null) body['error'] = error;
    await _post(body);
  }

  Future<Map<String, dynamic>?> _post(Map<String, dynamic> body) async {
    try {
      final response = await http
          .post(
            Uri.parse(endpoint),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode(body),
          )
          .timeout(timeout);
      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
    } catch (_) {
      // Telemetry failures must never surface to the user
    }
    return null;
  }
}

/// Handle for a started span — call [end] when the operation completes.
class SpanHandle {
  final OtelSidecar sidecar;
  final String spanId;
  final String? traceparent;
  bool _ended = false;

  SpanHandle({
    required this.sidecar,
    required this.spanId,
    this.traceparent,
  });

  Future<void> end({Map<String, dynamic>? attributes, String? error}) async {
    if (_ended) return;
    _ended = true;
    await sidecar.endSpan(spanId, attributes: attributes, error: error);
  }
}
