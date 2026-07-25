"""
servidor_publico.py
Servidor PÚBLICO — página web con el formulario para crear guías.

Este es para los CLIENTES: lo abren desde un navegador (computador o
celular, con la URL o un QR), no es una app que se instale. No toca
guias.db ni tiene login. Cuando alguien envía el formulario, este
servidor valida los datos y se los manda por HTTP al servidor admin
(servidor_admin.py) usando un token secreto interno (INTERNAL_TOKEN),
que se genera y comparte solo (ver configuracion.py).

El HTML vive en templates/ y el CSS/JS en static/ (Flask los sirve solo).
No hay HTML embebido en este archivo: así el frontend queda en un único
lugar y no se puede desincronizar.

Cómo correrlo (necesitas los dos servidores corriendo a la vez, desde la
misma carpeta del proyecto):
    Terminal 1: python servidor_admin.py     (abre la app de escritorio del empleado)
    Terminal 2: python servidor_publico.py   (deja la página web corriendo)

Luego los clientes abren, desde cualquier navegador:
    http://<ip-de-esta-máquina>:5000/

Si el cliente está en el mismo computador: http://localhost:5000/
Si está en otro dispositivo de la misma red (celular, otro PC): usa la IP
local de esta máquina en vez de "localhost" (este servidor ya escucha en
todas las interfaces de red, 0.0.0.0).

Sobre el token secreto (INTERNAL_TOKEN):
    No tienes que configurar nada. Se genera solo la primera vez que corres
    cualquiera de los dos servidores y queda guardado en .secretos/ (junto
    a guias.db). Como los dos servidores corren desde la misma carpeta,
    leen el mismo archivo y siempre coinciden. Si quieres controlar tú el
    valor, define la variable de entorno INTERNAL_TOKEN (igual en ambos
    servidores) antes de arrancar; tendrá prioridad sobre el archivo.

Variables de entorno opcionales:
    ADMIN_URL        URL del servidor admin (por defecto http://192.168.1.9:5001)
"""

import os
import socket
import threading
import webbrowser

import requests
from flask import Flask, jsonify, render_template, request

from configuracion import obtener_secreto

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)

# Debe coincidir con el de servidor_admin.py. Como ambos leen/generan el
# mismo archivo en .secretos/, esto ocurre automáticamente sin configurar nada.
INTERNAL_TOKEN = obtener_secreto('internal_token.txt', 'INTERNAL_TOKEN', BASE_DIR)

# Dirección del servidor admin. Cámbiala si lo corres en otra máquina/puerto.
ADMIN_URL = os.environ.get('ADMIN_URL', 'http://192.168.1.9:5001')

FORMAS_PAGO_VALIDAS = ['Contado', 'Al cobro', 'Contra Entrega']


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def limpiar(valor):
    if valor is None:
        return ''
    return str(valor).strip()


# ---------------------------------------------------------------------------
# Rutas de páginas (HTML en templates/, CSS/JS en static/)
# ---------------------------------------------------------------------------
@app.route('/')
def pagina_index():
    return render_template('index.html', admin_login_url=f'{ADMIN_URL}/login')


# ---------------------------------------------------------------------------
# API: guardar guía -> valida aquí y la reenvía al servidor admin
# ---------------------------------------------------------------------------
@app.route('/api/guardar_guia', methods=['POST'])
def api_guardar_guia():
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

    payload = {
        'rem_identificacion': rem_identificacion,
        'rem_nombre': rem_nombre,
        'rem_telefono': rem_telefono,
        'rem_direccion': rem_direccion,
        'des_identificacion': des_identificacion,
        'des_nombre': des_nombre,
        'des_telefono': des_telefono,
        'des_direccion': des_direccion,
        'forma_pago': forma_pago,
    }

    try:
        respuesta = requests.post(
            f'{ADMIN_URL}/api/interno/guardar_guia',
            json=payload,
            headers={'X-Internal-Token': INTERNAL_TOKEN},
            timeout=10,
        )
    except requests.exceptions.RequestException:
        return jsonify({
            'exito': False,
            'mensaje': 'No se pudo contactar al servidor de administración. Intenta de nuevo más tarde.'
        }), 502

    # Reenviamos al navegador la misma respuesta (éxito o error) que dio el admin.
    return jsonify(respuesta.json()), respuesta.status_code


# ---------------------------------------------------------------------------
# API: consultar estado de una guía -> se lo pide al servidor admin
# ---------------------------------------------------------------------------
@app.route('/api/estado_guia/<numero_guia>')
def api_estado_guia(numero_guia):
    numero_guia = limpiar(numero_guia)
    if not numero_guia:
        return jsonify({'exito': False, 'mensaje': 'Número de guía no válido.'}), 400

    try:
        respuesta = requests.get(
            f'{ADMIN_URL}/api/interno/estado_guia/{numero_guia}',
            headers={'X-Internal-Token': INTERNAL_TOKEN},
            timeout=10,
        )
    except requests.exceptions.RequestException:
        return jsonify({
            'exito': False,
            'mensaje': 'No se pudo contactar al servidor de administración. Intenta de nuevo más tarde.'
        }), 502

    return jsonify(respuesta.json()), respuesta.status_code


# ---------------------------------------------------------------------------
def _obtener_ip_local():
    """Mejor esfuerzo para mostrarle al usuario la IP a compartir con clientes."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return '127.0.0.1'


def _abrir_navegador():
    """Abre la página pública (ya decorada) en el navegador por defecto,
    apenas el servidor lleva un momento arriba."""
    webbrowser.open('http://localhost:5000/')


if __name__ == '__main__':
    ip_local = _obtener_ip_local()
    print('Servidor PÚBLICO (formulario para clientes) corriendo.')
    print('  - En este mismo computador: http://localhost:5000/')
    print('  - Desde otro dispositivo de la misma red (celular, etc.): http://192.168.1.9:5000/')
    if ip_local != '192.168.1.9':
        print(f'  (Aviso: la IP detectada ahora mismo es {ip_local}. Si cambió, actualiza el 192.168.1.9 en este archivo.)')
    print(f'Enviará las guías al servidor admin en: {ADMIN_URL}')

    # Abre el navegador solo (variable ABRIR_NAVEGADOR=0 para desactivarlo,
    # por ejemplo si corres esto en un servidor sin pantalla).
    if os.environ.get('ABRIR_NAVEGADOR', '1') == '1':
        threading.Timer(1.2, _abrir_navegador).start()

    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, threaded=True)

