import type { ReactNode } from 'react';
import { useApp } from '../app/state';
import { agentResultKind, resultItems, savingsProgress } from '../core/agentResults';
import { categoryKey, formatDate } from '../core/format';
import { formatMoney } from '../core/money';
import { Amount, Badge, Icon } from './kit';

interface AgentResultProps {
  intent: string;
  result: Record<string, unknown> | null;
  fallback: string;
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

export function AgentResult({ intent, result, fallback }: AgentResultProps) {
  const { t, locale } = useApp();
  const r = result ?? {};
  if (typeof r.reply === 'string') return <p className="agent-result-copy">{r.reply}</p>;
  if (typeof r.balance === 'string') {
    return (
      <section className="agent-result balance-result">
        <span className="agent-result-label">{t('aegis.balance')}</span>
        <Amount value={r.balance} currency={text(r.currency) || 'CNY'} />
      </section>
    );
  }
  if (Array.isArray(r.accounts)) {
    const accounts = r.accounts as Record<string, unknown>[];
    return (
      <ResultSection icon="i-bank" title={t('aegis.result.accounts')} count={accounts.length} href="#/cards" action={t('aegis.viewAccounts')}>
        {accounts.map((account, index) => (
          <ResultRow key={text(account.id) || text(account.account_number) || index} icon="i-bank">
            <div className="agent-result-main">
              <b>{text(account.name) || t('aegis.account')}</b>
              <span>{text(account.account_number) ? `•••• ${text(account.account_number).slice(-4)}` : ''}</span>
            </div>
            {typeof account.balance === 'string' && <strong>{formatMoney(account.balance, text(account.currency) || 'CNY')}</strong>}
          </ResultRow>
        ))}
      </ResultSection>
    );
  }
  if (typeof r.total === 'string' && r.by_category && typeof r.by_category === 'object') {
    return (
      <section className="agent-result balance-result">
        <span className="agent-result-label">{t('aegis.spendingTotal')}</span>
        <Amount value={r.total} />
        <div className="agent-result-breakdown">
          {Object.entries(r.by_category as Record<string, string>).map(([category, value]) => (
            <span key={category}>
              {t(`cat.${categoryKey(category)}`)}
              <b>{formatMoney(value)}</b>
            </span>
          ))}
        </div>
      </section>
    );
  }

  const kind = agentResultKind(intent);
  const items = resultItems(r, kind);
  if (!items.length) return <p className="agent-result-copy">{fallback}</p>;

  if (kind === 'cards') {
    return (
      <ResultSection icon="i-card" title={t('aegis.result.cards')} count={items.length} href="#/cards" action={t('aegis.viewCards')}>
        {items.map((card, index) => (
          <ResultRow key={text(card.id) || index} icon="i-card">
            <div className="agent-result-main">
              <b>{text(card.label) || t('cards.debit')}</b>
              <span>•••• {text(card.last_four) || '—'} · {t('aegis.cardLimit', { amount: formatMoney(text(card.spending_limit) || '0') })}</span>
            </div>
            <StatusBadge status={text(card.status)} />
          </ResultRow>
        ))}
      </ResultSection>
    );
  }

  if (kind === 'savings') {
    return (
      <ResultSection icon="i-target" title={t('aegis.result.savings')} count={items.length} href="#/wealth" action={t('aegis.viewSavings')}>
        {items.map((pot, index) => {
          const saved = text(pot.saved_amount) || '0';
          const target = text(pot.target_amount) || '0';
          const currency = text(pot.currency) || 'CNY';
          const pct = savingsProgress(saved, target);
          return (
            <article className="agent-goal" key={text(pot.id) || index}>
              <div className="agent-goal-head">
                <b>{text(pot.name) || t('aegis.savingsGoal')}</b>
                <StatusBadge status={text(pot.status)} />
              </div>
              <div className="agent-goal-money">
                <strong>{formatMoney(saved, currency)}</strong>
                <span>{t('aegis.savedOf', { target: formatMoney(target, currency) })}</span>
              </div>
              <div className="agent-progress" role="progressbar" aria-label={t('aegis.goalProgress')} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
                <i style={{ width: `${pct}%` }} />
              </div>
              <div className="agent-goal-meta">
                <span>{pct}%</span>
                {text(pot.target_date) && <span>{t('aegis.goalDate', { date: formatDate(text(pot.target_date), locale) })}</span>}
              </div>
            </article>
          );
        })}
      </ResultSection>
    );
  }

  if (kind === 'wealth') {
    return (
      <ResultSection icon="i-trend-up" title={intent === 'GET_WEALTH_RECOMMENDATIONS' ? t('aegis.result.recommendations') : t('aegis.result.wealth')} count={items.length} href="#/wealth" action={t('aegis.viewWealth')}>
        {items.map((product, index) => {
          const risk = text(product.risk_tier) || 'GREEN';
          const productType = text(product.product_type);
          return (
            <ResultRow key={text(product.id) || index} icon="i-chart">
              <div className="agent-result-main">
                <b>{text(product.name) || text(product.code) || t('aegis.investment')}</b>
                <span>
                  {productType ? t(`pt.${productType}` as 'pt.BOND_FUND') : ''}
                  {typeof product.minimum_amount === 'string' ? ` · ${t('inv.min', { amount: formatMoney(product.minimum_amount, text(product.currency) || 'CNY') })}` : ''}
                </span>
                <small>{product.supports_redemption ? t('aegis.redeemable') : t('aegis.notRedeemable')}</small>
              </div>
              <Badge tone={risk}>{t(`inv.risk.${risk}` as 'inv.risk.GREEN')}</Badge>
            </ResultRow>
          );
        })}
      </ResultSection>
    );
  }

  return (
    <ResultSection icon="i-check" title={t('aegis.result.details')} count={items.length}>
      {items.slice(0, 8).map((item, index) => (
        <ResultRow key={text(item.id) || index} icon="i-check">
          <div className="agent-result-main">
            <b>{text(item.name) || text(item.label) || text(item.merchant_name) || text(item.description) || t('aegis.result.item')}</b>
            <span>
              {text(item.last_four) ? `•••• ${text(item.last_four)}` : ''}
              {typeof item.amount === 'string' ? `${text(item.last_four) ? ' · ' : ''}${formatMoney(item.amount, text(item.currency) || 'CNY')}` : ''}
            </span>
          </div>
          {text(item.status) && <StatusBadge status={text(item.status)} />}
        </ResultRow>
      ))}
    </ResultSection>
  );
}

function ResultSection({ icon, title, count, href, action, children }: { icon: string; title: string; count: number; href?: string; action?: string; children: ReactNode }) {
  const { t } = useApp();
  return (
    <section className="agent-result">
      <header className="agent-result-head">
        <span className="agent-result-title"><Icon name={icon} />{title}</span>
        <span className="agent-result-count">{t('aegis.itemCount', { n: count })}</span>
      </header>
      <div className="agent-result-list">{children}</div>
      {href && action && <a className="agent-result-link" href={href}>{action}</a>}
    </section>
  );
}

function ResultRow({ icon, children }: { icon: string; children: ReactNode }) {
  return (
    <div className="agent-result-row">
      <span className="agent-result-icon"><Icon name={icon} /></span>
      {children}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const { t } = useApp();
  const labels: Record<string, ReturnType<typeof t>> = {
    ACTIVE: t('aegis.status.active'),
    FROZEN: t('aegis.status.frozen'),
    LOST: t('aegis.status.lost'),
    COMPLETED: t('aegis.status.completed'),
    CANCELLED: t('aegis.status.cancelled'),
  };
  return <Badge tone={status || 'ACTIVE'}>{labels[status] ?? status}</Badge>;
}

