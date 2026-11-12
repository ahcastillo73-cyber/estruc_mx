# Licencia de estruc_mx y avisos de terceros

## estruc_mx

Copyright (C) 2026 ahcastillo73-cyber y colaboradores de estruc_mx.

estruc_mx es software libre: puede redistribuirse y modificarse bajo los términos
de la Licencia Pública General de GNU publicada por la Free Software Foundation,
versión 3 o (a su elección) cualquier versión posterior (GPL-3.0-or-later). Se
distribuye con la esperanza de que sea útil, pero SIN NINGUNA GARANTÍA, ni siquiera
la garantía implícita de COMERCIABILIDAD o IDONEIDAD PARA UN PROPÓSITO PARTICULAR.
El texto completo está en el archivo `LICENSE`.

Los resultados de estruc_mx no sustituyen el criterio ni la responsabilidad del
ingeniero que firma un proyecto.

### Permiso adicional para OpenSees y OpenSeesPy (GPL 3, sección 7)

Como permiso adicional conforme a la sección 7 de la GPL versión 3, los titulares
de los derechos de estruc_mx autorizan a combinar estruc_mx con OpenSees u
OpenSeesPy (o versiones modificadas de ellos), ejecutarlos y distribuir la
combinación resultante, aunque la licencia de OpenSees u OpenSeesPy no sea
compatible con la GPL. Las partes que no son OpenSees ni OpenSeesPy siguen bajo la
GPL. Este permiso no cambia la licencia de OpenSees ni la de OpenSeesPy: quien
distribuya la combinación debe cumplir también los términos de esas licencias
(ver abajo). Quien modifique estruc_mx puede extender este permiso a su versión,
pero no está obligado a hacerlo.

## Componentes de terceros

estruc_mx se instala con `pip` como dependencias, y los instaladores (AppImage,
.dmg, .exe y .zip) incluyen copias de los componentes de esta lista. Cada uno
conserva su propia licencia; las copias completas viajan dentro del paquete de
cada componente (carpetas `*.dist-info` o el propio paquete).

### OpenSees y OpenSeesPy: uso no comercial

| Componente | Licencia |
|---|---|
| OpenSeesPy (`openseespy`, `openseespylinux`, `openseespymac`, `openseespywin`) | Propia: libre para investigación, educación y uso interno |
| OpenSees (dentro del binario de OpenSeesPy) | Propia de The Regents of the University of California (UC Berkeley): permite usar, copiar, modificar y distribuir con fines educativos, de investigación y sin fines de lucro; el uso o la redistribución comercial requiere permiso |

El aviso de OpenSeesPy dice textualmente:

> OpenSeesPy is free for research, education, and internal use. Commercial
> redistribution of OpenSeesPy, such as, but not limited to, an application or
> cloud-based service that uses import openseespy, requires a license similar to
> that required for commercial redistribution of OpenSees.exe. Contact Dr. Minjie
> Zhu (zhum@oregonstate.edu) for commercial licensing details.

En la práctica: estruc_mx y sus instaladores pueden usarse y compartirse
libremente para investigación, docencia y uso interno, pero **vender o
redistribuir comercialmente los instaladores, o un servicio que use el motor
OpenSees, requiere una licencia comercial de OpenSees/OpenSeesPy**. El motor PyNite
no tiene esa restricción; OpenSeesPy es una dependencia opcional (extra
`opensees`), y sin ella estruc_mx funciona con PyNite.

### Resto de componentes

| Componente | Licencia |
|---|---|
| PyNite (`PyNiteFEA`), Copyright (c) 2018 D. Craig Brinck | MIT |
| Python | PSF License |
| NumPy, SciPy | BSD-3-Clause |
| pydantic | MIT |
| prettytable | BSD-3-Clause |
| matplotlib | Licencia de Matplotlib (tipo PSF) |
| ReportLab | BSD-3-Clause |
| python-docx | MIT |
| lxml | BSD-3-Clause |
| Pillow | MIT-CMU (HPND) |
| PySide6 y Qt | LGPL-3.0 (se distribuyen como bibliotecas dinámicas separadas, que pueden sustituirse) |
| VTK | BSD-3-Clause |
| PyVista, pyvistaqt | MIT |
| Cargador de PyInstaller | GPL-2.0 con excepción para el cargador |

La lista refleja las dependencias directas y las principales indirectas; las
licencias exactas de cada versión incluida están en sus carpetas `*.dist-info`.
