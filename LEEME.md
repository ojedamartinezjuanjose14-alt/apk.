# Guía Interrapidísimo — v3 (corregida)

Dos programas separados que se hablan por HTTP:

- **servidor_admin.py** → APP de escritorio para el empleado (se abre en su
  propia ventana con pywebview). Aquí se hace login y se ve/gestiona el
  panel de guías. Es el único que toca `guias.db`.
- **servidor_publico.py** → PÁGINA WEB para el cliente. La abre desde
  cualquier navegador (computador o celular), no se instala nada. Cuando
  el cliente llena el formulario, este servidor le manda los datos al
  admin por HTTP usando un token secreto que los dos comparten solos.

## Qué estaba roto y qué se arregló

1. **La página pública no se veía / el panel del admin daba error al
   abrir.** Causa real: a los dos servidores les faltaban por completo las
   carpetas `templates/` y `static/` (el HTML, CSS y JS del proyecto). Sin
   esos archivos, Flask no tiene qué mostrar y revienta con
   `TemplateNotFound` apenas alguien entra a `/`, `/login` o `/panel`. Se
   construyeron de cero: `templates/index.html`, `templates/login.html`,
   `templates/panel.html`, y todo `static/css/` y `static/js/`, con diseño
   propio de nivel profesional (no plantillas genéricas).

2. **Bug al eliminar una guía que ya no existe: el panel se quedaba
   "trabado" y no dejaba hacer nada más.** El backend (`servidor_admin.py`)
   ya respondía correctamente con un `404` y un mensaje claro; el problema
   estaba en que no había una interfaz que manejara bien ese caso. El nuevo
   `static/js/panel.js` envuelve **todas** las acciones (cambiar estado,
   eliminar) en `try / catch / finally`, así que pase lo que pase —éxito,
   guía inexistente, o falla de red— los botones y modales del panel
   **siempre** vuelven a quedar habilitados. Si intentas eliminar una guía
   que ya no existe, ahora simplemente aparece un aviso ("Esa guía ya no
   existe...") y la tabla se refresca sola; puedes seguir trabajando sin
   recargar la página.

3. **Los dos servidores ahora se pueden levantar juntos, de una sola vez,
   y las páginas se abren solas.** Ver la sección "Correr" más abajo.

## Instalar (una sola vez)

```
pip install -r requirements.txt
```

## Correr — los dos servidores a la vez

**Opción más fácil (Windows): doble clic en `iniciar_todo.bat`.**
Abre las dos ventanas (admin y público) automáticamente, una detrás de
otra, cada una con su propia consola.

**Opción multiplataforma:**
```
python iniciar_todo.py
```
Esto levanta `servidor_admin.py` y, un segundo y medio después (el tiempo
que necesita para preparar `guias.db` y las claves secretas),
`servidor_publico.py`. Apenas arrancan:
- Se abre sola la ventana de escritorio del admin (login).
- Se abre solo el navegador con la página del cliente.

Si cierras la ventana del admin (o presionas Ctrl+C en la terminal donde
corriste `iniciar_todo.py`), el servidor público se cierra también.

**Opción manual (dos terminales, como antes):**
```
Terminal 1:  python servidor_admin.py       -> abre la app del empleado
Terminal 2:  python servidor_publico.py     -> deja la página web corriendo
```

Luego, desde cualquier navegador:
- `http://localhost:5000/` → página del cliente, en este mismo computador.
- `http://192.168.1.9:5000/` → la misma página, para compartir con
  clientes en la misma red (wifi de la oficina), desde su celular o su
  propio computador. Esa es la IP que aparece en tu adaptador de red
  actual.
- `http://192.168.1.9:5001/login` → login de empleados.

⚠️ Si tu IP cambia (por ejemplo, el router te asigna otra al reiniciar),
tienes que actualizar el `192.168.1.9` en `servidor_publico.py` (variable
`ADMIN_URL`) y en `servidor_admin.py` (donde abre la ventana y en los
mensajes). Corre `ipconfig` (Windows) para ver la IP actual.

Usuario del admin la primera vez: `admin` / `admin123` (cámbiala apenas
entres — de momento el cambio de contraseña no tiene pantalla propia en
el panel; si la necesitas, dime y la agrego).

## Claves secretas — no hay que configurar nada

`FLASK_SECRET_KEY` e `INTERNAL_TOKEN` se generan solos la primera vez que
corres cualquiera de los dos servidores, y quedan guardados en
`.secretos/` (al lado de `guias.db`). Los dos programas leen el mismo
archivo, así que siempre coinciden. Si subes esto a Git, agrega
`.secretos/` a tu `.gitignore`.

## Estructura

```
proyecto/
├── iniciar_todo.py        (arranca los dos servidores a la vez, multiplataforma)
├── iniciar_todo.bat        (arranca los dos servidores a la vez, Windows, doble clic)
├── servidor_admin.py       (app del empleado, puerto 5001)
├── servidor_publico.py     (página del cliente, puerto 5000)
├── configuracion.py        (genera/guarda las claves secretas solo)
├── guias.db
├── templates/
│   ├── index.html      (formulario del cliente + rastreo de guía)
│   ├── login.html      (login del empleado)
│   └── panel.html      (panel de guías del empleado)
└── static/
    ├── css/ (estilo.css → sitio público, panel.css → login + panel)
    └── js/  (main.js → sitio público, login.js, panel.js → panel admin)
```

## Qué se probó de verdad

Se corrieron los dos servidores Flask reales (con un cliente de pruebas,
sin simular nada) y se verificó:
- `GET /login`, `GET /panel` (con y sin sesión), `GET /` del público →
  las tres páginas cargan su HTML/CSS/JS sin errores.
- Login correcto e incorrecto.
- Crear una guía desde la API interna (lo que hace el formulario del
  cliente) → aparece en `/api/buscar` con sus estadísticas correctas.
- Cambiar el estado de una guía real.
- **Eliminar una guía que no existe → responde 404 con mensaje claro, y el
  panel sigue funcionando normalmente después (`/api/buscar` sigue
  respondiendo 200).**
- Eliminar una guía real y luego volver a intentar eliminarla (ya no
  existe) → mismo comportamiento correcto, sin romper nada.

## Otras características ya incluidas

- Límite de 5 intentos de login fallidos por usuario cada 5 minutos.
- Cookies de sesión con `HttpOnly` y `SameSite=Lax`.
- Paginación real en `/api/buscar`, con búsqueda por número de guía,
  remitente o destinatario, y filtro por estado (tocando las tarjetas de
  estadísticas o el selector).
- Índices en `guias.db` (`estado`, `numero_guia`).
- El enlace "Acceso empleados" en la página del cliente apunta a la URL
  real del admin.
- Rastreo de guía público (`/api/estado_guia/<numero>`), con su propia
  pestaña en la página del cliente.

## Si algo no arranca

Corre esto y mándame la salida completa:
```
python servidor_admin.py
```
