// ShopApp — Ionic/Angular (TypeScript)
//
// No observability. Run `Observe this project.` to add OpenTelemetry.
//
// Expected: agent adds @opentelemetry/sdk-trace-web + @opentelemetry/instrumentation-fetch.

import { Component, OnInit } from '@angular/core';
import { HttpClient } from '@angular/common/http';

interface Product {
  id: string;
  name: string;
  price: number;
  in_stock: boolean;
}

interface CartItem {
  product: Product;
  qty: number;
}

@Component({
  selector:    'app-home',
  templateUrl: 'home.page.html',
})
export class HomePage implements OnInit {
  products: Product[] = [];
  cart: CartItem[]    = [];
  loading             = false;
  orderId: string | null = null;

  private readonly apiBase = 'https://api.shopapp.io/v2';

  constructor(private http: HttpClient) {}

  ngOnInit() {
    this.loadProducts();
  }

  loadProducts() {
    this.loading = true;
    this.http.get<Product[]>(`${this.apiBase}/products`).subscribe({
      next: (data) => { this.products = data; this.loading = false; },
      error: ()     => { this.loading = false; },
    });
  }

  addToCart(product: Product) {
    const idx = this.cart.findIndex(i => i.product.id === product.id);
    if (idx >= 0) {
      this.cart[idx].qty++;
    } else {
      this.cart.push({ product, qty: 1 });
    }
  }

  get cartCount() { return this.cart.reduce((s, i) => s + i.qty, 0); }
  get cartTotal() { return this.cart.reduce((s, i) => s + i.product.price * i.qty, 0); }

  checkout() {
    this.loading = true;
    const body = {
      customer_id: 'ionic_user',
      items: this.cart.map(i => ({ product_id: i.product.id, qty: i.qty })),
    };
    this.http.post<{ order_id: string }>(`${this.apiBase}/orders`, body).subscribe({
      next: (res)   => {
        this.orderId = res.order_id;
        this.cart    = [];
        this.loading = false;
      },
      error: ()     => { this.loading = false; },
    });
  }
}
