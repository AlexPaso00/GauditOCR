from .schemas import FacturaNormalizada

REGLAS_PROVEEDOR = {
    "FEDA": "Suministros",         # electricidad Andorra
    "ANDORRA TELECOM": "Telecom",
    "AMAZON": "Material de oficina",
    "GOOGLE": "Servicios TI",
    "MICROSOFT": "Servicios TI",
}

KEYWORDS = {
    "hosting": "Servicios TI",
    "domini": "Servicios TI",      # catalán
    "dominio": "Servicios TI",
    "manteniment": "Mantenimiento",
    "mantenimiento": "Mantenimiento",
    "transport": "Logística",
    "neteja": "Servicios generales",
    "limpieza": "Servicios generales",
}

def clasificar(f: FacturaNormalizada) -> FacturaNormalizada:
    cat = None
    if f.proveedor_nombre:
        up = f.proveedor_nombre.upper()
        for k, v in REGLAS_PROVEEDOR.items():
            if k in up:
                cat = v
                break
    if not cat:
        texto = " ".join([(l.descripcion or "") for l in f.lineas]).lower()
        for k, v in KEYWORDS.items():
            if k in texto:
                cat = v
                break
    f.clasificacion_sage = cat or "Por revisar"
    for l in f.lineas:
        if f.clasificacion_sage == "Servicios TI":
            l.cuenta_sage = "629000"
        elif f.clasificacion_sage == "Suministros":
            l.cuenta_sage = "628000"
        else:
            l.cuenta_sage = "620000"
    return f
