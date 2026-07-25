"""
servidor_admin.py
Servidor de LOGIN + PANEL de administración.

Este servidor es el ÚNICO que toca la base de datos (guias.db).
Hace dos cosas:
  1. Sirve /login y /panel (protegidos por sesión con usuario/contraseña).
  2. Expone una API INTERNA (/api/interno/guardar_guia) que el servidor
     público (servidor_publico.py) usa para enviarle cada guía nueva.
     Esa API interna está protegida con un token secreto compartido
     (INTERNAL_TOKEN) — no la llames desde el navegador ni la expongas
     a internet sin más protección (ideal: que solo escuche en localhost
     o detrás de un firewall/VPN).

El HTML vive en templates/ y el CSS/JS en static/ (Flask los sirve solo).
No hay HTML embebido en este archivo: así el frontend queda en un único
lugar y no se puede desincronizar.

Cómo correrlo:
    pip install -r requirements.txt
    python servidor_admin.py

Luego abre:
    http://192.168.1.9:5001/login   -> Login de empleados
    http://192.168.1.9:5001/panel   -> Panel (pide sesión)

Usuario por defecto (primera vez que se crea la base de datos):
    usuario:    admin
    contraseña: admin123
    -> Cámbiala apenas entres la primera vez.

Sobre las claves secretas (FLASK_SECRET_KEY, INTERNAL_TOKEN):
    No tienes que configurar nada. La primera vez que corras este servidor
    se generan solas y quedan guardadas en la carpeta .secretos/ (junto a
    guias.db). servidor_publico.py lee el mismo archivo, así que ambos
    siempre coinciden. Si prefieres controlar tú el valor (por ejemplo en
    un servidor real de producción), puedes definir las variables de
    entorno FLASK_SECRET_KEY / INTERNAL_TOKEN antes de arrancar y esas
    tendrán prioridad sobre el archivo.
"""

import os
import sys
import sqlite3
import threading
from datetime import datetime
from functools import wraps

import webview
from flask import Flask, g, jsonify, request, session, redirect, render_template

from configuracion import obtener_secreto

if getattr(sys, 'frozen', False):
    # Corriendo empaquetado como .exe: usar la carpeta donde está el .exe,
    # no la carpeta temporal donde PyInstaller descomprime el programa.
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(BASE_DIR, 'guias.db')

app = Flask(__name__)

# La clave de sesión y el token interno ya no están escritos en el código.
# Se generan solos la primera vez que corres el servidor y quedan guardados
# en .secretos/ (ver configuracion.py). No tienes que hacer nada a mano.
app.secret_key = obtener_secreto('flask_secret_key.txt', 'FLASK_SECRET_KEY', BASE_DIR)
INTERNAL_TOKEN = obtener_secreto('internal_token.txt', 'INTERNAL_TOKEN', BASE_DIR)

# Cookies de sesión más seguras: no accesibles desde JS y no se envían
# a otros sitios. Marca SESSION_COOKIE_SECURE=1 en el entorno cuando
# sirvas la app por HTTPS (en HTTP plano, dejarlo activo bloquea la cookie).
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE', '0') == '1',
    PERMANENT_SESSION_LIFETIME=60 * 60 * 8,  # 8 horas
)

ESTADOS_VALIDOS = ['Pendiente', 'Recibida', 'En proceso', 'Entregada']
FORMAS_PAGO_VALIDAS = ['Contado', 'Al cobro', 'Contra Entrega']

# Límite simple de intentos de login por usuario (anti fuerza bruta).
# No sustituye un rate-limiter real (ej. Flask-Limiter) en producción,
# pero corta los ataques automáticos más obvios sin dependencias nuevas.
MAX_INTENTOS_LOGIN = 5
VENTANA_BLOQUEO_SEGUNDOS = 5 * 60
_intentos_login = {}  # usuario -> [timestamps de intentos fallidos]


def _login_bloqueado(usuario):
    ahora = datetime.now().timestamp()
    intentos = _intentos_login.get(usuario, [])
    intentos = [t for t in intentos if ahora - t < VENTANA_BLOQUEO_SEGUNDOS]
    _intentos_login[usuario] = intentos
    return len(intentos) >= MAX_INTENTOS_LOGIN


def _registrar_intento_fallido(usuario):
    ahora = datetime.now().timestamp()
    _intentos_login.setdefault(usuario, []).append(ahora)


def _limpiar_intentos(usuario):
    _intentos_login.pop(usuario, None)


# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------
def obtener_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


@app.teardown_appcontext
def cerrar_db(excepcion=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def inicializar_db():
    primera_vez = not os.path.exists(DB_PATH)
    conexion = sqlite3.connect(DB_PATH)
    conexion.executescript('''
        CREATE TABLE IF NOT EXISTS guias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero_guia TEXT NOT NULL UNIQUE,
            fecha TEXT NOT NULL,
            hora TEXT NOT NULL,
            estado TEXT NOT NULL DEFAULT 'Pendiente',
            rem_identificacion TEXT NOT NULL,
            rem_nombre TEXT NOT NULL,
            rem_telefono TEXT NOT NULL,
            rem_direccion TEXT NOT NULL,
            des_identificacion TEXT NOT NULL,
            des_nombre TEXT NOT NULL,
            des_telefono TEXT NOT NULL,
            des_direccion TEXT NOT NULL,
            forma_pago TEXT NOT NULL DEFAULT 'Contado',
            creado_en TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            nombre TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_guias_estado ON guias (estado);
        CREATE INDEX IF NOT EXISTS idx_guias_numero_guia ON guias (numero_guia);
    ''')

    if primera_vez:
        from werkzeug.security import generate_password_hash
        conexion.execute(
            'INSERT INTO usuarios (usuario, password, nombre) VALUES (?, ?, ?)',
            ('admin', generate_password_hash('admin123'), 'Administrador')
        )
        conexion.commit()
        print('Base de datos creada. Usuario por defecto -> admin / admin123')
        print('IMPORTANTE: cambia esta contraseña apenas inicies sesión.')

    conexion.close()


# ---------------------------------------------------------------------------
# Helpers de seguridad / validación
# ---------------------------------------------------------------------------
def limpiar(valor):
    if valor is None:
        return ''
    return str(valor).strip()


def requerir_sesion(funcion):
    @wraps(funcion)
    def envoltura(*args, **kwargs):
        if not session.get('usuario_id'):
            return jsonify({'exito': False, 'mensaje': 'Sesión no válida. Inicia sesión nuevamente.'}), 401
        return funcion(*args, **kwargs)
    return envoltura


def requerir_token_interno(funcion):
    """Protege la API interna que usa servidor_publico.py para mandar guías."""
    @wraps(funcion)
    def envoltura(*args, **kwargs):
        token = request.headers.get('X-Internal-Token', '')
        if token != INTERNAL_TOKEN:
            return jsonify({'exito': False, 'mensaje': 'Token interno no válido.'}), 403
        return funcion(*args, **kwargs)
    return envoltura


# ---------------------------------------------------------------------------
# Rutas de páginas (HTML en templates/, CSS/JS en static/)
# ---------------------------------------------------------------------------
@app.route('/')
def pagina_raiz():
    # Este servidor no tiene el formulario público, solo login/panel.
    return redirect('/login')


@app.route('/login')
def pagina_login():
    if session.get('usuario_id'):
        return redirect('/panel')
    return render_template('login.html')


@app.route('/panel')
def pagina_panel():
    if not session.get('usuario_id'):
        return redirect('/login')
    return render_template('panel.html')


# ---------------------------------------------------------------------------
# API: autenticación
# ---------------------------------------------------------------------------
@app.route('/api/login', methods=['POST'])
def api_login():
    from werkzeug.security import check_password_hash

    datos = request.get_json(silent=True) or {}
    usuario = limpiar(datos.get('usuario'))
    password = datos.get('password') or ''

    if not usuario or not password:
        return jsonify({'exito': False, 'mensaje': 'Completa usuario y contraseña.'}), 400

    if _login_bloqueado(usuario):
        return jsonify({
            'exito': False,
            'mensaje': f'Demasiados intentos fallidos. Espera {VENTANA_BLOQUEO_SEGUNDOS // 60} minutos e intenta de nuevo.'
        }), 429

    db = obtener_db()
    fila = db.execute('SELECT id, usuario, password, nombre FROM usuarios WHERE usuario = ?', (usuario,)).fetchone()

    if fila and check_password_hash(fila['password'], password):
        _limpiar_intentos(usuario)
        session.clear()
        session.permanent = True
        session['usuario_id'] = fila['id']
        session['usuario_nombre'] = fila['nombre']
        return jsonify({'exito': True, 'nombre': fila['nombre']})

    _registrar_intento_fallido(usuario)
    return jsonify({'exito': False, 'mensaje': 'Usuario o contraseña incorrectos.'}), 401


@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'exito': True})


@app.route('/api/sesion')
def api_sesion():
    if session.get('usuario_id'):
        return jsonify({'exito': True, 'nombre': session.get('usuario_nombre')})
    return jsonify({'exito': False}), 401


# ---------------------------------------------------------------------------
# API INTERNA: recibe guías que le manda servidor_publico.py
# ---------------------------------------------------------------------------
@app.route('/api/interno/guardar_guia', methods=['POST'])
@requerir_token_interno
def api_interno_guardar_guia():
    datos = request.get_json(silent=True) or {}

    rem_identificacion = limpiar(datos.get('rem_identificacion'))
    rem_nombre = limpiar(datos.get('rem_nombre'))
    rem_telefono = limpiar(datos.get('rem_telefono'))
    rem_direccion = limpiar(datos.get('rem_direccion'))

    des_identificacion = limpiar(datos.get('des_identificacion'))
    des_nombre = limpiar(datos.get('des_nombre'))
    des_telefono = limpiar(datos.get('des_telefono'))
    des_direccion = limpiar(datos.get('des_direccion'))

    forma_pago = limpiar(datos.get('forma_pago'))

    campos_obligatorios = {
        'Identificación del remitente': rem_identificacion,
        'Nombre del remitente': rem_nombre,
        'Teléfono del remitente': rem_telefono,
        'Dirección del remitente': rem_direccion,
        'Identificación del destinatario': des_identificacion,
        'Nombre del destinatario': des_nombre,
        'Teléfono del destinatario': des_telefono,
        'Dirección del destinatario': des_direccion,
    }

    errores = []
    for etiqueta, valor in campos_obligatorios.items():
        if not valor:
            errores.append(f'El campo "{etiqueta}" es obligatorio.')
        elif len(valor) > 255:
            errores.append(f'El campo "{etiqueta}" es demasiado largo.')

    if forma_pago not in FORMAS_PAGO_VALIDAS:
        errores.append('La forma de pago seleccionada no es válida.')

    if errores:
        return jsonify({'exito': False, 'mensaje': ' '.join(errores)}), 422

    ahora = datetime.now()
    fecha = ahora.strftime('%Y-%m-%d')
    hora = ahora.strftime('%H:%M:%S')
    estado = 'Pendiente'

    db = obtener_db()
    cursor = db.execute('''
        INSERT INTO guias (
            numero_guia, fecha, hora, estado,
            rem_identificacion, rem_nombre, rem_telefono, rem_direccion,
            des_identificacion, des_nombre, des_telefono, des_direccion,
            forma_pago
        ) VALUES ('000000', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        fecha, hora, estado,
        rem_identificacion, rem_nombre, rem_telefono, rem_direccion,
        des_identificacion, des_nombre, des_telefono, des_direccion,
        forma_pago,
    ))

    nuevo_id = cursor.lastrowid
    numero_guia = str(nuevo_id).zfill(6)
    db.execute('UPDATE guias SET numero_guia = ? WHERE id = ?', (numero_guia, nuevo_id))
    db.commit()

    return jsonify({
        'exito': True,
        'mensaje': 'Guía guardada correctamente.',
        'numero_guia': numero_guia,
        'fecha': fecha,
        'hora': hora,
        'estado': estado,
    })


# ---------------------------------------------------------------------------
# API INTERNA: consultar el estado de una guía por su número
# (la usa servidor_publico.py para mostrar el seguimiento en tiempo real
#  a la persona que envió o va a recibir la guía)
# ---------------------------------------------------------------------------
@app.route('/api/interno/estado_guia/<numero_guia>')
@requerir_token_interno
def api_interno_estado_guia(numero_guia):
    numero_guia = limpiar(numero_guia)
    db = obtener_db()
    fila = db.execute('''
        SELECT numero_guia, fecha, hora, estado, rem_nombre, des_nombre, forma_pago
        FROM guias WHERE numero_guia = ?
    ''', (numero_guia,)).fetchone()

    if not fila:
        return jsonify({'exito': False, 'mensaje': 'No existe ninguna guía con ese número.'}), 404

    return jsonify({'exito': True, 'guia': dict(fila)})


# ---------------------------------------------------------------------------
# API: listar / buscar guías + estadísticas (panel)
# ---------------------------------------------------------------------------
@app.route('/api/buscar')
@requerir_sesion
def api_buscar():
    q = limpiar(request.args.get('q'))
    estado_filtro = limpiar(request.args.get('estado'))

    try:
        pagina = max(1, int(request.args.get('pagina', 1)))
    except (TypeError, ValueError):
        pagina = 1
    tamano_pagina = 50
    offset = (pagina - 1) * tamano_pagina

    condiciones = []
    parametros = []

    if q:
        condiciones.append('(numero_guia LIKE ? OR rem_nombre LIKE ? OR des_nombre LIKE ?)')
        comodin = f'%{q}%'
        parametros.extend([comodin, comodin, comodin])

    if estado_filtro in ESTADOS_VALIDOS:
        condiciones.append('estado = ?')
        parametros.append(estado_filtro)

    where_sql = (' WHERE ' + ' AND '.join(condiciones)) if condiciones else ''

    db = obtener_db()

    total_filtrado = db.execute(
        f'SELECT COUNT(*) as total FROM guias{where_sql}', parametros
    ).fetchone()['total']

    sql = (
        'SELECT id, numero_guia, fecha, hora, estado, rem_nombre, des_nombre FROM guias'
        + where_sql + ' ORDER BY id DESC LIMIT ? OFFSET ?'
    )
    filas = db.execute(sql, parametros + [tamano_pagina, offset]).fetchall()
    guias = [dict(fila) for fila in filas]

    conteos = {estado: 0 for estado in ESTADOS_VALIDOS}
    for fila in db.execute('SELECT estado, COUNT(*) as total FROM guias GROUP BY estado').fetchall():
        if fila['estado'] in conteos:
            conteos[fila['estado']] = fila['total']

    return jsonify({
        'exito': True,
        'guias': guias,
        'paginacion': {
            'pagina': pagina,
            'tamano_pagina': tamano_pagina,
            'total_filtrado': total_filtrado,
            'total_paginas': max(1, -(-total_filtrado // tamano_pagina)),
        },
        'estadisticas': {
            'total': sum(conteos.values()),
            'pendientes': conteos['Pendiente'],
            'recibidas': conteos['Recibida'],
            'en_proceso': conteos['En proceso'],
            'entregadas': conteos['Entregada'],
        }
    })


# ---------------------------------------------------------------------------
# API: detalle de una guía
# ---------------------------------------------------------------------------
@app.route('/api/detalle/<int:guia_id>')
@requerir_sesion
def api_detalle(guia_id):
    db = obtener_db()
    fila = db.execute('SELECT * FROM guias WHERE id = ?', (guia_id,)).fetchone()

    if not fila:
        return jsonify({'exito': False, 'mensaje': 'La guía no existe.'}), 404

    return jsonify({'exito': True, 'guia': dict(fila)})


# ---------------------------------------------------------------------------
# API: actualizar estado / eliminar guía
# ---------------------------------------------------------------------------
@app.route('/api/actualizar_estado', methods=['POST'])
@requerir_sesion
def api_actualizar_estado():
    datos = request.get_json(silent=True) or {}

    try:
        guia_id = int(datos.get('id'))
    except (TypeError, ValueError):
        return jsonify({'exito': False, 'mensaje': 'Solicitud no válida.'}), 400

    accion = limpiar(datos.get('accion'))

    acciones_validas = {
        'marcar_recibida': 'Recibida',
        'marcar_en_proceso': 'En proceso',
        'marcar_entregada': 'Entregada',
        'eliminar': None,
    }

    if accion not in acciones_validas:
        return jsonify({'exito': False, 'mensaje': 'Solicitud no válida.'}), 400

    db = obtener_db()
    existe = db.execute('SELECT id FROM guias WHERE id = ?', (guia_id,)).fetchone()
    if not existe:
        return jsonify({'exito': False, 'mensaje': 'La guía no existe.'}), 404

    if accion == 'eliminar':
        db.execute('DELETE FROM guias WHERE id = ?', (guia_id,))
        db.commit()
        return jsonify({'exito': True, 'mensaje': 'Guía eliminada correctamente.'})

    nuevo_estado = acciones_validas[accion]
    db.execute('UPDATE guias SET estado = ? WHERE id = ?', (nuevo_estado, guia_id))
    db.commit()
    return jsonify({'exito': True, 'mensaje': 'Estado actualizado.', 'estado': nuevo_estado})


# ---------------------------------------------------------------------------
def iniciar_servidor():
    app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False, threaded=True)


if __name__ == '__main__':
    inicializar_db()
    print('Servidor ADMIN (login + panel) corriendo en http://192.168.1.9:5001 (también en http://localhost:5001)')
    hilo_servidor = threading.Thread(target=iniciar_servidor, daemon=True)
    hilo_servidor.start()
    # Abre una ventana de app de escritorio (no una pestaña del navegador)
    webview.create_window('Guía Interrapidísimo - Admin', 'http://192.168.1.9:5001/login', width=1100, height=850)
    webview.start()
