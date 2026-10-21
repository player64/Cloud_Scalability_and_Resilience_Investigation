#!/usr/bin/python3
"""Installed on Coupon EC2. Run only explicitly; never initialises at startup."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

BASE = Path('/opt/ca1')


def secret(config, parameter):
    result = subprocess.run(
        ['aws', 'ssm', 'get-parameter', '--region', config['region'],
         '--name', parameter, '--with-decryption', '--output', 'json'],
        capture_output=True, check=True, timeout=45,
    )
    return json.loads(result.stdout)['Parameter']['Value']


def quoted(value):
    # MySQL option-file quoting (runtime EnvironmentFile uses env_quote).
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace(
        '\n', '\\n').replace('\r', '\\r').replace('\t', '\\t') + '"'


def mysql(config, user, password, sql):
    # /run is tmpfs. Neither passwords nor secret SQL appear in argv or logs.
    with tempfile.TemporaryDirectory(prefix='ca1-db-', dir='/run') as directory:
        options = Path(directory) / 'client.cnf'
        options.write_text('[client]\nuser=' + quoted(user) + '\npassword=' +
                           quoted(password) + '\n', encoding='utf-8')
        options.chmod(0o600)
        result = subprocess.run(
            ['mysql', '--defaults-extra-file=' + str(options),
             '--host=' + config['host'], '--port=' + str(config['port']),
             '--database=' + config['database'], '--protocol=TCP',
             '--ssl', '--ssl-verify-server-cert',
             '--ssl-ca=/opt/ca1/rds-ca.pem', '--connect-timeout=10',
             '--default-character-set=utf8mb4', '--batch', '--skip-column-names'],
            input=sql, text=True, capture_output=True, timeout=120,
        )
        if result.returncode:
            # MySQL errors can include the failing SQL containing a secret.
            raise RuntimeError('Database command failed; inspect database state before retrying.')
        return result.stdout


def main():
    os.umask(0o077)
    if os.geteuid() != 0 or len(sys.argv) != 2:
        raise RuntimeError('Use sudo coupon-operator.py env|init|verify')
    mode = sys.argv[1]
    if mode not in ('env', 'init', 'verify'):
        raise RuntimeError('Expected env, init or verify.')
    config = json.loads((BASE / 'config.json').read_text())
    if mode == 'env':
        password = secret(config, config['app_parameter'])
        # EnvironmentFile double quotes allow literal newlines; escape only
        # backslashes and double quotes, with no shell expansion.
        def env_quote(value):
            return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
        values = {
            'DB_URL': 'jdbc:mysql://{}:{}/{}'.format(
                config['host'], config['port'], config['database']),
            'DB_USERNAME': 'ca1_app', 'DB_PASSWORD': password,
            'SPRING_JPA_HIBERNATE_DDL_AUTO': 'none', 'SERVER_PORT': '9091',
            'LOGGING_FILE_NAME': '/var/log/ca1/coupon.log',
        }
        directory = Path('/run/ca1-coupon')
        directory.mkdir(mode=0o700, exist_ok=True)
        target = directory / 'runtime.env'
        target.write_text(''.join(k + '=' + env_quote(v) + '\n' for k, v in values.items()))
        target.chmod(0o600)
        return

    app_password = secret(config, config['app_parameter'])
    if mode == 'init':
        admin_password = secret(config, config['admin_parameter'])
        def admin(sql):
            return mysql(config, config['admin_user'], admin_password, sql)
        tables = admin("SELECT COUNT(*) FROM information_schema.tables "
                       "WHERE table_schema='servicedb';")
        users = admin("SELECT COUNT(*) FROM mysql.user WHERE User='ca1_app';")
        if tables.strip() != '0' or users.strip() != '0':
            raise RuntimeError('Database is not empty or ca1_app exists. Stop and inspect; do not reseed.')
        script = BASE / 'initialise.sql'
        # Hex encoding avoids interpolation of the password into SQL syntax.
        prefix = 'SET @app_password = CONVERT(0x' + app_password.encode().hex() + ' USING utf8mb4);\n'
        admin(prefix + script.read_text())
        print('Initialisation completed. SQL SHA-256:', hashlib.sha256(script.read_bytes()).hexdigest())
        print('Run verify and inspect schema/grants before enabling Coupon.')
    else:
        def app(sql):
            return mysql(config, 'ca1_app', app_password, sql)
        coupons = app('SELECT id,code,discount,exp_date FROM coupon ORDER BY id;')
        products = app('SELECT id,name,description,price,coupon_code FROM product ORDER BY id;')
        if coupons != '1\tSAVE10\t10.00\t2030-12-31\n' or products != (
            '1\tKeyboard\tWired keyboard\t90.00\tSAVE10\n'
            '2\tMouse\tOptical mouse\t40.00\tSAVE10\n'
        ):
            raise RuntimeError('Fixture mismatch. Stop and inspect database state.')
        print(coupons + products, end='')
        print(app('SHOW CREATE TABLE coupon; SHOW CREATE TABLE product; SHOW GRANTS;'))
        print(app("SELECT TABLE_NAME,AUTO_INCREMENT FROM information_schema.tables "
                  "WHERE table_schema='servicedb' ORDER BY TABLE_NAME;"))
        print('Fixtures match. Inspect schema, next IDs (coupon 2/product 3), and DML-only grants above.')


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except Exception:
        # Do not print exception objects: subprocess errors may hold secrets.
        print('Coupon operator failed. Check mode, SSM/network access and database state; '
              'no credentials or SQL errors are printed.', file=sys.stderr)
        sys.exit(1)
