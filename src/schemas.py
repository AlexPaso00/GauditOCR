from __future__ import annotations

from pydantic import BaseModel, Field
from typing import List, Optional, Any
import re

# --- IGI helpers (los usa normalize para completar impuestos por línea) ---
IGI_RATES = [0.0, 1.0, 2.5, 4.5, 9.5]

def normalize_igi_rate(rate: Optional[float]) -> Optional[float]:
    if rate is None:
        return None
    return min(IGI_RATES, key=lambda x: abs(x - round(float(rate), 2)))

def igi_code_from_rate(rate: Optional[float]) -> Optional[str]:
    r = normalize_igi_rate(rate)
    if r is None:
        return None
    return f"IGI_{str(r).replace('.', '_')}"

# --- NRT/NIF/CIF detection (Andorra + España) ---
RE_NRT_AND = re.compile(r"\b([AELF])[-\s]?(\d{6})[-\s]?([A-Z])\b", re.IGNORECASE)
RE_NIF_ES  = re.compile(r"\b(\d{8})([A-Z])\b", re.IGNORECASE)  # DNI
RE_NIE_ES  = re.compile(r"\b([XYZ])(\d{7})([A-Z])\b", re.IGNORECASE)
RE_CIF_ES  = re.compile(r"\b([ABCDEFGHJKLMNPQRSUVW])(\d{7})([0-9A-J])\b", re.IGNORECASE)

class Linea(BaseModel):
    descripcion: Optional[str] = None
    cantidad: Optional[float] = None
    precio_unitario: Optional[float] = None
    tipo_igi: Optional[float] = None      # en %
    importe_igi: Optional[float] = None
    total_linea: Optional[float] = None
    cuenta_sage: Optional[str] = None
    codigo_igi_sage: Optional[str] = None

class FacturaNormalizada(BaseModel):
    # PROVEEDOR
    proveedor_nombre: Optional[str] = None
    proveedor_nrt: Optional[str] = None
    proveedor_direccion: Optional[str] = None
    proveedor_razon_social: Optional[str] = None

    # CLIENTE
    cliente_nombre: Optional[str] = None
    cliente_nrt: Optional[str] = None
    cliente_direccion: Optional[str] = None
    cliente_razon_social: Optional[str] = None

    # FACTURA
    num_factura: Optional[str] = None
    fecha: Optional[str] = None
    fecha_vencimiento: Optional[str] = None
    moneda: Optional[str] = "EUR"
    forma_pago: Optional[str] = None

    # TOTALES
    base_imponible: Optional[float] = None
    igi: Optional[float] = None
    total: Optional[float] = None

    # LÍNEAS Y CLASIFICACIÓN
    lineas: List[Linea] = Field(default_factory=list)
    clasificacion_sage: Optional[str] = None
    codigo_igi_sage: Optional[str] = None

    # --- Espejo Azure (modo raw) ---
    azure_fields: dict[str, Any] = Field(default_factory=dict)
    azure_items: List[dict] = Field(default_factory=list)
    azure_kv_pairs: List[dict] = Field(default_factory=list)
    azure_tables: List[List[List[str]]] = Field(default_factory=list)

    @staticmethod
    def try_extract_nrt(text: Optional[str]) -> Optional[str]:
        """Devuelve NRT (Andorra) o NIF/NIE/CIF (España) si lo detecta."""
        if not text:
            return None
        t = str(text).upper()

        m = RE_NRT_AND.search(t)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

        m = RE_CIF_ES.search(t)
        if m:
            return f"{m.group(1)}{m.group(2)}{m.group(3)}"

        m = RE_NIE_ES.search(t)
        if m:
            return f"{m.group(1)}{m.group(2)}{m.group(3)}"

        m = RE_NIF_ES.search(t)
        if m:
            return f"{m.group(1)}{m.group(2)}"

        return None
