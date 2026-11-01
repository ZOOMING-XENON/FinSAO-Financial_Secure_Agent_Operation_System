import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseReceipt } from '../src/core/receipt.ts';

test('reads a Chinese restaurant receipt', () => {
  const r = parseReceipt(`海底捞火锅（南山店）
2026-10-31 19:42
毛肚 1 58.00
虾滑 1 46.00
小计 104.00
优惠 -10.00
实付金额 ¥94.00`);
  assert.equal(r.amount, '94.00');
  assert.equal(r.date, '2026-10-31');
  assert.equal(r.category, 'DINING');
  assert.match(r.merchant, /火锅/);
});

test('reads an English supermarket receipt with the total on the next line', () => {
  const r = parseReceipt(`FreshMart Supermarket
Date: 2026/11/01
Milk 12.50
Bread 8,90
Subtotal 21.40
TOTAL
21.40`);
  assert.equal(r.amount, '21.40');
  assert.equal(r.date, '2026-11-01');
  assert.equal(r.category, 'GROCERIES');
  assert.equal(r.merchant, 'FreshMart Supermarket');
});

test('falls back to the largest amount when there is no total line', () => {
  const r = parseReceipt('Metro ticket\n4.00\n2.00');
  assert.equal(r.amount, '4.00');
  assert.equal(r.category, 'TRANSPORT');
  assert.equal(r.date, null);
});

test('returns no amount for text without money', () => {
  assert.equal(parseReceipt('hello world').amount, null);
});

test('joins spaced-out Chinese and prefers the shop type over item words', () => {
  const r = parseReceipt('鲜 集 超市 FreshMart\n2026-10-31 18:42\n面 包 Bread 8.90\n实付金额 ¥45.00');
  assert.equal(r.merchant, '鲜集超市 FreshMart');
  assert.equal(r.category, 'GROCERIES');
  assert.equal(r.amount, '45.00');
});
