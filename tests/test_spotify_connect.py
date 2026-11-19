"""Exercise invitation expiry, browser binding, replay and account isolation."""
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import boto3
from moto import mock_aws
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import spotify_connect as connect


@pytest.fixture
def setup(monkeypatch):
    for key, value in {
        'AWS_DEFAULT_REGION': 'us-east-1', 'AWS_ACCESS_KEY_ID': 'test',
        'AWS_SECRET_ACCESS_KEY': 'test', 'TABLE_NAME': 'sfw-test',
        'OAUTH_TABLE_NAME': 'oauth-test', 'SPOTIFY_CLIENT_ID': 'test-client',
        'CONNECT_BASE_URL': 'https://connect.example', 'GROUP_ID': 'friends',
        'SECRET_PREFIX': 'sfw/spotify/',
    }.items():
        monkeypatch.setenv(key, value)
    with mock_aws():
        resource = boto3.resource('dynamodb')
        resource.create_table(TableName='oauth-test', BillingMode='PAY_PER_REQUEST',
                              KeySchema=[{'AttributeName': 'id', 'KeyType': 'HASH'}],
                              AttributeDefinitions=[{'AttributeName': 'id', 'AttributeType': 'S'}])
        resource.create_table(TableName='sfw-test', BillingMode='PAY_PER_REQUEST',
                              KeySchema=[{'AttributeName': 'PK', 'KeyType': 'HASH'},
                                         {'AttributeName': 'SK', 'KeyType': 'RANGE'}],
                              AttributeDefinitions=[{'AttributeName': 'PK', 'AttributeType': 'S'},
                                                    {'AttributeName': 'SK', 'AttributeType': 'S'}])
        invite('anna', 'anna-link')
        yield


def invite(user, token):
    connect.table().put_item(Item={'id': 'INVITE#' + connect.digest(token), 'user_id': user,
                                   'display_name': user.title(), 'expires_at': int(time.time()) + 600})


def event(path, **params):
    return {'rawPath': path, 'queryStringParameters': params}


def authorize(token='anna-link'):
    response = connect.handler(event('/start', invite=token), None)
    state = parse_qs(urlsplit(response['headers']['location']).query)['state'][0]
    callback = event('/callback', state=state, code='private-code')
    callback['cookies'] = [response['cookies'][0].split(';')[0]]
    return callback


def fake_spotify(monkeypatch, account='account-anna'):
    def request(req):
        if req.full_url == connect.spotify.TOKEN_URL:
            return {'access_token': 'private-access', 'refresh_token': 'private-refresh'}
        return {'account_id': account, 'id': 'legacy-id'}
    monkeypatch.setattr(connect.spotify, '_call', request)


def test_expired_invite_is_rejected(setup):
    item = connect.invitation('anna-link')
    item['expires_at'] = 1
    connect.table().put_item(Item=item)
    assert connect.handler(event('/start', invite='anna-link'), None)['statusCode'] == 400


def test_callback_requires_same_browser(setup):
    callback = authorize()
    callback['cookies'] = ['sfw_connect=other-browser']
    assert connect.handler(callback, None)['statusCode'] == 400


def test_success_and_replay(setup, monkeypatch):
    fake_spotify(monkeypatch)
    callback = authorize()
    response = connect.handler(callback, None)
    assert response['statusCode'] == 200
    assert connect.store.group_members('friends') == ['anna']
    assert connect.store.get_profile('anna')['spotify_account_id'] == 'account-anna'
    assert connect.store.get_token('anna')['refresh_token'] == 'private-refresh'
    assert 'private-refresh' not in response['body']
    assert connect.handler(callback, None)['statusCode'] == 400
    assert connect.handler(event('/start', invite='anna-link'), None)['statusCode'] == 400


def test_duplicate_account_cannot_be_another_member(setup, monkeypatch):
    fake_spotify(monkeypatch)
    assert connect.handler(authorize(), None)['statusCode'] == 200
    invite('helena', 'helena-link')
    assert connect.handler(authorize('helena-link'), None)['statusCode'] == 409
    assert connect.store.get_profile('helena') is None


def test_existing_member_cannot_be_overwritten(setup, monkeypatch):
    fake_spotify(monkeypatch)
    connect.store.add_member('friends', 'anna', 'Anna')
    assert connect.handler(authorize(), None)['statusCode'] == 409


def test_storage_failure_can_be_retried_with_new_invitation(setup, monkeypatch):
    fake_spotify(monkeypatch)
    original = connect.store.save_token
    def fail(*args):
        from botocore.exceptions import ClientError
        raise ClientError({'Error': {'Code': 'AccessDeniedException'}}, 'PutSecretValue')
    monkeypatch.setattr(connect.store, 'save_token', fail)
    assert connect.handler(authorize(), None)['statusCode'] == 503
    assert connect.store.group_members('friends') == []
    monkeypatch.setattr(connect.store, 'save_token', original)
    invite('anna', 'replacement-link')
    assert connect.handler(authorize('replacement-link'), None)['statusCode'] == 200


def test_denial_keeps_invite_available(setup):
    callback = authorize()
    callback['queryStringParameters'] = {'state': callback['queryStringParameters']['state'],
                                          'error': 'access_denied'}
    assert connect.handler(callback, None)['statusCode'] == 400
    assert connect.handler(event('/start', invite='anna-link'), None)['statusCode'] == 302
