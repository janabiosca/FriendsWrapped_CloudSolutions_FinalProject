"""Registration supports teacher observers while preserving existing member defaults."""
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import allow_dashboard_member


def test_teacher_is_registered_only_as_an_observer(monkeypatch):
    oauth, group = Mock(), Mock()
    resource = Mock()
    resource.Table.side_effect = lambda name: oauth if name == 'sfw-dev-connect' else group
    monkeypatch.setattr(allow_dashboard_member.boto3, 'resource', lambda *a, **k: resource)
    monkeypatch.setattr(sys, 'argv', ['register', '--user-id', 'prof-test', '--email', 'teacher@example.com',
                                    '--viewer', '--name', 'Teacher'])
    allow_dashboard_member.main()
    assert oauth.put_item.call_args.kwargs['Item']['user_id'] == 'prof-test'
    assert group.put_item.call_args.kwargs['Item'] == {
        'PK': 'GROUP#friends', 'SK': 'VIEWER#prof-test', 'user_id': 'prof-test', 'display_name': 'Teacher'}


def test_new_user_requires_observer_flag(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['register', '--user-id', 'prof-test', '--email', 'teacher@example.com'])
    with pytest.raises(SystemExit) as error:
        allow_dashboard_member.main()
    assert error.value.code == 2


def test_existing_observer_keeps_default_name(monkeypatch):
    resource = Mock()
    monkeypatch.setattr(allow_dashboard_member.boto3, 'resource', lambda *a, **k: resource)
    monkeypatch.setattr(sys, 'argv', ['register', '--user-id', 'pati', '--email', 'pati@example.com', '--viewer'])
    allow_dashboard_member.main()
    assert resource.Table.return_value.put_item.call_args.kwargs['Item']['display_name'] == 'Pati'
