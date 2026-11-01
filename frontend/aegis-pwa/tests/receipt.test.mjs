import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseReceipt, parseReceipts } from '../src/core/receipt.ts';

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

test('takes the shop name from the top, skipping greetings and order numbers', () => {
  const r = parseReceipt('欢迎光临\n| 永辉超市（科技园店） |\nNO.20261031001\n2026-10-31 18:42\n可口可乐 3.50\n合计 3.50');
  assert.equal(r.merchant, '永辉超市（科技园店）');
  assert.equal(r.category, 'GROCERIES');
});

test('reads a payment detail screenshot by its labels', () => {
  const r = parseReceipt('9:41\n账单详情\n-28.50\n交易成功\n商户全称：瑞幸咖啡（深圳）有限公司\n支付时间 2026-10-30 08:12');
  assert.equal(r.amount, '28.50');
  assert.match(r.merchant, /瑞幸咖啡/);
  assert.equal(r.category, 'DINING');
  assert.equal(r.date, '2026-10-30');
});

test('finds every payment in a bill list screenshot', () => {
  const list = parseReceipts('9:41\n账单\n美团外卖 -35.00\n餐饮美食 10-31 12:30\n滴滴出行 -18.60\n交通出行 10-30 21:05\n工资 +5,000.00\n10-28 09:00', new Date('2026-11-01T10:00:00'));
  assert.equal(list.length, 3);
  assert.deepEqual(list.map(x => [x.merchant, x.amount, x.category, x.kind, x.date]), [
    ['美团外卖', '35.00', 'DINING', 'out', '2026-10-31'],
    ['滴滴出行', '18.60', 'TRANSPORT', 'out', '2026-10-30'],
    ['工资', '5000.00', 'UNKNOWN', 'in', '2026-10-28'],
  ]);
});

test('reads 一 as a minus sign and still finds the rows when the date lines are missing', () => {
  const list = parseReceipts('账单\n美团外卖 -35.00\n滴滴出行 一18.60\n永辉超市 一 86.40');
  assert.deepEqual(list.map(x => [x.merchant, x.amount, x.category]), [
    ['美团外卖', '35.00', 'DINING'],
    ['滴滴出行', '18.60', 'TRANSPORT'],
    ['永辉超市', '86.40', 'GROCERIES'],
  ]);
});
