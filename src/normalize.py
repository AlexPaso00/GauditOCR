from __future__ import annotations

import re
from typing import List
from .schemas import (
    FacturaNormalizada, Linea,
    normalize_igi_rate, igi_code_from_rate
)

# ---------------- utilidades ----------------

def _safeval(field):
    """Extrae .value o .content de un DocumentField/dict."""
    try:
        if field is None:
            return None
        v = getattr(field, "value", None)
        if v is not None and v != "":
            return v
        v = getattr(field, "content", None)
        if v not in (None, ""):
            return v
        if isinstance(field, dict):
            return field.get("value") or field.get("content")
    except Exception:
        pass
    return None

def _to_float(x):
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        try:
            return float(str(x).replace(",", ".").replace(" ", ""))
        except Exception:
            return None

def _clean_name(s: str | None) -> str | None:
    if s is None:
        return None
    return re.sub(r"\s+", " ", str(s)).strip() or None

def _calc_missing_line_taxes(linea: Linea):
    base_linea = None
    if linea.cantidad is not None and linea.precio_unitario is not None:
        base_linea = round(linea.cantidad * linea.precio_unitario, 2)
    if base_linea is None and linea.total_linea is not None and linea.tipo_igi is not None:
        r = normalize_igi_rate(linea.tipo_igi)
        base_linea = round(linea.total_linea / (1 + (r or 0)/100.0), 2)

    r = normalize_igi_rate(linea.tipo_igi) if linea.tipo_igi is not None else None
    if r is not None and base_linea is not None:
        linea.importe_igi = round(base_linea * (r/100.0), 2)
        if linea.total_linea is None:
            linea.total_linea = round(base_linea + linea.importe_igi, 2)
    linea.codigo_igi_sage = igi_code_from_rate(r)

# ---------------- normalizador ----------------

def norm_from_azure(result) -> FacturaNormalizada:
    f = FacturaNormalizada()

    # 1) Si hay 'documents', usamos SOLO los fields estándar (mirror + mapeo ligero)
    doc = result.documents[0] if getattr(result, "documents", None) else None
    if doc and getattr(doc, "fields", None):
        # espejo completo de fields
        for k, v in doc.fields.items():
            f.azure_fields[k] = _safeval(v)

        g = lambda name: _safeval(doc.fields.get(name))
        # Proveedor
        f.proveedor_nombre    = _clean_name(g("VendorName"))
        f.proveedor_nrt       = FacturaNormalizada.try_extract_nrt(g("VendorTaxId"))
        f.proveedor_direccion = _clean_name(g("VendorAddress"))
        f.proveedor_razon_social = _clean_name(g("VendorAddressRecipient"))
        # Cliente
        f.cliente_nombre      = _clean_name(g("CustomerName"))
        f.cliente_nrt         = FacturaNormalizada.try_extract_nrt(g("CustomerTaxId"))
        f.cliente_direccion   = _clean_name(g("CustomerAddress"))
        f.cliente_razon_social= _clean_name(g("CustomerAddressRecipient"))
        # Factura
        f.num_factura   = _clean_name(g("InvoiceId"))
        inv_date        = g("InvoiceDate")
        f.fecha         = str(inv_date) if inv_date is not None else None
        due_date        = g("DueDate")
        f.fecha_vencimiento = str(due_date) if due_date is not None else None
        f.forma_pago    = _clean_name(g("PaymentTerm"))
        f.moneda        = g("CurrencyCode") or "EUR"
        # Totales
        f.base_imponible = _to_float(g("SubTotal"))
        f.igi            = _to_float(g("TotalTax"))
        f.total          = _to_float(g("InvoiceTotal"))
        if f.total is None and f.base_imponible is not None and f.igi is not None:
            f.total = round(f.base_imponible + f.igi, 2)

        # Items (mirror + normalización ligera a Linea)
        items_field = doc.fields.get("Items")
        items_val = getattr(items_field, "value", None) if items_field else None
        if isinstance(items_val, list):
            for it in items_val:
                # espejo
                if hasattr(it, "properties") and isinstance(it.properties, dict):
                    raw = {k: _safeval(v) for k, v in it.properties.items()}
                elif hasattr(it, "value") and isinstance(it.value, dict):
                    raw = {k: _safeval(v) for k, v in it.value.items()}
                elif isinstance(it, dict):
                    raw = {k: _safeval(v) for k, v in it.items()}
                else:
                    raw = {}
                f.azure_items.append(raw)

                # normalización mínima
                linea = Linea(
                    descripcion=_clean_name(raw.get("Description")),
                    cantidad=_to_float(raw.get("Quantity")),
                    precio_unitario=_to_float(raw.get("UnitPrice")),
                    tipo_igi=_to_float(raw.get("TaxRate")),
                    total_linea=_to_float(raw.get("Amount") or raw.get("AmountDue")),
                )
                if any([linea.descripcion, linea.cantidad, linea.precio_unitario, linea.total_linea]):
                    _calc_missing_line_taxes(linea)
                    f.lineas.append(linea)

    # 2) Guardamos siempre KeyValuePairs y Tables (para la “Vista Azure/raw”)
    for kv in getattr(result, "key_value_pairs", []) or []:
        try:
            f.azure_kv_pairs.append({
                "key": getattr(kv.key, "content", None),
                "value": getattr(kv.value, "content", None)
            })
        except Exception:
            pass

    tables = []
    for p in getattr(result, "pages", []) or []:
        for t in getattr(p, "tables", []) or []:
            cells = getattr(t, "cells", []) or []
            if not cells:
                continue
            rows = max((getattr(c, "row_index", 0) for c in cells), default=-1) + 1
            cols = max((getattr(c, "column_index", 0) for c in cells), default=-1) + 1
            grid = [[""] * cols for _ in range(rows)]
            for c in cells:
                txt = getattr(c, "content", None) or getattr(c, "text", None) or ""
                r = getattr(c, "row_index", 0)
                k = getattr(c, "column_index", 0)
                if r < rows and k < cols:
                    grid[r][k] = txt.strip()
            tables.append(grid)
    f.azure_tables = tables

    f.clasificacion_sage = f.clasificacion_sage or "Por revisar"
    return f
