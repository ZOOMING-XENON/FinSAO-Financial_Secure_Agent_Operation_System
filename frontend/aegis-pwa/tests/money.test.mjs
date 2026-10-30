import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fromCents, formatMoney, isValidAmount, normalizeAmount, percent, toCents } from '../src/core/money.ts';

test('parses decimal strings into integer cents without floats', () => {
  assert.equal(toCents('0.1') + toCents('0.2'), 30n);
  assert.equal(toCents('11572.20'), 1157220n);
  assert.equal(toCents('-5.5'), -550n);
  assert.equal(fromCents(30n), '0.30');
  assert.equal(fromCents(-550n), '-5.50');
});

test('validates and normalizes user amounts', () => {
  assert.ok(isValidAmount('200'));
  assert.ok(isValidAmount('88.5'));
  assert.ok(!isValidAmount('0'));
  assert.ok(!isValidAmount('1.234'));
  assert.ok(!isValidAmount('-3'));
  assert.ok(!isValidAmount('1e3'));
  assert.equal(normalizeAmount('88.5'), '88.50');
});

test('formats with thousands separators and clamps percentages', () => {
  assert.equal(formatMoney('8000.00'), '¥8,000.00');
  assert.equal(formatMoney('1234567.8', 'USD'), '$1,234,567.80');
  assert.equal(percent('2400.00', '8000.00'), 30);
  assert.equal(percent('9000', '8000'), 100);
  assert.equal(percent('1', '0'), 0);
});
