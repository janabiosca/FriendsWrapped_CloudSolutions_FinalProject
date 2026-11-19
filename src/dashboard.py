"""Private statistics behind API Gateway JWT authorization and group membership checks."""
from datetime import datetime, timedelta, timezone
import hashlib
import base64
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

import boto3
from botocore.exceptions import ClientError

from group_stats import weekly_from_store
import listening_stats
import store
import wrapped


def email_key(email):
    return 'EMAIL#' + hashlib.sha256(email.strip().casefold().encode()).hexdigest()


def email_membership(email):
    return boto3.resource('dynamodb').Table(os.environ['OAUTH_TABLE_NAME']).get_item(
        Key={'id': email_key(email)}, ConsistentRead=True).get('Item')


def signup(event, context):
    """Cognito verifies ownership of approved email addresses during sign-up."""
    email = event.get('request', {}).get('userAttributes', {}).get('email', '')
    if not email or not email_membership(email):
        raise ValueError('Esta cuenta no tiene una invitación al grupo.')
    return event


def response(body, status=200):
    return {'statusCode': status, 'headers': {
        'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store',
        'x-content-type-options': 'nosniff', 'referrer-policy': 'no-referrer',
    }, 'body': json.dumps(body, ensure_ascii=False)}


def member_from_request(event):
    claims = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
    if claims.get('token_use') != 'access' or not claims.get('sub'):
        return None
    authorization = event.get('headers', {}).get('authorization', '')
    if not authorization.startswith('Bearer '):
        return None
    request = urllib.request.Request(os.environ['COGNITO_DOMAIN'] + '/oauth2/userInfo',
                                     headers={'Authorization': authorization})
    with urllib.request.urlopen(request, timeout=5) as result:
        user = json.load(result)
    if (user.get('sub') != claims['sub'] or str(user.get('email_verified')).lower() != 'true'
            or not user.get('email')):
        return None
    membership = email_membership(user['email'])
    if not membership or membership.get('group_id') != os.environ['GROUP_ID']:
        return None
    item = boto3.resource('dynamodb').Table(os.environ['TABLE_NAME']).get_item(
        Key={'PK': 'GROUP#' + membership['group_id'], 'SK': 'MEMBER#' + membership['user_id']},
        ConsistentRead=True).get('Item')
    if item:
        return membership
    viewer = boto3.resource('dynamodb').Table(os.environ['TABLE_NAME']).get_item(
        Key={'PK': 'GROUP#' + membership['group_id'], 'SK': 'VIEWER#' + membership['user_id']},
        ConsistentRead=True).get('Item')
    return {**membership, 'display_name': viewer.get('display_name', membership['user_id'])} if viewer else None


def public_page():
    config = {'clientId': os.environ['COGNITO_CLIENT_ID'],
              'domain': os.environ['COGNITO_DOMAIN'], 'redirectUri': os.environ['DASHBOARD_URL']}
    body = (Path(__file__).parent / 'index.html').read_text().replace(
        'const hostedConfig = null;', 'const hostedConfig = ' + json.dumps(config) + ';')
    return {'statusCode': 200, 'headers': {
        'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store',
        'x-content-type-options': 'nosniff', 'referrer-policy': 'no-referrer',
        'content-security-policy': "default-src 'self'; script-src 'unsafe-inline'; "
            "style-src 'unsafe-inline'; connect-src 'self' " + os.environ['COGNITO_DOMAIN'] +
            "; frame-ancestors 'none'; base-uri 'none'",
    }, 'body': body}


def handler(event, context):
    path = event.get('rawPath', '/')
    if path == '/':
        return public_page()
    try:
        member = member_from_request(event)
        if not member:
            return response({'error': 'Acceso denegado. Verifica tu correo y tu invitación al grupo.'}, 403)
        now = datetime.now(ZoneInfo('Europe/Madrid'))
        if path == '/api/wrapped':
            monday = wrapped.previous_week(now)
            key = wrapped.keys(member['group_id'], monday)['pdf_key']
            report = wrapped.read_object(key)
            if report is None:
                return response({'error': 'El Wrapped de la última semana completa todavía no está disponible.'}, 404)
            return {'statusCode': 200, 'isBase64Encoded': True, 'headers': {
                'content-type': 'application/pdf', 'cache-control': 'no-store',
                'content-disposition': 'attachment; filename="friends-wrapped-' + monday.isoformat() + '.pdf"',
                'x-content-type-options': 'nosniff',
            }, 'body': base64.b64encode(report).decode('ascii')}
        if path == '/api/group-weekly':
            monday = now.date() - timedelta(days=now.weekday())
            return response(weekly_from_store(member['group_id'], monday, now))
        if path == '/api/stats':
            period = (event.get('queryStringParameters') or {}).get('period', 'all')
            if period not in ('all', 'today', '7d'):
                return response({'error': 'Periodo inválido.'}, 400)
            member_ids = store.group_members(member['group_id'])
            default_user = member['user_id'] if member['user_id'] in member_ids else next(iter(member_ids), None)
            selected_user = (event.get('queryStringParameters') or {}).get('user_id', default_user)
            if selected_user not in member_ids:
                return response({'error': 'Este perfil no pertenece a tu grupo.'}, 403)
            profiles = {user_id: store.get_profile(user_id) or {} for user_id in member_ids}
            start = '0000'
            if period != 'all':
                beginning = now.replace(hour=0, minute=0, second=0, microsecond=0)
                if period == '7d':
                    beginning -= timedelta(days=6)
                start = beginning.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
            end = now.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
            profile = profiles[selected_user]
            result = listening_stats.summarize(store.plays_between(selected_user, start, end))
            result.update(display_name=profile.get('display_name', selected_user),
                          last_sync_at=profile.get('last_sync_at'), last_sync_status=profile.get('last_sync_status'),
                          possible_gaps=int(profile.get('possible_gaps', 0)), period=period,
                          selected_user_id=selected_user, account_user_id=member['user_id'],
                          account_name=profiles.get(member['user_id'], {}).get('display_name',
                              member.get('display_name', member['user_id'])),
                          profiles=[{'user_id': user_id, 'name': profiles[user_id].get('display_name', user_id)}
                                    for user_id in member_ids])
            return response(result)
        return response({'error': 'Ruta desconocida.'}, 404)
    except urllib.error.HTTPError as error:
        if error.code in (400, 401, 403):
            return response({'error': 'La sesión ha caducado. Vuelve a iniciar sesión.'}, 401)
        return response({'error': 'El servicio de acceso no está disponible. Inténtalo de nuevo.'}, 503)
    except (ClientError, OSError, ValueError):
        print(json.dumps({'event': 'dashboard_request_failed'}))
        return response({'error': 'No se han podido consultar los datos. Inténtalo de nuevo.'}, 503)
