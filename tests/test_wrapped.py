"""Verify closed-week selection, immutable retries, escaping and report access."""
from datetime import date, datetime, timezone
import io
import base64
from pypdf import PdfReader
import json

import boto3
import pytest

import dashboard
import wrapped
from test_dashboard import allow, request, userinfo
from test_spotify_connect import setup


@pytest.fixture
def report_store(setup, monkeypatch):
    monkeypatch.setenv('RAW_BUCKET', 'sfw-wrapped-test')
    boto3.client('s3').create_bucket(Bucket='sfw-wrapped-test')
    stats = {
        'week_start': '2026-11-09', 'generated_at': '2026-11-19T10:00:00+00:00',
        'ranking': [{'rank': 1, 'name': '<script>bad()</script>', 'total_plays': 1, 'estimated_minutes': 3.0}],
        'group': {'total_plays': 1, 'unique_tracks': 1, 'estimated_minutes': 3.0,
                  'top_tracks': [{'name': 'A & B', 'artists': ['Artist'], 'plays': 1}],
                  'top_artists': [{'name': 'Artist', 'plays': 1}]},
    }
    monkeypatch.setattr(wrapped, 'weekly_from_store', lambda *args: stats)
    return stats


def prepare():
    return wrapped.handler({'action': 'prepare', 'reference_time': '2026-11-19T10:00:00Z', 'request': {}}, None)


def test_last_complete_week_obeys_madrid_midnight():
    # Sunday 23:30 UTC is already Monday in Madrid in November.
    reference = datetime(2026, 11, 15, 23, 30, tzinfo=timezone.utc)
    assert wrapped.previous_week(reference) == date(2026, 11, 9)


def test_current_week_is_rejected(report_store):
    with pytest.raises(ValueError):
        wrapped.prepare({'week_start': '2026-11-16'}, datetime(2026, 11, 19, tzinfo=timezone.utc))


def test_retry_preserves_snapshot_and_report(report_store):
    first = prepare()
    result = wrapped.archive(first)
    original = wrapped.read_object(first['report_key'])
    assert result['status'] == 'ready'
    report_store['group']['total_plays'] = 999
    second = prepare()
    wrapped.archive(second)
    assert wrapped.read_object(first['report_key']) == original
    assert json.loads(wrapped.read_object(first['snapshot_key']))['group']['total_plays'] == 1
    objects = boto3.client('s3').list_objects_v2(Bucket='sfw-wrapped-test')['Contents']
    assert len(objects) == 3


def test_names_are_escaped_in_standalone_html(report_store):
    result = wrapped.archive(prepare())
    report = wrapped.read_object(result['report_key']).decode()
    assert '<script>bad()' not in report
    assert '&lt;script&gt;' in report
    assert 'A &amp; B' in report


def test_archive_rejects_another_groups_keys(report_store):
    manifest = prepare()
    manifest['report_key'] = 'wrapped/group=another/secret.html'
    with pytest.raises(ValueError):
        wrapped.archive(manifest)


def test_wrapped_download_requires_membership(report_store):
    assert dashboard.handler({'rawPath': '/api/wrapped'}, None)['statusCode'] == 403


def test_member_downloads_only_own_groups_report(report_store, monkeypatch):
    wrapped.archive(prepare())
    allow()
    userinfo(monkeypatch)
    dashboard.store.add_member('friends', 'anna', 'Anna')
    monkeypatch.setattr(wrapped, 'previous_week', lambda reference=None: date(2026, 11, 9))
    event = request('/api/wrapped')
    event['queryStringParameters'] = {'group_id': 'another'}
    result = dashboard.handler(event, None)
    assert result['statusCode'] == 200
    assert result['headers']['content-type'] == 'application/pdf'
    assert result['isBase64Encoded']
    reader = PdfReader(io.BytesIO(base64.b64decode(result['body'])))
    assert 'Friends Wrapped' in (reader.metadata.title or '')
    assert 'Así sonó vuestra semana.' in ''.join(page.extract_text() for page in reader.pages)


def test_missing_report_gives_a_clear_response(report_store, monkeypatch):
    allow()
    userinfo(monkeypatch)
    dashboard.store.add_member('friends', 'anna', 'Anna')
    result = dashboard.handler(request('/api/wrapped'), None)
    assert result['statusCode'] == 404


def test_legacy_manifest_gains_pdf_without_replacing_snapshot(report_store):
    manifest = prepare()
    legacy = {key: value for key, value in manifest.items() if key != 'pdf_key'}
    original = wrapped.read_object(manifest['snapshot_key'])
    result = wrapped.archive(legacy)
    assert wrapped.read_object(result['pdf_key']).startswith(b'%PDF-')
    assert wrapped.read_object(manifest['snapshot_key']) == original
