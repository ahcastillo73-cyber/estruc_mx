# estruc_mx

Herramienta de análisis estructural de edificios, multiplataforma (Linux, macOS y Windows), basada en motores abiertos y en la normativa mexicana (NTC 2023 y manuales CFE; AISC, ACI y FEMA donde haya lagunas). Es de uso propio.

Estado: **fase 0, prueba de concepto**. El plan completo está en el documento de viabilidad del proyecto.

## Qué hay ahora

- **Modelo de datos** (`src/estruc_mx/modelo`): materiales, secciones, nodos, barras, apoyos, patrones de carga, cargas nodales y distribuidas, y combinaciones. Se guarda en JSON y valida que todas las referencias existan. Incluye un generador de marcos regulares a partir de ejes y alturas de entrepiso.
- **Muros y losas** (`modelo/malla.py`, `analisis/areas.py`): cuadriláteros planos de cuatro nodos con sección de cáscara (material, espesor y factor de rigidez para agrietamiento). Cada uno se divide en elementos de hasta `tamano_malla` m; las áreas vecinas comparten nodos, las barras que pasan por la malla (dalas, castillos, vigas de borde) se parten para trabajar con ella y la base de un muro empotrado queda empotrada en toda su longitud. Ambos motores analizan la misma malla (PyNite con `Quad3D`, OpenSees con `ShellMITC4`). Resultados: fuerzas en la base de cada muro (P, V y M en el plano y fuera de él, como las *pier forces* de ETABS), en estático y en el modal espectral, y momentos por unidad de ancho en losas. Los patrones pueden aplicar el peso propio como carga (`peso_propio`, el CM del modelo nuevo lo trae en 1) sin contarlo dos veces en la masa.
- **Motor PyNite** (`motores/pynite.py`): análisis estático lineal dentro de la aplicación.
- **Motor OpenSees** (`motores/opensees.py`): genera un script OpenSeesPy legible y lo ejecuta en un proceso aparte. El script se puede exportar, editar y correr por separado.
- **Masas y espectro** (`modelo/masas.py`, `modelo/espectro.py`): masas nodales a partir de patrones de carga, peso propio y masas explícitas; espectro tabular (por ejemplo, el de SASID o PRODISIS) o paramétrico de las NTC Sismo.
- **Análisis modal espectral** (`analisis/espectral.py`): periodos, factores de participación, masa efectiva, combinación SRSS o CQC, cortante basal y derivas por nivel. Independiente del motor.
- **Aplicación de escritorio** (`app/`): ventana PySide6 con la vista VTK integrada; abre y guarda modelos, ejecuta análisis estático, modal y espectral con cualquiera de los dos motores sin bloquear la ventana, muestra tablas (resumen, desplazamientos, reacciones, modos, derivas) y la deformada o las formas modales con escala ajustable. Exporta el script OpenSeesPy. La lógica vive en `app/sesion.py`, que se prueba sin pantalla.
- **Edición del modelo** (`modelo/edicion.py`, `app/edicion.py`): modelo nuevo a partir de una rejilla de ejes y niveles (claros como «3x6, 8»), marco completo desde la rejilla, dibujo de barras, columnas, muros (dos clics arriba; baja al nivel de abajo) y losas (dos esquinas opuestas) con clics sobre nodos o cruces de ejes, losas en todos los tableros, selección en la vista 3D (Ctrl o Mayús para agregar) o en el explorador, panel de propiedades, borrar con Supr, apoyos, secciones, cargas en nodos, barras y áreas (kN/m²), y tablas de materiales, secciones, patrones y combinaciones (al renombrar se actualizan las referencias). Deshacer y rehacer con Ctrl+Z / Ctrl+Y. Cada cambio se valida completo antes de aplicarse y descarta los resultados anteriores. La rejilla se guarda en el JSON (`rejilla`), pero no entra en el análisis.
- **Revisión sísmica** (`analisis/revision_sismica.py`): sobre el modal espectral en X y Y, cortante basal mínimo (NTC: a_min según Ts y R; CFE: 0.8 del estático) con factor de escala para las fuerzas, centros de masa por nivel, torsión accidental como momento por piso resuelto con el mismo motor, combinación 100 % + 30 % de componentes ortogonales, distorsiones para Seguridad de Vida (γSV), Ocupación Inmediata (γOI, Grupo A) y Limitación de Daño (espectro elástico × Ks de la zona, Grupo B) y fuerzas sísmicas de diseño en muros. Los valores son de la NTC Sismo 2023 (`normas/ntc_sismo.py`, verificados contra el texto); los de CFE (`normas/cfe_sismo.py`) están sin verificar. El reporte muestra las fórmulas de referencia con su sección de la norma (`reporte/formulas.py`, reutilizable por las secciones futuras).
- **Replicar, diafragmas y edición de muros** (`modelo/edicion.py`, `modelo/diafragmas.py`): *Editar > Replicar selección* (Ctrl+R) copia nodos, barras, muros y losas a otros niveles de la rejilla o con un desplazamiento (dX, dY, dZ) repetido, con sus cargas, y los apoyos y masas de los nodos nuevos; lo que ya existe en el destino no se duplica. *Asignar > Diafragmas rígidos por nivel* (también al crear el modelo): cada nivel se mueve como cuerpo rígido en su plano con el nodo maestro en el centro de masa; OpenSees usa `rigidDiaphragm` y PyNite barras rígidas en el plano del piso, y ambos coinciden (1e-5 en el marco de prueba). El centro de masa de cada piso sale en la tabla «Diafragmas», en el reporte y con `modelo.diafragmas.centros_de_masa`; su desplazamiento, en la tabla de desplazamientos (nodo `<nivel>:CM`). Los muros se mueven o se cambian de altura desde el panel de propiedades, y *Editar > Dividir muro o losa* los parte en piezas (para huecos o para unirlos con nodos intermedios). En «Ver», *Cargas: <patrón>* dibuja las cargas en nodos, barras y áreas con flechas y valores.
- **Reporte** (`reporte/`): PDF o Word con datos del modelo, cargas y combinaciones, espectro, resultados modales, cortante basal, distorsiones contra los límites de las NTC y figuras de deformadas. Está hecho por bloques: cada sección es una función que devuelve títulos, párrafos, tablas y figuras, y los renderizadores PDF (ReportLab) y Word (python-docx) solo dibujan bloques. Para añadir una sección basta registrarla en `reporte/secciones.py`.
- **Vista 3D** (`visual/vista3d.py`): modelo y deformada con PyVista/VTK.
- **Ejemplos**: `ejemplos/marco_3niveles.json` y `ejemplos/casa_mamposteria.json` (dos niveles de mampostería confinada con castillos, dalas y losas); se regeneran con `python ejemplos/generar_ejemplos.py`.
- **Pruebas**: soluciones exactas, equilibrio y comparación PyNite contra OpenSees en un marco 3D de 3 niveles, con columnas giradas 0°, 30° y 90°. Ambos motores coinciden con tolerancia relativa de 1e-4, también en periodos, cortante basal y derivas del análisis espectral. Con muros y losas usan elementos de cáscara distintos sobre la misma malla: con malla de 0.5 m difieren menos de 3 % en desplazamientos, fuerzas en muros, periodos y cortante basal. Muro en voladizo, losa apoyada (Timoshenko) y equilibrio de las fuerzas en muros contra las cargas.

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
estruc-mx reporte ejemplos/marco_3niveles.json -o reporte.pdf --sistema marco_concreto_alta --zona B --ts 0.8
estruc-mx reporte ejemplos/marco_3niveles.json -o reporte.docx --secciones modelo,modal,derivas
estruc-mx reporte --sistemas   # sistemas estructurales y su distorsión límite

python -m pytest
```

## Instaladores

La CI genera tres instaladores con Python 3.12, OpenSeesPy, PyNite, el reporte y, cuando está en la rama, la ventana PySide6. No hace falta instalar Python en la otra máquina.

| Sistema | Archivo | Cómo se instala |
|---|---|---|
| Linux x86_64 | `estruc-mx-<versión>-x86_64.AppImage` | `chmod +x` y doble clic, o `./estruc-mx-….AppImage` |
| macOS Apple Silicon | `estruc-mx-<versión>-macos-arm64.dmg` | Arrastrar `estruc-mx.app` a Aplicaciones |
| Windows x64 | `estruc-mx-<versión>-windows-x64-instalador.exe` | Asistente; se instala para el usuario, sin permisos de administrador |
| Windows x64 | `estruc-mx-<versión>-windows-x64-portatil.zip` | Descomprimir y ejecutar `estruc-mx.exe` |

**Dónde descargarlos.** Al publicar una etiqueta, por ejemplo `git tag v0.1.0 && git push origin v0.1.0`, el flujo *Instaladores* crea un Release con los cuatro archivos. También se puede lanzar a mano en *Actions → Instaladores → Run workflow*; los archivos quedan como artefactos de esa ejecución durante 30 días.

**Uso.** Sin argumentos, o con un archivo `.json`, se abre la ventana (si no está incluida, se muestra la ayuda). Con una orden se comporta como `estruc-mx`: `./estruc-mx-….AppImage reporte modelo.json -o reporte.pdf`. En Windows la línea de comandos es `estruc-mx-cli.exe` (el instalador ofrece añadirlo al PATH); en macOS, `/Applications/estruc-mx.app/Contents/MacOS/estruc-mx`.

**Sin firma de código.** Los instaladores no están firmados. En macOS, la primera vez: clic derecho sobre la app → Abrir, o `xattr -dr com.apple.quarantine /Applications/estruc-mx.app`. En Windows, SmartScreen avisa: «Más información» → «Ejecutar de todas formas».

**Construir en local.** Con Python 3.12: `pip install ".[opensees,visual,reporte,gui]" pyinstaller`, `python empaquetado/iconos.py` y `pyinstaller --noconfirm empaquetado/estruc_mx.spec`; el resultado queda en `dist/`. Los scripts de `empaquetado/linux`, `macos` y `windows` hacen el último paso de cada sistema.

## Siguientes pasos de la fase 0

1. ~~Análisis modal y espectral en ambos motores.~~ Hecho; falta la forma paramétrica del espectro CFE.
2. ~~Muros como placas en PyNite.~~ Hecho en ambos motores, con dibujo en la ventana y en el reporte. Diafragma rígido hecho. Falta G = 0.2·Em de la mampostería (el modelo es isótropo).
3. ~~Ventana PySide6 con la vista VTK integrada.~~ Hecho, con edición del modelo (rejilla, dibujo, selección, propiedades, deshacer). Con replicar entre niveles, cargas dibujadas, diafragmas rígidos y edición de muros.
4. ~~Reporte mínimo.~~ Hecho en PDF y Word, con la revisión sísmica (cortante mínimo, torsión accidental, 100/30, distorsiones) de la NTC Sismo 2023.
5. ~~Instaladores automáticos para Linux (AppImage), macOS (.dmg) y Windows (.exe).~~ Hecho; sin firma de código.
