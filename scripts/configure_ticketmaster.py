"""Validate a Ticketmaster API key and store it privately in Secrets Manager."""
import getpass
import json
import urllib.error
import urllib.parse
import urllib.request

import boto3
from botocore.exceptions import ClientError


def main():
    key = getpass.getpass('Pega tu Consumer Key de Ticketmaster y pulsa Enter: ').strip()
    if not key:
        raise SystemExit('No se ha introducido ninguna clave.')
    query = urllib.parse.urlencode({'apikey': key, 'countryCode': 'ES', 'size': 1})
    try:
        with urllib.request.urlopen('https://app.ticketmaster.com/discovery/v2/events.json?' + query,
                                    timeout=15) as result:
            json.load(result)
    except urllib.error.HTTPError as error:
        raise SystemExit(f'Ticketmaster ha rechazado la consulta (HTTP {error.code}). La clave no se ha guardado.') from None
    except (OSError, ValueError):
        raise SystemExit('No se ha podido comprobar Ticketmaster. La clave no se ha guardado.') from None
    client = boto3.client('secretsmanager', region_name='us-east-1')
    body = json.dumps({'api_key': key})
    try:
        client.put_secret_value(SecretId='sfw-dev/ticketmaster', SecretString=body)
    except ClientError as error:
        if error.response['Error']['Code'] != 'ResourceNotFoundException':
            raise
        client.create_secret(Name='sfw-dev/ticketmaster', SecretString=body)
    print('Ticketmaster conectado. La clave está guardada en AWS Secrets Manager.')


if __name__ == '__main__':
    main()
