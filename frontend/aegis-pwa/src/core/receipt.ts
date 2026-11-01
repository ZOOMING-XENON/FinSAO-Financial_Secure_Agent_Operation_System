// Turns OCR text from a receipt into merchant, total, date and a category guess.
// Self-contained (no imports) so it can be unit-tested directly with Node.

export interface ParsedReceipt {
  merchant: string;
  amount: string | null; // decimal string "142.60"
  date: string | null; // YYYY-MM-DD
  category: string;
}

const TOTAL = /(实付|实收|应付|合计|总计|总额|付款金额|支付金额|grand\s*total|total|amount\s*due|amount\s*paid|paid)/i;
const SUBTOTAL = /(小计|subtotal|找零|change|优惠|discount|税|tax)/i;
const MONEY = /(?:[¥￥]|RMB|CNY)?\s*(\d{1,6}[.,]\d{2})(?!\d)/gi;

// Shop-type words first: a supermarket receipt listing 面包 (bread) is still groceries.
const CATEGORY_WORDS: [RegExp, string][] = [
  [/超市|便利店|生鲜|菜市|market|mart|grocery|supermarket/i, 'GROCERIES'],
  [/地铁|公交|出租|打车|滴滴|加油|停车|metro|taxi|bus|parking|fuel|petrol|railway|高铁/i, 'TRANSPORT'],
  [/影城|电影|ktv|游戏|演出|门票|cinema|movie|ticket|game|concert|bowling/i, 'ENTERTAINMENT'],
  [/家居|电费|水费|燃气|物业|五金|宜家|ikea|home|hardware|utility|electric/i, 'HOUSEHOLD'],
  [/餐|饭|面馆|粉|咖啡|奶茶|茶饮|火锅|烧烤|寿司|饺|restaurant|cafe|coffee|kitchen|bistro|noodle|pizza|burger/i, 'DINING'],
  [/生鲜|水果|果蔬|fresh|fruit/i, 'GROCERIES'],
];

const toAmount = (raw: string) => raw.replace(',', '.');
const cents = (a: string) => Math.round(parseFloat(a) * 100);

function amountsIn(line: string): string[] {
  return [...line.matchAll(MONEY)].map(m => toAmount(m[1]));
}

export function parseReceipt(text: string): ParsedReceipt {
  const lines = text
    .split(/\r?\n/)
    // OCR spaces out Chinese characters ("鲜 集 超市"); join them back.
    .map(l => l.replace(/\s+/g, ' ').replace(/([\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])/g, '$1').trim())
    .filter(Boolean);

  // Total: the last line that says "total / 合计 / 实付", or the line right after it.
  let amount: string | null = null;
  for (let i = lines.length - 1; i >= 0 && !amount; i--) {
    if (TOTAL.test(lines[i]) && !SUBTOTAL.test(lines[i])) {
      const here = amountsIn(lines[i]);
      const next = here.length ? here : amountsIn(lines[i + 1] ?? '');
      if (next.length) amount = next[next.length - 1];
    }
  }
  // Otherwise the largest believable amount on the receipt.
  if (!amount) {
    const all = lines.flatMap(amountsIn).filter(a => cents(a) > 0 && cents(a) < 10_000_000);
    if (all.length) amount = all.reduce((m, a) => (cents(a) > cents(m) ? a : m));
  }
  if (amount) amount = (cents(amount) / 100).toFixed(2);

  const d = text.match(/(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})/);
  const date = d ? `${d[1]}-${d[2].padStart(2, '0')}-${d[3].padStart(2, '0')}` : null;

  // Merchant: the first line with real words that isn't a total, date or number line.
  const merchant =
    lines.find(l => /[A-Za-z一-鿿]{2,}/.test(l) && !TOTAL.test(l) && !/\d{4}[-/.年]/.test(l) && amountsIn(l).length === 0 && l.length <= 32) ?? '';

  const category = CATEGORY_WORDS.find(([re]) => re.test(text))?.[1] ?? 'UNKNOWN';
  return { merchant, amount, date, category };
}
