#!/usr/bin/python3
"""Product pre-start: retrieve app credentials and check existing dependencies only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request


def env_quote(value):
    # systemd EnvironmentFile double quotes: no shell expansion.
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def mysql_quote(value):
    return env_quote(value).replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')


def main():
    os.umask(0o077)
    if os.geteuid() != 0:
        raise RuntimeError('Product pre-start requires root.')
    config = json.loads(Path('/opt/ca1/product-config.json').read_text())
    # The enclosing timeout also bounds SSM retries and all dependency checks.
    os.environ.update(AWS_RETRY_MODE='standard', AWS_MAX_ATTEMPTS='3', AWS_PAGER='')
    result = subprocess.run(
        ['aws', 'ssm', 'get-parameter', '--region', config['region'],
         '--name', config['app_parameter'], '--with-decryption', '--output', 'json'],
        capture_output=True, check=True, timeout=45,
    )
    password = json.loads(result.stdout)['Parameter']['Value']
    deadline = time.monotonic() + 125
    with tempfile.TemporaryDirectory(prefix='ca1-product-db-', dir='/run') as directory:
        options = Path(directory) / 'client.cnf'
        options.write_text('[client]\nuser=ca1_app\npassword=' + mysql_quote(password) + '\n')
        options.chmod(0o600)
        while True:
            try:
                subprocess.run(
                    ['mysql', '--defaults-extra-file=' + str(options),
                     '--host=' + config['host'], '--port=' + str(config['port']),
                     '--database=' + config['database'], '--protocol=TCP',
                     '--ssl', '--ssl-verify-server-cert', '--ssl-ca=/opt/ca1/rds-ca.pem',
                     '--connect-timeout=5', '--batch', '--skip-column-names'],
                    input='SELECT 1;', text=True, capture_output=True, check=True, timeout=10,
                )
                with urllib.request.urlopen(
                    config['coupon_url'] + '/couponapi/coupons/SAVE10', timeout=5,
                ) as response:
                    coupon = json.load(response)
                    if coupon.get('code') != 'SAVE10' or float(coupon.get('discount')) != 10:
                        raise ValueError('Known Coupon response mismatch.')
                break
            except Exception:
                # Suppress subprocess/HTTP bodies: failures must never expose secrets.
                if time.monotonic() + 20 >= deadline:
                    raise RuntimeError('Product dependency checks timed out.') from None
                print('Product waiting for database and known Coupon request.', file=sys.stderr)
                time.sleep(5)

    values = {
        'DB_URL': 'jdbc:mysql://{}:{}/{}'.format(
            config['host'], config['port'], config['database']),
        'DB_USERNAME': 'ca1_app', 'DB_PASSWORD': password,
        'CUPON_APP_URL': config['coupon_url'],
        'SPRING_JPA_HIBERNATE_DDL_AUTO': 'none',
        'SERVER_PORT': '9090',
        'MANAGEMENT_ENDPOINT_HEALTH_PROBES_ENABLED': 'true',
        'MANAGEMENT_ENDPOINT_HEALTH_GROUP_READINESS_INCLUDE': 'readinessState,db',
        'LOGGING_FILE_NAME': '/var/log/ca1/product.log',
    }
    directory = Path('/run/ca1-product')
    directory.mkdir(mode=0o700, exist_ok=True)
    target = directory / 'runtime.env'
    target.write_text(''.join(k + '=' + env_quote(v) + '\n' for k, v in values.items()))
    target.chmod(0o600)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Product pre-start failed; check SSM, database and Coupon connectivity. '
              'No credentials or response bodies are printed.', file=sys.stderr)
        sys.exit(1)
