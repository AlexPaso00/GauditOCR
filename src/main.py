import os
import json
import glob
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List

from dotenv import load_dotenv
from .azure_ocr import parse_invoice_bytes
from .normalize import norm_from_azure
from .classify import clasificar
from .schemas import FacturaNormalizada

load_dotenv()

IN_DIR = "data/input"
OUT_DIR = "data/output"
os.makedirs(OUT_DIR, exist_ok=True)


def process_one(path: str) -> FacturaNormalizada:
    """
    Procesa una factura desde disco y devuelve el objeto FacturaNormalizada.
    Mantiene tu lógica actual: Azure Document Intelligence -> normaliza -> clasifica.
    """
    with open(path, "rb") as f:
        content = f.read()

    # Llamada a Azure Document Intelligence (tu función existente)
    result = parse_invoice_bytes(content)

    # ------- DEBUG EXTENDIDO: inspección de valores de campos -------
    try:
        doc = (getattr(result, "documents", []) or [None])[0]
        if doc is None:
            print(f"[DEBUG] {os.path.basename(path)} -> Sin documents en el resultado.")
        else:
            fields = doc.fields or {}
            print(f"[DEBUG] {os.path.basename(path)} -> keys ({len(fields)}): {list(fields.keys())}")

            def _val(field):
                v = getattr(field, "value", None)
                if v is None or v == "":
                    v = getattr(field, "content", None)
                return v

            def _vtype(field):
                return getattr(field, "value_type", None)

            # 1) Campos de cabecera con valor y tipo
            print("=== CAMPOS CABECERA ===")
            for k in [
                "VendorName","VendorTaxId","VendorAddress","VendorAddressRecipient",
                "CustomerName","CustomerTaxId","CustomerAddress","CustomerAddressRecipient",
                "InvoiceId","InvoiceDate","PaymentTerm","SubTotal","TotalTax","InvoiceTotal",
                "TaxDetails","CurrencyCode"
            ]:
                f_k = fields.get(k)
                if f_k is not None:
                    print(f"{k}: value={_val(f_k)!r} | type={_vtype(f_k)}")
                else:
                    if k not in fields:
                        print(f"{k}: <no presente en fields>")

            # 2) Items (líneas)
            print("=== ITEMS (líneas) ===")
            items_field = fields.get("Items")
            items = None
            if items_field is not None:
                items = getattr(items_field, "value", None)
                if items is None:
                    items = getattr(items_field, "content", None)

            if isinstance(items, list):
                print(f"Items detectados: {len(items)}")
                for idx, it in enumerate(items[:5]):  # hasta 5 líneas para no saturar
                    props = {}
                    if hasattr(it, "properties") and isinstance(it.properties, dict):
                        props = it.properties
                    elif hasattr(it, "value") and isinstance(it.value, dict):
                        props = it.value
                    elif isinstance(it, dict):
                        props = it

                    def _p(name):
                        fld = props.get(name)
                        return _val(fld)

                    print(f"  - Linea {idx+1}:")
                    print(f"      Description : {_p('Description')!r}")
                    print(f"      Quantity    : {_p('Quantity')!r}")
                    print(f"      UnitPrice   : {_p('UnitPrice')!r}")
                    print(f"      TaxRate     : {_p('TaxRate')!r}")
                    print(f"      Amount      : {_p('Amount')!r}")
            else:
                kvp = getattr(result, "key_value_pairs", []) or []
                pages = getattr(result, "pages", []) or []
                print(f"Items no estructurados. KVP: {len(kvp)} | pages: {len(pages)}")

    except Exception as _e:
        print("[DEBUG] Error en debug extendido:", _e)
    # ---------------------------------------------------------------

    # Normalización y clasificación (tus funciones existentes)
    norm = norm_from_azure(result)
    norm = clasificar(norm)
    return norm


def to_row(f: FacturaNormalizada) -> Dict[str, Any]:
    """Fila para el CSV resumen (SAGE)."""
    return {
        "proveedor": f.proveedor_nombre,
        "nrt": f.proveedor_nrt,
        "num_factura": f.num_factura,
        "fecha": f.fecha,
        "base": f.base_imponible,
        "igi": f.igi,
        "total": f.total,
        "moneda": f.moneda,
        "igi_codigo": f.codigo_igi_sage or "",     # vacío si hay múltiples tipos por línea
        "clasificacion_sage": f.clasificacion_sage
    }


# ========================
# Funciones para la mini-UI
# ========================

def process_invoice(file_path: str) -> Dict[str, Any]:
    """
    Adapter para la UI: procesa un archivo y devuelve el JSON final (dict).
    Equivale a lo que guardas como Factura.json por CLI.
    """
    f = process_one(file_path)
    return f.model_dump()


def save_output_json(payload: Dict[str, Any], out_path: str) -> None:
    """
    Guarda un JSON (dict) en disco con indentación UTF-8.
    La UI lo usa para escribir en data/output/{uuid}.json y Factura.json.
    """
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as out:
        json.dump(payload, out, indent=2, ensure_ascii=False)


# ========================
# CLI tradicional (batch)
# ========================

def main():
    files: List[str] = [p for p in glob.glob(os.path.join(IN_DIR, "*")) if os.path.isfile(p)]
    registros: List[Dict[str, Any]] = []

    for p in files:
        try:
            f = process_one(p)

            # JSON por factura (igual que antes)
            base = os.path.splitext(os.path.basename(p))[0]
            out_path = os.path.join(OUT_DIR, f"{base}.json")
            save_output_json(f.model_dump(), out_path)

            registros.append(to_row(f))
            print(f"OK  -> {os.path.basename(p)}")

        except Exception as e:
            print(f"FAIL-> {os.path.basename(p)}: {e}")

    # CSV resumen para importar/revisar en SAGE
    if registros:
        df = pd.DataFrame(registros)
        df.to_csv(os.path.join(OUT_DIR, "resumen_sage.csv"), index=False, encoding="utf-8-sig")
        print("Generado data/output/resumen_sage.csv")
    else:
        print("No se generaron registros. Revisa los archivos de entrada en data/input.")


if __name__ == "__main__":
    main()
