from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

import pytest

from biofield.contracts import ResourceEvent, ResourceOperation
from biofield.ledger import (
    SHARED_POOL,
    SPENT,
    IdempotencyConflict,
    InsufficientFunds,
    InvalidResourceEvent,
    ResourceLedger,
    agent_escrow_account,
    reserved_account,
)


class Operation(Enum):
    INJECT = "inject"
    RESERVE = "reserve"
    GRANT = "grant"
    SPEND = "spend"
    RETURN = "return"
    EXPIRE = "expire"


@dataclass(frozen=True)
class Event:
    event_id: str
    operation: str | Operation
    resource_type: str
    amount: Decimal
    source_account: str | None
    target_account: str | None
    idempotency_key: str | None = None


def event(
    event_id: str,
    operation: str | Operation,
    amount: str,
    source: str | None,
    target: str | None,
    *,
    resource_type: str = "tokens",
    idempotency_key: str | None = None,
) -> Event:
    return Event(
        event_id=event_id,
        operation=operation,
        resource_type=resource_type,
        amount=Decimal(amount),
        source_account=source,
        target_account=target,
        idempotency_key=idempotency_key,
    )


def test_full_resource_lifecycle_is_conserved_per_resource_type() -> None:
    ledger = ResourceLedger({"tokens": Decimal("10"), "api_calls": Decimal("2")})
    alice = agent_escrow_account("alice")
    alice_reserved = reserved_account("alice")

    assert ledger.apply(event("i1", Operation.INJECT, "5", None, SHARED_POOL))
    assert ledger.apply(event("g1", "grant", "9", SHARED_POOL, alice))
    assert ledger.apply(event("r1", "reserve", "6", alice, alice_reserved))
    assert ledger.apply(event("s1", "spend", "4", alice_reserved, SPENT))
    assert ledger.apply(event("b1", "return", "1", alice_reserved, SHARED_POOL))
    assert ledger.apply(event("x1", "expire", "1", alice_reserved, SHARED_POOL))

    assert ledger.balance("tokens", SHARED_POOL) == Decimal("8")
    assert ledger.balance("tokens", alice) == Decimal("3")
    assert ledger.balance("tokens", alice_reserved) == Decimal("0")
    assert ledger.balance("tokens", SPENT) == Decimal("4")

    token_totals = ledger.totals("tokens")
    assert token_totals.initial == Decimal("10")
    assert token_totals.injected == Decimal("5")
    assert token_totals.accounted == Decimal("15")
    assert token_totals.expected == Decimal("15")

    # A different resource type has an independent conservation equation.
    assert ledger.balance("api_calls", SHARED_POOL) == Decimal("2")
    assert ledger.totals("api_calls").accounted == Decimal("2")
    ledger.assert_conserved()


def test_duplicate_event_and_duplicate_idempotency_key_are_no_ops() -> None:
    ledger = ResourceLedger()
    original = event(
        "inject-attempt-1",
        "inject",
        "3.25",
        None,
        SHARED_POOL,
        idempotency_key="invoice-42",
    )

    assert ledger.apply(original) is True
    assert ledger.apply(original) is False
    assert ledger.apply(
        event(
            "inject-retry-2",
            "inject",
            "3.25",
            None,
            SHARED_POOL,
            idempotency_key="invoice-42",
        )
    ) is False

    assert ledger.balance("tokens", SHARED_POOL) == Decimal("3.25")
    assert ledger.processed_event_count == 1
    ledger.assert_conserved()


def test_public_resource_event_float_is_decimalized_at_the_boundary() -> None:
    ledger = ResourceLedger()

    for sequence, amount in enumerate((0.1, 0.2), start=1):
        ledger.apply(
            ResourceEvent(
                event_id=f"public-{sequence}",
                operation=ResourceOperation.INJECT,
                resource_type="tokens",
                amount=amount,
                source_account="external",
                target_account=SHARED_POOL,
                idempotency_key=f"public-key-{sequence}",
            )
        )

    assert ledger.balance("tokens", SHARED_POOL) == Decimal("0.3")
    assert ledger.totals("tokens").injected == Decimal("0.3")
    ledger.assert_conserved()


def test_public_contract_account_names_match_the_architecture_ledger() -> None:
    ledger = ResourceLedger()
    events = (
        ResourceEvent(
            event_id="inject",
            operation=ResourceOperation.INJECT,
            resource_type="tokens",
            amount=3,
            source_account="external",
            target_account="SharedPool",
            idempotency_key="inject",
        ),
        ResourceEvent(
            event_id="grant",
            operation=ResourceOperation.GRANT,
            resource_type="tokens",
            amount=2,
            source_account="SharedPool",
            target_account="AgentEscrow[agent-1]",
            idempotency_key="grant",
        ),
        ResourceEvent(
            event_id="reserve",
            operation=ResourceOperation.RESERVE,
            resource_type="tokens",
            amount=1,
            source_account="AgentEscrow[agent-1]",
            target_account="Reserved[agent-1]",
            idempotency_key="reserve",
        ),
        ResourceEvent(
            event_id="spend",
            operation=ResourceOperation.SPEND,
            resource_type="tokens",
            amount=1,
            source_account="Reserved[agent-1]",
            target_account="Spent",
            idempotency_key="spend",
        ),
    )

    for item in events:
        assert ledger.apply(item)

    assert ledger.balance("tokens", "SharedPool") == Decimal("1")
    assert ledger.balance("tokens", "AgentEscrow[agent-1]") == Decimal("1")
    assert ledger.balance("tokens", "Spent") == Decimal("1")
    ledger.assert_conserved()


def test_reusing_an_identity_with_a_different_payload_is_rejected() -> None:
    ledger = ResourceLedger()
    ledger.apply(
        event(
            "inject-1",
            "inject",
            "3",
            None,
            SHARED_POOL,
            idempotency_key="invoice-1",
        )
    )

    with pytest.raises(IdempotencyConflict, match="event_id"):
        ledger.apply(event("inject-1", "inject", "4", None, SHARED_POOL))

    with pytest.raises(IdempotencyConflict, match="idempotency_key"):
        ledger.apply(
            event(
                "inject-2",
                "inject",
                "4",
                None,
                SHARED_POOL,
                idempotency_key="invoice-1",
            )
        )

    assert ledger.balance("tokens", SHARED_POOL) == Decimal("3")


@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-1")])
def test_non_positive_amount_is_rejected_without_mutating_the_ledger(
    amount: Decimal,
) -> None:
    ledger = ResourceLedger({"tokens": Decimal("2")})
    invalid = Event("bad", "grant", "tokens", amount, SHARED_POOL, agent_escrow_account("a"))

    with pytest.raises(InvalidResourceEvent, match="positive"):
        ledger.apply(invalid)

    assert ledger.balance("tokens", SHARED_POOL) == Decimal("2")
    assert ledger.processed_event_count == 0
    ledger.assert_conserved()


@pytest.mark.parametrize("amount", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_duck_event_amount_is_rejected(amount: float) -> None:
    ledger = ResourceLedger({"tokens": Decimal("2")})
    invalid = Event(  # type: ignore[arg-type]
        "bad-float",
        "grant",
        "tokens",
        amount,
        SHARED_POOL,
        agent_escrow_account("a"),
    )

    with pytest.raises(InvalidResourceEvent, match="finite"):
        ledger.apply(invalid)

    assert ledger.balance("tokens", SHARED_POOL) == Decimal("2")


def test_invalid_account_transition_is_rejected() -> None:
    ledger = ResourceLedger({"tokens": Decimal("2")})

    with pytest.raises(InvalidResourceEvent, match="grant"):
        ledger.apply(event("bad-route", "grant", "1", SHARED_POOL, SPENT))

    assert ledger.balance("tokens", SHARED_POOL) == Decimal("2")


def test_spent_resources_cannot_be_returned() -> None:
    ledger = ResourceLedger({"tokens": Decimal("2")})
    alice = agent_escrow_account("alice")
    ledger.apply(event("grant", "grant", "2", SHARED_POOL, alice))
    ledger.apply(event("spend", "spend", "2", alice, SPENT))

    with pytest.raises(InvalidResourceEvent, match="return"):
        ledger.apply(event("undo", "return", "1", SPENT, SHARED_POOL))

    assert ledger.balance("tokens", SPENT) == Decimal("2")
    ledger.assert_conserved()


def test_overspend_is_explicitly_rejected_and_can_be_retried() -> None:
    ledger = ResourceLedger({"tokens": Decimal("5")})
    alice = agent_escrow_account("alice")
    grant = event("grant-1", "grant", "6", SHARED_POOL, alice, idempotency_key="grant-alice")

    with pytest.raises(InsufficientFunds) as error:
        ledger.apply(grant)

    assert error.value.available == Decimal("5")
    assert error.value.requested == Decimal("6")
    assert ledger.processed_event_count == 0

    # A rejected event does not consume its identity, so a corrected retry is valid.
    corrected = event("grant-1", "grant", "5", SHARED_POOL, alice, idempotency_key="grant-alice")
    assert ledger.apply(corrected)
    assert ledger.balance("tokens", alice) == Decimal("5")
    ledger.assert_conserved()


def test_abnormal_termination_returns_unspent_escrow_and_reservations() -> None:
    ledger = ResourceLedger({"tokens": Decimal("10"), "api_calls": Decimal("3")})
    alice = agent_escrow_account("alice")
    alice_reserved = reserved_account("alice")

    ledger.apply(event("tg", "grant", "8", SHARED_POOL, alice))
    ledger.apply(event("tr", "reserve", "5", alice, alice_reserved))
    ledger.apply(event("ts", "spend", "2", alice_reserved, SPENT))
    ledger.apply(event("ag", "grant", "2", SHARED_POOL, alice, resource_type="api_calls"))
    ledger.apply(
        event(
            "ar",
            "reserve",
            "1",
            alice,
            alice_reserved,
            resource_type="api_calls",
        )
    )

    returned = ledger.settle_abnormal_termination("alice", settlement_id="crash-1")

    assert returned == {"api_calls": Decimal("2"), "tokens": Decimal("6")}
    assert ledger.balance("tokens", SHARED_POOL) == Decimal("8")
    assert ledger.balance("tokens", SPENT) == Decimal("2")
    assert ledger.balance("tokens", alice) == Decimal("0")
    assert ledger.balance("tokens", alice_reserved) == Decimal("0")
    assert ledger.balance("api_calls", SHARED_POOL) == Decimal("3")

    # Settlement retries do not return resources twice.
    assert ledger.settle_abnormal_termination("alice", settlement_id="crash-1") == returned
    record = ledger.settlement_record("crash-1")
    assert record.agent_id == "alice"
    assert record.returned_by_resource() == returned
    ledger.assert_conserved()


def test_terminated_agent_cannot_receive_new_resource_events() -> None:
    ledger = ResourceLedger({"tokens": Decimal("3")})
    alice = agent_escrow_account("alice")
    ledger.settle_abnormal_termination("alice", settlement_id="crash-1")

    with pytest.raises(InvalidResourceEvent, match="terminal"):
        ledger.apply(event("grant-after-crash", "grant", "1", SHARED_POOL, alice))

    with pytest.raises(IdempotencyConflict, match="already terminal"):
        ledger.settle_abnormal_termination("alice", settlement_id="crash-2")

    assert ledger.balance("tokens", SHARED_POOL) == Decimal("3")


@pytest.mark.parametrize(
    ("operation", "source", "target"),
    [
        ("grant", SHARED_POOL, "AgentEscrow[ alice ]"),
        ("reserve", "AgentEscrow[ alice ]", "Reserved[ alice ]"),
        ("spend", "Reserved[ alice ]", SPENT),
    ],
)
def test_noncanonical_accounts_cannot_bypass_a_terminal_agent_guard(
    operation: str,
    source: str,
    target: str,
) -> None:
    ledger = ResourceLedger({"tokens": Decimal("3")})
    ledger.settle_abnormal_termination("alice", settlement_id="crash-1")

    with pytest.raises(InvalidResourceEvent):
        ledger.apply(event(f"bad-{operation}", operation, "1", source, target))

    assert ledger.balance("tokens", SHARED_POOL) == Decimal("3")
    ledger.assert_conserved()


def test_same_settlement_id_cannot_be_reused_for_another_agent() -> None:
    ledger = ResourceLedger()
    ledger.settle_abnormal_termination("alice", settlement_id="crash-1")

    with pytest.raises(IdempotencyConflict, match="settlement_id"):
        ledger.settle_abnormal_termination("bob", settlement_id="crash-1")


def test_concurrent_grants_cannot_overdraw_shared_pool() -> None:
    ledger = ResourceLedger({"tokens": Decimal("10")})
    events = [
        event("grant-a", "grant", "7", SHARED_POOL, agent_escrow_account("a")),
        event("grant-b", "grant", "7", SHARED_POOL, agent_escrow_account("b")),
    ]

    def attempt(item: Event) -> str:
        try:
            ledger.apply(item)
        except InsufficientFunds:
            return "rejected"
        return "applied"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, events))

    assert sorted(outcomes) == ["applied", "rejected"]
    assert ledger.balance("tokens", SHARED_POOL) == Decimal("3")
    assert sum(
        ledger.balance("tokens", account)
        for account in (agent_escrow_account("a"), agent_escrow_account("b"))
    ) == Decimal("7")
    ledger.assert_conserved()
