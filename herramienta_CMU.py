# HERRAMIENTA PARA LA PROGRAMACIÓN DE EXÁMENES MÉDICOS OCUPACIONALES

# Importar librerías
import io
import os
import sys
import tempfile
import traceback
import contextlib
from pathlib import Path
import re
import html
import json
import unicodedata
import importlib.util
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Dict, Any, Tuple
import pandas as pd
import pdfplumber
import streamlit as st
import streamlit.components.v1 as components


# _________________________
# CONFIGURACIÓN BASE
# _________________________

st.set_page_config(
    page_title="Programación EMO - CMU",
    layout="wide",
)

CAL_HORA_MINIMA = "07:00"
CAL_HORA_MAXIMA = "17:00"
ALMUERZO_INICIO = "12:00"
ALMUERZO_FIN = "13:00"
TIEMPO_MAXIMO_BUSQUEDA_SEG = 3600
RUTA_CONJUNTOS_GUARDADOS = Path("conjuntos_emo_guardados.json")

DIAS_ES = {
    0: "Lunes",
    1: "Martes",
    2: "Miércoles",
    3: "Jueves",
    4: "Viernes",
    5: "Sábado",
    6: "Domingo",
}

DIAS_SEMANA_OPCIONES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
DIAS_NOMBRE_A_NUM = {v: k for k, v in DIAS_ES.items()}

# Recursos que pueden venir en el PDF de Hosvital
RECURSOS_EMO = {
    "OPTOMETRIA": {
        "nombre": "Optometría",
        "duracion_min": 15,
        "color": "#2EC4B6",
        "orden": 1,
    },
    "FONOAUDIOLOGIA": {
        "nombre": "Fonoaudiología",
        "duracion_min": 15,
        "color": "#7B61FF",
        "orden": 2,
    },
    "SALUD OCUPACIONAL": {
        "nombre": "Salud ocupacional",
        "duracion_min": 20,
        "color": "#3A86FF",
        "orden": 3,
    },
    "FISIOTERAPIA": {
        "nombre": "Fisioterapia",
        "duracion_min": 15,
        "color": "#FFB703",
        "orden": 4,
    },
}

# Exámenes que el usuario puede seleccionar para un paciente
EXAMENES_NOMBRES = [
    "Optometría",
    "Fonoaudiología",
    "Espirometría",
    "Laboratorios",
    "Electrocardiograma",
    "Salud ocupacional",
    "Imagenología",
    "Otros externos",
]

EXAMEN_NOMBRE_A_CODIGO = {
    "Optometría": "OPTOMETRIA",
    "Fonoaudiología": "FONOAUDIOLOGIA",
    "Espirometría": "ESPIROMETRIA",
    "Laboratorios": "LABORATORIO",
    "Electrocardiograma": "ELECTROCARDIOGRAMA",
    "Salud ocupacional": "SALUD OCUPACIONAL",
    "Imagenología": "IMAGENOLOGIA",
    "Otros externos": "OTROS_EXTERNOS",
}

CODIGO_A_EXAMEN_NOMBRE = {
    v: k for k, v in EXAMEN_NOMBRE_A_CODIGO.items()
}

ALIAS_RECURSOS = {
    "OPTOMETRIA": "OPTOMETRIA",
    "OPTOMETRÍA": "OPTOMETRIA",

    "FONOAUDIOLOGIA": "FONOAUDIOLOGIA",
    "FONOAUDIOLOGÍA": "FONOAUDIOLOGIA",

    "SALUD OCUPACIONAL": "SALUD OCUPACIONAL",
    "MEDICINA OCUPACIONAL": "SALUD OCUPACIONAL",

    "FISIOTERAPIA": "FISIOTERAPIA",
}

REGEX_FECHA_AGENDA = re.compile(
    r'(?P<fecha>\d{1,2}/\d{1,2}/\d{4})',
    re.IGNORECASE,
)

REGEX_MEDICO = re.compile(
    r"Medico\s+(?P<codigo>\S+)\s+(?P<nombre>.+?)\s*-\s*(?P<especialidad>.+)",
    re.IGNORECASE,
)

REGEX_FILA_CITA = re.compile(
    r"^(?P<emp>\d{2})\s+"
    r"(?P<sed>\d{3})\s+"
    r"(?P<cita_no>\d+)\s+"
    r"(?P<cons>\d+)\s+"
    r"(?P<tipo>[IGJ])\s+"
    r"(?P<hora>\d{1,2}:\d{2}:\d{2})\s+"
    r"(?P<detalle>.+)$"
)


RUTA_AJUSTES = Path("ajustes_modelo.json")

AJUSTES_DEFAULT = {
    "tiempo_solver": 3600,

    "duraciones": {
        "optometria": 15,
        "laboratorios": 5,
        "fonoaudiologia": 15,
        "espirometria": 15,
        "salud_ocupacional": 20,
        "electrocardiograma": 5
    },

    "horarios": {
        "OPTOMETRIA": {
            "Lunes": [["13:00","17:00"]],
            "Martes": [["13:00","17:00"]],
            "Miércoles": [["13:00","17:00"]],
            "Jueves": [["13:00","17:00"]],
            "Viernes": [["13:00","17:00"]]
        },

        "FONOAUDIOLOGIA": {
            "Lunes": [["09:00","11:30"]],
            "Jueves": [["09:00","11:30"]]
        },

        "SALUD OCUPACIONAL": {
            "Lunes": [["13:00","17:00"]],
            "Jueves": [["13:00","17:00"]]
        },

        "FISIOTERAPIA": {
            "Lunes": [["13:00","17:00"]],
            "Miércoles": [["13:00","17:00"]],
            "Viernes": [["13:00","17:00"]]
        },

        "LABORATORIO": {
            "Lunes": [["07:00","10:00"]],
            "Martes": [["07:00","10:00"]],
            "Miércoles": [["07:00","10:00"]],
            "Jueves": [["07:00","10:00"]],
            "Viernes": [["07:00","10:00"]]
        },

        "ENFERMERIA": {
            "Lunes": [["07:00","12:00"],["13:00","17:00"]],
            "Martes": [["07:00","12:00"],["13:00","17:00"]],
            "Miércoles": [["07:00","12:00"],["13:00","17:00"]],
            "Jueves": [["07:00","12:00"],["13:00","17:00"]],
            "Viernes": [["07:00","12:00"],["13:00","17:00"]]
        }
    }
}


# ______________
# FUNCIONES
# ______________
def cargar_ajustes():
    if not RUTA_AJUSTES.exists():
        with open(RUTA_AJUSTES, "w", encoding="utf-8") as f:
            json.dump(AJUSTES_DEFAULT, f, indent=4)

    with open(RUTA_AJUSTES, "r", encoding="utf-8") as f:
        return json.load(f)


def convertir_horarios_json(datos):

    resultado = {}

    mapa = {
        "Lunes":0,
        "Martes":1,
        "Miércoles":2,
        "Jueves":3,
        "Viernes":4,
        "Sábado":5,
        "Domingo":6
    }

    for recurso, dias in datos.items():

        resultado[recurso] = {}

        for dia, ventanas in dias.items():

            resultado[recurso][mapa[dia]] = [
                tuple(v) for v in ventanas
            ]

    return resultado


def guardar_ajustes(ajustes):
    with open(RUTA_AJUSTES, "w", encoding="utf-8") as f:
        json.dump(ajustes, f, indent=4)


def normalizar_texto(x: object) -> str:
    if x is None or pd.isna(x):
        return ""
    x = str(x).strip()
    x = unicodedata.normalize("NFKD", x)
    x = "".join(c for c in x if not unicodedata.combining(c))
    x = re.sub(r"\s+", " ", x)
    return x.upper().strip()


def clasificar_recurso_emo(especialidad_pdf: str) -> Optional[str]:
    especialidad_norm = normalizar_texto(especialidad_pdf)
    for alias, recurso in ALIAS_RECURSOS.items():
        if normalizar_texto(alias) in especialidad_norm:
            return recurso
    return None


def convertir_fecha(fecha_txt: str) -> pd.Timestamp:
    return pd.to_datetime(fecha_txt, dayfirst=True, errors="coerce")


def parse_hora(hora_txt: str) -> time:
    return datetime.strptime(hora_txt, "%H:%M").time()


def combinar_fecha_hora(fecha_dia: date, hora_obj: time) -> pd.Timestamp:
    return pd.Timestamp(datetime.combine(fecha_dia, hora_obj))


def formatear_fecha_larga(fecha_dia: date) -> str:
    fecha_ts = pd.to_datetime(fecha_dia)
    return f"{DIAS_ES[int(fecha_ts.weekday())]} {fecha_ts.strftime('%d/%m/%Y')}"


def ordenar_recursos(lista_recursos: List[str]) -> List[str]:
    return sorted(list(lista_recursos), key=lambda r: RECURSOS_EMO.get(r, {}).get("orden", 999))


def dentro_de_horario_emo(row: pd.Series) -> bool:
    recurso = row.get("recurso")
    fecha = row.get("fecha_dt")
    if pd.isna(fecha) or recurso not in HORARIOS_EMO_AJUSTADOS:
        return True

    dia_semana = int(fecha.weekday())
    ventanas = HORARIOS_EMO_AJUSTADOS.get(recurso, {}).get(dia_semana, [])
    if not ventanas:
        return False

    inicio = row["inicio"].time()
    fin = row["fin"].time()
    for h_ini, h_fin in ventanas:
        v_ini = datetime.strptime(h_ini, "%H:%M").time()
        v_fin = datetime.strptime(h_fin, "%H:%M").time()
        if inicio >= v_ini and fin <= v_fin:
            return True
    return False


def minutos_desde_medianoche(dt: pd.Timestamp) -> int:
    return int(dt.hour) * 60 + int(dt.minute)


def normalizar_lista_examenes(valor: object) -> List[str]:
    """Recibe texto pegado, lista o celda del editor y devuelve nombres canónicos de exámenes."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return []

    if isinstance(valor, list):
        candidatos = valor
    else:
        texto = str(valor)
        candidatos = re.split(r"[,;\n|/]+", texto)

    mapa_norm = {normalizar_texto(nombre): nombre for nombre in EXAMENES_NOMBRES}
    salida = []
    for item in candidatos:
        item_norm = normalizar_texto(item)
        if not item_norm:
            continue
        if item_norm in mapa_norm:
            nombre = mapa_norm[item_norm]
            if nombre not in salida:
                salida.append(nombre)
    return salida


def examenes_a_texto(lista_nombres: object) -> str:
    return ", ".join(normalizar_lista_examenes(lista_nombres))


def examenes_texto_a_codigos(valor: object) -> List[str]:
    codigos = []
    for nombre in normalizar_lista_examenes(valor):
        codigo = EXAMEN_NOMBRE_A_CODIGO.get(nombre)
        if codigo and codigo not in codigos:
            codigos.append(codigo)
    return ordenar_recursos(codigos)


def rango_fechas(inicio: date, fin: date) -> List[date]:
    if inicio > fin:
        return []
    return list(pd.date_range(inicio, fin, freq="D").date)

# ________________________________
# LECTURA Y PREPARACIÓN DEL PDF
# ________________________________

@st.cache_data(show_spinner=False)
def extraer_citas_de_pdf_bytes(nombre_archivo: str, contenido: bytes) -> pd.DataFrame:
    registros = []
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        for num_pagina, pagina in enumerate(pdf.pages, start=1):
            texto = pagina.extract_text() or ""
            if not texto.strip():
                continue

            print("\n===================")
            print("PAGINA:", num_pagina)
            print("===================")

            match_fecha = REGEX_FECHA_AGENDA.search(texto)
            
            print("Fecha encontrada:", match_fecha.groupdict() if match_fecha else None)
            match_medico = REGEX_MEDICO.search(texto)
            
            print("Medico encontrado:", match_medico.groupdict() if match_medico else None)
            if not match_fecha or not match_medico:
                continue

            fecha_txt = match_fecha.group("fecha")
            codigo_medico = match_medico.group("codigo").strip()
            nombre_medico = match_medico.group("nombre").strip()
            especialidad_pdf = match_medico.group("especialidad").strip()
            recurso = clasificar_recurso_emo(especialidad_pdf)
            
            print("ESPECIALIDAD:", repr(especialidad_pdf)," -> RECURSO:",repr(recurso))

            for linea in texto.splitlines():
                linea = linea.strip()
                match_fila = REGEX_FILA_CITA.match(linea)
                if not match_fila:
                    continue
                datos = match_fila.groupdict()
                registros.append(
                    {
                        "archivo": nombre_archivo,
                        "pagina": num_pagina,
                        "fecha_txt": fecha_txt,
                        "fecha_dt": convertir_fecha(fecha_txt),
                        "codigo_medico": codigo_medico,
                        "nombre_medico": nombre_medico,
                        "especialidad_pdf": especialidad_pdf,
                        "especialidad_norm": normalizar_texto(especialidad_pdf),
                        "recurso": recurso,
                        "recurso_nombre": RECURSOS_EMO.get(recurso, {}).get("nombre", None),
                        "cita_no": datos["cita_no"],
                        "consultorio": datos["cons"],
                        "tipo_cita": datos["tipo"],
                        "hora_inicio_txt": datos["hora"],
                    }
                )
                
    print("TOTAL REGISTROS EXTRAIDOS:", len(registros))
    return pd.DataFrame(registros)


@st.cache_data(show_spinner=False)
def preparar_bloques_ocupados(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    df = df.copy()
    df = df[df["recurso"].notna()].copy()
    if df.empty:
        return pd.DataFrame()

    df = df.drop_duplicates(
        subset=["fecha_dt", "codigo_medico", "recurso", "hora_inicio_txt"],
        keep="first",
    ).copy()

    df["inicio"] = pd.to_datetime(
        df["fecha_dt"].dt.strftime("%Y-%m-%d") + " " + df["hora_inicio_txt"],
        errors="coerce",
    )
    df["duracion_min"] = df["recurso"].map({r: c["duracion_min"] for r, c in RECURSOS_EMO.items()}).fillna(15).astype(int)
    df["fin"] = df["inicio"] + pd.to_timedelta(df["duracion_min"], unit="m")

    df = df.sort_values(["fecha_dt", "codigo_medico", "recurso", "inicio"]).copy()
    df["siguiente_inicio"] = df.groupby(["fecha_dt", "codigo_medico", "recurso"])["inicio"].shift(-1)
    mask_corte = (
        df["siguiente_inicio"].notna()
        & (df["siguiente_inicio"] > df["inicio"])
        & (df["siguiente_inicio"] < df["fin"])
    )
    df.loc[mask_corte, "fin"] = df.loc[mask_corte, "siguiente_inicio"]

    df["dentro_horario_emo"] = df.apply(dentro_de_horario_emo, axis=1)
    df["fecha_iso"] = df["fecha_dt"].dt.strftime("%Y-%m-%d")
    df["inicio_iso"] = df["inicio"].dt.strftime("%Y-%m-%d %H:%M")
    df["fin_iso"] = df["fin"].dt.strftime("%Y-%m-%d %H:%M")
    df["hora_inicio_txt_corta"] = df["inicio"].dt.strftime("%H:%M")
    df["hora_fin_txt"] = df["fin"].dt.strftime("%H:%M")
    return df


def procesar_pdfs_subidos(archivos_pdf) -> None:
    lista_df = []
    errores = []
    for archivo in archivos_pdf:
        try:
            df_archivo = extraer_citas_de_pdf_bytes(archivo.name, archivo.getvalue())
            if not df_archivo.empty:
                lista_df.append(df_archivo)
        except Exception as e:
            errores.append(f"{archivo.name}: {e}")

    if errores:
        st.session_state.pdf_errores = errores
    else:
        st.session_state.pdf_errores = []

    if lista_df:
        df_crudo = pd.concat(lista_df, ignore_index=True)
        df_bloques = preparar_bloques_ocupados(df_crudo)
        st.session_state.df_crudo = df_crudo
        st.session_state.df_bloques = df_bloques
        st.session_state.agenda_procesada = True
        st.session_state.idx_fecha_calendario = 0
    else:
        st.session_state.df_crudo = pd.DataFrame()
        st.session_state.df_bloques = pd.DataFrame()
        st.session_state.agenda_procesada = False


# ________________________________
# PACIENTES Y DISPONIBILIDAD
# ________________________________

def inicializar_estado() -> None:
    defaults = {
        "agenda_procesada": False,
        "df_crudo": pd.DataFrame(),
        "df_bloques": pd.DataFrame(),
        "pdf_errores": [],
        "nombre_conjunto": "Grupo EMO a programar",
        "num_pacientes_config": 5,
        "horizonte_inicio": date.today(),
        "horizonte_fin": date.today() + timedelta(days=4),
        "pacientes_df": pd.DataFrame(),
        "examenes_externos_df": pd.DataFrame(),
        "disponibilidades_pacientes": [],
        "idx_fecha_calendario": 0,
        "idx_fecha_disp": 0,
        "recursos_calendario_sel": [],
        "filtrar_horario_emo": False,
        "resultados_modelo": None,
        "idx_fecha_resultados": 0,
        "conjunto_cargado_nombre": "",
        "examenes_externos_editor": pd.DataFrame(),
        "claves_externos": set(),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def ajustar_tabla_pacientes(num_pacientes: int) -> None:
    columnas = ["Paciente", "Identificación", "Nombre", "Tipo de EMO", "Exámenes EMO a realizar"]
    actual = st.session_state.get("pacientes_df", pd.DataFrame(columns=columnas)).copy()
    for col in columnas:
        if col not in actual.columns:
            actual[col] = ""

    filas = []
    for i in range(num_pacientes):
        paciente_id = f"P{i + 1:03d}"
        if i < len(actual):
            fila = actual.iloc[i].to_dict()
            fila["Paciente"] = paciente_id
        else:
            fila = {
                "Paciente": paciente_id,
                "Identificación": "",
                "Nombre": "",
                "Tipo de EMO": "Ingreso",
                "Exámenes EMO a realizar": "",
            }
        fila["Tipo de EMO"] = fila.get("Tipo de EMO") or "Ingreso"
        fila["Exámenes EMO a realizar"] = examenes_a_texto(fila.get("Exámenes EMO a realizar", ""))
        filas.append(fila)

    st.session_state.pacientes_df = pd.DataFrame(filas, columns=columnas)


def paciente_etiquetas() -> List[str]:
    df = st.session_state.get("pacientes_df", pd.DataFrame())
    if df.empty:
        return []
    opciones = []
    for _, row in df.iterrows():
        pid = str(row.get("Paciente", "")).strip()
        nombre = str(row.get("Nombre", "")).strip()
        identificacion = str(row.get("Identificación", "")).strip()
        etiqueta = nombre if nombre else (identificacion if identificacion else "Sin nombre")
        opciones.append(f"{pid} - {etiqueta}")
    return opciones


def obtener_paciente_row(paciente_id: str) -> Optional[pd.Series]:
    df = st.session_state.get("pacientes_df", pd.DataFrame())
    if df.empty or paciente_id not in df["Paciente"].values:
        return None
    return df[df["Paciente"] == paciente_id].iloc[0]


def partir_por_almuerzo(fecha_dia: date, hora_ini: time, hora_fin: time) -> List[Dict[str, str]]:
    if hora_fin <= hora_ini:
        return []

    alm_ini = parse_hora(ALMUERZO_INICIO)
    alm_fin = parse_hora(ALMUERZO_FIN)
    intervalos = []

    if hora_ini < alm_ini:
        fin_1 = min(hora_fin, alm_ini)
        if fin_1 > hora_ini:
            intervalos.append((hora_ini, fin_1))

    if hora_fin > alm_fin:
        ini_2 = max(hora_ini, alm_fin)
        if hora_fin > ini_2:
            intervalos.append((ini_2, hora_fin))

    if not intervalos and (hora_fin <= alm_ini or hora_ini >= alm_fin):
        intervalos.append((hora_ini, hora_fin))

    salida = []
    for ini, fin in intervalos:
        salida.append(
            {
                "fecha": fecha_dia.isoformat(),
                "inicio": combinar_fecha_hora(fecha_dia, ini).strftime("%Y-%m-%d %H:%M"),
                "fin": combinar_fecha_hora(fecha_dia, fin).strftime("%Y-%m-%d %H:%M"),
                "hora_inicio": ini.strftime("%H:%M"),
                "hora_fin": fin.strftime("%H:%M"),
            }
        )
    return salida


def obtener_intervalos_franja(fecha_dia: date, franja: str, hora_ini_custom: time, hora_fin_custom: time) -> List[Dict[str, str]]:
    if franja == "Mañana completa (07:00-12:00)":
        return partir_por_almuerzo(fecha_dia, parse_hora("07:00"), parse_hora("12:00"))
    if franja == "Tarde completa (13:00-17:00)":
        return partir_por_almuerzo(fecha_dia, parse_hora("13:00"), parse_hora("17:00"))
    if franja == "Jornada completa (07:00-12:00 y 13:00-17:00)":
        return partir_por_almuerzo(fecha_dia, parse_hora("07:00"), parse_hora("12:00")) + partir_por_almuerzo(fecha_dia, parse_hora("13:00"), parse_hora("17:00"))
    if franja == "Personalizada":
        return partir_por_almuerzo(fecha_dia, hora_ini_custom, hora_fin_custom)
    return []




def guardar_disponibilidad(paciente_id: str, paciente_nombre: str, fechas: List[date], franja: str, hora_ini_custom: time, hora_fin_custom: time) -> int:
    actuales = st.session_state.get("disponibilidades_pacientes", [])
    claves = {(x["paciente_id"], x["fecha"], x["hora_inicio"], x["hora_fin"]) for x in actuales}
    agregados = 0

    for fecha_dia in fechas:
        for item in obtener_intervalos_franja(fecha_dia, franja, hora_ini_custom, hora_fin_custom):
            clave = (paciente_id, item["fecha"], item["hora_inicio"], item["hora_fin"])
            if clave in claves:
                continue
            actuales.append({"paciente_id": paciente_id, "paciente_nombre": paciente_nombre, **item})
            claves.add(clave)
            agregados += 1

    st.session_state.disponibilidades_pacientes = actuales
    return agregados


def disponibilidades_a_dataframe() -> pd.DataFrame:
    datos = st.session_state.get("disponibilidades_pacientes", [])
    if not datos:
        return pd.DataFrame(columns=["paciente_id", "paciente_nombre", "fecha", "inicio", "fin", "hora_inicio", "hora_fin", "inicio_dt", "fin_dt"])
    df = pd.DataFrame(datos)
    df["inicio_dt"] = pd.to_datetime(df["inicio"], errors="coerce")
    df["fin_dt"] = pd.to_datetime(df["fin"], errors="coerce")
    return df


def construir_df_disponibilidad_calendario(df_disp_paciente: pd.DataFrame, recursos: List[str]) -> pd.DataFrame:
    if df_disp_paciente.empty or not recursos:
        return pd.DataFrame(columns=["recurso", "inicio", "fin", "hora_inicio_txt", "hora_fin_txt"])
    registros = []
    for _, row in df_disp_paciente.iterrows():
        for recurso in recursos:
            registros.append(
                {
                    "recurso": recurso,
                    "inicio": row["inicio_dt"],
                    "fin": row["fin_dt"],
                    "hora_inicio_txt": row["hora_inicio"],
                    "hora_fin_txt": row["hora_fin"],
                }
            )
    return pd.DataFrame(registros)


# ____________________________
# CALENDARIO DIARIO
# ____________________________

def construir_html_calendario_dia(
    df_dia_ocupados: pd.DataFrame,
    fecha_dia: date,
    recursos_ordenados: List[str],
    titulo: str,
    subtitulo: str,
    df_dia_disponibilidad: Optional[pd.DataFrame] = None,
    mostrar_nota_privacidad: bool = False,
) -> str:
    h_min = datetime.strptime(CAL_HORA_MINIMA, "%H:%M")
    h_max = datetime.strptime(CAL_HORA_MAXIMA, "%H:%M")
    min_total = h_min.hour * 60 + h_min.minute
    max_total = h_max.hour * 60 + h_max.minute
    rango_total = max_total - min_total

    altura_hora_px = 76
    altura_total_px = max(int((rango_total / 60) * altura_hora_px), 520)
    n_cols = max(len(recursos_ordenados), 1)
    template_cols = "82px " + " ".join(["minmax(155px, 1fr)"] * n_cols)
    fecha_legible = pd.to_datetime(fecha_dia).strftime("%d/%m/%Y")

    time_labels = []
    grid_lines = []
    h = min_total
    while h <= max_total:
        top = ((h - min_total) / rango_total) * altura_total_px
        etiqueta = f"{h // 60:02d}:00"
        time_labels.append(f'<div class="time-label" style="top:{top:.2f}px;">{etiqueta}</div>')
        grid_lines.append(f'<div class="hour-line" style="top:{top:.2f}px;"></div>')
        h += 60

    h = min_total + 30
    while h < max_total:
        top = ((h - min_total) / rango_total) * altura_total_px
        grid_lines.append(f'<div class="half-hour-line" style="top:{top:.2f}px;"></div>')
        h += 60

    header_cells = ['<div class="corner-cell">Hora</div>']
    for recurso in recursos_ordenados:
        cfg = RECURSOS_EMO.get(recurso, {})
        nombre = cfg.get("nombre", recurso.title())
        color = cfg.get("color", "#64748B")
        header_cells.append(f'<div class="resource-header"><span class="resource-dot" style="background:{color};"></span>{html.escape(nombre)}</div>')

    alm_ini_min = datetime.strptime(ALMUERZO_INICIO, "%H:%M").hour * 60
    alm_fin_min = datetime.strptime(ALMUERZO_FIN, "%H:%M").hour * 60
    lunch_top = ((alm_ini_min - min_total) / rango_total) * altura_total_px
    lunch_height = ((alm_fin_min - alm_ini_min) / rango_total) * altura_total_px
    lunch_html = (
        f'<div class="lunch-block" style="top:{lunch_top:.2f}px; height:{lunch_height:.2f}px;">'
        f'<strong></strong><span>{ALMUERZO_INICIO}-{ALMUERZO_FIN}</span></div>'
    )

    lanes = ['<div class="time-axis" style="height:' + str(altura_total_px) + 'px;">' + "".join(time_labels) + "</div>"]
    if df_dia_disponibilidad is None:
        df_dia_disponibilidad = pd.DataFrame()

    for recurso in recursos_ordenados:
        cfg = RECURSOS_EMO.get(recurso, {})
        color = cfg.get("color", "#64748B")
        nombre_recurso = cfg.get("nombre", recurso.title())
        eventos_html = []

        if not df_dia_disponibilidad.empty and "recurso" in df_dia_disponibilidad.columns:
            df_disp_recurso = df_dia_disponibilidad[df_dia_disponibilidad["recurso"] == recurso].sort_values("inicio")
            for _, ev in df_disp_recurso.iterrows():
                ini_min = minutos_desde_medianoche(ev["inicio"])
                fin_min = minutos_desde_medianoche(ev["fin"])
                if fin_min <= min_total or ini_min >= max_total:
                    continue
                ini_min = max(ini_min, min_total)
                fin_min = min(fin_min, max_total)
                if fin_min <= ini_min:
                    continue
                top = ((ini_min - min_total) / rango_total) * altura_total_px
                height = max(((fin_min - ini_min) / rango_total) * altura_total_px, 24)
                subtitulo_ev = f'{ev["hora_inicio_txt"]}-{ev["hora_fin_txt"]}'
                eventos_html.append(
                    f'<div class="available-card" title="Disponible {html.escape(subtitulo_ev)}" style="top:{top:.2f}px; height:{height:.2f}px;">'
                    f'<strong>Disponible</strong><span>{html.escape(subtitulo_ev)}</span></div>'
                )

        if not df_dia_ocupados.empty and "recurso" in df_dia_ocupados.columns:
            df_recurso = df_dia_ocupados[df_dia_ocupados["recurso"] == recurso].sort_values("inicio")
            for _, ev in df_recurso.iterrows():
                ini_min = minutos_desde_medianoche(ev["inicio"])
                fin_min = minutos_desde_medianoche(ev["fin"])
                if fin_min <= min_total or ini_min >= max_total:
                    continue
                ini_min = max(ini_min, min_total)
                fin_min = min(fin_min, max_total)
                if fin_min <= ini_min:
                    continue
                top = ((ini_min - min_total) / rango_total) * altura_total_px
                height = max(((fin_min - ini_min) / rango_total) * altura_total_px, 22)
                subtitulo_ev = f'{ev["hora_inicio_txt_corta"]}-{ev["hora_fin_txt"]}'
                medico = str(ev.get("nombre_medico", ""))
                cita = str(ev.get("cita_no", ""))
                consultorio = str(ev.get("consultorio", ""))
                tooltip = f"{nombre_recurso} | {medico} | {subtitulo_ev} | Cita {cita} | Consultorio {consultorio}"
                eventos_html.append(
                    f'<div class="event-card" title="{html.escape(tooltip)}" style="top:{top:.2f}px; height:{height:.2f}px; background:{color};">'
                    f'<strong>Ocupado</strong><span>{html.escape(subtitulo_ev)}</span><small>Cita {html.escape(cita)}</small></div>'
                )

        lanes.append(
            '<div class="resource-lane" style="height:' + str(altura_total_px) + 'px;">'
            + "".join(grid_lines)
            + lunch_html
            + "".join(eventos_html)
            + "</div>"
        )

    empty_state = ""
    if df_dia_ocupados.empty and (df_dia_disponibilidad is None or df_dia_disponibilidad.empty):
        empty_state = '<div class="empty-state">No hay bloques ocupados ni disponibilidad guardada para este día.</div>'

    privacy_note = '<div class="privacy-note">Vista sin datos personales de pacientes</div>' if mostrar_nota_privacidad else ""

    return f"""
    <style>
        * {{ box-sizing: border-box; }}
        body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: #19324a; background: #ffffff; }}
        .calendar-shell {{ background: linear-gradient(180deg, #f7fbff 0%, #ffffff 100%); border: 1px solid #e4edf7; border-radius: 22px; padding: 16px; box-shadow: 0 10px 24px rgba(31, 47, 70, 0.07); overflow-x: auto; }}
        .calendar-title {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 12px; }}
        .calendar-title h3 {{ margin: 0; font-size: 20px; color: #17324d; }}
        .calendar-title p {{ margin: 4px 0 0 0; color: #6b7f93; font-size: 13px; }}
        .privacy-note {{ font-size: 12px; color: #6b7f93; background: #ffffff; border: 1px solid #e4edf7; border-radius: 999px; padding: 7px 12px; white-space: nowrap; }}
        .calendar-grid {{ display: grid; grid-template-columns: {template_cols}; min-width: {max(860, 82 + n_cols * 170)}px; border: 1px solid #e4edf7; border-radius: 16px; overflow: hidden; background: #ffffff; }}
        .corner-cell, .resource-header {{ height: 50px; display: flex; align-items: center; justify-content: center; gap: 8px; font-size: 13px; font-weight: 700; color: #27435f; background: #f4f8fc; border-bottom: 1px solid #e4edf7; border-right: 1px solid #e4edf7; }}
        .resource-dot {{ width: 11px; height: 11px; border-radius: 50%; display: inline-block; }}
        .time-axis {{ position: relative; background: #fbfdff; border-right: 1px solid #e4edf7; }}
        .time-label {{ position: absolute; right: 10px; transform: translateY(-50%); font-size: 12px; color: #60758a; font-weight: 600; }}
        .resource-lane {{ position: relative; background: #ffffff; border-right: 1px solid #edf2f7; }}
        .hour-line {{ position: absolute; left: 0; right: 0; border-top: 1px solid #e5edf5; }}
        .half-hour-line {{ position: absolute; left: 0; right: 0; border-top: 1px dashed #edf3f8; }}
        .lunch-block {{ position: absolute; left: 5px; right: 5px; border-radius: 10px; padding: 7px 8px; background: repeating-linear-gradient(45deg, #eef2f7, #eef2f7 8px, #e2e8f0 8px, #e2e8f0 16px); color: #475569; border: 1px solid #cbd5e1; z-index: 5; text-align: center; opacity: 0.96; overflow: hidden; }}
        .lunch-block strong {{ display: block; font-size: 12px; line-height: 1.1; }}
        .lunch-block span {{ display: block; font-size: 11px; margin-top: 2px; }}
        .available-card {{ position: absolute; left: 9px; right: 9px; border-radius: 12px; padding: 6px 8px; background: #dcfce7; color: #166534; border: 1px solid #86efac; overflow: hidden; z-index: 2; }}
        .available-card strong, .event-card strong {{ display: block; font-size: 12px; line-height: 1.1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        .available-card span, .event-card span {{ display: block; font-size: 11px; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        .event-card {{ position: absolute; left: 9px; right: 9px; border-radius: 12px; padding: 6px 8px; color: white; overflow: hidden; box-shadow: 0 6px 14px rgba(24, 50, 74, 0.15); border: 1px solid rgba(255, 255, 255, 0.35); z-index: 4; }}
        .event-card small {{ display: block; font-size: 10px; margin-top: 1px; opacity: 0.93; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        .empty-state {{ margin-top: 12px; padding: 14px; background: #fff7ed; border: 1px solid #fed7aa; color: #9a3412; border-radius: 14px; font-size: 13px; }}
    </style>
    <div class="calendar-shell">
        <div class="calendar-title"><div><h3>{html.escape(titulo)} - {fecha_legible}</h3><p>{html.escape(subtitulo)}</p></div>{privacy_note}</div>
        <div class="calendar-grid">{''.join(header_cells)}{''.join(lanes)}</div>
        {empty_state}
    </div>
    """

ajustes = cargar_ajustes()
HORARIOS_EMO_AJUSTADOS = convertir_horarios_json(
    ajustes["horarios"]
)

# ___________________________
# MÓDULOS DE LA HERRAMIENTA
# ___________________________

def modulo_agenda_hosvital() -> None:
    st.markdown("### 1. Disponibilidad recursos")

    col_upload, col_reglas = st.columns([1.05, 1.3], vertical_alignment="top")
    with col_upload:
        with st.form("form_cargue_pdf", clear_on_submit=False):
            archivos_pdf = st.file_uploader(
                "Adjunta uno o varios reportes PDF descargados de Hosvital",
                type=["pdf"],
                accept_multiple_files=True,
            )
            procesar = st.form_submit_button("Procesar agenda", use_container_width=True)
        if procesar:
            if not archivos_pdf:
                st.warning("Primero adjunta al menos un PDF.")
            else:
                with st.spinner("Leyendo PDF de Hosvital..."):
                    procesar_pdfs_subidos(archivos_pdf)
                if st.session_state.agenda_procesada:
                    st.success("Agenda procesada y guardada.")
                else:
                    st.error("No se encontraron citas legibles en los PDF.")

    if st.session_state.pdf_errores:
        st.warning("Algunos archivos no pudieron leerse:\n" + "\n".join(st.session_state.pdf_errores))

    df_crudo = st.session_state.get("df_crudo", pd.DataFrame())
    df_bloques = st.session_state.get("df_bloques", pd.DataFrame())

    if not st.session_state.agenda_procesada or df_bloques.empty:
        st.info("Cuando proceses el PDF, aparecerá el calendario de disponibilidad de los recursos.")
        return

    col2, col3 = st.columns(2)
    col2.metric("Bloques ocupados", f"{len(df_bloques):,}")
    col3.metric("Recursos detectados", int(df_bloques["recurso"].nunique()))

    st.markdown("### Calendario disponibilidad recursos")
    recursos_presentes = ordenar_recursos(df_bloques["recurso"].dropna().unique().tolist())
    recursos_nombre_a_codigo = {RECURSOS_EMO[r]["nombre"]: r for r in recursos_presentes}
    recursos_nombres = [RECURSOS_EMO[r]["nombre"] for r in recursos_presentes]

    if not st.session_state.recursos_calendario_sel:
        st.session_state.recursos_calendario_sel = recursos_nombres

    with st.form("form_filtros_calendario", clear_on_submit=False):
        col_f1, col_f2, col_f3 = st.columns([1.8, 1.0, 0.8], vertical_alignment="bottom")
        with col_f1:
            recursos_sel_nombre_tmp = st.multiselect(
                "Especialidades a mostrar",
                options=recursos_nombres,
                default=[r for r in st.session_state.recursos_calendario_sel if r in recursos_nombres] or recursos_nombres,
            )
        with col_f2:
            filtrar_horario_tmp = st.checkbox(
                "Solo horario EMO ajustado",
                value=bool(st.session_state.filtrar_horario_emo),
            )
        with col_f3:
            aplicar_filtros = st.form_submit_button("Actualizar calendario", use_container_width=True)

    if aplicar_filtros:
        st.session_state.recursos_calendario_sel = recursos_sel_nombre_tmp
        st.session_state.filtrar_horario_emo = filtrar_horario_tmp
        st.session_state.idx_fecha_calendario = 0

    recursos_sel = [recursos_nombre_a_codigo[n] for n in st.session_state.recursos_calendario_sel if n in recursos_nombre_a_codigo]
    if not recursos_sel:
        st.warning("Selecciona al menos una especialidad para mostrar.")
        return

    df_base = df_bloques[df_bloques["recurso"].isin(recursos_sel)].copy()
    if st.session_state.filtrar_horario_emo:
        df_base = df_base[df_base["dentro_horario_emo"]].copy()

    fechas_disponibles = sorted(df_base["fecha_dt"].dt.date.dropna().unique().tolist())
    if not fechas_disponibles:
        st.warning("No hay bloques para mostrar con los filtros seleccionados.")
        return

    st.session_state.idx_fecha_calendario = max(0, min(int(st.session_state.idx_fecha_calendario), len(fechas_disponibles) - 1))

    def mover_fecha(delta: int) -> None:
        st.session_state.idx_fecha_calendario = max(0, min(int(st.session_state.idx_fecha_calendario) + delta, len(fechas_disponibles) - 1))

    cprev, cfecha, cnext = st.columns([0.8, 2.4, 0.8], vertical_alignment="center")
    with cprev:
        st.button("Día anterior", use_container_width=True, disabled=st.session_state.idx_fecha_calendario == 0, on_click=mover_fecha, args=(-1,))
    with cnext:
        st.button("Día siguiente", use_container_width=True, disabled=st.session_state.idx_fecha_calendario == len(fechas_disponibles) - 1, on_click=mover_fecha, args=(1,))

    fecha_actual = fechas_disponibles[st.session_state.idx_fecha_calendario]
    with cfecha:
        st.markdown(f"<div style='text-align:center; font-size:22px; font-weight:700; color:#17324d;'>{formatear_fecha_larga(fecha_actual)}</div>", unsafe_allow_html=True)

    df_dia = df_base[df_base["fecha_dt"].dt.date == fecha_actual].copy()
    html_cal = construir_html_calendario_dia(
        df_dia_ocupados=df_dia,
        fecha_dia=fecha_actual,
        recursos_ordenados=ordenar_recursos(recursos_sel),
        titulo="Calendario de ocupación",
        subtitulo="",
    )
    components.html(html_cal, height=930, scrolling=True)

    if st.checkbox("Mostrar tabla del día seleccionado", value=False):
        columnas = ["archivo", "fecha_iso", "recurso_nombre", "codigo_medico", "nombre_medico", "especialidad_pdf", "hora_inicio_txt_corta", "hora_fin_txt", "inicio_iso", "fin_iso", "duracion_min", "cita_no", "consultorio", "dentro_horario_emo"]
        st.dataframe(df_dia[columnas].sort_values(["recurso_nombre", "hora_inicio_txt_corta"]), use_container_width=True, hide_index=True)
        csv = df_base[columnas].to_csv(index=False).encode("utf-8-sig")
        st.download_button("Descargar bloques ocupados en CSV", data=csv, file_name="bloques_ocupados_hosvital.csv", mime="text/csv")

    if st.checkbox("Mostrar diagnóstico de especialidades encontradas", value=False):
        diag = df_crudo[["archivo", "pagina", "fecha_txt", "codigo_medico", "nombre_medico", "especialidad_pdf", "recurso_nombre"]].drop_duplicates().sort_values(["archivo", "pagina"])
        st.dataframe(diag, use_container_width=True, hide_index=True)



def modulo_pacientes() -> None:
    st.markdown("### 2. Registro de pacientes")
    st.caption("Registra los pacientes que se van a programar y los exámenes que requiere cada uno.")

    df_bloques = st.session_state.get("df_bloques", pd.DataFrame())
    if not df_bloques.empty:
        fecha_base_default = min(df_bloques["fecha_dt"].dt.date.dropna().unique().tolist())
        fecha_fin_default = max(df_bloques["fecha_dt"].dt.date.dropna().unique().tolist())
    else:
        fecha_base_default = date.today()
        fecha_fin_default = date.today() + timedelta(days=4)

    if st.session_state.horizonte_inicio is None:
        st.session_state.horizonte_inicio = fecha_base_default
    if st.session_state.horizonte_fin is None:
        st.session_state.horizonte_fin = fecha_fin_default

    with st.form("form_config_conjunto", clear_on_submit=False):
        col_c1, col_c2, col_c3 = st.columns([1.3, 0.7, 1.3], vertical_alignment="bottom")
        with col_c1:
            nombre_tmp = st.text_input("Nombre del grupo a programar", value=st.session_state.nombre_conjunto)
        with col_c2:
            num_tmp = st.number_input("Cantidad de pacientes", min_value=1, max_value=300, value=int(st.session_state.num_pacientes_config), step=1)
        with col_c3:
            horizonte_tmp = st.date_input(
                "Fechas disponibles para programar",
                value=(st.session_state.horizonte_inicio, st.session_state.horizonte_fin),
                format="DD/MM/YYYY",
            )
        guardar_config = st.form_submit_button("Actualizar grupo", use_container_width=True)

    if guardar_config:
        if isinstance(horizonte_tmp, (tuple, list)) and len(horizonte_tmp) == 2:
            h_ini, h_fin = horizonte_tmp
        else:
            h_ini, h_fin = fecha_base_default, fecha_fin_default
        if h_fin < h_ini:
            st.error("La fecha final debe ser mayor o igual a la fecha inicial.")
        else:
            cambio_num = int(num_tmp) != int(st.session_state.num_pacientes_config)
            st.session_state.nombre_conjunto = nombre_tmp.strip() or "Grupo EMO a programar"
            st.session_state.num_pacientes_config = int(num_tmp)
            st.session_state.horizonte_inicio = h_ini
            st.session_state.horizonte_fin = h_fin
            if cambio_num or st.session_state.pacientes_df.empty:
                ajustar_tabla_pacientes(int(num_tmp))
            st.success("Grupo actualizado.")

    if st.session_state.pacientes_df.empty or len(st.session_state.pacientes_df) != int(st.session_state.num_pacientes_config):
        ajustar_tabla_pacientes(int(st.session_state.num_pacientes_config))

    st.markdown("##### Información de pacientes")

    pacientes_editados = st.data_editor(
        st.session_state.pacientes_df,
        key="editor_pacientes_principal",
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "Paciente": st.column_config.TextColumn("Código interno", disabled=True),
            "Identificación": st.column_config.TextColumn("Identificación"),
            "Nombre": st.column_config.TextColumn("Nombre"),
            "Tipo de EMO": st.column_config.SelectboxColumn("Tipo de EMO", options=["Ingreso", "Periódico", "Egreso"], required=True),
            "Exámenes EMO a realizar": st.column_config.TextColumn("Exámenes a realizar"),
        },
    )

    st.markdown("##### Selección de paquete de exámenes")
    col_s1, col_s2, col_s3 = st.columns([1.1, 1.9, 0.8], vertical_alignment="bottom")
    etiquetas = ["Todos los pacientes"] + paciente_etiquetas()
    with col_s1:
        destino = st.selectbox("Aplicar a", options=etiquetas)
    with col_s2:
        examenes_sel = st.multiselect("Exámenes", options=EXAMENES_NOMBRES)
    with col_s3:
        aplicar = st.button("Aplicar paquete", use_container_width=True)

    if aplicar:
        if not examenes_sel:
            st.warning("Selecciona al menos un examen.")
        else:
            df = pacientes_editados.copy()
            texto_exam = examenes_a_texto(examenes_sel)
            if destino == "Todos los pacientes":
                df["Exámenes EMO a realizar"] = texto_exam
            else:
                pid = destino.split(" - ")[0]
                df.loc[df["Paciente"] == pid, "Exámenes EMO a realizar"] = texto_exam
            st.session_state.pacientes_df = df
            st.success("Paquete aplicado. El ID y nombre se conservaron.")
            st.rerun()

    if st.button("Guardar información de pacientes", type="primary", use_container_width=True):
        df = pacientes_editados.copy()
        df["Exámenes EMO a realizar"] = df["Exámenes EMO a realizar"].apply(examenes_a_texto)
        st.session_state.pacientes_df = df
        st.success("Información de pacientes guardada.")

    # EXÁMENES EXTERNOS
    df_pacientes = pacientes_editados.copy()

    df_pacientes["Exámenes EMO a realizar"] = (
        df_pacientes["Exámenes EMO a realizar"]
        .apply(examenes_a_texto)
    )

    registros_externos = []

    for _, row in df_pacientes.iterrows():

        examenes = examenes_texto_a_codigos(
            row["Exámenes EMO a realizar"]
        )

        if "IMAGENOLOGIA" in examenes:
            registros_externos.append(
                {
                    "Paciente": row["Paciente"],
                    "Examen": "imagenologia",
                }
            )

        if "OTROS_EXTERNOS" in examenes:
            registros_externos.append(
                {
                    "Paciente": row["Paciente"],
                    "Examen": "otros_externos",
                }
            )

    if registros_externos:

        claves_actuales = {
            (r["Paciente"], r["Examen"])
            for r in registros_externos
        }

        if claves_actuales != st.session_state.claves_externos:

            df_ext = st.session_state.examenes_externos_df.copy()

            if df_ext.empty:

                df_ext = pd.DataFrame([
                    {
                        "Paciente": r["Paciente"],
                        "Examen": r["Examen"],
                        "Fecha": "",
                        "Inicio": "",
                        "Fin": "",
                        "Resultado fecha": "",
                        "Resultado hora": "",
                    }
                    for r in registros_externos
                ])

            else:

                claves_existentes = {
                    (row["Paciente"], row["Examen"])
                    for _, row in df_ext.iterrows()
                }

                # agregar filas nuevas
                for paciente, examen in (
                    claves_actuales - claves_existentes
                ):

                    df_ext.loc[len(df_ext)] = {
                        "Paciente": paciente,
                        "Examen": examen,
                        "Fecha": "",
                        "Inicio": "",
                        "Fin": "",
                        "Resultado fecha": "",
                        "Resultado hora": "",
                    }

                # eliminar filas que ya no aplican
                df_ext = df_ext[
                    df_ext.apply(
                        lambda r: (
                            r["Paciente"],
                            r["Examen"]
                        ) in claves_actuales,
                        axis=1
                    )
                ].reset_index(drop=True)

            st.session_state.examenes_externos_df = df_ext
            st.session_state.claves_externos = claves_actuales

        st.markdown("#### Registro de exámenes externos")

        df_externos_editado = st.data_editor(
            st.session_state.examenes_externos_df,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            key="tabla_examenes_externos",
        )

        st.session_state.examenes_externos_df = (
            df_externos_editado.copy()
        )

    else:

        st.session_state.examenes_externos_df = pd.DataFrame()
        st.session_state.claves_externos = set()

    col_m1, col_m2, col_m3 = st.columns(3)

    col_m1.metric(
        "Pacientes registrados",
        len(st.session_state.pacientes_df)
    )

    con_examenes = st.session_state.pacientes_df[
        "Exámenes EMO a realizar"
    ].apply(
        lambda x: len(normalizar_lista_examenes(x)) > 0
    ).sum()

    col_m2.metric(
        "Con exámenes asignados",
        int(con_examenes)
    )

    col_m3.metric(
        "Fechas",
        f"{st.session_state.horizonte_inicio.strftime('%d/%m')} - "
        f"{st.session_state.horizonte_fin.strftime('%d/%m')}"
    )


def modulo_disponibilidad() -> None:
    st.markdown("### 3. Disponibilidad de pacientes")
    st.caption("Registra los días y horarios en los que los pacientes pueden asistir al Centro Médico.")

    if st.session_state.pacientes_df.empty:
        st.info("Primero registra los pacientes.")
        return

    fechas_horizonte = rango_fechas(st.session_state.horizonte_inicio, st.session_state.horizonte_fin)
    if not fechas_horizonte:
        st.warning("Configura un rango de fechas válido en el módulo de pacientes.")
        return

    opciones = paciente_etiquetas()
    if not opciones:
        st.info("No hay pacientes disponibles para registrar disponibilidad.")
        return

    col_left, col_right = st.columns([0.95, 1.75], vertical_alignment="top")
    with col_left:
        st.markdown("#### Paciente a consultar")
        paciente_label = st.selectbox("Ver calendario de", options=opciones)
        paciente_id = paciente_label.split(" - ")[0]
        paciente_row = obtener_paciente_row(paciente_id)
        if paciente_row is None:
            st.stop()
        paciente_nombre = str(paciente_row.get("Nombre", "")).strip() or str(paciente_row.get("Identificación", "")).strip() or paciente_id
        recursos_requeridos = examenes_texto_a_codigos(paciente_row.get("Exámenes EMO a realizar", ""))
        if recursos_requeridos:
            st.success("Requiere: " + ", ".join(CODIGO_A_EXAMEN_NOMBRE[r] for r in recursos_requeridos))
        else:
            st.warning("Este paciente todavía no tiene exámenes asignados.")

        if st.button("Eliminar disponibilidad de este paciente", use_container_width=True):
            actuales = st.session_state.get("disponibilidades_pacientes", [])
            st.session_state.disponibilidades_pacientes = [x for x in actuales if x["paciente_id"] != paciente_id]
            st.warning("Disponibilidad eliminada para este paciente.")
            st.rerun()
    with col_right:

        st.markdown("#### Agregar disponibilidad")
        st.caption("Puedes registrar disponibilidad para un paciente, varios pacientes o todo el grupo.")

        modo_dias = st.selectbox(
            "Días disponibles",
            options=[
                "Un día específico",
                "Rango de fechas",
                "Días específicos"
            ],
            key="modo_dias_disponibilidad"
        )

        with st.form("form_disponibilidad", clear_on_submit=False):

            aplicar_a = st.multiselect(
                "Aplicar disponibilidad a",
                options=["Todos los pacientes"] + opciones,
                default=[paciente_label],
            )

            franja = st.selectbox(
                "Franja horaria",
                options=[
                    "Mañana completa (07:00-12:00)",
                    "Tarde completa (13:00-17:00)",
                    "Jornada completa (07:00-12:00 y 13:00-17:00)",
                    "Personalizada",
                ],
            )

            fechas_a_usar: List[date] = []

            if modo_dias == "Un día específico":
                fecha_unica = st.date_input(
                    "Día",
                    value=fechas_horizonte[0],
                    min_value=fechas_horizonte[0],
                    max_value=fechas_horizonte[-1],
                    format="DD/MM/YYYY"
                )
                fechas_a_usar = [fecha_unica]

            elif modo_dias == "Rango de fechas":
                col_r1, col_r2, col_r3 = st.columns([1.0, 1.0, 1.4])

                with col_r1:
                    fecha_inicio = st.date_input(
                        "Desde",
                        value=fechas_horizonte[0],
                        min_value=fechas_horizonte[0],
                        max_value=fechas_horizonte[-1],
                        format="DD/MM/YYYY"
                    )

                with col_r2:
                    fecha_fin = st.date_input(
                        "Hasta",
                        value=fechas_horizonte[-1],
                        min_value=fechas_horizonte[0],
                        max_value=fechas_horizonte[-1],
                        format="DD/MM/YYYY"
                    )

                with col_r3:
                    dias_semana = st.multiselect(
                        "Aplicar solo en",
                        options=DIAS_SEMANA_OPCIONES,
                        default=DIAS_SEMANA_OPCIONES[:5]
                    )

                if fecha_fin >= fecha_inicio:
                    nums = [DIAS_NOMBRE_A_NUM[d] for d in dias_semana]
                    fechas_a_usar = [
                        d for d in rango_fechas(fecha_inicio, fecha_fin)
                        if d.weekday() in nums
                    ]

            else:
                fechas_a_usar = st.multiselect(
                    "Selecciona los días",
                    options=fechas_horizonte,
                    default=fechas_horizonte[:1],
                    format_func=formatear_fecha_larga
                )

            st.caption("Si eliges una franja completa, los horarios personalizados se ignoran.")
            col_h1, col_h2 = st.columns(2)
            with col_h1:
                hora_ini_custom = st.time_input("Inicio personalizado", value=time(7, 0), step=timedelta(minutes=15))
            with col_h2:
                hora_fin_custom = st.time_input("Fin personalizado", value=time(17, 0), step=timedelta(minutes=15))

            guardar_disp = st.form_submit_button("Guardar disponibilidad", use_container_width=True)

        if guardar_disp:
            if not aplicar_a:
                st.warning("Selecciona al menos un paciente.")
            elif not fechas_a_usar:
                st.warning("No hay días seleccionados para guardar. Revisa el rango de fechas o los días de la semana.")
            else:
                if "Todos los pacientes" in aplicar_a:
                    etiquetas_objetivo = opciones
                else:
                    etiquetas_objetivo = aplicar_a
                total_agregados = 0
                for etiqueta in etiquetas_objetivo:
                    pid = etiqueta.split(" - ")[0]
                    row = obtener_paciente_row(pid)
                    if row is None:
                        continue
                    nombre_p = str(row.get("Nombre", "")).strip() or str(row.get("Identificación", "")).strip() or pid
                    total_agregados += guardar_disponibilidad(pid, nombre_p, fechas_a_usar, franja, hora_ini_custom, hora_fin_custom)
                st.success(f"Disponibilidad guardada. Intervalos nuevos agregados: {total_agregados}.")
                st.rerun()

    st.markdown("#### Calendario del paciente seleccionado")
    if not recursos_requeridos:
        st.info("Asigna exámenes al paciente para ver el calendario con las especialidades requeridas.")
        return

    st.session_state.idx_fecha_disp = max(0, min(int(st.session_state.idx_fecha_disp), len(fechas_horizonte) - 1))

    def mover_fecha_disp(delta: int) -> None:
        st.session_state.idx_fecha_disp = max(0, min(int(st.session_state.idx_fecha_disp) + delta, len(fechas_horizonte) - 1))

    cprev, cfecha, cnext = st.columns([0.8, 2.4, 0.8], vertical_alignment="center")
    with cprev:
        st.button("Día anterior", key="disp_prev", use_container_width=True, disabled=st.session_state.idx_fecha_disp == 0, on_click=mover_fecha_disp, args=(-1,))
    with cnext:
        st.button("Día siguiente", key="disp_next", use_container_width=True, disabled=st.session_state.idx_fecha_disp == len(fechas_horizonte) - 1, on_click=mover_fecha_disp, args=(1,))

    fecha_actual = fechas_horizonte[st.session_state.idx_fecha_disp]
    with cfecha:
        st.markdown(f"<div style='text-align:center; font-size:22px; font-weight:700; color:#17324d;'>{formatear_fecha_larga(fecha_actual)}</div>", unsafe_allow_html=True)

    df_bloques = st.session_state.get("df_bloques", pd.DataFrame())
    if not df_bloques.empty:
        df_ocupados = df_bloques[(df_bloques["fecha_dt"].dt.date == fecha_actual) & (df_bloques["recurso"].isin(recursos_requeridos))].copy()
    else:
        df_ocupados = pd.DataFrame()

    df_disp_all = disponibilidades_a_dataframe()
    if not df_disp_all.empty:
        df_disp_paciente = df_disp_all[(df_disp_all["paciente_id"] == paciente_id) & (df_disp_all["inicio_dt"].dt.date == fecha_actual)].copy()
    else:
        df_disp_paciente = pd.DataFrame()

    df_disp_cal = construir_df_disponibilidad_calendario(df_disp_paciente, recursos_requeridos)
    html_cal = construir_html_calendario_dia(
        df_dia_ocupados=df_ocupados,
        fecha_dia=fecha_actual,
        recursos_ordenados=recursos_requeridos,
        titulo=f"Disponibilidad de {paciente_nombre}",
        subtitulo="Verde = disponibilidad del paciente; color sólido = horario ocupado del especialista.",
        df_dia_disponibilidad=df_disp_cal,
        mostrar_nota_privacidad=False,
    )
    components.html(html_cal, height=900, scrolling=True)

    if st.checkbox("Mostrar disponibilidad guardada del paciente", value=False):
        df_disp_paciente_all = df_disp_all[df_disp_all["paciente_id"] == paciente_id].copy() if not df_disp_all.empty else pd.DataFrame()
        if df_disp_paciente_all.empty:
            st.info("Este paciente todavía no tiene disponibilidad guardada.")
        else:
            st.dataframe(df_disp_paciente_all[["paciente_id", "paciente_nombre", "fecha", "hora_inicio", "hora_fin"]].sort_values(["fecha", "hora_inicio"]), use_container_width=True, hide_index=True)




def construir_datos_modelo() -> Dict[str, Any]:
    pacientes_modelo = []
    df_pac = st.session_state.get("pacientes_df", pd.DataFrame())
    for _, row in df_pac.iterrows():
        examenes_cod = examenes_texto_a_codigos(row.get("Exámenes EMO a realizar", ""))
        pacientes_modelo.append(
            {
                "paciente_id": str(row.get("Paciente", "")).strip(),
                "identificacion": str(row.get("Identificación", "")).strip(),
                "nombre": str(row.get("Nombre", "")).strip(),
                "tipo_emo": str(row.get("Tipo de EMO", "")).strip(),
                "examenes_requeridos": examenes_cod,
                "examenes_requeridos_nombres": [CODIGO_A_EXAMEN_NOMBRE[c] for c in examenes_cod],
            }
        )

    df_bloques = st.session_state.get("df_bloques", pd.DataFrame())
    columnas_bloques = ["fecha_iso", "recurso", "recurso_nombre", "codigo_medico", "nombre_medico", "inicio_iso", "fin_iso", "duracion_min", "cita_no", "consultorio"]
    if not df_bloques.empty:
        bloques_ocupados = df_bloques[columnas_bloques].sort_values(["fecha_iso", "recurso", "inicio_iso"]).to_dict("records")
    else:
        bloques_ocupados = []

    fechas_horizonte = rango_fechas(st.session_state.horizonte_inicio, st.session_state.horizonte_fin)
    bloques_almuerzo = []
    for fecha_dia in fechas_horizonte:
        for recurso in RECURSOS_EMO.keys():
            bloques_almuerzo.append(
                {
                    "fecha": fecha_dia.isoformat(),
                    "recurso": recurso,
                    "recurso_nombre": CODIGO_A_EXAMEN_NOMBRE[recurso],
                    "inicio": f"{fecha_dia.isoformat()} {ALMUERZO_INICIO}",
                    "fin": f"{fecha_dia.isoformat()} {ALMUERZO_FIN}",
                    "tipo_bloqueo": "ALMUERZO_RECESO",
                }
            )

    return {
        "nombre_conjunto": st.session_state.nombre_conjunto,
        "horizonte_programacion": {
            "fecha_inicio": st.session_state.horizonte_inicio.isoformat(),
            "fecha_fin": st.session_state.horizonte_fin.isoformat(),
        },
        "duraciones_estandar_min": {codigo: cfg["duracion_min"] for codigo, cfg in RECURSOS_EMO.items()},
        "bloque_almuerzo_receso": {"inicio": ALMUERZO_INICIO, "fin": ALMUERZO_FIN, "aplica_a": "todos_los_recursos_y_pacientes"},
        "pacientes": pacientes_modelo,
        "disponibilidad_pacientes": st.session_state.get("disponibilidades_pacientes", []),
        "bloques_ocupados_hosvital": bloques_ocupados,
        "bloques_fijos_almuerzo": bloques_almuerzo,
    }

from datetime import datetime
import streamlit as st

def modulo_ajustes():

    ajustes = cargar_ajustes()

    st.subheader("Configuración del modelo")

    # SOLVER

    st.markdown("### Solver")

    tiempo_solver = st.number_input(
        "Tiempo máximo de ejecución (segundos)",
        min_value=60,
        value=int(ajustes["tiempo_solver"]),
        step=60
    )

    # DURACIONES

    st.markdown("### Duración de exámenes")

    nuevas_duraciones = {}

    for examen, duracion in ajustes["duraciones"].items():

        nuevas_duraciones[examen] = st.number_input(
            examen.replace("_", " ").title(),
            min_value=1,
            value=int(duracion),
            step=1
        )

    # HORARIOS

    st.markdown("### Horarios de especialistas")

    dias_semana = [
        "Lunes",
        "Martes",
        "Miércoles",
        "Jueves",
        "Viernes",
        "Sábado",
        "Domingo"
    ]

    nuevos_horarios = {}

    for recurso, dias in ajustes["horarios"].items():

        with st.expander(recurso, expanded=False):

            dias_actuales = list(dias.keys())

            dias_seleccionados = st.multiselect(
                "Días de atención",
                options=dias_semana,
                default=dias_actuales,
                key=f"dias_{recurso}"
            )

            nuevos_horarios[recurso] = {}

            for dia in dias_seleccionados:

                if dia in dias:

                    hora_ini_actual = dias[dia][0][0]
                    hora_fin_actual = dias[dia][0][1]

                else:

                    hora_ini_actual = "07:00"
                    hora_fin_actual = "17:00"

                col1, col2 = st.columns(2)

                with col1:

                    hora_inicio = st.time_input(
                        f"{dia} - Inicio",
                        value=datetime.strptime(
                            hora_ini_actual,
                            "%H:%M"
                        ).time(),
                        key=f"{recurso}_{dia}_inicio"
                    )

                with col2:

                    hora_fin = st.time_input(
                        f"{dia} - Fin",
                        value=datetime.strptime(
                            hora_fin_actual,
                            "%H:%M"
                        ).time(),
                        key=f"{recurso}_{dia}_fin"
                    )

                nuevos_horarios[recurso][dia] = [
                    [
                        hora_inicio.strftime("%H:%M"),
                        hora_fin.strftime("%H:%M")
                    ]
                ]

    if st.button(
        "Guardar ajustes",
        use_container_width=True
    ):

        ajustes["tiempo_solver"] = int(tiempo_solver)

        ajustes["duraciones"] = nuevas_duraciones

        ajustes["horarios"] = nuevos_horarios

        guardar_ajustes(ajustes)

        st.success(
            "Configuración guardada correctamente."
        )

        st.rerun()


    if st.button(
        "Restaurar configuración por defecto",
        use_container_width=True
    ):

        guardar_ajustes(AJUSTES_DEFAULT)

        st.success(
            "Configuración restaurada."
        )

        st.rerun()

# _______________________________________________________________________
# PREPARACIÓN DEL EXCEL DEL MODELO Y EJECUCIÓN DE LA PROGRAMACIÓN
# _______________________________________________________________________

COLUMNAS_MODELO_EXAMENES = [
    "paciente",
    "optometria",
    "laboratorios",
    "fonoaudiologia",
    "espirometria",
    "electrocardiograma",
    "imagenologia",
    "otros_externos",
]

MAPA_EXAMEN_APP_A_MODELO = {
    "OPTOMETRIA": "optometria",
    "LABORATORIO": "laboratorios",
    "FONOAUDIOLOGIA": "fonoaudiologia",
    "ESPIROMETRIA": "espirometria",
    "ELECTROCARDIOGRAMA": "electrocardiograma",
    "IMAGENOLOGIA": "imagenologia",
    "OTROS_EXTERNOS": "otros_externos",
    # Salud ocupacional no se envía como columna porque los modelos la agregan siempre.
    "SALUD OCUPACIONAL": "salud_ocupacional",

}

MAPA_RECURSO_APP_A_MODELO = {
    "OPTOMETRIA": "optometra",
    "LABORATORIO": "tecnico_laboratorios",
    "FONOAUDIOLOGIA": "fonoaudiologa",
    "SALUD OCUPACIONAL": "medico_ocupacional",
    "ESPIROMETRIA": "fisioterapeuta",
    "ELECTROCARDIOGRAMA": "enfermera",
}

RECURSO_MODELO_A_NOMBRE = {
    "optometra": "Optometría",
    "tecnico_laboratorios": "Laboratorio",
    "fonoaudiologa": "Fonoaudiología",
    "medico_ocupacional": "Salud ocupacional",
    "fisioterapeuta": "Espirometría",
    "enfermera": "Electrocardiograma",
    "externo": "Externo",
}

ESPECIALIDAD_MODELO_A_NOMBRE = {
    "optometria": "Optometría",
    "laboratorios": "Laboratorio",
    "fonoaudiologia": "Fonoaudiología",
    "espirometria": "Espirometría",
    "electrocardiograma": "Electrocardiograma",
    "imagenologia": "Imágenes diagnósticas",
    "otros_externos": "Otros externos",
    "salud_ocupacional": "Salud ocupacional",
}

DISPONIBILIDAD_RECURSOS_MODELO = {
    "optometra": {0: [("13:00", "17:00")], 1: [("13:00", "17:00")], 2: [("13:00", "17:00")], 3: [("13:00", "17:00")], 4: [("13:00", "17:00")]},
    "tecnico_laboratorios": {0: [("07:00", "10:00")], 1: [("07:00", "10:00")], 2: [("07:00", "10:00")], 3: [("07:00", "10:00")], 4: [("07:00", "10:00")]},
    "fonoaudiologa": {0: [("09:00", "11:30")], 3: [("09:00", "11:30")]},
    "medico_ocupacional": {0: [("13:00", "17:00")], 3: [("13:00", "17:00")]},
    "fisioterapeuta": {0: [("13:00", "17:00")], 2: [("13:00", "17:00")], 4: [("13:00", "17:00")]},
    "enfermera": {0: [("07:00", "12:00"), ("13:00", "17:00")], 1: [("07:00", "12:00"), ("13:00", "17:00")], 2: [("07:00", "12:00"), ("13:00", "17:00")], 3: [("07:00", "12:00"), ("13:00", "17:00")], 4: [("07:00", "12:00"), ("13:00", "17:00")]},
}


def preparar_tabla_examenes_modelo() -> Tuple[pd.DataFrame, List[str]]:
    """Convierte la tabla editable de pacientes al formato exacto de los modelos."""
    df_pac = st.session_state.get("pacientes_df", pd.DataFrame()).copy()
    filas = []
    advertencias = []

    for _, row in df_pac.iterrows():
        paciente = str(row.get("Paciente", "")).strip()
        if not paciente:
            continue
        fila = {col: 0 for col in COLUMNAS_MODELO_EXAMENES}
        fila["paciente"] = paciente
        for codigo_app in examenes_texto_a_codigos(row.get("Exámenes EMO a realizar", "")):
            examen_modelo = MAPA_EXAMEN_APP_A_MODELO.get(codigo_app)
            if examen_modelo is None:
                advertencias.append(
                    f"El examen/recurso '{CODIGO_A_EXAMEN_NOMBRE.get(codigo_app, codigo_app)}' del paciente {paciente} no existe como examen interno/externo en el modelo y no se enviará."
                )
                continue
            if examen_modelo == "salud_ocupacional":
                # El modelo la agrega automáticamente a todos los pacientes.
                continue
            if examen_modelo in fila:
                fila[examen_modelo] = 1
        filas.append(fila)

    return pd.DataFrame(filas, columns=COLUMNAS_MODELO_EXAMENES), advertencias


def preparar_disponibilidad_pacientes_modelo() -> pd.DataFrame:
    disp = st.session_state.get("disponibilidades_pacientes", [])
    filas = []
    for item in disp:
        paciente = str(item.get("paciente_id", "")).strip()
        fecha = item.get("fecha")
        hora_inicio = item.get("hora_inicio")
        hora_fin = item.get("hora_fin")
        if paciente and fecha and hora_inicio and hora_fin:
            filas.append({
                "paciente": paciente,
                "fecha": fecha,
                "inicio": hora_inicio,
                "fin": hora_fin,
            })
    return pd.DataFrame(filas, columns=["paciente", "fecha", "inicio", "fin"])


def preparar_disponibilidad_recursos_modelo() -> pd.DataFrame:

    ajustes = cargar_ajustes()

    horarios = convertir_horarios_json(
        ajustes["horarios"]
    )

    mapa_recursos = {
        "OPTOMETRIA": "optometra",
        "FONOAUDIOLOGIA": "fonoaudiologa",
        "SALUD OCUPACIONAL": "medico_ocupacional",
        "FISIOTERAPIA": "fisioterapeuta",
    }

    filas = []

    for fecha_dia in rango_fechas(
        st.session_state.horizonte_inicio,
        st.session_state.horizonte_fin
    ):

        wd = int(pd.Timestamp(fecha_dia).weekday())

        for recurso_app, dias in horarios.items():

            recurso_modelo = mapa_recursos.get(recurso_app)

            if recurso_modelo is None:
                continue

            for h_ini, h_fin in dias.get(wd, []):

                filas.append(
                    {
                        "recurso": recurso_modelo,
                        "fecha": fecha_dia.isoformat(),
                        "inicio": h_ini,
                        "fin": h_fin,
                    }
                )

    return pd.DataFrame(
        filas,
        columns=[
            "recurso",
            "fecha",
            "inicio",
            "fin"
        ]
    )

def preparar_bloques_ocupados_modelo() -> Tuple[pd.DataFrame, List[str]]:
    df_bloques = st.session_state.get("df_bloques", pd.DataFrame()).copy()
    filas = []
    advertencias = []
    if df_bloques.empty:
        return pd.DataFrame(columns=["recurso", "fecha", "inicio", "fin"]), advertencias

    for _, row in df_bloques.iterrows():
        recurso_app = row.get("recurso")
        recurso_modelo = MAPA_RECURSO_APP_A_MODELO.get(recurso_app)
        if recurso_modelo is None:
            continue
        inicio = pd.to_datetime(row.get("inicio"), errors="coerce")
        fin = pd.to_datetime(row.get("fin"), errors="coerce")
        if pd.isna(inicio) or pd.isna(fin):
            continue
        filas.append({
            "recurso": recurso_modelo,
            "fecha": inicio.date().isoformat(),
            "inicio": inicio.strftime("%H:%M"),
            "fin": fin.strftime("%H:%M"),
        })
    return pd.DataFrame(filas, columns=["recurso", "fecha", "inicio", "fin"]), advertencias


def escribir_seccion_excel(writer, sheet_name: str, marcador: str, df: pd.DataFrame, fila_inicio: int) -> int:
    """Escribe una sección tipo [MARCADOR] en una hoja de Excel."""
    workbook = writer.book
    if sheet_name in writer.sheets:
        ws = writer.sheets[sheet_name]
    else:
        ws = workbook.create_sheet(sheet_name)
        writer.sheets[sheet_name] = ws
    ws.cell(row=fila_inicio + 1, column=1, value=marcador)
    for j, col in enumerate(df.columns, start=1):
        ws.cell(row=fila_inicio + 2, column=j, value=col)
    for i, (_, row) in enumerate(df.iterrows(), start=fila_inicio + 3):
        for j, col in enumerate(df.columns, start=1):
            ws.cell(row=i, column=j, value=row[col])
    return fila_inicio + len(df) + 4


def generar_excel_escenario_modelo(ruta_excel: str) -> Dict[str, Any]:
    """Genera el Excel por secciones que lee el modelo de programación."""

    examenes_df, adv_examenes = preparar_tabla_examenes_modelo()
    disp_pac_df = preparar_disponibilidad_pacientes_modelo()
    disp_rec_df = preparar_disponibilidad_recursos_modelo()
    bloques_df, adv_bloques = preparar_bloques_ocupados_modelo()

    examenes_externos_df = (
        st.session_state.get(
            "examenes_externos_df",
            pd.DataFrame()
        ).copy()
    )

    if not examenes_externos_df.empty:

        examenes_externos_df = examenes_externos_df.rename(
            columns={
                "Paciente": "paciente",
                "Examen": "examen",
                "Fecha": "fecha",
                "Inicio": "inicio",
                "Fin": "fin",
                "Resultado fecha": "resultado_fecha",
                "Resultado hora": "resultado_hora",
            }
        )

        # Normalizar texto
        for col in [
            "paciente",
            "examen",
            "fecha",
            "inicio",
            "fin",
            "resultado_fecha",
            "resultado_hora",
        ]:

            if col in examenes_externos_df.columns:

                examenes_externos_df[col] = (
                    examenes_externos_df[col]
                    .fillna("")
                    .astype(str)
                    .str.strip()
                )

    else:

        examenes_externos_df = pd.DataFrame(
            columns=[
                "paciente",
                "examen",
                "fecha",
                "inicio",
                "fin",
                "resultado_fecha",
                "resultado_hora",
            ]
        )

    festivos_df = pd.DataFrame(columns=["fecha"])

    with pd.ExcelWriter(ruta_excel, engine="openpyxl") as writer:
        sheet = "escenario_1"
        # Crear hoja vacía inicial.
        pd.DataFrame().to_excel(writer, sheet_name=sheet, index=False, header=False)
        fila = 0
        fila = escribir_seccion_excel(writer, sheet, "[EXAMENES_PACIENTE]", examenes_df, fila)
        fila = escribir_seccion_excel(writer, sheet, "[DISPONIBILIDAD_PACIENTES]", disp_pac_df, fila)
        fila = escribir_seccion_excel(writer, sheet, "[DISPONIBILIDAD_RECURSOS]", disp_rec_df, fila)
        fila = escribir_seccion_excel(writer, sheet, "[BLOQUES_OCUPADOS]", bloques_df, fila)
        fila = escribir_seccion_excel(writer, sheet, "[EXAMENES_EXTERNOS]", examenes_externos_df, fila)
        fila = escribir_seccion_excel(writer, sheet, "[FESTIVOS]", festivos_df, fila)

    return {
        "examenes_paciente": examenes_df,
        "disponibilidad_pacientes": disp_pac_df,
        "disponibilidad_recursos": disp_rec_df,
        "bloques_ocupados": bloques_df,
        "advertencias": adv_examenes + adv_bloques,
    }


def extraer_resumen_resultado(nombre_metodo: str, resultado: Optional[dict]) -> pd.DataFrame:
    if not resultado:
        return pd.DataFrame([{
            "metodo": "Programación",
            "estado_solucion": "Sin programación retornada",
        }])
    resumen = resultado.get("metricas", {}).get("resumen_metricas", pd.DataFrame()).copy()
    if resumen.empty:
        return pd.DataFrame([{"metodo": "Programación", "estado_solucion": resultado.get("estado", "No disponible")}])
    resumen["metodo_app"] = "Programación"
    return resumen

def obtener_agenda_resultado(nombre_metodo: str, resultado: Optional[dict]) -> pd.DataFrame:
    if not resultado:
        return pd.DataFrame()
    agenda = resultado.get("agenda_paciente", pd.DataFrame()).copy()
    if agenda.empty and "agenda" in resultado:
        agenda = resultado.get("agenda", pd.DataFrame()).copy()
    if not agenda.empty:
        agenda["metodo"] = nombre_metodo
    return agenda


def obtener_lookup_pacientes_app() -> pd.DataFrame:
    """Devuelve datos de identificación, nombre y tipo de EMO digitados en la interfaz."""
    df_pac = st.session_state.get("pacientes_df", pd.DataFrame()).copy()
    if df_pac.empty or "Paciente" not in df_pac.columns:
        return pd.DataFrame(columns=["paciente", "identificacion", "nombre_paciente", "tipo_emo"])

    rename_map = {}
    if "Paciente" in df_pac.columns:
        rename_map["Paciente"] = "paciente"
    if "Identificación" in df_pac.columns:
        rename_map["Identificación"] = "identificacion"
    if "Nombre" in df_pac.columns:
        rename_map["Nombre"] = "nombre_paciente"
    if "Tipo de EMO" in df_pac.columns:
        rename_map["Tipo de EMO"] = "tipo_emo"

    out = df_pac.rename(columns=rename_map)
    for col in ["paciente", "identificacion", "nombre_paciente", "tipo_emo"]:
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].astype(str).fillna("").str.strip()
    return out[["paciente", "identificacion", "nombre_paciente", "tipo_emo"]].drop_duplicates("paciente", keep="first")


def enriquecer_agenda_con_pacientes(agenda: pd.DataFrame) -> pd.DataFrame:
    """Agrega a la agenda final el nombre, identificación y una etiqueta legible del paciente."""
    if agenda is None or agenda.empty:
        return pd.DataFrame()

    df = agenda.copy()
    if "paciente" not in df.columns:
        df["paciente"] = ""
    df["paciente"] = df["paciente"].astype(str).fillna("").str.strip()

    lookup = obtener_lookup_pacientes_app()
    if not lookup.empty:
        # Evita duplicar columnas si el modelo ya devolvió alguna información de paciente.
        for col in ["identificacion", "nombre_paciente", "tipo_emo"]:
            if col in df.columns:
                df = df.drop(columns=[col])
        df = df.merge(lookup, on="paciente", how="left")

    for col in ["identificacion", "nombre_paciente", "tipo_emo"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].astype(str).fillna("").str.strip()

    def construir_etiqueta(row: pd.Series) -> str:
        paciente = str(row.get("paciente", "")).strip()
        nombre = str(row.get("nombre_paciente", "")).strip()
        identificacion = str(row.get("identificacion", "")).strip()
        partes = []
        if paciente:
            partes.append(paciente)
        if nombre:
            partes.append(nombre)
        elif identificacion:
            partes.append(f"ID {identificacion}")
        return " · ".join(partes) if partes else "Paciente sin identificar"

    df["paciente_etiqueta"] = df.apply(construir_etiqueta, axis=1)
    return df


def obtener_objetivo_comparable(nombre_metodo: str, resultado: Optional[dict]) -> float:
    if not resultado:
        return float("inf")
    if nombre_metodo == "MILP":
        resumen = resultado.get("metricas", {}).get("resumen_metricas", pd.DataFrame())
        if not resumen.empty:
            for col in ["valor_objetivo", "tiempo_total_sistema_min"]:
                if col in resumen.columns and pd.notna(resumen.iloc[0].get(col)):
                    return float(resumen.iloc[0][col])
        solve = resultado.get("resultado_solve", {})
        if solve.get("valor_objetivo") is not None:
            return float(solve.get("valor_objetivo"))
        return float("inf")
    resumen = resultado.get("resumen", pd.DataFrame())
    if not resumen.empty:
        for col in ["objetivo", "tiempo_total_sistema_min"]:
            if col in resumen.columns and pd.notna(resumen.iloc[0].get(col)):
                return float(resumen.iloc[0][col])
    return float("inf")


def es_optimo_milp(resultado: Optional[dict]) -> bool:
    if not resultado:
        return False
    return str(resultado.get("estado", "")).lower() == "optimal"


def dependencia_disponible(nombre_modulo: str) -> bool:
    """Valida si una librería está instalada sin romper la app."""
    try:
        return importlib.util.find_spec(nombre_modulo) is not None
    except Exception:
        return False


def minutos_hhmm(valor: Any) -> Optional[int]:
    try:
        if isinstance(valor, time):
            return valor.hour * 60 + valor.minute
        txt = str(valor).strip()[:5]
        h, m = txt.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def intervalos_se_intersectan(inicio_a: Any, fin_a: Any, inicio_b: Any, fin_b: Any) -> bool:
    a1 = minutos_hhmm(inicio_a)
    a2 = minutos_hhmm(fin_a)
    b1 = minutos_hhmm(inicio_b)
    b2 = minutos_hhmm(fin_b)
    if None in [a1, a2, b1, b2]:
        return False
    return max(a1, b1) < min(a2, b2)


def validar_datos_antes_modelo(tablas: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """
    Diagnóstico rápido antes de llamar el solver.
    No reemplaza al modelo, pero evita ejecutarlo cuando hay errores estructurales claros.
    """
    errores: List[str] = []
    advertencias: List[str] = []

    examenes = tablas.get("examenes_paciente", pd.DataFrame())
    disp_pac = tablas.get("disponibilidad_pacientes", pd.DataFrame())
    disp_rec = tablas.get("disponibilidad_recursos", pd.DataFrame())

    if examenes.empty:
        errores.append("No hay pacientes válidos con identificación para enviar al modelo.")
    if disp_pac.empty:
        errores.append("No hay disponibilidad registrada para los pacientes.")
    if disp_rec.empty:
        errores.append("No hay disponibilidad de recursos dentro del horizonte seleccionado.")
    if errores:
        return errores, advertencias

    pacientes = set(examenes["paciente"].astype(str))
    pacientes_con_disp = set(disp_pac["paciente"].astype(str)) if "paciente" in disp_pac.columns else set()
    sin_disp = sorted(pacientes - pacientes_con_disp)
    if sin_disp:
        errores.append("Hay pacientes sin disponibilidad registrada: " + ", ".join(sin_disp[:8]) + ("..." if len(sin_disp) > 8 else ""))

    # Todos los pacientes requieren salud ocupacional porque el modelo la agrega automáticamente.
    fechas_med_ocup = set(disp_rec.loc[disp_rec["recurso"].astype(str) == "medico_ocupacional", "fecha"].astype(str)) if not disp_rec.empty else set()
    if not fechas_med_ocup:
        errores.append("El horizonte no contiene disponibilidad de salud ocupacional. Recuerda que en el modelo está lunes y jueves de 13:00 a 17:00.")

    recurso_por_examen = {
        "optometria": "optometra",
        "laboratorios": "tecnico_laboratorios",
        "fonoaudiologia": "fonoaudiologa",
        "espirometria": "fisioterapeuta",
        "electrocardiograma": "enfermera",
        "salud_ocupacional": "medico_ocupacional",
    }

    for _, row in examenes.iterrows():
        paciente = str(row.get("paciente", "")).strip()
        if not paciente:
            continue
        disp_p = disp_pac[disp_pac["paciente"].astype(str) == paciente]
        if disp_p.empty:
            continue

        examenes_req = [c for c in COLUMNAS_MODELO_EXAMENES if c != "paciente" and int(row.get(c, 0) or 0) == 1]
        examenes_req.append("salud_ocupacional")

        for examen in examenes_req:
            recurso = recurso_por_examen.get(examen)
            if recurso is None:
                # Exámenes externos: no consumen recurso interno, se validan dentro del modelo.
                continue
            disp_r = disp_rec[disp_rec["recurso"].astype(str) == recurso]
            if disp_r.empty:
                errores.append(f"El paciente {paciente} requiere {ESPECIALIDAD_MODELO_A_NOMBRE.get(examen, examen)}, pero el recurso {RECURSO_MODELO_A_NOMBRE.get(recurso, recurso)} no tiene disponibilidad en el horizonte.")
                continue
            posible = False
            for _, dp in disp_p.iterrows():
                fecha_p = str(dp.get("fecha", ""))
                disp_r_fecha = disp_r[disp_r["fecha"].astype(str) == fecha_p]
                for _, dr in disp_r_fecha.iterrows():
                    if intervalos_se_intersectan(dp.get("inicio"), dp.get("fin"), dr.get("inicio"), dr.get("fin")):
                        posible = True
                        break
                if posible:
                    break
            if not posible:
                advertencias.append(f"Revisar disponibilidad: el paciente {paciente} requiere {ESPECIALIDAD_MODELO_A_NOMBRE.get(examen, examen)}, pero no se observa cruce directo entre su disponibilidad y la del recurso {RECURSO_MODELO_A_NOMBRE.get(recurso, recurso)}.")

    # Evitar que la misma advertencia se repita demasiado.
    advertencias = list(dict.fromkeys(advertencias))
    errores = list(dict.fromkeys(errores))
    return errores, advertencias[:25]


def es_milp_diagnostico(resultado: Optional[dict]) -> bool:
    if not resultado:
        return False
    modo = str(resultado.get("resultado_solve", {}).get("modo_objetivo", "")).lower()
    diag = resultado.get("diagnostico_no_programados", pd.DataFrame())
    return "diagnostico" in modo or (isinstance(diag, pd.DataFrame) and not diag.empty)


def es_solucion_factible_completa(nombre_metodo: str, resultado: Optional[dict]) -> bool:
    if not resultado:
        return False
    agenda = obtener_agenda_resultado(nombre_metodo, resultado)
    if agenda.empty:
        return False
    if nombre_metodo == "MILP":
        estado = str(resultado.get("estado", "")).lower()
        if estado in ["infeasible", "undefined", "unbounded"]:
            return False
        if es_milp_diagnostico(resultado):
            return False
        return True
    no_prog = resultado.get("no_programados", pd.DataFrame())
    if isinstance(no_prog, pd.DataFrame) and not no_prog.empty:
        return False
    resumen = resultado.get("resumen", pd.DataFrame())
    if isinstance(resumen, pd.DataFrame) and not resumen.empty:
        estado_ag = str(resumen.iloc[0].get("estado_solucion", "")).lower()
        return "factible" in estado_ag and "no program" not in estado_ag and "penal" not in estado_ag
    return False


def tabla_diagnostico_no_programados(nombre_metodo: str, resultado: Optional[dict]) -> pd.DataFrame:
    if not resultado:
        return pd.DataFrame()
    if nombre_metodo == "MILP":
        df = resultado.get("diagnostico_no_programados", pd.DataFrame())
    else:
        df = resultado.get("no_programados", pd.DataFrame())
    if isinstance(df, pd.DataFrame):
        return df.copy()
    return pd.DataFrame()


def seleccionar_mejor_factible(resultado_milp: Optional[dict], resultado_ag: Optional[dict] = None) -> Tuple[Optional[str], Optional[dict], float, float]:
    factible = es_solucion_factible_completa("MILP", resultado_milp)
    objetivo = obtener_objetivo_comparable("MILP", resultado_milp) if factible else float("inf")
    if not factible:
        return None, None, objetivo, float("inf")
    return "MILP", resultado_milp, objetivo, float("inf")

def ejecutar_modelos_desde_excel(ruta_excel: str) -> Dict[str, Any]:
    """Ejecuta únicamente el modelo de programación durante máximo 60 minutos."""
    import modelo_milp_app
    
    ajustes = cargar_ajustes()
    modelo_milp_app.TIME_LIMIT_SOLVER = ajustes["tiempo_solver"]
    modelo_milp_app.PESO_VISITAS = 0
    modelo_milp_app.HOJA_ESCENARIO = "escenario_1"
    modelo_milp_app.HORARIOS_RECURSOS = ajustes["horarios"]
    try:
        modelo_milp_app.LOG_SOLVER = f"log_solver_{modelo_milp_app.NOMBRE_SOLVER.lower()}_escenario_1.txt"
    except Exception:
        pass
    for examen, duracion in ajustes["duraciones"].items():
        modelo_milp_app.DURACIONES_ESTANDAR[examen] = duracion

    bitacora = []
    resultado_milp = None
    stdout_milp = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout_milp):
            resultado_milp = modelo_milp_app.ejecutar_programacion(
                archivo_escenarios=ruta_excel,
                hoja_escenario="escenario_1",
                permitir_no_programar=False,
                exportar=False,
            )
        bitacora.append("La programación finalizó.")
    except Exception as e:
        bitacora.append("No fue posible generar la programación: " + str(e))
        bitacora.append(traceback.format_exc())

    objetivo = obtener_objetivo_comparable("MILP", resultado_milp) if es_solucion_factible_completa("MILP", resultado_milp) else float("inf")
    if es_solucion_factible_completa("MILP", resultado_milp):
        bitacora.append("Se encontró una programación válida para todos los exámenes requeridos.")
    else:
        bitacora.append("No se encontró una programación completa con los datos actuales.")

    return {
        "resultado_milp": resultado_milp,
        "resultado_ag": None,
        "metodo_ganador": "MILP" if es_solucion_factible_completa("MILP", resultado_milp) else None,
        "resultado_ganador": resultado_milp if es_solucion_factible_completa("MILP", resultado_milp) else None,
        "objetivo_milp": objetivo,
        "objetivo_ag": None,
        "stdout_milp": stdout_milp.getvalue(),
        "stdout_ag": "",
        "bitacora": bitacora,
    }


def preparar_agenda_para_calendario(agenda: pd.DataFrame) -> pd.DataFrame:
    if agenda is None or agenda.empty:
        return pd.DataFrame()
    df = enriquecer_agenda_con_pacientes(agenda)
    # La agenda trae fecha y hora_inicio/hora_fin como texto.
    df["fecha_dt"] = pd.to_datetime(df["fecha"], errors="coerce")
    df["inicio"] = pd.to_datetime(df["fecha"].astype(str) + " " + df["hora_inicio"].astype(str), errors="coerce")
    df["fin"] = pd.to_datetime(df["fecha"].astype(str) + " " + df["hora_fin"].astype(str), errors="coerce")
    df["especialidad_nombre"] = df["especialidad"].apply(lambda x: ESPECIALIDAD_MODELO_A_NOMBRE.get(str(x), str(x))) if "especialidad" in df.columns else ""
    df["recurso_nombre"] = df["recurso"].apply(lambda x: RECURSO_MODELO_A_NOMBRE.get(str(x), str(x))) if "recurso" in df.columns else ""
    df["paciente"] = df["paciente"].astype(str)
    return df.dropna(subset=["fecha_dt", "inicio", "fin"])


def construir_html_calendario_resultados(df_agenda: pd.DataFrame, fecha_dia: date) -> str:
    df = preparar_agenda_para_calendario(df_agenda)
    df = df[df["fecha_dt"].dt.date == fecha_dia].copy()
    especialidades = sorted(df["especialidad_nombre"].unique().tolist()) if not df.empty else []
    if not especialidades:
        return "<div style='padding:20px; color:#64748b;'>No hay citas programadas para este día.</div>"

    hora_ini_min = 7 * 60
    hora_fin_min = 18 * 60
    alto_por_min = 1.35
    alto_total = int((hora_fin_min - hora_ini_min) * alto_por_min)
    col_w = 235
    time_w = 76
    colores = ["#3A86FF", "#2EC4B6", "#7B61FF", "#FFB703", "#EF476F", "#06D6A0", "#8D99AE", "#118AB2"]
    color_map = {esp: colores[i % len(colores)] for i, esp in enumerate(especialidades)}

    horas_html = []
    for h in range(7, 19):
        top = int(((h * 60) - hora_ini_min) * alto_por_min)
        horas_html.append(f"<div class='hour-line' style='top:{top}px;'></div>")
        horas_html.append(f"<div class='hour-label' style='top:{top-7}px;'>{h:02d}:00</div>")

    eventos_html = []
    for _, row in df.iterrows():
        esp = row["especialidad_nombre"]
        col_idx = especialidades.index(esp)
        ini = minutos_desde_medianoche(row["inicio"])
        fin = minutos_desde_medianoche(row["fin"])
        top = max(0, int((ini - hora_ini_min) * alto_por_min))
        height = max(18, int((fin - ini) * alto_por_min) - 2)
        left = time_w + col_idx * col_w + 6
        height = max(34, height)
        paciente_codigo = str(row.get("paciente", "")).strip()
        paciente_nombre = str(row.get("nombre_paciente", "")).strip()
        identificacion = str(row.get("identificacion", "")).strip()
        tipo_emo = str(row.get("tipo_emo", "")).strip()
        paciente_etiqueta = html.escape(str(row.get("paciente_etiqueta", paciente_codigo)))
        paciente_linea = html.escape(paciente_nombre if paciente_nombre else paciente_codigo)
        detalle_linea = []
        if paciente_codigo:
            detalle_linea.append(paciente_codigo)
        if identificacion:
            detalle_linea.append(f"ID {identificacion}")
        if tipo_emo:
            detalle_linea.append(tipo_emo)
        detalle_txt = html.escape(" · ".join(detalle_linea))
        recurso = html.escape(str(row.get("recurso_nombre", "")))
        hora_txt = f"{row['inicio'].strftime('%H:%M')} - {row['fin'].strftime('%H:%M')}"
        tooltip = html.escape(f"Paciente: {row.get('paciente_etiqueta', paciente_codigo)} | ID: {identificacion} | Tipo EMO: {tipo_emo} | Especialidad: {esp} | Recurso: {row.get('recurso_nombre', '')} | Hora: {hora_txt}")
        eventos_html.append(
            f"""
            <div class='event' title='{tooltip}' style='top:{top}px; left:{left}px; width:{col_w-12}px; height:{height}px; background:{color_map[esp]};'>
              <div class='event-time'>{hora_txt}</div>
              <div class='event-title'>{paciente_etiqueta}</div>
              <div class='event-sub'>{detalle_txt}</div>
              <div class='event-resource'>{recurso}</div>
            </div>
            """
        )

    headers = "".join(
        f"<div class='col-head' style='left:{time_w + i*col_w}px; width:{col_w}px;'>{html.escape(esp)}</div>"
        for i, esp in enumerate(especialidades)
    )
    grid_cols = "".join(
        f"<div class='col-bg' style='left:{time_w + i*col_w}px; width:{col_w}px; height:{alto_total}px;'></div>"
        for i in range(len(especialidades))
    )
    width_total = time_w + len(especialidades) * col_w
    fecha_txt = formatear_fecha_larga(fecha_dia)
    return f"""
    <style>
      .res-calendar-wrap {{ font-family: Arial, sans-serif; background:#f8fafc; border:1px solid #dbe3ee; border-radius:16px; padding:14px; overflow:auto; }}
      .res-title {{ font-size:20px; font-weight:800; color:#17324d; margin-bottom:8px; }}
      .res-calendar {{ position:relative; width:{width_total}px; height:{alto_total + 48}px; background:white; border-radius:12px; border:1px solid #e5e7eb; overflow:hidden; }}
      .col-head {{ position:absolute; top:0; height:44px; display:flex; align-items:center; justify-content:center; font-weight:700; color:#17324d; border-left:1px solid #e5e7eb; background:#eef4fb; text-align:center; font-size:13px; padding:0 4px; }}
      .col-bg {{ position:absolute; top:44px; border-left:1px solid #edf2f7; background:linear-gradient(#fff, #fff); }}
      .hour-line {{ position:absolute; left:0; right:0; border-top:1px solid #e5e7eb; z-index:1; transform:translateY(44px); }}
      .hour-label {{ position:absolute; left:8px; width:58px; font-size:12px; color:#64748b; z-index:2; transform:translateY(44px); }}
      .event {{ position:absolute; z-index:5; border-radius:10px; color:white; padding:5px 7px; box-sizing:border-box; box-shadow:0 2px 7px rgba(15,23,42,0.18); overflow:hidden; transform:translateY(44px); }}
      .event-time {{ font-size:11px; font-weight:700; line-height:1.05; }}
      .event-title {{ font-size:12px; font-weight:800; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; line-height:1.15; }}
      .event-sub {{ font-size:10px; opacity:0.95; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; line-height:1.15; }}
      .event-resource {{ font-size:10px; opacity:0.9; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; line-height:1.1; }}
    </style>
    <div class='res-calendar-wrap'>
      <div class='res-title'>Calendario de solución - {fecha_txt}</div>
      <div class='res-calendar'>
        {headers}
        {grid_cols}
        {''.join(horas_html)}
        {''.join(eventos_html)}
      </div>
    </div>
    """


def estado_amigable_resultado(resultado: Optional[dict]) -> Tuple[str, str]:
    if not resultado:
        return "Sin programación", "No se recibió una respuesta utilizable."
    diagnostico = resultado.get("resultado_solve", {}) or {}
    clasificacion = str(diagnostico.get("clasificacion", "") or "").upper()
    estado = str(resultado.get("estado", "") or diagnostico.get("estado_pulp", "") or "").upper()
    if clasificacion == "OPTIMA_COMPLETA" or estado == "OPTIMAL":
        return "Programación completa", "Se encontró la mejor programación posible con la información registrada."
    if "FACTIBLE" in clasificacion:
        return "Programación completa", "Se encontró una programación válida para todos los pacientes dentro del tiempo máximo de búsqueda."
    if "INFACTIBLE" in clasificacion:
        return "No fue posible programar todo", "Con las fechas, horarios y restricciones actuales no hay espacio suficiente para completar todos los exámenes."
    if "LIMITE" in clasificacion or "TIME" in estado:
        return "Sin programación completa", "Se agotó el tiempo máximo de búsqueda sin obtener una agenda completa."
    return "Revisar resultado", "No fue posible confirmar una programación completa. Revisa la información cargada y los mensajes de la bitácora."


def construir_resumen_ejecutivo(resultado: Optional[dict], agenda: pd.DataFrame) -> pd.DataFrame:
    if resultado is None:
        return pd.DataFrame()
    metricas = resultado.get("metricas", {}) if isinstance(resultado, dict) else {}
    resumen = metricas.get("resumen_metricas", pd.DataFrame()) if isinstance(metricas, dict) else pd.DataFrame()
    estado_txt, _ = estado_amigable_resultado(resultado)
    filas = []

    def agregar(indicador, valor):
        filas.append({"Indicador": indicador, "Valor": valor})

    agregar("Estado de la programación", estado_txt)
    agregar("Pacientes programados", agenda["paciente"].nunique() if isinstance(agenda, pd.DataFrame) and not agenda.empty and "paciente" in agenda.columns else 0)
    agregar("Citas programadas", len(agenda) if isinstance(agenda, pd.DataFrame) else 0)

    if isinstance(resumen, pd.DataFrame) and not resumen.empty:
        r = resumen.iloc[0].to_dict()
        campos = [
            ("Tiempo total en el sistema", "tiempo_total_sistema_min", " min"),
            ("Tiempo promedio por paciente", "tiempo_promedio_sistema_min", " min"),
            ("Número promedio de visitas", "numero_promedio_visitas", ""),
            ("Pacientes en una sola visita", "porcentaje_pacientes_1_visita", "%"),
            ("Pacientes con dos o más visitas", "porcentaje_pacientes_2_o_mas_visitas", "%"),
            ("Espera promedio entre citas", "espera_promedio_entre_citas_min", " min"),
        ]
        for nombre, campo, sufijo in campos:
            if campo in r and pd.notna(r[campo]):
                val = r[campo]
                if isinstance(val, float):
                    val = round(val, 2)
                agregar(nombre, f"{val}{sufijo}")
    return pd.DataFrame(filas)


def preparar_agenda_por_paciente(agenda: pd.DataFrame) -> pd.DataFrame:
    if agenda is None or agenda.empty:
        return pd.DataFrame()
    df = enriquecer_agenda_con_pacientes(agenda)
    if "especialidad" in df.columns:
        df["examen"] = df["especialidad"].apply(lambda x: ESPECIALIDAD_MODELO_A_NOMBRE.get(str(x), str(x)))
    if "recurso" in df.columns:
        df["recurso_atencion"] = df["recurso"].apply(lambda x: RECURSO_MODELO_A_NOMBRE.get(str(x), str(x)))
    columnas = ["paciente", "identificacion", "nombre_paciente", "tipo_emo", "fecha", "bloque", "examen", "recurso_atencion", "hora_inicio", "hora_fin", "duracion_min"]
    cols = [c for c in columnas if c in df.columns]
    return df[cols].sort_values(["paciente", "fecha", "hora_inicio"]).reset_index(drop=True)


def preparar_agenda_por_recurso(agenda: pd.DataFrame) -> pd.DataFrame:
    if agenda is None or agenda.empty:
        return pd.DataFrame()
    df = enriquecer_agenda_con_pacientes(agenda)
    if "especialidad" in df.columns:
        df["examen"] = df["especialidad"].apply(lambda x: ESPECIALIDAD_MODELO_A_NOMBRE.get(str(x), str(x)))
    if "recurso" in df.columns:
        df["recurso_atencion"] = df["recurso"].apply(lambda x: RECURSO_MODELO_A_NOMBRE.get(str(x), str(x)))
    columnas = ["recurso_atencion", "fecha", "bloque", "hora_inicio", "hora_fin", "paciente", "identificacion", "nombre_paciente", "tipo_emo", "examen"]
    cols = [c for c in columnas if c in df.columns]
    return df[cols].sort_values(["recurso_atencion", "fecha", "hora_inicio", "paciente"]).reset_index(drop=True)


def construir_validacion_visual(tablas: Dict[str, Any], errores: List[str], advertencias: List[str]) -> pd.DataFrame:
    examenes = tablas.get("examenes_paciente", pd.DataFrame())
    disp_pac = tablas.get("disponibilidad_pacientes", pd.DataFrame())
    disp_rec = tablas.get("disponibilidad_recursos", pd.DataFrame())
    bloques = tablas.get("bloques_ocupados", pd.DataFrame())
    pacientes_total = len(examenes) if isinstance(examenes, pd.DataFrame) else 0
    pacientes_con_examenes = 0
    if isinstance(examenes, pd.DataFrame) and not examenes.empty:
        cols_exam = [c for c in examenes.columns if c != "paciente"]
        pacientes_con_examenes = int((examenes[cols_exam].fillna(0).astype(int).sum(axis=1) > 0).sum())
    pacientes_con_disp = disp_pac["paciente"].nunique() if isinstance(disp_pac, pd.DataFrame) and not disp_pac.empty and "paciente" in disp_pac.columns else 0

    filas = [
        {"Revisión": "Pacientes registrados", "Resultado": f"{pacientes_total} pacientes", "Estado": "Correcto" if pacientes_total > 0 else "Falta información"},
        {"Revisión": "Exámenes asignados", "Resultado": f"{pacientes_con_examenes} de {pacientes_total}", "Estado": "Correcto" if pacientes_con_examenes == pacientes_total and pacientes_total > 0 else "Falta información"},
        {"Revisión": "Disponibilidad de pacientes", "Resultado": f"{pacientes_con_disp} de {pacientes_total} pacientes", "Estado": "Correcto" if pacientes_con_disp == pacientes_total and pacientes_total > 0 else "Falta información"},
        {"Revisión": "Horarios de especialistas", "Resultado": f"{len(disp_rec)} ventanas disponibles", "Estado": "Correcto" if isinstance(disp_rec, pd.DataFrame) and not disp_rec.empty else "Falta información"},
        {"Revisión": "Ocupación cargada desde Hosvital", "Resultado": f"{len(bloques)} bloques ocupados", "Estado": "Correcto" if isinstance(bloques, pd.DataFrame) else "Sin bloqueos cargados"},
        {"Revisión": "Validación general", "Resultado": f"{len(errores)} puntos por corregir, {len(advertencias)} advertencias", "Estado": "Listo" if not errores else "Corregir antes de continuar"},
    ]
    return pd.DataFrame(filas)


def mostrar_panel_avance() -> None:
    df_pac = st.session_state.get("pacientes_df", pd.DataFrame())
    disp = st.session_state.get("disponibilidades_pacientes", [])
    df_bloques = st.session_state.get("df_bloques", pd.DataFrame())
    total_pac = len(df_pac) if isinstance(df_pac, pd.DataFrame) else 0
    con_examenes = int(df_pac["Exámenes EMO a realizar"].apply(lambda x: len(normalizar_lista_examenes(x)) > 0).sum()) if total_pac and "Exámenes EMO a realizar" in df_pac.columns else 0
    con_disp = len({x.get("paciente_id") for x in disp if x.get("paciente_id")})
    pasos_ok = sum([
        bool(st.session_state.get("agenda_procesada")) or len(df_bloques) >= 0,
        total_pac > 0,
        con_examenes == total_pac and total_pac > 0,
        con_disp == total_pac and total_pac > 0,
        bool(st.session_state.horizonte_inicio and st.session_state.horizonte_fin),
    ])
    progreso = pasos_ok / 5
    st.markdown("#### Avance del proceso")
    st.progress(progreso)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Agenda Hosvital", "Cargada" if st.session_state.get("agenda_procesada") else "Opcional")
    c2.metric("Pacientes", total_pac)
    c3.metric("Con exámenes", f"{con_examenes}/{total_pac}")
    c4.metric("Con disponibilidad", f"{con_disp}/{total_pac}")
    c5.metric("Rango de fechas", f"{st.session_state.horizonte_inicio.strftime('%d/%m')} - {st.session_state.horizonte_fin.strftime('%d/%m')}")


def df_to_jsonable_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    out = df.copy()
    for col in out.columns:
        out[col] = out[col].apply(lambda x: x.isoformat() if isinstance(x, (datetime, date, time, pd.Timestamp)) else (None if pd.isna(x) else x))
    return out.to_dict("records")


def registros_a_df(registros: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(registros or [])


def cargar_conjuntos_guardados() -> List[Dict[str, Any]]:
    if not RUTA_CONJUNTOS_GUARDADOS.exists():
        return []
    try:
        return json.loads(RUTA_CONJUNTOS_GUARDADOS.read_text(encoding="utf-8"))
    except Exception:
        return []


def escribir_conjuntos_guardados(conjuntos: List[Dict[str, Any]]) -> None:
    RUTA_CONJUNTOS_GUARDADOS.write_text(json.dumps(conjuntos, ensure_ascii=False, indent=2), encoding="utf-8")


def crear_paquete_conjunto_guardado(nombre: str) -> Dict[str, Any]:
    resultados = st.session_state.get("resultados_modelo") or {}
    resultado = resultados.get("resultado_ganador") or resultados.get("resultado_milp") or {}
    agenda = obtener_agenda_resultado("MILP", resultado) if resultado else pd.DataFrame()
    return {
        "id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "nombre": nombre.strip() or st.session_state.nombre_conjunto,
        "fecha_guardado": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "horizonte_inicio": st.session_state.horizonte_inicio.isoformat(),
        "horizonte_fin": st.session_state.horizonte_fin.isoformat(),
        "pacientes": df_to_jsonable_records(st.session_state.get("pacientes_df", pd.DataFrame())),
        "disponibilidades_pacientes": st.session_state.get("disponibilidades_pacientes", []),
        "bloques_ocupados": df_to_jsonable_records(st.session_state.get("df_bloques", pd.DataFrame())),
        "agenda_programada": df_to_jsonable_records(enriquecer_agenda_con_pacientes(agenda)) if isinstance(agenda, pd.DataFrame) and not agenda.empty else [],
        "resumen_ejecutivo": df_to_jsonable_records(construir_resumen_ejecutivo(resultado, agenda)) if resultado else [],
        "agenda_por_paciente": df_to_jsonable_records(preparar_agenda_por_paciente(agenda)) if isinstance(agenda, pd.DataFrame) and not agenda.empty else [],
        "agenda_por_recurso": df_to_jsonable_records(preparar_agenda_por_recurso(agenda)) if isinstance(agenda, pd.DataFrame) and not agenda.empty else [],
    }


def guardar_conjunto_actual(nombre: str) -> None:
    conjuntos = cargar_conjuntos_guardados()
    paquete = crear_paquete_conjunto_guardado(nombre)
    conjuntos = [c for c in conjuntos if c.get("id") != paquete["id"]]
    conjuntos.append(paquete)
    escribir_conjuntos_guardados(conjuntos)


def restaurar_conjunto_en_sesion(conjunto: Dict[str, Any]) -> None:
    pacientes = registros_a_df(conjunto.get("pacientes", []))
    if not pacientes.empty:
        st.session_state.pacientes_df = pacientes
        st.session_state.num_pacientes_config = len(pacientes)
    st.session_state.nombre_conjunto = conjunto.get("nombre", "Grupo EMO a programar")
    st.session_state.horizonte_inicio = pd.to_datetime(conjunto.get("horizonte_inicio", date.today())).date()
    st.session_state.horizonte_fin = pd.to_datetime(conjunto.get("horizonte_fin", date.today())).date()
    st.session_state.disponibilidades_pacientes = conjunto.get("disponibilidades_pacientes", []) or []
    bloques = registros_a_df(conjunto.get("bloques_ocupados", []))
    if not bloques.empty:
        for col in ["fecha_dt", "inicio", "fin", "siguiente_inicio"]:
            if col in bloques.columns:
                bloques[col] = pd.to_datetime(bloques[col], errors="coerce")
        st.session_state.df_bloques = bloques
        st.session_state.agenda_procesada = True
    st.session_state.conjunto_cargado_nombre = conjunto.get("nombre", "")


def modulo_conjuntos_guardados() -> None:
    st.markdown("### Conjuntos guardados")
    st.caption("Consulta grupos de pacientes programados anteriormente y, si lo necesitas, carga su información nuevamente en la interfaz.")
    conjuntos = cargar_conjuntos_guardados()
    if not conjuntos:
        st.info("Todavía no hay conjuntos guardados.")
        return

    opciones = [f"{c.get('nombre', 'Sin nombre')} · {c.get('fecha_guardado', '')}" for c in conjuntos]
    seleccionado = st.selectbox("Selecciona un conjunto", options=opciones)
    idx_sel = opciones.index(seleccionado)
    conjunto = conjuntos[idx_sel]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pacientes", len(conjunto.get("pacientes", [])))
    c2.metric("Disponibilidades", len(conjunto.get("disponibilidades_pacientes", [])))
    c3.metric("Citas programadas", len(conjunto.get("agenda_programada", [])))
    c4.metric("Guardado", conjunto.get("fecha_guardado", ""))

    tab_resumen, tab_agenda_p, tab_agenda_r, tab_datos = st.tabs(["Resumen", "Agenda por paciente", "Agenda por recurso", "Datos cargados"])
    with tab_resumen:
        resumen = registros_a_df(conjunto.get("resumen_ejecutivo", []))
        if resumen.empty:
            st.info("Este conjunto no tiene resumen guardado.")
        else:
            st.dataframe(resumen, use_container_width=True, hide_index=True)
    with tab_agenda_p:
        df = registros_a_df(conjunto.get("agenda_por_paciente", []))
        if df.empty:
            st.info("Este conjunto no tiene agenda por paciente guardada.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
    with tab_agenda_r:
        df = registros_a_df(conjunto.get("agenda_por_recurso", []))
        if df.empty:
            st.info("Este conjunto no tiene agenda por recurso guardada.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
    with tab_datos:
        st.markdown("**Pacientes registrados**")
        st.dataframe(registros_a_df(conjunto.get("pacientes", [])), use_container_width=True, hide_index=True)
        st.markdown("**Disponibilidad registrada**")
        st.dataframe(registros_a_df(conjunto.get("disponibilidades_pacientes", [])), use_container_width=True, hide_index=True)

    col_a, col_c = st.columns(2)
    with col_a:
        if st.button("Cargar este conjunto en la interfaz", use_container_width=True):
            restaurar_conjunto_en_sesion(conjunto)
            st.success("Conjunto cargado en la interfaz.")
            st.rerun()
    
    with col_c:
        if st.button("Eliminar conjunto", use_container_width=True):
            conjuntos = [c for c in conjuntos if c.get("id") != conjunto.get("id")]
            escribir_conjuntos_guardados(conjuntos)
            st.warning("Conjunto eliminado.")
            st.rerun()

def exportar_resultados_modelo_excel(resultados: Dict[str, Any]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        resultado = resultados.get("resultado_ganador") or resultados.get("resultado_milp")
        if resultado:
            agenda = obtener_agenda_resultado("MILP", resultado)
            agenda_enriquecida = enriquecer_agenda_con_pacientes(agenda) if not agenda.empty else pd.DataFrame()
            resumen_ejecutivo = construir_resumen_ejecutivo(resultado, agenda_enriquecida)
            agenda_paciente = preparar_agenda_por_paciente(agenda_enriquecida)
            agenda_recurso = preparar_agenda_por_recurso(agenda_enriquecida)

            if not resumen_ejecutivo.empty:
                resumen_ejecutivo.to_excel(writer, sheet_name="resumen_ejecutivo", index=False)
            if not agenda_paciente.empty:
                agenda_paciente.to_excel(writer, sheet_name="agenda_por_paciente", index=False)
            if not agenda_recurso.empty:
                agenda_recurso.to_excel(writer, sheet_name="agenda_por_recurso", index=False)
            if not agenda_enriquecida.empty:
                agenda_enriquecida.to_excel(writer, sheet_name="agenda_completa", index=False)
            if resultado.get("metricas"):
                for k, df in resultado["metricas"].items():
                    if isinstance(df, pd.DataFrame) and not df.empty:
                        df.to_excel(writer, sheet_name=f"{k[:25]}"[:31], index=False)
    buffer.seek(0)
    return buffer.getvalue()

def modulo_ejecutar_modelo() -> None:
    st.markdown("### 4. Programación EMO")
    st.caption("La herramienta revisa la información registrada y busca una agenda válida para los pacientes. El tiempo máximo de búsqueda es de 60 minutos.")

    mostrar_panel_avance()

    if not dependencia_disponible("openpyxl"):
        st.error("Falta instalar una librería necesaria para preparar los datos de la programación.")
        st.code("python -m pip install openpyxl", language="bash")
        st.info("Después de instalarla, cierra la app con Ctrl + C y vuelve a ejecutarla.")
        return

    if not dependencia_disponible("modelo_milp_app"):
        st.error("No encuentro el archivo modelo_milp_app.py en la misma carpeta de la aplicación.")
        st.info("Guarda el archivo del modelo con el nombre modelo_milp_app.py junto a esta app y vuelve a ejecutar.")
        return

    if st.session_state.pacientes_df.empty:
        st.warning("Primero registra los pacientes.")
        return
    if not st.session_state.get("disponibilidades_pacientes"):
        st.warning("Primero registra la disponibilidad de los pacientes.")
        return

    st.markdown("#### Revisión antes de generar la agenda")
    tmp_preview = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    tmp_preview.close()
    tablas_preview = None
    errores_previos: List[str] = []
    advertencias_previas: List[str] = []
    try:
        tablas_preview = generar_excel_escenario_modelo(tmp_preview.name)
        errores_previos, advertencias_previas = validar_datos_antes_modelo(tablas_preview)
    except Exception as e:
        errores_previos = [f"No fue posible preparar la información para la programación: {e}"]
    finally:
        try:
            os.remove(tmp_preview.name)
        except Exception:
            pass

    if tablas_preview is not None:
        df_validacion = construir_validacion_visual(tablas_preview, errores_previos, advertencias_previas)
        st.dataframe(df_validacion, use_container_width=True, hide_index=True)
    else:
        st.error("No fue posible generar la vista de validación.")

    if errores_previos:
        st.error("Antes de generar la agenda corrige estos puntos:")
        for err in errores_previos:
            st.error(err)
    if advertencias_previas:
        with st.expander("Advertencias para revisar"):
            for adv in advertencias_previas:
                st.warning(adv)

    with st.expander("Ver datos que se enviarán a la programación"):
        if tablas_preview is not None:
            st.markdown("**Exámenes por paciente**")
            st.dataframe(tablas_preview["examenes_paciente"], use_container_width=True, hide_index=True)
            st.markdown("**Disponibilidad de pacientes**")
            st.dataframe(tablas_preview["disponibilidad_pacientes"], use_container_width=True, hide_index=True)
            st.markdown("**Horarios disponibles de especialistas**")
            st.dataframe(tablas_preview["disponibilidad_recursos"], use_container_width=True, hide_index=True)
            st.markdown("**Horarios ocupados cargados desde Hosvital**")
            st.dataframe(tablas_preview["bloques_ocupados"], use_container_width=True, hide_index=True)

    ejecutar = st.button(
        "Generar programación EMO",
        type="primary",
        use_container_width=True,
        disabled=bool(errores_previos),
    )
    if ejecutar:
        ruta_tmp = os.path.abspath("escenario_app_emo.xlsx")
        try:
            tablas = generar_excel_escenario_modelo(ruta_tmp)
            errores_previos, advertencias_previas = validar_datos_antes_modelo(tablas)
            if errores_previos:
                st.error("La programación no se puede generar hasta corregir la información marcada.")
                for err in errores_previos:
                    st.error(err)
                return
            for adv in tablas.get("advertencias", []) + advertencias_previas:
                st.warning(adv)

            with st.spinner("Buscando una programación válida para el grupo de pacientes..."):
                st.session_state.resultados_modelo = ejecutar_modelos_desde_excel(ruta_tmp)
            st.success("Proceso finalizado.")
        except Exception as e:
            st.error(f"No fue posible generar la agenda: {e}")
            st.code(traceback.format_exc())

    resultados = st.session_state.get("resultados_modelo")
    if not resultados:
        st.info("Cuando generes la programación, aparecerá la agenda por paciente, por recurso y el calendario.")
        return

    resultado = resultados.get("resultado_ganador") or resultados.get("resultado_milp")
    estado_txt, mensaje_estado = estado_amigable_resultado(resultado)
    if resultados.get("metodo_ganador"):
        st.success(f"{estado_txt}. {mensaje_estado}")
    else:
        st.error(f"{estado_txt}. {mensaje_estado}")
        diag = tabla_diagnostico_no_programados("MILP", resultados.get("resultado_milp"))
        if not diag.empty:
            st.markdown("**Exámenes que quedaron sin programar**")
            st.dataframe(diag, use_container_width=True, hide_index=True)
        with st.expander("Ver detalle técnico solo para revisión"):
            st.write("\n".join(resultados.get("bitacora", [])))
            if resultados.get("stdout_milp"):
                st.code(resultados["stdout_milp"][-8000:])
        return

    agenda_final = obtener_agenda_resultado("MILP", resultado)
    if agenda_final.empty:
        st.warning("No hay agenda para mostrar.")
        return

    agenda_final = enriquecer_agenda_con_pacientes(agenda_final)
    resumen_ejecutivo = construir_resumen_ejecutivo(resultado, agenda_final)
    agenda_paciente = preparar_agenda_por_paciente(agenda_final)
    agenda_recurso = preparar_agenda_por_recurso(agenda_final)

    st.markdown("#### Resumen ejecutivo")
    st.dataframe(resumen_ejecutivo, use_container_width=True, hide_index=True)

    tab_cal, tab_paciente, tab_recurso, tab_ind, tab_guardar = st.tabs([
        "Calendario", "Agenda por paciente", "Agenda por especialista", "Indicadores", "Guardar y descargar"
    ])

    with tab_cal:
        st.caption("Cada bloque muestra el paciente, el examen y el horario programado.")
        df_cal = preparar_agenda_para_calendario(agenda_final)
        fechas = sorted(df_cal["fecha_dt"].dt.date.unique().tolist()) if not df_cal.empty else []
        if fechas:
            if "idx_fecha_resultados" not in st.session_state:
                st.session_state.idx_fecha_resultados = 0
            st.session_state.idx_fecha_resultados = max(0, min(int(st.session_state.idx_fecha_resultados), len(fechas) - 1))

            def mover_fecha_resultados(delta: int) -> None:
                st.session_state.idx_fecha_resultados = max(0, min(int(st.session_state.idx_fecha_resultados) + delta, len(fechas) - 1))

            cprev, cfecha, cnext = st.columns([0.8, 2.4, 0.8], vertical_alignment="center")
            with cprev:
                st.button("Día anterior", key="res_prev", use_container_width=True, disabled=st.session_state.idx_fecha_resultados == 0, on_click=mover_fecha_resultados, args=(-1,))
            with cnext:
                st.button("Día siguiente", key="res_next", use_container_width=True, disabled=st.session_state.idx_fecha_resultados == len(fechas) - 1, on_click=mover_fecha_resultados, args=(1,))
            fecha_sel = fechas[st.session_state.idx_fecha_resultados]
            with cfecha:
                st.markdown(f"<div style='text-align:center; font-size:22px; font-weight:700; color:#17324d;'>{formatear_fecha_larga(fecha_sel)}</div>", unsafe_allow_html=True)

            html_res = construir_html_calendario_resultados(agenda_final, fecha_sel)
            components.html(html_res, height=980, scrolling=True)

            agenda_dia = preparar_agenda_para_calendario(agenda_final)
            agenda_dia = agenda_dia[agenda_dia["fecha_dt"].dt.date == fecha_sel].copy()
            if not agenda_dia.empty:
                st.markdown("##### Detalle del día seleccionado")
                columnas_dia = ["hora_inicio", "hora_fin", "especialidad_nombre", "recurso_nombre", "paciente", "identificacion", "nombre_paciente", "tipo_emo"]
                cols_dia = [c for c in columnas_dia if c in agenda_dia.columns]
                st.dataframe(agenda_dia[cols_dia].sort_values(["hora_inicio", "especialidad_nombre"]), use_container_width=True, hide_index=True)
        else:
            st.info("No hay citas con fecha válida para mostrar en calendario.")

    with tab_paciente:
        st.dataframe(agenda_paciente, use_container_width=True, hide_index=True)
    with tab_recurso:
        st.dataframe(agenda_recurso, use_container_width=True, hide_index=True)
    with tab_ind:
        metricas = resultado.get("metricas", {}) if resultado else {}
        if isinstance(metricas, dict):
            for titulo, clave in [
                ("Métricas por paciente", "metricas_paciente"),
                ("Métricas por día", "metricas_agenda_dia"),
                ("Métricas por recurso", "metricas_recursos"),
                ("Resultados diferidos", "metricas_resultados"),
            ]:
                dfm = metricas.get(clave, pd.DataFrame())
                if isinstance(dfm, pd.DataFrame) and not dfm.empty:
                    st.markdown(f"**{titulo}**")
                    st.dataframe(dfm, use_container_width=True, hide_index=True)
    with tab_guardar:
        nombre_guardar = st.text_input("Nombre para guardar este conjunto", value=st.session_state.nombre_conjunto)
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            if st.button("Guardar conjunto programado", use_container_width=True):
                guardar_conjunto_actual(nombre_guardar)
                st.success("Conjunto guardado. Puedes consultarlo en el módulo Conjuntos guardados.")
        with col_g2:
            st.download_button(
                "Descargar resultados en Excel",
                data=exportar_resultados_modelo_excel(resultados),
                file_name="programacion_emo.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

        with st.expander("Ver detalle técnico solo para revisión"):
            st.write("\n".join(resultados.get("bitacora", [])))
            if resultados.get("stdout_milp"):
                st.code(resultados["stdout_milp"][-8000:])

# ____________________
# HERRAMIENTA
# ____________________

inicializar_estado()

st.markdown(
    """
    <style>
    :root {
        --cmu-blue: #008DCA;
        --cmu-blue-dark: #005B8F;
        --cmu-navy: #17324D;
        --cmu-gray: #575756;
        --cmu-light: #F3F8FC;
        --cmu-border: #D8E6F0;
        --cmu-white: #FFFFFF;
    }
    .stApp {
        background: linear-gradient(180deg, #F7FBFE 0%, #FFFFFF 42%, #F6F8FA 100%);
        color: var(--cmu-navy);
    }
    .block-container {
        padding-top: 1.1rem;
        padding-bottom: 2.5rem;
        max-width: 1280px;
    }
    h1, h2, h3, h4 {
        color: var(--cmu-navy);
        letter-spacing: -0.02em;
    }
    h3 {
        border-left: 5px solid var(--cmu-blue);
        padding-left: 0.75rem;
        margin-top: 1.35rem;
        margin-bottom: 0.6rem;
    }
    h4 {
        color: var(--cmu-blue-dark);
    }
    .cmu-topbar {
        background: #FFFFFF;
        border: 1px solid var(--cmu-border);
        border-radius: 18px;
        padding: 1.05rem 1.25rem;
        box-shadow: 0 10px 28px rgba(0, 91, 143, 0.08);
        margin-bottom: 1.2rem;
    }
    .cmu-brand-row {
        display: flex;
        align-items: center;
        gap: 1.25rem;
    }
    .cmu-logo {
        width: 210px;
        max-width: 24vw;
        height: auto;
        object-fit: contain;
        flex-shrink: 0;
    }
    .cmu-hero {
        background: linear-gradient(135deg, rgba(0,141,202,0.10), rgba(255,255,255,0.95));
        border: 1px solid var(--cmu-border);
        border-radius: 18px;
        padding: 1.15rem 1.25rem;
        margin-bottom: 1.2rem;
    }
    .cmu-eyebrow {
        color: var(--cmu-blue);
        font-weight: 800;
        text-transform: uppercase;
        font-size: 0.78rem;
        letter-spacing: 0.10em;
        margin-bottom: 0.25rem;
    }
    .cmu-hero h1 {
        margin: 0;
        font-size: 2.05rem;
        line-height: 1.1;
        color: var(--cmu-navy);
    }
    .cmu-hero p {
        margin: 0.45rem 0 0 0;
        color: var(--cmu-gray);
        font-size: 1.02rem;
    }
    .cmu-logo-fallback {
        font-weight: 900;
        font-size: 1.35rem;
        line-height: 1.05;
        color: var(--cmu-gray);
        border-left: 5px solid var(--cmu-blue);
        padding-left: 0.75rem;
    }
    .cmu-logo-fallback span {
        color: var(--cmu-blue);
        font-size: 1.1rem;
    }
    div[data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1px solid var(--cmu-border);
        border-top: 4px solid var(--cmu-blue);
        border-radius: 16px;
        padding: 0.85rem 1rem;
        box-shadow: 0 8px 20px rgba(23, 50, 77, 0.05);
    }
    div[data-testid="stMetricValue"] {
        color: var(--cmu-navy);
        font-size: 1.45rem;
        font-weight: 800;
    }
    div[data-testid="stMetricLabel"] {
        color: var(--cmu-gray);
        font-weight: 600;
    }
    .stButton > button, .stDownloadButton > button, button[kind="primary"] {
        background: var(--cmu-blue);
        color: white;
        border: 1px solid var(--cmu-blue);
        border-radius: 999px;
        font-weight: 700;
        box-shadow: 0 7px 14px rgba(0, 141, 202, 0.20);
    }
    .stButton > button:hover, .stDownloadButton > button:hover {
        background: var(--cmu-blue-dark);
        border-color: var(--cmu-blue-dark);
        color: white;
    }
    .stButton > button:disabled {
        background: #E9EFF4;
        color: #91A3B2;
        border-color: #E9EFF4;
        box-shadow: none;
    }
    div[data-testid="stForm"] {
        background: #FFFFFF;
        border: 1px solid var(--cmu-border);
        border-radius: 18px;
        padding: 1rem;
        box-shadow: 0 8px 24px rgba(23, 50, 77, 0.045);
    }
    div[data-testid="stExpander"] {
        border: 1px solid var(--cmu-border);
        border-radius: 14px;
        background: #FFFFFF;
    }
    div[role="radiogroup"] {
        background: #FFFFFF;
        border: 1px solid var(--cmu-border);
        border-radius: 999px;
        padding: 0.35rem 0.55rem;
        box-shadow: 0 8px 20px rgba(23, 50, 77, 0.05);
    }
    div[role="radiogroup"] label {
        padding: 0.35rem 0.55rem;
        border-radius: 999px;
        color: var(--cmu-navy);
        font-weight: 650;
    }
    .stDataFrame, div[data-testid="stDataFrame"] {
        border-radius: 14px;
    }
    .calendar-shell {
        border-top: 4px solid var(--cmu-blue) !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="cmu-topbar">
        <div class="cmu-brand-row">
            <img class="cmu-logo" src="data:image/png;base64,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" alt="Centro Médico Uninorte">
            <div class="cmu-hero">
                <div class="cmu-eyebrow">Centro Médico Uninorte</div>
                <h1>Programación de exámenes médicos ocupacionales</h1>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

modulo = st.radio(
    "Seleccione el módulo",
    options=["Disponibilidad recursos", "Registro de pacientes", "Disponibilidad pacientes", "Programar EMO", "Ajustes","Conjuntos guardados"],
    horizontal=True,
    label_visibility="visible",
)

if modulo == "Disponibilidad recursos":
    modulo_agenda_hosvital()
elif modulo == "Registro de pacientes":
    modulo_pacientes()
elif modulo == "Disponibilidad pacientes":
    modulo_disponibilidad()
elif modulo == "Programar EMO":
    modulo_ejecutar_modelo()
elif modulo == "Ajustes":
    modulo_ajustes()
elif modulo == "Conjuntos guardados":
    modulo_conjuntos_guardados()
