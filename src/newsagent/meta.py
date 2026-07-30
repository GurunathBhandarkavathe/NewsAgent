from __future__ import annotations

from dataclasses import dataclass, field

import requests

from .config import Config
from .meta_api import meta_response_error_detail, redact_sensitive_meta_text
from .publisher import Publisher


@dataclass
class MetaTestResult:
    ok: bool
    checks: list[dict] = field(default_factory=list)
    account: dict = field(default_factory=dict)
    sample_asset_url: str = ""


def check_meta_connection(config: Config, sample_slide_path: str = "") -> MetaTestResult:
    result = MetaTestResult(ok=True)
    add_config_check(result, "Instagram business account id", bool(config.instagram_business_account_id))
    add_config_check(result, "Meta access token", bool(config.meta_access_token))
    add_config_check(result, "Meta API host", True, f"{config.resolved_meta_api_host} ({config.meta_auth_flow_label})")
    add_config_check(result, "Public HTTPS asset URL", config.public_asset_base_url.startswith("https://"))

    if sample_slide_path and config.public_asset_base_url:
        result.sample_asset_url = Publisher(config)._public_url_for_slide(sample_slide_path)
        add_config_check(result, "Sample public asset URL", result.sample_asset_url.startswith("https://"))

    if not config.instagram_business_account_id or not config.meta_access_token:
        result.ok = False
        return result

    try:
        response = requests.get(
            f"{config.meta_api_base_url}/{config.instagram_business_account_id}",
            params={
                "fields": "id,username,media_count",
                "access_token": config.meta_access_token,
            },
            timeout=30,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError:
            add_config_check(result, "Meta account lookup", False, meta_response_error_detail(response, config))
            return result
        result.account = response.json()
        add_config_check(result, "Meta account lookup", True, f"@{result.account.get('username', 'unknown')}")
    except Exception as exc:
        add_config_check(result, "Meta account lookup", False, redact_sensitive_meta_text(str(exc), config))

    result.ok = all(check["ok"] for check in result.checks)
    return result


def add_config_check(result: MetaTestResult, name: str, ok: bool, detail: str = "") -> None:
    result.checks.append({"name": name, "ok": ok, "detail": detail})
    if not ok:
        result.ok = False
