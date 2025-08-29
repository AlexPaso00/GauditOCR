from typing import List
from .schemas import (
    FacturaNormalizada, Linea,
    normalize_igi_rate, igi_code_from_rate
)
import re

# ========= utilidades =========

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

# ========= utilidades nuevas (dinero y extracción por bloques) =========

# Números tipo "199.65" / "199,65" / "-1.234,56"
RE_NUM = re.compile(r"[-+]?\d{1,3}(?:[\.\s]\d{3})*(?:[\,\.]\d{2})|[-+]?\d+(?:[\,\.]\d{2})?")

def _parse_money(s: str | None):
    """Devuelve el *último* número con formato monetario en el texto (evita coger '21' de 'IVA 21% (-504,00€)')."""
    if not s:
        return None
    s = s.replace("€", "").replace("EUR", "")
    nums = RE_NUM.findall(s.strip())
    if not nums:
        return None
    return _to_float(nums[-1])

def _pct_from_text(s: str | None):
    """Extrae el porcentaje (número) de un texto como 'IVA 21% (-504,00€)'."""
    if not s:
        return None
    m = re.search(r"([-+]?\d{1,2}(?:[\,\.]\d+)?)\s*%", str(s))
    return _to_float(m.group(1)) if m else _to_float(s)

def _extract_qty_unit(cell: str | None):
    """
    Extrae cantidad y precio unitario si la celda viene como '-300 x 8,00 €'.
    Devuelve (qty, unit) y usa None si no encuentra alguno.
    """
    if not cell:
        return None, None
    txt = str(cell)
    m = re.search(
        r"(?P<qty>[-+]?\d+(?:[\.\s]\d{3})*(?:[\,\.]\d+)?)[^\S\r\n]*[x×]\s*(?P<unit>\d+(?:[\.\s]\d{3})*(?:[\,\.]\d+)?)",
        txt, re.IGNORECASE
    )
    if m:
        return _to_float(m.group("qty")), _to_float(m.group("unit"))
    # si no hay 'x', intenta solo cantidad
    return _to_float(txt), None

def _extract_block(text: str, header: str, stop_headers: list[str]) -> str | None:
    """Devuelve las líneas bajo 'header' hasta la siguiente cabecera en stop_headers."""
    lines = text.splitlines()
    out, on = [], False
    header_l = header.lower()
    stops = [s.lower() for s in stop_headers]
    for ln in lines:
        l = ln.strip()
        if not l:
            continue
        if not on and header_l in l.lower():
            on = True
            post = l.lower().split(header_l, 1)[-1].strip(": -")
            if post and post != l.lower():
                try:
                    out.append(ln.split(":", 1)[-1].strip())
                except Exception:
                    pass
            continue
        if on:
            if any(s in l.lower() for s in stops):
                break
            out.append(l)
    return _clean_name(" ".join(out)) if out else None

# ========= regex de OCR =========

RE_EMPRESA = re.compile(
    r"\b([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ\.\,&\s]{3,}?(?:S\.?L\.?U?\.?|S\.?A\.?U?\.?|S\.?L\.?|S\.?A\.?|INC\.?|LLC|LTD|GMBH))\b"
)
RE_FACTURA_ID = re.compile(
    r"\b(?:Factura|FACTURA|Nº\s*Factura|N[ºo]\s*Factura|Num(?:ero)?\s*Factura|Invoice|FV)\s*[:\-]?\s*([A-Z0-9\-\/]+)\b",
    re.IGNORECASE
)
RE_FECHA = re.compile(r"\b(\d{2}[\/\-]\d{2}[\/\-]\d{4})\b")
RE_NRT_ANY = re.compile(r"\b([AELF]-?\d{6}-?[A-Z])\b", re.IGNORECASE)
RE_MONEDA = re.compile(r"\b(EUR|€)\b", re.IGNORECASE)

# Totales y metadatos
RE_SUBTOTAL    = re.compile(r"\bsub\s*total|subtotal\b", re.IGNORECASE)
RE_IVA_LINE    = re.compile(r"\b(iva|tax|impuesto)\b.*?(\d{1,2}(?:[\,\.]\d+)?%)?", re.IGNORECASE)
RE_TOTAL       = re.compile(r"\btotal\b", re.IGNORECASE)
RE_DUE         = re.compile(r"\b(fecha\s*vencimiento|due\s*date)\b[:\-\s]*([0-9\/\-]{8,10})", re.IGNORECASE)
RE_PO          = re.compile(r"\b(n[ºo]\s*de\s*pedido|order\s*number)\b[:\-\s]*([A-Z0-9\-\/]+)", re.IGNORECASE)

# Totales específicos ES
RE_BASE_IMP    = re.compile(r"\b(base\s+imponible|base\s+imp\.?|b\.\s*i\.)\b", re.IGNORECASE)
RE_TOTAL_FACT  = re.compile(r"\btotal\s+factura\b", re.IGNORECASE)
RE_TOTAL_IVA   = re.compile(r"\btotal\s+iva\b", re.IGNORECASE)

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

# ====== Extraer líneas desde tablas OCR ======

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

        header = [h.lower() for h in grid[0]]
        def find(*alts):
            for a in alts:
                if a in header:
                    return header.index(a)
            return -1

        i_desc = find("concepte", "concepte/description", "descripció", "descripción", "descripcion",
                      "description", "concepto", "concepe")
        i_qty  = find("quantitat", "cantidad", "qty", "cant.", "cant", "unidades", "ud.", "uds", "qtd", "unitats")
        i_unit = find("preu", "preu unitari", "precio", "precio unitario", "unit price", "p. unit", "pu", "precio/u")
        i_tax  = find("igi", "iva", "i.v.a.", "tax", "impuesto", "% igi", "%", "tipus igi", "tipo iva")
        i_amt  = find("import", "amount", "total línea", "total linea", "total", "importe", "importe (€)", "neto",
                      "base imp.", "base imp", "base")

        for r in grid[1:]:
            desc_txt   = r[i_desc] if i_desc >= 0 and i_desc < len(r) else ""
            qty_txt    = r[i_qty]  if i_qty  >= 0 and i_qty  < len(r) else None
            unit_txt   = r[i_unit] if i_unit >= 0 and i_unit < len(r) else None
            tax_txt    = r[i_tax]  if i_tax  >= 0 and i_tax  < len(r) else None
            amount_txt = r[i_amt]  if i_amt  >= 0 and i_amt  < len(r) else None

            if not any([desc_txt, qty_txt, unit_txt, amount_txt]):
                continue

            # cantidad / unitario pueden venir como "-300 x 8,00 €" en la celda de cantidad
            qty, unit = _extract_qty_unit(qty_txt)
            if unit is None:
                unit = _to_float(unit_txt)

            rate = _pct_from_text(tax_txt)
            amount = _to_float(amount_txt)

            linea = Linea(
                descripcion=_clean_name(desc_txt),
                cantidad=qty,
                precio_unitario=unit,
                tipo_igi=rate,
                total_linea=amount
            )
            _calc_missing_line_taxes(linea)
            out.append(linea)

    return out

# ====== Fallback desde texto OCR ======

def _lines_from_text(text: str) -> List[Linea]:
    """
    Fallback extremo: parsea filas desde texto cuando no hay tables/Items.
    Soporta cabeceras: CANT(IDAD), CONCEPTO/DESCRIPCIÓN, PRECIO, NETO/IMPORTE/BASE IMP./B.I.
    """
    out: List[Linea] = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return out

    # Detectar cabecera en ventana de 3 líneas
    header_idx = -1
    for i in range(len(lines)):
        window = " | ".join(lines[i:i+3]).lower()
        if (("cant" in window or "cantidad" in window)
            and ("concep" in window or "descrip" in window)
            and ("precio" in window or "importe" in window or "neto" in window or "base imp" in window or "b.i." in window)):
            header_idx = i + min(2, len(lines)-i-1)
            break
    if header_idx < 0:
        return out

    # Delimitar bloque hasta 'Subtotal', 'Base imponible' o 'Total'
    end_idx = len(lines)
    for j in range(header_idx + 1, len(lines)):
        lj = lines[j].lower()
        if lj.startswith("subtotal") or lj.startswith("base imponible") or lj.startswith("total"):
            end_idx = j
            break

    body = [b for b in lines[header_idx + 1 : end_idx]
            if "sin líneas" not in b.lower() and "sin lineas" not in b.lower()]
    if not body:
        return out

    num_pat = r"\d+(?:[\.\s]\d{3})*(?:[\,\.]\d+)?"
    pct_pat = r"\d{1,2}(?:[\,\.]\d+)?\s*%"

    # Formato genérico: cant  desc...  precio|—  importe  [iva% ...]
    row_re = re.compile(
        rf"^\s*(?P<qty>[-+]?{num_pat}(?:\s*[x×]\s*{num_pat})?)\s+(?P<desc>.+?)\s+(?P<unit>{num_pat})?\s+(?P<amount>[-+]?{num_pat})(?:\s+{pct_pat}.*)?$",
        re.IGNORECASE
    )

    for ln in body:
        m = row_re.match(ln)
        if not m:
            continue

        qty_raw = m.group("qty")
        qty, unit_from_qty = None, None
        if "x" in qty_raw.lower() or "×" in qty_raw.lower():
            qty, unit_from_qty = _extract_qty_unit(qty_raw)
        else:
            qty = _to_float(qty_raw)

        unit = _to_float(m.group("unit")) if m.group("unit") else unit_from_qty
        amount = _to_float(m.group("amount"))
        desc = _clean_name(m.group("desc"))
        if desc:
            desc = re.sub(r"^\s*x\s*", "", desc, flags=re.IGNORECASE)

        if desc and (qty is not None or unit is not None or amount is not None):
            linea = Linea(
                descripcion=desc,
                cantidad=qty,
                precio_unitario=unit,
                total_linea=amount,
                tipo_igi=None
            )
            _calc_missing_line_taxes(linea)
            out.append(linea)

    return out

def _fill_totals_from_text(text: str, f: FacturaNormalizada):
    """Rellena base/igi/total a partir de texto si faltan."""
    base_guess = None
    iva_guess = None
    total_guess = None
    iva_rate_guess = None

    for ln in text.splitlines():
        l = ln.strip()

        if (RE_SUBTOTAL.search(l) or RE_BASE_IMP.search(l)) and f.base_imponible is None:
            val = _parse_money(l)
            if val is not None:
                base_guess = val

        if RE_TOTAL_IVA.search(l) and iva_guess is None:
            val = _parse_money(l)
            if val is not None:
                iva_guess = val

        m_iva = RE_IVA_LINE.search(l)
        if m_iva and iva_guess is None:
            val = _parse_money(l)
            if val is not None:
                iva_guess = val
            if iva_rate_guess is None and m_iva.group(2):
                iva_rate_guess = _to_float(m_iva.group(2).replace("%", ""))

        if (RE_TOTAL_FACT.search(l) or RE_TOTAL.search(l)) and total_guess is None:
            val = _parse_money(l)
            if val is not None:
                total_guess = val

    if f.base_imponible is None and base_guess is not None:
        f.base_imponible = base_guess
    if f.igi is None and iva_guess is not None:
        f.igi = iva_guess
    if f.total is None and total_guess is not None:
        f.total = total_guess
    if f.total is None and f.base_imponible is not None and f.igi is not None:
        f.total = round(f.base_imponible + f.igi, 2)
    if f.codigo_igi_sage is None and iva_rate_guess is not None:
        f.codigo_igi_sage = igi_code_from_rate(normalize_igi_rate(iva_rate_guess))

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
        if f.total is None and f.base_imponible is not None and f.igi is not None:
            f.total = round(f.base_imponible + f.igi, 2)

        # LÍNEAS desde Items
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

        # Fallback 2: líneas desde texto OCR
        t_doc = _text_from_result(result)
        if not f.lineas:
            f.lineas = _lines_from_text(t_doc)

        # Fallback totales por texto (también en rama con documents)
        if f.base_imponible is None or f.igi is None or f.total is None:
            _fill_totals_from_text(t_doc, f)

        # Fallback 3: línea sintética a partir de totales
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
                precio_unitario=f.base_imponible,  # neto
                tipo_igi=rate,
                total_linea=f.total               # bruto
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

        tipos = {normalize_igi_rate(l.tipo_igi) for l in f.lineas if l.tipo_igi is not None}
        f.codigo_igi_sage = igi_code_from_rate(list(tipos)[0]) if len(tipos) == 1 else f.codigo_igi_sage

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

    # BLOQUES: Facturar a / Enviar a
    stops = ["enviar a", "facturar a", "nº de factura", "fecha", "nº de pedido", "fecha vencimiento", "subtotal", "iva", "total"]
    bill = _extract_block(t, "Facturar a", stops)
    ship = _extract_block(t, "Enviar a", stops)
    if bill and not f.cliente_nombre:
        parts = bill.split(", ")
        f.cliente_nombre = _clean_name(parts[0])
        f.cliente_direccion = _clean_name(bill if len(parts) < 2 else ", ".join(parts[1:]))
    if ship and not f.cliente_razon_social:
        f.cliente_razon_social = _clean_name(ship)

    # Nº pedido y vencimiento (si aplica)
    m_po = RE_PO.search(t)
    if m_po and hasattr(f, "num_pedido"):
        try:
            f.num_pedido = m_po.group(2).strip()
        except Exception:
            pass
    m_due = RE_DUE.search(t)
    if m_due and not f.fecha_vencimiento:
        f.fecha_vencimiento = m_due.group(2).replace("-", "/")

    # Totales por texto
    _fill_totals_from_text(t, f)

    # Líneas
    f.lineas = _lines_from_tables(result)
    if not f.lineas:
        f.lineas = _lines_from_text(t)

    # Línea sintética si aún vacío
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
            precio_unitario=f.base_imponible,
            tipo_igi=rate,
            total_linea=f.total
        )
        _calc_missing_line_taxes(linea)
        f.lineas.append(linea)

    f.clasificacion_sage = "Por revisar"
    return f
