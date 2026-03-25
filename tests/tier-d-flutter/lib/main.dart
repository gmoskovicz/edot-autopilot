import 'package:flutter/material.dart';
import 'otel_sidecar.dart';

// The sidecar URL — in production this would point to a sidecar
// running alongside your backend, exposed via your API domain.
// For local dev, use an HTTP tunnel or run the sidecar on your dev machine.
const _sidecarUrl = String.fromEnvironment(
  'OTEL_SIDECAR_URL',
  defaultValue: 'http://localhost:9411',
);

final _otel = OtelSidecar(endpoint: _sidecarUrl);

void main() {
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'EDOT Flutter Tier D Demo',
      home: const CheckoutScreen(),
    );
  }
}

class CheckoutScreen extends StatefulWidget {
  const CheckoutScreen({super.key});

  @override
  State<CheckoutScreen> createState() => _CheckoutScreenState();
}

class _CheckoutScreenState extends State<CheckoutScreen> {
  String _status = 'Ready';

  Future<void> _simulateCheckout() async {
    setState(() => _status = 'Processing...');

    // Start a checkout span — spans stay open until the checkout completes
    final span = await _otel.startSpan('checkout.initiated', attributes: {
      'customer.tier': 'enterprise',
      'cart.item_count': 3,
      'cart.value_usd': 4200.00,
      'platform': 'flutter',
    });

    await Future.delayed(const Duration(milliseconds: 500));

    // Nested span for payment
    await _otel.event('payment.processing', {
      'payment.method': 'card',
      'payment.amount_usd': 4200.00,
    });

    await Future.delayed(const Duration(milliseconds: 300));

    // End the checkout span with result
    await span.end(attributes: {
      'checkout.status': 'success',
      'order.id': 'ORD-FLUTTER-001',
      'order.value_usd': 4200.00,
    });

    setState(() => _status = 'Order confirmed! Check Kibana APM → flutter-tier-d');
  }

  Future<void> _simulateError() async {
    setState(() => _status = 'Simulating error...');

    final span = await _otel.startSpan('checkout.initiated', attributes: {
      'customer.tier': 'free',
      'cart.value_usd': 4200.00,
    });

    await Future.delayed(const Duration(milliseconds: 200));

    await span.end(
      attributes: {'fraud.score': 0.92, 'fraud.decision': 'blocked'},
      error: 'Order blocked by fraud check',
    );

    setState(() => _status = 'Blocked! Error span sent to Elastic.');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Flutter EDOT Tier D Demo')),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(_status, style: Theme.of(context).textTheme.bodyLarge),
            const SizedBox(height: 32),
            ElevatedButton(
              onPressed: _simulateCheckout,
              child: const Text('Simulate Checkout (Success)'),
            ),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: _simulateError,
              style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
              child: const Text('Simulate Checkout (Fraud Block)'),
            ),
          ],
        ),
      ),
    );
  }
}
