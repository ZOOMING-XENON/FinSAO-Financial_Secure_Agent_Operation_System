// Wire types for Banking Core and the Agent API. Money is always a decimal string ("800.00").

export type Money = string;
export type Currency = 'CNY' | 'USD' | 'EUR';
export type RiskTier = 'GREEN' | 'YELLOW' | 'RED';

export const CATEGORIES = ['HOUSEHOLD', 'GROCERIES', 'TRANSPORT', 'ENTERTAINMENT', 'DINING', 'UNKNOWN'] as const;
export type Category = (typeof CATEGORIES)[number];

export interface Account {
  id: string;
  account_number: string;
  name: string;
  currency: Currency;
  status: 'ACTIVE' | 'FROZEN' | 'CLOSED';
}

export interface Balance {
  account_id: string;
  balance: Money;
  currency: Currency;
}

export interface Transaction {
  id: string;
  reference: string;
  status: 'PENDING' | 'COMPLETED' | 'FAILED' | 'REVERSED';
  amount: Money;
  currency: Currency;
  description: string;
  category: string | null;
  posted_at: string | null;
}

export interface TransactionPage {
  items: Transaction[];
  limit: number;
  offset: number;
}

export interface Beneficiary {
  id: string;
  name: string;
  nickname: string | null;
  destination_account_id: string;
  destination_account_number: string;
}

export interface TransferDraft {
  id: string;
  source_account_id: string;
  destination_account_id: string;
  amount: Money;
  currency: Currency;
  status: string;
  expires_at: string;
  transaction_id: string | null;
}

export interface TransferReceipt {
  transaction_id: string;
  reference: string;
  status: Transaction['status'];
  amount: Money;
  currency: Currency;
}

export interface Approval {
  id: string;
  operation_id: string;
  operation_type: string;
  target_account_id: string | null;
  recipient_id: string | null;
  amount: Money | null;
  currency: Currency | null;
  risk_tier: RiskTier;
  status: string;
  expires_at: string;
}

export interface AuthorizationGrant {
  authorization_ref: string;
  expires_at: string;
}

export interface MfaChallenge {
  challenge_id: string;
  expires_at: string;
}

export interface Card {
  id: string;
  account_id: string;
  label: string;
  last_four: string;
  status: 'ACTIVE' | 'FROZEN' | 'LOST' | 'CANCELLED' | 'EXPIRED';
  spending_limit: Money;
}

export interface Subscription {
  id: string;
  merchant_name: string;
  amount: Money;
  currency: Currency;
  next_billing_date: string;
  active: boolean;
  status: string;
  cancelled_at: string | null;
}

export interface SpendingSummary {
  total: Money;
  by_category: Record<string, Money>;
  by_merchant: Record<string, Money>;
}

export interface Budget {
  id: string;
  category: string;
  month: string;
  limit_amount: Money;
  currency: Currency;
}

export interface BudgetStatus {
  limit: Money;
  used: Money;
  remaining: Money;
  estimate: Money;
  threshold_exceeded: boolean;
}

export interface SavingsPot {
  id: string;
  name: string;
  target_amount: Money;
  saved_amount: Money;
  currency: Currency;
  target_date: string;
  status: string;
  allocation_mode: 'VIRTUAL_ALLOCATION';
  created_at: string;
  updated_at: string;
}

export interface SavingsContribution {
  id: string;
  pot_id: string;
  amount: Money;
  note: string | null;
  created_at: string;
}

/* ---------- Agent API ---------- */

export interface ClarificationField {
  name: string;
  label: string;
  value: unknown;
  options: { value: string; label: string }[];
  inferred: boolean;
  required: boolean;
  input_type: 'text' | 'date' | 'month' | 'amount' | 'select' | 'combobox';
}

export interface ToolCall {
  tool_name: string;
  arguments: Record<string, unknown>;
}

export interface PlanStep {
  step_id: string;
  purpose: string;
  tool_call: ToolCall | null;
}

export interface AgentTask {
  id: string;
  status: 'COMPLETED' | 'NEEDS_CLARIFICATION' | 'WAITING_APPROVAL' | 'FAILED' | string;
  public_message: string | null;
  plan: { goal: string; steps: PlanStep[] } | null;
  result: Record<string, unknown> | null;
  error_code: string | null;
}

export interface ConversationMessage {
  role: 'user' | 'assistant';
  content: string;
}
