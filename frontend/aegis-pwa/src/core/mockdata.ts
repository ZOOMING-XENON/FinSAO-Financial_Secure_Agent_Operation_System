// Demo-mode dataset: about three months of fictional, deterministic activity relative to
// today, so Insights, the calendar, budgets and pots have something real to show.
// Live mode never uses this; it shows whatever Banking Core returns.
import { fromCents, toCents } from './money';

export interface DemoTx {
  reference: string;
  amount: string;
  category: string;
  posted_at: string;
  out: boolean;
  description: string;
}

function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const iso = (d: Date, h: number, m: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate(), h, m).toISOString();
const yuan = (r: () => number, lo: number, hi: number) => fromCents(BigInt(Math.round((lo + r() * (hi - lo)) * 10)) * 10n);
const dayStr = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

const LUNCH = ['Noodle House 面馆', 'Dumpling Corner 饺子馆', 'Green Bowl 轻食', 'Canteen 员工餐厅', 'Rice & Curry 咖喱饭'];
const DINNER = ['Hotpot Garden 火锅', 'Cantonese Kitchen 粤菜馆', 'Sushi Bar 寿司'];
const GROCER = ['FreshMart 鲜集超市', 'Fruit Stand 水果铺', 'Neighbourhood Market 菜市场'];
const FUN = ['City Cinema 影城', 'Board Game Café 桌游', 'Bowling Club 保龄球', 'Concert Hall 音乐厅'];
const HOME = ['Home Goods 家居店', 'Electricity bill 电费', 'Water & gas 水费燃气'];

export function buildDemo(today = new Date()) {
  const r = rng(20261031);
  const tx: DemoTx[] = [];
  let n = 0;
  const add = (d: Date, h: number, amount: string, category: string, description: string, out = true) =>
    tx.push({ reference: `DEMO-${dayStr(d)}-${++n}`, amount, category, posted_at: iso(d, h, Math.floor(r() * 59)), out, description });

  for (let back = 92; back >= 0; back--) {
    const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() - back);
    const dow = d.getDay();
    const weekend = dow === 0 || dow === 6;
    if (d.getDate() === 10) add(d, 9, '18500.00', 'SALARY', 'Salary · Shenzhen Tech Co. 工资', false);
    if (d.getDate() === 1) add(d, 10, '4800.00', 'HOUSEHOLD', 'Rent 房租');
    if (d.getDate() === 12) add(d, 20, yuan(r, 160, 260), 'HOUSEHOLD', HOME[1 + Math.floor(r() * 2)]);
    if (d.getDate() === 15) add(d, 21, '25.00', 'ENTERTAINMENT', 'Video streaming 视频会员');
    if (d.getDate() === 22) add(d, 21, '15.00', 'ENTERTAINMENT', 'Music streaming 音乐会员');
    if (!weekend) {
      add(d, 8, yuan(r, 3, 7), 'TRANSPORT', 'Metro 地铁');
      add(d, 18, yuan(r, 3, 7), 'TRANSPORT', 'Metro 地铁');
      if (r() < 0.85) add(d, 12, yuan(r, 22, 48), 'DINING', LUNCH[Math.floor(r() * LUNCH.length)]);
    } else {
      if (r() < 0.7) add(d, 14, yuan(r, 45, 180), 'ENTERTAINMENT', FUN[Math.floor(r() * FUN.length)]);
      if (r() < 0.6) add(d, 19, yuan(r, 90, 260), 'DINING', DINNER[Math.floor(r() * DINNER.length)]);
      if (r() < 0.5) add(d, 17, yuan(r, 18, 45), 'TRANSPORT', 'Taxi 打车');
    }
    if (back % 4 === 1) add(d, 19, yuan(r, 55, 190), 'GROCERIES', GROCER[Math.floor(r() * GROCER.length)]);
    if (r() < 0.06) add(d, 15, yuan(r, 60, 320), 'HOUSEHOLD', HOME[0]);
    if (r() < 0.03) add(d, 16, yuan(r, 20, 80), 'UNKNOWN', 'Card payment 刷卡消费');
  }

  const inCents = tx.filter(t => !t.out).reduce((s, t) => s + toCents(t.amount), 0n);
  const outCents = tx.filter(t => t.out).reduce((s, t) => s + toCents(t.amount), 0n);

  const month = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-01`;
  const plus = (days: number) => dayStr(new Date(today.getFullYear(), today.getMonth(), today.getDate() + days));
  const ago = (days: number) => new Date(today.getFullYear(), today.getMonth(), today.getDate() - days).toISOString();

  return {
    tx,
    netCents: inCents - outCents,
    budgets: [
      ['DINING', '1800.00'],
      ['GROCERIES', '1300.00'],
      ['TRANSPORT', '400.00'],
      ['ENTERTAINMENT', '900.00'],
      ['HOUSEHOLD', '5600.00'],
    ].map(([category, limit]) => ({ category, month, limit_amount: limit })),
    subs: [
      { merchant_name: 'Video streaming 视频会员', amount: '25.00', next_billing_date: plus(2) },
      { merchant_name: 'Music streaming 音乐会员', amount: '15.00', next_billing_date: plus(9) },
      { merchant_name: 'Cloud storage 云盘', amount: '21.00', next_billing_date: plus(19) },
    ],
    pots: [
      { name: 'Japan trip 日本旅行', target_amount: '12000.00', saved_amount: '7800.00', target_date: plus(150), created_at: ago(120) },
      { name: 'New phone 新手机', target_amount: '6999.00', saved_amount: '6700.00', target_date: plus(30), created_at: ago(90) },
      { name: 'Emergency fund 应急金', target_amount: '30000.00', saved_amount: '11200.00', target_date: plus(365), created_at: ago(200) },
    ],
  };
}
