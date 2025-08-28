import os
import uuid
import datetime as dt
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"

INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(dotenv_path=ROOT / ".env")

# Importa adaptadores de tu pipeline
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


# --------------------------
# Vistas
# --------------------------
@app.get("/", response_class=HTMLResponse)
def home():
    rows = []
    for p in sorted(OUTPUT_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        name = p.stem
        if name.endswith(".post"):
            # omitimos los post.json en la lista principal
            continue
        ts = dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        post_path = OUTPUT_DIR / f"{name}.post.json"
        posted_badge = "<span style='background:#e5e7eb;padding:2px 8px;border-radius:999px;'>Pendiente</span>"
        if post_path.exists():
            posted_badge = "<span style='background:#DCFCE7;padding:2px 8px;border-radius:999px;'>Completado</span>"
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
    """
    - Guarda archivo en data/input/{uuid}.ext
    - Ejecuta pipeline (process_invoice) -> data/output/{uuid}.json
    - Postea mock a SAGE -> data/output/{uuid}.post.json
    - Redirige al comprobante (RedirectResponse 303)
    """
    ext = Path(file.filename).suffix.lower() if file.filename else ".pdf"
    doc_id = str(uuid.uuid4())
    input_path = INPUT_DIR / f"{doc_id}{ext}"
    with input_path.open("wb") as f:
        f.write(await file.read())

    # 1) Procesar con tu pipeline
    payload = process_invoice(str(input_path))

    # 2) Guardar JSON de salida
    out_json_path = OUTPUT_DIR / f"{doc_id}.json"
    save_output_json(payload, str(out_json_path))

    # 3) Postear (mock) y guardar comprobante de posteo
    post_res = post_to_sage_mock(payload)
    save_output_json(post_res, str(OUTPUT_DIR / f"{doc_id}.post.json"))

    # 4) Redirigir al comprobante
    return RedirectResponse(url=f"/receipt/{doc_id}", status_code=303)


@app.get("/json/{name}")
def get_json(name: str):
    p = OUTPUT_DIR / name
    if not p.exists():
        return JSONResponse({"ok": False, "error": "No existe"}, status_code=404)
    # Opción 1: devolver dict (JSON real, sin comillas escapadas)
    data = read_json(p)  # parsea archivo a dict
    return JSONResponse(content=data)


@app.get("/receipt/{doc_id}", response_class=HTMLResponse)
def receipt(doc_id: str):
    """
    Render de comprobante "registrado en SAGE (mock)" con estilo simple.
    """
    json_path = OUTPUT_DIR / f"{doc_id}.json"
    post_path = OUTPUT_DIR / f"{doc_id}.post.json"
    if not json_path.exists() or not post_path.exists():
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    data = read_json(json_path)
    post = read_json(post_path)

    proveedor = data.get("proveedor_nombre") or data.get("proveedor", {}).get("nombre")
    proveedor_nrt = data.get("proveedor_nrt") or data.get("proveedor", {}).get("nrt")
    cliente = data.get("cliente_nombre") or data.get("cliente", {}).get("nombre")
    cliente_nrt = data.get("cliente_nrt") or data.get("cliente", {}).get("nrt")
    num_factura = data.get("num_factura") or data.get("factura", {}).get("numero")
    fecha = data.get("fecha") or data.get("factura", {}).get("fecha_emision")
    moneda = data.get("moneda") or data.get("factura", {}).get("moneda") or "EUR"
    base = data.get("base_imponible") or data.get("totales", {}).get("base_imponible")
    impuesto = data.get("igi") or data.get("totales", {}).get("impuesto")
    total = data.get("total") or data.get("totales", {}).get("total")
    lineas = data.get("lineas") or []

    tx_id = post.get("sage_tx_id")
    posted_at = post.get("posted_at")

    # Render
    html = f"""
    <html>
      <head>
        <meta charset="utf-8" />
        <title>Comprobante SAGE (mock)</title>
        <style>
          body {{ font-family: Arial, sans-serif; padding: 28px; color:#111827; background:#fafafa; }}
          .card {{ background:white; border:1px solid #e5e7eb; border-radius:14px; padding:20px; max-width: 980px; margin: 0 auto; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }}
          .header {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; }}
          .badge-ok {{ background:#22c55e; color:white; padding:6px 10px; border-radius:999px; font-weight:600; }}
          .muted {{ color:#6b7280; font-size:12px; }}
          .grid {{ display:grid; grid-template-columns: 1fr 1fr; gap:14px; }}
          table {{ width:100%; border-collapse: collapse; margin-top: 12px; }}
          th, td {{ border-bottom:1px solid #f3f4f6; padding:10px; text-align:left; }}
          th {{ background:#f9fafb; }}
          .totals {{ text-align:right; margin-top: 14px; }}
          .totals div {{ margin: 4px 0; }}
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
              <h2 style="margin:0;">Factura registrada en SAGE (mock)</h2>
              <div class="muted">Transacción <code>{tx_id}</code> · {posted_at}</div>
            </div>
            <span class="badge-ok">Completado</span>
          </div>

          <div class="grid">
            <div>
              <h4 style="margin:0 0 6px 0;">Proveedor</h4>
              <div><strong>{proveedor or '-'}</strong></div>
              <div class="muted">{proveedor_nrt or '-'}</div>
            </div>
            <div>
              <h4 style="margin:0 0 6px 0;">Cliente</h4>
              <div><strong>{cliente or '-'}</strong></div>
              <div class="muted">{cliente_nrt or '-'}</div>
            </div>
          </div>

          <div class="grid" style="margin-top:12px;">
            <div>
              <div class="muted">Número de factura</div>
              <div><strong>{num_factura or '-'}</strong></div>
            </div>
            <div>
              <div class="muted">Fecha</div>
              <div><strong>{fecha or '-'}</strong></div>
            </div>
          </div>

          <table>
            <thead>
              <tr>
                <th>Descripción</th>
                <th style="width:100px;">Cantidad</th>
                <th style="width:140px;">Precio</th>
                <th style="width:140px;">Importe</th>
              </tr>
            </thead>
            <tbody>
              {''.join([
                f"<tr><td>{(l.get('descripcion') or '')}</td>"
                f"<td>{(l.get('cantidad') or '')}</td>"
                f"<td>{(l.get('precio_unitario') or '')}</td>"
                f"<td>{(l.get('total_linea') or '')}</td></tr>"
                for l in lineas
              ]) or '<tr><td colspan="4" class="muted">Sin líneas</td></tr>'}
            </tbody>
          </table>

          <div class="totals">
            <div>Base imponible: <strong>{base if base is not None else '-'}</strong> {moneda}</div>
            <div>Impuestos: <strong>{impuesto if impuesto is not None else '-'}</strong> {moneda}</div>
            <div style="font-size:18px;">Total: <strong>{total if total is not None else '-'}</strong> {moneda}</div>
          </div>

          <div class="actions">
            <a class="btn btn-dark" href="/json/{doc_id}.json" target="_blank">Ver JSON</a>
            <a class="btn btn-ghost" href="/">Volver</a>
          </div>
        </div>
      </body>
    </html>
    """
    return HTMLResponse(html)
