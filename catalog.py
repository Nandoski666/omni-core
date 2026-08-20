"""
Catálogo de productos leído desde un Google Sheet publicado como CSV.

Cómo el user actualiza productos:
  1. Abre el Google Sheet (link en la env var CATALOG_CSV_URL)
  2. Edita, agrega o quita filas
  3. En máx 5 min el bot lo refleja (cache TTL configurable)
"""

import csv
import io
import time
import asyncio
import httpx

# Cache global en RAM
_cached_products: list[dict] = []
_cached_formatted: str = ""
_last_refresh_ts: float = 0.0
_refresh_lock = asyncio.Lock()

TRUTHY = {"SI", "SÍ", "YES", "TRUE", "1", "X"}


def _is_truthy(value) -> bool:
    return str(value or "").strip().upper() in TRUTHY


async def _fetch_csv(url: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as http_client:
        response = await http_client.get(url)
        response.raise_for_status()
        text = response.text
    reader = csv.DictReader(io.StringIO(text))
    products = []
    for row in reader:
        # Normaliza claves (quita espacios, ignora mayúsculas)
        normalized = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        if not _is_truthy(normalized.get("activo")):
            continue
        nombre = normalized.get("nombre", "")
        if not nombre:
            continue
        products.append({
            "nombre": nombre,
            "descripcion": normalized.get("descripción", "") or normalized.get("descripcion", ""),
            "precio": normalized.get("precio", ""),
            "link": normalized.get("link", "") or normalized.get("url", ""),
            "categoria": normalized.get("categoría", "") or normalized.get("categoria", ""),
            "es_ganador": _is_truthy(normalized.get("ganador")),
        })
    return products


def _format_for_prompt(products: list[dict], sales_url: str) -> str:
    if not products:
        return ""
    ganadores = [p for p in products if p["es_ganador"]]
    otros = [p for p in products if not p["es_ganador"]]

    lines = ["", "CATÁLOGO ACTUAL DE PRODUCTOS (usa SOLO estos, no inventes otros):"]
    if ganadores:
        lines.append("")
        lines.append("⭐ PRODUCTOS ESTRELLA (menciona primero cuando el interés del cliente encaje):")
        for p in ganadores:
            lines.append(_format_product_line(p, sales_url))
    if otros:
        lines.append("")
        lines.append("Otros productos disponibles:")
        for p in otros:
            lines.append(_format_product_line(p, sales_url))
    lines.append("")
    lines.append("REGLAS DE USO DEL CATÁLOGO:")
    lines.append("- Solo menciona productos que aparecen arriba. Nunca inventes uno que no esté.")
    lines.append("- Cuando recomiendes un producto específico, incluye SU link (no el genérico).")
    lines.append("- Los precios son referenciales; el precio 100% actualizado está en el link del producto.")
    lines.append("- Si el cliente pregunta por algo que NO está en el catálogo, di honestamente que ahora no lo manejas y ofrece los productos estrella como alternativa.")
    return "\n".join(lines)


def _format_product_line(p: dict, sales_url: str) -> str:
    link = p["link"] or sales_url
    parts = [f"• {p['nombre']}"]
    if p["descripcion"]:
        parts.append(f"— {p['descripcion']}")
    if p["precio"]:
        parts.append(f"— Precio ref: {p['precio']}")
    parts.append(f"— {link}")
    return " ".join(parts)


async def refresh_if_stale(csv_url: str, ttl_seconds: int, sales_url: str) -> None:
    """Refresca el catálogo si el cache expiró. Silencioso ante errores."""
    global _cached_products, _cached_formatted, _last_refresh_ts

    if not csv_url:
        return
    if time.time() - _last_refresh_ts < ttl_seconds and _cached_products:
        return

    async with _refresh_lock:
        # Doble-check dentro del lock
        if time.time() - _last_refresh_ts < ttl_seconds and _cached_products:
            return
        try:
            fresh = await _fetch_csv(csv_url)
            _cached_products = fresh
            _cached_formatted = _format_for_prompt(fresh, sales_url)
            _last_refresh_ts = time.time()
            print(f"📦 Catálogo actualizado: {len(fresh)} productos activos")
        except Exception as e:
            print(f"⚠️ No se pudo actualizar el catálogo: {e}")
            _last_refresh_ts = time.time()  # evita reintentar cada mensaje


def get_formatted_for_prompt() -> str:
    """Devuelve el catálogo ya formateado para insertar en el system prompt."""
    return _cached_formatted


def get_products() -> list[dict]:
    return list(_cached_products)
