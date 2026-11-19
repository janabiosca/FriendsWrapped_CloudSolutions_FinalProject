"""Generate immutable weekly snapshots and standalone Wrapped reports in private S3."""
from datetime import date, datetime, timedelta
import html
import json
import os
from zoneinfo import ZoneInfo

import boto3
from botocore.exceptions import ClientError

from group_stats import weekly_from_store


def previous_week(reference=None):
    reference = reference or datetime.now(ZoneInfo('Europe/Madrid'))
    today = reference.astimezone(ZoneInfo('Europe/Madrid')).date()
    return today - timedelta(days=today.weekday() + 7)


def keys(group_id, monday):
    prefix = f'wrapped/group={group_id}/week={monday.isoformat()}'
    return {'group_id': group_id, 'week_start': monday.isoformat(),
            'snapshot_key': prefix + '/summary.json', 'report_key': prefix + '/wrapped.html',
            'pdf_key': prefix + '/wrapped.pdf'}


def read_object(key):
    try:
        return boto3.client('s3').get_object(Bucket=os.environ['RAW_BUCKET'], Key=key)['Body'].read()
    except ClientError as error:
        if error.response['Error']['Code'] in ('NoSuchKey', '404'):
            return None
        raise


def write_once(key, body, content_type):
    try:
        boto3.client('s3').put_object(Bucket=os.environ['RAW_BUCKET'], Key=key,
                                    Body=body, ContentType=content_type, IfNoneMatch='*')
    except ClientError as error:
        if error.response['Error']['Code'] != 'PreconditionFailed':
            raise


def prepare(request, reference):
    monday = date.fromisoformat(request['week_start']) if request.get('week_start') else previous_week(reference)
    if monday.weekday() != 0 or monday > previous_week(reference):
        raise ValueError('Choose the Monday of a completed week')
    manifest = keys(os.environ['GROUP_ID'], monday)
    if read_object(manifest['snapshot_key']) is None:
        stats = weekly_from_store(manifest['group_id'], monday, reference)
        write_once(manifest['snapshot_key'], json.dumps(stats, ensure_ascii=False).encode(),
                   'application/json; charset=utf-8')
    return manifest


def render_report(stats):
    esc = lambda text: html.escape(str(text))
    start = date.fromisoformat(stats['week_start'])
    end = start + timedelta(days=6)
    ranking = ''.join(
        '<tr><td>' + str(member['rank']) + '</td><th scope="row">' + esc(member['name']) +
        '</th><td>' + str(member['total_plays']) + '</td><td>' +
        f"{member['estimated_minutes']:.1f}" + '</td></tr>' for member in stats['ranking'])
    tracks = ''.join('<li><strong>' + esc(track['name']) + '</strong> · ' +
                     esc(', '.join(track['artists'])) + ' · ' + str(track['plays']) +
                     ' reproducciones</li>' for track in stats['group']['top_tracks'])
    artists = ''.join('<li><strong>' + esc(artist['name']) + '</strong> · ' +
                      str(artist['plays']) + ' reproducciones</li>'
                      for artist in stats['group']['top_artists'])
    if not stats['group']['total_plays']:
        tracks = artists = '<li>Esta semana no tiene escuchas guardadas.</li>'
    return f'''<!doctype html><html lang="es"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'">
<title>Friends Wrapped · {start:%d/%m/%Y}–{end:%d/%m/%Y}</title>
<style>
body{{margin:0;background:#101310;color:#f4f5e9;font:16px/1.6 system-ui,sans-serif}}
main{{max-width:900px;margin:auto;padding:40px 24px}}h1{{font-size:clamp(36px,7vw,64px);line-height:1.1;letter-spacing:-2px}}
h1, strong{{color:#dcfa87}}.metrics{{display:flex;gap:24px;flex-wrap:wrap}}.metrics p{{flex:1;min-width:160px}}
.metrics strong{{display:block;font-size:36px}}section{{padding:24px 0;border-top:1px solid #333c30}}
table{{width:100%;text-align:left;border-collapse:collapse}}td,th{{padding:12px 6px;border-bottom:1px solid #333c30}}
.scroll{{overflow:auto}}li{{margin:12px 0}}.note,footer{{color:#a8b2a4}}footer{{font-size:13px;margin-top:32px}}
</style><main><p>Friends Wrapped</p><h1>Así sonó vuestra semana.</h1>
<p>{start:%d/%m/%Y}–{end:%d/%m/%Y} · Horario de Madrid</p>
<div class="metrics"><p><strong>{stats['group']['total_plays']}</strong>reproducciones guardadas</p>
<p><strong>{stats['group']['unique_tracks']}</strong>canciones distintas</p>
<p><strong>{stats['group']['estimated_minutes']:.1f}</strong>minutos estimados</p></div>
<section><h2>El ranking del grupo</h2><div class="scroll"><table><thead><tr><th>Puesto</th><th>Perfil</th>
<th>Reproducciones</th><th>Minutos estimados</th></tr></thead><tbody>{ranking}</tbody></table></div></section>
<section><h2>Las canciones de la semana</h2><ol>{tracks}</ol></section>
<section><h2>Los artistas del grupo</h2><ol>{artists}</ol></section>
<p class="note">Este resumen utiliza el historial guardado por el proyecto. Los huecos de recogida y las fechas de conexión
pueden afectar a las comparaciones. Los minutos se estiman mediante la duración de las canciones cuando no existe
una medición del tiempo reproducido. La cobertura completa de los días queda sin verificar.</p>
<footer>Generado el {esc(stats['generated_at'])} · Compartido con el grupo Friends Wrapped</footer></main></html>'''


def archive(manifest):
    monday = date.fromisoformat(manifest['week_start'])
    expected = keys(os.environ['GROUP_ID'], monday)
    legacy = {key: value for key, value in expected.items() if key != 'pdf_key'}
    if manifest not in (expected, legacy):
        raise ValueError('Unexpected report location')
    snapshot = read_object(manifest['snapshot_key'])
    if snapshot is None:
        raise ValueError('The weekly snapshot is missing')
    if read_object(manifest['report_key']) is None:
        report = render_report(json.loads(snapshot)).encode()
        write_once(manifest['report_key'], report, 'text/html; charset=utf-8')
    if read_object(expected['pdf_key']) is None:
        from wrapped_pdf import render_pdf
        write_once(expected['pdf_key'], render_pdf(json.loads(snapshot)), 'application/pdf')
    return {**expected, 'status': 'ready'}


def handler(event, context):
    if event.get('action') == 'prepare':
        reference = datetime.fromisoformat(event['reference_time'].replace('Z', '+00:00'))
        if reference.tzinfo is None:
            raise ValueError('Reference time must include a timezone')
        result = prepare(event.get('request') or {}, reference)
    elif event.get('action') == 'archive':
        result = archive(event['snapshot'])
    else:
        raise ValueError('Unknown Wrapped action')
    print(json.dumps({'event': 'wrapped_' + event['action'], 'week_start': result['week_start']}))
    return result
