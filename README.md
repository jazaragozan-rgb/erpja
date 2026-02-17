# JA · ERP — Sistema de Gestión

ERP local para freelance de ingeniería mecánica industrial. Desarrollado con Flask + SQLite.

## Módulos

- **CRM / Clientes** — Gestión comercial, presupuestos, historial de comunicaciones
- **Proyectos** — Seguimiento, registro de horas, Diagrama de Gantt, proveedores por proyecto
- **Facturación** — Facturas, control de cobros, resumen fiscal IVA/IRPF, generación PDF
- **Proveedores** — Red de subcontratación, pedidos, gastos

## Ejecutar en GitHub Codespaces

1. Clic en **Code → Codespaces → Create codespace on main**
2. Esperar ~1 minuto a que se prepare el entorno
3. En la terminal ejecutar:
   ```
   python app.py
   ```
4. Codespaces abrirá automáticamente el navegador con la app

## Ejecutar en local (Windows)

1. Instalar Python desde [python.org](https://python.org) marcando **"Add to PATH"**
2. Abrir `cmd` en la carpeta del proyecto
3. Ejecutar:
   ```
   pip install flask reportlab
   python app.py
   ```
4. Abrir `http://localhost:5000`

O simplemente hacer doble clic en `INICIAR_CRM.bat`

## Tecnología

- **Backend:** Python 3 + Flask
- **Base de datos:** SQLite (archivo `crm.db` local)
- **PDF:** ReportLab
- **Frontend:** HTML/CSS/JS vanilla
