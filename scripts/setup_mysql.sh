#!/usr/bin/env bash
# One-shot local MySQL setup for verifying FiFi's generated SQL.
# Run with sudo (root uses socket auth on Ubuntu):
#     sudo scripts/setup_mysql.sh
#
# Creates database `tbx`, user `fifi`/`fifi`, and loads the three TBX tables
# from the DDL extracted out of the schema document.
set -euo pipefail
DB=tbx; USER=fifi; PASS=fifi
HERE="$(cd "$(dirname "$0")" && pwd)"

mysql <<SQL
CREATE DATABASE IF NOT EXISTS \`$DB\` CHARACTER SET utf8mb4;
CREATE USER IF NOT EXISTS '$USER'@'localhost' IDENTIFIED BY '$PASS';
GRANT ALL PRIVILEGES ON \`$DB\`.* TO '$USER'@'localhost';
FLUSH PRIVILEGES;
SQL

mysql "$DB" < "$HERE/tbx_schema.sql"

echo "Loaded:"
mysql "$DB" -N -B -e "SELECT 'bank', COUNT(*) FROM bank
                UNION SELECT 'account', COUNT(*) FROM account
                UNION SELECT 'transaction', COUNT(*) FROM \`transaction\`;" \
  | while read -r t n; do printf '  %-12s %s rows\n' "$t" "$n"; done
echo
echo "Now run:  scripts/verify_mysql.sh tbx fifi fifi"
