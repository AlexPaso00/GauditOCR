import os
import uuid
import datetime as dt
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from dotenv import load_dotenv

# --------------------------
# Paths y entorno
# --------------------------
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"
INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
load_dotenv(dotenv_path=ROOT / ".env")

# Pipeline
from .main import process_invoice, save_output_json  # type: ignore

app = FastAPI(title="GauditOCR – Demo UI SAGE Mock")


# --------------------------
# Helpers
# --------------------------
def post_to_sage_mock(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Simula el posteo a SAGE devolviendo un ID de transacción."""
    doc_id = payload.get("num_factura") or str(uuid.uuid4())[:8]
    tx_id = f"MOCK-{dt.datetime.utcnow():%Y%m%d%H%M%S}-{doc_id}"
    return {
        "sage_tx_id": tx_id,
        "posted_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "mode": "mock",
    }

def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    import json as _json
    return _json.loads(path.read_text(encoding="utf-8"))

def _html_table_from_items(items: List[Dict[str, Any]]) -> str:
    """Tabla dinámica para azure_items (columnas = unión de keys)."""
    cols: List[str] = []
    for it in items:
        for k in it.keys():
            if k not in cols:
                cols.append(k)
    if not cols:
        return "<div class='muted'>Sin columnas</div>"

    header = "".join(f"<th>{c}</th>" for c in cols)
    rows = "".join(
        "<tr>" + "".join(f"<td>{(it.get(c, '') or '')}</td>" for c in cols) + "</tr>"
        for it in items
    )
    return f"<table><thead><tr>{header}</tr></thead><tbody>{rows}</tbody></table>"

def _html_table_from_grid(grid: List[List[str]]) -> str:
    rows = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in grid)
    return f"<table><tbody>{rows}</tbody></table>"


# --------------------------
# Vistas
# --------------------------
@app.get("/", response_class=HTMLResponse)
def home():
    rows = []
    for p in sorted(OUTPUT_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        name = p.stem
        if name.endswith(".post"):
            continue
        ts = dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        post_path = OUTPUT_DIR / f"{name}.post.json"
        posted_badge = "<span class='badge grey'>Pendiente</span>"
        if post_path.exists():
            posted_badge = "<span class='badge green'>Completado</span>"
        rows.append(
            f"<tr>"
            f"<td>{name}</td>"
            f"<td>{ts}</td>"
            f"<td>{posted_badge}</td>"
            f"<td>"
            f"<a href='/json/{name}.json' target='_blank'>Ver JSON</a> &nbsp;|&nbsp; "
            f"<a href='/receipt/{name}'>Ver comprobante</a>"
            f"</td>"
            f"</tr>"
        )

    html = f"""
    <html>
      <head>
        <meta charset="utf-8" />
        <title>GauditOCR – Demo</title>
        <style>
          body {{ font-family: Arial, sans-serif; padding: 24px; color:#111827; }}
          .box {{ border:1px solid #e5e7eb; border-radius:10px; padding:16px; margin-bottom:20px; }}
          table {{ border-collapse: collapse; width:100%; }}
          th, td {{ border-bottom:1px solid #f3f4f6; padding:10px; text-align:left; }}
          th {{ background:#f9fafb; }}
          button {{ padding:10px 16px; border:0; border-radius:8px; background:#111827; color:white; cursor:pointer; }}
          button:hover {{ opacity:0.9; }}
          input[type=file] {{ padding:6px; }}
          .muted {{ color:#6b7280; font-size:12px; }}
          .badge {{ padding:2px 8px; border-radius:999px; font-size:12px; }}
          .badge.grey {{ background:#e5e7eb; }}
          .badge.green {{ background:#22c55e; color:white; }}
        </style>
      </head>
      <body>
        <h1>GauditOCR</h1>

        <div class="box">
          <h3>Subir y procesar factura</h3>
          <form action="/upload-and-process" method="post" enctype="multipart/form-data">
            <label>Archivo: </label>
            <input type="file" name="file" accept=".pdf,.png,.jpg,.jpeg" required />
            <button type="submit">Procesar y registrar (mock)</button>
          </form>
          <p class="muted">Se guardará el JSON en <code>data/output/</code> y se generará un comprobante de “Completado en SAGE (mock)”.</p>
        </div>

        <div class="box">
          <h3>Resultados</h3>
          <table>
            <thead><tr><th>Documento</th><th>Fecha</th><th>Estado</th><th>Acciones</th></tr></thead>
            <tbody>{''.join(rows) if rows else '<tr><td colspan="4">Sin resultados aún.</td></tr>'}</tbody>
          </table>
        </div>
      </body>
    </html>
    """
    return HTMLResponse(html)


@app.post("/upload-and-process")
async def upload_and_process(file: UploadFile = File(...), tenant: Optional[str] = Form(None)):
    ext = Path(file.filename).suffix.lower() if file.filename else ".pdf"
    doc_id = str(uuid.uuid4())
    input_path = INPUT_DIR / f"{doc_id}{ext}"
    with input_path.open("wb") as f:
        f.write(await file.read())

    payload = process_invoice(str(input_path))
    out_json_path = OUTPUT_DIR / f"{doc_id}.json"
    save_output_json(payload, str(out_json_path))

    post_res = post_to_sage_mock(payload)
    save_output_json(post_res, str(OUTPUT_DIR / f"{doc_id}.post.json"))

    return RedirectResponse(url=f"/receipt/{doc_id}", status_code=303)


@app.get("/json/{name}")
def get_json(name: str):
    p = OUTPUT_DIR / name
    if not p.exists():
        return JSONResponse({"ok": False, "error": "No existe"}, status_code=404)
    data = read_json(p)
    return JSONResponse(content=data)


@app.get("/receipt/{doc_id}", response_class=HTMLResponse)
def receipt(doc_id: str):
    """
    Vista ÚNICA: Azure (raw). Muestra exactamente lo devuelto por Document Intelligence:
    - azure_items (tabla dinámica)
    - azure_tables (rejillas)
    - azure_fields (key->value)
    - azure_kv_pairs (pares clave-valor)
    """
    json_path = OUTPUT_DIR / f"{doc_id}.json"
    post_path = OUTPUT_DIR / f"{doc_id}.post.json"
    if not json_path.exists() or not post_path.exists():
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    data = read_json(json_path)
    post = read_json(post_path)

    # Azure raw
    azure_items  = data.get("azure_items") or []
    azure_tables = data.get("azure_tables") or []
    azure_fields = data.get("azure_fields") or {}
    azure_kv     = data.get("azure_kv_pairs") or []

    # Mini-resumen sacado directamente de azure_fields (sin normalizar)
    vendor   = azure_fields.get("VendorName") or "-"
    customer = azure_fields.get("CustomerName") or "-"
    inv_id   = azure_fields.get("InvoiceId") or "-"
    inv_date = azure_fields.get("InvoiceDate") or "-"
    subtotal = azure_fields.get("SubTotal") or "-"
    tax      = azure_fields.get("TotalTax") or "-"
    total    = azure_fields.get("InvoiceTotal") or "-"
    curr     = azure_fields.get("CurrencyCode") or "—"

    tx_id = post.get("sage_tx_id")
    posted_at = post.get("posted_at")

    items_html = _html_table_from_items(azure_items) if azure_items else "<div class='muted'>Sin items</div>"
    tables_html = "".join(
        f"<div class='muted'>Tabla {i+1}</div>{_html_table_from_grid(tab)}"
        for i, tab in enumerate(azure_tables)
    ) if azure_tables else "<div class='muted'>Sin tablas</div>"

    fields_rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in azure_fields.items()) or "<tr><td colspan='2' class='muted'>Sin fields</td></tr>"
    kv_rows = "".join(f"<tr><td>{kv.get('key','')}</td><td>{kv.get('value','')}</td></tr>" for kv in azure_kv) or "<tr><td colspan='2' class='muted'>Sin pares clave-valor</td></tr>"

    html = f"""
    <html>
      <head>
        <meta charset="utf-8" />
        <title>Azure raw · Comprobante (mock)</title>
        <style>
          body {{ font-family: Arial, sans-serif; padding: 28px; color:#111827; background:#fafafa; }}
          .card {{ background:white; border:1px solid #e5e7eb; border-radius:14px; padding:20px; max-width: 1100px; margin: 0 auto; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }}
          .header {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; }}
          .badge-ok {{ background:#22c55e; color:white; padding:6px 10px; border-radius:999px; font-weight:600; }}
          .muted {{ color:#6b7280; font-size:12px; }}
          .grid {{ display:grid; grid-template-columns: repeat(4, 1fr); gap:12px; }}
          .kpi {{ background:#f9fafb; border:1px solid #e5e7eb; border-radius:10px; padding:10px; }}
          .kpi .label {{ font-size:12px; color:#6b7280; }}
          table {{ width:100%; border-collapse: collapse; margin-top: 12px; }}
          th, td {{ border-bottom:1px solid #f3f4f6; padding:10px; text-align:left; vertical-align: top; }}
          th {{ background:#f9fafb; }}
          .actions {{ margin-top:20px; display:flex; gap:10px; }}
          a.btn {{ text-decoration:none; display:inline-block; padding:10px 14px; border-radius:8px; }}
          .btn-dark {{ background:#111827; color:white; }}
          .btn-ghost {{ background:white; color:#111827; border:1px solid #e5e7eb; }}
          code {{ background:#f3f4f6; padding:2px 4px; border-radius:4px; }}
        </style>
      </head>
      <body>
        <div class="card">
          <div class="header">
            <div>
              <h2 style="margin:0;">Documento procesado · Vista Azure (raw)</h2>
              <div class="muted">Transacción <code>{tx_id}</code> · {posted_at}</div>
            </div>
            <span class="badge-ok">Completado</span>
          </div>

          <div class="grid">
            <div class="kpi"><div class="label">Proveedor</div><div><strong>{vendor}</strong></div></div>
            <div class="kpi"><div class="label">Cliente</div><div><strong>{customer}</strong></div></div>
            <div class="kpi"><div class="label">Nº factura</div><div><strong>{inv_id}</strong></div></div>
            <div class="kpi"><div class="label">Fecha</div><div><strong>{inv_date}</strong></div></div>
            <div class="kpi"><div class="label">Subtotal</div><div><strong>{subtotal}</strong></div></div>
            <div class="kpi"><div class="label">Impuestos</div><div><strong>{tax}</strong></div></div>
            <div class="kpi"><div class="label">Total</div><div><strong>{total}</strong></div></div>
            <div class="kpi"><div class="label">Moneda</div><div><strong>{curr}</strong></div></div>
          </div>

          <h3 style="margin-top:18px;">Items</h3>
          {items_html}

          <h3 style="margin-top:18px;">Tablas</h3>
          {tables_html}

          <h3 style="margin-top:18px;">Fields</h3>
          <table><tbody>{fields_rows}</tbody></table>

          <h3 style="margin-top:18px;">Key-Value pairs</h3>
          <table><tbody>{kv_rows}</tbody></table>

          <div class="actions">
            <a class="btn btn-dark" href="/json/{doc_id}.json" target="_blank">Ver JSON</a>
            <a class="btn btn-ghost" href="/">Volver</a>
          </div>
        </div>
      </body>
    </html>
    """
    return HTMLResponse(html)
