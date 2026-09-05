#!/usr/bin/env bash
# Prove the SQL this app generates actually runs on MySQL.
#
# Usage:  scripts/verify_mysql.sh <db> [user] [password]
# The app's own queries are replayed against MySQL with ANSI_QUOTES enabled,
# which is the one session setting the double-quoted identifiers require.
set -euo pipefail
DB="${1:-tbx}"; USER="${2:-fifi}"; PASS="${3:-fifi}"
MYSQL=(mysql -u "$USER" "-p$PASS" "$DB" -N -B)

run() { printf '  %-46s ' "$1"; shift
        if out=$("${MYSQL[@]}" -e "SET SESSION sql_mode=CONCAT(@@sql_mode,',ANSI_QUOTES'); $1" 2>&1)
        then echo "OK  ${out//$'\n'/ }"; else echo "FAIL  ${out:0:90}"; FAILED=1; fi; }

FAILED=0
echo "Verifying generated-SQL constructs against MySQL ($DB)"
run 'identifier quoting'      'SELECT COUNT(*) FROM "transaction"'
run 'CAST AS CHAR'            'SELECT CAST(transaction_amount AS CHAR) FROM "transaction" LIMIT 1'
run 'masked account (RIGHT)'  'SELECT RIGHT(CAST(account_number AS CHAR), 4) FROM "account" LIMIT 1'
run 'case-insensitive equals' 'SELECT COUNT(*) FROM "bank" WHERE LOWER(CAST(bank_code AS CHAR)) = LOWER("HDFC")'
run 'portable NULL ordering'  'SELECT bank_code, SUM(1) AS result FROM "account" GROUP BY bank_code ORDER BY (result IS NULL), result DESC'
run 'the three-table join'    'SELECT COUNT(*) FROM "transaction" t LEFT JOIN "account" a ON a.account_id=t.account_id LEFT JOIN "bank" b ON b.bank_code=a.bank_code'
run 'ledger direction filter' 'SELECT SUM(transaction_amount) FROM "transaction" WHERE transaction_type = "debit"'
echo
[ "$FAILED" = 0 ] && echo "All constructs run on MySQL." || { echo "Some constructs failed - fix before switching."; exit 1; }
