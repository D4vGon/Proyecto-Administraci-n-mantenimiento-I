import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
import os

# Configuración de la página
st.set_page_config(page_title="MantPro - Gestión de Mantenimiento", layout="wide", page_icon="🛠️")

# --- CREAR DIRECTORIO PARA SUBIDAS ---
if not os.path.exists("uploads"):
    os.makedirs("uploads")

# --- ESTILOS PERSONALIZADOS (CSS) ---
st.markdown("""
            ...
            
    <style>
    /* Estilo para el contenedor de métricas */
    [data-testid="stMetricValue"] {
        font-size: 28px;
        color: #0E1117;
    }
    
    /* Mejoras en las tarjetas de indicadores */
    div[data-testid="metric-container"] {
        background-color: #f8f9fa;
        border: 1px solid #e0e0e0;
        padding: 15px 20px;
        border-radius: 10px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
    }

    /* Estilo para los formularios */
    .stForm {
        background-color: #ffffff;
        padding: 2rem;
        border-radius: 15px;
        border: 1px solid #dce0e5;
    }
    
    /* Botones principales personalizados */
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.3s;
    }
    
    .stButton>button:hover {
        border-color: #ff4b4b;
        color: #ff4b4b;
    }
    </style>
    """, unsafe_allow_html=True)

# --- FUNCIONES DE BASE DE DATOS ---
def get_connection():
    """Establece la conexión y activa explícitamente las claves foráneas."""
    conn = sqlite3.connect('mantenimiento.db', check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Tabla de Activos
    cursor.execute('''CREATE TABLE IF NOT EXISTS activos (
                        id TEXT PRIMARY KEY,
                        nombre TEXT,
                        area TEXT,
                        tipo TEXT,
                        estado TEXT)''')
    
    # Tabla de Trabajos de Mantenimiento con ON DELETE CASCADE
    cursor.execute('''CREATE TABLE IF NOT EXISTS trabajos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        equipo_id TEXT,
                        tipo_mant TEXT,
                        fecha_inicio TIMESTAMP,
                        fecha_fin TIMESTAMP,
                        descripcion TEXT,
                        personal TEXT,
                        costo_repuestos REAL DEFAULT 0,
                        FOREIGN KEY(equipo_id) REFERENCES activos(id) ON DELETE CASCADE)''')
    
    # Tabla de Paros con ON DELETE CASCADE
    cursor.execute('''CREATE TABLE IF NOT EXISTS paros (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        equipo_id TEXT,
                        inicio_paro TIMESTAMP,
                        fin_paro TIMESTAMP,
                        causa TEXT,
                        FOREIGN KEY(equipo_id) REFERENCES activos(id) ON DELETE CASCADE)''')
    
    # Tabla de repuestos
    cursor.execute('''CREATE TABLE IF NOT EXISTS repuestos (
                        id TEXT PRIMARY KEY,
                        descripcion TEXT,
                        stock INTEGER,
                        costo_unitario REAL)''')
    
    # Tabla Detalle Repuestos
    cursor.execute('''CREATE TABLE IF NOT EXISTS detalle_repuestos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trabajo_id INTEGER,
                        repuesto_id TEXT,
                        cantidad INTEGER,
                        costo_total REAL,
                        FOREIGN KEY(trabajo_id) REFERENCES trabajos(id) ON DELETE CASCADE,
                        FOREIGN KEY(repuesto_id) REFERENCES repuestos(id) ON DELETE CASCADE)''')
    
    # Migraciones (por si ya tenías la BD creada antes y necesitas las nuevas columnas)
    try: 
        conn.execute("ALTER TABLE repuestos ADD COLUMN numero_parte TEXT")
    except:
        pass

    try:
        conn.execute("ALTER TABLE trabajos ADD COLUMN archivo_adjunto TEXT")
    except:
        pass
    
    # NUEVO
    try:
        conn.execute("ALTER TABLE trabajos ADD COLUMN tiempo_inter REAL")
    except:
        pass

    conn.commit()
    conn.close()

# --- FUNCIONES AUXILIARES ---
def generar_id_automatico(tipo_activo):
    prefijos = {"Motor": "MOT", "Bomba": "BOM", "Compresor": "COM", "Cinta Transportadora": "CIN", "Otro": "GEN"}
    prefijo = prefijos.get(tipo_activo, "GEN")
    
    conn = get_connection()
    # Consulta parametrizada para evitar inyección
    df = pd.read_sql("SELECT id FROM activos WHERE id LIKE ?", conn, params=(f"{prefijo}-%",))
    conn.close()
    
    if df.empty:
        return f"{prefijo}-001"
    else:
        nums = df['id'].str.extract(r'-(\d+)')[0].dropna().astype(int)
        if nums.empty:
            return f"{prefijo}-001"
        return f"{prefijo}-{(nums.max() + 1):03d}"

def guardar_archivo(archivo_subido, prefijo=""):
    if archivo_subido is not None:
        nombre_archivo = f"{prefijo}_{archivo_subido.name}"
        ruta = os.path.join("uploads", nombre_archivo)
        with open(ruta, "wb") as f:
            f.write(archivo_subido.getbuffer())
        return nombre_archivo
    return None

# --- LÓGICA DE CÁLCULO DE INDICADORES ---
def calcular_indicadores(equipo_id=None):
    conn = get_connection()

    query_trabajos = "SELECT * FROM trabajos"
    query_paros = "SELECT * FROM paros"
    
    if equipo_id:
        # Uso de parámetros para evitar inyección
        df_trabajos = pd.read_sql(query_trabajos + " WHERE equipo_id = ?", conn, params=(equipo_id,))
        df_paros = pd.read_sql(query_paros + " WHERE equipo_id = ?", conn, params=(equipo_id,))
    else:
        df_trabajos = pd.read_sql(query_trabajos, conn)
        df_paros = pd.read_sql(query_paros, conn)
    conn.close()

    if df_trabajos.empty and df_paros.empty:
        return (None, None, None)

    # Conversión a datetime con errors='coerce' y eliminación de NaT
    df_trabajos['fecha_inicio'] = pd.to_datetime(df_trabajos['fecha_inicio'], errors='coerce')
    df_trabajos['fecha_fin'] = pd.to_datetime(df_trabajos['fecha_fin'], errors='coerce')
    df_paros['inicio_paro'] = pd.to_datetime(df_paros['inicio_paro'], errors='coerce')
    df_paros['fin_paro'] = pd.to_datetime(df_paros['fin_paro'], errors='coerce')

    # Eliminar filas con fechas nulas
    df_trabajos = df_trabajos.dropna(subset=['fecha_inicio', 'fecha_fin'])
    df_paros = df_paros.dropna(subset=['inicio_paro', 'fin_paro'])

    # Tiempo Total de Paro (Horas)
    total_paro = 0
    num_fallas = 0
    if not df_paros.empty:
        df_paros['t_paro'] = (df_paros['fin_paro'] - df_paros['inicio_paro']).dt.total_seconds() / 3600
        total_paro = df_paros['t_paro'].sum()
        num_fallas = len(df_paros)

    # Ventana de tiempo real
    if not df_paros.empty and not df_trabajos.empty:
        inicio_estudio = min(df_paros['inicio_paro'].min(), df_trabajos['fecha_inicio'].min())
        fin_estudio = max(df_paros['fin_paro'].max(), df_trabajos['fecha_fin'].max())
    elif not df_paros.empty:
        inicio_estudio = df_paros['inicio_paro'].min()
        fin_estudio = df_paros['fin_paro'].max()
    elif not df_trabajos.empty:
        inicio_estudio = df_trabajos['fecha_inicio'].min()
        fin_estudio = df_trabajos['fecha_fin'].max()
    else:
        inicio_estudio = fin_estudio = pd.Timestamp.now()
    tiempo_total_estudio = (fin_estudio - inicio_estudio).total_seconds() / 3600
    if tiempo_total_estudio == 0:
        tiempo_total_estudio = 1  # evitar división por cero

    # Cálculo de indicadores
    mttr = total_paro / num_fallas if num_fallas > 0 else 0
    mtbf = (tiempo_total_estudio - total_paro) / num_fallas if num_fallas > 0 else tiempo_total_estudio
    disponibilidad = ((tiempo_total_estudio - total_paro) / tiempo_total_estudio) * 100
    frecuencia_fallos = num_fallas / (tiempo_total_estudio / 24) if tiempo_total_estudio > 0 else 0
    costo_total = df_trabajos['costo_repuestos'].sum() if not df_trabajos.empty else 0

    indicadores = {
        "MTBF (H)": round(mtbf, 2),
        "MTTR (H)": round(mttr, 2),
        "Disponibilidad (%)": round(disponibilidad, 2),
        "Frecuencia Fallos (f/día)": round(frecuencia_fallos, 4),
        "Horas Paro": round(total_paro, 2),
        "Costo Total ($)": round(costo_total, 2)
    }
    return (indicadores, df_trabajos, df_paros)



def cargar_datos_demo(cantidad_activos=12, trabajos_por_activo=8, paros_por_activo=4, limpiar_antes=False):
    """Carga datos de prueba realistas para validar KPIs, gráficas, filtros y tablas.

    - Si limpiar_antes=True, borra activos, trabajos, paros, repuestos y consumos previos.
    - Usa INSERT OR IGNORE para evitar errores si se ejecuta más de una vez.
    - Genera datos determinísticos para que los resultados sean repetibles.
    """
    from datetime import timedelta
    import random

    random.seed(2026)
    conn = get_connection()
    cursor = conn.cursor()

    if limpiar_antes:
        cursor.execute("DELETE FROM detalle_repuestos")
        cursor.execute("DELETE FROM trabajos")
        cursor.execute("DELETE FROM paros")
        cursor.execute("DELETE FROM repuestos")
        cursor.execute("DELETE FROM activos")
        conn.commit()

    tipos = ["Motor", "Bomba", "Compresor", "Cinta Transportadora"]
    prefijos = {"Motor": "MOT", "Bomba": "BOM", "Compresor": "COM", "Cinta Transportadora": "CIN"}
    areas = ["Producción", "Empaque", "Utilidades", "Tratamiento", "Calderas", "Refrigeración"]

    # Repuestos demo
    repuestos_demo = [
        ("REP-001", "SKF-6204", "Rodamiento rígido de bolas", 80, 25.0),
        ("REP-002", "SEL-MEC-01", "Sello mecánico", 45, 65.0),
        ("REP-003", "BANDA-A42", "Banda industrial A42", 35, 40.0),
        ("REP-004", "FILT-HID-10", "Filtro hidráulico", 60, 18.0),
        ("REP-005", "BREAKER-3P", "Breaker trifásico", 20, 95.0),
        ("REP-006", "ACOPLE-25", "Acople flexible", 25, 55.0),
        ("REP-007", "ACEITE-ISO68", "Aceite industrial ISO 68", 100, 12.0),
        ("REP-008", "VAR-2HP", "Variador de frecuencia 2 HP", 8, 280.0),
    ]
    for rid, nparte, desc, stock, costo in repuestos_demo:
        cursor.execute(
            "INSERT OR IGNORE INTO repuestos (id, numero_parte, descripcion, stock, costo_unitario) VALUES (?,?,?,?,?)",
            (rid, nparte, desc, stock, costo)
        )

    activos_generados = []
    contador_tipo = {tipo: 1 for tipo in tipos}
    for i in range(cantidad_activos):
        tipo = tipos[i % len(tipos)]
        aid = f"{prefijos[tipo]}-{contador_tipo[tipo]:03d}"
        contador_tipo[tipo] += 1
        nombre = f"{tipo} Demo {contador_tipo[tipo]-1:02d}"
        area = areas[i % len(areas)]
        estado = "Activo" if i % 7 != 0 else "Fuera de servicio"
        cursor.execute("INSERT OR IGNORE INTO activos VALUES (?,?,?,?,?)", (aid, nombre, area, tipo, estado))
        activos_generados.append(aid)

    fecha_base = datetime(2026, 1, 1, 8, 0, 0)
    tipos_mant = ["Preventivo", "Correctivo", "Predictivo"]
    descripciones = {
        "Preventivo": ["Lubricación general", "Cambio de filtros", "Ajuste de tensión", "Inspección programada"],
        "Correctivo": ["Cambio de rodamiento", "Reparación de fuga", "Cambio de sello mecánico", "Reparación eléctrica"],
        "Predictivo": ["Análisis vibracional", "Termografía", "Medición de corriente", "Ultrasonido"]
    }
    tecnicos = ["Luis Vargas", "Carlos Mora", "María López", "Andrés Solano", "Sofía Jiménez"]

    for idx, aid in enumerate(activos_generados):
        # Trabajos de mantenimiento
        for j in range(trabajos_por_activo):
            tipo_mant = tipos_mant[(j + idx) % len(tipos_mant)]
            inicio = fecha_base + timedelta(days=idx * 3 + j * 5, hours=(j * 2) % 10)
            if tipo_mant == "Correctivo":
                duracion = round(random.uniform(2.0, 9.0), 2)
            elif tipo_mant == "Preventivo":
                duracion = round(random.uniform(1.0, 4.0), 2)
            else:
                duracion = round(random.uniform(0.5, 2.5), 2)
            fin = inicio + timedelta(hours=duracion)
            costo_base = {"Preventivo": 60, "Correctivo": 180, "Predictivo": 45}[tipo_mant]
            costo = round(costo_base + random.uniform(0, 220), 2)
            desc = random.choice(descripciones[tipo_mant])
            personal = random.choice(tecnicos)
            cursor.execute(
                """INSERT INTO trabajos
                   (equipo_id, tipo_mant, fecha_inicio, fecha_fin, descripcion, personal, costo_repuestos, tiempo_inter, archivo_adjunto)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (aid, tipo_mant, inicio.strftime('%Y-%m-%d %H:%M:%S'), fin.strftime('%Y-%m-%d %H:%M:%S'), desc, personal, costo, duracion, None)
            )
            trabajo_id = cursor.lastrowid

            # Consumo de repuestos en algunos trabajos correctivos/preventivos
            if tipo_mant in ["Correctivo", "Preventivo"] and random.random() < 0.65:
                rep = random.choice(repuestos_demo)
                repuesto_id = rep[0]
                costo_unit = rep[4]
                cantidad = random.randint(1, 3)
                costo_total = round(cantidad * costo_unit, 2)
                cursor.execute(
                    "INSERT INTO detalle_repuestos (trabajo_id, repuesto_id, cantidad, costo_total) VALUES (?,?,?,?)",
                    (trabajo_id, repuesto_id, cantidad, costo_total)
                )
                cursor.execute("UPDATE repuestos SET stock = MAX(stock - ?, 0) WHERE id = ?", (cantidad, repuesto_id))

        # Paros/fallas por activo
        for k in range(paros_por_activo):
            inicio_paro = fecha_base + timedelta(days=idx * 4 + k * 11 + 2, hours=(k * 3 + idx) % 12)
            duracion_paro = round(random.uniform(1.0, 12.0), 2)
            fin_paro = inicio_paro + timedelta(hours=duracion_paro)
            causas = ["Falla de rodamiento", "Fuga", "Disparo de breaker", "Sobrecalentamiento", "Desalineación", "Daño en sello"]
            causa = random.choice(causas)
            cursor.execute(
                "INSERT INTO paros (equipo_id, inicio_paro, fin_paro, causa) VALUES (?,?,?,?)",
                (aid, inicio_paro.strftime('%Y-%m-%d %H:%M:%S'), fin_paro.strftime('%Y-%m-%d %H:%M:%S'), causa)
            )

    conn.commit()
    conn.close()
    return cantidad_activos, cantidad_activos * trabajos_por_activo, cantidad_activos * paros_por_activo

# --- INTERFAZ STREAMLIT ---
init_db()

# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:
    ruta_logo = os.path.join(os.path.dirname(__file__), "logo_tec.png")
    if os.path.exists(ruta_logo):
        st.image(ruta_logo, use_container_width=True)
    else:
        st.title("🎓 Adm. Mantenimiento I")
    
    st.markdown("---")
    st.title("Navegación")
    menu = st.radio("Ir a:", ["📊 Dashboard", "📋 Registro Activos", "🔧 Mantenimiento", "📦 Repuestos", "🔍 Base de datos"])
    st.markdown("---")
    st.info("Proyecto Final - TEC")

st.title("🛠️ MantPro: Gestión de Mantenimiento")

# =========================================================
# DASHBOARD
# =========================================================
if menu == "📊 Dashboard":
    st.header("Indicadores de Desempeño (KPIs)")
    
    conn = get_connection()
    df_activos = pd.read_sql("SELECT * FROM activos", conn)

    df_trab_global = pd.read_sql("SELECT costo_repuestos FROM trabajos", conn)
    costo_global = df_trab_global['costo_repuestos'].sum() if not df_trab_global.empty else 0
    
    st.info(f"💰 **Costo Total de Mantenimiento (Global de Planta):** ${costo_global:,.2f}")
    st.markdown("---")

    activos = pd.read_sql("SELECT id, nombre FROM activos", conn)
    conn.close()
    
    if df_activos.empty:
        st.info("No hay activos registrados. Por favor, registre un equipo primero.")
    else:
        col_sel, col_estado, col_manual = st.columns([2, 1, 1])
        
        with col_sel:
            selected_option = st.selectbox("Seleccione un equipo:", df_activos['id'] + " - " + df_activos['nombre'])
            eid = selected_option.split(" - ")[0]
            
        with col_estado:
            st.write("Estado Operativo:")
            estado_actual = df_activos.loc[df_activos['id'] == eid, 'estado'].values[0]
            
            nuevo_estado = st.radio("Modificar", ["Activo", "En Falla"], 
                                    index=0 if estado_actual == "Activo" else 1, horizontal=True, label_visibility="collapsed")
            
            if nuevo_estado != estado_actual:
                conn_upd = get_connection()
                conn_upd.execute("UPDATE activos SET estado = ? WHERE id = ?", (nuevo_estado, eid))
                conn_upd.commit()
                conn_upd.close()
                st.rerun()
                
            if nuevo_estado == "Activo":
                st.success("🟢 Equipo Operativo")
            else:
                st.error("🔴 Equipo Detenido (En Falla)")
                
        with col_manual:
            st.write("Documentación Técnica")
            archivos_equipo = []
            carpeta_uploads = "uploads"
        
            if os.path.exists(carpeta_uploads):
                for archivo in os.listdir(carpeta_uploads):
                    if f"OT_{eid}" in archivo or f"MANUAL_{eid}" in archivo:
                        archivos_equipo.append(archivo)
        
            if archivos_equipo:
                for archivo in archivos_equipo:
                    ruta_archivo = os.path.join(carpeta_uploads, archivo)
                    with open(ruta_archivo, "rb") as file:
                        file_bytes = file.read()  # Leer completamente antes de cerrar
                    st.download_button(
                        label=f"📄 {archivo}",
                        data=file_bytes,
                        file_name=archivo,
                        mime="application/octet-stream",
                        key=archivo
                    )
            else:
                st.info("No hay documentos asociados a este activo.")

        st.markdown("---")
        
        indicadores, df_trab, df_paros = calcular_indicadores(eid)
        
        if indicadores is not None:
            col1, col2, col3 = st.columns(3)
            col1.metric("MTBF (H)", f"{indicadores['MTBF (H)']} h", help="Tiempo medio entre fallos")
            col2.metric("MTTR (H)", f"{indicadores['MTTR (H)']} h", help="Tiempo medio de reparación")
            col3.metric("Disponibilidad", f"{indicadores['Disponibilidad (%)']}%")
            
            col4, col5, col6 = st.columns(3)
            col4.metric("Frecuencia de Fallos", f"{indicadores['Frecuencia Fallos (f/día)']} f/d")
            col5.metric("Total Paro", f"{indicadores['Horas Paro']} h")
            col6.metric("Costo Mantenimiento (Equipo)", f"${indicadores['Costo Total ($)']}")
            
            st.markdown("---")
            st.subheader("🧠 Interpretación Técnica")

            disp = indicadores['Disponibilidad (%)']
            if disp < 85:
                st.error("⚠️ Equipo crítico: baja disponibilidad operacional")
            elif disp < 95:
                st.warning("⚠️ Disponibilidad aceptable pero mejorable")
            else:
                st.success("✅ Excelente disponibilidad")
            st.subheader(f"{disp} %")

            if indicadores['MTBF (H)'] < 20:
                st.warning("⚠️ Alta frecuencia de fallos. Se recomienda fortalecer mantenimiento preventivo.")

            st.markdown("---")
            st.subheader("📊 Comparativa de Tiempos de Mantenimiento")
            
            if not df_trab.empty:
                df_trab['Horas'] = (df_trab['fecha_fin'] - df_trab['fecha_inicio']).dt.total_seconds() / 3600
                resumen_grafico = df_trab.groupby('tipo_mant')['Horas'].sum().reset_index()
                
                fig = px.bar(
                    resumen_grafico, 
                    x='tipo_mant', 
                    y='Horas',
                    color='tipo_mant',
                    title=f"Horas Totales por Tipo de Mantenimiento ({eid})",
                    labels={'tipo_mant': 'Tipo', 'Horas': 'Horas Totales'},
                    color_discrete_map={'Preventivo': '#2E86C1', 'Correctivo': '#E74C3C', 'Predictivo': '#27AE60'},
                    text_auto='.1f'
                )
                fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No hay registros de trabajos de mantenimiento para generar el gráfico.")
        else:
            st.warning("El equipo seleccionado no tiene datos de paros o trabajos registrados aún.")

# =========================================================
# ACTIVOS
# =========================================================
elif menu == "📋 Registro Activos":
    st.header("Registro de Nuevos Equipos")

    tipo = st.selectbox("1. Seleccione Tipo de Activo", ["Motor", "Bomba", "Compresor", "Cinta Transportadora", "Otro"])
    id_sugerido = generar_id_automatico(tipo)

    with st.form("form_activos"):
        st.write("2. Complete los datos del equipo")
        c1, c2 = st.columns(2)
        aid = c1.text_input("Código/ID Equipo", value=id_sugerido, help="Puede dejar el generado automáticamente o editarlo.")
        nombre = c2.text_input("Nombre del Equipo", placeholder="Ej: Bomba de Agua Principal")
        area = c1.text_input("Área o Proceso")
        estado = c2.selectbox("Estado Inicial", ["Activo", "Fuera de servicio"])
        manual_equipo = st.file_uploader("Manual / Plano del equipo", type=['pdf', 'png', 'jpg'])

        if st.form_submit_button("✅ Guardar Activo"):
            if aid and nombre:
                conn = get_connection()
                try:
                    conn.execute("INSERT INTO activos VALUES (?,?,?,?,?)", (aid, nombre, area, tipo, estado))
                    conn.commit()
                    if manual_equipo:
                        guardar_archivo(manual_equipo, prefijo=f"MANUAL_{aid}")
                    st.success(f"Equipo {nombre} ({aid}) registrado correctamente.")
                    st.balloons()
                except sqlite3.Error:
                    st.error(f"Error: El ID ya existe o hay un problema con la base de datos.")
                finally:
                    conn.close()
            else:
                st.warning("Por favor complete los campos obligatorios (ID y Nombre).")
    
    st.markdown("---")
    conn = get_connection()
    df = pd.read_sql("SELECT * FROM activos", conn)
    conn.close()
    st.dataframe(df, use_container_width=True)

# =========================================================
# MANTENIMIENTOS
# =========================================================
elif menu == "🔧 Mantenimiento":
    st.header("Registro de trabajos de mantenimiento")
    tab1, tab2 = st.tabs(["⚒️ Intervenciones", "🛑 Registro de Paros"])
    
    conn = get_connection()
    lista_activos = pd.read_sql("SELECT id, nombre FROM activos", conn)
    lista_opciones = (lista_activos['id'] + " - " + lista_activos['nombre']).tolist() if not lista_activos.empty else []
    conn.close()
    
    if not lista_opciones:
        st.warning("⚠️ Debe registrar al menos un activo antes de reportar mantenimiento.")
    else:
        with tab1:
            with st.form("form_trabajo"):
                tequipo = st.selectbox("Equipo", lista_opciones).split(" - ")[0]
                ttipo = st.selectbox("Tipo Mantenimiento", ["Preventivo", "Correctivo", "Predictivo"])
        
                col_f1, col_h1 = st.columns(2)
                with col_f1:
                    fecha_ini = st.date_input("Fecha inicio", datetime.now().date())
                with col_h1:
                    hora_ini = st.time_input("Hora inicio", datetime.now().time())
        
                col_f2, col_h2 = st.columns(2)
                with col_f2:
                    fecha_fin = st.date_input("Fecha fin", datetime.now().date())
                with col_h2:
                    hora_fin = st.time_input("Hora fin", datetime.now().time())
        
                tini = datetime.combine(fecha_ini, hora_ini)
                tfin = datetime.combine(fecha_fin, hora_fin)
        
                horas_duracion = None  # Inicialización para evitar NameError
                if tfin < tini:
                    st.error("❌ La fecha/hora de fin no puede ser anterior a la de inicio.")
                else:
                    diferencia = tfin - tini
                    horas_duracion = diferencia.total_seconds() / 3600.0
                    
        
                tdesc = st.text_area("Descripción de la tarea")
                col_t3, col_t4 = st.columns(2)
                tpers = col_t3.text_input("Técnico Responsable")
                tcosto = col_t4.number_input("Costo Mantenimiento ($)", min_value=0.0, value=0.0)
                archivo_reporte = st.file_uploader("Adjuntar Reporte / Orden de Trabajo (Opcional)", type=['pdf', 'docx', 'jpg'])
        
                if st.form_submit_button("Registrar Mantenimiento"):
                    if tfin < tini:
                        st.error("No se puede guardar: la fecha de fin es anterior a la de inicio.")
                    else:
                        nombre_archivo = guardar_archivo(archivo_reporte, prefijo=f"OT_{tequipo}")
                        conn = get_connection()
                        conn.execute("""
                            INSERT INTO trabajos 
                            (equipo_id, tipo_mant, fecha_inicio, fecha_fin, descripcion, personal, costo_repuestos, tiempo_inter, archivo_adjunto)
                            VALUES (?,?,?,?,?,?,?,?,?)
                        """, (tequipo, ttipo, tini, tfin, tdesc, tpers, tcosto, horas_duracion, nombre_archivo))
                        conn.commit()
                        conn.close()
                        st.success("Orden de trabajo guardada exitosamente.")
                        st.balloons()
        with tab2:
            with st.form("form_paro"):
                pequipo_full = st.selectbox("Equipo en Paro", lista_opciones)
                pequipo = pequipo_full.split(" - ")[0]
                
                col_p1, col_p2 = st.columns(2)
                with col_p1:
                    fecha_ini_paro = st.date_input("Fecha inicio paro", datetime.now().date())
                    hora_ini_paro = st.time_input("Hora inicio paro", datetime.now().time())
                with col_p2:
                    fecha_fin_paro = st.date_input("Fecha fin paro", datetime.now().date())
                    hora_fin_paro = st.time_input("Hora fin paro", datetime.now().time())
                
                pini = datetime.combine(fecha_ini_paro, hora_ini_paro)
                pfin = datetime.combine(fecha_fin_paro, hora_fin_paro)
                
                # Inicializar variable para evitar NameError
                diferencia_paro = None
                horas_paro = None
                
                if pfin < pini:
                    st.error("❌ La fecha/hora de fin no puede ser anterior a la de inicio.")
                else:
                    diferencia_paro = pfin - pini
                    horas_paro = diferencia_paro.total_seconds() / 3600.0
                    
                
                pcausa = st.text_input("Causa Raíz / Motivo")
                
                if st.form_submit_button("Reportar Paro"):
                    if pfin < pini:
                        st.error("No se puede registrar: la fecha de fin es anterior a la de inicio.")
                    else:
                        conn = get_connection()
                        conn.execute(
                            "INSERT INTO paros (equipo_id, inicio_paro, fin_paro, causa) VALUES (?,?,?,?)",
                            (pequipo, pini, pfin, pcausa)
                        )
                        conn.commit()
                        conn.close()
                        st.success(f"✅ Paro registrado para el equipo {pequipo}.")
                        st.balloons()

# =========================================================
# REPUESTOS
# =========================================================
elif menu == "📦 Repuestos":
    st.header("📦 Gestión de Inventario")
    tab_reg, tab_uso = st.tabs(["📥 Nuevo Repuesto", "📤 Registrar Uso en Intervención"])
    
    with tab_reg:
        with st.form("form_repuestos"):
            c1, c2, c3 = st.columns(3)
            rid = c1.text_input("Código Interno", placeholder="Ej: REP-001")
            n_parte = c2.text_input("N° de Parte / Fabrica", placeholder="Ej: SKF-6204")
            desc = c3.text_input("Descripción", placeholder="Rodamiento de bolas")

            c4, c5 = st.columns(2)
            stock = c4.number_input("Stock Inicial", min_value=0)
            costo = c5.number_input("Costo Unitario ($)", min_value=0.0)

            if st.form_submit_button("Guardar Repuesto"):
                conn = get_connection()
                try:
                    conn.execute("INSERT INTO repuestos (id, numero_parte, descripcion, stock, costo_unitario) VALUES (?,?,?,?,?)", 
                                 (rid, n_parte, desc, stock, costo))
                    conn.commit()
                    st.success("Repuesto guardado en el inventario.")
                    st.balloons()
                except sqlite3.Error as e:
                    st.error(f"Error al guardar: {e}")
                finally:
                    conn.close()

        conn = get_connection()
        df = pd.read_sql("SELECT id, numero_parte, descripcion, stock, costo_unitario FROM repuestos", conn)
        conn.close()
        st.dataframe(df, use_container_width=True)

    with tab_uso:
        st.write("Registre los repuestos utilizados en una orden de trabajo.")
        conn = get_connection()
        df_trabajos_act = pd.read_sql("SELECT id, equipo_id, descripcion FROM trabajos ORDER BY id DESC", conn)
        df_reps = pd.read_sql("SELECT id, descripcion, stock, costo_unitario FROM repuestos WHERE stock > 0", conn)
        
        if df_trabajos_act.empty or df_reps.empty:
            st.info("Debe registrar al menos un trabajo de mantenimiento y un repuesto con stock disponible para registrar un consumo.")
        else:
            with st.form("form_uso_repuestos"):
                lista_t = df_trabajos_act['id'].astype(str) + " - " + df_trabajos_act['equipo_id'] + " (" + df_trabajos_act['descripcion'].str[:20] + "...)"
                sel_trabajo = st.selectbox("1. Seleccione Orden de Trabajo", lista_t)
                trabajo_id = sel_trabajo.split(" - ")[0]
                
                lista_r = df_reps['id'] + " - " + df_reps['descripcion'] + " (Stock: " + df_reps['stock'].astype(str) + ")"
                sel_rep = st.selectbox("2. Seleccione Repuesto", lista_r)
                repuesto_id = sel_rep.split(" - ")[0]
                
                stock_actual = int(df_reps.loc[df_reps['id'] == repuesto_id, 'stock'].values[0])
                costo_u = float(df_reps.loc[df_reps['id'] == repuesto_id, 'costo_unitario'].values[0])
                
                cantidad_uso = st.number_input("3. Cantidad utilizada", min_value=1, max_value=stock_actual, value=1)
                costo_total_calculado = cantidad_uso * costo_u
                st.info(f"**Costo Total por intervención calculable:** ${costo_total_calculado:.2f}")
                
                if st.form_submit_button("Registrar Consumo y Descontar Stock"):
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO detalle_repuestos (trabajo_id, repuesto_id, cantidad, costo_total) VALUES (?,?,?,?)",
                                   (trabajo_id, repuesto_id, cantidad_uso, costo_total_calculado))
                    cursor.execute("UPDATE repuestos SET stock = stock - ? WHERE id = ?", (cantidad_uso, repuesto_id))
                    # Usar IFNULL para evitar que costo_repuestos NULL cause problemas
                    cursor.execute("UPDATE trabajos SET costo_repuestos = IFNULL(costo_repuestos, 0) + ? WHERE id = ?", 
                                   (costo_total_calculado, trabajo_id))
                    conn.commit()
                    st.success("Inventario actualizado y costo asignado a la orden de trabajo exitosamente.")
                    st.balloons()
                    
        st.subheader("Historial de Consumo de Repuestos")
        try:
            df_detalles = pd.read_sql('''
                SELECT d.id AS "ID Uso", t.equipo_id AS "Equipo", d.trabajo_id AS "Orden Trabajo", 
                       r.descripcion AS "Repuesto", d.cantidad AS "Cant. Usada", 
                       r.costo_unitario AS "Costo U.", d.costo_total AS "Costo Total"
                FROM detalle_repuestos d
                JOIN repuestos r ON d.repuesto_id = r.id
                JOIN trabajos t ON d.trabajo_id = t.id
                ORDER BY d.id DESC
            ''', conn)
            st.dataframe(df_detalles, use_container_width=True)
        except Exception as e:
            pass
        conn.close()

# =========================================================
# BASE DE DATOS
# =========================================================
elif menu == "🔍 Base de datos":
    st.header("Historial y Gestión de Datos")
    t_act, t_hist, t_rept, t_adm = st.tabs(["Lista de Activos", "Historial Completo", "Repuestos", "⚙️ Administración"])
    
    conn = get_connection()
    with t_act:
        st.dataframe(pd.read_sql("SELECT * FROM activos", conn), use_container_width=True)
    with t_hist:
        st.subheader("Historial de Mantenimientos")
        df_trabajos_hist = pd.read_sql("SELECT * FROM trabajos", conn)
    
        # Botón para resetear (opcional)
        if st.button("🔄 Mostrar todos los registros"):
            st.rerun()
    
        if not df_trabajos_hist.empty:
            df_trabajos_hist['fecha_inicio'] = pd.to_datetime(df_trabajos_hist['fecha_inicio'], errors='coerce')
            df_trabajos_hist = df_trabajos_hist.dropna(subset=['fecha_inicio'])
    
            # Filtros de equipo y tipo
            c_f1, c_f2 = st.columns(2)
            filtro_eq = c_f1.multiselect("Filtrar por Equipo", df_trabajos_hist['equipo_id'].unique())
            filtro_tipo = c_f2.multiselect("Filtrar por Tipo de Mantenimiento", df_trabajos_hist['tipo_mant'].unique())
    
            if filtro_eq:
                df_trabajos_hist = df_trabajos_hist[df_trabajos_hist['equipo_id'].isin(filtro_eq)]
            if filtro_tipo:
                df_trabajos_hist = df_trabajos_hist[df_trabajos_hist['tipo_mant'].isin(filtro_tipo)]
    
            # Filtros de fecha opcionales
            c_f3, c_f4 = st.columns(2)
            fecha_desde = c_f3.date_input("Fecha inicio filtro (opcional)", value=None)
            fecha_hasta = c_f4.date_input("Fecha final filtro (opcional)", value=None)
    
            if fecha_desde is not None:
                df_trabajos_hist = df_trabajos_hist[df_trabajos_hist['fecha_inicio'] >= pd.Timestamp(fecha_desde)]
            if fecha_hasta is not None:
                fecha_hasta_ts = pd.Timestamp(fecha_hasta) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
                df_trabajos_hist = df_trabajos_hist[df_trabajos_hist['fecha_inicio'] <= fecha_hasta_ts]
    
        st.dataframe(df_trabajos_hist, use_container_width=True)

        st.subheader("Archivos Adjuntos")
        for _, row in df_trabajos_hist.iterrows():
            archivo = row.get("archivo_adjunto")
            if archivo:
                ruta = os.path.join("uploads", archivo)
                if os.path.exists(ruta):
                    with open(ruta, "rb") as f:
                        file_bytes = f.read()
                    st.download_button(
                        label=f"📄 OT #{row['id']} - {archivo}",
                        data=file_bytes,
                        file_name=archivo,
                        key=f"hist_{row['id']}"
                    )
        
        st.subheader("Historial de Paros")
        df_paros_hist = pd.read_sql("SELECT * FROM paros", conn)
        
        if not df_paros_hist.empty and filtro_eq:
            df_paros_hist = df_paros_hist[df_paros_hist['equipo_id'].isin(filtro_eq)]
             
        st.dataframe(df_paros_hist, use_container_width=True)
        
    with t_rept:
        st.dataframe(pd.read_sql("SELECT id, descripcion, stock, costo_unitario FROM repuestos", conn), use_container_width=True)
    
    with t_adm:
        st.subheader("🧪 Carga rápida de datos de prueba")
        st.info("Use esta opción para poblar la base de datos con activos, mantenimientos, paros y repuestos de ejemplo. Ideal para validar MTBF, MTTR, disponibilidad, costos, filtros y gráficas.")
        col_demo1, col_demo2, col_demo3 = st.columns(3)
        with col_demo1:
            demo_activos = st.number_input("Activos demo", min_value=4, max_value=50, value=12, step=1)
        with col_demo2:
            demo_trabajos = st.number_input("Trabajos por activo", min_value=1, max_value=30, value=8, step=1)
        with col_demo3:
            demo_paros = st.number_input("Paros por activo", min_value=1, max_value=20, value=4, step=1)
        limpiar_demo = st.checkbox("Limpiar base de datos antes de cargar demo", value=False)
        if st.button("🚀 Cargar datos demo", key="btn_cargar_demo"):
            activos_c, trabajos_c, paros_c = cargar_datos_demo(
                cantidad_activos=int(demo_activos),
                trabajos_por_activo=int(demo_trabajos),
                paros_por_activo=int(demo_paros),
                limpiar_antes=limpiar_demo
            )
            st.success(f"Datos demo cargados: {activos_c} activos, {trabajos_c} trabajos y {paros_c} paros.")
            st.balloons()
            st.rerun()

        st.markdown("---")
        st.subheader("Zona de Peligro")
        col_activo, col_repuesto = st.columns(2)
    
        with col_activo:
            lista_borrar_equipo = pd.read_sql("SELECT id FROM activos", conn)['id'].tolist()
            if lista_borrar_equipo:
                equipo_a_borrar = st.selectbox("Seleccione ID de equipo a eliminar", lista_borrar_equipo, key="sel_borrar_activo")
                st.warning(f"Borrar el activo {equipo_a_borrar} eliminará también todo su historial.")
                if st.button("Confirmar eliminación de activo", key="btn_borrar_activo"):
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM activos WHERE id = ?", (equipo_a_borrar,))
                    conn.commit()
                    st.success("Activo eliminado.")
                    st.balloons()
                    st.rerun()
    
        with col_repuesto:
            lista_borrar_repuesto = pd.read_sql("SELECT id FROM repuestos", conn)['id'].tolist()
            if lista_borrar_repuesto:
                repuesto_a_borrar = st.selectbox("Seleccione ID de repuesto a eliminar", lista_borrar_repuesto, key="sel_borrar_repuesto")
                st.warning(f"Borrar el repuesto {repuesto_a_borrar} eliminará su historial.")
                if st.button("Confirmar eliminación de repuesto", key="btn_borrar_repuesto"):
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM detalle_repuestos WHERE repuesto_id = ?", (repuesto_a_borrar,))
                    cursor.execute("DELETE FROM repuestos WHERE id = ?", (repuesto_a_borrar,))
                    conn.commit()
                    st.success("Repuesto eliminado.")
                    st.balloons()
                    st.rerun()
    conn.close()
