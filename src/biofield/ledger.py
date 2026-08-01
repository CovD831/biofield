from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from threading import RLock
from typing import Mapping, Protocol

SHARED_POOL = "SharedPool"
SPENT = "Spent"
EXTERNAL = "external"

_AGENT_ESCROW_PREFIX = "AgentEscrow["
_RESERVED_PREFIX = "Reserved["
_ACCOUNT_SUFFIX = "]"
_OPERATIONS = frozenset({"inject", "reserve", "grant", "spend", "return", "expire"})


class ResourceEventLike(Protocol):
    """Structural contract accepted by :class:`ResourceLedger`."""

    event_id: str
    operation: str | Enum
    resource_type: str
    amount: Decimal | int | float | str
    source_account: str | None
    target_account: str | None
    idempotency_key: str | None


class LedgerError(ValueError):
    """Base class for rejected ledger operations."""


class InvalidResourceEvent(LedgerError):
    """Raised when an event violates the resource-event contract."""


class IdempotencyConflict(LedgerError):
    """Raised when an event identity is reused for different work."""


class InsufficientFunds(LedgerError):
    """Raised instead of silently overdrawing an account."""

    def __init__(
        self,
        *,
        resource_type: str,
        account: str,
        available: Decimal,
        requested: Decimal,
    ) -> None:
        self.resource_type = resource_type
        self.account = account
        self.available = available
        self.requested = requested
        super().__init__(
            f"insufficient {resource_type} in {account}: "
            f"available={available}, requested={requested}"
        )


@dataclass(frozen=True)
class LedgerTotals:
    resource_type: str
    initial: Decimal
    injected: Decimal
    shared_pool: Decimal
    escrow: Decimal
    reserved: Decimal
    spent: Decimal

    @property
    def accounted(self) -> Decimal:
        return self.shared_pool + self.escrow + self.reserved + self.spent

    @property
    def expected(self) -> Decimal:
        return self.initial + self.injected


@dataclass(frozen=True)
class SettlementRecord:
    settlement_id: str
    agent_id: str
    returned: tuple[tuple[str, Decimal], ...]

    def returned_by_resource(self) -> dict[str, Decimal]:
        return dict(self.returned)


@dataclass(frozen=True)
class _NormalizedEvent:
    event_id: str
    operation: str
    resource_type: str
    amount: Decimal
    source_account: str | None
    target_account: str | None
    idempotency_key: str | None

    @property
    def semantic_fingerprint(self) -> tuple[str, str, Decimal, str | None, str | None]:
        return (
            self.operation,
            self.resource_type,
            self.amount,
            self.source_account,
            self.target_account,
        )

    @property
    def event_fingerprint(
        self,
    ) -> tuple[tuple[str, str, Decimal, str | None, str | None], str | None]:
        return self.semantic_fingerprint, self.idempotency_key


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidResourceEvent(f"{field} must be a non-empty string")
    return value.strip()


def _decimal(value: object, field: str, *, allow_zero: bool) -> Decimal:
    if isinstance(value, bool):
        raise InvalidResourceEvent(f"{field} must be a decimal-compatible number")
    try:
        # The public event contract uses JSON numbers. Decimal(str(float))
        # preserves that JSON-facing decimal value without ever doing ledger
        # arithmetic in binary floating point.
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise InvalidResourceEvent(f"{field} must be an exact decimal value") from error
    if not amount.is_finite():
        raise InvalidResourceEvent(f"{field} must be finite")
    if amount < 0 or (not allow_zero and amount == 0):
        qualifier = "non-negative" if allow_zero else "positive"
        raise InvalidResourceEvent(f"{field} must be {qualifier}")
    return amount


def _agent_id(value: object) -> str:
    return _non_empty_string(value, "agent_id")


def agent_escrow_account(agent_id: str) -> str:
    return f"{_AGENT_ESCROW_PREFIX}{_agent_id(agent_id)}{_ACCOUNT_SUFFIX}"


def reserved_account(agent_id: str) -> str:
    return f"{_RESERVED_PREFIX}{_agent_id(agent_id)}{_ACCOUNT_SUFFIX}"


def _account_agent(account: str | None, prefix: str) -> str | None:
    if (
        account is None
        or not account.startswith(prefix)
        or not account.endswith(_ACCOUNT_SUFFIX)
    ):
        return None
    raw_agent_id = account[len(prefix) : -len(_ACCOUNT_SUFFIX)]
    try:
        normalized_agent_id = _agent_id(raw_agent_id)
    except InvalidResourceEvent:
        return None
    if raw_agent_id != normalized_agent_id:
        return None
    return normalized_agent_id


class ResourceLedger:
    """Thread-safe, exact resource ledger with per-resource conservation.

    ``grant`` transfers SharedPool to an AgentEscrow. ``reserve`` commits part
    of that escrow, ``spend`` moves an escrow or reservation into the
    irreversible Spent account, and ``return``/``expire`` release unspent
    resources back to SharedPool. Only ``inject`` increases system resources.
    """

    def __init__(self, initial_resources: Mapping[str, Decimal] | None = None) -> None:
        self._lock = RLock()
        self._balances: dict[str, dict[str, Decimal]] = {}
        self._initial: dict[str, Decimal] = {}
        self._injected: dict[str, Decimal] = {}
        self._events_by_id: dict[
            str,
            tuple[tuple[str, str, Decimal, str | None, str | None], str | None],
        ] = {}
        self._events_by_key: dict[
            str, tuple[str, str, Decimal, str | None, str | None]
        ] = {}
        self._processed_event_count = 0
        self._settlements: dict[str, SettlementRecord] = {}
        self._terminal_agents: dict[str, str] = {}

        for resource_type, raw_amount in (initial_resources or {}).items():
            normalized_type = _non_empty_string(resource_type, "resource_type")
            amount = _decimal(raw_amount, "initial resource amount", allow_zero=True)
            self._initial[normalized_type] = amount
            self._balances[normalized_type] = {SHARED_POOL: amount}

    @property
    def processed_event_count(self) -> int:
        with self._lock:
            return self._processed_event_count

    def balance(self, resource_type: str, account: str) -> Decimal:
        normalized_type = _non_empty_string(resource_type, "resource_type")
        normalized_account = _non_empty_string(account, "account")
        with self._lock:
            return self._balances.get(normalized_type, {}).get(
                normalized_account, Decimal(0)
            )

    def totals(self, resource_type: str) -> LedgerTotals:
        normalized_type = _non_empty_string(resource_type, "resource_type")
        with self._lock:
            accounts = self._balances.get(normalized_type, {})
            return LedgerTotals(
                resource_type=normalized_type,
                initial=self._initial.get(normalized_type, Decimal(0)),
                injected=self._injected.get(normalized_type, Decimal(0)),
                shared_pool=accounts.get(SHARED_POOL, Decimal(0)),
                escrow=sum(
                    (
                        amount
                        for account, amount in accounts.items()
                        if account.startswith(_AGENT_ESCROW_PREFIX)
                    ),
                    Decimal(0),
                ),
                reserved=sum(
                    (
                        amount
                        for account, amount in accounts.items()
                        if account.startswith(_RESERVED_PREFIX)
                    ),
                    Decimal(0),
                ),
                spent=accounts.get(SPENT, Decimal(0)),
            )

    def assert_conserved(self) -> None:
        with self._lock:
            resource_types = set(self._balances) | set(self._initial) | set(self._injected)
            for resource_type in resource_types:
                totals = self.totals(resource_type)
                if totals.accounted != totals.expected:
                    raise RuntimeError(
                        f"resource conservation failed for {resource_type}: "
                        f"accounted={totals.accounted}, expected={totals.expected}"
                    )

    def apply(self, event: ResourceEventLike) -> bool:
        """Apply an event atomically; return ``False`` for an exact duplicate."""

        normalized = self._normalize_event(event)
        with self._lock:
            duplicate = self._check_idempotency(normalized)
            if duplicate:
                return False

            self._validate_transition(normalized)
            if normalized.operation == "inject":
                self._credit(
                    normalized.resource_type,
                    SHARED_POOL,
                    normalized.amount,
                )
                self._injected[normalized.resource_type] = (
                    self._injected.get(normalized.resource_type, Decimal(0))
                    + normalized.amount
                )
            else:
                assert normalized.source_account is not None
                assert normalized.target_account is not None
                self._transfer(
                    normalized.resource_type,
                    normalized.source_account,
                    normalized.target_account,
                    normalized.amount,
                )

            self._events_by_id[normalized.event_id] = normalized.event_fingerprint
            if normalized.idempotency_key is not None:
                self._events_by_key[
                    normalized.idempotency_key
                ] = normalized.semantic_fingerprint
            self._processed_event_count += 1
            self.assert_conserved()
            return True

    def settle_abnormal_termination(
        self,
        agent_id: str,
        *,
        settlement_id: str,
    ) -> dict[str, Decimal]:
        """Atomically return all unspent escrow/reservations for a failed agent.

        Already spent resources remain in ``spent``. Replaying the same
        settlement returns its original result without moving funds twice.
        """

        normalized_agent = _agent_id(agent_id)
        normalized_settlement = _non_empty_string(settlement_id, "settlement_id")
        with self._lock:
            previous = self._settlements.get(normalized_settlement)
            if previous is not None:
                if previous.agent_id != normalized_agent:
                    raise IdempotencyConflict(
                        "settlement_id was already used for another agent"
                    )
                return previous.returned_by_resource()

            existing_settlement = self._terminal_agents.get(normalized_agent)
            if existing_settlement is not None:
                raise IdempotencyConflict(
                    f"agent is already terminal under settlement {existing_settlement}"
                )

            escrow = agent_escrow_account(normalized_agent)
            reserved = reserved_account(normalized_agent)
            returned: dict[str, Decimal] = {}
            for resource_type, accounts in self._balances.items():
                amount = accounts.get(escrow, Decimal(0)) + accounts.get(
                    reserved, Decimal(0)
                )
                if amount == 0:
                    continue
                accounts[escrow] = Decimal(0)
                accounts[reserved] = Decimal(0)
                accounts[SHARED_POOL] = accounts.get(SHARED_POOL, Decimal(0)) + amount
                returned[resource_type] = amount

            ordered_returned = dict(sorted(returned.items()))
            record = SettlementRecord(
                settlement_id=normalized_settlement,
                agent_id=normalized_agent,
                returned=tuple(ordered_returned.items()),
            )
            self._settlements[normalized_settlement] = record
            self._terminal_agents[normalized_agent] = normalized_settlement
            self.assert_conserved()
            return dict(ordered_returned)

    def settlement_record(self, settlement_id: str) -> SettlementRecord:
        normalized_settlement = _non_empty_string(settlement_id, "settlement_id")
        with self._lock:
            try:
                return self._settlements[normalized_settlement]
            except KeyError as error:
                raise KeyError(normalized_settlement) from error

    def _normalize_event(self, event: ResourceEventLike) -> _NormalizedEvent:
        try:
            event_id = _non_empty_string(event.event_id, "event_id")
            raw_operation = event.operation
            resource_type = _non_empty_string(event.resource_type, "resource_type")
            amount = _decimal(event.amount, "amount", allow_zero=False)
            source = event.source_account
            target = event.target_account
            raw_key = getattr(event, "idempotency_key", None)
        except AttributeError as error:
            raise InvalidResourceEvent(f"missing event field: {error.name}") from error

        if isinstance(raw_operation, Enum):
            raw_operation = raw_operation.value
        operation = _non_empty_string(raw_operation, "operation").lower()
        if operation not in _OPERATIONS:
            raise InvalidResourceEvent(f"unsupported operation: {operation}")
        if source is not None:
            source = _non_empty_string(source, "source_account")
        if target is not None:
            target = _non_empty_string(target, "target_account")
        key = None if raw_key is None else _non_empty_string(raw_key, "idempotency_key")
        return _NormalizedEvent(
            event_id=event_id,
            operation=operation,
            resource_type=resource_type,
            amount=amount,
            source_account=source,
            target_account=target,
            idempotency_key=key,
        )

    def _check_idempotency(self, event: _NormalizedEvent) -> bool:
        previous_event = self._events_by_id.get(event.event_id)
        if previous_event is not None:
            if previous_event != event.event_fingerprint:
                raise IdempotencyConflict("event_id was reused with a different payload")
            return True

        if event.idempotency_key is not None:
            previous_key = self._events_by_key.get(event.idempotency_key)
            if previous_key is not None:
                if previous_key != event.semantic_fingerprint:
                    raise IdempotencyConflict(
                        "idempotency_key was reused with a different payload"
                    )
                # Remember the retry's event ID so it cannot later identify
                # different work, while keeping the applied-event count stable.
                self._events_by_id[event.event_id] = event.event_fingerprint
                return True
        return False

    def _validate_transition(self, event: _NormalizedEvent) -> None:
        source = event.source_account
        target = event.target_account
        source_agent = _account_agent(source, _AGENT_ESCROW_PREFIX)
        source_reservation_agent = _account_agent(source, _RESERVED_PREFIX)
        target_agent = _account_agent(target, _AGENT_ESCROW_PREFIX)
        target_reservation_agent = _account_agent(target, _RESERVED_PREFIX)

        involved_agents = {
            agent
            for agent in (
                source_agent,
                source_reservation_agent,
                target_agent,
                target_reservation_agent,
            )
            if agent is not None
        }
        terminal = involved_agents.intersection(self._terminal_agents)
        if terminal:
            raise InvalidResourceEvent(
                f"resource event references terminal agent: {sorted(terminal)[0]}"
            )

        if event.operation == "inject":
            if source not in {None, EXTERNAL} or target != SHARED_POOL:
                raise InvalidResourceEvent(
                    "inject must transfer external resources into shared_pool"
                )
            return
        if event.operation == "grant":
            if source != SHARED_POOL or target_agent is None:
                raise InvalidResourceEvent(
                    "grant must transfer shared_pool to an agent escrow"
                )
            return
        if event.operation == "reserve":
            if (
                source_agent is None
                or target_reservation_agent is None
                or source_agent != target_reservation_agent
            ):
                raise InvalidResourceEvent(
                    "reserve must transfer an agent escrow to its reservation"
                )
            return
        if event.operation == "spend":
            if (source_agent is None and source_reservation_agent is None) or target != SPENT:
                raise InvalidResourceEvent(
                    "spend must transfer an agent escrow or reservation to spent"
                )
            return
        if event.operation in {"return", "expire"}:
            if (
                source_agent is None and source_reservation_agent is None
            ) or target != SHARED_POOL:
                raise InvalidResourceEvent(
                    f"{event.operation} must transfer unspent agent resources to shared_pool"
                )
            return
        raise AssertionError(f"unhandled operation: {event.operation}")

    def _credit(self, resource_type: str, account: str, amount: Decimal) -> None:
        accounts = self._balances.setdefault(resource_type, {})
        accounts[account] = accounts.get(account, Decimal(0)) + amount

    def _transfer(
        self,
        resource_type: str,
        source: str,
        target: str,
        amount: Decimal,
    ) -> None:
        accounts = self._balances.setdefault(resource_type, {})
        available = accounts.get(source, Decimal(0))
        if available < amount:
            raise InsufficientFunds(
                resource_type=resource_type,
                account=source,
                available=available,
                requested=amount,
            )
        accounts[source] = available - amount
        accounts[target] = accounts.get(target, Decimal(0)) + amount
