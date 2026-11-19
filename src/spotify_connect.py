"""Invitation-only Spotify PKCE onboarding through an API Gateway HTTP API."""
import base64
import hashlib
import html
from http.cookies import SimpleCookie
import json
import os
import secrets
import time
import urllib.parse
import urllib.request

import boto3
from botocore.exceptions import ClientError

import spotify
import store

SCOPES = "user-read-recently-played user-top-read"


class InvalidLink(Exception):
    pass


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def table():
    return boto3.resource("dynamodb").Table(os.environ["OAUTH_TABLE_NAME"])


def page(message, status=200, link=None):
    action = ""
    if link:
        action = f'<p><a href="{html.escape(link, quote=True)}">Conectar Spotify</a></p>'
    return {
        "statusCode": status,
        "headers": {
            "content-type": "text/html; charset=utf-8", "cache-control": "no-store",
            "referrer-policy": "no-referrer", "x-content-type-options": "nosniff",
            "content-security-policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        },
        "body": '<!doctype html><html lang="es"><meta name="viewport" content="width=device-width">'
                '<title>Friends Wrapped</title><h1>Friends Wrapped</h1>'
                f'<p>{html.escape(message)}</p>{action}</html>',
    }


def invitation(token):
    if not token or len(token) > 128:
        raise InvalidLink()
    item = table().get_item(Key={"id": "INVITE#" + digest(token)}, ConsistentRead=True).get("Item")
    if not item or item["expires_at"] <= int(time.time()) or item.get("claimed"):
        raise InvalidLink()
    return item


def start(event, token):
    member = invitation(token)
    state, browser, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    table().put_item(Item={
        "id": "SESSION#" + digest(state), "invite_id": member["id"],
        "browser_hash": digest(browser), "verifier": verifier,
        "expires_at": int(time.time()) + 600,
    })
    query = urllib.parse.urlencode({
        "client_id": os.environ["SPOTIFY_CLIENT_ID"], "response_type": "code",
        "redirect_uri": os.environ["CONNECT_BASE_URL"] + "/callback", "scope": SCOPES,
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        "show_dialog": "true",
    })
    response = page("Abriendo Spotify…", 302)
    response["headers"]["location"] = "https://accounts.spotify.com/authorize?" + query
    response["cookies"] = [f"sfw_connect={browser}; Path=/; Max-Age=600; HttpOnly; Secure; SameSite=Lax"]
    return response


def callback(event, params):
    state = params.get("state", "")
    if not state or len(state) > 128:
        raise InvalidLink()
    key = {"id": "SESSION#" + digest(state)}
    session = table().get_item(Key=key, ConsistentRead=True).get("Item")
    cookies = SimpleCookie()
    cookies.load("; ".join(event.get("cookies", [])))
    browser = cookies.get("sfw_connect")
    if (not session or session["expires_at"] <= int(time.time()) or not browser
            or not secrets.compare_digest(session["browser_hash"], digest(browser.value))):
        raise InvalidLink()
    # Atomic removal prevents the same authorization code being processed concurrently.
    table().delete_item(Key=key, ConditionExpression="attribute_exists(id)")
    if params.get("error") or not params.get("code"):
        return page("No has autorizado la conexión. Puedes volver a abrir tu invitación.", 400)
    member = table().get_item(Key={"id": session["invite_id"]}, ConsistentRead=True).get("Item")
    if not member or member["expires_at"] <= int(time.time()) or member.get("claimed"):
        raise InvalidLink()
    payload = urllib.parse.urlencode({
        "client_id": os.environ["SPOTIFY_CLIENT_ID"], "grant_type": "authorization_code",
        "code": params["code"], "redirect_uri": os.environ["CONNECT_BASE_URL"] + "/callback",
        "code_verifier": session["verifier"],
    }).encode()
    token = spotify._call(urllib.request.Request(spotify.TOKEN_URL, data=payload,
                         headers={"Content-Type": "application/x-www-form-urlencoded"}))
    profile = spotify._call(urllib.request.Request(spotify.API_URL + "/me",
                           headers={"Authorization": "Bearer " + token["access_token"]}))
    account = profile.get("account_id") or profile.get("id")
    if not account or not token.get("refresh_token"):
        return page("Spotify no ha completado la autorización. Pide una nueva invitación.", 400)
    existing = store.get_profile(member["user_id"])
    if existing and existing.get("spotify_account_id") != account:
        return page("Esta integrante ya tiene otra cuenta conectada. Contacta con Jana.", 409)
    # A single Spotify account cannot become two members. The reservation survives retries.
    table().update_item(
        Key={"id": "ACCOUNT#" + digest(account)},
        UpdateExpression="SET user_id = :u",
        ConditionExpression="attribute_not_exists(user_id) OR user_id = :u",
        ExpressionAttributeValues={":u": member["user_id"]},
    )
    table().update_item(
        Key={"id": member["id"]}, UpdateExpression="SET claimed = :yes",
        ConditionExpression="attribute_not_exists(claimed) AND expires_at > :now",
        ExpressionAttributeValues={":yes": True, ":now": int(time.time())},
    )
    # Bind identity before storing a token, so failed/reissued invitations cannot overwrite
    # another account. The collector only sees the member after the token has been saved.
    boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]).update_item(
        Key={"PK": "USER#" + member["user_id"], "SK": "PROFILE"},
        UpdateExpression="SET spotify_account_id = :a, user_id = :u, group_id = :g, "
                         "display_name = :n, cursor_ms = if_not_exists(cursor_ms, :zero)",
        ConditionExpression="attribute_not_exists(spotify_account_id) OR spotify_account_id = :a",
        ExpressionAttributeValues={":a": account, ":u": member["user_id"],
                                   ":g": os.environ["GROUP_ID"], ":n": member["display_name"], ":zero": 0},
    )
    store.save_token(member["user_id"], {"refresh_token": token["refresh_token"]})
    store.add_member(os.environ["GROUP_ID"], member["user_id"], member["display_name"])
    response = page(f"{member['display_name']}, tu Spotify está conectado. "
                    "La recogida comenzará automáticamente. Ya puedes cerrar esta pestaña.")
    response["cookies"] = ["sfw_connect=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax"]
    return response


def handler(event, context):
    params = event.get("queryStringParameters") or {}
    path = event.get("rawPath", "/")
    try:
        if path == "/health":
            return page("Conexión disponible.")
        if path == "/callback":
            return callback(event, params)
        if path == "/start":
            return start(event, params.get("invite", ""))
        if path == "/connect":
            member = invitation(params.get("invite", ""))
            return page(f"Hola, {member['display_name']}. Conecta tu propia cuenta de Spotify "
                        "para compartir tus estadísticas de música con el grupo. "
                        "Comprueba la cuenta que aparece en Spotify antes de aceptar.",
                        link="/start?" + urllib.parse.urlencode({"invite": params["invite"]}))
        return page("Abre la invitación personal que te ha enviado Jana.", 404)
    except InvalidLink:
        return page("El enlace ha caducado o ya se ha utilizado. Pide una nueva invitación.", 400)
    except ClientError as error:
        # Do not log request events, query strings, codes, tokens or Spotify response bodies.
        code = error.response["Error"]["Code"]
        print(json.dumps({"event": "connect_aws_error", "code": code}))
        if code == "ConditionalCheckFailedException":
            return page("La conexión ya se ha utilizado o la cuenta ya está vinculada. Contacta con Jana.", 409)
        return page("No se ha podido guardar la conexión. Contacta con Jana para volver a intentarlo.", 503)
    except (spotify.SpotifyError, KeyError, ValueError, TypeError, OSError):
        print(json.dumps({"event": "connect_spotify_error"}))
        return page("Spotify no ha completado la conexión. Contacta con Jana para volver a intentarlo.", 502)
