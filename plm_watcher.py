"""
PLM Watch Folder Daemon — JA · ERP
Monitoriza carpetas de SolidWorks/AutoCAD y sincroniza cambios al ERP.

Uso:
    python plm_watcher.py

Requisitos:
    pip install watchdog requests

Este script se ejecuta en paralelo a app.py y envía cambios automáticamente.
"""

import time
import os
import sys
import hashlib
import logging
import sqlite3
import shutil
from datetime import datetime

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_OK = True
except ImportError:
    WATCHDOG_OK = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [PLM-WATCH] %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('plm_watcher')

# Ajusta esta ruta al directorio donde está tu ERP
ERP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ERP_DIR, 'crm.db')
VAULT_DIR = os.path.join(ERP_DIR, 'plm_vault')
os.makedirs(VAULT_DIR, exist_ok=True)

# Extensiones CAD soportadas
EXT_MAP = {
    '.sldprt': ('pieza',       'solidworks'),
    '.sldasm': ('ensamblaje',  'solidworks'),
    '.slddrw': ('plano',       'solidworks'),
    '.prt':    ('pieza',       'solidworks'),
    '.asm':    ('ensamblaje',  'solidworks'),
    '.drw':    ('plano',       'solidworks'),
    '.dwg':    ('plano',       'autocad'),
    '.dxf':    ('plano',       'autocad'),
    '.ipt':    ('pieza',       'autocad'),
    '.iam':    ('ensamblaje',  'autocad'),
    '.idw':    ('plano',       'autocad'),
    '.step':   ('pieza',       'otro'),
    '.stp':    ('pieza',       'otro'),
    '.iges':   ('pieza',       'otro'),
    '.stl':    ('pieza',       'otro'),
}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def calc_hash(filepath):
    try:
        h = hashlib.md5()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def next_codigo(conn, tipo):
    prefijos = {'pieza': 'PZA', 'ensamblaje': 'ENS', 'plano': 'PLN', 'otro': 'DOC'}
    pref = prefijos.get(tipo, 'DOC')
    row = conn.execute(
        "SELECT codigo FROM plm_documentos WHERE tipo=? ORDER BY id DESC LIMIT 1", (tipo,)
    ).fetchone()
    if row:
        try:
            num = int(row['codigo'].split('-')[-1]) + 1
        except Exception:
            num = 1
    else:
        num = 1
    return f"{pref}-{datetime.now().year}-{num:04d}"


def log_accion_db(conn, documento_id, accion, detalle=''):
    conn.execute(
        'INSERT INTO plm_log (documento_id, accion, detalle) VALUES (?,?,?)',
        (documento_id, accion, detalle)
    )


def process_file(filepath):
    """Procesa un archivo CAD detectado: crea o actualiza en BD."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in EXT_MAP:
        return

    tipo, software = EXT_MAP[ext]
    nuevo_hash = calc_hash(filepath)
    if not nuevo_hash:
        return

    nombre_sin_ext = os.path.splitext(os.path.basename(filepath))[0]
    conn = get_db()

    try:
        existing = conn.execute(
            "SELECT * FROM plm_documentos WHERE ruta_origen=?", (filepath,)
        ).fetchone()

        if existing:
            if existing['hash_md5'] != nuevo_hash:
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                vault_name = f"{existing['codigo']}_rev_{ts}{ext}"
                shutil.copy2(filepath, os.path.join(VAULT_DIR, vault_name))
                conn.execute(
                    '''UPDATE plm_documentos
                       SET hash_md5=?, archivo_vault=?, modificado=?, estado='en_diseno'
                       WHERE id=?''',
                    (nuevo_hash, vault_name, datetime.now().isoformat(), existing['id'])
                )
                log_accion_db(conn, existing['id'], 'WATCHER_CAMBIO',
                              f"Cambio detectado → {vault_name}")
                log.info(f"ACTUALIZADO: {nombre_sin_ext} [{existing['codigo']}]")
            else:
                log.debug(f"Sin cambios: {nombre_sin_ext}")
        else:
            codigo = next_codigo(conn, tipo)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            vault_name = f"{codigo}_{ts}{ext}"
            shutil.copy2(filepath, os.path.join(VAULT_DIR, vault_name))
            conn.execute(
                '''INSERT INTO plm_documentos
                   (codigo, nombre, tipo, software, ruta_origen, archivo_vault, hash_md5, estado)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (codigo, nombre_sin_ext, tipo, software,
                 filepath, vault_name, nuevo_hash, 'en_diseno')
            )
            doc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                '''INSERT INTO plm_revisiones (documento_id, revision, descripcion_cambio)
                   VALUES (?,?,?)''',
                (doc_id, 'A', 'Importado automáticamente por Watch Folder')
            )
            log_accion_db(conn, doc_id, 'WATCHER_NUEVO', f"Detectado: {filepath}")
            log.info(f"NUEVO: {nombre_sin_ext} → {codigo} [{software}]")

        conn.commit()
    except Exception as e:
        log.error(f"Error procesando {filepath}: {e}")
    finally:
        conn.close()


class CADFileHandler(FileSystemEventHandler):
    """Handler de eventos del sistema de archivos."""

    def _should_process(self, path):
        ext = os.path.splitext(path)[1].lower()
        return ext in EXT_MAP and os.path.isfile(path)

    def on_created(self, event):
        if not event.is_directory and self._should_process(event.src_path):
            # Pequeña espera para que el programa CAD termine de escribir
            time.sleep(1.5)
            process_file(event.src_path)

    def on_modified(self, event):
        if not event.is_directory and self._should_process(event.src_path):
            time.sleep(1.5)
            process_file(event.src_path)

    def on_moved(self, event):
        if not event.is_directory and self._should_process(event.dest_path):
            process_file(event.dest_path)


def get_watchfolders():
    """Obtiene carpetas activas de la BD."""
    try:
        conn = get_db()
        folders = conn.execute(
            "SELECT * FROM plm_watchfolders WHERE activa=1"
        ).fetchall()
        conn.close()
        return [(f['ruta'], f['software']) for f in folders]
    except Exception:
        return []


def main():
    if not WATCHDOG_OK:
        print("=" * 60)
        print("  ERROR: Instala watchdog primero:")
        print("  pip install watchdog")
        print("=" * 60)
        sys.exit(1)

    print("=" * 60)
    print("  JA · ERP — PLM Watch Folder Daemon")
    print("=" * 60)

    observer = Observer()
    handlers_activos = []

    folders = get_watchfolders()
    if not folders:
        log.warning("No hay watch folders configuradas en la BD.")
        log.warning("Añádelas desde el ERP en PLM → Watch Folders.")
    else:
        for ruta, software in folders:
            if os.path.exists(ruta):
                handler = CADFileHandler()
                observer.schedule(handler, ruta, recursive=True)
                handlers_activos.append(ruta)
                log.info(f"Monitorizando: {ruta} [{software or 'mixto'}]")
            else:
                log.warning(f"Carpeta no encontrada: {ruta}")

    observer.start()
    log.info("Watcher activo. Ctrl+C para detener.")

    try:
        check_interval = 30  # segundos entre re-lecturas de config
        elapsed = 0
        while True:
            time.sleep(1)
            elapsed += 1
            if elapsed >= check_interval:
                elapsed = 0
                # Recargar carpetas por si se añadieron nuevas desde el ERP
                nuevas = get_watchfolders()
                for ruta, software in nuevas:
                    if ruta not in handlers_activos and os.path.exists(ruta):
                        handler = CADFileHandler()
                        observer.schedule(handler, ruta, recursive=True)
                        handlers_activos.append(ruta)
                        log.info(f"Nueva carpeta añadida: {ruta}")
    except KeyboardInterrupt:
        log.info("Deteniendo watcher...")
        observer.stop()

    observer.join()
    log.info("Watcher detenido.")


if __name__ == '__main__':
    main()
