"""Instagram Graph API (Instagram Login) ile yayın ve token yenileme.
Facebook sayfası gerekmez; İşletme veya İçerik Üreticisi hesabı yeterlidir."""
from __future__ import annotations

import base64
import logging
import os
import time

import requests

from . import config

log = logging.getLogger(__name__)
BASE = f"{config.IG_API_HOST}/{config.IG_API_VERSION}"


class InstagramError(RuntimeError):
    pass


def _check(r: requests.Response) -> dict:
    try:
        data = r.json()
    except ValueError:
        raise InstagramError(f"HTTP {r.status_code}: {r.text[:300]}")
    if r.status_code >= 400 or "error" in data:
        err = data.get("error", {})
        raise InstagramError(f"{err.get('message', r.text[:300])} (code={err.get('code')}, "
                             f"subcode={err.get('error_subcode')})")
    return data


def refresh_token(token: str) -> tuple[str, int]:
    """Uzun ömürlü (60 gün) token'ı yeniler. Token en az 24 saatlik olmalıdır."""
    r = requests.get(f"{config.IG_API_HOST}/refresh_access_token",
                     params={"grant_type": "ig_refresh_token", "access_token": token}, timeout=30)
    data = _check(r)
    return data["access_token"], int(data.get("expires_in", 0))


def update_github_secret(name: str, value: str) -> bool:
    """Yenilenen token farklıysa GitHub Secret'ı günceller (GH_PAT gerektirir)."""
    pat, repo = os.getenv("GH_PAT"), os.getenv("GITHUB_REPOSITORY")
    if not (pat and repo):
        return False
    from nacl import encoding, public

    h = {"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"}
    key = requests.get(f"https://api.github.com/repos/{repo}/actions/secrets/public-key", headers=h,
                       timeout=30).json()
    box = public.SealedBox(public.PublicKey(key["key"].encode(), encoding.Base64Encoder()))
    enc = base64.b64encode(box.encrypt(value.encode())).decode()
    r = requests.put(f"https://api.github.com/repos/{repo}/actions/secrets/{name}", headers=h,
                     json={"encrypted_value": enc, "key_id": key["key_id"]}, timeout=30)
    return r.status_code in (201, 204)


def keep_token_alive() -> str:
    token = os.environ["IG_ACCESS_TOKEN"]
    try:
        new, expires = refresh_token(token)
        days = expires / 86400
        if new != token:
            if update_github_secret("IG_ACCESS_TOKEN", new):
                log.info("Instagram token yenilendi ve GitHub Secret güncellendi (%.0f gün geçerli).", days)
            else:
                log.warning("Token yenilendi ama yeni değer kaydedilemedi. GH_PAT secret'ını ekleyin; "
                            "aksi halde %.0f gün sonra token'ı elle yenilemeniz gerekir.", days)
        else:
            log.info("Instagram token süresi uzatıldı (%.0f gün geçerli).", days)
        return new
    except InstagramError as exc:
        log.warning("Token yenilenemedi (yayın mevcut token ile denenecek): %s", exc)
        return token


def publish_image(image_url: str, caption: str) -> str:
    token = keep_token_alive()
    user_id = os.environ["IG_USER_ID"]
    auth = {"Authorization": f"Bearer {token}"}

    container = _check(requests.post(f"{BASE}/{user_id}/media", headers=auth,
                                     data={"image_url": image_url, "caption": caption}, timeout=60))["id"]
    log.info("Medya kapsayıcısı oluşturuldu: %s", container)

    for _ in range(30):  # Instagram görseli kendi sunucusuna çekene kadar bekle
        status = _check(requests.get(f"{BASE}/{container}", headers=auth,
                                     params={"fields": "status_code,status"}, timeout=30))
        code = status.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise InstagramError(f"Kapsayıcı işlenemedi: {status}")
        time.sleep(4)
    else:
        raise InstagramError("Kapsayıcı 2 dakika içinde hazır olmadı.")

    media_id = _check(requests.post(f"{BASE}/{user_id}/media_publish", headers=auth,
                                    data={"creation_id": container}, timeout=60))["id"]
    log.info("Instagram'da yayınlandı. Medya kimliği: %s", media_id)
    return media_id
