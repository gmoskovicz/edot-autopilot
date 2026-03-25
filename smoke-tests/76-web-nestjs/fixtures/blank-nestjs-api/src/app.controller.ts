// Order API — NestJS (TypeScript)
// No observability. Run `Observe this project.` to add OpenTelemetry.
import { Controller, Get, Post, Body, Param, HttpCode, HttpException, HttpStatus } from '@nestjs/common';
import { Injectable } from '@nestjs/common';
import { randomUUID } from 'crypto';

interface CreateOrderDto {
  customer_id?: string;
  customer_tier?: string;
  items: { product_id: string; qty: number; price_usd: number }[];
}

interface Order {
  order_id: string; customer_id: string; total_usd: number;
  status: string; created_at: string;
}

@Injectable()
export class AppService {
  private orders = new Map<string, Order>();

  createOrder(dto: CreateOrderDto): Order {
    const total = dto.items.reduce((s, i) => s + i.price_usd * i.qty, 0);
    if (total <= 0) throw new HttpException('total must be > 0', HttpStatus.BAD_REQUEST);
    const order: Order = {
      order_id: randomUUID(), customer_id: dto.customer_id || 'anon',
      total_usd: total, status: 'confirmed', created_at: new Date().toISOString(),
    };
    this.orders.set(order.order_id, order);
    return order;
  }

  getOrder(id: string): Order {
    const order = this.orders.get(id);
    if (!order) throw new HttpException('not found', HttpStatus.NOT_FOUND);
    return order;
  }
}

@Controller()
export class AppController {
  constructor(private readonly svc: AppService) {}

  @Get('health')
  health() { return { status: 'ok' }; }

  @Post('orders')
  @HttpCode(201)
  createOrder(@Body() dto: CreateOrderDto) { return this.svc.createOrder(dto); }

  @Get('orders/:id')
  getOrder(@Param('id') id: string) { return this.svc.getOrder(id); }
}
