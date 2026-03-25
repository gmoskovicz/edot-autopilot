<template>
  <!-- ShopClient — Vue 3 (TypeScript)
       No observability. Run `Observe this project.` to add OpenTelemetry Web SDK. -->
  <div>
    <h1>ShopClient (Vue)</h1>
    <p>Cart: {{ cartCount }} items | Total: ${{ cartTotal.toFixed(2) }}</p>
    <div v-for="p in products" :key="p.id">
      <span>{{ p.name }} — ${{ p.price.toFixed(2) }}</span>
      <button @click="addToCart(p)" :disabled="!p.in_stock">
        {{ p.in_stock ? 'Add' : 'OOS' }}
      </button>
    </div>
    <button v-if="cart.length" @click="checkout">Place Order</button>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';

interface Product { id: string; name: string; price: number; in_stock: boolean; }

const products = ref<Product[]>([]);
const cart     = ref<{product: Product; qty: number}[]>([]);

onMounted(() => {
  fetch('https://api.shopapp.io/v2/products')
    .then(r => r.json()).then(d => products.value = d);
});

function addToCart(p: Product) {
  const i = cart.value.findIndex(x => x.product.id === p.id);
  if (i >= 0) cart.value[i].qty++; else cart.value.push({ product: p, qty: 1 });
}

const cartCount = computed(() => cart.value.reduce((s, i) => s + i.qty, 0));
const cartTotal = computed(() => cart.value.reduce((s, i) => s + i.product.price * i.qty, 0));

async function checkout() {
  await fetch('https://api.shopapp.io/v2/orders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ customer_id: 'vue_user', items: cart.value }),
  });
  cart.value = [];
}
</script>
