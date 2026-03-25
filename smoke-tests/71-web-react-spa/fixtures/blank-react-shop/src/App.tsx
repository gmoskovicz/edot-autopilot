// ShopClient — React SPA (TypeScript)
//
// No observability. Run `Observe this project.` to add OpenTelemetry Web SDK.
//
// Expected: agent adds @opentelemetry/sdk-trace-web + instrumentation-fetch + instrumentation-document-load.

import { useState, useEffect } from 'react';

interface Product { id: string; name: string; price: number; in_stock: boolean; }
interface CartItem  { product: Product; qty: number; }

const API = 'https://api.shopapp.io/v2';

export default function App() {
  const [products, setProducts] = useState<Product[]>([]);
  const [cart, setCart]         = useState<CartItem[]>([]);
  const [page, setPage]         = useState<'home'|'cart'|'confirm'>('home');
  const [orderId, setOrderId]   = useState<string|null>(null);

  useEffect(() => {
    fetch(`${API}/products`)
      .then(r => r.json())
      .then(setProducts)
      .catch(console.error);
  }, []);

  function addToCart(p: Product) {
    setCart(prev => {
      const i = prev.findIndex(x => x.product.id === p.id);
      return i >= 0
        ? prev.map((x, idx) => idx === i ? {...x, qty: x.qty + 1} : x)
        : [...prev, { product: p, qty: 1 }];
    });
  }

  async function checkout() {
    const res = await fetch(`${API}/orders`, {
      method:  'POST',
      headers: {'Content-Type': 'application/json'},
      body:    JSON.stringify({ customer_id: 'spa_user', items: cart }),
    });
    if (res.ok) {
      const data = await res.json();
      setOrderId(data.order_id);
      setCart([]);
      setPage('confirm');
    }
  }

  const total = cart.reduce((s, i) => s + i.product.price * i.qty, 0);

  if (page === 'confirm') return (
    <div>
      <h1>Order confirmed: {orderId}</h1>
      <button onClick={() => setPage('home')}>Continue Shopping</button>
    </div>
  );

  if (page === 'cart') return (
    <div>
      <h1>Cart</h1>
      {cart.map(i => <div key={i.product.id}>{i.product.name} x{i.qty} = ${(i.product.price * i.qty).toFixed(2)}</div>)}
      <p>Total: ${total.toFixed(2)}</p>
      <button onClick={checkout}>Place Order</button>
      <button onClick={() => setPage('home')}>Back</button>
    </div>
  );

  return (
    <div>
      <h1>ShopClient</h1>
      {cart.length > 0 && <button onClick={() => setPage('cart')}>Cart ({cart.length})</button>}
      {products.map(p => (
        <div key={p.id}>
          <span>{p.name} — ${p.price.toFixed(2)}</span>
          <button onClick={() => addToCart(p)} disabled={!p.in_stock}>
            {p.in_stock ? 'Add to Cart' : 'Out of Stock'}
          </button>
        </div>
      ))}
    </div>
  );
}
