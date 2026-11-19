"""Render the saved weekly snapshot as a printable PDF with embedded fonts."""
from datetime import date, timedelta
from html import escape
from io import BytesIO
from pathlib import Path


def render_pdf(stats):
    import reportlab
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    fonts = Path(reportlab.__file__).parent / 'fonts'
    if 'WrappedSans' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('WrappedSans', str(fonts / 'Vera.ttf')))
        pdfmetrics.registerFont(TTFont('WrappedBold', str(fonts / 'VeraBd.ttf')))
        pdfmetrics.registerFontFamily('WrappedSans', normal='WrappedSans', bold='WrappedBold')
    ink, green, muted = (colors.HexColor(value) for value in ('#172718', '#345C2C', '#586457'))
    body = ParagraphStyle('body', fontName='WrappedSans', fontSize=10, leading=14, textColor=ink)
    small = ParagraphStyle('small', parent=body, fontSize=8.5, leading=12, textColor=muted)
    heading = ParagraphStyle('heading', parent=body, fontName='WrappedBold', fontSize=15,
                             leading=20, spaceBefore=17, spaceAfter=9, keepWithNext=True)
    title = ParagraphStyle('title', parent=heading, fontSize=29, leading=35, spaceBefore=10)
    number = ParagraphStyle('number', parent=heading, fontSize=25, leading=32, spaceBefore=0)
    right = ParagraphStyle('right', parent=body, alignment=TA_RIGHT)
    monday = date.fromisoformat(stats['week_start'])
    sunday = monday + timedelta(days=6)
    period = f'{monday:%d/%m/%Y} - {sunday:%d/%m/%Y}'
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, leftMargin=42, rightMargin=42,
                                 topMargin=38, bottomMargin=45, title='Friends Wrapped ' + period,
                                 author='Friends Wrapped')
    story = [Paragraph('FRIENDS WRAPPED', ParagraphStyle('brand', parent=body, textColor=green)),
             Paragraph('Así sonó vuestra semana.', title),
             Paragraph(period + ' · Horario de Madrid', body), Spacer(1, 18)]
    group = stats['group']
    metrics = Table([[
        [Paragraph(str(group['total_plays']), number), Paragraph('reproducciones guardadas', small)],
        [Paragraph(str(group['unique_tracks']), number), Paragraph('canciones distintas', small)],
        [Paragraph(f"{group['estimated_minutes']:.1f}", number), Paragraph('minutos estimados', small)],
    ]], colWidths=[document.width / 3] * 3)
    metrics.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#EAF1DF')),
                                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                ('TOPPADDING', (0, 0), (-1, -1), 12),
                                ('BOTTOMPADDING', (0, 0), (-1, -1), 12)]))
    story.extend([metrics, Paragraph('El ranking del grupo', heading)])
    rows = [[Paragraph(label, small) for label in ['Puesto', 'Perfil', 'Reproducciones', 'Min. estimados']]]
    for member in stats['ranking']:
        rows.append([Paragraph(str(member['rank']), body), Paragraph(escape(member['name']), body),
                     Paragraph(str(member['total_plays']), right),
                     Paragraph(f"{member['estimated_minutes']:.1f}", right)])
    ranking = Table(rows, colWidths=[43, document.width - 233, 95, 95], repeatRows=1, hAlign='LEFT')
    ranking.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                ('LINEBELOW', (0, 0), (-1, 0), 0.7, green),
                                ('LINEBELOW', (0, 1), (-1, -1), 0.4, colors.HexColor('#DDE3D8')),
                                ('TOPPADDING', (0, 0), (-1, -1), 8),
                                ('BOTTOMPADDING', (0, 0), (-1, -1), 8)]))
    story.append(ranking)
    song_items = [Paragraph('Canciones del grupo', heading)]
    for track in group['top_tracks']:
        song_items.extend([Paragraph(escape(track['name']), body),
                           Paragraph(escape(', '.join(track['artists'])) +
                                     f" · {track['plays']} reproducciones", small), Spacer(1, 8)])
    artist_items = [Paragraph('Artistas del grupo', heading)]
    for artist in group['top_artists']:
        artist_items.extend([Paragraph(escape(artist['name']), body),
                             Paragraph(f"{artist['plays']} reproducciones", small), Spacer(1, 8)])
    if not group['total_plays']:
        song_items.append(Paragraph('Sin escuchas guardadas esta semana.', body))
        artist_items.append(Paragraph('Sin escuchas guardadas esta semana.', body))
    lists = Table([[song_items, artist_items]], colWidths=[document.width / 2] * 2)
    lists.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                              ('LEFTPADDING', (0, 0), (0, 0), 0),
                              ('RIGHTPADDING', (0, 0), (0, 0), 16)]))
    story.extend([lists, Spacer(1, 14), Paragraph(
        'Este resumen utiliza el historial guardado por el proyecto. Los huecos de recogida y las fechas '
        'de conexión pueden afectar a las comparaciones. Los minutos se estiman mediante la duración '
        'de las canciones cuando no existe una medición del tiempo reproducido. La cobertura completa '
        'de los días queda sin verificar.', small)])

    def footer(canvas, doc):
        canvas.setStrokeColor(colors.HexColor('#DDE3D8'))
        canvas.line(42, 33, A4[0] - 42, 33)
        canvas.setFont('WrappedSans', 8)
        canvas.setFillColor(muted)
        canvas.drawString(42, 20, 'Friends Wrapped · ' + period)
        canvas.drawRightString(A4[0] - 42, 20, str(canvas.getPageNumber()))

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
