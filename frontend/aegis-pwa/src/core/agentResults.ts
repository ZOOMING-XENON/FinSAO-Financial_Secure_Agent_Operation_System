import { percent } from './money';

export type AgentResultKind = 'cards' | 'savings' | 'wealth' | 'generic';

export function agentResultKind(intent: string): AgentResultKind {
  if (intent === 'LIST_CARDS' || intent === 'GET_CARD') return 'cards';
  if (intent === 'LIST_SAVINGS_POTS') return 'savings';
  if (
    intent === 'GET_WEALTH_RECOMMENDATIONS'
    || intent === 'LIST_WEALTH_PRODUCTS'
    || intent === 'COMPARE_WEALTH_PRODUCTS'
  ) return 'wealth';
  return 'generic';
}

export function resultItems(result: Record<string, unknown>, kind: AgentResultKind): Record<string, unknown>[] {
  const collection = [result.items, result.products, result.recommendations, result.pots]
    .find(Array.isArray);
  if (collection) {
    return collection.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object');
  }
  const isSingleItem = (
    (kind === 'cards' && ('last_four' in result || 'spending_limit' in result))
    || (kind === 'savings' && ('saved_amount' in result || 'target_amount' in result))
    || (kind === 'wealth' && ('risk_tier' in result || 'minimum_amount' in result))
  );
  return isSingleItem ? [result] : [];
}

export function savingsProgress(saved: unknown, target: unknown): number {
  if (typeof saved !== 'string' || typeof target !== 'string') return 0;
  try {
    return percent(saved, target);
  } catch {
    return 0;
  }
}

