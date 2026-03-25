/**
 * ShopApp — React Native (TypeScript)
 *
 * No observability. Run `Observe this project.` to add OpenTelemetry RUM/APM.
 *
 * Expected: agent adds @elastic/opentelemetry-react-native or
 * @opentelemetry/sdk-trace-web + React Native bridge.
 */

import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  FlatList,
  StyleSheet,
  ActivityIndicator,
  Alert,
} from 'react-native';

interface Product {
  id: string;
  name: string;
  price: number;
  inStock: boolean;
}

interface CartItem {
  product: Product;
  qty: number;
}

const API_BASE = 'https://api.shopapp.io/v2';

async function fetchProducts(): Promise<Product[]> {
  const resp = await fetch(`${API_BASE}/products`);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function createOrder(items: CartItem[], customerId: string): Promise<{ orderId: string }> {
  const resp = await fetch(`${API_BASE}/orders`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      customer_id: customerId,
      items: items.map(i => ({ product_id: i.product.id, qty: i.qty, price: i.product.price })),
    }),
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

export default function App() {
  const [products, setProducts]   = useState<Product[]>([]);
  const [cart, setCart]           = useState<CartItem[]>([]);
  const [loading, setLoading]     = useState(true);
  const [screen, setScreen]       = useState<'home' | 'cart' | 'confirm'>('home');
  const [orderId, setOrderId]     = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    fetchProducts()
      .then(setProducts)
      .catch(err => Alert.alert('Error', err.message))
      .finally(() => setLoading(false));
  }, []);

  function addToCart(product: Product) {
    setCart(prev => {
      const existing = prev.find(i => i.product.id === product.id);
      if (existing) {
        return prev.map(i =>
          i.product.id === product.id ? { ...i, qty: i.qty + 1 } : i
        );
      }
      return [...prev, { product, qty: 1 }];
    });
  }

  async function submitOrder() {
    try {
      setLoading(true);
      const result = await createOrder(cart, 'user_anonymous');
      setOrderId(result.orderId);
      setCart([]);
      setScreen('confirm');
    } catch (err: any) {
      Alert.alert('Order failed', err.message);
    } finally {
      setLoading(false);
    }
  }

  const totalUsd = cart.reduce((s, i) => s + i.product.price * i.qty, 0);

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  if (screen === 'confirm') {
    return (
      <View style={styles.center}>
        <Text style={styles.heading}>Order Confirmed!</Text>
        <Text>Order ID: {orderId}</Text>
        <TouchableOpacity onPress={() => setScreen('home')} style={styles.btn}>
          <Text style={styles.btnText}>Continue Shopping</Text>
        </TouchableOpacity>
      </View>
    );
  }

  if (screen === 'cart') {
    return (
      <View style={styles.container}>
        <Text style={styles.heading}>Cart ({cart.length} items)</Text>
        <FlatList
          data={cart}
          keyExtractor={i => i.product.id}
          renderItem={({ item }) => (
            <View style={styles.row}>
              <Text>{item.product.name} x{item.qty}</Text>
              <Text>${(item.product.price * item.qty).toFixed(2)}</Text>
            </View>
          )}
        />
        <Text style={styles.total}>Total: ${totalUsd.toFixed(2)}</Text>
        <TouchableOpacity onPress={submitOrder} style={styles.btn}>
          <Text style={styles.btnText}>Place Order</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => setScreen('home')} style={[styles.btn, styles.btnSecondary]}>
          <Text style={styles.btnText}>Back</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.heading}>ShopApp</Text>
      <FlatList
        data={products}
        keyExtractor={p => p.id}
        renderItem={({ item: product }) => (
          <View style={styles.row}>
            <View>
              <Text style={styles.productName}>{product.name}</Text>
              <Text>${product.price.toFixed(2)}</Text>
            </View>
            <TouchableOpacity
              onPress={() => addToCart(product)}
              style={[styles.btn, !product.inStock && styles.btnDisabled]}
              disabled={!product.inStock}
            >
              <Text style={styles.btnText}>{product.inStock ? 'Add' : 'OOS'}</Text>
            </TouchableOpacity>
          </View>
        )}
      />
      {cart.length > 0 && (
        <TouchableOpacity onPress={() => setScreen('cart')} style={styles.btn}>
          <Text style={styles.btnText}>View Cart ({cart.length})</Text>
        </TouchableOpacity>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container:    { flex: 1, padding: 16, paddingTop: 60 },
  center:       { flex: 1, alignItems: 'center', justifyContent: 'center' },
  heading:      { fontSize: 24, fontWeight: 'bold', marginBottom: 16 },
  row:          { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 8, borderBottomWidth: 1, borderColor: '#eee' },
  productName:  { fontWeight: '600' },
  total:        { fontSize: 18, fontWeight: 'bold', marginVertical: 16 },
  btn:          { backgroundColor: '#007AFF', padding: 12, borderRadius: 8, marginTop: 8, alignItems: 'center' },
  btnSecondary: { backgroundColor: '#666' },
  btnDisabled:  { backgroundColor: '#ccc' },
  btnText:      { color: '#fff', fontWeight: '600' },
});
