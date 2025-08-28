from typing import List
from .schemas import (
    FacturaNormalizada, Linea,
    normalize_igi_rate, igi_code_from_rate
)
import re

# ========= utilidades =========

def _safeval(field):
    """
    Extrae el valor de un DocumentField:
    - .value si existe
    - si no, .content
    - si no, None
    """
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
    # quita saltos de línea y espacios dobles
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s if s else None

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

# ========= fallback OCR/regex =========

RE_EMPRESA = re.compile(
    r"\b([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ\.\,&\s]{3,}?(?:S\.?L\.?U?\.?|S\.?A\.?U?\.?|S\.?L\.?|S\.?A\.?))\b"
)
RE_FACTURA_ID = re.compile(
    r"\b(?:Factura|FACTURA|Nº\s*Factura|Num(?:ero)?\s*Factura|Invoice|FV)\s*[:\-]?\s*([A-Z0-9\-\/]+)\b"
)
RE_FECHA = re.compile(r"\b(\d{2}[\/\-]\d{2}[\/\-]\d{4})\b")
RE_NRT_ANY = re.compile(r"\b([AELF]-?\d{6}-?[A-Z])\b", re.IGNORECASE)
RE_MONEDA = re.compile(r"\b(EUR|€)\b", re.IGNORECASE)

def _text_from_result(result) -> str:
    lines = []
    for p in getattr(result, "pages", []) or []:
        for ln in getattr(p, "lines", []) or []:
            txt = getattr(ln, "content", None) or getattr(ln, "text", None)
            if txt:
                lines.append(txt)
    for kv in getattr(result, "key_value_pairs", []) or []:
        try:
            k = getattr(kv.key, "content", None) or ""
            v = getattr(kv.value, "content", None) or ""
            if k or v:
                lines.append(f"{k}: {v}".strip(": ").strip())
        except Exception:
            pass
    return "\n".join(lines)

def _normalize_nrt(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.upper().replace(" ", "").replace("--", "-")
    if "-" not in raw and len(raw) >= 8:
        raw = f"{raw[0]}-{raw[1:7]}-{raw[-1]}"
    return raw

# ====== Extraer líneas desde tablas OCR cuando Items no está estructurado ======

def _lines_from_tables(result) -> List[Linea]:
    out: List[Linea] = []
    tables = []
    for p in getattr(result, "pages", []) or []:
        tables.extend(getattr(p, "tables", []) or [])

    for t in tables:
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

        if not grid:
            continue

        # Cabeceras: añade más alias en catalán/es
        header = [h.lower() for h in grid[0]]
        def find(*alts):
            for a in alts:
                if a in header:
                    return header.index(a)
            return -1

        i_desc = find(
            "concepte", "concepte/description", "descripció", "descripción", "descripcion",
            "description", "concepto", "concepe"
        )
        i_qty  = find("quantitat", "cantidad", "qty", "cant.", "unidades", "ud.", "uds", "qtd", "unitats")
        i_unit = find("preu", "preu unitari", "precio", "precio unitario", "unit price", "p. unit", "pu")
        i_tax  = find("igi", "iva", "tax", "impuesto", "% igi", "%", "tipus igi", "tipo iva")
        i_amt  = find("import", "amount", "total línea", "total linea", "total", "importe", "base+igi")

        # Recorre filas de datos
        for r in grid[1:]:
            desc   = r[i_desc] if i_desc >= 0 and i_desc < len(r) else ""
            qty    = r[i_qty]  if i_qty  >= 0 and i_qty  < len(r) else None
            unit   = r[i_unit] if i_unit >= 0 and i_unit < len(r) else None
            tax    = r[i_tax]  if i_tax  >= 0 and i_tax  < len(r) else None
            amount = r[i_amt]  if i_amt  >= 0 and i_amt  < len(r) else None

            if not any([desc, qty, unit, amount]):
                continue

            linea = Linea(
                descripcion=_clean_name(desc),
                cantidad=_to_float(qty),
                precio_unitario=_to_float(unit),
                tipo_igi=_to_float(tax),
                total_linea=_to_float(amount)
            )
            _calc_missing_line_taxes(linea)
            out.append(linea)

    return out

# ========= normalizador principal =========

def norm_from_azure(result) -> FacturaNormalizada:
    doc = result.documents[0] if getattr(result, "documents", None) else None

    # ---- Ruta estándar con fields del prebuilt-invoice ----
    if doc:
        f = FacturaNormalizada()
        g = lambda name: _safeval(doc.fields.get(name)) if doc.fields else None

        # PROVEEDOR
        f.proveedor_nombre       = _clean_name(g("VendorName"))
        f.proveedor_nrt          = FacturaNormalizada.try_extract_nrt(g("VendorTaxId")) or _normalize_nrt(g("VendorTaxId"))
        f.proveedor_direccion    = _clean_name(g("VendorAddress"))
        f.proveedor_razon_social = _clean_name(g("VendorAddressRecipient"))

        # CLIENTE
        f.cliente_nombre         = _clean_name(g("CustomerName"))
        f.cliente_nrt            = FacturaNormalizada.try_extract_nrt(g("CustomerTaxId")) or _normalize_nrt(g("CustomerTaxId"))
        f.cliente_direccion      = _clean_name(g("CustomerAddress"))
        f.cliente_razon_social   = _clean_name(g("CustomerAddressRecipient"))

        # FACTURA
        f.num_factura            = _clean_name(g("InvoiceId"))
        inv_date                 = g("InvoiceDate")
        f.fecha                  = str(inv_date) if inv_date is not None else None
        due_date                 = g("DueDate")
        f.fecha_vencimiento      = str(due_date) if due_date is not None else None
        f.forma_pago             = _clean_name(g("PaymentTerm"))
        f.moneda                 = g("CurrencyCode") or "EUR"

        # TOTALES (nota: SubTotal con T mayúscula)
        f.base_imponible         = _to_float(g("SubTotal"))
        f.igi                    = _to_float(g("TotalTax"))
        f.total                  = _to_float(g("InvoiceTotal"))

        # LÍNEAS: intenta Items
        items_field = doc.fields.get("Items") if doc.fields else None
        items = None
        if items_field is not None:
            items = getattr(items_field, "value", None)
            if items is None:
                items = getattr(items_field, "content", None)

        if isinstance(items, list):
            for it in items:
                props = {}
                if hasattr(it, "properties") and isinstance(it.properties, dict):
                    props = it.properties
                elif hasattr(it, "value") and isinstance(it.value, dict):
                    props = it.value
                elif isinstance(it, dict):
                    props = it

                desc   = _safeval(props.get("Description"))
                qty    = _to_float(_safeval(props.get("Quantity")))
                unit   = _to_float(_safeval(props.get("UnitPrice")))
                rate   = _to_float(_safeval(props.get("TaxRate")))
                amount = _to_float(_safeval(props.get("Amount")))

                linea = Linea(
                    descripcion=_clean_name(desc),
                    cantidad=qty,
                    precio_unitario=unit,
                    tipo_igi=rate,
                    total_linea=amount
                )
                _calc_missing_line_taxes(linea)
                f.lineas.append(linea)

        # Fallback: tablas OCR
        if not f.lineas:
            f.lineas = _lines_from_tables(result)

        # Fallback 2: línea sintética a partir de totales
        if not f.lineas and f.base_imponible is not None and f.total is not None:
            rate = None
            if f.base_imponible and f.igi is not None:
                try:
                    rate = round((f.igi / f.base_imponible) * 100.0, 2)
                except Exception:
                    rate = None
            # precio_unitario = base (10.00) y total_linea = total (10.45)
            linea = Linea(
                descripcion=_clean_name(f"Factura {f.num_factura or ''}".strip()),
                cantidad=1.0,
                precio_unitario=f.base_imponible,  # <-- neto
                tipo_igi=rate,
                total_linea=f.total               # <-- bruto
            )
            _calc_missing_line_taxes(linea)
            f.lineas.append(linea)

        # Completa totales si faltan usando líneas
        if f.base_imponible is None and f.lineas:
            base_estimada = 0.0
            igi_estimada = 0.0
            for l in f.lineas:
                if l.total_linea is not None and l.tipo_igi is not None:
                    r = normalize_igi_rate(l.tipo_igi) or 0.0
                    base = round(l.total_linea / (1 + r/100.0), 2)
                    base_estimada += base
                    igi_estimada += round(base * (r/100.0), 2)
            if base_estimada > 0:
                f.base_imponible = round(base_estimada, 2)
                f.igi = round(igi_estimada, 2)
                if f.total is None:
                    f.total = round(f.base_imponible + f.igi, 2)

        # Código IGI cabecera si homogéneo
        tipos = {normalize_igi_rate(l.tipo_igi) for l in f.lineas if l.tipo_igi is not None}
        f.codigo_igi_sage = igi_code_from_rate(list(tipos)[0]) if len(tipos) == 1 else None

        # Asegura clasificación por defecto
        f.clasificacion_sage = f.clasificacion_sage or "Por revisar"
        return f

    # ---- Fallback OCR si no hay documents ----
    t = _text_from_result(result)
    f = FacturaNormalizada()

    m_emp = RE_EMPRESA.search(t)
    if m_emp:
        f.proveedor_nombre = _clean_name(m_emp.group(1))

    m_nrt = RE_NRT_ANY.search(t)
    if m_nrt:
        f.proveedor_nrt = _normalize_nrt(m_nrt.group(1))

    m_id = RE_FACTURA_ID.search(t)
    if m_id:
        f.num_factura = m_id.group(1).strip(" :-/")

    m_fecha = RE_FECHA.search(t)
    if m_fecha:
        f.fecha = m_fecha.group(1).replace("-", "/")

    if RE_MONEDA.search(t):
        f.moneda = "EUR"

    # Líneas desde tablas si existen
    f.lineas = _lines_from_tables(result)

    # Línea sintética si aún vacío y tenemos totales (poco habitual en este camino)
    if not f.lineas and f.base_imponible is not None and f.total is not None:
        rate = None
        if f.base_imponible and f.igi is not None:
            try:
                rate = round((f.igi / f.base_imponible) * 100.0, 2)
            except Exception:
                rate = None
        linea = Linea(
            descripcion=_clean_name(f"Factura {f.num_factura or ''}".strip()),
            cantidad=1.0,
            precio_unitario=f.base_imponible,  # <-- neto
            tipo_igi=rate,
            total_linea=f.total               # <-- bruto
        )
        _calc_missing_line_taxes(linea)
        f.lineas.append(linea)

    f.clasificacion_sage = "Por revisar"
    return f
