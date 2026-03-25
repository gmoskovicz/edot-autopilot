// ShopApp — Flutter (Dart)
//
// No observability. Run `Observe this project.` to add OpenTelemetry.
//
// Expected: agent adds opentelemetry_dart or elastic_apm_agent Flutter plugin.

import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

void main() => runApp(const ShopApp());

class ShopApp extends StatelessWidget {
  const ShopApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'ShopApp',
      theme: ThemeData(colorSchemeSeed: Colors.blue),
      home: const HomeScreen(),
    );
  }
}

class Product {
  final String id, name;
  final double price;
  final bool inStock;
  const Product({required this.id, required this.name,
                 required this.price, required this.inStock});
  factory Product.fromJson(Map<String, dynamic> j) => Product(
      id: j['id'], name: j['name'],
      price: (j['price'] as num).toDouble(), inStock: j['in_stock'] ?? true);
}

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  List<Product> products = [];
  List<Map<String, dynamic>> cart = [];
  bool loading = true;

  @override
  void initState() {
    super.initState();
    _loadProducts();
  }

  Future<void> _loadProducts() async {
    final resp = await http.get(Uri.parse('https://api.shopapp.io/v2/products'));
    if (resp.statusCode == 200) {
      final List data = jsonDecode(resp.body);
      setState(() {
        products = data.map((e) => Product.fromJson(e)).toList();
        loading = false;
      });
    }
  }

  void _addToCart(Product p) {
    setState(() {
      final idx = cart.indexWhere((i) => i['id'] == p.id);
      if (idx >= 0) {
        cart[idx]['qty']++;
      } else {
        cart.add({'id': p.id, 'name': p.name, 'price': p.price, 'qty': 1});
      }
    });
  }

  Future<void> _checkout() async {
    final resp = await http.post(
      Uri.parse('https://api.shopapp.io/v2/orders'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'customer_id': 'flutter_user', 'items': cart}),
    );
    if (resp.statusCode == 201) {
      setState(() => cart = []);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Order placed!')));
    }
  }

  @override
  Widget build(BuildContext context) {
    if (loading) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    return Scaffold(
      appBar: AppBar(title: const Text('ShopApp'),
                     actions: [if (cart.isNotEmpty)
                       IconButton(icon: Badge(label: Text('${cart.length}'),
                                              child: const Icon(Icons.shopping_cart)),
                                  onPressed: _checkout)]),
      body: ListView.builder(
        itemCount: products.length,
        itemBuilder: (_, i) {
          final p = products[i];
          return ListTile(
            title: Text(p.name),
            subtitle: Text('\$${p.price.toStringAsFixed(2)}'),
            trailing: ElevatedButton(
              onPressed: p.inStock ? () => _addToCart(p) : null,
              child: Text(p.inStock ? 'Add' : 'OOS')),
          );
        },
      ),
    );
  }
}
