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
                        costo_repuestos REAL,
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
        conn.execute("ALTER TABLE trabajos ADD COLUMN tiempo_inter TEXT")
    except:
        pass

    conn.commit()
    conn.close()

# --- FUNCIONES AUXILIARES ---
def generar_id_automatico(tipo_activo):
    prefijos = {"Motor": "MOT", "Bomba": "BOM", "Compresor": "COM", "Cinta Transportadora": "CIN", "Otro": "GEN"}
    prefijo = prefijos.get(tipo_activo, "GEN")
    
    conn = get_connection()
    df = pd.read_sql(f"SELECT id FROM activos WHERE id LIKE '{prefijo}-%'", conn)
    conn.close()
    
    if df.empty:
        return f"{prefijo}-001"
    else:
        # Extraer el número, encontrar el máximo y sumar 1
        nums = df['id'].str.extract(r'-(\d+)')[0].dropna().astype(int)
        if nums.empty: return f"{prefijo}-001"
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
        query_trabajos += f" WHERE equipo_id = '{equipo_id}'"
        query_paros += f" WHERE equipo_id = '{equipo_id}'"
        
    df_trabajos = pd.read_sql(query_trabajos, conn)
    df_paros = pd.read_sql(query_paros, conn)
    conn.close()

    if df_trabajos.empty and df_paros.empty:
        return (None, None, None)  # ahora devolvemos una tupla de tres elementos

    # Conversión a datetime
    df_trabajos['fecha_inicio'] = pd.to_datetime(df_trabajos['fecha_inicio'])
    df_trabajos['fecha_fin'] = pd.to_datetime(df_trabajos['fecha_fin'])
    df_paros['inicio_paro'] = pd.to_datetime(df_paros['inicio_paro'])
    df_paros['fin_paro'] = pd.to_datetime(df_paros['fin_paro'])

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


    # Cálculo de indicadores #
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

# --- INTERFAZ STREAMLIT ---
init_db()

# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:
    # Intentamos cargar el logo desde la ruta proporcionada
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

    # --- NUEVO: Cálculo Global de Planta (Requisito 'f') ---
    df_trab_global = pd.read_sql("SELECT costo_repuestos FROM trabajos", conn)
    costo_global = df_trab_global['costo_repuestos'].sum() if not df_trab_global.empty else 0
    
    st.info(f"💰 **Costo Total de Mantenimiento (Global de Planta):** ${costo_global:,.2f}")
    st.markdown("---")
    # -------------------------------------------------------

    activos = pd.read_sql("SELECT id, nombre FROM activos", conn)
    conn.close()
    
    if df_activos.empty:
        st.info("No hay activos registrados. Por favor, registre un equipo primero.")
    else:
        col_sel, col_estado, col_manual = st.columns([2, 1, 1])
        
        with col_sel:
            selected_option = st.selectbox("Seleccione un equipo:", df_activos['id'] + " - " + df_activos['nombre'])
            eid = selected_option.split(" - ")[0]
            
        # 🌟 NUEVO: Cambio de Estado Operativo rápido
        with col_estado:
            st.write("Estado Operativo:")
            estado_actual = df_activos.loc[df_activos['id'] == eid, 'estado'].values[0]
            
            # Selector de estado
            nuevo_estado = st.radio("Modificar", ["Activo", "En Falla"], 
                                    index=0 if estado_actual == "Activo" else 1, horizontal=True, label_visibility="collapsed")
            
            if nuevo_estado != estado_actual:
                # 2. Abrimos una conexión NUEVA exclusiva para actualizar
                conn_upd = get_connection()
                conn_upd.execute("UPDATE activos SET estado = ? WHERE id = ?", (nuevo_estado, eid))
                conn_upd.commit()
                conn_upd.close()
                st.rerun()
                
            if nuevo_estado == "Activo":
                st.success("🟢 Equipo Operativo")
            else:
                st.error("🔴 Equipo Detenido (En Falla)")
                
        # 🌟 NUEVO: Carga de Manuales / Planos
        with col_manual:
            archivo_manual = st.file_uploader("Subir Manual/Plano (PDF)", type=['pdf', 'png', 'jpg'])
            if archivo_manual:
                guardar_archivo(archivo_manual, prefijo=f"MANUAL_{eid}")
                st.toast("Manual guardado exitosamente.")

        conn.close()
        st.markdown("---")
        
        indicadores, df_trab, df_paros = calcular_indicadores(eid)  # ahora devuelve tres
        
        if indicadores is not None:   # si hay datos, el diccionario no es None
            # Métricas con las claves correctas
            col1, col2, col3 = st.columns(3)
            col1.metric("MTBF (H)", f"{indicadores['MTBF (H)']} h", help="Tiempo medio entre fallos")
            col2.metric("MTTR (H)", f"{indicadores['MTTR (H)']} h", help="Tiempo medio de reparación")
            col3.metric("Disponibilidad", f"{indicadores['Disponibilidad (%)']}%")
            
            col4, col5, col6 = st.columns(3)
            col4.metric("Frecuencia de Fallos", f"{indicadores['Frecuencia Fallos (f/día)']} f/d")
            col5.metric("Total Paro", f"{indicadores['Horas Paro']} h")
            col6.metric("Costo Mantenimiento (Equipo)", f"${indicadores['Costo Total ($)']}")
            
            # INTERPRETACIÓN TÉCNICA
            st.markdown("---")
            st.subheader("🧠 Interpretación Técnica")

            if indicadores['Disponibilidad (%)'] < 85:
                st.error("⚠️ Equipo crítico: baja disponibilidad operacional")
                st.subheader(f"{indicadores['Disponibilidad (%)']} %")

            elif indicadores['Disponibilidad (%)'] < 95:
                st.warning("⚠️ Disponibilidad aceptable pero mejorable")
                st.subheader(f"{indicadores['Disponibilidad (%)']} %")

            else:
                st.success("✅ Excelente disponibilidad")
                st.subheader(f"{indicadores['Disponibilidad (%)']} %")

            if indicadores['MTBF (H)'] < 20:
                st.warning("⚠️ Alta frecuencia de fallos. Se recomienda fortalecer mantenimiento preventivo.")


            # --- GRÁFICO INTERACTIVO ---
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

    # 🌟 NUEVO: Sacamos el tipo de equipo fuera del form para que Streamlit pueda actualizar el ID dinámicamente
    tipo = st.selectbox("1. Seleccione Tipo de Activo", ["Motor", "Bomba", "Compresor", "Cinta Transportadora", "Otro"])
    
    # Generador automático
    id_sugerido = generar_id_automatico(tipo)

    with st.form("form_activos"):
        st.write("2. Complete los datos del equipo")
        c1, c2 = st.columns(2)
        # Se rellena automáticamente con el ID sugerido
        aid = c1.text_input("Código/ID Equipo", value=id_sugerido, help="Puede dejar el generado automáticamente o editarlo.")
        nombre = c2.text_input("Nombre del Equipo", placeholder="Ej: Bomba de Agua Principal")
        area = c1.text_input("Área o Proceso")
        estado = c2.selectbox("Estado Inicial", ["Activo", "Fuera de servicio"])
        
        if st.form_submit_button("✅ Guardar Activo"):
            if aid and nombre:
                conn = get_connection()
                try:
                    conn.execute("INSERT INTO activos VALUES (?,?,?,?,?)", (aid, nombre, area, tipo, estado))
                    conn.commit()
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
                
                c_t1, c_t2 = st.columns(2)
                tini = c_t1.datetime_input("Inicio Intervención", datetime.now())
                tfin = c_t2.datetime_input("Fin Intervención", datetime.now())
                
                tdesc = st.text_area("Descripción de la tarea")
                c_t3, c_t4 = st.columns(2)
                tpers = c_t3.text_input("Técnico Responsable")
                tcosto = c_t4.number_input("Costo Mantenimiento ($)", min_value=0.0)
                
                # 🌟 NUEVO: Carga de archivo de reporte de intervención
                archivo_reporte = st.file_uploader("Adjuntar Reporte / Orden de Trabajo (Opcional)", type=['pdf', 'docx', 'jpg'])
                
                if tfin < tini:
                    st.error("¡Error! La fecha de fin no puede ser anterior a la de inicio.")
                else:
                    diferencia_int = tfin - tini
                    # Mostrar el resultado directo (formato: 0:00:00)
                    tint = str(diferencia_int)
                    st.write(f"La duración total de intervención es: {diferencia_int}")
                    

                if st.form_submit_button("Registrar Mantenimiento"):
                    nombre_archivo = guardar_archivo(archivo_reporte, prefijo=f"OT_{tequipo}")
                    conn = get_connection()
                    conn.execute("INSERT INTO trabajos (equipo_id, tipo_mant, fecha_inicio, fecha_fin, descripcion, personal, costo_repuestos, tiempo_inter, archivo_adjunto) VALUES (?,?,?,?,?,?,?,?,?)",
                                    (tequipo, ttipo, tini, tfin, tdesc, tpers, tcosto, tint, nombre_archivo))
                    conn.commit()
                    conn.close()
                    st.success("Orden de trabajo guardada exitosamente.")

        with tab2:
            with st.form("form_paro"):
                pequipo_full = st.selectbox("Equipo en Paro", lista_activos)
                pequipo = pequipo_full.split(" - ")[0]
                c_p1, c_p2 = st.columns(2)
                pini = c_p1.datetime_input("Inicio del Paro", datetime.now())
                pfin = c_p2.datetime_input("Fin del Paro", datetime.now())
                
                if pfin < pini:
                    st.error("¡Error! La fecha de fin no puede ser anterior a la de inicio.")
                else:
                    diferencia_paro = pfin - pini
                # Mostrar el resultado directo (formato: 0:00:00)
                pint = str(diferencia_paro)
                st.write(f"La duración total del paro es: {diferencia_paro}")

                
                pcausa = st.text_input("Causa Raíz / Motivo")
                
                if st.form_submit_button("Reportar Paro"):
                    conn = get_connection()
                    conn.execute("INSERT INTO paros (equipo_id, inicio_paro, fin_paro, causa) VALUES (?,?,?,?)",
                                (pequipo, pini, pfin, pcausa))
                    conn.commit()
                    conn.close()
                    st.warning(f"Paro registrado para el equipo {pequipo}.")

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
                    # Insertar el detalle del repuesto consumido
                    cursor.execute("INSERT INTO detalle_repuestos (trabajo_id, repuesto_id, cantidad, costo_total) VALUES (?,?,?,?)",
                                   (trabajo_id, repuesto_id, cantidad_uso, costo_total_calculado))
                    # Descontar el stock automáticamente
                    cursor.execute("UPDATE repuestos SET stock = stock - ? WHERE id = ?", (cantidad_uso, repuesto_id))
                    # Sumar el costo al costo total de la orden de trabajo
                    cursor.execute("UPDATE trabajos SET costo_repuestos = costo_repuestos + ? WHERE id = ?", (costo_total_calculado, trabajo_id))
                    conn.commit()
                    st.success("Inventario actualizado y costo asignado a la orden de trabajo exitosamente.")
                    
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
    t_act, t_hist, t_rept, t_adm = st.tabs(["Lista de Activos", "Historial Completo", "Respuestos", "⚙️ Administración"])
    
    conn = get_connection()
    with t_act:
        st.dataframe(pd.read_sql("SELECT * FROM activos", conn), use_container_width=True)
    with t_hist:
        st.subheader("Historial de Mantenimientos")
        df_trabajos_hist = pd.read_sql("SELECT * FROM trabajos", conn)
        
        # --- NUEVO: FILTRADO OBLIGATORIO ---
        if not df_trabajos_hist.empty:
            c_f1, c_f2 = st.columns(2)
            filtro_eq = c_f1.multiselect("Filtrar por Equipo", df_trabajos_hist['equipo_id'].unique())
            filtro_tipo = c_f2.multiselect("Filtrar por Tipo de Mantenimiento", df_trabajos_hist['tipo_mant'].unique())
            
            if filtro_eq:
                df_trabajos_hist = df_trabajos_hist[df_trabajos_hist['equipo_id'].isin(filtro_eq)]
            if filtro_tipo:
                df_trabajos_hist = df_trabajos_hist[df_trabajos_hist['tipo_mant'].isin(filtro_tipo)]
                
        st.dataframe(df_trabajos_hist, use_container_width=True)
        
        st.subheader("Historial de Paros")
        df_paros_hist = pd.read_sql("SELECT * FROM paros", conn)
        
        # Sincronizamos el filtro de equipo con la tabla de paros
        if not df_paros_hist.empty and 'filtro_eq' in locals() and filtro_eq:
             df_paros_hist = df_paros_hist[df_paros_hist['equipo_id'].isin(filtro_eq)]
             
        st.dataframe(df_paros_hist, use_container_width=True)
        
    with t_rept:
        st.dataframe(pd.read_sql("SELECT id, descripcion, stock, costo_unitario FROM repuestos", conn),use_container_width=True)
    
    with t_adm:
    st.subheader("Zona de Peligro")

            col_activo, col_repuesto = st.columns(2)
        
            # =========================
            # BORRAR ACTIVOS
            # =========================
            with col_activo:
                lista_borrar_equipo = pd.read_sql(
                    "SELECT id FROM activos", conn
                )['id'].tolist()
        
                if lista_borrar_equipo:
                    equipo_a_borrar = st.selectbox(
                        "Seleccione ID de equipo a eliminar",
                        lista_borrar_equipo,
                        key="sel_borrar_activo"
                    )
        
                    st.warning(
                        f"Borrar el activo {equipo_a_borrar} eliminará también todo su historial."
                    )
        
                    if st.button(
                        "Confirmar eliminación de activo",
                        key="btn_borrar_activo"
                    ):
                        cursor = conn.cursor()
                        cursor.execute(
                            "DELETE FROM activos WHERE id = ?",
                            (equipo_a_borrar,)
                        )
                        conn.commit()
        
                        st.success("Activo eliminado.")
                        st.rerun()
        
            # =========================
            # BORRAR REPUESTOS
            # =========================
            with col_repuesto:
                lista_borrar_repuesto = pd.read_sql(
                    "SELECT id FROM repuestos", conn
                )['id'].tolist()
        
                if lista_borrar_repuesto:
                    repuesto_a_borrar = st.selectbox(
                        "Seleccione ID de repuesto a eliminar",
                        lista_borrar_repuesto,
                        key="sel_borrar_repuesto"
                    )
        
                    st.warning(
                        f"Borrar el repuesto {repuesto_a_borrar} eliminará su historial."
                    )
        
                    if st.button(
                        "Confirmar eliminación de repuesto",
                        key="btn_borrar_repuesto"
                    ):
                        cursor = conn.cursor()
        
                        cursor.execute(
                            "DELETE FROM detalle_repuestos WHERE repuesto_id = ?",
                            (repuesto_a_borrar,)
                        )
        
                        cursor.execute(
                            "DELETE FROM repuestos WHERE id = ?",
                            (repuesto_a_borrar,)
                        )
        
                        conn.commit()
        
                        st.success("Repuesto eliminado.")
                        st.rerun()
    conn.close()
