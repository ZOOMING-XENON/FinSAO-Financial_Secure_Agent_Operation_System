// In-memory demo backend, used only when Banking Core is unreachable.
// Mirrors the seed data (user "Lin") and the real policy: transfers are YELLOW until
// today's outgoing total passes ¥1,000, then RED; card.report_lost and wealth are RED.
import { fromCents, toCents } from './money';

export const MOCK_MFA_CODE = '123456';

type Json = Record<string, unknown>;
type Result = [number, unknown];

const U = (n: number) => '00000000-0000-4000-8000-' + String(n).padStart(12, '0');
const rid = () => crypto.randomUUID();
const now = () => new Date().toISOString();
const err = (status: number, code: string, message = code): Result => [status, { code, message }];

const CHECKING = U(1);
const SAVINGS = U(2);

interface Tx { id: string; reference: string; status: string; amount: string; currency: 'CNY'; description: string; category: string | null; posted_at: string; account: string; out: boolean }

const PAYEES: [string, string][] = [
  ['爸爸', '299000000001'], ['妈妈', '390000000002'], ['爷爷', '299000000003'], ['奶奶', '390000000004'],
  ['外公', '299000000005'], ['外婆', '390000000006'], ['哥哥', '299000000007'], ['姐姐', '390000000008'],
  ['好友小王', '299000000009'], ['好友小李', '390000000010'],
];

const db = {
  accounts: [
    { id: CHECKING, account_number: 'DEMO0101000001', name: 'Checking', currency: 'CNY', status: 'ACTIVE' },
    { id: SAVINGS, account_number: 'DEMO0102000001', name: 'Savings', currency: 'CNY', status: 'ACTIVE' },
  ],
  balances: { [CHECKING]: 1157220n, [SAVINGS]: 3000000n } as Record<string, bigint>,
  directory: Object.fromEntries([['DEMO0201000001', U(3)], ...PAYEES.map(([, n], i) => [n, U(200 + i)])]) as Record<string, string>,
  beneficiaries: [
    { id: U(11), name: 'Demo Friend', nickname: 'Friend', destination_account_id: U(3), destination_account_number: 'DEMO0201000001' },
  ] as Json[],
  tx: [
    ['DEMO-OPENING-LIN-CHECKING', '12000.00', 'OPENING_BALANCE', '2026-01-01T08:00:00Z', CHECKING, false, 'Deterministic demo opening balance'],
    ['DEMO-OPENING-LIN-SAVINGS', '30000.00', 'OPENING_BALANCE', '2026-01-01T08:00:00Z', SAVINGS, false, 'Deterministic demo opening balance'],
    ['DEMO-EXPENSE-LIN-2026-01', '128.40', 'HOUSEHOLD', '2026-01-15T12:00:00Z', CHECKING, true, 'Fictional monthly household purchase'],
    ['DEMO-EXPENSE-LIN-2026-02', '156.80', 'HOUSEHOLD', '2026-02-15T12:00:00Z', CHECKING, true, 'Fictional monthly household purchase'],
    ['DEMO-EXPENSE-LIN-2026-03', '142.60', 'HOUSEHOLD', '2026-03-15T12:00:00Z', CHECKING, true, 'Fictional monthly household purchase'],
  ].map(([reference, amount, category, posted_at, account, out, description], i): Tx => ({
    id: U(100 + i), reference: reference as string, status: 'COMPLETED', amount: amount as string, currency: 'CNY',
    description: description as string, category: category as string, posted_at: posted_at as string, account: account as string, out: out as boolean,
  })),
  cards: [{ id: U(31), account_id: CHECKING, label: 'Fictional Demo Card', last_four: '1000', status: 'ACTIVE', spending_limit: '5000.00' }] as Json[],
  subs: [{ id: U(41), merchant_name: 'Demo Stream Lin', amount: '25.00', currency: 'CNY', next_billing_date: '2026-04-15', active: true, status: 'ACTIVE', cancelled_at: null }] as Json[],
  budgets: [{ id: U(51), category: 'HOUSEHOLD', month: '2026-03-01', limit_amount: '1500.00', currency: 'CNY' }] as Json[],
  pots: [{
    id: U(71), name: 'Demo Travel Fund', target_amount: '8000.00', saved_amount: '2400.00', currency: 'CNY', target_date: '2027-05-01',
    status: 'ACTIVE', allocation_mode: 'ACCOUNT_FUNDED', created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
  }] as Json[],
  contributions: [] as Json[],
  drafts: {} as Record<string, Json & { amount: string; source_account_id: string; destination_account_id: string; created: string }>,
  draftKeys: {} as Record<string, string>,
  approvals: {} as Record<string, Json & { risk_tier: string; status: string; operation_id: string; operation_type: string }>,
  challenges: {} as Record<string, string>,
  grants: {} as Record<string, { op: string; type: string; used: boolean; exp: number }>,
  idem: {} as Record<string, Json>,
};

const RED_OPS = new Set(['card.report_lost', 'wealth.subscribe', 'wealth.redeem', 'password.change']);
const YELLOW_OPS = new Set(['subscription.cancel', 'card.limit', 'card.freeze', 'card.unfreeze', 'virtual_card.apply']);

function todayOutgoing(): bigint {
  const day = now().slice(0, 10);
  return Object.values(db.drafts)
    .filter(d => d.created.startsWith(day) && d.status !== 'CANCELLED' && d.status !== 'EXPIRED')
    .reduce((sum, d) => sum + toCents(d.amount), 0n);
}

function issueGrant(ap: { id?: unknown; operation_id: string; operation_type: string; status: string }) {
  const ref = rid();
  const exp = Date.now() + 10 * 60_000;
  db.grants[ref] = { op: ap.operation_id, type: ap.operation_type, used: false, exp };
  ap.status = 'CONFIRMED';
  return { authorization_ref: ref, expires_at: new Date(exp).toISOString() };
}

function consume(ref: unknown, op: string, type: string): Result | null {
  const g = db.grants[String(ref)];
  if (!g || g.used || g.op !== op || g.type !== type || g.exp < Date.now()) return err(403, 'AUTHORIZATION_REQUIRED', 'invalid authorization');
  g.used = true;
  return null;
}

function spending(year: number, month: number) {
  const key = `${year}-${String(month).padStart(2, '0')}`;
  const byCat: Record<string, bigint> = {};
  const byMerchant: Record<string, bigint> = {};
  let total = 0n;
  for (const t of db.tx) {
    if (!t.out || !t.posted_at.startsWith(key) || t.category === 'INTERNAL_TRANSFER' || t.category === 'OPENING_BALANCE') continue;
    const c = toCents(t.amount);
    total += c;
    byCat[t.category || 'UNKNOWN'] = (byCat[t.category || 'UNKNOWN'] || 0n) + c;
    byMerchant[t.description] = (byMerchant[t.description] || 0n) + c;
  }
  const map = (o: Record<string, bigint>) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, fromCents(v)]));
  return { total: fromCents(total), by_category: map(byCat), by_merchant: map(byMerchant) };
}

const publicTx = ({ account: _a, out: _o, ...t }: Tx) => t;

export function mockCore(method: string, path: string, q: Record<string, string>, body: unknown, headers: Record<string, string>): Result {
  const b = (body ?? {}) as Json;
  const m = (re: RegExp) => path.match(re);
  let r: RegExpMatchArray | null;

  if (method === 'GET' && path === '/health') return [200, { status: 'ok' }];
  if (method === 'GET' && path === '/accounts') return [200, db.accounts];
  if (method === 'GET' && (r = m(/^\/accounts\/([^/]+)\/balance$/))) {
    const id = r[1];
    if (!(id in db.balances)) return err(404, 'NOT_FOUND', 'account not found');
    return [200, { account_id: id, balance: fromCents(db.balances[id]), currency: 'CNY' }];
  }
  if (method === 'GET' && (r = m(/^\/accounts\/([^/]+)\/transactions$/))) {
    const limit = Number(q.limit || 50);
    const offset = Number(q.offset || 0);
    const items = db.tx
      .filter(t => t.account === r![1] && (!q.category || t.category === q.category))
      .sort((a, c) => c.posted_at.localeCompare(a.posted_at))
      .slice(offset, offset + limit)
      .map(publicTx);
    return [200, { items, limit, offset }];
  }

  if (method === 'GET' && path === '/beneficiaries') return [200, db.beneficiaries];
  if (method === 'POST' && path === '/beneficiaries') {
    const number = String(b.account_number || '').trim();
    const dest = db.directory[number];
    if (!dest) return err(404, 'NOT_FOUND', 'destination account not found');
    const existing = db.beneficiaries.find(x => x.destination_account_number === number);
    if (existing) return [201, existing];
    const item = { id: rid(), name: String(b.name), nickname: (b.nickname as string) || null, destination_account_id: dest, destination_account_number: number };
    db.beneficiaries.push(item);
    return [201, item];
  }
  if (method === 'GET' && path === '/beneficiaries/resolve') {
    const query = (q.query || '').trim().toLowerCase();
    const matches = db.beneficiaries.filter(x => String(x.name).toLowerCase() === query || String(x.nickname || '').toLowerCase() === query);
    return [200, { status: matches.length === 0 ? 'NOT_FOUND' : matches.length === 1 ? 'RESOLVED' : 'AMBIGUOUS', matches }];
  }

  if (method === 'POST' && path === '/transfers/drafts') {
    const key = headers['Idempotency-Key'];
    if (!key) return err(422, 'VALIDATION_ERROR', 'Idempotency-Key required');
    if (db.draftKeys[key]) return [200, db.drafts[db.draftKeys[key]]];
    const src = String(b.source_account_id);
    if (!(src in db.balances)) return err(404, 'NOT_FOUND', 'account not found');
    const amount = toCents(String(b.amount));
    if (amount <= 0n) return err(422, 'VALIDATION_ERROR');
    if (amount > db.balances[src]) return err(409, 'INSUFFICIENT_FUNDS', 'insufficient funds');
    const draft = {
      id: rid(), source_account_id: src, destination_account_id: String(b.destination_account_id), amount: fromCents(amount), currency: 'CNY',
      status: 'PENDING_AUTHORIZATION', expires_at: new Date(Date.now() + 15 * 60_000).toISOString(), transaction_id: null, created: now(),
    };
    db.drafts[draft.id] = draft;
    db.draftKeys[key] = draft.id;
    const { created: _c, ...pub } = draft;
    return [200, pub];
  }
  if (method === 'GET' && (r = m(/^\/transfers\/(?:drafts\/)?([^/]+)$/))) {
    const d = db.drafts[r[1]];
    if (!d) return err(404, 'NOT_FOUND');
    const { created: _c, ...pub } = d;
    return [200, pub];
  }
  if (method === 'POST' && (r = m(/^\/transfers\/([^/]+)\/commit$/))) {
    const d = db.drafts[r[1]];
    if (!d) return err(404, 'NOT_FOUND');
    const denied = consume(b.authorization_ref, d.id as string, 'transfer.commit');
    if (denied) return denied;
    const amount = toCents(d.amount);
    if (amount > db.balances[d.source_account_id]) return err(409, 'INSUFFICIENT_FUNDS');
    db.balances[d.source_account_id] -= amount;
    const benef = db.beneficiaries.find(x => x.destination_account_id === d.destination_account_id);
    const tx: Tx = {
      id: rid(), reference: 'TRF-' + Date.now().toString(36).toUpperCase(), status: 'COMPLETED', amount: d.amount, currency: 'CNY',
      description: `Transfer to ${benef?.name ?? 'recipient'}`, category: 'INTERNAL_TRANSFER', posted_at: now(), account: d.source_account_id, out: true,
    };
    db.tx.push(tx);
    d.status = 'COMPLETED';
    d.transaction_id = tx.id;
    return [200, { transaction_id: tx.id, reference: tx.reference, status: 'COMPLETED', amount: d.amount, currency: 'CNY' }];
  }

  if (method === 'POST' && path === '/security/approvals') {
    const op = String(b.operation_id);
    const draft = db.drafts[op];
    const type = draft ? 'transfer.commit' : String(b.operation_type || '');
    let tier: string;
    if (type === 'transfer.commit') tier = todayOutgoing() <= 100000n ? 'YELLOW' : 'RED';
    else if (type === 'savings.contribute') tier = toCents(String(b.amount)) <= 100000n ? 'YELLOW' : 'RED';
    else if (RED_OPS.has(type)) tier = 'RED';
    else if (YELLOW_OPS.has(type)) tier = 'YELLOW';
    else return err(403, 'AUTHORIZATION_REQUIRED', 'operation denied by policy');
    const ap = {
      id: rid(), operation_id: op, operation_type: type, target_account_id: draft?.source_account_id ?? b.target_account_id ?? null, recipient_id: draft?.destination_account_id ?? null,
      amount: draft?.amount ?? (b.amount as string | undefined) ?? null, currency: 'CNY', risk_tier: tier, status: 'PENDING',
      expires_at: new Date(Date.now() + 10 * 60_000).toISOString(),
    };
    db.approvals[ap.id] = ap;
    return [201, ap];
  }
  if (method === 'POST' && (r = m(/^\/security\/approvals\/([^/]+)\/decision$/))) {
    const ap = db.approvals[r[1]];
    if (!ap || ap.status !== 'PENDING') return err(409, 'CONFLICT', 'approval not pending');
    if (!b.accepted) { ap.status = 'REJECTED'; return [200, null]; }
    if (ap.risk_tier === 'RED') return err(403, 'AUTHORIZATION_REQUIRED', 'MFA is required');
    return [200, issueGrant(ap)];
  }
  if (method === 'POST' && (r = m(/^\/security\/approvals\/([^/]+)\/mfa$/))) {
    const ap = db.approvals[r[1]];
    if (!ap || ap.risk_tier !== 'RED' || ap.status !== 'PENDING') return err(409, 'CONFLICT');
    const id = rid();
    db.challenges[id] = ap.id as string;
    return [200, { challenge_id: id, expires_at: new Date(Date.now() + 5 * 60_000).toISOString() }];
  }
  if (method === 'POST' && (r = m(/^\/security\/mfa\/([^/]+)\/verify$/))) {
    const ap = db.approvals[db.challenges[r[1]]];
    if (!ap) return err(404, 'NOT_FOUND');
    if (b.code !== MOCK_MFA_CODE) return err(403, 'AUTHORIZATION_REQUIRED', 'invalid verification code');
    delete db.challenges[r[1]];
    return [200, issueGrant(ap)];
  }

  if (method === 'GET' && path === '/cards') return [200, db.cards];
  if (method === 'POST' && (r = m(/^\/cards\/([^/]+)\/(freeze|unfreeze|report-lost)$/))) {
    const card = db.cards.find(c => c.id === r![1]);
    if (!card) return err(404, 'NOT_FOUND');
    const type = r[2] === 'report-lost' ? 'card.report_lost' : `card.${r[2]}`;
    const denied = consume(b.authorization_ref, card.id as string, type);
    if (denied) return denied;
    card.status = r[2] === 'freeze' ? 'FROZEN' : r[2] === 'unfreeze' ? 'ACTIVE' : 'LOST';
    return [200, card];
  }

  if (method === 'GET' && path === '/subscriptions') return [200, db.subs];
  if (method === 'GET' && path === '/subscriptions/detect-recurring') return [200, []];
  if (method === 'POST' && (r = m(/^\/subscriptions\/([^/]+)\/cancel$/))) {
    const sub = db.subs.find(s => s.id === r![1]);
    if (!sub) return err(404, 'NOT_FOUND');
    const denied = consume(b.authorization_ref, sub.id as string, 'subscription.cancel');
    if (denied) return denied;
    Object.assign(sub, { active: false, status: 'CANCELLED', cancelled_at: now() });
    return [200, sub];
  }

  if (method === 'GET' && (path === '/analytics/monthly-summary' || path === '/analytics/spending')) {
    return [200, spending(Number(q.year), Number(q.month))];
  }
  if (method === 'GET' && path === '/budgets') return [200, db.budgets];
  if (method === 'POST' && path === '/budgets') {
    const existing = db.budgets.find(x => x.category === b.category && x.month === b.month);
    if (existing) { existing.limit_amount = b.limit_amount; return [200, existing]; }
    const item = { id: rid(), category: b.category, month: b.month, limit_amount: b.limit_amount, currency: 'CNY' };
    db.budgets.push(item);
    return [200, item];
  }
  if (method === 'GET' && (r = m(/^\/budgets\/([^/]+)\/status$/))) {
    const bud = db.budgets.find(x => x.id === r![1]);
    if (!bud) return err(404, 'NOT_FOUND');
    const [y, mo] = String(bud.month).split('-').map(Number);
    const used = toCents(spending(y, mo).by_category[String(bud.category)] || '0');
    const limit = toCents(String(bud.limit_amount));
    return [200, { limit: fromCents(limit), used: fromCents(used), remaining: fromCents(limit - used), estimate: fromCents(used), threshold_exceeded: used * 100n >= limit * 80n }];
  }

  if (method === 'GET' && path === '/savings-pots') return [200, db.pots.filter(p => p.status !== 'DELETED')];
  if (method === 'POST' && path === '/savings-pots') {
    const key = 'pot:' + b.idempotency_key;
    if (db.idem[key]) return [201, db.idem[key]];
    const pot = {
      id: rid(), name: b.name, target_amount: b.target_amount, saved_amount: '0.00', currency: 'CNY', target_date: b.target_date,
      status: 'ACTIVE', allocation_mode: 'ACCOUNT_FUNDED', created_at: now(), updated_at: now(),
    };
    db.pots.push(pot);
    db.idem[key] = pot;
    return [201, pot];
  }
  if ((r = m(/^\/savings-pots\/([^/]+)(\/contributions)?$/))) {
    const pot = db.pots.find(p => p.id === r![1] && p.status !== 'DELETED');
    if (!pot) return err(404, 'NOT_FOUND', 'savings pot not found');
    if (!r[2] && method === 'GET') return [200, pot];
    if (!r[2] && method === 'DELETE') {
      if (toCents(String(pot.saved_amount)) > 0n) return err(409, 'CONFLICT', 'funded savings pot cannot be deleted');
      pot.status = 'DELETED';
      return [204, null];
    }
    if (r[2] && method === 'GET') return [200, db.contributions.filter(c => c.pot_id === pot.id).reverse()];
    if (r[2] && method === 'POST') {
      const key = 'contrib:' + b.idempotency_key;
      if (db.idem[key]) return [201, db.idem[key]];
      const source = String(b.source_account_id);
      const amount = toCents(String(b.amount));
      if (!(source in db.balances)) return err(404, 'NOT_FOUND', 'account not found');
      const denied = consume(b.authorization_ref, String(pot.id), 'savings.contribute');
      if (denied) return denied;
      if (amount > db.balances[source]) return err(409, 'INSUFFICIENT_FUNDS');
      db.balances[source] -= amount;
      const transactionId = rid();
      const c = { id: rid(), pot_id: pot.id, source_account_id: source, transaction_id: transactionId, amount: b.amount, note: b.note ?? null, created_at: now() };
      db.tx.push({
        id: transactionId, reference: 'SAV-' + Date.now().toString(36).toUpperCase(), status: 'COMPLETED', amount: fromCents(amount), currency: 'CNY',
        description: `Savings contribution: ${pot.name}`, category: 'SAVINGS', posted_at: now(), account: source, out: true,
      });
      pot.saved_amount = fromCents(toCents(String(pot.saved_amount)) + amount);
      pot.updated_at = now();
      db.contributions.push(c);
      db.idem[key] = c;
      return [201, c];
    }
  }
  return err(404, 'NOT_FOUND', `no demo route for ${method} ${path}`);
}
