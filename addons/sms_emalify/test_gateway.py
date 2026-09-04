# -*- coding: utf-8 -*-
"""Standalone check for the SMS gateway dispatcher. Run: python test_gateway.py

Loads models/sms_api.py with odoo stubbed out, so it needs no Odoo runtime.
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_sms_api():
    """Import models/sms_api.py against stub odoo modules."""
    odoo = types.ModuleType('odoo')
    odoo.api = types.SimpleNamespace(model_create_multi=lambda f: f)
    odoo.models = types.SimpleNamespace(Model=type('Model', (), {'_inherit': None}))
    odoo._ = lambda s: s
    exceptions = types.ModuleType('odoo.exceptions')
    exceptions.UserError = type('UserError', (Exception,), {})
    odoo.exceptions = exceptions
    sys.modules['odoo'] = odoo
    sys.modules['odoo.exceptions'] = exceptions

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'sms_api_under_test', os.path.join(HERE, 'models', 'sms_api.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sms_api = _load_sms_api()
SmsSms = sms_api.SmsSms


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.content = b'x'
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise sms_api.requests.exceptions.HTTPError('%s' % self.status)

    def json(self):
        return self._payload


def fake_gateway(payload, status=200):
    """Patch requests.post; return the list of captured calls."""
    calls = []

    def post(url, json=None, headers=None, timeout=None):
        calls.append({'url': url, 'json': json, 'headers': headers})
        return FakeResponse(payload, status)

    sms_api.requests.post = post
    return calls


def fake_record(params):
    """A stand-in for an sms.sms recordset exposing only .env config params."""
    getter = types.SimpleNamespace(get_param=lambda key, default='': params.get(key, default))
    rec = SmsSms()
    rec.env = {'ir.config_parameter': types.SimpleNamespace(sudo=lambda: getter)}
    return rec


VIDATECH = {
    'sms_emalify.provider': 'vidatech',
    'sms_emalify.vidatech_token': 'tok-123',
    'sms_emalify.vidatech_sender': 'SHAZZ',
}


def test_vidatech_request_shape():
    calls = fake_gateway([{'status': True, 'data': {'uniqueId': 'abc', 'phone': '254700000001'}}])
    rec = fake_record(VIDATECH)
    message_id, response = SmsSms._sms_gateway_send(rec, '254700000001', 'hello')

    call = calls[0]
    assert call['url'] == 'https://bulk.vidatech.co.ke/api/v1/send-sms', call['url']
    assert call['headers']['Authorization'] == 'Bearer tok-123', call['headers']
    assert call['json'] == [{'sender': 'SHAZZ', 'message': 'hello', 'phone': '254700000001'}], call['json']
    assert message_id == 'abc', message_id
    assert response[0]['status'] is True


def test_vidatech_failure_raises():
    fake_gateway([{'status': False, 'message': 'Insufficient balance'}])
    rec = fake_record(VIDATECH)
    try:
        SmsSms._sms_gateway_send(rec, '254700000001', 'hello')
    except Exception as e:
        assert 'Insufficient balance' in str(e), str(e)
    else:
        raise AssertionError('expected a failure for status=false')


def test_roamtech_still_default():
    calls = fake_gateway({'responses': [{'messageid': 42}]})
    rec = fake_record({
        'sms_emalify.api_key': 'k', 'sms_emalify.partner_id': '221', 'sms_emalify.shortcode': 'SHAZZ',
    })  # no provider param set -> roamtech
    message_id, _response = SmsSms._sms_gateway_send(rec, '254700000001', 'hello')

    assert 'emalify.com' in calls[0]['url'], calls[0]['url']
    assert calls[0]['json']['partnerID'] == '221', calls[0]['json']
    assert message_id == '42', message_id


def test_missing_credentials_are_named_per_provider():
    assert SmsSms._sms_gateway_missing_credentials(fake_record(VIDATECH)) == ''
    assert SmsSms._sms_gateway_missing_credentials(fake_record({})) == 'API Key, Partner ID, Shortcode'
    partial = SmsSms._sms_gateway_missing_credentials(fake_record({'sms_emalify.provider': 'vidatech'}))
    assert partial == 'Vidatech Token, Vidatech Sender ID', partial


def test_phone_formatting():
    assert SmsSms._emalify_format_phone_number(None, '0724512285') == '254724512285'
    assert SmsSms._emalify_format_phone_number(None, '+254 724 512 285') == '254724512285'
    assert SmsSms._emalify_format_phone_number(None, '123') is None


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok  %s' % name)
