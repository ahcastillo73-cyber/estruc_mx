# estruc_mx

Herramienta de análisis estructural de edificios, multiplataforma (Linux, macOS y Windows), basada en motores abiertos y en la normativa mexicana (NTC 2023 y manuales CFE; AISC, ACI y FEMA donde haya lagunas). Es de uso propio.

Estado: **fase 0, prueba de concepto**. El plan completo está en el documento de viabilidad del proyecto.

## Qué hay ahora

- **Modelo de datos** (`src/estruc_mx/modelo`): materiales, secciones, nodos, barras, apoyos, patrones de carga, cargas nodales y distribuidas, y combinaciones. Se guarda en JSON y valida que todas las referencias existan. Incluye un generador de marcos regulares a partir de ejes y alturas de entrepiso.
- **Motor PyNite** (`motores/pynite.py`): análisis estático lineal dentro de la aplicación.
- **Motor OpenSees** (`motores/opensees.py`): genera un script OpenSeesPy legible y lo ejecuta en un proceso aparte. El script se puede exportar, editar y correr por separado.
- **Masas y espectro** (`modelo/masas.py`, `modelo/espectro.py`): masas nodales a partir de patrones de carga, peso propio y masas explícitas; espectro tabular (por ejemplo, el de SASID o PRODISIS) o paramétrico de las NTC Sismo.
- **Análisis modal espectral** (`analisis/espectral.py`): periodos, factores de participación, masa efectiva, combinación SRSS o CQC, cortante basal y derivas por nivel. Independiente del motor.
- **Aplicación de escritorio** (`app/`): ventana PySide6 con la vista VTK integrada; abre y guarda modelos, ejecuta análisis estático, modal y espectral con cualquiera de los dos motores sin bloquear la ventana, muestra tablas (resumen, desplazamientos, reacciones, modos, derivas) y la deformada o las formas modales con escala ajustable. Exporta el script OpenSeesPy. La lógica vive en `app/sesion.py`, que se prueba sin pantalla.
- **Edición del modelo** (`modelo/edicion.py`, `app/edicion.py`): modelo nuevo a partir de una rejilla de ejes y niveles (claros como «3x6, 8»), marco completo desde la rejilla, dibujo de barras y columnas con clics sobre nodos o cruces de ejes, selección en la vista 3D (Ctrl o Mayús para agregar) o en el explorador, panel de propiedades, borrar con Supr, apoyos, secciones, cargas en nodos y barras, y tablas de materiales, secciones, patrones y combinaciones (al renombrar se actualizan las referencias). Deshacer y rehacer con Ctrl+Z / Ctrl+Y. Cada cambio se valida completo antes de aplicarse y descarta los resultados anteriores. La rejilla se guarda en el JSON (`rejilla`), pero no entra en el análisis.
- **Reporte** (`reporte/`): PDF o Word con datos del modelo, cargas y combinaciones, espectro, resultados modales, cortante basal, distorsiones contra los límites de las NTC y figuras de deformadas. Está hecho por bloques: cada sección es una función que devuelve títulos, párrafos, tablas y figuras, y los renderizadores PDF (ReportLab) y Word (python-docx) solo dibujan bloques. Para añadir una sección basta registrarla en `reporte/secciones.py`.
- **Vista 3D** (`visual/vista3d.py`): modelo y deformada con PyVista/VTK.
- **Pruebas**: soluciones exactas, equilibrio y comparación PyNite contra OpenSees en un marco 3D de 3 niveles, con columnas giradas 0°, 30° y 90°. Ambos motores coinciden con tolerancia relativa de 1e-4, también en periodos, cortante basal y derivas del análisis espectral.

## Requisitos

Python 3.12 o posterior: OpenSeesPy 3.8, la primera versión con binarios para Windows, Linux y macOS con chip M, no se publica para versiones anteriores. En Windows el motor OpenSees funciona solo con Python 3.12, porque su binario está compilado contra esa versión; en Linux y macOS también funciona con 3.13. Los instaladores incluirán Python 3.12.

En Linux, Qt necesita algunas librerías del sistema (en Ubuntu: `sudo apt install libegl1 libxkbcommon-x11-0 libxcb-cursor0`). El instalador las incluirá.

## Convenciones

- Unidades: kN, m, kPa.
- Ejes globales: Z vertical hacia arriba.
- Ejes locales de barra: x de i a j. En vigas, y apunta hacia arriba y la inercia mayor (I33) resiste la gravedad. En columnas que suben, y = −X global. `rotacion` gira y, z alrededor de x.

## Uso

```bash
python -m pip install -e ".[dev,visual,gui,opensees,reporte]"

estruc-mx gui ejemplos/marco_3niveles.json      # aplicación de escritorio
estruc-mx gui                                   # y Archivo > Nuevo para empezar desde una rejilla

estruc-mx analizar ejemplos/marco_3niveles.json --motor pynite
estruc-mx analizar ejemplos/marco_3niveles.json --motor opensees
estruc-mx script ejemplos/marco_3niveles.json -o modelo_opensees.py
estruc-mx ver ejemplos/marco_3niveles.json --combinacion "1.1CM+SX"
estruc-mx modal ejemplos/marco_3niveles.json --modos 12 --motor opensees
estruc-mx espectral ejemplos/marco_3niveles.json --direccion X --metodo CQC
estruc-mx reporte ejemplos/marco_3niveles.json -o reporte.pdf --sistema marco_ductil_concreto
estruc-mx reporte ejemplos/marco_3niveles.json -o reporte.docx --secciones modelo,modal,derivas
estruc-mx reporte --sistemas   # sistemas estructurales y su distorsión límite

python -m pytest
```

## Siguientes pasos de la fase 0

1. ~~Análisis modal y espectral en ambos motores.~~ Hecho; falta la forma paramétrica del espectro CFE.
2. Muros como placas en PyNite.
3. ~~Ventana PySide6 con la vista VTK integrada.~~ Hecho, con edición del modelo (rejilla, dibujo, selección, propiedades, deshacer). Falta mostrar las cargas en la vista y la edición de muros.
4. ~~Reporte mínimo.~~ Hecho en PDF y Word; falta la revisión de limitación de daños (servicio) y el cortante mínimo de las NTC.
5. Instaladores automáticos para Linux (AppImage), macOS (.dmg) y Windows (.exe).
