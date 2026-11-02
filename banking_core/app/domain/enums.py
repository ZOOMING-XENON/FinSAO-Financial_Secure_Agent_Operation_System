from enum import StrEnum


class Currency(StrEnum):
    CNY = "CNY"
    USD = "USD"
    EUR = "EUR"


class AccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class TransactionKind(StrEnum):
    EXPENSE = "EXPENSE"
    INCOME = "INCOME"
    REFUND = "REFUND"
    TRANSFER = "TRANSFER"
    OPENING_BALANCE = "OPENING_BALANCE"
    ADJUSTMENT = "ADJUSTMENT"


class TransactionOrigin(StrEnum):
    BANK = "BANK"
    CARD = "CARD"
    CASH = "CASH"
    MANUAL = "MANUAL"
    IMPORT = "IMPORT"


class TransactionDirection(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"
    MOVE = "MOVE"


class TransactionStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


class TransferStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_AUTHORIZATION = "PENDING_AUTHORIZATION"
    AUTHORIZED = "AUTHORIZED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class CardStatus(StrEnum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    LOST = "LOST"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class RiskTier(StrEnum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class WealthOrderType(StrEnum):
    SUBSCRIPTION = "SUBSCRIPTION"
    REDEMPTION = "REDEMPTION"
