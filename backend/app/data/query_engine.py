import csv
import io
from dataclasses import dataclass
from typing import Any
from uuid import uuid4
from app.data.catalog import DatasetCatalog
from app.data.display import PREFERRED_DISPLAY_COLUMNS
from app.data.projections import from_clause
from app.schemas import Evidence, QueryPlan


class ReconciliationError(RuntimeError):
    """The breakdown does not add up to the headline figure."""


@dataclass
class QueryResult:
    evidence: Evidence
    csv_content: str
    total_matching: int


class GroundedQueryEngine:
    OPERATIONS = {
        "count": "COUNT(*)",
        "sum": "SUM({measure})",
        "average": "AVG({measure})",
        "minimum": "MIN({measure})",
        "maximum": "MAX({measure})",
    }
    FILTERS = {"eq": "=", "neq": "<>", "gte": ">=", "lte": "<=", "gt": ">", "lt": "<"}

    def __init__(self, catalog: DatasetCatalog):
        self.catalog = catalog
        # When the database is not ours - TBX grants SELECT only - the safe
        # surface cannot be a view there, so it is inlined into every query.
        self.inline_sources = bool(getattr(catalog, "inline_sources", False))
        self.source_prefix = getattr(catalog, "source_prefix", "")

    # operations where the parts genuinely compose back into the whole.
    # An average of averages is not the overall average, so it is excluded.
    RECONCILABLE = {"sum": "SUM", "count": "COUNT", "minimum": "MIN", "maximum": "MAX"}

    def _reconcile(self, connection, plan, where, parameters, rows, quoted_groups, returned, total_matching):
        """Check the supporting numbers add up to the headline.

        This is what makes "verifiable" a property rather than a claim: a
        breakdown that is scoped differently from the headline produces a table
        that quietly disagrees with the number above it, and nobody notices
        until an auditor does.
        """
        op = plan.operation
        if op == "list":
            if returned == total_matching:
                return True, f"All {total_matching} matching rows are shown."
            return None, f"Showing {returned} of {total_matching} matching rows."

        if op not in self.RECONCILABLE:
            return None, f"No reconciliation check applies to {op}."

        if not (quoted_groups and rows):
            return None, "Single aggregate; no breakdown to reconcile against."

        # the same aggregate without the grouping must equal the parts combined
        agg = self.RECONCILABLE[op]
        expression = "COUNT(*)" if op == "count" else f'{agg}("{plan.measure}")'
        try:
            source = from_clause(plan.dataset, self.source_prefix, self.inline_sources)
            whole = connection.execute(
                f"SELECT {expression} FROM {source}{where}", parameters
            ).fetchone()[0]
        except Exception as exc:  # noqa: BLE001 - a failed check must not fail the answer
            return None, f"Reconciliation check could not run ({exc})."

        values = [row.get("result") for row in rows if row.get("result") is not None]
        if not values:
            return None, "Breakdown contained no values to reconcile."

        parts = sum(values) if op in {"sum", "count"} else (min(values) if op == "minimum" else max(values))
        whole = float(whole or 0)
        parts = float(parts)
        delta = abs(parts - whole)
        if delta < 0.01:
            return True, f"The {len(values)} rows below sum to {parts:,.2f}, matching the headline."
        return False, (
            f"The breakdown totals {parts:,.2f} but the headline is {whole:,.2f} "
            f"(off by {delta:,.2f}). The table and the number disagree."
        )

    def execute(self, plan: QueryPlan) -> QueryResult:
        available = self.catalog.describe()
        if plan.dataset not in available:
            raise ValueError(f"Dataset '{plan.dataset}' is not available")
        columns = {column["name"] for column in available[plan.dataset]}
        if hasattr(self.catalog, "validate_plan"):
            self.catalog.validate_plan(plan)
        requested = set(plan.group_by) | set(plan.select) | {item.column for item in plan.filters}
        if plan.measure:
            requested.add(plan.measure)
        unknown = requested - columns
        if unknown:
            raise ValueError(f"Unknown columns: {', '.join(sorted(unknown))}")
        if plan.operation not in {"list", "count"} and not plan.measure:
            raise ValueError(f"Operation '{plan.operation}' requires a measure")
        if plan.operation == "list" and not plan.select:
            raise ValueError("List queries require an explicit column projection")

        quoted_groups = [f'"{column}"' for column in plan.group_by]
        if plan.operation == "list":
            # a wide joined view is unreadable as a full row dump; show the
            # columns a person reads, and keep the rest in the CSV export
            preferred = [c for c in PREFERRED_DISPLAY_COLUMNS.get(plan.dataset, []) if c in columns]
            select = ", ".join(f'"{c}"' for c in preferred) if preferred else "*"
        else:
            expression = self.OPERATIONS[plan.operation]
            if "{measure}" in expression:
                expression = expression.format(measure=f'"{plan.measure}"')
            select = ", ".join(quoted_groups + [f"{expression} AS result"])

        clauses: list[str] = []
        parameters: list[Any] = []
        for item in plan.filters:
            if item.operator == "contains":
                clauses.append(f'LOWER(CAST("{item.column}" AS CHAR)) LIKE LOWER(?)')
                parameters.append(f"%{item.value}%")
            else:
                clauses.append(f'"{item.column}" {self.FILTERS[item.operator]} ?')
                parameters.append(item.value)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        source = from_clause(plan.dataset, self.source_prefix, self.inline_sources)
        sql = f"SELECT {select} FROM {source}{where}"
        if quoted_groups and plan.operation != "list":
            sql += " GROUP BY " + ", ".join(quoted_groups)
            # the narration calls out the largest groups, so the rows must be
            # ordered - otherwise "Largest:" names whichever rows came back first
            # NULLS LAST is not MySQL syntax; this ordering is portable and
            # means the same thing on both engines
            sql += " ORDER BY (result IS NULL), result DESC"

        # A LIMIT belongs on a row listing, never on an aggregate: truncating
        # groups silently changes the answer. Aggregates are already one row per
        # group, so they are returned whole.
        query_parameters = list(parameters)
        max_rows = int(getattr(self.catalog, "max_result_rows", 200))
        if plan.operation == "list":
            # MySQL can reject parameter markers in LIMIT when the same query is
            # wrapped by EXPLAIN. Both values are validated bounded integers, so
            # rendering this one literal is safe; all user filter values remain
            # parameterized.
            sql += f" LIMIT {min(plan.limit, max_rows)}"
        elif quoted_groups:
            # Fetch one sentinel group so an oversized breakdown is refused,
            # never silently truncated and presented as a reconciled whole.
            sql += f" LIMIT {max_rows + 1}"

        connection = self.catalog.connection()

        # The true number of rows the filters match, independent of any limit.
        # Reporting len(rows) here is how "which transactions are unreconciled?"
        # silently answers 50 when the real answer is 500.
        total_matching = connection.execute(
            f"SELECT COUNT(*) FROM {source}{where}", parameters
        ).fetchone()[0]

        cursor = connection.execute(sql, query_parameters)
        names = [item[0] for item in cursor.description]
        rows = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

        # run the reconciliation check while the connection is still open
        # An empty result caused by the direction filter is true but unhelpful:
        # "no debits at Kotak" is better said as "there are transactions there,
        # just no outgoing ones". One cheap count, only on the empty path.
        without_direction = None
        if total_matching == 0:
            others = [c for item, c in zip(plan.filters, clauses)
                      if item.column != "transaction_type"]
            other_params = [p for item, p in zip(plan.filters, parameters)
                            if item.column != "transaction_type"]
            if len(others) != len(clauses):
                relaxed = (" WHERE " + " AND ".join(others)) if others else ""
                try:
                    without_direction = connection.execute(
                        f"SELECT COUNT(*) FROM {source}{relaxed}", other_params
                    ).fetchone()[0]
                except Exception:  # noqa: BLE001
                    without_direction = None

        reconciles, reconcile_note = self._reconcile(
            connection, plan, where, parameters, rows, quoted_groups, len(rows), total_matching
        )
        connection.close()

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)
        calculation = f"{plan.operation} on {plan.dataset}; filters={len(plan.filters)}; grouped_by={plan.group_by or 'none'}"
        total_groups = len(rows) if (quoted_groups and plan.operation != "list") else None
        evidence = Evidence(
            dataset=plan.dataset,
            columns=names,
            rows=rows,
            total_rows=total_matching,
            returned_rows=len(rows),
            total_groups=total_groups,
            calculation=calculation,
            sql=sql,
            reconciles=reconciles,
            reconcile_note=reconcile_note,
            matches_ignoring_direction=without_direction,
            export_id=str(uuid4()),
        )
        return QueryResult(evidence=evidence, csv_content=output.getvalue(), total_matching=total_matching)
