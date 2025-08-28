from pydantic import BaseModel, Field
from typing import List, Optional
import re

# IGI constants (Andorra)
IGI_RATES = [0.0, 1.0, 2.5, 4.5, 9.5]

NRT_REGEX = re.compile(r"\b([AELF])[-\s]?(\d{6})[-\s]?([A-Z])\b", re.IGNORECASE)

def normalize_igi_rate(rate: Optional[float]) -> Optional[float]:
    if rate is None:
        return None
    # snap to closest official IGI rate (0, 1, 2.5, 4.5, 9.5)
    return min(IGI_RATES, key=lambda x: abs(x - round(float(rate), 2)))

def igi_code_from_rate(rate: Optional[float]) -> Optional[str]:
    r = normalize_igi_rate(rate)
    if r is None:
        return None
    txt = str(r).replace('.', '_')
    return f"IGI_{txt}"

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
    proveedor_razon_social: Optional[str] = None   # VendorAddressRecipient

    # CLIENTE
    cliente_nombre: Optional[str] = None
    cliente_nrt: Optional[str] = None
    cliente_direccion: Optional[str] = None
    cliente_razon_social: Optional[str] = None     # CustomerAddressRecipient

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
    clasificacion_sage: Optional[str] = None  # centro de coste / categoría
    codigo_igi_sage: Optional[str] = None     # si homogéneo

    @staticmethod
    def try_extract_nrt(text: Optional[str]) -> Optional[str]:
        if not text:
            return None
        m = NRT_REGEX.search(text.upper())
        if m:
            return f"{m.group(1).upper()}-{m.group(2)}-{m.group(3).upper()}"
        return None
