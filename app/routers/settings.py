"""Global settings management endpoints."""
import os
import json
from fastapi import APIRouter, Query, HTTPException
from ..database import get_db
from ..models import SettingsUpdate
from ..config import get_setting, set_setting, get_setting_json, set_setting_json

router = APIRouter()


def _try_parse_json(value):
    """Try to parse a value as JSON. Return original string if not valid JSON."""
    if value is None:
        return None
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


@router.get("/settings")
async def get_all_settings():
    """Return all settings as a dict with JSON values parsed."""
    db = get_db()
    rows = db.execute("SELECT key, value FROM settings").fetchall()
    result = {}
    for row in rows:
        result[row["key"]] = _try_parse_json(row["value"])
    return result


@router.put("/settings")
async def update_setting(setting: SettingsUpdate):
    """Update a single setting. Uses JSON setter if the value is a dict/list."""
    try:
        if isinstance(setting.value, (dict, list)):
            set_setting_json(setting.key, setting.value)
        else:
            set_setting(setting.key, str(setting.value))
        return {"status": "updated", "key": setting.key, "value": setting.value}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update setting: {str(e)}")


@router.get("/settings/{key}")
async def get_single_setting(key: str):
    """Get a single setting by key."""
    db = get_db()
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")
    return {"key": key, "value": _try_parse_json(row["value"])}


@router.put("/settings/{key}")
async def update_single_setting(key: str, data: dict):
    """Update a single setting by key. Accepts {value: ...} body."""
    if "value" not in data:
        raise HTTPException(status_code=400, detail="Request body must contain 'value' field")

    value = data["value"]
    try:
        if isinstance(value, (dict, list)):
            set_setting_json(key, value)
        elif isinstance(value, bool):
            set_setting_json(key, value)
        elif isinstance(value, (int, float)):
            set_setting(key, str(value))
        else:
            set_setting(key, str(value))
        return {"status": "updated", "key": key, "value": value}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update setting '{key}': {str(e)}")


@router.post("/settings/test-vault")
async def test_vault_path(data: dict):
    """Test if a vault path is accessible (exists and writable)."""
    path = data.get("path")
    if not path:
        raise HTTPException(status_code=400, detail="'path' is required")

    path = os.path.expanduser(path)

    checks = {
        "path": path,
        "exists": False,
        "is_directory": False,
        "writable": False,
        "readable": False,
    }

    if os.path.exists(path):
        checks["exists"] = True

        if os.path.isdir(path):
            checks["is_directory"] = True

            # Check readability
            checks["readable"] = os.access(path, os.R_OK)

            # Check writability
            checks["writable"] = os.access(path, os.W_OK)
    else:
        # Check if we can create it
        parent = os.path.dirname(path) or "."
        if os.access(parent, os.W_OK):
            checks["writable"] = True
            checks["can_create"] = True
        else:
            checks["can_create"] = False

    all_pass = checks["exists"] and checks["is_directory"] and checks["writable"]

    return {
        "valid": all_pass,
        "checks": checks,
        "message": "Vault path is valid" if all_pass else "Vault path failed validation",
    }


@router.get("/settings/domain-taxonomy")
async def get_domain_taxonomy():
    """Return the domain taxonomy dict from settings."""
    taxonomy = get_setting_json("domain_taxonomy", {})
    if not taxonomy:
        # Return a default empty structure
        taxonomy = {
            "categories": {},
            "description": "Domain classification taxonomy for content categorization",
        }
    return taxonomy


@router.put("/settings/domain-taxonomy")
async def update_domain_taxonomy(data: dict):
    """Update the full domain taxonomy. Accepts a complete dict body."""
    try:
        set_setting_json("domain_taxonomy", data)
        return {
            "status": "updated",
            "key": "domain_taxonomy",
            "categories_count": len(data) if isinstance(data, dict) else len(data),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update domain taxonomy: {str(e)}")
