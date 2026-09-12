"""Settlement suggestions - the "who owes whom" half of the balance.

`suggest_settlements` is a pure function over already-computed balances, so it
can be exercised without a database. The invariant that matters: after applying
every suggested transfer, everybody sits at zero.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.schemas import PartnerBalance
from app.services.balance import suggest_settlements


def partner(name: str, net: str, share: str = "0.5") -> PartnerBalance:
    """A balance row with only the fields the suggester actually reads."""
    return PartnerBalance(
        user_id=uuid.uuid4(),
        display_name=name,
        equity_share=Decimal(share),
        personal_outlay=Decimal("0.00"),
        business_outlay=Decimal("0.00"),
        unverified_outlay=Decimal("0.00"),
        fair_share=Decimal("0.00"),
        settlements_received=Decimal("0.00"),
        settlements_paid=Decimal("0.00"),
        net_position=Decimal(net),
        document_count=0,
    )


def test_two_partners_settle_with_one_transfer() -> None:
    # Ana spent 1000 of her own money, Bogdan 400. Fair share is 700 each,
    # so Bogdan owes Ana 300.
    ana = partner("Ana", "300.00")
    bogdan = partner("Bogdan", "-300.00")

    suggestions = suggest_settlements([ana, bogdan])

    assert len(suggestions) == 1
    transfer = suggestions[0]
    assert transfer.from_user_id == bogdan.user_id
    assert transfer.to_user_id == ana.user_id
    assert transfer.amount == Decimal("300.00")


def test_balanced_partners_need_no_transfer() -> None:
    assert suggest_settlements([partner("Ana", "0.00"), partner("Bogdan", "0.00")]) == []


def test_rounding_noise_is_not_a_debt() -> None:
    """Nobody should be told to transfer one ban."""
    suggestions = suggest_settlements(
        [partner("Ana", "0.01"), partner("Bogdan", "-0.01")]
    )
    assert suggestions == []


def test_three_partners_need_at_most_two_transfers() -> None:
    ana = partner("Ana", "500.00")
    bogdan = partner("Bogdan", "-200.00")
    carmen = partner("Carmen", "-300.00")

    suggestions = suggest_settlements([ana, bogdan, carmen])

    assert len(suggestions) == 2
    assert all(s.to_user_id == ana.user_id for s in suggestions)
    assert sum(s.amount for s in suggestions) == Decimal("500.00")


def test_transfers_flatten_everyone_to_zero() -> None:
    """The property that actually matters, whatever the split looks like."""
    balances = [
        partner("Ana", "750.50"),
        partner("Bogdan", "-200.25"),
        partner("Carmen", "-550.25"),
    ]
    positions = {b.user_id: b.net_position for b in balances}

    for transfer in suggest_settlements(balances):
        positions[transfer.from_user_id] += transfer.amount
        positions[transfer.to_user_id] -= transfer.amount

    assert all(abs(value) <= Decimal("0.01") for value in positions.values())


def test_a_partner_owed_nothing_is_left_out() -> None:
    ana = partner("Ana", "100.00")
    bogdan = partner("Bogdan", "-100.00")
    carmen = partner("Carmen", "0.00")

    suggestions = suggest_settlements([ana, bogdan, carmen])

    involved = {s.from_user_id for s in suggestions} | {s.to_user_id for s in suggestions}
    assert carmen.user_id not in involved


def test_suggestions_do_not_mutate_the_input_balances() -> None:
    """The report returns these same rows; they must survive the calculation."""
    ana = partner("Ana", "300.00")
    bogdan = partner("Bogdan", "-300.00")

    suggest_settlements([ana, bogdan])

    assert ana.net_position == Decimal("300.00")
    assert bogdan.net_position == Decimal("-300.00")
