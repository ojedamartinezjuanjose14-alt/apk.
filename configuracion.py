"""
configuracion.py
Maneja las claves/tokens secretos (FLASK_SECRET_KEY, INTERNAL_TOKEN) sin
que tengas que escribirlos a mano ni dejarlos fijos en el código.

Cómo funciona, en orden:
  1. Si existe la variable de entorno, se usa esa (útil en un servidor real
     de producción, donde sí quieres controlar el valor tú mismo).
  2. Si no existe, se busca un archivo local en la carpeta .secretos/
     (al lado de guias.db). Si ya existe, se reutiliza ese valor.
  3. Si tampoco existe el archivo, se genera un valor aleatorio nuevo y se
     guarda ahí para la próxima vez.

Como servidor_admin.py y servidor_publico.py corren desde la misma carpeta
del proyecto, los dos leen/escriben el mismo archivo .secretos/internal_token.txt
y por lo tanto siempre coinciden sin que tengas que copiar y pegar nada.

Si subes este proyecto a un repositorio (Git), agrega ".secretos/" a tu
.gitignore para no publicar estos valores por accidente.
"""

import os
import secrets


def obtener_secreto(nombre_archivo, variable_entorno, base_dir):
    valor_env = os.environ.get(variable_entorno)
    if valor_env:
        return valor_env

    carpeta_secretos = os.path.join(base_dir, '.secretos')
    ruta = os.path.join(carpeta_secretos, nombre_archivo)

    if os.path.exists(ruta):
        with open(ruta, 'r', encoding='utf-8') as f:
            valor = f.read().strip()
            if valor:
                return valor

    # No existe todavía: generamos uno nuevo y lo guardamos.
    os.makedirs(carpeta_secretos, exist_ok=True)
    valor_nuevo = secrets.token_hex(32)
    with open(ruta, 'w', encoding='utf-8') as f:
        f.write(valor_nuevo)

    # Permisos restrictivos en Linux/Mac (en Windows no aplica, no falla).
    try:
        os.chmod(ruta, 0o600)
    except (OSError, NotImplementedError):
        pass

    print(f'[configuracion] Se generó y guardó un nuevo valor en {ruta}')
    return valor_nuevo
