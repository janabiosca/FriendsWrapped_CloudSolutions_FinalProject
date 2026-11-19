"""Check verified-email membership and per-user data isolation behind the JWT gateway."""
import io
import json
import sys
from pathlib import Path

import boto3
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import dashboard
from test_spotify_connect import setup


def request(path='/api/stats'):
    return {'rawPath': path, 'headers': {'authorization': 'Bearer valid-access'},
            'requestContext': {'authorizer': {'jwt': {'claims': {'sub': 'anna-sub', 'token_use': 'access'}}}}}


def allow(email='anna@example.com', user_id='anna'):
    boto3.resource('dynamodb').Table('oauth-test').put_item(
        Item={'id': dashboard.email_key(email), 'user_id': user_id, 'group_id': 'friends'})


def userinfo(monkeypatch, verified=True, sub='anna-sub'):
    monkeypatch.setenv('COGNITO_DOMAIN', 'https://login.example.com')
    data = {'sub': sub, 'email': 'anna@example.com', 'email_verified': str(verified).lower()}
    monkeypatch.setattr(dashboard.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(json.dumps(data).encode()))


def test_api_without_verified_gateway_context_is_denied(setup):
    assert dashboard.handler({'rawPath': '/api/group-weekly'}, None)['statusCode'] == 403


def test_signup_only_accepts_approved_email(setup):
    event = {'request': {'userAttributes': {'email': 'Anna@Example.com'}}}
    with pytest.raises(ValueError):
        dashboard.signup(event, None)
    allow()
    assert dashboard.signup(event, None) == event


def test_unverified_email_cannot_read_statistics(setup, monkeypatch):
    allow()
    userinfo(monkeypatch, verified=False)
    dashboard.store.add_member('friends', 'anna', 'Anna')
    assert dashboard.handler(request(), None)['statusCode'] == 403


def test_verified_email_needs_active_group_membership(setup, monkeypatch):
    allow()
    userinfo(monkeypatch)
    assert dashboard.handler(request(), None)['statusCode'] == 403


def test_identity_must_match_gateway_subject(setup, monkeypatch):
    allow()
    userinfo(monkeypatch, sub='another-user')
    dashboard.store.add_member('friends', 'anna', 'Anna')
    assert dashboard.handler(request(), None)['statusCode'] == 403


def test_personal_stats_reject_profile_outside_the_group(setup, monkeypatch):
    allow()
    userinfo(monkeypatch)
    dashboard.store.add_member('friends', 'anna', 'Anna')
    users = []
    def plays(user_id, start, end):
        users.append(user_id)
        return []
    monkeypatch.setattr(dashboard.store, 'plays_between', plays)
    event = request()
    event['queryStringParameters'] = {'user_id': 'helena'}
    result = dashboard.handler(event, None)
    assert result['statusCode'] == 403
    assert users == []


def test_removed_email_loses_access(setup, monkeypatch):
    userinfo(monkeypatch)
    dashboard.store.add_member('friends', 'anna', 'Anna')
    assert dashboard.handler(request(), None)['statusCode'] == 403


def test_viewer_without_spotify_can_open_member_profile(setup, monkeypatch):
    allow(user_id='pati')
    userinfo(monkeypatch)
    table = boto3.resource('dynamodb').Table('sfw-test')
    table.put_item(Item={'PK': 'GROUP#friends', 'SK': 'VIEWER#pati', 'user_id': 'pati', 'display_name': 'Pati'})
    dashboard.store.add_member('friends', 'anna', 'Anna')
    result = dashboard.handler(request(), None)
    assert result['statusCode'] == 200
    data = json.loads(result['body'])
    assert data['selected_user_id'] == 'anna'
    assert data['account_user_id'] == 'pati'
    assert data['account_name'] == 'Pati'
    assert dashboard.store.group_members('friends') == ['anna']


def test_member_can_open_another_profile_in_the_group(setup, monkeypatch):
    allow()
    userinfo(monkeypatch)
    dashboard.store.add_member('friends', 'anna', 'Anna')
    dashboard.store.add_member('friends', 'helena', 'Helena')
    event = request()
    event['queryStringParameters'] = {'user_id': 'helena'}
    result = dashboard.handler(event, None)
    assert result['statusCode'] == 200
    data = json.loads(result['body'])
    assert data['display_name'] == 'Helena'
    assert data['selected_user_id'] == 'helena'
    assert data['account_user_id'] == 'anna'
    assert data['account_name'] == 'Anna'


def test_removed_viewer_cannot_read_group(setup, monkeypatch):
    allow(user_id='pati')
    userinfo(monkeypatch)
    dashboard.store.add_member('friends', 'anna', 'Anna')
    assert dashboard.handler(request('/api/group-weekly'), None)['statusCode'] == 403
