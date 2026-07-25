"""
iniciar_todo.py
Corre servidor_admin.py y servidor_publico.py AL MISMO TIEMPO con un
solo comando, cada uno en su propio proceso (así la ventana de escritorio
del admin no bloquea la página del público, ni al revés).

Uso:
    python iniciar_todo.py

Al cerrar la ventana del admin (o presionar Ctrl+C en esta terminal),
el servidor público también se apaga solo.
"""

import os
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable


def main():
    print('=' * 70)
    print('Iniciando Guía Interrapidísimo (los dos servidores a la vez)...')
    print('=' * 70)

    # 1) Servidor admin primero: crea/inicializa guias.db y genera las
    #    claves secretas en .secretos/ si todavía no existen. El servidor
    #    público las necesita, por eso arranca un momento después.
    proceso_admin = subprocess.Popen(
        [PYTHON, os.path.join(BASE_DIR, 'servidor_admin.py')],
        cwd=BASE_DIR,
    )

    time.sleep(1.5)

    # 2) Servidor público: su propio navegador se abre solo.
    proceso_publico = subprocess.Popen(
        [PYTHON, os.path.join(BASE_DIR, 'servidor_publico.py')],
        cwd=BASE_DIR,
    )

    try:
        # Se queda esperando mientras la ventana del admin esté abierta.
        proceso_admin.wait()
    except KeyboardInterrupt:
        print('\nCerrando...')
    finally:
        for proceso in (proceso_publico, proceso_admin):
            if proceso.poll() is None:
                proceso.terminate()
                try:
                    proceso.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proceso.kill()
        print('Los dos servidores se cerraron.')


if __name__ == '__main__':
    main()
