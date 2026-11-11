# CLIPPY-CYBERPUNK · Help Desk L1 (Windows)

## Contenido
- clippy_cyberpunk.py : la aplicación
- requirements.txt    : dependencias (anthropic)
- INICIAR.bat         : instala dependencias y abre la app

## Uso
1. Instala Python 3.10+ (marca "Add to PATH").
2. Haz clic derecho en INICIAR.bat > "Ejecutar como administrador"
   (necesario para reiniciar servicios).
3. Pega tu API key de Anthropic cuando la pida
   (o defínela antes en la variable ANTHROPIC_API_KEY).

## Seguridad (aplicada en el código)
- Solo diagnósticos de lectura: ipconfig, ping, servicios, eventos, disco.
- Solo reinicia: Audiosrv, AudioEndpointBuilder, Spooler, Dnscache, WlanSvc
  (editable en SERVICIOS_SEGUROS).
- Tras 2 intentos fallidos se bloquean las acciones y se genera el
  Reporte de Escalamiento a L2.
- Botón "Nueva incidencia" reinicia el contador.
