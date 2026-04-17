"""
Don Felipe — Pescadería / Backend
==================================
Flask + PostgreSQL + sesiones server-side + Mercado Pago

Instalación:
    pip install flask psycopg2-binary mercadopago

Variables de entorno necesarias:
    DATABASE_URL   → postgres://user:pass@host:5432/dbname  (Railway lo da automático)
    SECRET_KEY     → string random para sesiones Flask
    MP_ACCESS_TOKEN → (opcional) token de Mercado Pago

Uso local:
    DATABASE_URL=postgres://... python server.py

Setup inicial (primera vez):
    python server.py --setup
    → Crea tablas y usuario admin con contraseña don.felipe
"""

import os
import sys
import hashlib
import json
from datetime import datetime, date
from functools import wraps

from flask import (Flask, request, jsonify, send_from_directory,
                   session, redirect, url_for)
import psycopg2
import psycopg2.extras

# ── Config ──────────────────────────────────────────────────────────────────
DATABASE_URL    = os.environ.get("DATABASE_URL", "")
SECRET_KEY      = os.environ.get("SECRET_KEY", "donfelipe-dev-secret-2026")
MP_ACCESS_TOKEN  = os.environ.get("MP_ACCESS_TOKEN", "")
GEMINI_API_KEY   = os.environ.get("GEMINI_API_KEY", "")
GROK_API_KEY     = os.environ.get("GROK_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BASE_DIR        = os.path.dirname(os.path.abspath(__file__))

# Railway usa postgres:// pero psycopg2 necesita postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app = Flask(__name__, static_folder=BASE_DIR)
app.secret_key = SECRET_KEY
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"]   = os.environ.get("PRODUCTION", "") == "1"


# ── DB helpers ──────────────────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)

def query(sql, params=(), one=False, commit=False):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        if commit:
            conn.commit()
            return cur.rowcount
        rows = cur.fetchone() if one else cur.fetchall()
        return rows
    finally:
        conn.close()

def execute(sql, params=()):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        try:
            return cur.fetchone()
        except Exception:
            return None
    finally:
        conn.close()

def hsh(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def serialize_row(row):
    """Convierte tipos PostgreSQL no serializables a tipos Python básicos."""
    import decimal
    result = {}
    for k, v in dict(row).items():
        if v is None:
            result[k] = None
        elif hasattr(v, 'isoformat'):  # date, time, datetime
            result[k] = v.isoformat()
        elif isinstance(v, decimal.Decimal):
            result[k] = float(v)
        elif isinstance(v, list):
            result[k] = [serialize_row(i) if hasattr(i, 'items') else i for i in v if i is not None]
        else:
            result[k] = v
    return result


# ── Auth helpers ─────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"error": "No autenticado"}), 401
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"error": "No autenticado"}), 401
        if session.get("rol") != "admin":
            return jsonify({"error": "Sin permiso"}), 403
        return f(*args, **kwargs)
    return decorated

def check_permission(seccion: str) -> bool:
    """Devuelve True si el usuario actual puede acceder a la sección."""
    if session.get("rol") == "admin":
        return True
    # Vendedor: chequea tabla de permisos
    row = query(
        "SELECT habilitado FROM permisos_vendedor WHERE seccion=%s",
        (seccion,), one=True
    )
    return bool(row and row["habilitado"])

def perm_required(seccion: str):
    """Decorator que verifica permiso de sección."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get("user_id"):
                return jsonify({"error": "No autenticado"}), 401
            if not check_permission(seccion):
                return jsonify({"error": "Sin permiso para esta sección"}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


# ── Frontend ────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


# ── AUTH API ─────────────────────────────────────────────────────────────────
@app.route("/api/auth/login", methods=["POST"])
def api_login():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    user = query(
        "SELECT id, username, pass_hash, rol, nombre_display FROM usuarios "
        "WHERE username=%s AND activo=TRUE",
        (username,), one=True
    )
    if not user or user["pass_hash"] != hsh(password):
        return jsonify({"error": "Usuario o contraseña incorrectos"}), 401

    session["user_id"]      = user["id"]
    session["username"]     = user["username"]
    session["rol"]          = user["rol"]
    session["nombre_display"] = user["nombre_display"] or user["username"]

    # Permisos para el frontend
    permisos = _get_permisos_vendedor() if user["rol"] == "vendedor" else None

    # Config del negocio
    cfg = _get_config()

    return jsonify({
        "ok": True,
        "user": {
            "id":       user["id"],
            "username": user["username"],
            "rol":      user["rol"],
            "nombre":   user["nombre_display"] or user["username"],
        },
        "permisos": permisos,
        "config":   cfg,
    })


@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/auth/me", methods=["GET"])
def api_me():
    if not session.get("user_id"):
        return jsonify({"autenticado": False}), 200
    permisos = _get_permisos_vendedor() if session.get("rol") == "vendedor" else None
    cfg = _get_config()
    return jsonify({
        "autenticado": True,
        "user": {
            "id":       session["user_id"],
            "username": session["username"],
            "rol":      session["rol"],
            "nombre":   session["nombre_display"],
        },
        "permisos": permisos,
        "config":   cfg,
    })


# ── CONFIG API ───────────────────────────────────────────────────────────────
def _get_config():
    rows = query("SELECT clave, valor FROM config")
    return {r["clave"]: r["valor"] for r in rows} if rows else {}

def _get_permisos_vendedor():
    rows = query("SELECT seccion, habilitado FROM permisos_vendedor ORDER BY seccion")
    return {r["seccion"]: r["habilitado"] for r in rows} if rows else {}

@app.route("/api/config", methods=["GET"])
@login_required
def api_config_get():
    cfg = _get_config()
    # El mp_token solo lo ve el admin
    if session.get("rol") != "admin":
        cfg.pop("mp_token", None)
    return jsonify(cfg)

@app.route("/api/config", methods=["PUT"])
@admin_required
def api_config_put():
    data = request.get_json() or {}
    for clave, valor in data.items():
        execute("UPDATE config SET valor=%s WHERE clave=%s", (str(valor), clave))
    return jsonify({"ok": True})


# ── USUARIOS API (solo admin) ────────────────────────────────────────────────
@app.route("/api/usuarios", methods=["GET"])
@admin_required
def api_usuarios_get():
    rows = query(
        "SELECT id, username, rol, nombre_display, activo, creado_en "
        "FROM usuarios ORDER BY id"
    )
    return jsonify([serialize_row(r) for r in rows])

@app.route("/api/usuarios", methods=["POST"])
@admin_required
def api_usuarios_post():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    rol      = data.get("rol", "vendedor")
    nombre   = data.get("nombre_display", username)

    if not username or not password:
        return jsonify({"error": "Faltan datos"}), 400
    if rol not in ("admin", "vendedor"):
        return jsonify({"error": "Rol inválido"}), 400

    try:
        row = execute(
            "INSERT INTO usuarios (username, pass_hash, rol, nombre_display) "
            "VALUES (%s,%s,%s,%s) RETURNING id",
            (username, hsh(password), rol, nombre)
        )
        return jsonify({"ok": True, "id": row["id"] if row else None})
    except psycopg2.errors.UniqueViolation:
        return jsonify({"error": "El usuario ya existe"}), 409

@app.route("/api/usuarios/<int:uid>", methods=["PUT"])
@admin_required
def api_usuarios_put(uid):
    data    = request.get_json() or {}
    nombre  = data.get("nombre_display")
    rol     = data.get("rol")
    activo  = data.get("activo")
    password= data.get("password")

    if nombre  is not None: execute("UPDATE usuarios SET nombre_display=%s WHERE id=%s", (nombre, uid))
    if rol     is not None: execute("UPDATE usuarios SET rol=%s WHERE id=%s", (rol, uid))
    if activo  is not None: execute("UPDATE usuarios SET activo=%s WHERE id=%s", (activo, uid))
    if password:            execute("UPDATE usuarios SET pass_hash=%s WHERE id=%s", (hsh(password), uid))
    return jsonify({"ok": True})

@app.route("/api/usuarios/<int:uid>", methods=["DELETE"])
@admin_required
def api_usuarios_delete(uid):
    if uid == session.get("user_id"):
        return jsonify({"error": "No podés eliminarte a vos mismo"}), 400
    execute("UPDATE usuarios SET activo=FALSE WHERE id=%s", (uid,))
    return jsonify({"ok": True})

@app.route("/api/usuarios/cambiar-password", methods=["POST"])
@login_required
def api_cambiar_pass():
    data     = request.get_json() or {}
    old_pass = data.get("old", "")
    new_pass = data.get("new", "")
    if len(new_pass) < 4:
        return jsonify({"error": "Mínimo 4 caracteres"}), 400
    user = query("SELECT pass_hash FROM usuarios WHERE id=%s", (session["user_id"],), one=True)
    if not user or user["pass_hash"] != hsh(old_pass):
        return jsonify({"error": "Contraseña actual incorrecta"}), 401
    execute("UPDATE usuarios SET pass_hash=%s WHERE id=%s", (hsh(new_pass), session["user_id"]))
    return jsonify({"ok": True})


# ── PERMISOS API (solo admin) ────────────────────────────────────────────────
@app.route("/api/permisos", methods=["GET"])
@admin_required
def api_permisos_get():
    return jsonify(_get_permisos_vendedor())

@app.route("/api/permisos", methods=["PUT"])
@admin_required
def api_permisos_put():
    data = request.get_json() or {}
    for seccion, habilitado in data.items():
        execute(
            "UPDATE permisos_vendedor SET habilitado=%s WHERE seccion=%s",
            (bool(habilitado), seccion)
        )
    return jsonify({"ok": True})


# ── PRODUCTOS API ────────────────────────────────────────────────────────────
@app.route("/api/productos", methods=["GET"])
@perm_required("stock")
def api_productos_get():
    rows = query("SELECT * FROM productos WHERE activo=TRUE ORDER BY nombre")
    return jsonify([serialize_row(r) for r in rows])

@app.route("/api/productos", methods=["POST"])
@perm_required("stock")
def api_productos_post():
    d = request.get_json() or {}
    unidad = d.get("unidad","kg")
    if unidad not in ("kg","unidad","litro","gramo"): unidad="kg"
    row = execute(
        "INSERT INTO productos (nombre,cat,codigo,stock,min_stock,costo,precio,unidad) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (d["nombre"], d.get("cat","Pescados"), d.get("codigo",""),
         d.get("stock",0), d.get("min",5), d.get("costo",0), d.get("precio",0), unidad)
    )
    return jsonify({"ok": True, "id": row["id"] if row else None})

@app.route("/api/productos/<int:pid>", methods=["PUT"])
@perm_required("stock")
def api_productos_put(pid):
    d = request.get_json() or {}
    unidad = d.get("unidad","kg")
    if unidad not in ("kg","unidad","litro","gramo"): unidad="kg"
    execute(
        "UPDATE productos SET nombre=%s,cat=%s,codigo=%s,stock=%s,"
        "min_stock=%s,costo=%s,precio=%s,unidad=%s WHERE id=%s",
        (d["nombre"], d.get("cat","Pescados"), d.get("codigo",""),
         d.get("stock",0), d.get("min",5), d.get("costo",0), d.get("precio",0), unidad, pid)
    )
    return jsonify({"ok": True})

@app.route("/api/productos/<int:pid>", methods=["DELETE"])
@admin_required
def api_productos_delete(pid):
    execute("UPDATE productos SET activo=FALSE WHERE id=%s", (pid,))
    return jsonify({"ok": True})


# ── CLIENTES API ─────────────────────────────────────────────────────────────
@app.route("/api/clientes", methods=["GET"])
@perm_required("clientes")
def api_clientes_get():
    rows = query("SELECT * FROM clientes ORDER BY nombre")
    return jsonify([serialize_row(r) for r in rows])

@app.route("/api/clientes", methods=["POST"])
@perm_required("clientes")
def api_clientes_post():
    d = request.get_json() or {}
    row = execute(
        "INSERT INTO clientes (nombre,tel,email,dir) VALUES (%s,%s,%s,%s) RETURNING id",
        (d["nombre"], d.get("tel",""), d.get("email",""), d.get("dir",""))
    )
    return jsonify({"ok": True, "id": row["id"] if row else None})


# ── VENTAS API ────────────────────────────────────────────────────────────────
@app.route("/api/ventas", methods=["GET"])
@perm_required("caja")
def api_ventas_get():
    fecha = request.args.get("fecha", date.today().isoformat())
    rows = query(
        "SELECT v.*, json_agg(vi.*) AS items "
        "FROM ventas v "
        "LEFT JOIN venta_items vi ON vi.venta_id=v.id "
        "WHERE v.fecha=%s "
        "GROUP BY v.id ORDER BY v.hora DESC",
        (fecha,)
    )
    result = []
    for r in rows:
        row = serialize_row(r)
        row["items"] = [serialize_row(i) for i in (row.get("items") or []) if i] 
        result.append(row)
    return jsonify(result)

@app.route("/api/ventas/rango", methods=["GET"])
@login_required
def api_ventas_rango():
    """KPIs para dashboard/mobile: ventas de los últimos N días."""
    dias = int(request.args.get("dias", 7))
    rows = query(
        "SELECT v.fecha, v.total, v.pago, vi.prod_nombre, vi.kg, vi.cat, vi.precio, vi.subtotal "
        "FROM ventas v "
        "JOIN venta_items vi ON vi.venta_id=v.id "
        "WHERE v.fecha >= CURRENT_DATE - (%s * INTERVAL '1 day') "
        "AND (v.anulada IS NULL OR v.anulada=FALSE)",
        (dias,)
    )
    return jsonify([serialize_row(r) for r in rows])

@app.route("/api/ventas", methods=["POST"])
@perm_required("caja")
def api_ventas_post():
    d = request.get_json() or {}
    items  = d.get("items", [])
    total  = float(d.get("total", 0))
    pago   = d.get("pago", "efectivo")
    cliente= d.get("cliente", "Mostrador")

    if not items or total <= 0:
        return jsonify({"error": "Datos incompletos"}), 400

    conn = get_conn()
    try:
        cur = conn.cursor()

        # Validar stock disponible (descontando reservado)
        for item in items:
            cur.execute(
                "SELECT nombre, stock, COALESCE(stock_reservado,0) AS reservado, unidad "
                "FROM productos WHERE id=%s",
                (item["id"],)
            )
            prod = cur.fetchone()
            if prod:
                disponible = float(prod["stock"]) - float(prod["reservado"])
                if float(item["kg"]) > disponible:
                    reservado = float(prod["reservado"])
                    unidad = prod.get("unidad","kg")
                    msg = f"Stock insuficiente para {prod['nombre']}. "
                    msg += f"Stock total: {prod['stock']}{unidad}"
                    if reservado > 0:
                        msg += f" ({reservado}{unidad} reservados para pedidos)"
                    msg += f". Disponible: {round(disponible,2)}{unidad}"
                    return jsonify({"error": msg}), 400

        # Insertar venta con estado_factura pendiente
        cur.execute(
            "INSERT INTO ventas (fecha,hora,cliente,total,pago,usuario_id,estado_factura) "
            "VALUES (CURRENT_DATE,CURRENT_TIME,%s,%s,%s,%s,'pendiente') RETURNING id",
            (cliente, total, pago, session["user_id"])
        )
        venta_id = cur.fetchone()["id"]

        for item in items:
            cur.execute(
                "INSERT INTO venta_items (venta_id,prod_id,prod_nombre,kg,precio,subtotal,cat) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (venta_id, item["id"], item["nombre"], item["kg"],
                 item["precio"], item["subtotal"], item.get("cat",""))
            )
            # Descontar stock
            cur.execute(
                "UPDATE productos SET stock=GREATEST(0, stock-%s) WHERE id=%s",
                (item["kg"], item["id"])
            )

        # Actualizar cliente si no es mostrador
        if cliente and cliente != "Mostrador":
            cur.execute(
                "UPDATE clientes SET compras=compras+1, total=total+%s WHERE nombre=%s",
                (total, cliente)
            )

        conn.commit()
        return jsonify({"ok": True, "id": venta_id})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ── ANULAR VENTA ─────────────────────────────────────────────────────────────
@app.route("/api/ventas/<int:vid>/factura", methods=["PUT"])
@admin_required
def api_venta_factura(vid):
    """Cambia el estado de facturación de una venta."""
    d = request.get_json() or {}
    estado = d.get("estado")
    if estado not in ("pendiente", "facturada"):
        return jsonify({"error": "Estado inválido"}), 400
    execute("UPDATE ventas SET estado_factura=%s WHERE id=%s", (estado, vid))
    return jsonify({"ok": True})


@app.route("/api/ventas/<int:vid>/anular", methods=["POST"])
@admin_required
def api_ventas_anular(vid):
    d = request.get_json() or {}
    motivo = d.get("motivo", "").strip()
    if not motivo:
        return jsonify({"error": "El motivo de anulacion es obligatorio"}), 400

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM ventas WHERE id=%s", (vid,))
        venta = cur.fetchone()
        if not venta:
            return jsonify({"error": "Venta no encontrada"}), 404
        if venta["anulada"]:
            return jsonify({"error": "La venta ya esta anulada"}), 400

        # Obtener items para devolver stock
        cur.execute("SELECT * FROM venta_items WHERE venta_id=%s", (vid,))
        items = cur.fetchall()

        # Devolver stock
        for item in items:
            cur.execute(
                "UPDATE productos SET stock=stock+%s WHERE id=%s",
                (item["kg"], item["prod_id"])
            )

        # Descontar del historial del cliente
        if venta["cliente"] and venta["cliente"] != "Mostrador":
            cur.execute(
                "UPDATE clientes SET compras=GREATEST(0,compras-1), "
                "total=GREATEST(0,total-%s) WHERE nombre=%s",
                (venta["total"], venta["cliente"])
            )

        # Marcar anulada
        cur.execute(
            "UPDATE ventas SET anulada=TRUE, anulada_en=NOW(), "
            "anulada_por=%s, motivo_anulacion=%s WHERE id=%s",
            (session["user_id"], motivo, vid)
        )

        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ── LOTES API ─────────────────────────────────────────────────────────────────
@app.route("/api/lotes", methods=["GET"])
@perm_required("stock")
def api_lotes_get():
    rows = query(
        "SELECT l.*, p.codigo FROM lotes l "
        "JOIN productos p ON p.id=l.prod_id "
        "ORDER BY l.fecha_venc ASC NULLS LAST"
    )
    return jsonify([serialize_row(r) for r in rows])

@app.route("/api/lotes", methods=["POST"])
@perm_required("stock")
def api_lotes_post():
    d = request.get_json() or {}
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO lotes (prod_id,prod_nombre,kg,costo,proveedor,fecha_in,fecha_venc,nota) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (d["prodId"], d["prodNombre"], d["kg"], d.get("costo",0),
             d.get("proveedor",""), d.get("fechaIn"), d.get("fechaVenc"), d.get("nota",""))
        )
        lote_id = cur.fetchone()["id"]
        # Actualizar stock del producto
        cur.execute(
            "UPDATE productos SET stock=stock+%s, costo=%s WHERE id=%s",
            (d["kg"], d.get("costo",0), d["prodId"])
        )
        # Guardar en hist_costos
        cur.execute(
            "INSERT INTO hist_costos (prod_id,prod_nombre,fecha,costo,precio_venta) "
            "SELECT %s,%s,CURRENT_DATE,%s,precio FROM productos WHERE id=%s",
            (d["prodId"], d["prodNombre"], d.get("costo",0), d["prodId"])
        )
        conn.commit()
        return jsonify({"ok": True, "id": lote_id})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route("/api/lotes/<int:lid>", methods=["DELETE"])
@admin_required
def api_lotes_delete(lid):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT prod_id, kg FROM lotes WHERE id=%s", (lid,))
        lote = cur.fetchone()
        if not lote:
            return jsonify({"error": "Lote no encontrado"}), 404
        # Descontar el stock del producto
        cur.execute(
            "UPDATE productos SET stock=GREATEST(0, stock-%s) WHERE id=%s",
            (lote["kg"], lote["prod_id"])
        )
        cur.execute("DELETE FROM lotes WHERE id=%s", (lid,))
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ── MERMAS API ────────────────────────────────────────────────────────────────
@app.route("/api/mermas", methods=["GET"])
@perm_required("merma")
def api_mermas_get():
    rows = query("SELECT * FROM mermas ORDER BY fecha DESC, id DESC")
    return jsonify([serialize_row(r) for r in rows])

@app.route("/api/mermas", methods=["POST"])
@perm_required("merma")
def api_mermas_post():
    d = request.get_json() or {}
    conn = get_conn()
    try:
        cur = conn.cursor()
        # Obtener costo actual del producto
        prod = query("SELECT costo FROM productos WHERE id=%s", (d["prodId"],), one=True)
        costo_kg = float(prod["costo"]) if prod else 0
        cur.execute(
            "INSERT INTO mermas (prod_id,prod_nombre,kg,costo,fecha,motivo,obs,usuario_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (d["prodId"], d["prodNombre"], d["kg"], costo_kg,
             d.get("fecha", date.today().isoformat()),
             d.get("motivo","otro"), d.get("obs",""), session["user_id"])
        )
        cur.execute(
            "UPDATE productos SET stock=GREATEST(0, stock-%s) WHERE id=%s",
            (d["kg"], d["prodId"])
        )
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ── PEDIDOS API ───────────────────────────────────────────────────────────────
@app.route("/api/pedidos", methods=["GET"])
@perm_required("pedidos")
def api_pedidos_get():
    rows = query(
        "SELECT p.*, json_agg(pi.*) AS items "
        "FROM pedidos p "
        "LEFT JOIN pedido_items pi ON pi.pedido_id=p.id "
        "GROUP BY p.id ORDER BY p.fecha_ent ASC"
    )
    result = []
    for r in rows:
        row = serialize_row(r)
        row["items"] = [serialize_row(i) for i in (row.get("items") or []) if i]
        result.append(row)
    return jsonify(result)

@app.route("/api/pedidos", methods=["POST"])
@perm_required("pedidos")
def api_pedidos_post():
    d = request.get_json() or {}
    items = d.get("items", [])
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO pedidos (cliente,fecha_ent,hora_ent,alerta_horas,total,notas,usuario_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (d["cliente"], d["fechaEnt"], d.get("horaEnt") or None,
             int(d.get("alertaHoras", 2)),
             d.get("total",0), d.get("notas",""), session["user_id"])
        )
        ped_id = cur.fetchone()["id"]
        for item in items:
            cur.execute(
                "INSERT INTO pedido_items (pedido_id,prod_id,prod_nombre,kg,precio,subtotal) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (ped_id, item["id"], item["nombre"], item["kg"], item["precio"], item["subtotal"])
            )
            # Reservar stock del producto
            cur.execute(
                "UPDATE productos SET stock_reservado=COALESCE(stock_reservado,0)+%s WHERE id=%s",
                (item["kg"], item["id"])
            )
        conn.commit()
        return jsonify({"ok": True, "id": ped_id})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/pedidos/<int:pid>", methods=["PUT"])
@perm_required("pedidos")
def api_pedidos_put(pid):
    d = request.get_json() or {}
    estado = d.get("estado")
    if estado:
        execute("UPDATE pedidos SET estado=%s WHERE id=%s", (estado, pid))
        # Al entregar o cancelar, liberar la reserva de stock
        if estado in ("entregado", "cancelado"):
            conn = get_conn()
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM pedido_items WHERE pedido_id=%s", (pid,))
                items = cur.fetchall()
                for item in items:
                    cur.execute(
                        "UPDATE productos SET stock_reservado=GREATEST(0,COALESCE(stock_reservado,0)-%s) WHERE id=%s",
                        (item["kg"], item["prod_id"])
                    )
                conn.commit()
            finally:
                conn.close()
    return jsonify({"ok": True})

@app.route("/api/pedidos/<int:pid>", methods=["DELETE"])
@perm_required("pedidos")
def api_pedidos_delete(pid):
    # Liberar reserva de stock antes de eliminar
    conn = get_conn()
    try:
        cur = conn.cursor()
        # Solo liberar si el pedido está pendiente (entregado ya liberó)
        cur.execute("SELECT estado FROM pedidos WHERE id=%s", (pid,))
        ped = cur.fetchone()
        if ped and ped["estado"] == "pendiente":
            cur.execute("SELECT * FROM pedido_items WHERE pedido_id=%s", (pid,))
            items = cur.fetchall()
            for item in items:
                cur.execute(
                    "UPDATE productos SET stock_reservado=GREATEST(0,COALESCE(stock_reservado,0)-%s) WHERE id=%s",
                    (item["kg"], item["prod_id"])
                )
        cur.execute("DELETE FROM pedidos WHERE id=%s", (pid,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})


# ── ALERTAS DE PEDIDOS ───────────────────────────────────────────────────────
@app.route("/api/pedidos/alertas", methods=["GET"])
@login_required
def api_pedidos_alertas():
    """Pedidos pendientes cuya alarma debe dispararse ahora o ya pasó."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        # Pedidos pendientes con hora de entrega configurada
        cur.execute("""
            SELECT p.id, p.cliente, p.fecha_ent, p.hora_ent,
                   p.alerta_horas, p.total, p.notas,
                   json_agg(pi.*) AS items
            FROM pedidos p
            LEFT JOIN pedido_items pi ON pi.pedido_id=p.id
            WHERE p.estado='pendiente'
            AND p.hora_ent IS NOT NULL
            AND p.fecha_ent >= CURRENT_DATE
            GROUP BY p.id
            ORDER BY p.fecha_ent ASC, p.hora_ent ASC
        """)
        rows = []
        now = datetime.now()
        for r in cur.fetchall():
            row = serialize_row(r)
            row["items"] = [serialize_row(i) for i in (row.get("items") or []) if i]
            # Calcular si la alarma debe dispararse
            if row.get("fecha_ent") and row.get("hora_ent"):
                from datetime import datetime as dt2, timedelta
                try:
                    fecha_str = str(row["fecha_ent"])[:10]
                    hora_str  = str(row["hora_ent"])[:5]
                    entrega_dt = dt2.fromisoformat(f"{fecha_str}T{hora_str}:00")
                    alerta_dt  = entrega_dt - timedelta(hours=int(row.get("alerta_horas",2)))
                    minutos_para_alerta = (alerta_dt - now).total_seconds() / 60
                    minutos_para_entrega = (entrega_dt - now).total_seconds() / 60
                    row["minutos_para_entrega"] = round(minutos_para_entrega)
                    row["minutos_para_alerta"]  = round(minutos_para_alerta)
                    # Disparar si estamos dentro de la ventana de alerta (±60 min)
                    row["alerta_activa"] = -60 <= minutos_para_alerta <= 60
                    row["entrega_pasada"] = minutos_para_entrega < 0
                except Exception:
                    row["alerta_activa"] = False
                    row["entrega_pasada"] = False
            else:
                row["alerta_activa"] = False
                row["entrega_pasada"] = False
            rows.append(row)
        return jsonify(rows)
    finally:
        conn.close()


# ── HIST COSTOS API ───────────────────────────────────────────────────────────
@app.route("/api/hist-costos", methods=["GET"])
@perm_required("rentabilidad")
def api_hist_costos():
    rows = query(
        "SELECT * FROM hist_costos ORDER BY fecha DESC, id DESC LIMIT 100"
    )
    return jsonify([serialize_row(r) for r in rows])


# ── DASHBOARD / KPIs API ──────────────────────────────────────────────────────
@app.route("/api/dashboard", methods=["GET"])
@login_required
def api_dashboard():
    """KPIs consolidados para dashboard y vista mobile."""
    conn = get_conn()
    try:
        cur = conn.cursor()

        # Ventas hoy
        cur.execute("SELECT COALESCE(SUM(total),0) AS hoy FROM ventas WHERE fecha=CURRENT_DATE AND (anulada IS NULL OR anulada=FALSE)")
        ventas_hoy = float(cur.fetchone()["hoy"])

        # Ventas 7 días
        cur.execute("SELECT COALESCE(SUM(total),0) AS s7 FROM ventas WHERE fecha>=CURRENT_DATE-7 AND (anulada IS NULL OR anulada=FALSE)")
        ventas_7 = float(cur.fetchone()["s7"])

        # Semana anterior (comparación %)
        cur.execute("SELECT COALESCE(SUM(total),0) AS sa FROM ventas WHERE fecha>=CURRENT_DATE-14 AND fecha<CURRENT_DATE-7 AND (anulada IS NULL OR anulada=FALSE)")
        ventas_7_ant = float(cur.fetchone()["sa"])

        # Stock crítico (bajo mínimo)
        cur.execute("SELECT COUNT(*) AS n FROM productos WHERE activo=TRUE AND stock<min_stock")
        stock_critico = cur.fetchone()["n"]

        # Merma 30 días (costo)
        cur.execute("SELECT COALESCE(SUM(kg*costo),0) AS mc FROM mermas WHERE fecha>=CURRENT_DATE-30")
        costo_merma = float(cur.fetchone()["mc"])

        # Pedidos pendientes
        cur.execute("SELECT COUNT(*) AS n FROM pedidos WHERE estado='pendiente'")
        pedidos_pend = cur.fetchone()["n"]

        # Vencimientos urgentes (próximos 2 días o vencidos)
        cur.execute(
            "SELECT COUNT(*) AS n FROM lotes "
            "WHERE fecha_venc IS NOT NULL AND fecha_venc<=CURRENT_DATE+2"
        )
        venc_urgente = cur.fetchone()["n"]

        # Productos activos
        cur.execute("SELECT COUNT(*) AS n FROM productos WHERE activo=TRUE")
        n_productos = cur.fetchone()["n"]

        # Barras ventas 7 días
        cur.execute(
            "SELECT fecha, COALESCE(SUM(total),0) AS total "
            "FROM ventas WHERE fecha>=CURRENT_DATE-6 "
            "AND (anulada IS NULL OR anulada=FALSE) "
            "GROUP BY fecha ORDER BY fecha"
        )
        ventas_semana = [{"fecha": str(r["fecha"]), "total": float(r["total"])} for r in cur.fetchall()]

        return jsonify({
            "ventas_hoy":    ventas_hoy,
            "ventas_7":      ventas_7,
            "ventas_7_ant":  ventas_7_ant,
            "stock_critico": stock_critico,
            "costo_merma":   costo_merma,
            "pedidos_pend":  pedidos_pend,
            "venc_urgente":  venc_urgente,
            "n_productos":   n_productos,
            "ventas_semana": ventas_semana,
        })
    finally:
        conn.close()


# ── ASISTENTE IA (Gemini 1.5 Flash) ─────────────────────────────────────────
@app.route("/api/ia/chat", methods=["POST"])
@login_required
def api_ia_chat():
    """
    Proxy seguro hacia Gemini 1.5 Flash. La API key nunca sale al frontend.
    Body: { "mensaje": "...", "historial": [...], "contexto": {...} }
    """
    if not GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY no configurada. Agregala como variable de entorno."}), 503

    import urllib.request
    import urllib.error

    data = request.get_json() or {}
    mensaje   = data.get("mensaje", "").strip()
    historial = data.get("historial", [])   # [{role, text}, ...]
    ctx       = data.get("contexto", {})

    if not mensaje:
        return jsonify({"error": "Mensaje vacío"}), 400

    # ── System prompt especializado ──────────────────────────────────────────
    nombre_negocio = ctx.get("nombre", "Don Felipe")
    productos_str  = ctx.get("productos", "sin datos")
    lotes_str      = ctx.get("lotes", "sin datos")
    merma_str      = ctx.get("merma", "sin datos")
    ventas_str     = ctx.get("ventas", "sin datos")

    system_prompt = f"""Sos el asesor financiero y de gestión de "{nombre_negocio}", una pescadería en Argentina.
Tu especialidad es la gestión de negocios de alimentos perecederos: control de costos, rentabilidad, merma, rotación de stock, fijación de precios y planificación de compras.

DATOS ACTUALES DEL NEGOCIO:
- Productos y stock: {productos_str}
- Lotes y vencimientos: {lotes_str}
- Merma últimos 30 días: {merma_str}
- Ventas recientes: {ventas_str}

CÓMO RESPONDÉS:
- Siempre en español argentino (vos, che, etc.)
- Respuestas cortas y accionables — máximo 3-4 párrafos
- Cuando detectés un problema (merma alta, margen bajo, stock por vencer) lo mencionás directamente con números concretos
- Si el negocio tiene buenas métricas, lo reconocés brevemente y sugerís qué optimizar
- Usás conceptos financieros reales: margen bruto, punto de equilibrio, rotación de inventario, costo de oportunidad, pero los explicás en lenguaje simple
- Nunca inventés datos que no estén en el contexto
- Si no tenés datos suficientes para responder algo, lo decís y sugerís qué registrar en el sistema

CHIPS DE CONSULTA FRECUENTE (podés responder sobre esto):
- Reposición: qué conviene pedir y en qué cantidad según rotación y días de stock
- Vencimientos: qué despachar primero y cómo reducir la merma
- Rentabilidad: qué productos tienen mejor margen y cuáles están en rojo
- Precios: si los precios de venta cubren los costos con margen suficiente
- Merma: análisis de pérdidas y sugerencias para reducirlas
- Proyección: estimaciones de demanda y compras para la próxima semana"""

    # ── Armar conversación para Gemini 1.5 Flash ────────────────────────────
    contents = []
    for msg in historial[-10:]:
        role = "model" if msg.get("role") == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": msg.get("text", "")}]})
    contents.append({"role": "user", "parts": [{"text": mensaje}]})

    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1024, "topP": 0.9},
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT",        "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH",       "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent?key={GEMINI_API_KEY}"

    try:
        import json as _json
        req = urllib.request.Request(
            url,
            data=_json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read().decode("utf-8"))

        candidates = result.get("candidates", [])
        if not candidates:
            return jsonify({"error": "Sin respuesta del modelo"}), 500

        parts = candidates[0].get("content", {}).get("parts", [])
        reply = "".join(p.get("text", "") for p in parts).strip()
        if not reply:
            return jsonify({"error": "Respuesta vacía"}), 500

        return jsonify({"reply": reply})

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            err_data = _json.loads(body)
            msg = err_data.get("error", {}).get("message", str(e))
        except Exception:
            msg = str(e)
        return jsonify({"error": f"Error de Gemini: {msg}"}), 500
    except Exception as e:
        return jsonify({"error": f"Error de conexión: {str(e)}"}), 500


# ── REPORTES API ──────────────────────────────────────────────────────────────
@app.route("/api/reportes/tendencia", methods=["GET"])
@login_required
def api_tendencia():
    """Ventas agrupadas por mes, últimos 3 meses."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                TO_CHAR(fecha, 'YYYY-MM') AS mes,
                TO_CHAR(fecha, 'Mon YYYY') AS mes_label,
                COALESCE(SUM(total),0) AS total,
                COUNT(*) AS n_ventas
            FROM ventas
            WHERE fecha >= CURRENT_DATE - INTERVAL '90 days'
            AND (anulada IS NULL OR anulada=FALSE)
            GROUP BY TO_CHAR(fecha,'YYYY-MM'), TO_CHAR(fecha,'Mon YYYY')
            ORDER BY mes ASC
        """)
        rows = cur.fetchall()
        return jsonify([serialize_row(r) for r in rows])
    finally:
        conn.close()


@app.route("/api/reportes/mensual", methods=["GET"])
@login_required
def api_reporte_mensual():
    """Reporte completo de un mes dado. ?mes=2026-04"""
    mes = request.args.get("mes", date.today().strftime("%Y-%m"))
    conn = get_conn()
    try:
        cur = conn.cursor()

        # Ventas del mes
        cur.execute("""
            SELECT COALESCE(SUM(total),0) AS facturacion,
                   COUNT(*) AS n_ventas,
                   COALESCE(SUM(CASE WHEN pago='efectivo' THEN total ELSE 0 END),0) AS efectivo,
                   COALESCE(SUM(CASE WHEN pago='mercadopago' THEN total ELSE 0 END),0) AS mercadopago,
                   COALESCE(SUM(CASE WHEN pago='transferencia' THEN total ELSE 0 END),0) AS transferencia,
                   COALESCE(SUM(CASE WHEN pago='debito' THEN total ELSE 0 END),0) AS debito
            FROM ventas
            WHERE TO_CHAR(fecha,'YYYY-MM')=%s
            AND (anulada IS NULL OR anulada=FALSE)
        """, (mes,))
        ventas = dict(cur.fetchone())

        # Merma del mes
        cur.execute("""
            SELECT COALESCE(SUM(kg),0) AS kg_perdidos,
                   COALESCE(SUM(kg*costo),0) AS costo_perdido,
                   COUNT(*) AS n_mermas
            FROM mermas WHERE TO_CHAR(fecha,'YYYY-MM')=%s
        """, (mes,))
        merma = dict(cur.fetchone())

        # Top 5 productos más vendidos en kg
        cur.execute("""
            SELECT vi.prod_nombre, ROUND(SUM(vi.kg)::numeric,2) AS kg_total,
                   ROUND(SUM(vi.subtotal)::numeric,0) AS monto_total
            FROM venta_items vi
            JOIN ventas v ON v.id=vi.venta_id
            WHERE TO_CHAR(v.fecha,'YYYY-MM')=%s
            AND (v.anulada IS NULL OR v.anulada=FALSE)
            GROUP BY vi.prod_nombre ORDER BY kg_total DESC LIMIT 5
        """, (mes,))
        top5 = [dict(r) for r in cur.fetchall()]

        # Mejor día del mes
        cur.execute("""
            SELECT fecha, COALESCE(SUM(total),0) AS total
            FROM ventas
            WHERE TO_CHAR(fecha,'YYYY-MM')=%s
            AND (anulada IS NULL OR anulada=FALSE)
            GROUP BY fecha ORDER BY total DESC LIMIT 1
        """, (mes,))
        row_md = cur.fetchone()
        if row_md:
            md = dict(row_md)
            # Convertir fecha a string ISO para evitar problemas de serialización
            if hasattr(md.get('fecha'), 'isoformat'):
                md['fecha'] = md['fecha'].isoformat()
            import decimal
            if isinstance(md.get('total'), decimal.Decimal):
                md['total'] = float(md['total'])
            mejor_dia = md
        else:
            mejor_dia = {}

        # Ventas anuladas del mes
        cur.execute("""
            SELECT COUNT(*) AS n FROM ventas
            WHERE TO_CHAR(fecha,'YYYY-MM')=%s AND anulada=TRUE
        """, (mes,))
        anuladas = cur.fetchone()["n"]

        # Costo estimado de lo vendido
        cur.execute("""
            SELECT COALESCE(SUM(vi.kg * p.costo),0) AS costo_total
            FROM venta_items vi
            JOIN ventas v ON v.id=vi.venta_id
            JOIN productos p ON p.id=vi.prod_id
            WHERE TO_CHAR(v.fecha,'YYYY-MM')=%s
            AND (v.anulada IS NULL OR v.anulada=FALSE)
        """, (mes,))
        costo_row = cur.fetchone()
        costo_vendido = float(costo_row["costo_total"]) if costo_row else 0

        facturacion = float(ventas["facturacion"])
        ganancia = facturacion - costo_vendido - float(merma["costo_perdido"])
        margen = round(ganancia/facturacion*100, 1) if facturacion > 0 else 0

        return jsonify({
            "mes": mes,
            "facturacion": facturacion,
            "n_ventas": ventas["n_ventas"],
            "efectivo": float(ventas["efectivo"]),
            "mercadopago": float(ventas["mercadopago"]),
            "transferencia": float(ventas["transferencia"]),
            "debito": float(ventas["debito"]),
            "costo_vendido": costo_vendido,
            "ganancia": ganancia,
            "margen": margen,
            "merma_kg": float(merma["kg_perdidos"]),
            "merma_costo": float(merma["costo_perdido"]),
            "n_mermas": merma["n_mermas"],
            "top5": top5,
            "mejor_dia": mejor_dia,
            "anuladas": anuladas,
        })
    finally:
        conn.close()


@app.route("/api/reportes/rango", methods=["GET"])
@login_required
def api_reporte_rango():
    """Ventas y merma entre dos fechas. ?desde=2026-04-01&hasta=2026-04-30"""
    desde = request.args.get("desde", date.today().isoformat())
    hasta = request.args.get("hasta", date.today().isoformat())
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT v.fecha, v.hora, v.cliente, v.total, v.pago,
                   json_agg(vi.*) AS items
            FROM ventas v
            LEFT JOIN venta_items vi ON vi.venta_id=v.id
            WHERE v.fecha BETWEEN %s AND %s
            AND (v.anulada IS NULL OR v.anulada=FALSE)
            GROUP BY v.id ORDER BY v.fecha DESC, v.hora DESC
        """, (desde, hasta))
        rows = []
        for r in cur.fetchall():
            row = serialize_row(r)
            row["items"] = [serialize_row(i) for i in (row.get("items") or []) if i]
            rows.append(row)

        # KPIs del rango
        cur.execute("""
            SELECT COALESCE(SUM(total),0) AS total,
                   COUNT(*) AS n_ventas,
                   COALESCE(SUM(CASE WHEN pago='efectivo' THEN total ELSE 0 END),0) AS efectivo,
                   COALESCE(SUM(CASE WHEN pago='mercadopago' THEN total ELSE 0 END),0) AS mercadopago
            FROM ventas
            WHERE fecha BETWEEN %s AND %s
            AND (anulada IS NULL OR anulada=FALSE)
        """, (desde, hasta))
        kpis = dict(cur.fetchone())

        return jsonify({"ventas": rows, "kpis": kpis})
    finally:
        conn.close()


# ── LOGO API ──────────────────────────────────────────────────────────────────
@app.route("/api/config/logo", methods=["POST"])
@admin_required
def api_logo_post():
    """Guarda el logo en base64 en la config."""
    d = request.get_json() or {}
    logo = d.get("logo", "")
    if logo and len(logo) > 500000:  # max ~375KB imagen
        return jsonify({"error": "El logo es muy grande. Máximo 375KB."}), 400
    execute("UPDATE config SET valor=%s WHERE clave='logo'", (logo,))
    # Si no existe la fila, insertarla
    execute("INSERT INTO config (clave, valor) VALUES ('logo', %s) ON CONFLICT (clave) DO UPDATE SET valor=%s", (logo, logo))
    return jsonify({"ok": True})


# ── MERCADO PAGO API ──────────────────────────────────────────────────────────
@app.route("/api/mp/crear-preferencia", methods=["POST"])
@perm_required("caja")
def crear_preferencia():
    try:
        import mercadopago
    except ImportError:
        return jsonify({"error": "Instalá: pip install mercadopago"}), 500

    data   = request.get_json(silent=True) or {}
    total  = float(data.get("total", 0))
    titulo = data.get("titulo", "Don Felipe — Venta")

    if total <= 0:
        return jsonify({"error": "Total inválido"}), 400

    # Obtener token de DB o variable de entorno
    cfg = _get_config()
    token = cfg.get("mp_token") or MP_ACCESS_TOKEN

    if not token or token == "TU_ACCESS_TOKEN_AQUI":
        return jsonify({
            "init_point": "https://www.mercadopago.com.ar/checkout/demo",
            "modo": "DEMO"
        })

    try:
        sdk = mercadopago.SDK(token)
        pref = {
            "items": [{"title": titulo, "quantity": 1, "unit_price": total, "currency_id": "ARS"}],
            "payment_methods": {"installments": int(cfg.get("mp_cuotas", 1))},
            "statement_descriptor": "DON FELIPE PESCADERIA",
            "binary_mode": True,
        }
        result = sdk.preference().create(pref)
        resp   = result["response"]
        link   = resp.get("init_point") or resp.get("sandbox_init_point")
        return jsonify({"init_point": link, "preference_id": resp.get("id")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/mp/notificacion", methods=["POST"])
def mp_notificacion():
    data = request.get_json(silent=True) or {}
    topic = data.get("type") or request.args.get("topic")
    rid   = data.get("data", {}).get("id") or request.args.get("id")
    print(f"[MP] topic={topic}  id={rid}")
    return jsonify({"status": "ok"}), 200


# ── NOTAS API ────────────────────────────────────────────────────────────────
@app.route("/api/notas", methods=["GET"])
@login_required
def api_notas_get():
    rows = query(
        "SELECT * FROM notas WHERE usuario_id=%s ORDER BY completada ASC, creada_en DESC",
        (session["user_id"],)
    )
    return jsonify([serialize_row(r) for r in rows])

@app.route("/api/notas", methods=["POST"])
@login_required
def api_notas_post():
    d = request.get_json() or {}
    texto = d.get("texto","").strip()
    if not texto:
        return jsonify({"error": "El texto no puede estar vacío"}), 400
    row = execute(
        "INSERT INTO notas (usuario_id, texto) VALUES (%s,%s) RETURNING id",
        (session["user_id"], texto)
    )
    return jsonify({"ok": True, "id": row["id"] if row else None})

@app.route("/api/notas/<int:nid>", methods=["PUT"])
@login_required
def api_notas_put(nid):
    d = request.get_json() or {}
    completada = d.get("completada")
    texto = d.get("texto","").strip()
    conn = get_conn()
    try:
        cur = conn.cursor()
        # Solo el dueño puede editar
        cur.execute("SELECT usuario_id FROM notas WHERE id=%s", (nid,))
        nota = cur.fetchone()
        if not nota or nota["usuario_id"] != session["user_id"]:
            return jsonify({"error": "No autorizado"}), 403
        if completada is not None:
            cur.execute("UPDATE notas SET completada=%s WHERE id=%s", (completada, nid))
        if texto:
            cur.execute("UPDATE notas SET texto=%s WHERE id=%s", (texto, nid))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()

@app.route("/api/notas/<int:nid>", methods=["DELETE"])
@login_required
def api_notas_delete(nid):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT usuario_id FROM notas WHERE id=%s", (nid,))
        nota = cur.fetchone()
        if not nota or nota["usuario_id"] != session["user_id"]:
            return jsonify({"error": "No autorizado"}), 403
        cur.execute("DELETE FROM notas WHERE id=%s", (nid,))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()

@app.route("/api/notas/limpiar", methods=["DELETE"])
@login_required
def api_notas_limpiar():
    """Elimina todas las notas completadas del usuario."""
    execute(
        "DELETE FROM notas WHERE usuario_id=%s AND completada=TRUE",
        (session["user_id"],)
    )
    return jsonify({"ok": True})


# ── BACKUP API ───────────────────────────────────────────────────────────────
@app.route("/api/backup", methods=["GET"])
@admin_required
def api_backup():
    """Exporta todos los datos en JSON para backup."""
    conn = get_conn()
    try:
        cur = conn.cursor()

        def tabla(sql):
            cur.execute(sql)
            return [dict(r) for r in cur.fetchall()]

        from datetime import datetime as dt
        import decimal

        data = {
            "exportado_en": dt.now().isoformat(),
            "version": "donfelipe-v3",
            "productos":   tabla("SELECT * FROM productos WHERE activo=TRUE ORDER BY nombre"),
            "clientes":    tabla("SELECT * FROM clientes ORDER BY nombre"),
            "lotes":       tabla("SELECT * FROM lotes ORDER BY fecha_in DESC"),
            "ventas":      tabla("SELECT * FROM ventas ORDER BY fecha DESC, hora DESC"),
            "venta_items": tabla("SELECT * FROM venta_items ORDER BY venta_id"),
            "pedidos":     tabla("SELECT * FROM pedidos ORDER BY fecha_ent DESC"),
            "pedido_items":tabla("SELECT * FROM pedido_items ORDER BY pedido_id"),
            "mermas":      tabla("SELECT * FROM mermas ORDER BY fecha DESC"),
            "hist_costos": tabla("SELECT * FROM hist_costos ORDER BY fecha DESC"),
            "config":      tabla("SELECT clave, valor FROM config WHERE clave != 'logo'"),
        }

        # Convertir tipos no serializables
        def serialize(obj):
            if isinstance(obj, dt):
                return obj.isoformat()
            if hasattr(obj, 'isoformat'):  # date, time
                return obj.isoformat()
            if isinstance(obj, decimal.Decimal):
                return float(obj)
            if hasattr(obj, 'total_seconds'):  # timedelta
                return str(obj)
            try:
                return str(obj)
            except Exception:
                raise TypeError(f"No serializable: {type(obj)}")

        from flask import Response
        nombre = f"donfelipe-backup-{dt.now().strftime('%Y%m%d-%H%M')}.json"
        return Response(
            json.dumps(data, default=serialize, ensure_ascii=False, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename={nombre}"}
        )
    finally:
        conn.close()


# ── SETUP ─────────────────────────────────────────────────────────────────────
def setup_db():
    """Crea tablas e inserta usuario admin inicial."""
    schema_path = os.path.join(BASE_DIR, "schema.sql")
    with open(schema_path, encoding="utf-8") as f:
        sql = f.read()

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        # Crear usuario admin si no existe
        cur.execute("SELECT id FROM usuarios WHERE username='admin'")
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO usuarios (username, pass_hash, rol, nombre_display) "
                "VALUES ('admin', %s, 'admin', 'Administrador')",
                (hsh("don.felipe"),)
            )
            print("✓ Usuario admin creado  →  admin / don.felipe")
        else:
            print("✓ Usuario admin ya existe")
        conn.commit()
        print("✓ Base de datos lista")
    finally:
        conn.close()


# ── Arranque ──────────────────────────────────────────────────────────────────
def run_migrations():
    """Ejecuta ALTER TABLE para columnas nuevas. Siempre seguro con IF NOT EXISTS."""
    migrations = [
        "ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS hora_ent TIME DEFAULT NULL",
        "ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS alerta_horas INTEGER DEFAULT 2",
        "ALTER TABLE productos ADD COLUMN IF NOT EXISTS stock_reservado NUMERIC(10,2) DEFAULT 0",
        "ALTER TABLE productos ADD COLUMN IF NOT EXISTS unidad VARCHAR(20) DEFAULT 'kg'",
        """CREATE TABLE IF NOT EXISTS notas (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
            texto TEXT NOT NULL,
            completada BOOLEAN DEFAULT FALSE,
            creada_en TIMESTAMP DEFAULT NOW()
        )""",
        "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS estado_factura VARCHAR(20) DEFAULT 'pendiente'",
        "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS anulada BOOLEAN DEFAULT FALSE",
        "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS anulada_en TIMESTAMP DEFAULT NULL",
        "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS anulada_por INTEGER REFERENCES usuarios(id)",
        "ALTER TABLE ventas ADD COLUMN IF NOT EXISTS motivo_anulacion TEXT DEFAULT NULL",
    ]
    conn = get_conn()
    try:
        cur = conn.cursor()
        for sql in migrations:
            try:
                cur.execute(sql)
            except Exception as e:
                print(f"⚠  Migración: {e}")
        conn.commit()
    finally:
        conn.close()


def auto_setup():
    """Crea tablas y admin si no existen. Funciona con Flask dev y gunicorn."""
    if not DATABASE_URL:
        return
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='usuarios'"
        )
        existe = cur.fetchone()["count"] > 0
        conn.close()
        if not existe:
            print("⚙  Primera vez — inicializando base de datos...")
            setup_db()
            print("✓  Setup automático completado")
        else:
            print("✓  Base de datos OK")
        # Siempre ejecutar migraciones para columnas nuevas
        run_migrations()
    except Exception as e:
        print(f"⚠  Error en auto_setup: {e}")

if __name__ == "__main__":
    if "--setup" in sys.argv:
        setup_db()
        sys.exit(0)

    if not DATABASE_URL:
        print("⚠  DATABASE_URL no configurado.")
        sys.exit(1)

    # Setup automático si las tablas no existen
    auto_setup()

    modo_mp = "ACTIVO" if (MP_ACCESS_TOKEN and MP_ACCESS_TOKEN != "TU_ACCESS_TOKEN_AQUI") else "DEMO"

    print("=" * 55)
    print("  🐟  Don Felipe — Sistema de gestión de pescadería")
    print("=" * 55)
    print(f"  URL:          http://localhost:5000")
    print(f"  Mercado Pago: {modo_mp}")
    print(f"  DB:           PostgreSQL")
    print("=" * 55)

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", debug=os.environ.get("DEBUG","0")=="1", port=port)


