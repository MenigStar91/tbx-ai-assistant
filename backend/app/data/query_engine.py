import csv
import io
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.data.catalog import DatasetCatalog
from app.schemas import Evidence, QueryPlan


@dataclass
class QueryResult:
    evidence: Evidence
    csv_content: str


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

    def execute(self, plan: QueryPlan) -> QueryResult:
        available = self.catalog.describe()
        if plan.dataset not in available:
            raise ValueError(f"Dataset '{plan.dataset}' is not available")
        columns = {column["name"] for column in available[plan.dataset]}
        requested = set(plan.group_by) | {item.column for item in plan.filters}
        if plan.measure:
            requested.add(plan.measure)
        unknown = requested - columns
        if unknown:
            raise ValueError(f"Unknown columns: {', '.join(sorted(unknown))}")
        if plan.operation not in {"list", "count"} and not plan.measure:
            raise ValueError(f"Operation '{plan.operation}' requires a measure")

        quoted_groups = [f'"{column}"' for column in plan.group_by]
        if plan.operation == "list":
            select = "*"
        else:
            expression = self.OPERATIONS[plan.operation]
            if "{measure}" in expression:
                expression = expression.format(measure=f'"{plan.measure}"')
            select = ", ".join(quoted_groups + [f"{expression} AS result"])

        clauses: list[str] = []
        parameters: list[Any] = []
        for item in plan.filters:
            if item.operator == "contains":
                clauses.append(f'LOWER(CAST("{item.column}" AS VARCHAR)) LIKE LOWER(?)')
                parameters.append(f"%{item.value}%")
            else:
                clauses.append(f'"{item.column}" {self.FILTERS[item.operator]} ?')
                parameters.append(item.value)
        sql = f'SELECT {select} FROM "{plan.dataset}"'
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        if quoted_groups and plan.operation != "list":
            sql += " GROUP BY " + ", ".join(quoted_groups)
        sql += " LIMIT ?"
        parameters.append(plan.limit)

        connection = self.catalog.connection()
        cursor = connection.execute(sql, parameters)
        names = [item[0] for item in cursor.description]
        rows = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        connection.close()

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)
        calculation = f"{plan.operation} on {plan.dataset}; filters={len(plan.filters)}; grouped_by={plan.group_by or 'none'}"
        evidence = Evidence(
            dataset=plan.dataset,
            columns=names,
            rows=rows,
            total_rows=len(rows),
            calculation=calculation,
            export_id=str(uuid4()),
        )
        return QueryResult(evidence=evidence, csv_content=output.getvalue())

