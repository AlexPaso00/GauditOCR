import os
import base64
from typing import Optional, List

from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient

# Carga variables del .env si existe
load_dotenv()

# === Configuración desde entorno ===
_AZ_ENDPOINT: Optional[str] = os.getenv("AZURE_ENDPOINT")
_AZ_KEY: Optional[str] = os.getenv("AZURE_KEY")

# API version y modelo (con defaults sensatos)
_AZ_API_VERSION: str = os.getenv("AZURE_API_VERSION", "2024-02-29-preview")
_MODEL_ID: str = os.getenv("AZURE_MODEL_ID", "prebuilt-invoice")

# Idioma preferido (catalán por tu caso; prueba "es-ES" si lo prefieres)
_LOCALE: str = os.getenv("AZURE_LOCALE", "ca-ES")

# Features recomendadas (keyValuePairs y tables mejoran detección)
_features_env = os.getenv("AZURE_FEATURES", "keyValuePairs,tables")
_FEATURES: List[str] = [f.strip() for f in _features_env.split(",") if f.strip()]

def _ensure_env():
    if not _AZ_ENDPOINT or not _AZ_KEY:
        raise RuntimeError(
            "Faltan variables de entorno de Azure. "
            "Define AZURE_ENDPOINT y AZURE_KEY en tu .env"
        )

def _client() -> DocumentIntelligenceClient:
    _ensure_env()
    return DocumentIntelligenceClient(
        _AZ_ENDPOINT,
        AzureKeyCredential(_AZ_KEY),
        api_version=_AZ_API_VERSION,
    )

def parse_invoice_bytes(content: bytes):
    if not content:
        raise ValueError("content vacío: debes pasar bytes del archivo a analizar")

    cli = _client()
    b64 = base64.b64encode(content).decode("utf-8")
    analyze_request = {
        "base64Source": b64,        # camelCase como en la API REST
        "locale": _LOCALE,
        "features": _FEATURES,
    }

    poller = cli.begin_analyze_document(
        model_id=_MODEL_ID,
        analyze_request=analyze_request,
    )
    return poller.result()

def parse_invoice_path(path: str):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"No se encontró el archivo: {path}")
    with open(path, "rb") as f:
        return parse_invoice_bytes(f.read())

def parse_invoice_url(url: str):
    if not url or not isinstance(url, str):
        raise ValueError("url inválida")
    cli = _client()
    analyze_request = {
        "urlSource": url,
        "locale": _LOCALE,
        "features": _FEATURES,
    }
    poller = cli.begin_analyze_document(
        model_id=_MODEL_ID,
        analyze_request=analyze_request,
    )
    return poller.result()
