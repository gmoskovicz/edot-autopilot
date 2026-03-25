<script lang="ts">
// ShopClient — Svelte (TypeScript)
// No observability. Run `Observe this project.` to add OpenTelemetry Web SDK.
  import { onMount } from 'svelte';
  interface Product { id: string; name: string; price: number; in_stock: boolean; }
  let products: Product[] = [];
  let cart: {product: Product; qty: number}[] = [];
  let cartCount = 0;
  onMount(async () => {
    products = await fetch('https://api.shopapp.io/v2/products').then(r => r.json());
  });
  function addToCart(p: Product) {
    const i = cart.findIndex(x => x.product.id === p.id);
    if (i >= 0) cart[i].qty++; else cart = [...cart, { product: p, qty: 1 }];
    cartCount = cart.reduce((s, i) => s + i.qty, 0);
  }
  async function checkout() {
    await fetch('https://api.shopapp.io/v2/orders', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ customer_id: 'svelte_user', items: cart })
    });
    cart = []; cartCount = 0;
  }
</script>
<h1>ShopClient (Svelte)</h1>
<p>Cart: {cartCount} items</p>
{#each products as p}
  <div>
    <span>{p.name} — ${p.price.toFixed(2)}</span>
    <button on:click={() => addToCart(p)} disabled={!p.in_stock}>
      {p.in_stock ? 'Add' : 'OOS'}
    </button>
  </div>
{/each}
{#if cart.length > 0}
  <button on:click={checkout}>Place Order</button>
{/if}
