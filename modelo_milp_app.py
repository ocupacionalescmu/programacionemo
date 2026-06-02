# MODELO MILP PARA PROGRAMACIÓN DE EXÁMENES MÉDICOS OCUPACIONALES

#Previamente se deben instalar las librerías
#streamlit
#pandas
#pdfplumber
#openpyxl
#pulp
#numpy
#xlsxwriter
#plotly
#pyomo
#highspy

# Importar librerías
import math
import os
import re
import time as time_module
import unicodedata
from datetime import datetime, date, time, timedelta
from itertools import combinations
import pandas as pd
import pulp as pl

# PARÁMETROS DE EXPERIMENTACIÓN

# Archivo de Excel que contiene los escenarios.
ARCHIVO_ESCENARIOS = "escenarios_pruebas_y_reales.xlsx"

# Nombre de la hoja del escenario que se quiere resolver.
HOJA_ESCENARIO = "escenario_1"

# Límite máximo de tiempo del ejecución en segundos.
TIME_LIMIT_SOLVER = 3600

# Brecha de optimalidad del solver.
MIP_GAP = 0

# Selección del solver a utilizar.

# Para cambiar el solver, se deben quitar las líneas comentadas del solver seleccionado en la función crear_solver().
# También se debe quitar la línea comentada del nombre del solver para que los archivos de salida indiquen el solver correcto.
#NOMBRE_SOLVER = "CBC"
NOMBRE_SOLVER = "HiGHS"
#NOMBRE_SOLVER = "Gurobi"

# Archivo de log del solver, usado para identificar si hubo límite de tiempo, infactibilidad, gap pendiente u otros.
GUARDAR_LOG_SOLVER = True
LOG_SOLVER = f"log_solver_{NOMBRE_SOLVER.lower()}_{HOJA_ESCENARIO}.txt"

# Diagnóstico de infactibilidad 

# Si el modelo exacto sale infactible, esta opción permite resolver una versión relajada del problema.
ACTIVAR_DIAGNOSTICO_INFACTIBILIDAD = True
# Penalización muy grande para operaciones no programadas en el diagnóstico de infactibilidad.
PENALIZACION_NO_PROGRAMADO = 1_000_000

# PARÁMETROS DEL MODELO

# Horario de funcionamiento del Centro Médico.
HORA_APERTURA = "07:00"
HORA_ALMUERZO_INICIO = "12:00"
HORA_ALMUERZO_FIN = "13:00"
HORA_CIERRE = "17:00"

# Bloques para contar visitas (Una persona con exámenes en mañana y tarde el mismo día cuenta como 2 visitas).
BLOQUES_VISITA = {
    "manana": ("07:00", "12:00"),
    "tarde": ("13:00", "17:00"),
}

# Tiempo estándar de traslado entre un examen externo y uno interno el mismo día.
TIEMPO_TRASLADO_EXTERNO_INTERNO = 90

# Parámetro M de respaldo (Más adelante se recalcula M con base en el horizonte, pero este valor queda como mínimo).
M_RESPALDO = 100000

# Duraciones estándar de los exámenes (en minutos) usadas para agendar citas.
DURACIONES_ESTANDAR = {
    "optometria": 15,
    "laboratorios": 5,
    "fonoaudiologia": 15,
    "espirometria": 15,
    "salud_ocupacional": 20,
    "electrocardiograma": 5,
}

# Exámenes internos programables dentro del Centro Médico.
EXAMENES_INTERNOS = set(DURACIONES_ESTANDAR.keys())

# Exámenes externos
EXAMENES_EXTERNOS = {"imagenologia", "otros_externos"}

# Exámenes cuyo resultado no está disponible inmediatamente al finalizar la cita.
EXAMENES_CON_RESULTADO_DIFERIDO = {
    "laboratorios",
    "imagenologia",
    "electrocardiograma",
    "otros_externos",
}

# Relación entre recurso y examen interno
RECURSOS_POR_EXAMEN = {
    "optometria": ["optometra"],
    "laboratorios": ["tecnico_laboratorios"],
    "fonoaudiologia": ["fonoaudiologa"],
    "espirometria": ["fisioterapeuta"],
    "salud_ocupacional": ["medico_ocupacional"],
    "electrocardiograma": ["enfermera"],
}

# Reglas de disponibilidad de resultados
HORA_RESULTADO_LABORATORIOS = "17:00"
HORA_RESULTADO_DIA_HABIL_SIGUIENTE = "10:00"

# Para laboratorios se seleccionó el supuesto conservador:
# aunque el resultado esté disponible a las 17:00 del mismo día,
# salud ocupacional queda habilitada desde el siguiente día hábil.
LABORATORIOS_HABILITA_SALUD_DIA_HABIL_SIGUIENTE = True

# Laboratorios solo se programan de lunes a viernes en esta franja horaria.
LABORATORIOS_INICIO_PERMITIDO = "07:00"
LABORATORIOS_FIN_PERMITIDO = "10:00"

# Funciones de normalización y tiempo

def normalizar_texto(x):
    """Convierte textos a minúsculas, sin tíldes, sin espacios dobles y con guiones bajos."""
    if pd.isna(x):
        return ""
    x = str(x).strip().lower()
    x = unicodedata.normalize("NFKD", x)
    x = "".join(c for c in x if not unicodedata.combining(c))
    x = x.replace("ñ", "n")
    for ch in [" ", "-", "/", "\\", ".", ",", ";", ":", "(", ")", "[", "]"]:
        x = x.replace(ch, "_")
    while "__" in x:
        x = x.replace("__", "_")
    return x.strip("_")

# Nombres estándar permitidos en la plantilla
EXAMENES_VALIDOS = EXAMENES_INTERNOS | EXAMENES_EXTERNOS

RECURSOS_VALIDOS = set()
for _recursos in RECURSOS_POR_EXAMEN.values():
    RECURSOS_VALIDOS.update(_recursos)

def minutos_de_hora(valor):
    """Convierte una hora a minutos desde 00:00."""
    if pd.isna(valor):
        raise ValueError("Hora vacía encontrada")

    if isinstance(valor, time):
        return valor.hour * 60 + valor.minute + valor.second / 60

    if isinstance(valor, datetime):
        return valor.hour * 60 + valor.minute + valor.second / 60

    if isinstance(valor, pd.Timestamp):
        return valor.hour * 60 + valor.minute + valor.second / 60

    if isinstance(valor, (int, float)):
        if 0 <= valor < 1:
            return float(valor) * 24 * 60
        valor_str = str(int(valor)).zfill(4)
        h = int(valor_str[:-2])
        m = int(valor_str[-2:])
        return h * 60 + m

    texto = str(valor).strip().lower()
    texto = texto.replace("a. m.", "am").replace("p. m.", "pm")
    texto = texto.replace("a.m.", "am").replace("p.m.", "pm")
    texto = texto.replace(" ", "")

    formatos = ["%H:%M", "%H:%M:%S", "%I:%M%p", "%I:%M:%S%p", "%I%p"]
    for fmt in formatos:
        try:
            dt = datetime.strptime(texto, fmt)
            return dt.hour * 60 + dt.minute + dt.second / 60
        except ValueError:
            pass

    raise ValueError(f"No se pudo interpretar la hora: {valor}")


def convertir_fecha(valor, nombre_columna="fecha"):
    """Convierte valores de fecha desde Excel a datetime.date."""
    if pd.isna(valor):
        raise ValueError(f"Fecha vacía encontrada en la columna '{nombre_columna}'.")
    try:
        return pd.to_datetime(valor).date()
    except Exception as e:
        raise ValueError(f"No se pudo interpretar la fecha '{valor}' en la columna '{nombre_columna}'.") from e


def abs_min(fecha, minuto_local, fecha_base):
    """Convierte fecha + minuto local a minuto absoluto desde fecha_base."""
    return (fecha - fecha_base).days * 1440 + float(minuto_local)


def fecha_hora_desde_abs(minuto_abs, fecha_base):
    """Convierte minuto absoluto a fecha y hora legible."""
    dt = datetime.combine(fecha_base, time(0, 0)) + timedelta(minutes=float(minuto_abs))
    return dt.date(), dt.strftime("%H:%M")


def obtener_bloque_por_intervalo(inicio_min, fin_min):
    """Clasifica un intervalo local en bloque mañana/tarde para conteo de visitas."""
    inicio = float(inicio_min)
    fin = float(fin_min)
    for nombre, (b_ini_txt, b_fin_txt) in BLOQUES_VISITA.items():
        b_ini = minutos_de_hora(b_ini_txt)
        b_fin = minutos_de_hora(b_fin_txt)
        if inicio >= b_ini and fin <= b_fin:
            return nombre
    return "fuera_bloque"


def es_dia_habil(fecha, festivos):
    """Retorna True si la fecha es lunes a viernes y no está en festivos."""
    return fecha.weekday() < 5 and fecha not in festivos


def siguiente_dia_habil(fecha, festivos):
    """Retorna el siguiente día hábil posterior a la fecha dada."""
    f = fecha + timedelta(days=1)
    while not es_dia_habil(f, festivos):
        f += timedelta(days=1)
    return f


def mismo_o_siguiente_habil(fecha, festivos):
    """Retorna la misma fecha si es hábil, si no, el siguiente día hábil."""
    f = fecha
    while not es_dia_habil(f, festivos):
        f += timedelta(days=1)
    return f


def mostrar_tabla(df, nombre="Tabla"):
    """Muestra una tabla."""
    print(f"\n===== {nombre} =====")
    if df is None:
        print("No disponible.")
        return
    try:
        from IPython.display import display
        display(df)
    except Exception:
        print(df.to_string(index=False))


# _____________________________________________________
# MÓDULO 1 - LECTURA DE DATOS DE LA PLANTILLA DE EXCEL
# _____________________________________________________

MARCADORES_SECCIONES = {
    "[EXAMENES_PACIENTE]": "examenes_paciente",
    "[DISPONIBILIDAD_PACIENTES]": "disponibilidad_pacientes",
    "[DISPONIBILIDAD_RECURSOS]": "disponibilidad_recursos",
    "[BLOQUES_OCUPADOS]": "bloques_ocupados",
    "[EXAMENES_EXTERNOS]": "examenes_externos",
    "[FESTIVOS]": "festivos",
}

SECCIONES_REQUERIDAS = [
    "examenes_paciente",
    "disponibilidad_pacientes",
    "disponibilidad_recursos",
]

COLUMNAS_EXAMENES_PACIENTE = [
    "paciente",
    "optometria",
    "laboratorios",
    "fonoaudiologia",
    "espirometria",
    "electrocardiograma",
    "imagenologia",
    "otros_externos",
]

COLUMNAS_DISPONIBILIDAD_PACIENTES = ["paciente", "fecha", "inicio", "fin"]
COLUMNAS_DISPONIBILIDAD_RECURSOS = ["recurso", "fecha", "inicio", "fin"]
COLUMNAS_BLOQUES_OCUPADOS = ["recurso", "fecha", "inicio", "fin"]
COLUMNAS_EXAMENES_EXTERNOS = ["paciente", "examen", "fecha", "inicio", "fin"]
COLUMNAS_FESTIVOS = ["fecha"]


def detectar_secciones(df_raw):
    """Detecta únicamente los marcadores exactos de la plantilla estándar."""
    secciones = []
    for idx, row in df_raw.iterrows():
        valores = [v for v in row.tolist() if not pd.isna(v)]
        if not valores:
            continue
        texto = str(valores[0]).strip()
        if texto in MARCADORES_SECCIONES:
            secciones.append((MARCADORES_SECCIONES[texto], idx, texto))
    return secciones


def extraer_seccion(df_raw, nombre_seccion, secciones):
    """Extrae una sección de la hoja estándar.La primera fila después del marcador se toma como encabezado."""
    posiciones = {nombre: idx for nombre, idx, _ in secciones}
    if nombre_seccion not in posiciones:
        return pd.DataFrame()

    inicio_marker = posiciones[nombre_seccion]
    indices_ordenados = sorted(idx for _, idx, _ in secciones)
    posibles_fin = [idx for idx in indices_ordenados if idx > inicio_marker]
    fin = min(posibles_fin) if posibles_fin else len(df_raw)

    bloque = df_raw.iloc[inicio_marker + 1:fin].copy()
    bloque = bloque.dropna(how="all")
    if bloque.empty:
        return pd.DataFrame()

    encabezados = [str(c).strip() if not pd.isna(c) else "" for c in bloque.iloc[0].tolist()]
    datos = bloque.iloc[1:].copy()
    datos.columns = encabezados
    datos = datos.dropna(how="all")
    datos = datos.loc[:, [c for c in datos.columns if c != ""]]
    datos = datos.reset_index(drop=True)
    return datos


def leer_escenario_excel(ruta_excel, hoja):
    """Lee una hoja de escenario diligenciada con la plantilla estándar."""
    try:
        df_raw = pd.read_excel(ruta_excel, sheet_name=hoja, header=None, dtype=object)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"No encontré el archivo '{ruta_excel}'."
        )
    except ValueError as e:
        raise ValueError(
            f"No encontré la hoja '{hoja}' en el archivo '{ruta_excel}'."
        ) from e

    secciones = detectar_secciones(df_raw)
    if not secciones:
        raise ValueError(
            "No encontré marcadores de sección con el formato exacto de la plantilla."
            "Usa marcadores como [EXAMENES_PACIENTE], [DISPONIBILIDAD_PACIENTES] y [DISPONIBILIDAD_RECURSOS]."
        )

    tablas = {sec: extraer_seccion(df_raw, sec, secciones) for sec, _, _ in secciones}

    faltantes = [s for s in SECCIONES_REQUERIDAS if s not in tablas or tablas[s].empty]
    if faltantes:
        raise ValueError(
            "Faltan secciones requeridas o están vacías: " + ", ".join(faltantes) +
            ". Revisa la hoja del escenario y conserva la estructura de la plantilla."
        )

    for opcional in ["bloques_ocupados", "examenes_externos", "festivos"]:
        if opcional not in tablas:
            tablas[opcional] = pd.DataFrame()

    return tablas

# _____________________________________________________
# MÓDULO 2 - PREPARACIÓN Y VALIDACIÓN DE DATOS
# _____________________________________________________

def limpiar_si_no_vacio(df):
    """Quita filas totalmente vacías sin cambiar los nombres de columnas de la plantilla."""
    if df is None or df.empty:
        return pd.DataFrame()
    return df.copy().dropna(how="all").reset_index(drop=True)


def valor_vacio(valor):
    """Identifica valores vacíos leídos desde Excel. Permite limpiar filas opcionales sin perder la lógica estricta de la plantilla."""
    if pd.isna(valor):
        return True
    texto = str(valor).strip().lower()
    return texto in {"", "nan", "nat", "none"}


def quitar_filas_sin_identificador(df, columnas_identificador):
    """Elimina filas de una sección opcional cuando sus identificadores están vacíos."""
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    columnas_existentes = [c for c in columnas_identificador if c in df.columns]
    if not columnas_existentes:
        return df
    mascara_sin_identificador = df[columnas_existentes].apply(
        lambda fila: all(valor_vacio(v) for v in fila),
        axis=1,
    )
    return df.loc[~mascara_sin_identificador].reset_index(drop=True)


def exigir_campos_obligatorios(df, nombre_seccion, columnas_obligatorias):
    """Valida que las filas tengan completos los campos obligatorios de la sección."""
    if df is None or df.empty:
        return
    errores = []
    for idx, row in df.iterrows():
        faltantes = [c for c in columnas_obligatorias if c in df.columns and valor_vacio(row[c])]
        if faltantes:
            errores.append(f"fila {idx + 1}: faltan {', '.join(faltantes)}")
    if errores:
        raise ValueError(
            f"En [{nombre_seccion}] hay filas incompletas. "
            "Completa los campos obligatorios o elimina esas filas.\n"
            + "\n".join(errores)
        )


def exigir_columnas(df, nombre_seccion, columnas_requeridas, errores):
    """Valida que una sección tenga las columnas requeridas de la plantilla estándar."""
    faltantes = [c for c in columnas_requeridas if c not in df.columns]
    if faltantes:
        errores.append(
            f"La sección [{nombre_seccion}] debe tener estas columnas: {', '.join(columnas_requeridas)}. "
            f"Faltan: {', '.join(faltantes)}."
        )


def validar_columnas_exactas(df, nombre_seccion, columnas_permitidas, errores):
    """Valida que no existan columnas por fuera de la plantilla estándar. Esto evita que el código interprete alias o nombres alternativos."""
    extras = [str(c) for c in df.columns if str(c).strip() not in columnas_permitidas]
    if extras:
        errores.append(
            f"La sección [{nombre_seccion}] contiene columnas no estándar: {', '.join(extras)}. "
            f"Usa exactamente las columnas permitidas: {', '.join(columnas_permitidas)}."
        )


def validar_valores_permitidos(serie, valores_permitidos, nombre_seccion, nombre_campo):
    """Valida que una columna solo contenga nombres permitidos por la plantilla."""
    valores = sorted({str(v).strip() for v in serie.tolist() if not valor_vacio(v)})
    invalidos = [v for v in valores if v not in valores_permitidos]
    if invalidos:
        raise ValueError(
            f"En [{nombre_seccion}], la columna '{nombre_campo}' contiene nombres no estándar: "
            f"{', '.join(invalidos)}.\n"
            f"Usa exactamente uno de estos valores: {', '.join(sorted(valores_permitidos))}."
        )


def convertir_binario_plantilla(valor, paciente, examen):
    """Convierte columnas 0/1 de la plantilla."""
    if pd.isna(valor) or valor == "":
        return 0
    try:
        v = int(valor)
    except Exception as e:
        raise ValueError(
            f"En [EXAMENES_PACIENTE], paciente {paciente}, examen {examen}, "
            f"se esperaba 0 o 1 y se encontró '{valor}'."
        ) from e
    if v not in (0, 1):
        raise ValueError(
            f"En [EXAMENES_PACIENTE], paciente {paciente}, examen {examen}, "
            f"se esperaba 0 o 1 y se encontró '{valor}'."
        )
    return v


def preparar_datos(tablas):
    """Prepara y valida las tablas del escenario estándar."""
    examenes_paciente = limpiar_si_no_vacio(tablas["examenes_paciente"])
    disp_pacientes = limpiar_si_no_vacio(tablas["disponibilidad_pacientes"])
    disp_recursos = limpiar_si_no_vacio(tablas["disponibilidad_recursos"])
    bloques_ocupados = limpiar_si_no_vacio(tablas.get("bloques_ocupados", pd.DataFrame()))
    examenes_externos = limpiar_si_no_vacio(tablas.get("examenes_externos", pd.DataFrame()))
    festivos_df = limpiar_si_no_vacio(tablas.get("festivos", pd.DataFrame()))

    errores = []
    advertencias = []

    exigir_columnas(examenes_paciente, "EXAMENES_PACIENTE", COLUMNAS_EXAMENES_PACIENTE, errores)
    exigir_columnas(disp_pacientes, "DISPONIBILIDAD_PACIENTES", COLUMNAS_DISPONIBILIDAD_PACIENTES, errores)
    exigir_columnas(disp_recursos, "DISPONIBILIDAD_RECURSOS", COLUMNAS_DISPONIBILIDAD_RECURSOS, errores)

    validar_columnas_exactas(
        examenes_paciente,
        "EXAMENES_PACIENTE",
        set(COLUMNAS_EXAMENES_PACIENTE) | {"comentario"},
        errores,
    )
    validar_columnas_exactas(
        disp_pacientes,
        "DISPONIBILIDAD_PACIENTES",
        set(COLUMNAS_DISPONIBILIDAD_PACIENTES) | {"comentario"},
        errores,
    )
    validar_columnas_exactas(
        disp_recursos,
        "DISPONIBILIDAD_RECURSOS",
        set(COLUMNAS_DISPONIBILIDAD_RECURSOS) | {"comentario"},
        errores,
    )

    if not bloques_ocupados.empty:
        exigir_columnas(bloques_ocupados, "BLOQUES_OCUPADOS", COLUMNAS_BLOQUES_OCUPADOS, errores)
        validar_columnas_exactas(
            bloques_ocupados,
            "BLOQUES_OCUPADOS",
            set(COLUMNAS_BLOQUES_OCUPADOS) | {"motivo", "comentario"},
            errores,
        )
    if not examenes_externos.empty:
        exigir_columnas(examenes_externos, "EXAMENES_EXTERNOS", COLUMNAS_EXAMENES_EXTERNOS, errores)
        validar_columnas_exactas(
            examenes_externos,
            "EXAMENES_EXTERNOS",
            set(COLUMNAS_EXAMENES_EXTERNOS) | {"resultado_fecha", "resultado_hora", "comentario"},
            errores,
        )
    if not festivos_df.empty:
        exigir_columnas(festivos_df, "FESTIVOS", COLUMNAS_FESTIVOS, errores)
        validar_columnas_exactas(festivos_df, "FESTIVOS", set(COLUMNAS_FESTIVOS) | {"descripcion", "comentario"}, errores)

    if errores:
        raise ValueError("\n".join(["Errores en estructura del Excel:"] + [f"- {e}" for e in errores]))

    # Limpiar filas opcionales que son solo residuos de formato de Excel.
    bloques_ocupados = quitar_filas_sin_identificador(bloques_ocupados, ["recurso"])
    examenes_externos = quitar_filas_sin_identificador(examenes_externos, ["paciente", "examen"])
    festivos_df = quitar_filas_sin_identificador(festivos_df, ["fecha"])

    if not bloques_ocupados.empty:
        exigir_campos_obligatorios(bloques_ocupados, "BLOQUES_OCUPADOS", COLUMNAS_BLOQUES_OCUPADOS)
    if not examenes_externos.empty:
        exigir_campos_obligatorios(examenes_externos, "EXAMENES_EXTERNOS", COLUMNAS_EXAMENES_EXTERNOS)
    if not festivos_df.empty:
        exigir_campos_obligatorios(festivos_df, "FESTIVOS", COLUMNAS_FESTIVOS)

    # Festivos
    festivos = set()
    if not festivos_df.empty:
        for _, r in festivos_df.iterrows():
            if pd.isna(r["fecha"]):
                continue
            festivos.add(convertir_fecha(r["fecha"], "fecha"))

    # Exámenes por paciente
    examenes_paciente["paciente"] = examenes_paciente["paciente"].astype(str).str.strip()
    examenes_paciente = examenes_paciente[examenes_paciente["paciente"] != ""].copy()

    if examenes_paciente.empty:
        raise ValueError("La sección [EXAMENES_PACIENTE] no tiene pacientes válidos.")

    examenes_reconocidos = sorted((EXAMENES_INTERNOS | EXAMENES_EXTERNOS) - {"salud_ocupacional"})
    for examen in examenes_reconocidos:
        if examen not in examenes_paciente.columns:
            raise ValueError(
                f"La columna '{examen}' debe existir en [EXAMENES_PACIENTE]. "
                "Conserva la estructura de la plantilla estándar."
            )

    for _, r in examenes_paciente.iterrows():
        paciente = r["paciente"]
        for examen in examenes_reconocidos:
            examenes_paciente.loc[examenes_paciente["paciente"] == paciente, examen] = convertir_binario_plantilla(
                r[examen], paciente, examen
            )

    # Salud ocupacional siempre se fuerza para todos los pacientes y no necesita columna en el Excel.
    examenes_paciente["salud_ocupacional"] = 1

    # Disponibilidad de pacientes
    disp_pacientes["paciente"] = disp_pacientes["paciente"].astype(str).str.strip()
    disp_pacientes["fecha"] = disp_pacientes["fecha"].apply(lambda x: convertir_fecha(x, "fecha"))
    disp_pacientes["inicio_min"] = disp_pacientes["inicio"].apply(minutos_de_hora)
    disp_pacientes["fin_min"] = disp_pacientes["fin"].apply(minutos_de_hora)
    disp_pacientes = disp_pacientes[disp_pacientes["fin_min"] > disp_pacientes["inicio_min"]].copy()
    if disp_pacientes.empty:
        raise ValueError("La sección [DISPONIBILIDAD_PACIENTES] no tiene ventanas válidas. Revisa fecha, inicio y fin.")

    # Disponibilidad de recursos
    disp_recursos["recurso"] = disp_recursos["recurso"].astype(str).str.strip()
    validar_valores_permitidos(
        disp_recursos["recurso"],
        RECURSOS_VALIDOS,
        "DISPONIBILIDAD_RECURSOS",
        "recurso",
    )
    disp_recursos["fecha"] = disp_recursos["fecha"].apply(lambda x: convertir_fecha(x, "fecha"))
    disp_recursos["inicio_min"] = disp_recursos["inicio"].apply(minutos_de_hora)
    disp_recursos["fin_min"] = disp_recursos["fin"].apply(minutos_de_hora)
    disp_recursos = disp_recursos[disp_recursos["fin_min"] > disp_recursos["inicio_min"]].copy()
    if disp_recursos.empty:
        raise ValueError("La sección [DISPONIBILIDAD_RECURSOS] no tiene ventanas válidas. Revisa fecha, inicio y fin.")

    # Bloques ocupados
    if not bloques_ocupados.empty:
        bloques_ocupados["recurso"] = bloques_ocupados["recurso"].astype(str).str.strip()
        validar_valores_permitidos(
            bloques_ocupados["recurso"],
            RECURSOS_VALIDOS,
            "BLOQUES_OCUPADOS",
            "recurso",
        )
        bloques_ocupados["fecha"] = bloques_ocupados["fecha"].apply(lambda x: convertir_fecha(x, "fecha"))
        bloques_ocupados["inicio_min"] = bloques_ocupados["inicio"].apply(minutos_de_hora)
        bloques_ocupados["fin_min"] = bloques_ocupados["fin"].apply(minutos_de_hora)
        bloques_ocupados = bloques_ocupados[bloques_ocupados["fin_min"] > bloques_ocupados["inicio_min"]].copy()
    else:
        bloques_ocupados = pd.DataFrame(columns=["recurso", "fecha", "inicio_min", "fin_min", "motivo"])

    # Exámenes externos
    if not examenes_externos.empty:
        examenes_externos["paciente"] = examenes_externos["paciente"].astype(str).str.strip()
        examenes_externos["examen"] = examenes_externos["examen"].astype(str).str.strip()
        validar_valores_permitidos(
            examenes_externos["examen"],
            EXAMENES_EXTERNOS,
            "EXAMENES_EXTERNOS",
            "examen",
        )
        examenes_externos["fecha"] = examenes_externos["fecha"].apply(lambda x: convertir_fecha(x, "fecha"))
        examenes_externos["inicio_min"] = examenes_externos["inicio"].apply(minutos_de_hora)
        examenes_externos["fin_min"] = examenes_externos["fin"].apply(minutos_de_hora)
        examenes_externos = examenes_externos[examenes_externos["fin_min"] > examenes_externos["inicio_min"]].copy()

        if "resultado_fecha" in examenes_externos.columns:
            examenes_externos["resultado_fecha"] = examenes_externos["resultado_fecha"].apply(
                lambda x: None if pd.isna(x) or x == "" else convertir_fecha(x, "resultado_fecha")
            )
        else:
            examenes_externos["resultado_fecha"] = None

        if "resultado_hora" in examenes_externos.columns:
            examenes_externos["resultado_hora_min"] = examenes_externos["resultado_hora"].apply(
                lambda x: None if pd.isna(x) or x == "" else minutos_de_hora(x)
            )
        else:
            examenes_externos["resultado_hora_min"] = None
    else:
        examenes_externos = pd.DataFrame(
            columns=["paciente", "examen", "fecha", "inicio_min", "fin_min", "resultado_fecha", "resultado_hora_min"]
        )

    # Validaciones de consistencia
    pacientes_req = set(examenes_paciente["paciente"])
    pacientes_disp = set(disp_pacientes["paciente"])

    pacientes_extra_disp = sorted(pacientes_disp - pacientes_req)
    if pacientes_extra_disp:
        raise ValueError(
            "En [DISPONIBILIDAD_PACIENTES] aparecen pacientes que no están en [EXAMENES_PACIENTE]: " +
            ", ".join(pacientes_extra_disp) +
            ". Revisa si hay un ID mal escrito o elimina esas filas del escenario."
        )

    faltan_disp = sorted(pacientes_req - pacientes_disp)
    if faltan_disp:
        raise ValueError(
            "Hay pacientes con exámenes requeridos pero sin disponibilidad registrada: " +
            ", ".join(faltan_disp) +
            ". Agrega al menos una ventana en [DISPONIBILIDAD_PACIENTES]."
        )

    recursos_necesarios = set()
    for examen, recursos in RECURSOS_POR_EXAMEN.items():
        if examen in examenes_paciente.columns and examenes_paciente[examen].sum() > 0:
            recursos_necesarios.update(recursos)
    recursos_disponibles = set(disp_recursos["recurso"])
    faltan_recursos = sorted(recursos_necesarios - recursos_disponibles)
    if faltan_recursos:
        raise ValueError(
            "Falta disponibilidad para los siguientes recursos requeridos: " +
            ", ".join(faltan_recursos) +
            ". En la plantilla, los nombres de recursos deben coincidir exactamente con RECURSOS_POR_EXAMEN."
        )

    # Validar que los exámenes externos correspondan a pacientes existentes.
    if not examenes_externos.empty:
        pacientes_extra_ext = sorted(set(examenes_externos["paciente"]) - pacientes_req)
        if pacientes_extra_ext:
            raise ValueError(
                "En [EXAMENES_EXTERNOS] aparecen pacientes que no están en [EXAMENES_PACIENTE]: " +
                ", ".join(pacientes_extra_ext) +
                ". Revisa si hay un ID mal escrito o elimina esas filas del escenario."
            )

    # Validar que los exámenes externos requeridos tengan cita fija registrada.
    requeridos_ext = []
    for _, r in examenes_paciente.iterrows():
        for ex in EXAMENES_EXTERNOS:
            if int(r[ex]) == 1:
                requeridos_ext.append((r["paciente"], ex))

    registrados_ext = set()
    if not examenes_externos.empty:
        registrados_ext = set(zip(examenes_externos["paciente"], examenes_externos["examen"]))

    faltan_ext = sorted(set(requeridos_ext) - registrados_ext)
    if faltan_ext:
        msg = "Faltan registros en [EXAMENES_EXTERNOS] para exámenes externos requeridos:\n"
        for p, ex in faltan_ext:
            msg += f"- Paciente {p}, examen {ex}\n"
        msg += "Agrega fecha, inicio y fin de la cita externa."
        raise ValueError(msg)

    externos_invalidos = sorted(set(examenes_externos["examen"]) - EXAMENES_EXTERNOS) if not examenes_externos.empty else []
    if externos_invalidos:
        raise ValueError(
            "En [EXAMENES_EXTERNOS] aparecen exámenes no definidos como externos: " +
            ", ".join(externos_invalidos) +
            ". Usa exactamente: imagenologia u otros_externos."
        )

    # Validar exámenes externos fijos del mismo paciente con separación suficiente.
    if not examenes_externos.empty:
        for paciente, grupo in examenes_externos.groupby("paciente"):
            grupo = grupo.sort_values(["fecha", "inicio_min"])
            for a, b in combinations(grupo.to_dict("records"), 2):
                if a["fecha"] != b["fecha"]:
                    continue
                sep1 = b["inicio_min"] - a["fin_min"]
                sep2 = a["inicio_min"] - b["fin_min"]
                if sep1 < TIEMPO_TRASLADO_EXTERNO_INTERNO and sep2 < TIEMPO_TRASLADO_EXTERNO_INTERNO:
                    raise ValueError(
                        f"El paciente {paciente} tiene exámenes externos el {a['fecha']} "
                        f"sin separación suficiente de {TIEMPO_TRASLADO_EXTERNO_INTERNO} min. "
                        "Ajusta las horas en [EXAMENES_EXTERNOS]."
                    )

    for _, r in disp_recursos.iterrows():
        if not es_dia_habil(r["fecha"], festivos):
            advertencias.append(
                f"Se encontró disponibilidad del recurso {r['recurso']} en día no hábil {r['fecha']}. "
                "El modelo no programará exámenes internos ese día."
            )

    return {
        "examenes_paciente": examenes_paciente,
        "disp_pacientes": disp_pacientes,
        "disp_recursos": disp_recursos,
        "bloques_ocupados": bloques_ocupados,
        "examenes_externos": examenes_externos,
        "festivos": festivos,
        "advertencias": advertencias,
    }

# _____________________________________________________
# MÓDULO 3 - GENERACIÓN DE CANTIDADOS
# _____________________________________________________

# VENTANAS LIBRES DE RECURSOS

def restar_intervalo(intervalos, ocupado):
    """Resta un intervalo ocupado a una lista de intervalos libres."""
    occ_ini, occ_fin = ocupado
    nuevos = []
    for ini, fin in intervalos:
        if occ_fin <= ini or occ_ini >= fin:
            nuevos.append((ini, fin))
        else:
            if occ_ini > ini:
                nuevos.append((ini, occ_ini))
            if occ_fin < fin:
                nuevos.append((occ_fin, fin))
    return nuevos


def intersecar_con_horario_centro(inicio, fin):
    """Intersecta una ventana con el horario 7-12 y 13-17 para evitar almuerzo y fuera de horario."""
    bloques = [
        (minutos_de_hora(HORA_APERTURA), minutos_de_hora(HORA_ALMUERZO_INICIO)),
        (minutos_de_hora(HORA_ALMUERZO_FIN), minutos_de_hora(HORA_CIERRE)),
    ]
    salida = []
    for b_ini, b_fin in bloques:
        ini = max(float(inicio), float(b_ini))
        f = min(float(fin), float(b_fin))
        if f > ini:
            salida.append((ini, f))
    return salida


def restringir_laboratorios_si_aplica(recurso, inicio, fin):
    """Si el recurso corresponde a laboratorios, limita la ventana a 7:00-10:00."""
    if recurso != "tecnico_laboratorios":
        return [(inicio, fin)]
    lab_ini = minutos_de_hora(LABORATORIOS_INICIO_PERMITIDO)
    lab_fin = minutos_de_hora(LABORATORIOS_FIN_PERMITIDO)
    ini = max(float(inicio), lab_ini)
    f = min(float(fin), lab_fin)
    return [(ini, f)] if f > ini else []


def construir_ventanas_libres_recursos(disp_recursos, bloques_ocupados, fecha_base, festivos):
    """Construye ventanas libres de recursos internos, descontando bloques ocupados y almuerzo."""
    filas_libres = []

    for _, row in disp_recursos.iterrows():
        recurso = row["recurso"]
        fecha = row["fecha"]

        if not es_dia_habil(fecha, festivos):
            continue

        # Intersectar disponibilidad declarada con horario del centro médico.
        ventanas_base = intersecar_con_horario_centro(row["inicio_min"], row["fin_min"])
        ventanas_ajustadas = []
        for ini, fin in ventanas_base:
            ventanas_ajustadas.extend(restringir_laboratorios_si_aplica(recurso, ini, fin))

        for inicio, fin in ventanas_ajustadas:
            libres = [(inicio, fin)]

            ocupados = bloques_ocupados[
                (bloques_ocupados["recurso"] == recurso) &
                (bloques_ocupados["fecha"] == fecha)
            ]

            for _, occ in ocupados.iterrows():
                occ_ini = float(occ["inicio_min"])
                occ_fin = float(occ["fin_min"])
                libres = restar_intervalo(libres, (occ_ini, occ_fin))

            for libre_ini, libre_fin in libres:
                if libre_fin > libre_ini:
                    bloque = obtener_bloque_por_intervalo(libre_ini, libre_fin)
                    if bloque == "fuera_bloque":
                        continue
                    filas_libres.append({
                        "recurso": recurso,
                        "fecha": fecha,
                        "bloque": bloque,
                        "inicio_min": libre_ini,
                        "fin_min": libre_fin,
                        "inicio_abs": abs_min(fecha, libre_ini, fecha_base),
                        "fin_abs": abs_min(fecha, libre_fin, fecha_base),
                    })

    return pd.DataFrame(filas_libres)

# DISPONIBILIDAD DE RESULTADOS Y EXÁMENES EXTERNOS

def resultado_y_liberacion_interno(examen, fecha_examen, inicio_local, fin_local, fecha_base, festivos):
    """Calcula:
    - resultado_abs: cuándo se considera disponible el resultado.
    - libera_salud_abs: desde cuándo ese examen permite hacer salud ocupacional.
    """
    fin_abs = abs_min(fecha_examen, fin_local, fecha_base)

    if examen not in EXAMENES_CON_RESULTADO_DIFERIDO:
        return fin_abs, fin_abs

    if examen == "laboratorios":
        # Resultado disponible mismo día a las 17:00.
        resultado_abs = abs_min(fecha_examen, minutos_de_hora(HORA_RESULTADO_LABORATORIOS), fecha_base)
        if LABORATORIOS_HABILITA_SALUD_DIA_HABIL_SIGUIENTE:
            fecha_liberacion = siguiente_dia_habil(fecha_examen, festivos)
            libera_salud_abs = abs_min(fecha_liberacion, minutos_de_hora(HORA_APERTURA), fecha_base)
        else:
            libera_salud_abs = resultado_abs
        return resultado_abs, libera_salud_abs

    if examen == "electrocardiograma":
        fecha_res = siguiente_dia_habil(fecha_examen, festivos)
        resultado_abs = abs_min(fecha_res, minutos_de_hora(HORA_RESULTADO_DIA_HABIL_SIGUIENTE), fecha_base)
        return resultado_abs, resultado_abs

    # Caso de respaldo para cualquier otro examen interno con resultado diferido.
    fecha_res = siguiente_dia_habil(fecha_examen, festivos)
    resultado_abs = abs_min(fecha_res, minutos_de_hora(HORA_RESULTADO_DIA_HABIL_SIGUIENTE), fecha_base)
    return resultado_abs, resultado_abs


def preparar_examenes_externos(examenes_externos, fecha_base, festivos):
    """Agrega tiempos absolutos y resultados a los exámenes externos fijos."""
    if examenes_externos.empty:
        return examenes_externos.copy()

    df = examenes_externos.copy()
    filas = []
    for _, r in df.iterrows():
        fecha = r["fecha"]
        inicio_min = float(r["inicio_min"])
        fin_min = float(r["fin_min"])
        examen = r["examen"]

        if pd.notna(r.get("resultado_fecha", None)) and r.get("resultado_fecha", None) is not None and r.get("resultado_hora_min", None) is not None:
            fecha_resultado = r["resultado_fecha"]
            hora_resultado = float(r["resultado_hora_min"])
            fecha_resultado = mismo_o_siguiente_habil(fecha_resultado, festivos)
        else:
            # Supuesto para imagenología y otros externos: cuando no se registra fecha resultado se asume disponible el siguiente día hábil a las 10:00.
            fecha_resultado = siguiente_dia_habil(fecha, festivos)
            hora_resultado = minutos_de_hora(HORA_RESULTADO_DIA_HABIL_SIGUIENTE)

        resultado_abs = abs_min(fecha_resultado, hora_resultado, fecha_base)
        bloque = obtener_bloque_por_intervalo(inicio_min, fin_min)

        fila = r.to_dict()
        fila.update({
            "inicio_abs": abs_min(fecha, inicio_min, fecha_base),
            "fin_abs": abs_min(fecha, fin_min, fecha_base),
            "resultado_abs": resultado_abs,
            "libera_salud_abs": resultado_abs,
            "resultado_fecha_calculada": fecha_resultado,
            "resultado_hora_calculada_min": hora_resultado,
            "bloque": bloque,
        })
        filas.append(fila)

    return pd.DataFrame(filas)

# OPERACIONES INTERNAS Y CANDIDATOS FACTIBLES

def construir_operaciones_y_candidatos(examenes_paciente, disp_pacientes, ventanas_recursos, fecha_base, festivos):
    """Crea las operaciones internas requeridas y sus candidatos factibles."""
    operaciones = []
    candidatos = []
    cand_id = 0

    # Disponibilidad de pacientes en minutos absolutos.
    disp_pacientes = disp_pacientes.copy()
    disp_pacientes["inicio_abs"] = disp_pacientes.apply(
        lambda r: abs_min(r["fecha"], float(r["inicio_min"]), fecha_base), axis=1
    )
    disp_pacientes["fin_abs"] = disp_pacientes.apply(
        lambda r: abs_min(r["fecha"], float(r["fin_min"]), fecha_base), axis=1
    )

    for _, row in examenes_paciente.iterrows():
        paciente = row["paciente"]
        disp_i = disp_pacientes[disp_pacientes["paciente"] == paciente]

        for examen in sorted(EXAMENES_INTERNOS):
            if int(row[examen]) != 1:
                continue

            op = (paciente, examen)
            operaciones.append(op)
            duracion = DURACIONES_ESTANDAR[examen]
            recursos_posibles = RECURSOS_POR_EXAMEN[examen]

            for recurso in recursos_posibles:
                ventanas_r = ventanas_recursos[ventanas_recursos["recurso"] == recurso]

                for _, vr in ventanas_r.iterrows():
                    fecha = vr["fecha"]
                    disp_i_fecha = disp_i[disp_i["fecha"] == fecha]

                    for _, vp in disp_i_fecha.iterrows():
                        # Intersección entre disponibilidad del paciente y del recurso.
                        inicio_inter = max(float(vr["inicio_abs"]), float(vp["inicio_abs"]))
                        fin_inter = min(float(vr["fin_abs"]), float(vp["fin_abs"]))

                        if fin_inter - inicio_inter >= duracion:
                            inicio_local = inicio_inter - (fecha - fecha_base).days * 1440
                            fin_local = fin_inter - (fecha - fecha_base).days * 1440
                            bloque = obtener_bloque_por_intervalo(inicio_local, fin_local)
                            if bloque == "fuera_bloque":
                                continue

                            resultado_abs, libera_salud_abs = resultado_y_liberacion_interno(
                                examen=examen,
                                fecha_examen=fecha,
                                inicio_local=inicio_local,
                                fin_local=fin_local,
                                fecha_base=fecha_base,
                                festivos=festivos,
                            )

                            candidatos.append({
                                "cand_id": cand_id,
                                "paciente": paciente,
                                "examen": examen,
                                "op": op,
                                "recurso": recurso,
                                "fecha": fecha,
                                "bloque": bloque,
                                "inicio_lb": inicio_inter,
                                "fin_ub": fin_inter,
                                "duracion": duracion,
                                "resultado_abs": resultado_abs,
                                "libera_salud_abs": libera_salud_abs,
                            })
                            cand_id += 1

    operaciones = list(dict.fromkeys(operaciones))
    candidatos = pd.DataFrame(candidatos)
    operaciones_sin_candidatos = []

    for op in operaciones:
        if candidatos.empty or candidatos[candidatos["op"] == op].empty:
            operaciones_sin_candidatos.append(op)

    return operaciones, candidatos, operaciones_sin_candidatos

# _____________________________________________________
# MÓDULO 4 - CONSTRUCCIÓN DEL MODELO MILP
# _____________________________________________________

def calcular_M(candidatos, externos_preparados):
    valores = [0]
    if not candidatos.empty:
        valores.extend(candidatos["inicio_lb"].tolist())
        valores.extend(candidatos["fin_ub"].tolist())
        valores.extend(candidatos["libera_salud_abs"].tolist())
    if not externos_preparados.empty:
        valores.extend(externos_preparados["inicio_abs"].tolist())
        valores.extend(externos_preparados["fin_abs"].tolist())
        valores.extend(externos_preparados["libera_salud_abs"].tolist())
    return max(M_RESPALDO, (max(valores) - min(valores)) + 14 * 1440)


def construir_modelo_milp(
    examenes_paciente,
    operaciones,
    candidatos,
    externos_preparados,
    fecha_base,
    permitir_no_programar=True,
):
    """Construye el modelo MILP. Si permitir_no_programar=True, activa diagnóstico de infactibilidad."""
    pacientes = list(examenes_paciente["paciente"].unique())
    op_idx = {op: k for k, op in enumerate(operaciones)}
    idx_op = {k: op for op, k in op_idx.items()}

    candidatos = candidatos.copy()
    if not candidatos.empty:
        candidatos["op_idx"] = candidatos["op"].map(op_idx)

    M = calcular_M(candidatos, externos_preparados)

# Modelo de minimización
    modelo = pl.LpProblem("Programacion_EMO_MILP", pl.LpMinimize)

    # Variables de tiempo por operación interna.
    S = {k: pl.LpVariable(f"S_op_{k}", lowBound=0) for k in idx_op}
    C = {k: pl.LpVariable(f"C_op_{k}", lowBound=0) for k in idx_op}
    R = {k: pl.LpVariable(f"R_op_{k}", lowBound=0) for k in idx_op}

    # Inicio y fin del proceso de cada paciente.
    B = {i: pl.LpVariable(f"B_{normalizar_texto(i)}", lowBound=0) for i in pacientes}
    F = {i: pl.LpVariable(f"F_{normalizar_texto(i)}", lowBound=0) for i in pacientes}

    # Variable binaria para seleccionar candidatos internos.
    z = {}
    if not candidatos.empty:
        z = {
            int(row["cand_id"]): pl.LpVariable(f"z_cand_{int(row['cand_id'])}", cat="Binary")
            for _, row in candidatos.iterrows()
        }

    # Diagnóstico de infactibilidad: variable que permite dejar una operación interna sin programar.
    omit = {}
    if permitir_no_programar:
        omit = {k: pl.LpVariable(f"omit_op_{k}", cat="Binary") for k in idx_op}
    else:
        omit = {k: 0 for k in idx_op}

    # Fechas/bloques posibles para visitas, incluyendo externas fijas.
    fechas_bloques = set()
    if not candidatos.empty:
        fechas_bloques.update((r["paciente"], r["fecha"], r["bloque"]) for _, r in candidatos.iterrows())
    if not externos_preparados.empty:
        fechas_bloques.update((r["paciente"], r["fecha"], r["bloque"]) for _, r in externos_preparados.iterrows())

    # Asegurar al menos fechas/bloques por paciente si no hay candidatos.
    y = {
        (p, f, b): pl.LpVariable(f"y_{normalizar_texto(p)}_{str(f)}_{b}", cat="Binary")
        for (p, f, b) in sorted(fechas_bloques, key=lambda x: (str(x[0]), str(x[1]), str(x[2])))
    }

# RESTRICCIONES
    # Asignación única de cada operación interna requerida
    for op, k in op_idx.items():
        if candidatos.empty:
            cand_op = []
        else:
            cand_op = candidatos[candidatos["op_idx"] == k]["cand_id"].astype(int).tolist()
        if permitir_no_programar:
            modelo += pl.lpSum(z[c] for c in cand_op) + omit[k] == 1, f"asignacion_o_diagnostico_op_{k}"
        else:
            modelo += pl.lpSum(z[c] for c in cand_op) == 1, f"asignacion_unica_op_{k}"

    # Duración de cada examen interno
    for op, k in op_idx.items():
        _, examen = op
        p = DURACIONES_ESTANDAR[examen]
        if permitir_no_programar:
            modelo += C[k] >= S[k] + p - M * omit[k], f"duracion_lb_op_{k}"
            modelo += C[k] <= S[k] + p + M * omit[k], f"duracion_ub_op_{k}"
        else:
            modelo += C[k] == S[k] + p, f"duracion_op_{k}"

    # Cumplimiento de la ventana candidata
    for _, row in candidatos.iterrows():
        c_id = int(row["cand_id"])
        k = int(row["op_idx"])
        modelo += S[k] >= float(row["inicio_lb"]) - M * (1 - z[c_id]), f"inicio_ventana_{c_id}"
        modelo += C[k] <= float(row["fin_ub"]) + M * (1 - z[c_id]), f"fin_ventana_{c_id}"

    # Disponibilidad de resultado de cada examen interno
    for op, k in op_idx.items():
        _, examen = op
        if examen not in EXAMENES_CON_RESULTADO_DIFERIDO:
            if permitir_no_programar:
                modelo += R[k] >= C[k] - M * omit[k], f"resultado_inmediato_lb_{k}"
                modelo += R[k] <= C[k] + M * omit[k], f"resultado_inmediato_ub_{k}"
            else:
                modelo += R[k] == C[k], f"resultado_inmediato_{k}"
        else:
            if permitir_no_programar:
                modelo += R[k] >= C[k] - M * omit[k], f"resultado_despues_fin_{k}"
            else:
                modelo += R[k] >= C[k], f"resultado_despues_fin_{k}"
            cand_op = candidatos[candidatos["op_idx"] == k] if not candidatos.empty else pd.DataFrame()
            for _, row in cand_op.iterrows():
                c_id = int(row["cand_id"])
                libera = float(row["libera_salud_abs"])
                modelo += R[k] >= libera - M * (1 - z[c_id]), f"resultado_diferido_{c_id}"

    # Activación de visitas por fecha y bloque
    for _, row in candidatos.iterrows():
        c_id = int(row["cand_id"])
        key = (row["paciente"], row["fecha"], row["bloque"])
        if key in y:
            modelo += y[key] >= z[c_id], f"activa_visita_interna_{c_id}"

    # Externos fijos activan visitas
    for idx, row in externos_preparados.iterrows():
        key = (row["paciente"], row["fecha"], row["bloque"])
        if key in y:
            modelo += y[key] >= 1, f"activa_visita_externa_{idx}"

    # No superposición del paciente entre operaciones internas
    ops_por_paciente = {}
    for op, k in op_idx.items():
        paciente, _ = op
        ops_por_paciente.setdefault(paciente, []).append(k)

    for paciente, ops in ops_por_paciente.items():
        for k1, k2 in combinations(ops, 2):
            u = pl.LpVariable(f"u_paciente_{normalizar_texto(paciente)}_{k1}_{k2}", cat="Binary")
            relajacion_omit = M * (omit[k1] + omit[k2]) if permitir_no_programar else 0
            modelo += S[k2] >= C[k1] - M * (1 - u) - relajacion_omit, f"no_sol_pac_1_{normalizar_texto(paciente)}_{k1}_{k2}"
            modelo += S[k1] >= C[k2] - M * u - relajacion_omit, f"no_sol_pac_2_{normalizar_texto(paciente)}_{k1}_{k2}"

    # Separación entre exámenes internos y externos
    if not externos_preparados.empty and not candidatos.empty:
        for _, row_c in candidatos.iterrows():
            c_id = int(row_c["cand_id"])
            k = int(row_c["op_idx"])
            paciente = row_c["paciente"]
            fecha = row_c["fecha"]
            externos_i = externos_preparados[
                (externos_preparados["paciente"] == paciente) &
                (externos_preparados["fecha"] == fecha)
            ]
            for idx_ext, row_e in externos_i.iterrows():
                q = pl.LpVariable(f"q_ext_int_{c_id}_{idx_ext}", cat="Binary")
                ext_ini = float(row_e["inicio_abs"])
                ext_fin = float(row_e["fin_abs"])
                t = TIEMPO_TRASLADO_EXTERNO_INTERNO
                # q = 0: interno antes del externo.
                modelo += C[k] <= ext_ini - t + M * (1 - z[c_id] + q), f"interno_antes_externo_{c_id}_{idx_ext}"
                # q = 1: interno después del externo.
                modelo += S[k] >= ext_fin + t - M * (1 - z[c_id] + 1 - q), f"interno_despues_externo_{c_id}_{idx_ext}"

    # No superposición del recurso
    if not candidatos.empty:
        grupos_recurso_fecha = candidatos.groupby(["recurso", "fecha"])

        for (recurso, fecha), grupo in grupos_recurso_fecha:
            ops_grupo = sorted(grupo["op_idx"].unique())

            for k1, k2 in combinations(ops_grupo, 2):
                cand_k1 = grupo[grupo["op_idx"] == k1]["cand_id"].astype(int).tolist()
                cand_k2 = grupo[grupo["op_idx"] == k2]["cand_id"].astype(int).tolist()

                asigna_k1 = pl.lpSum(z[c] for c in cand_k1)
                asigna_k2 = pl.lpSum(z[c] for c in cand_k2)

                v = pl.LpVariable(f"v_recurso_{recurso}_{str(fecha)}_{k1}_{k2}", cat="Binary")

                modelo += (
                    S[k2] >= C[k1]
                    - M * (1 - v)
                    - M * (2 - asigna_k1 - asigna_k2)
                ), f"no_sol_rec_1_{recurso}_{fecha}_{k1}_{k2}"

                modelo += (
                    S[k1] >= C[k2]
                    - M * v
                    - M * (2 - asigna_k1 - asigna_k2)
                ), f"no_sol_rec_2_{recurso}_{fecha}_{k1}_{k2}"

    # Disponibilidad de resultados antes de salud ocupacional
    for paciente, ops in ops_por_paciente.items():
        salud_ops = [k for k in ops if idx_op[k][1] == "salud_ocupacional"]
        if not salud_ops:
            raise ValueError(f"El paciente {paciente} no tiene salud ocupacional asignada.")
        k_salud = salud_ops[0]

    # Precedencia de salud ocupacional respecto a los demás exámenes
        # Exámenes internos antes de salud ocupacional
        for k in ops:
            examen = idx_op[k][1]
            if examen == "salud_ocupacional":
                continue
            if permitir_no_programar:
                modelo += S[k_salud] >= R[k] - M * (omit[k] + omit[k_salud]), f"precedencia_salud_int_{normalizar_texto(paciente)}_{k}"
            else:
                modelo += S[k_salud] >= R[k], f"precedencia_salud_int_{normalizar_texto(paciente)}_{k}"

        # Exámenes externos antes de salud ocupacional
        externos_i = externos_preparados[externos_preparados["paciente"] == paciente]
        for idx_ext, row_e in externos_i.iterrows():
            libera = float(row_e["libera_salud_abs"])
            if permitir_no_programar:
                modelo += S[k_salud] >= libera - M * omit[k_salud], f"precedencia_salud_ext_{normalizar_texto(paciente)}_{idx_ext}"
            else:
                modelo += S[k_salud] >= libera, f"precedencia_salud_ext_{normalizar_texto(paciente)}_{idx_ext}"

    # Definición del inicio y finalización del proceso del paciente
    for paciente, ops in ops_por_paciente.items():
        for k in ops:
            if permitir_no_programar:
                modelo += B[paciente] <= S[k] + M * omit[k], f"inicio_proceso_int_{normalizar_texto(paciente)}_{k}"
                modelo += F[paciente] >= C[k] - M * omit[k], f"fin_proceso_int_{normalizar_texto(paciente)}_{k}"
            else:
                modelo += B[paciente] <= S[k], f"inicio_proceso_int_{normalizar_texto(paciente)}_{k}"
                modelo += F[paciente] >= C[k], f"fin_proceso_int_{normalizar_texto(paciente)}_{k}"

        # Externos también hacen parte del proceso del paciente.
        externos_i = externos_preparados[externos_preparados["paciente"] == paciente]
        for idx_ext, row_e in externos_i.iterrows():
            modelo += B[paciente] <= float(row_e["inicio_abs"]), f"inicio_proceso_ext_{normalizar_texto(paciente)}_{idx_ext}"
            modelo += F[paciente] >= float(row_e["fin_abs"]), f"fin_proceso_ext_{normalizar_texto(paciente)}_{idx_ext}"

    # Función objetivo
    expr_tiempo = pl.lpSum(F[i] - B[i] for i in pacientes)

    expr_omision = pl.lpSum(omit[k] for k in idx_op) if permitir_no_programar else 0

    if permitir_no_programar:
        # En diagnóstico de infactibilidad, primero busca programar lo máximo posible.
        objetivo = PENALIZACION_NO_PROGRAMADO * expr_omision + expr_tiempo
    else:
        objetivo = expr_tiempo

    modelo += objetivo, "funcion_objetivo"

    objetos = {
        "modelo": modelo,
        "op_idx": op_idx,
        "idx_op": idx_op,
        "S": S,
        "C": C,
        "R": R,
        "B": B,
        "F": F,
        "z": z,
        "y": y,
        "omit": omit,
        "expr_tiempo": expr_tiempo,
        "expr_omision": expr_omision,
        "candidatos": candidatos,
        "externos_preparados": externos_preparados,
        "M": M,
        "permitir_no_programar": permitir_no_programar,
    }
    return objetos

# _____________________________________________________
# MÓDULO 5 - SOLUCIÓN DEL MODELO MILP
# _____________________________________________________

def crear_solver(msg=True):
    """Crea el solver que se usará para resolver el modelo."""
    log_path = LOG_SOLVER if GUARDAR_LOG_SOLVER else None

    # SOLVER CBC
    #solver = pl.PULP_CBC_CMD(
    #    msg=msg,
    #    timeLimit=TIME_LIMIT_SOLVER,
    #    gapRel=MIP_GAP,
    #)

    # SOLVER HiGHS
    solver = pl.HiGHS(
         msg=msg,
         timeLimit=TIME_LIMIT_SOLVER,
         gapRel=MIP_GAP,
     )

    # SOLVER Gurobi
    #solver = pl.GUROBI(
    #     msg=msg,
    #     timeLimit=TIME_LIMIT_SOLVER,
    #     gapRel=MIP_GAP,
    #)

    return solver


def leer_log_solver():
    """Lee el log del solver si existe."""
    if not GUARDAR_LOG_SOLVER or not LOG_SOLVER:
        return ""
    if not os.path.exists(LOG_SOLVER):
        return ""
    try:
        with open(LOG_SOLVER, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""


def analizar_log_solver(texto_log):
    """Busca señales útiles en el texto del log del solver."""
    t = (texto_log or "").lower()
    return {
        "log_disponible": bool(t.strip()),
        "log_indica_limite_tiempo": any(frase in t for frase in [
            "time limit", "timelimit", "time-limit", "seconds was changed", "stopped on time",
            "reached time limit", "time limit reached", "limite de tiempo",
        ]),
        "log_indica_optimo": any(frase in t for frase in [
            "optimal solution found", "optimal - objective", "status: optimal", "model status        : optimal",
        ]),
        "log_indica_infactible": any(frase in t for frase in [
            "infeasible", "infeasibility", "primal infeasible", "model status        : infeasible",
        ]),
        "log_indica_no_solucion_factible": any(frase in t for frase in [
            "no feasible solution", "no integer solution", "no solution found", "solution count 0",
        ]),
        "log_indica_gap": any(frase in t for frase in [
            "gap", "mipgap", "relative gap", "gap tolerance",
        ]),
    }


def extraer_info_solver_especifico(modelo):
    """Extrae información adicional cuando el solver deja un objeto interno disponible."""
    info = {}
    solver_model = getattr(modelo, "solverModel", None)
    if solver_model is None:
        return info

    # Estados de Gurobi.
    mapa_gurobi = {
        1: "LOADED",
        2: "OPTIMAL",
        3: "INFEASIBLE",
        4: "INF_OR_UNBD",
        5: "UNBOUNDED",
        6: "CUTOFF",
        7: "ITERATION_LIMIT",
        8: "NODE_LIMIT",
        9: "TIME_LIMIT",
        10: "SOLUTION_LIMIT",
        11: "INTERRUPTED",
        12: "NUMERIC",
        13: "SUBOPTIMAL",
        14: "INPROGRESS",
        15: "USER_OBJ_LIMIT",
        16: "WORK_LIMIT",
        17: "MEM_LIMIT",
    }

    try:
        status_num = getattr(solver_model, "Status", None)
        if status_num is not None:
            info["estado_solver_codigo"] = status_num
            info["estado_solver_texto"] = mapa_gurobi.get(status_num, str(status_num))
    except Exception:
        pass

    for attr, nombre in [
        ("SolCount", "soluciones_encontradas_solver"),
        ("ObjVal", "objetivo_solver"),
        ("ObjBound", "mejor_cota_solver"),
        ("MIPGap", "gap_solver"),
        ("Runtime", "runtime_solver"),
        ("NodeCount", "nodos_explorados_solver"),
    ]:
        try:
            info[nombre] = getattr(solver_model, attr)
        except Exception:
            pass

    return info


def contar_operaciones_omitidas(objetos):
    """Cuenta cuántas operaciones quedaron omitidas en modo diagnóstico."""
    if not bool(objetos.get("permitir_no_programar", True)):
        return 0
    omit = objetos.get("omit", {})
    total = 0
    for _, var in omit.items():
        try:
            if hasattr(var, "varValue") and pl.value(var) is not None and pl.value(var) > 0.5:
                total += 1
        except Exception:
            pass
    return total


def hay_alguna_solucion_entera(objetos):
    """
    Verifica si se recibió alguna selección de candidatos con valores enteros utilizables.
    Sirve como apoyo cuando el estado de PuLP es poco informativo por límite de tiempo.
    """
    z = objetos.get("z", {})
    if not z:
        return False
    seleccionados = 0
    for _, var in z.items():
        try:
            val = pl.value(var)
            if val is not None and val > 0.5:
                seleccionados += 1
        except Exception:
            pass
    return seleccionados > 0


def clasificar_estado_solucion(modelo, estado_pulp, estado_solucion_pulp, objetos, info_log, info_solver):
    """
    Clasifica la solución en términos operativos para interpretar qué pasó.
    """
    permitir_no_programar = bool(objetos.get("permitir_no_programar", True))
    operaciones_omitidas = contar_operaciones_omitidas(objetos)
    programo_todos = (operaciones_omitidas == 0)

    estado_solver_texto = str(info_solver.get("estado_solver_texto", "")).upper()
    sol_count = info_solver.get("soluciones_encontradas_solver", None)

    hay_solucion_por_solver = False
    if sol_count is not None:
        try:
            hay_solucion_por_solver = int(sol_count) > 0
        except Exception:
            hay_solucion_por_solver = False

    hay_solucion = (
        estado_pulp in {"Optimal", "Feasible"}
        or "solution found" in str(estado_solucion_pulp).lower()
        or hay_solucion_por_solver
        or hay_alguna_solucion_entera(objetos)
    )

    limite_tiempo = bool(info_log.get("log_indica_limite_tiempo", False)) or estado_solver_texto == "TIME_LIMIT"
    infactible = estado_pulp == "Infeasible" or bool(info_log.get("log_indica_infactible", False)) or estado_solver_texto == "INFEASIBLE"
    no_acotado = estado_pulp == "Unbounded" or estado_solver_texto == "UNBOUNDED"
    numerico = estado_solver_texto in {"NUMERIC", "SUBOPTIMAL"}

    if estado_pulp == "Optimal" and not limite_tiempo and programo_todos:
        clasificacion = "OPTIMA_COMPLETA"
        interpretacion = "El solver reporta solución óptima y todas las operaciones requeridas fueron programadas."
    elif estado_pulp == "Optimal" and not programo_todos:
        clasificacion = "RESPUESTA_DIAGNOSTICO_NO_PROGRAMO_TODOS"
        interpretacion = (
            "El modelo de diagnóstico encontró una solución, pero dejó operaciones sin programar. "
            "Revisa la tabla de diagnóstico de no programados."
        )
    elif hay_solucion and limite_tiempo and programo_todos:
        clasificacion = "FACTIBLE_POR_LIMITE_TIEMPO"
        interpretacion = (
            "El solver encontró una solución factible y programó todo, pero se detuvo por límite de tiempo. "
            "No se certificó optimalidad."
        )
    elif hay_solucion and not programo_todos:
        clasificacion = "RESPUESTA_DIAGNOSTICO_NO_PROGRAMO_TODOS"
        interpretacion = (
            "Se obtuvo una respuesta en modo diagnóstico, pero no se programaron todas las operaciones. "
            "Esto suele indicar falta de ventanas factibles o conflicto de restricciones."
        )
    elif hay_solucion:
        clasificacion = "FACTIBLE_NO_CERTIFICADA_OPTIMA"
        interpretacion = (
            "Se encontró una solución factible, pero el estado no certifica optimalidad. "
            "Revisa gap, límite de tiempo y log del solver."
        )
    elif infactible:
        clasificacion = "INFACTIBLE"
        interpretacion = (
            "El solver indica que no existe solución factible con las restricciones actuales. "
            "Revisa disponibilidad de pacientes, recursos, resultados diferidos, externos y salud ocupacional."
        )
    elif no_acotado:
        clasificacion = "NO_ACOTADO"
        interpretacion = "El solver indica que el modelo es no acotado. Revisa cotas de variables de tiempo y función objetivo."
    elif numerico:
        clasificacion = "PROBLEMA_NUMERICO"
        interpretacion = "El solver reporta problemas numéricos. Revisa el valor de M y escalas de tiempo."
    elif limite_tiempo:
        clasificacion = "SIN_SOLUCION_POR_LIMITE_TIEMPO"
        interpretacion = (
            "El solver se detuvo por límite de tiempo y no se identificó una solución factible utilizable. "
            "Puedes ampliar el tiempo, relajar el gap o activar el modo diagnóstico."
        )
    else:
        clasificacion = "NO_RESUELTO_O_ESTADO_NO_IDENTIFICADO"
        interpretacion = (
            "No se pudo certificar una solución. Revisa el log del solver, la instalación del solver, "
            "los datos de entrada y los mensajes de error previos."
        )

    return {
        "clasificacion_estado": clasificacion,
        "interpretacion_estado": interpretacion,
        "hay_solucion_utilizable": hay_solucion,
        "programo_todos": programo_todos,
        "operaciones_omitidas": operaciones_omitidas,
        "se_detuvo_por_limite_tiempo": limite_tiempo,
        "es_infactible": infactible,
        "es_no_acotado": no_acotado,
        "problema_numerico": numerico,
    }


def resolver_con_solver(modelo, objetos, msg=True):
    """Resuelve el modelo con el solver seleccionado y devuelve diagnóstico ampliado."""
    if GUARDAR_LOG_SOLVER and LOG_SOLVER and os.path.exists(LOG_SOLVER):
        try:
            os.remove(LOG_SOLVER)
        except Exception:
            pass

    solver = crear_solver(msg=msg)

    t0 = time_module.time()
    try:
        modelo.solve(solver)
        error_ejecucion = None
    except Exception as e:
        t1 = time_module.time()
        return {
            "estado": "Error",
            "estado_pulp": "Error",
            "estado_solucion_pulp": None,
            "tiempo_ejecucion_seg": t1 - t0,
            "solver_usado": NOMBRE_SOLVER,
            "error_ejecucion": str(e),
            "clasificacion_estado": "ERROR_EJECUCION_SOLVER",
            "interpretacion_estado": (
                "El solver no pudo ejecutarse. Revisa instalación, licencia, ruta del ejecutable, "
                "compatibilidad del solver o parámetros enviados."
            ),
            "hay_solucion_utilizable": False,
            "programo_todos": False,
            "operaciones_omitidas": None,
            "se_detuvo_por_limite_tiempo": False,
        }
    t1 = time_module.time()

    estado_pulp = pl.LpStatus.get(modelo.status, str(modelo.status))
    estado_solucion_codigo = getattr(modelo, "sol_status", None)
    estado_solucion_pulp = pl.LpSolution.get(estado_solucion_codigo, str(estado_solucion_codigo))

    texto_log = leer_log_solver()
    info_log = analizar_log_solver(texto_log)
    info_solver = extraer_info_solver_especifico(modelo)
    clasificacion = clasificar_estado_solucion(
        modelo=modelo,
        estado_pulp=estado_pulp,
        estado_solucion_pulp=estado_solucion_pulp,
        objetos=objetos,
        info_log=info_log,
        info_solver=info_solver,
    )

    resultado = {
        "estado": estado_pulp,
        "estado_pulp": estado_pulp,
        "estado_solucion_pulp": estado_solucion_pulp,
        "codigo_estado_pulp": modelo.status,
        "codigo_estado_solucion_pulp": estado_solucion_codigo,
        "tiempo_ejecucion_seg": t1 - t0,
        "solver_usado": NOMBRE_SOLVER,
        "archivo_log_solver": LOG_SOLVER if info_log.get("log_disponible") else None,
        "error_ejecucion": None,
        **info_log,
        **info_solver,
        **clasificacion,
    }
    return resultado


def imprimir_diagnostico_solucion(resultado_solve):
    """Imprime en consola un resumen claro del estado de solución."""
    print("\n===== DIAGNÓSTICO DEL ESTADO DE LA SOLUCIÓN =====")
    print(f"Solver usado: {resultado_solve.get('solver_usado')}")
    print(f"Estado PuLP: {resultado_solve.get('estado_pulp')}")
    print(f"Estado solución PuLP: {resultado_solve.get('estado_solucion_pulp')}")

    if resultado_solve.get("estado_solver_texto"):
        print(f"Estado específico del solver: {resultado_solve.get('estado_solver_texto')}")
    if resultado_solve.get("soluciones_encontradas_solver") is not None:
        print(f"Soluciones encontradas por solver: {resultado_solve.get('soluciones_encontradas_solver')}")
    if resultado_solve.get("mejor_cota_solver") is not None:
        print(f"Mejor cota del solver: {resultado_solve.get('mejor_cota_solver')}")
    if resultado_solve.get("gap_solver") is not None:
        print(f"Gap reportado por solver: {resultado_solve.get('gap_solver')}")

    print(f"Clasificación: {resultado_solve.get('clasificacion_estado')}")
    print(f"Interpretación: {resultado_solve.get('interpretacion_estado')}")
    print(f"¿Hay solución utilizable?: {resultado_solve.get('hay_solucion_utilizable')}")
    print(f"¿Programó todos?: {resultado_solve.get('programo_todos')}")
    print(f"Operaciones omitidas: {resultado_solve.get('operaciones_omitidas')}")
    print(f"¿Se detuvo por límite de tiempo?: {resultado_solve.get('se_detuvo_por_limite_tiempo')}")
    print(f"Tiempo de ejecución: {resultado_solve.get('tiempo_ejecucion_seg', 0):.2f} segundos")

    if resultado_solve.get("archivo_log_solver"):
        print(f"Log del solver: {resultado_solve.get('archivo_log_solver')}")
    if resultado_solve.get("error_ejecucion"):
        print(f"Error de ejecución: {resultado_solve.get('error_ejecucion')}")


def resolver_modelo(objetos, msg=True):
    """
    Resuelve el modelo con el objetivo de minimizar tiempo total en el sistema.
    Si el modelo está en modo diagnóstico de infactibilidad, agrega primero una penalización muy grande
    por operaciones no programadas para identificar dónde está el problema.
    """
    modelo = objetos["modelo"]
    expr_tiempo = objetos["expr_tiempo"]
    expr_omision = objetos["expr_omision"]
    permitir_no_programar = bool(objetos.get("permitir_no_programar", True))

    if permitir_no_programar:
        modelo.objective = (
            PENALIZACION_NO_PROGRAMADO * expr_omision
            + expr_tiempo
        )
        resultado = resolver_con_solver(modelo, objetos, msg=msg)
        resultado.update({
            "valor_objetivo": pl.value(modelo.objective),
            "valor_tiempo_sistema_modelo": pl.value(expr_tiempo),
            "valor_omisiones": pl.value(expr_omision),
        })
        return resultado

    modelo.objective = expr_tiempo
    resultado = resolver_con_solver(modelo, objetos, msg=msg)
    resultado.update({
        "valor_objetivo": pl.value(modelo.objective),
        "valor_tiempo_sistema_modelo": pl.value(expr_tiempo),
        "valor_omisiones": None,
    })
    return resultado

# _____________________________________________________
# MÓDULO 6 - GENERACIÓN DE RESULTADOS Y MÉTRICAS
# _____________________________________________________

def valor_var(x):
    try:
        return pl.value(x)
    except Exception:
        return None


def construir_agenda(objetos, fecha_base):
    """Construye agenda consolidada: internos seleccionados + externos fijos."""
    candidatos = objetos["candidatos"]
    externos = objetos["externos_preparados"]
    idx_op = objetos["idx_op"]
    S, C, R, z = objetos["S"], objetos["C"], objetos["R"], objetos["z"]
    omit = objetos["omit"]

    filas = []

    # Internos seleccionados
    for _, row in candidatos.iterrows():
        c_id = int(row["cand_id"])
        if c_id in z and valor_var(z[c_id]) is not None and valor_var(z[c_id]) > 0.5:
            k = int(row["op_idx"])
            paciente, examen = idx_op[k]
            s_val = valor_var(S[k])
            c_val = valor_var(C[k])
            r_val = valor_var(R[k])
            fecha_ini, hora_ini = fecha_hora_desde_abs(s_val, fecha_base)
            fecha_fin, hora_fin = fecha_hora_desde_abs(c_val, fecha_base)
            fecha_res, hora_res = fecha_hora_desde_abs(float(row["resultado_abs"]), fecha_base)
            fecha_lib, hora_lib = fecha_hora_desde_abs(r_val, fecha_base)

            filas.append({
                "tipo": "interno",
                "paciente": paciente,
                "fecha": fecha_ini,
                "bloque": row["bloque"],
                "especialidad": examen,
                "recurso": row["recurso"],
                "hora_inicio": hora_ini,
                "hora_fin": hora_fin,
                "duracion_min": DURACIONES_ESTANDAR[examen],
                "resultado_disponible_fecha": fecha_res if examen in EXAMENES_CON_RESULTADO_DIFERIDO else "No aplica",
                "resultado_disponible_hora": hora_res if examen in EXAMENES_CON_RESULTADO_DIFERIDO else "No aplica",
                "salud_habilitada_fecha": fecha_lib if examen in EXAMENES_CON_RESULTADO_DIFERIDO else "No aplica",
                "salud_habilitada_hora": hora_lib if examen in EXAMENES_CON_RESULTADO_DIFERIDO else "No aplica",
                "inicio_abs": s_val,
                "fin_abs": c_val,
                "resultado_abs": float(row["resultado_abs"]),
                "libera_salud_abs": r_val,
            })

    # Externos fijos
    for _, row in externos.iterrows():
        fecha_ini, hora_ini = fecha_hora_desde_abs(float(row["inicio_abs"]), fecha_base)
        fecha_fin, hora_fin = fecha_hora_desde_abs(float(row["fin_abs"]), fecha_base)
        fecha_res, hora_res = fecha_hora_desde_abs(float(row["resultado_abs"]), fecha_base)
        filas.append({
            "tipo": "externo",
            "paciente": row["paciente"],
            "fecha": fecha_ini,
            "bloque": row["bloque"],
            "especialidad": row["examen"],
            "recurso": "externo",
            "hora_inicio": hora_ini,
            "hora_fin": hora_fin,
            "duracion_min": round(float(row["fin_abs"] - row["inicio_abs"]), 2),
            "resultado_disponible_fecha": fecha_res,
            "resultado_disponible_hora": hora_res,
            "salud_habilitada_fecha": fecha_res,
            "salud_habilitada_hora": hora_res,
            "inicio_abs": float(row["inicio_abs"]),
            "fin_abs": float(row["fin_abs"]),
            "resultado_abs": float(row["resultado_abs"]),
            "libera_salud_abs": float(row["libera_salud_abs"]),
        })

    agenda = pd.DataFrame(filas)
    if not agenda.empty:
        agenda = agenda.sort_values(["paciente", "inicio_abs", "tipo"]).reset_index(drop=True)
    return agenda


def construir_diagnostico_no_programados(objetos):
    """Devuelve operaciones omitidas en el modo diagnóstico."""
    omit = objetos["omit"]
    idx_op = objetos["idx_op"]
    filas = []
    for k, var in omit.items():
        if hasattr(var, "varValue") and valor_var(var) is not None and valor_var(var) > 0.5:
            paciente, examen = idx_op[k]
            filas.append({"paciente": paciente, "examen": examen, "motivo_probable": "Sin ventana factible o conflicto de restricciones"})
    return pd.DataFrame(filas)


def calcular_metricas(agenda, objetos, resultado_solve, fecha_base, ventanas_recursos):
    """Calcula métricas de solución, paciente, visitas, espera, resultados, agenda y recursos."""
    pacientes = sorted(agenda["paciente"].unique()) if not agenda.empty else []
    B, F = objetos["B"], objetos["F"]

    # Métricas por paciente
    filas_paciente = []
    for p in pacientes:
        ag_p = agenda[agenda["paciente"] == p].sort_values("inicio_abs")
        b_val = min(ag_p["inicio_abs"])
        f_val = max(ag_p["fin_abs"])
        fecha_inicio, hora_inicio = fecha_hora_desde_abs(b_val, fecha_base)
        fecha_fin, hora_fin = fecha_hora_desde_abs(f_val, fecha_base)

        # Visitas por paciente-fecha-bloque
        visitas = ag_p[["fecha", "bloque"]].drop_duplicates()
        num_visitas = len(visitas)

        # Tiempo teórico presencial dedicado a atención: suma de duraciones de citas
        # No incluye espera entre exámenes.
        tiempo_atencion = ag_p["duracion_min"].sum()

        # Tiempo presencial por visita: desde primera cita hasta última cita dentro de cada fecha-bloque
        tiempo_presencial_bloque = 0
        for _, g in ag_p.groupby(["fecha", "bloque"]):
            tiempo_presencial_bloque += g["fin_abs"].max() - g["inicio_abs"].min()

        # Esperas entre citas consecutivas del paciente
        espera_total = 0
        espera_antes_salud = None
        for i in range(len(ag_p) - 1):
            espera_total += max(0, ag_p.iloc[i + 1]["inicio_abs"] - ag_p.iloc[i]["fin_abs"])
        salud = ag_p[ag_p["especialidad"] == "salud_ocupacional"]
        if not salud.empty:
            s_salud = salud.iloc[0]["inicio_abs"]
            previos = ag_p[ag_p["fin_abs"] <= s_salud]
            previos = previos[previos["especialidad"] != "salud_ocupacional"]
            if not previos.empty:
                espera_antes_salud = s_salud - previos["fin_abs"].max()

        filas_paciente.append({
            "paciente": p,
            "inicio_proceso_fecha": fecha_inicio,
            "inicio_proceso_hora": hora_inicio,
            "fin_proceso_fecha": fecha_fin,
            "fin_proceso_hora": hora_fin,
            "tiempo_sistema_min": round(f_val - b_val, 2),
            "tiempo_sistema_horas": round((f_val - b_val) / 60, 2),
            "tiempo_teorico_atencion_min": round(tiempo_atencion, 2),
            "tiempo_presencial_por_bloques_min": round(tiempo_presencial_bloque, 2),
            "numero_visitas": int(num_visitas),
            "espera_total_entre_citas_min": round(espera_total, 2),
            "espera_antes_salud_ocupacional_min": None if espera_antes_salud is None else round(espera_antes_salud, 2),
        })

    metricas_paciente = pd.DataFrame(filas_paciente)

    # Métricas de disponibilidad de resultados
    filas_resultados = []
    if not agenda.empty:
        for _, r in agenda.iterrows():
            if r["especialidad"] in EXAMENES_CON_RESULTADO_DIFERIDO:
                filas_resultados.append({
                    "paciente": r["paciente"],
                    "especialidad": r["especialidad"],
                    "tipo": r["tipo"],
                    "fecha_examen": r["fecha"],
                    "hora_fin_examen": r["hora_fin"],
                    "resultado_disponible_fecha": r["resultado_disponible_fecha"],
                    "resultado_disponible_hora": r["resultado_disponible_hora"],
                    "tiempo_fin_a_resultado_min": round(float(r["resultado_abs"] - r["fin_abs"]), 2),
                    "salud_habilitada_fecha": r["salud_habilitada_fecha"],
                    "salud_habilitada_hora": r["salud_habilitada_hora"],
                    "tiempo_fin_a_habilitacion_salud_min": round(float(r["libera_salud_abs"] - r["fin_abs"]), 2),
                })
    metricas_resultados = pd.DataFrame(filas_resultados)

    # Métricas de agenda por día
    filas_dia = []
    if not agenda.empty:
        for fecha, g in agenda.groupby("fecha"):
            primer_ini = g["inicio_abs"].min()
            ultimo_fin = g["fin_abs"].max()
            _, hora_primer = fecha_hora_desde_abs(primer_ini, fecha_base)
            _, hora_ultimo = fecha_hora_desde_abs(ultimo_fin, fecha_base)
            filas_dia.append({
                "fecha": fecha,
                "primer_inicio_dia": hora_primer,
                "ultimo_fin_dia": hora_ultimo,
                "numero_pacientes_agendados": g["paciente"].nunique(),
                "numero_citas_agendadas": len(g),
                "citas_internas": int((g["tipo"] == "interno").sum()),
                "citas_externas": int((g["tipo"] == "externo").sum()),
            })
    metricas_agenda_dia = pd.DataFrame(filas_dia)

    # Métricas de recursos
    filas_recursos = []
    if not ventanas_recursos.empty:
        disp_recurso = ventanas_recursos.copy()
        disp_recurso["disponible_min"] = disp_recurso["fin_abs"] - disp_recurso["inicio_abs"]
        disponible = disp_recurso.groupby("recurso")["disponible_min"].sum().to_dict()
        internos = agenda[agenda["tipo"] == "interno"] if not agenda.empty else pd.DataFrame()
        ocupado = internos.groupby("recurso")["duracion_min"].sum().to_dict() if not internos.empty else {}
        for recurso in sorted(set(disponible) | set(ocupado)):
            disp = float(disponible.get(recurso, 0))
            ocu = float(ocupado.get(recurso, 0))
            filas_recursos.append({
                "recurso": recurso,
                "minutos_disponibles": round(disp, 2),
                "minutos_ocupados": round(ocu, 2),
                "minutos_ociosos": round(max(0, disp - ocu), 2),
                "utilizacion_%": None if disp <= 0 else round(100 * ocu / disp, 2),
            })
    metricas_recursos = pd.DataFrame(filas_recursos)

    # Resumen general
    if metricas_paciente.empty:
        resumen = pd.DataFrame([{
            "metodo": f"MILP-{NOMBRE_SOLVER}",
            "estado_solucion": resultado_solve.get("estado"),
            "tiempo_ejecucion_seg": round(resultado_solve.get("tiempo_ejecucion_seg", 0), 2),
            "valor_objetivo": resultado_solve.get("valor_objetivo"),
        }])
    else:
        resumen = pd.DataFrame([{
            "metodo": f"MILP-{NOMBRE_SOLVER}",
            "estado_solucion": resultado_solve.get("estado"),
            "tiempo_ejecucion_seg": round(resultado_solve.get("tiempo_ejecucion_seg", 0), 2),
            "valor_objetivo": resultado_solve.get("valor_objetivo"),
            "valor_tiempo_sistema_modelo": resultado_solve.get("valor_tiempo_sistema_modelo"),
            "valor_visitas_modelo": resultado_solve.get("valor_visitas"),
            "tiempo_total_sistema_min": metricas_paciente["tiempo_sistema_min"].sum(),
            "tiempo_promedio_sistema_min": metricas_paciente["tiempo_sistema_min"].mean(),
            "tiempo_max_sistema_min": metricas_paciente["tiempo_sistema_min"].max(),
            "tiempo_min_sistema_min": metricas_paciente["tiempo_sistema_min"].min(),
            "desv_tiempo_sistema_min": metricas_paciente["tiempo_sistema_min"].std(ddof=0),
            "tiempo_total_teorico_atencion_min": metricas_paciente["tiempo_teorico_atencion_min"].sum(),
            "tiempo_promedio_teorico_atencion_min": metricas_paciente["tiempo_teorico_atencion_min"].mean(),
            "tiempo_total_presencial_bloques_min": metricas_paciente["tiempo_presencial_por_bloques_min"].sum(),
            "tiempo_promedio_presencial_bloques_min": metricas_paciente["tiempo_presencial_por_bloques_min"].mean(),
            "total_visitas": metricas_paciente["numero_visitas"].sum(),
            "numero_promedio_visitas": metricas_paciente["numero_visitas"].mean(),
            "numero_max_visitas": metricas_paciente["numero_visitas"].max(),
            "porcentaje_pacientes_1_visita": round(100 * (metricas_paciente["numero_visitas"] == 1).mean(), 2),
            "porcentaje_pacientes_2_o_mas_visitas": round(100 * (metricas_paciente["numero_visitas"] >= 2).mean(), 2),
            "espera_total_entre_citas_min": metricas_paciente["espera_total_entre_citas_min"].sum(),
            "espera_promedio_entre_citas_min": metricas_paciente["espera_total_entre_citas_min"].mean(),
        }])

    return {
        "metricas_paciente": metricas_paciente,
        "metricas_resultados": metricas_resultados,
        "metricas_agenda_dia": metricas_agenda_dia,
        "metricas_recursos": metricas_recursos,
        "resumen_metricas": resumen,
    }

# EXPORTACIÓN DE RESULTADOS

def exportar_resultados(nombre_archivo, tablas):
    """Exporta las tablas principales a Excel."""
    with pd.ExcelWriter(nombre_archivo, engine="openpyxl") as writer:
        for nombre, df in tablas.items():
            if df is not None and isinstance(df, pd.DataFrame):
                df.to_excel(writer, sheet_name=nombre[:31], index=False)
    print(f"\nResultados exportados a: {nombre_archivo}")

# EJECUCIÓN

def ejecutar_programacion(
    archivo_escenarios=ARCHIVO_ESCENARIOS,
    hoja_escenario=HOJA_ESCENARIO,
    permitir_no_programar=True,
    exportar=True,
):
    print("Leyendo escenario desde Excel...")
    tablas = leer_escenario_excel(archivo_escenarios, hoja_escenario)
    datos = preparar_datos(tablas)

    for adv in datos["advertencias"]:
        print("ADVERTENCIA:", adv)

    examenes_paciente = datos["examenes_paciente"]
    disp_pacientes = datos["disp_pacientes"]
    disp_recursos = datos["disp_recursos"]
    bloques_ocupados = datos["bloques_ocupados"]
    examenes_externos = datos["examenes_externos"]
    festivos = datos["festivos"]

    # Fecha base automática: fecha mínima encontrada en el escenario.
    fechas = []
    fechas.extend(disp_pacientes["fecha"].tolist())
    fechas.extend(disp_recursos["fecha"].tolist())
    if not bloques_ocupados.empty:
        fechas.extend(bloques_ocupados["fecha"].tolist())
    if not examenes_externos.empty:
        fechas.extend(examenes_externos["fecha"].tolist())
        if "resultado_fecha" in examenes_externos.columns:
            fechas.extend([f for f in examenes_externos["resultado_fecha"].tolist() if f is not None and not pd.isna(f)])
    if festivos:
        # Los festivos no determinan horizonte por sí mismos; se usan solo si existen otras fechas.
        pass

    if not fechas:
        raise ValueError("No encontré fechas válidas en el escenario.")

    fecha_base = min(fechas)
    print(f"Fecha base automática del escenario: {fecha_base}")

    print("Construyendo ventanas libres de recursos internos...")
    ventanas_recursos = construir_ventanas_libres_recursos(
        disp_recursos=disp_recursos,
        bloques_ocupados=bloques_ocupados,
        fecha_base=fecha_base,
        festivos=festivos,
    )

    if ventanas_recursos.empty:
        raise ValueError(
            "No hay ventanas libres de recursos internos después de aplicar horario de centro médico, almuerzo, "
            "días no hábiles, festivos y bloques ocupados. Revisa [DISPONIBILIDAD_RECURSOS]."
        )

    print("Preparando exámenes externos fijos...")
    externos_preparados = preparar_examenes_externos(examenes_externos, fecha_base, festivos)

    print("Generando operaciones internas y candidatos factibles...")
    operaciones, candidatos, operaciones_sin_candidatos = construir_operaciones_y_candidatos(
        examenes_paciente=examenes_paciente,
        disp_pacientes=disp_pacientes,
        ventanas_recursos=ventanas_recursos,
        fecha_base=fecha_base,
        festivos=festivos,
    )

    print(f"Pacientes: {examenes_paciente['paciente'].nunique()}")
    print(f"Operaciones internas requeridas: {len(operaciones)}")
    print(f"Candidatos internos factibles generados: {len(candidatos)}")
    print(f"Exámenes externos fijos: {len(externos_preparados)}")

    if operaciones_sin_candidatos and not permitir_no_programar:
        msg = "No hay ventanas factibles para las siguientes operaciones internas:\n"
        for paciente, examen in operaciones_sin_candidatos:
            msg += f"- Paciente {paciente}, examen {examen}\n"
        msg += (
            "\nPosibles causas: falta disponibilidad del paciente, falta disponibilidad del recurso, "
            "bloques ocupados, días no hábiles, horario de almuerzo/cierre o regla de laboratorios 7:00-10:00."
        )
        if ACTIVAR_DIAGNOSTICO_INFACTIBILIDAD:
            print(msg)
            print("Activando modo diagnóstico con operaciones no programadas penalizadas...")
            return ejecutar_programacion(
                archivo_escenarios=archivo_escenarios,
                hoja_escenario=hoja_escenario,
                permitir_no_programar=True,
                exportar=exportar,
            )
        raise ValueError(msg)

    print("Construyendo modelo MILP...")
    objetos = construir_modelo_milp(
        examenes_paciente=examenes_paciente,
        operaciones=operaciones,
        candidatos=candidatos,
        externos_preparados=externos_preparados,
        fecha_base=fecha_base,
        permitir_no_programar=permitir_no_programar,
    )

    print(f"Resolviendo con {NOMBRE_SOLVER}.")
    resultado_solve = resolver_modelo(objetos, msg=True)
    estado = resultado_solve["estado"]
    print(f"Estado del modelo: {estado}")
    print(f"Tiempo de ejecución: {resultado_solve['tiempo_ejecucion_seg']:.2f} segundos")
    print(f"Valor objetivo: {resultado_solve.get('valor_objetivo')}")
    imprimir_diagnostico_solucion(resultado_solve)

    if not resultado_solve.get("hay_solucion_utilizable", False):
        print("\nNo se encontró una solución utilizable para construir agenda.")
        if ACTIVAR_DIAGNOSTICO_INFACTIBILIDAD and not permitir_no_programar:
            print("Activando modo diagnóstico con operaciones no programadas penalizadas...")
            return ejecutar_programacion(
                archivo_escenarios=archivo_escenarios,
                hoja_escenario=hoja_escenario,
                permitir_no_programar=True,
                exportar=exportar,
            )
        return {
            "estado": estado,
            "resultado_solve": resultado_solve,
            "objetos_modelo": objetos,
            "fecha_base": fecha_base,
            "ventanas_recursos": ventanas_recursos,
        }

    print("Construyendo salidas y métricas...")
    agenda = construir_agenda(objetos, fecha_base)

    if agenda.empty:
        print("No se construyó agenda. Revisa el estado de solución y los datos de entrada.")
        return None

    agenda_paciente = agenda[[
        "tipo", "paciente", "fecha", "bloque", "especialidad", "recurso",
        "hora_inicio", "hora_fin", "duracion_min",
        "resultado_disponible_fecha", "resultado_disponible_hora",
        "salud_habilitada_fecha", "salud_habilitada_hora",
    ]].sort_values(["paciente", "fecha", "hora_inicio"]).reset_index(drop=True)

    agenda_recurso = agenda[agenda["tipo"] == "interno"][[
        "recurso", "fecha", "bloque", "hora_inicio", "hora_fin", "paciente", "especialidad"
    ]].sort_values(["recurso", "fecha", "hora_inicio"]).reset_index(drop=True)

    agenda_externos = agenda[agenda["tipo"] == "externo"][[
        "paciente", "fecha", "bloque", "especialidad", "hora_inicio", "hora_fin",
        "resultado_disponible_fecha", "resultado_disponible_hora"
    ]].sort_values(["paciente", "fecha", "hora_inicio"]).reset_index(drop=True)

    metricas = calcular_metricas(agenda, objetos, resultado_solve, fecha_base, ventanas_recursos)
    diagnostico_no_programados = construir_diagnostico_no_programados(objetos) if permitir_no_programar else pd.DataFrame()
    diagnostico_estado = pd.DataFrame([resultado_solve])

    mostrar_tabla(diagnostico_estado, "Diagnóstico del estado de la solución")
    mostrar_tabla(agenda_paciente, "Agenda consolidada por paciente")
    mostrar_tabla(agenda_recurso, "Agenda por recurso interno")
    mostrar_tabla(agenda_externos, "Agenda de exámenes externos")
    mostrar_tabla(metricas["metricas_paciente"], "Métricas por paciente")
    mostrar_tabla(metricas["metricas_resultados"], "Métricas de resultados diferidos")
    mostrar_tabla(metricas["metricas_agenda_dia"], "Métricas de agenda por día")
    mostrar_tabla(metricas["metricas_recursos"], "Métricas de recursos")
    mostrar_tabla(metricas["resumen_metricas"], "Resumen de métricas")

    if permitir_no_programar:
        mostrar_tabla(diagnostico_no_programados, "Diagnóstico: operaciones no programadas")

    tablas_salida = {
        "agenda_paciente": agenda_paciente,
        "agenda_recurso": agenda_recurso,
        "agenda_externos": agenda_externos,
        "metricas_paciente": metricas["metricas_paciente"],
        "metricas_resultados": metricas["metricas_resultados"],
        "metricas_agenda_dia": metricas["metricas_agenda_dia"],
        "metricas_recursos": metricas["metricas_recursos"],
        "resumen_metricas": metricas["resumen_metricas"],
        "diagnostico_estado": diagnostico_estado,
        "diagnostico_no_programados": diagnostico_no_programados,
    }

    if exportar:
        nombre_salida = f"resultados_{normalizar_texto(hoja_escenario)}.xlsx"
        exportar_resultados(nombre_salida, tablas_salida)

    return {
        "estado": estado,
        "fecha_base": fecha_base,
        "objetos_modelo": objetos,
        "resultado_solve": resultado_solve,
        "agenda": agenda,
        "agenda_paciente": agenda_paciente,
        "agenda_recurso": agenda_recurso,
        "agenda_externos": agenda_externos,
        "metricas": metricas,
        "diagnostico_estado": diagnostico_estado,
        "diagnostico_no_programados": diagnostico_no_programados,
        "ventanas_recursos": ventanas_recursos,
    }

resultado = ejecutar_programacion(
    archivo_escenarios=ARCHIVO_ESCENARIOS,
    hoja_escenario=HOJA_ESCENARIO,
    permitir_no_programar=True,
    exportar=True,
)