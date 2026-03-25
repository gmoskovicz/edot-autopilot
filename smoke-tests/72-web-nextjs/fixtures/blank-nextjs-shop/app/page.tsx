// ShopClient — Next.js 14 App Router (TypeScript)
//
// No observability. Run `Observe this project.` to add OpenTelemetry.
// Expected: agent adds @vercel/otel or @opentelemetry/sdk-node for server-side
// and @opentelemetry/sdk-trace-web for client-side RUM.

'use client';

import { useState, useEffect } from 'react';

interface Product { id: string; name: string; price: number; in_stock: boolean; }

export default function ShopPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [cart, setCart] = useState<{id: string; qty: number}[]>([]);

  useEffect(() => {
    fetch('https://api.shopapp.io/v2/products')
      .then(r => r.json()).then(setProducts);
  }, []);

  function addToCart(id: string) {
    setCart(prev => {
      const i = prev.findIndex(x => x.id === id);
      return i >= 0 ? prev.map((x, j) => j === i ? {...x, qty: x.qty + 1} : x)
                    : [...prev, {id, qty: 1}];
    });
  }

  return (
    <main>
      <h1>ShopClient (Next.js)</h1>
      <p>Cart: {cart.reduce((s, i) => s + i.qty, 0)} items</p>
      {products.map(p => (
        <div key={p.id}>
          <span>{p.name} — ${p.price.toFixed(2)}</span>
          <button onClick={() => addToCart(p.id)} disabled={!p.in_stock}>
            {p.in_stock ? 'Add' : 'OOS'}
          </button>
        </div>
      ))}
    </main>
  );
}
