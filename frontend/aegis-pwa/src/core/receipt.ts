// Turns OCR text from a receipt or a payment-app screenshot into merchant, amount, date and a
// category guess. A bill list (Alipay / WeChat Pay style, several payments in one screenshot)
// comes back as several entries. Self-contained (no imports) so Node can unit-test it directly.

export interface ParsedReceipt {
  merchant: string;
  amount: string | null; // decimal string "142.60"
  date: string | null; // YYYY-MM-DD
  category: string;
  kind: 'out' | 'in';
}

const TOTAL = /(实付|实收|应付|应收|合计|总计|总额|付款金额|支付金额|交易金额|订单金额|grand\s*total|total|amount\s*due|amount\s*paid|paid)/i;
const SUBTOTAL = /(小计|subtotal|找零|change|优惠|折扣|discount|税|tax|积分)/i;
const MONEY = /(?:[¥￥]|RMB|CNY)?\s*(\d{1,6}(?:,\d{3})*[.,]\d{2})(?!\d)/gi;
const DATE_FULL = /(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})/;
const DATE_SHORT = /(?:^|\D)(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*日?(?:\s+\d{1,2}:\d{2})?(?:\D|$)/;
const TIME_ONLY = /^\d{1,2}:\d{2}/;
// Lines at the top of a receipt or screenshot that are not the shop's name.
const NOISE = /^(欢迎光临|欢迎|收银小票|购物小票|结账单|小票|收据|发票|电子发票|账单详情|交易详情|订单详情|全部账单|账单|支付成功|交易成功|当前状态|receipt|sales receipt|invoice|tax invoice|welcome|thank|谢谢)/i;
const LABELED = /(?:商户全称|商户名称|商户|收款方全称|收款方|对方账户|店铺名称|店铺|门店|店名|商家|merchant|store|shop)\s*[:：]\s*(.{2,40})/i;
const SHOP_WORD = /(店|超市|餐厅|餐馆|饭店|酒楼|咖啡|有限公司|公司|商行|商场|药房|便利|mart|store|shop|market|cafe|café|restaurant|kitchen|company|co\.|ltd|inc)/i;
// Category names payment apps print next to each payment.
const APP_LABELS: [RegExp, string][] = [
  [/餐饮美食|餐饮/, 'DINING'],
  [/日用百货|超市|生鲜/, 'GROCERIES'],
  [/交通出行|出行/, 'TRANSPORT'],
  [/休闲娱乐|文化休闲|娱乐/, 'ENTERTAINMENT'],
  [/住房物业|生活服务|充值缴费|生活缴费/, 'HOUSEHOLD'],
];

const CATEGORY_WORDS: Record<string, RegExp> = {
  DINING:
    /餐饮|餐厅|饭店|饭馆|酒楼|食堂|小吃|面馆|拉面|米粉|粉店|火锅|烧烤|烤肉|寿司|料理|饺子|包子|咖啡|奶茶|茶饮|喜茶|奈雪|蜜雪|瑞幸|星巴克|麦当劳|肯德基|必胜客|汉堡|海底捞|外卖|饿了么|美团外卖|堂食|桌号|餐位|米饭|restaurant|cafe|café|coffee|kitchen|bistro|noodle|pizza|burger|kfc|mcdonald|starbucks|luckin|diner|grill/gi,
  GROCERIES:
    /超市|便利店|生鲜|菜市场|果蔬|水果|盒马|永辉|沃尔玛|家乐福|物美|华润万家|大润发|山姆|全家|罗森|便利蜂|美宜佳|日用百货|牛奶|鸡蛋|蔬菜|7-?eleven|supermarket|grocery|groceries|\bmart\b|market|walmart|carrefour|familymart|lawson|costco|fresh/gi,
  TRANSPORT:
    /地铁|公交|出租|打车|滴滴|高德|曹操出行|加油|中石化|中石油|停车|高铁|火车|12306|铁路|机票|航空|单车|哈啰|交通出行|metro|subway|taxi|uber|didi|\bbus\b|parking|fuel|petrol|railway|airline|flight/gi,
  ENTERTAINMENT:
    /影城|影院|电影|猫眼|淘票票|ktv|游戏|演出|门票|景区|剧本杀|密室|健身|休闲娱乐|爱奇艺|腾讯视频|优酷|网易云|bilibili|steam|cinema|movie|ticket|\bgame|concert|bowling|netflix|spotify/gi,
  HOUSEHOLD:
    /家居|电费|水费|燃气|物业|五金|宜家|房租|租金|国家电网|中国移动|中国联通|中国电信|话费|宽带|充值缴费|住房物业|生活服务|ikea|hardware|utility|electric|\brent\b|telecom/gi,
};

const toAmount = (raw: string) => raw.replace(/,(?=\d{3}\b)/g, '').replace(',', '.');
const cents = (a: string) => Math.round(parseFloat(a) * 100);
const fixed = (a: string) => (cents(a) / 100).toFixed(2);

function amountsIn(line: string): string[] {
  return [...line.matchAll(MONEY)].map(m => toAmount(m[1]));
}

/** Splits OCR text into tidy lines; joins Chinese characters that OCR spaced out ("鲜 集 超市"). */
export function cleanLines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map(l =>
      l
        .replace(/\s+/g, ' ')
        .replace(/([一-鿿])\s+(?=[一-鿿])/g, '$1')
        .trim(),
    )
    .filter(Boolean);
}

/** Strips OCR junk (bullets, bars, stray symbols) from both ends of a name. */
function tidyName(s: string): string {
  return s
    .replace(/^[^\p{L}\p{N}(（]+/u, '')
    .replace(/[^\p{L}\p{N})）.]+$/u, '')
    .trim();
}

const wordy = (l: string) => /[一-鿿]{2,}|[A-Za-z]{3,}/.test(l);
const hasDate = (l: string) => DATE_FULL.test(l) || TIME_ONLY.test(l) || /\d{1,2}:\d{2}(:\d{2})?/.test(l);

/** Phone status bars and order numbers ("15:10 7 all 56 ©)"): a clock, or mostly digits and symbols. */
function junkName(l: string): boolean {
  const letters = (l.match(/[\p{L}]/gu) ?? []).length;
  return hasDate(l) || letters / l.length < 0.5 || /\b(all|ill|lte|5g|4g|wifi)\b/i.test(l) && /\d/.test(l);
}

function guessMerchant(lines: string[]): string {
  for (const l of lines) {
    const m = l.match(LABELED);
    if (m) {
      const v = tidyName(m[1].replace(MONEY, ''));
      if (wordy(v)) return v;
    }
  }
  // Otherwise the shop name printed at the top: the best wordy line among the first few.
  let best = '';
  let bestScore = -Infinity;
  lines.slice(0, 8).forEach((raw, i) => {
    const l = tidyName(raw);
    if (!wordy(l) || l.length > 36 || NOISE.test(l) || TOTAL.test(l) || amountsIn(l).length || junkName(l)) return;
    const letters = (l.match(/[\p{L}]/gu) ?? []).length;
    const score = (SHOP_WORD.test(l) ? 3 : 0) - i * 0.6 + Math.min(letters, 12) * 0.05;
    if (score > bestScore) {
      best = l;
      bestScore = score;
    }
  });
  return best;
}

/** Scores each category: the shop name and the app's own label count most, item lines a little. */
export function guessCategory(merchant: string, text: string): string {
  const score: Record<string, number> = {};
  for (const [re, cat] of APP_LABELS) if (re.test(text)) score[cat] = (score[cat] ?? 0) + 4;
  for (const [cat, re] of Object.entries(CATEGORY_WORDS)) {
    const inName = new Set(merchant.match(re) ?? []).size;
    const inText = new Set((text.match(re) ?? []).map(w => w.toLowerCase())).size;
    if (inName || inText) score[cat] = (score[cat] ?? 0) + inName * 3 + inText;
  }
  let best = 'UNKNOWN';
  let top = 0;
  for (const [cat, n] of Object.entries(score)) {
    if (n > top) {
      best = cat;
      top = n;
    }
  }
  return best;
}

function findDate(text: string, now = new Date()): string | null {
  const d = text.match(DATE_FULL);
  if (d) return `${d[1]}-${d[2].padStart(2, '0')}-${d[3].padStart(2, '0')}`;
  if (/今天|today/i.test(text)) return now.toISOString().slice(0, 10);
  if (/昨天|yesterday/i.test(text)) return new Date(now.getTime() - 864e5).toISOString().slice(0, 10);
  const s = text.match(DATE_SHORT);
  if (s) {
    const m = Number(s[1]);
    const day = Number(s[2]);
    if (m >= 1 && m <= 12 && day >= 1 && day <= 31) {
      // A month later than now means last year's payment.
      const y = m > now.getMonth() + 1 ? now.getFullYear() - 1 : now.getFullYear();
      return `${y}-${String(m).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    }
  }
  return null;
}

/** One paper receipt or one payment detail screen. */
export function parseReceipt(text: string): ParsedReceipt {
  const lines = cleanLines(text);
  const joined = lines.join('\n');

  // Total: the last line that says "total / 合计 / 实付", or the line right after it.
  let amount: string | null = null;
  for (let i = lines.length - 1; i >= 0 && !amount; i--) {
    if (TOTAL.test(lines[i]) && !SUBTOTAL.test(lines[i])) {
      const here = amountsIn(lines[i]);
      const next = here.length ? here : amountsIn(lines[i + 1] ?? '');
      if (next.length) amount = next[next.length - 1];
    }
  }
  // A payment app's detail screen shows the amount on its own line with a sign: "-28.50".
  if (!amount) {
    const signed = lines.map(l => l.match(/^[-−–—一]\s*[¥￥]?\s*(\d{1,6}(?:,\d{3})*\.\d{2})$/)).find(Boolean);
    if (signed) amount = toAmount(signed[1]);
  }
  // Otherwise the largest believable amount on the receipt.
  if (!amount) {
    const all = lines.flatMap(amountsIn).filter(a => cents(a) > 0 && cents(a) < 10_000_000);
    if (all.length) amount = all.reduce((m, a) => (cents(a) > cents(m) ? a : m));
  }

  const merchant = guessMerchant(lines);
  return { merchant, amount: amount ? fixed(amount) : null, date: findDate(joined), category: guessCategory(merchant, joined), kind: 'out' };
}

// A bill-list row: a name with a signed amount at the end, e.g. "美团外卖 -35.00" or "Salary +5,000.00".
// OCR often reads the minus sign as the Chinese character 一, so that counts as a minus too.
const LIST_ROW = /^(.*?[\p{L}].*?)\s*([-−–—一+＋])\s*[¥￥]?\s*(\d{1,6}(?:,\d{3})*\.\d{2})$/u;

/**
 * Everything found in one picture. A bill list with two or more signed rows gives one entry per
 * row (date and category label are read from the lines under each row); anything else is read
 * as a single receipt.
 */
export function parseReceipts(text: string, now = new Date()): ParsedReceipt[] {
  const lines = cleanLines(text);
  const rows: { i: number; name: string; sign: string; amount: string }[] = [];
  lines.forEach((l, i) => {
    const m = l.match(LIST_ROW);
    if (m) {
      const name = tidyName(m[1]);
      if (wordy(name) && !junkName(name) && !TOTAL.test(name) && !SUBTOTAL.test(name)) rows.push({ i, name, sign: m[2], amount: toAmount(m[3]) });
    }
  });
  if (rows.length < 2) {
    const one = parseReceipt(text);
    return one.amount ? [one] : [];
  }
  return rows.map((r, k) => {
    const until = rows[k + 1]?.i ?? Math.min(lines.length, r.i + 4);
    const detail = lines.slice(r.i + 1, until).join('\n');
    return {
      merchant: r.name,
      amount: fixed(r.amount),
      date: findDate(detail, now),
      category: guessCategory(r.name, r.name + '\n' + detail),
      kind: r.sign === '+' || r.sign === '＋' ? 'in' : 'out',
    };
  });
}
