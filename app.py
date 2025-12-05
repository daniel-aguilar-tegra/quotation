import streamlit as st
import pandas as pd
import time
import json
import google.generativeai as genai
from PIL import Image
from io import BytesIO

# --- 1. CONFIGURACIÓN GLOBAL ---
PAGE_TITLE = "Cotizador Industrial Tegra AI"
PAGE_ICON = "⚡"
BATCH_SIZE = 10  # Tamaño del bloque para enviar a la IA

# Configuración de página
st.set_page_config(
    page_title=PAGE_TITLE,
    page_icon=PAGE_ICON,
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. ESTILOS CSS (Modo Claro & Branding) ---
st.markdown("""
    <style>
        [data-testid="stAppViewContainer"] { background-color: #ffffff; }
        [data-testid="stSidebar"] { background-color: #f8f9fa; }
        h1, h2, h3, h4, h5, h6, p, li, div, span, label, .stMarkdown { color: #000000 !important; }
        
        /* Botones estilo Industrial */
        .stButton>button {
            width: 100%; font-weight: bold; border-radius: 8px;
            background-color: #d32f2f; color: white !important; border: none;
            transition: all 0.2s;
        }
        .stButton>button:hover { background-color: #b71c1c; transform: scale(1.01); }
        
        /* Tablas y Métricas */
        [data-testid="stMetricValue"] { color: #d32f2f !important; }
        .stDataFrame { border: 1px solid #ddd; border-radius: 5px; }
    </style>
""", unsafe_allow_html=True)

# --- 3. GESTIÓN DE ESTADO (CRUCIAL PARA EVITAR ERRORES) ---
if 'resultados' not in st.session_state:
    st.session_state.resultados = None

if 'procesando' not in st.session_state:
    st.session_state.procesando = False

# --- 4. FUNCIONES DE LÓGICA DE NEGOCIO ---

def normalizar_secciones(df):
    """
    Detecta filas que actúan como encabezados de sección (ej: 'V', 'SECCIÓN II')
    y propaga ese valor a una nueva columna 'Sección' para los ítems inferiores.
    """
    filas_limpias = []
    seccion_actual = "GENERAL"
    
    # Patrones comunes de secciones en licitaciones
    romanos = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", 
               "XI", "XII", "XIII", "XIV", "XV", "XX"]

    for index, row in df.iterrows():
        # Limpieza segura de valores
        val_col_a = str(row.iloc[0]).strip().upper().replace(".", "")
        val_col_b = str(row.iloc[1]).strip() if len(row) > 1 else ""
        
        # Criterio: Es sección si Col A es Romano O contiene "SECCION"
        es_seccion = (val_col_a in romanos) or ("SECCION" in val_col_a) or ("SECCIÓN" in val_col_a)
        
        if es_seccion:
            # Capturamos el título de la sección
            titulo = val_col_b if len(val_col_b) > 3 else str(row.iloc[0])
            seccion_actual = f"{val_col_a} - {titulo}"
        else:
            # Es un ítem de costo
            row_dict = row.to_dict()
            row_dict['Sección Detectada'] = seccion_actual
            filas_limpias.append(row_dict)
            
    # Reconstruimos DataFrame
    df_nuevo = pd.DataFrame(filas_limpias)
    if not df_nuevo.empty and 'Sección Detectada' in df_nuevo.columns:
        cols = list(df_nuevo.columns)
        cols.insert(0, cols.pop(cols.index('Sección Detectada')))
        df_nuevo = df_nuevo[cols]
        
    return df_nuevo

def analizar_lote_con_gemini(lote_df, api_key, modelo):
    """
    Envía un lote de filas a Gemini para desglosar materiales y mano de obra.
    """
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(modelo)
    
    # Convertimos el lote a JSON String
    lote_json = lote_df.to_json(orient="records")
    
    prompt = f"""
    Actúa como un Ingeniero de Costos Eléctricos Experto.
    Analiza esta lista de partidas de licitación (JSON):
    {lote_json}
    
    Devuelve un JSON con una lista de objetos con esta estructura exacta por ítem:
    {{
        "descripcion_original": "Manten la descripción original aqui",
        "categoria": "Clasifica en: Tablero, Transformador, Cableado, Canalización, Maniobra o Varios",
        "materiales_hardware": "Lista separada por comas de SOLO equipos físicos (ej: Interruptor 3x400A, Gabinete)",
        "mano_de_obra_tareas": "Lista de tareas humanas (ej: Fijación, Torqueo, Pruebas)",
        "precio_estimado_usd": "Estimación numérica en USD (solo número)",
        "link_referencia": "URL de búsqueda de Google (ej: https://www.google.com/search?q=Precio+Interruptor+Siemens)"
    }}
    
    IMPORTANTE: Responde SOLO el JSON válido.
    """
    
    try:
        response = model.generate_content(prompt)
        # Limpieza de bloques de código markdown si la IA los pone
        texto_limpio = response.text.replace("```json", "").replace("```", "").strip()
        if texto_limpio.startswith("json"): 
             texto_limpio = texto_limpio[4:].strip()
        return json.loads(texto_limpio)
    except Exception as e:
        st.error(f"Error procesando lote con IA: {e}")
        # Devolvemos estructura vacía con error para no romper el flujo
        return [{"descripcion_original": "ERROR IA", "error": str(e)}] * len(lote_df)

def generar_excel_descargable(df):
    """Genera archivo .xlsx en memoria."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Cotización')
        
        workbook = writer.book
        worksheet = writer.sheets['Cotización']
        
        # Formatos
        header_fmt = workbook.add_format({'bold': True, 'bg_color': '#D32F2F', 'font_color': 'white', 'border': 1})
        
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_fmt)
            
        worksheet.set_column(0, 0, 25) # Sección
        worksheet.set_column(1, 1, 60) # Descripción
        
    return output.getvalue()

# --- 5. INTERFAZ GRÁFICA (BARRA LATERAL) ---
with st.sidebar:
    try:
        st.image("logo_tegra.png", use_container_width=True)
    except:
        st.title("Tegra Soluciones")
    
    st.markdown("---")
    st.header("⚙️ Configuración")
    
    cliente_opt = st.selectbox("Formato de Cliente", ["GEPP (Seccionado)", "Estándar"])
    modo_gepp = "GEPP" in cliente_opt
    
    st.markdown("---")
    st.subheader("Motor de IA")
    api_key = st.text_input("Gemini API Key", type="password")
    
    # SELECTOR DE MODELO (Soluciona el error 404)
    modelo_ia = st.selectbox(
        "Versión del Modelo", 
        ["gemini-2.5-flash"],
        help="Si recibes error 404, cambia a 'gemini-1.5-flash-latest' o 'gemini-pro'"
    )
    
    st.caption("v2.2 - Full Fix")

# --- 6. INTERFAZ PRINCIPAL ---
st.title(PAGE_TITLE)

if modo_gepp:
    st.info("ℹ️ **Modo Avanzado GEPP:** Detecta secciones (I, II, V...) y procesa por lotes.")

st.divider()

uploaded_file = st.file_uploader("Sube el Excel (.xlsx)", type=["xlsx"])

if uploaded_file:
    try:
        xls = pd.ExcelFile(uploaded_file)
        
        # Selectores de Hoja y Encabezado
        col1, col2 = st.columns(2)
        with col1:
            # Buscar hoja por nombre automáticamente
            idx_def = 0
            for i, n in enumerate(xls.sheet_names):
                if any(x in n.upper() for x in ['RFQ', 'SIPA', 'CONCEPTOS', 'SOLICITUD']): 
                    idx_def = i; break
            hoja = st.selectbox("Pestaña de Datos:", xls.sheet_names, index=idx_def)
            
        with col2:
            header_row = st.number_input("Fila de Encabezados:", min_value=1, value=11 if modo_gepp else 1)

        # Lectura
        df_raw = pd.read_excel(xls, sheet_name=hoja, header=header_row-1)
        df_raw = df_raw.dropna(how='all')
        
        # Procesamiento
        if modo_gepp:
            with st.spinner("Normalizando estructura de secciones..."):
                df_procesado = normalizar_secciones(df_raw)
        else:
            df_procesado = df_raw

        # Vista Previa
        st.write("### 🔍 Vista Previa (Datos Limpios)")
        st.dataframe(df_procesado.head(5), use_container_width=True)
        st.caption(f"Total de partidas: {len(df_procesado)}")

        # Botón de IA
        st.write("")
        col_btn, _ = st.columns([1, 2])
        with col_btn:
            ready = api_key and not df_procesado.empty
            if st.button("🚀 INICIAR COTIZACIÓN", type="primary", disabled=not ready):
                
                res_finales = []
                total_items = len(df_procesado)
                batches = range(0, total_items, BATCH_SIZE)
                total_batches = len(batches)
                
                prog_bar = st.progress(0)
                status_container = st.status(f"Conectando con {modelo_ia}...", expanded=True)
                
                for i, start_idx in enumerate(batches):
                    end_idx = min(start_idx + BATCH_SIZE, total_items)
                    lote = df_procesado.iloc[start_idx:end_idx]
                    
                    status_container.write(f"Procesando lote {i+1}/{total_batches} (Filas {start_idx}-{end_idx})...")
                    prog_bar.progress((i+1)/total_batches)
                    
                    # Llamada a la IA
                    datos_enriquecidos = analizar_lote_con_gemini(lote, api_key, modelo_ia)
                    
                    # Unir resultados con datos originales
                    for j, item_ia in enumerate(datos_enriquecidos):
                        if j < len(lote):
                            fila_orig = lote.iloc[j].to_dict()
                            # Combinar diccionarios
                            fila_combinada = {**fila_orig, **item_ia}
                            res_finales.append(fila_combinada)
                    
                    time.sleep(1) # Rate limit preventivo

                status_container.update(label="✅ ¡Análisis Completado!", state="complete", expanded=False)
                
                # Guardar en estado
                df_resultado_ia = pd.DataFrame(res_finales)
                st.session_state.resultados = df_resultado_ia

    except Exception as e:
        st.error(f"Error leyendo el archivo: {e}")

# --- 7. ZONA DE DESCARGA ---
if st.session_state.resultados is not None:
    st.divider()
    st.subheader("📂 Resultados")
    
    col_res1, col_res2 = st.columns([3, 1])
    
    with col_res1:
        st.dataframe(st.session_state.resultados.head(10))
        
    with col_res2:
        st.success("Listo para descargar.")
        excel_data = generar_excel_descargable(st.session_state.resultados)
        timestamp = time.strftime("%Y%m%d-%H%M")
        
        st.download_button(
            label="📥 Descargar Excel (.xlsx)",
            data=excel_data,
            file_name=f"Cotizacion_Tegra_{timestamp}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )