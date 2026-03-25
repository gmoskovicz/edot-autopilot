// ShopClient — Angular 17 (TypeScript)
// No observability. Run `Observe this project.` to add OpenTelemetry Web SDK.
import { Component, OnInit } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { CommonModule } from '@angular/common';
import { HttpClientModule } from '@angular/common/http';

interface Product { id: string; name: string; price: number; in_stock: boolean; }

@Component({
  selector: 'app-root', standalone: true,
  imports: [CommonModule, HttpClientModule],
  template: `
    <h1>ShopClient (Angular)</h1>
    <p>Cart: {{ cartCount }} items</p>
    <div *ngFor="let p of products">
      <span>{{ p.name }} — \${{ p.price.toFixed(2) }}</span>
      <button (click)="addToCart(p)" [disabled]="!p.in_stock">
        {{ p.in_stock ? 'Add' : 'OOS' }}
      </button>
    </div>
    <button *ngIf="cart.length" (click)="checkout()">Place Order</button>
  `
})
export class AppComponent implements OnInit {
  products: Product[] = [];
  cart: {product: Product; qty: number}[] = [];
  get cartCount() { return this.cart.reduce((s, i) => s + i.qty, 0); }

  constructor(private http: HttpClient) {}

  ngOnInit() {
    this.http.get<Product[]>('https://api.shopapp.io/v2/products')
      .subscribe(data => this.products = data);
  }

  addToCart(p: Product) {
    const i = this.cart.findIndex(x => x.product.id === p.id);
    if (i >= 0) this.cart[i].qty++; else this.cart.push({ product: p, qty: 1 });
  }

  checkout() {
    this.http.post('https://api.shopapp.io/v2/orders', {
      customer_id: 'angular_user', items: this.cart
    }).subscribe(() => this.cart = []);
  }
}
