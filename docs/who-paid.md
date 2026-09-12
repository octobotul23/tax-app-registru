# Who paid how much

The arithmetic behind the **Balance** page, in full. This is the part of the app
where a mistake costs real money, so it is worth reading once.

---

## The two kinds of spending

Every receipt is filed as one of two things, and you choose which at upload:

**Business money** — you paid with the company card, from the company account.
The business bought it, the business paid for it, the story ends. It shows up in
the dashboard totals and in the category breakdown, and it is counted for the
books. It creates **no debt between the two of you**.

**Own money** — you paid out of your own pocket for something the business
needed. The business now owes you that amount. This is what the balance is
about.

Filing a receipt under the wrong one is the single most consequential mistake
you can make in this app. Business money filed as personal money invents a debt
that does not exist.

---

## A worked example

Say you and your partner are equal partners (0.5 each), and over a month:

| | Own money spent |
|---|---|
| You | 1.000 lei |
| Partner | 400 lei |

Total personal funding: **1.400 lei**.

At an equal partnership, each of you should be carrying half of that — **700
lei** each. That is the *fair share*.

| | Paid | Fair share | Net |
|---|---|---|---|
| You | 1.000 | 700 | **+300** |
| Partner | 400 | 700 | **−300** |

A positive number means you have put in more than your share; the business — in
practice, your partner — owes you. A negative number means you are behind.

The page says: *Partner pays you 300 lei.* Once that transfer happens and you
record it under **Settlements**, both numbers become zero.

Note what fair share is **not**: it is not "half the receipts each" and it is
not per-item. It is your equity share of the total money the two of you put in
personally. Business spending never enters this table at all.

---

## The formula

```
net_position = personal_outlay
             − fair_share
             − settlements_received
             + settlements_paid

fair_share   = total_personal_outlay × (your equity share ÷ sum of all shares)
```

Settlements appear with opposite signs for a reason. Money you received was
repayment of what you were owed, so it reduces your claim. Money you paid out
settled a debt, so it restores yours.

**Equity shares are normalised.** They are meant to add up to 1, but nothing
stops someone typing 0.5 and 0.6. Rather than producing nonsense, the app
divides by whatever they actually sum to — so 0.5/0.6 is treated as 45%/55%, and
a single owner at 0.5 still comes out at 100%. If every share somehow ends up at
zero, it falls back to an even split.

---

## Suggested settlements

With two partners this is trivial — one of you pays the other, once. The
algorithm generalises anyway (largest debtor pays largest creditor, repeat), so
it still gives the minimum number of transfers if you ever add a third partner.

Residual imbalances under **0,01 lei** are ignored. That is rounding dust from
currency conversion, not a debt, and nobody should be making a bank transfer
over a ban.

---

## What is left out of the balance, and why

A receipt only counts once it has a total that can be expressed in lei. Three
things keep one out:

**It is still being scanned, or the scan failed.** No numbers yet.

**Its currency has no exchange rate.** A euro receipt with no EUR rate on or
before its date cannot be valued in lei. The app refuses to guess — it flags the
receipt and tells you which rate is missing. Counting it as zero would silently
understate what somebody is owed.

**It was deleted.** Soft-deleted rows are excluded, though they remain in the
database.

The balance page shows a count of excluded receipts at all times. If that number
is not zero, the balance below it is incomplete, and the page says so rather
than quietly presenting a wrong figure as a right one.

---

## Verified versus unverified

Receipts read by the model but not yet checked by a human are counted in the
balance, but tracked separately as **unverified**, and shown as such.

This is a deliberate middle path. Excluding them would make the balance useless
until you had reviewed everything. Counting them silently would let a model
misreading 1.200 as 200 sit in your books unnoticed. So they count, and the page
tells you how much of the total is still only a machine's opinion.

Opening a receipt and saving it — even with no changes — marks it confirmed.

---

## Periods

The balance accepts a date range. A receipt falls in the period by its **printed
date**, falling back to its upload date when the model could not read one.

Settlements are filtered by the same range, which matters: if you settle up in
April for March's spending, a report over March alone shows the debt as still
open. That is correct — it was open during March. Run the report over both
months to see it closed.

---

## Multiple currencies

Receipts are stored in the currency printed on them. The conversion to lei
happens once, at save time, and the rate used is **frozen onto that receipt**.

This is why a balance you print today still shows the same numbers a year from
now. If conversion happened at read time, every new rate you entered would
silently rewrite history, and the copy you filed would stop matching the app.

Rates are entered by hand in **Settings**, each with a date it takes effect
from. A rate applies from its date forward until a newer one supersedes it.
There is no automatic rate feed, on purpose: the rate that belongs in your books
is the one your bank actually charged, and no public rate table knows that
number.

A receipt filed before its currency had any rate is stranded: it has a total,
but no value in lei, so it stays out of the balance. Adding the rate afterwards
does not rescue it on its own. **Settings → Revalue** goes back over those
stranded receipts and values them, and tells you how many it recovered.

> The EUR and USD rates created on first install are **placeholders** — 5,00 and
> 4,60 — and they are wrong on purpose, so that a real number has to be entered
> before any foreign-currency receipt can be trusted.
