#!/usr/bin/env python3
"""Generate deterministic, synthetic data matching the final TBX CSV schema.

No Faker dependency is used, so this works in a clean Python installation.
The output is demonstrative only and must never be presented as TBX data.
"""

from __future__ import annotations

import argparse
import csv
import random
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

BANKS = [
    ("HDFC", "HDFC Bank"),
    ("ICICI", "ICICI Bank"),
    ("SBI", "State Bank of India"),
    ("AXIS", "Axis Bank"),
    ("KOTAK", "Kotak Mahindra Bank"),
    ("YES", "YES Bank"),
]
DESCRIPTIONS = [
    "Cloud infrastructure payment", "Payroll processing", "Software subscription",
    "Equipment purchase", "Travel settlement", "Customer payment", "Refund received",
    "Insurance premium", "Office services", "Interest credit",
]


def stable_uuid(namespace: str, number: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tbx-synthetic/{namespace}/{number}"))


def write_csv(path: Path, fields: list[str], rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def generate(output: Path, account_count: int, transaction_count: int, seed: int) -> None:
    if account_count < 1 or transaction_count < 1:
        raise ValueError("accounts and transactions must both be positive")
    output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    write_csv(output / "bank.csv", ["bank_code", "bank_name"],
              ({"bank_code": code, "bank_name": name} for code, name in BANKS))

    accounts = []
    for index in range(account_count):
        bank_code, _ = BANKS[index % len(BANKS)]
        accounts.append({
            "account_id": stable_uuid("account", index),
            "entity_id": stable_uuid("entity", index // 4),
            "account_number": f"5010{index:012d}",
            "program_id": 100 + index % 8,
            "available_balance": str(Decimal(rng.randrange(25_000_00, 25_000_000_00)) / 100),
            "bank_code": bank_code,
        })
    write_csv(output / "account.csv", list(accounts[0]), accounts)

    start = datetime(2025, 9, 1, 8, 0)
    transactions = []
    for index in range(transaction_count):
        account = accounts[rng.randrange(account_count)]
        posted = start + timedelta(minutes=rng.randrange(365 * 24 * 60))
        transaction_type = "debit" if rng.random() < 0.64 else "credit"
        amount = Decimal(rng.randrange(100_00, 500_000_00)) / 100
        transactions.append({
            "transaction_id": stable_uuid("transaction", index),
            "account_id": account["account_id"],
            "transaction_date": posted.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "transaction_type": transaction_type,
            "description": rng.choice(DESCRIPTIONS),
            "transaction_amount": str(amount),
            "transaction_reference_id": f"REF-SYN-{index + 1:010d}",
            "utr_number": "" if index % 11 == 0 else f"UTR-SYN-ENC-{index + 1:010d}",
        })
    transactions.sort(key=lambda row: row["transaction_date"])
    write_csv(output / "transaction.csv", list(transactions[0]), transactions)

    print(f"Generated {len(BANKS)} banks, {account_count:,} accounts and "
          f"{transaction_count:,} transactions in {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/generated"))
    parser.add_argument("--accounts", type=int, default=1_000)
    parser.add_argument("--transactions", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=20260905)
    args = parser.parse_args()
    generate(args.output, args.accounts, args.transactions, args.seed)


if __name__ == "__main__":
    main()
