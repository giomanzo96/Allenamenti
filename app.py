import sqlite3
from datetime import date, timedelta
from html import escape
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


DB_PATH = Path("allenamenti.db")
TABLE_NAME = "allenamenti"
MIN_FILTER_DATE = date(2026, 3, 23)

ACTIVITY_COLS = [
    "palestra",
    "corsa",
    "sci",
    "camminata",
    "kayak",
    "calcio",
    "arrampicata",
]
OTHER_COLS = ["sci", "camminata", "kayak", "calcio", "arrampicata"]
PIE_ORDER = ["sci", "camminata", "kayak", "calcio", "arrampicata", "palestra", "corsa"]

LABELS = {
    "palestra": "Palestra",
    "corsa": "Corsa",
    "sci": "Sci",
    "camminata": "Camminata",
    "kayak": "Kayak",
    "calcio": "Calcio",
    "arrampicata": "Arrampicata",
}

COLORS = {
    "palestra": "#F4C430",
    "corsa": "#14B8D4",
    "altro": "#F05D7B",
    "sci": "#5B7CFA",
    "camminata": "#FF8A5B",
    "kayak": "#00A896",
    "calcio": "#7BC950",
    "arrampicata": "#8F98A8",
}

BAR_COLORS = {
    "Palestra": "#F4C430",
    "Corsa": "#14B8D4",
    "Altro": "#BA566A",
}

CHART_FONT = "Inter, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def iso_week_number(day: date) -> int:
    return int(day.isocalendar().week)


def monday_of_week(day: date) -> date:
    return day - timedelta(days=day.weekday())


def init_db() -> None:
    """Inizializza il database creando la tabella se non esiste già."""
    with get_conn() as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                settimana_n INTEGER,
                data_da DATE,
                data_a DATE,
                palestra INTEGER DEFAULT 0,
                corsa INTEGER DEFAULT 0,
                sci INTEGER DEFAULT 0,
                camminata INTEGER DEFAULT 0,
                kayak INTEGER DEFAULT 0,
                calcio INTEGER DEFAULT 0,
                arrampicata INTEGER DEFAULT 0,
                note TEXT,
                UNIQUE(data_da, data_a)
            )
            """
        )


def load_all_data() -> pd.DataFrame:
    """Carica tutti i dati dal database e restituisce un DataFrame con i tipi corretti."""
    columns = [
        "id",
        "settimana_n",
        "data_da",
        "data_a",
        "palestra",
        "corsa",
        "sci",
        "camminata",
        "kayak",
        "calcio",
        "arrampicata",
        "note",
    ]
    with get_conn() as conn:
        df = pd.read_sql_query(
            f"""
            SELECT {", ".join(columns)}
            FROM {TABLE_NAME}
            ORDER BY date(data_da)
            """,
            conn,
        )

    if df.empty:
        return pd.DataFrame(columns=columns)

    df["data_da"] = pd.to_datetime(df["data_da"], errors="coerce")
    df["data_a"] = pd.to_datetime(df["data_a"], errors="coerce")
    df = df.dropna(subset=["data_da", "data_a"]).copy()

    for col in ACTIVITY_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    df["settimana_n"] = pd.to_numeric(df["settimana_n"], errors="coerce").fillna(0).astype(int)
    df["note"] = df["note"].fillna("")
    return df


def save_week(
    selected_id: int | None,
    settimana_n: int,
    data_da: date,
    data_a: date,
    sport_values: dict[str, int],
    note: str,
) -> None:
    """Salva una settimana nel database, aggiornando se esiste già una settimana con le stesse date."""
    
    data_da_iso = data_da.isoformat()
    data_a_iso = data_a.isoformat()
    # Controlla se esiste già una settimana con le stesse date (esclusi i record con id diverso da selected_id)
    with get_conn() as conn:
        existing = conn.execute(
            f"SELECT id FROM {TABLE_NAME} WHERE data_da = ? AND data_a = ?",
            (data_da_iso, data_a_iso),
        ).fetchone()
        target_id = existing["id"] if existing else selected_id

        values = (
            int(settimana_n),
            data_da_iso,
            data_a_iso,
            int(sport_values["palestra"]),
            int(sport_values["corsa"]),
            int(sport_values["sci"]),
            int(sport_values["camminata"]),
            int(sport_values["kayak"]),
            int(sport_values["calcio"]),
            int(sport_values["arrampicata"]),
            note.strip(),
        )

        if target_id:
            conn.execute(
                f"""
                UPDATE {TABLE_NAME}
                SET settimana_n = ?,
                    data_da = ?,
                    data_a = ?,
                    palestra = ?,
                    corsa = ?,
                    sci = ?,
                    camminata = ?,
                    kayak = ?,
                    calcio = ?,
                    arrampicata = ?,
                    note = ?
                WHERE id = ?
                """,
                (*values, int(target_id)),
            )
        else:
            conn.execute(
                f"""
                INSERT INTO {TABLE_NAME}
                (settimana_n, data_da, data_a, palestra, corsa, sci, camminata, kayak, calcio, arrampicata, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )


def delete_week(row_id: int) -> None:
    """Elimina una settimana dal database in base all'id."""
    with get_conn() as conn:
        conn.execute(f"DELETE FROM {TABLE_NAME} WHERE id = ?", (int(row_id),))


def filter_by_period(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Filtra il DataFrame per includere solo le settimane che rientrano nel periodo specificato."""
    if df.empty or end < start:
        return df.iloc[0:0].copy()

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    return df[(df["data_da"] >= start_ts) & (df["data_a"] <= end_ts)].copy()


def year_slice(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Restituisce le settimane dall'inizio dell'anno selezionato
    fino all'ultima settimana registrata alla data odierna."""
    
    if df.empty:
        return df.copy()

    year_start = pd.Timestamp(date(year, 1, 1))
    year_end = pd.Timestamp(date(year, 12, 31))
    
    upper_bound = min(pd.Timestamp(date.today()), year_end)

    return df[
        (df["data_da"] >= year_start)
        & (df["data_da"] <= upper_bound)
    ].copy()


def calculate_weekly_averages(year_df: pd.DataFrame, period_df: pd.DataFrame) -> pd.DataFrame:
    """Calcola le medie settimanali per palestra, corsa e altre attività sia per l'anno che per il periodo selezionato."""
    def avg_col(frame: pd.DataFrame, col: str) -> float:
        if frame.empty:
            return 0.0
        return round(float(frame[col].mean()), 2)

    def avg_other(frame: pd.DataFrame) -> float:
        if frame.empty:
            return 0.0
        return round(float(frame[OTHER_COLS].sum(axis=1).mean()), 2)

    return pd.DataFrame(
        [
            {"Categoria": "Palestra", "Anno": avg_col(year_df, "palestra"), "Periodo": avg_col(period_df, "palestra")},
            {"Categoria": "Corsa", "Anno": avg_col(year_df, "corsa"), "Periodo": avg_col(period_df, "corsa")},
            {"Categoria": "Altro", "Anno": avg_other(year_df), "Periodo": avg_other(period_df)},
        ]
    )


def calculate_totals(year_df: pd.DataFrame, period_df: pd.DataFrame) -> pd.DataFrame:
    """Calcola i totali per palestra, corsa e altre attività sia per l'anno che per il periodo selezionato."""
    rows = []
    for col in PIE_ORDER:
        rows.append(
            {
                "Sport": LABELS[col],
                "Anno": int(year_df[col].sum()) if not year_df.empty else 0,
                "Periodo": int(period_df[col].sum()) if not period_df.empty else 0,
                "_col": col,
            }
        )
    return pd.DataFrame(rows)


def default_period(df: pd.DataFrame) -> tuple[date, date]:
    """Determina il periodo di default da mostrare nei filtri: ultimi 3 mesi disponibili."""
    if df.empty:
        end = date.today()
        start = (pd.Timestamp(end) - pd.DateOffset(months=3)).date()
        return max(start, MIN_FILTER_DATE), max(end, MIN_FILTER_DATE)

    min_start = max(df["data_da"].min().date(), MIN_FILTER_DATE)
    max_end = df["data_a"].max().date()
    today = date.today()

    if today < min_start:
        end = min_start
    elif today > max_end:
        end = max_end
    else:
        end = today

    start = (pd.Timestamp(end) - pd.DateOffset(months=3)).date()
    return max(start, min_start), end



def format_date(day: pd.Timestamp | date) -> str:
    """Formatta una data come stringa nel formato DD/MM/YYYY. Accetta sia oggetti pd.Timestamp che date."""
    if isinstance(day, pd.Timestamp):
        day = day.date()
    return day.strftime("%d/%m/%Y")


def form_year(df: pd.DataFrame) -> int:
    """Determina l'anno da mostrare di default nel form: l'anno corrente."""
    return date.today().year


def annual_week_options(year: int) -> tuple[list[str], dict[str, tuple[int, date, date]]]:
    """Genera le opzioni per il selettore delle settimane annuali, restituendo sia le etichette che una mappa con i dettagli di ogni settimana."""
    first_monday = monday_of_week(date(year, 1, 1))
    last_day = date(year, 12, 31)
    options: list[str] = []
    week_map: dict[str, tuple[int, date, date]] = {}

    current = first_monday
    while current <= last_day:
        week_end = current + timedelta(days=6)
        label = f"{current.strftime('%d-%m-%Y')} / {week_end.strftime('%d-%m-%Y')}"
        options.append(label)
        week_map[label] = (iso_week_number(current), current, week_end)
        current += timedelta(days=7)

    return options, week_map


def week_defaults(df: pd.DataFrame, data_da: date, data_a: date) -> tuple[int | None, dict[str, int], str]:
    """Determina i valori di default per il form della settimana selezionata, basandosi sui dati esistenti per quella settimana. 
    Restituisce una tupla con l'id del record (o None se non esiste), un dizionario con i valori delle attività e la nota associata."""
    if not df.empty:
        row_match = df[
            (df["data_da"].dt.date == data_da)
            & (df["data_a"].dt.date == data_a)
        ]
        if not row_match.empty:
            row = row_match.iloc[0]
            values = {col: int(row[col]) for col in ACTIVITY_COLS}
            return int(row["id"]), values, str(row["note"])

    return None, {col: 0 for col in ACTIVITY_COLS}, ""


def default_week_index(options: list[str], week_map: dict[str, tuple[int, date, date]], df: pd.DataFrame) -> int:
    """Determina l'indice di default da selezionare nel menu delle settimane: la settimana corrente."""
    target_start = monday_of_week(date.today())

    for index, option in enumerate(options):
        _, start, _ = week_map[option]
        if start == target_start:
            return index

    if df.empty:
        return 0

    fallback_start = df["data_da"].max().date()
    for index, option in enumerate(options):
        _, start, _ = week_map[option]
        if start == fallback_start:
            return index

    return 0


def flash(message: str, level: str = "success") -> None:
    """Mostra un messaggio flash all'utente. Il messaggio viene memorizzato nello stato della sessione e mostrato alla successiva chiamata di show_flash()."""
    st.session_state["flash_message"] = (level, message)


def show_flash() -> None:
    """Controlla se c'è un messaggio flash da mostrare e lo visualizza. Dopo la visualizzazione, il messaggio viene rimosso dallo stato della sessione."""
    payload = st.session_state.pop("flash_message", None)
    if not payload:
        return
    level, message = payload
    if level == "error":
        st.error(message)
    elif level == "warning":
        st.warning(message)
    else:
        st.success(message)


def rerun() -> None:
    """Forza un rerun dell'applicazione Streamlit. Utilizza st.rerun() se disponibile, altrimenti st.experimental_rerun()."""
    if hasattr(st, "rerun"):
        st.rerun()
    st.experimental_rerun()


def inject_css() -> None:
    """Inietta il CSS personalizzato per lo styling dell'applicazione. Il CSS definisce i colori, i font, le spaziature e altri aspetti visivi per creare un'interfaccia coerente e piacevole."""
    st.markdown(
        """
        <style>
            :root {
                --app-accent: #0798a7;
                --app-accent-dark: #057987;
                --app-accent-soft: #dff7f8;
                --app-ink: #14213d;
                --app-text: #23324a;
                --app-muted: #6a7588;
                --app-line: #dce4ee;
                --app-line-strong: #afbdca;
                --app-surface: #ffffff;
                --app-bg: #f5f8fb;
            }

            html,
            body,
            .stApp {
                background:
                    linear-gradient(180deg, #eef8fb 0%, var(--app-bg) 19rem, #ffffff 100%);
                color: var(--app-text);
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Arial, sans-serif;
            }

            header[data-testid="stHeader"] {
                background: rgba(245, 248, 251, 0.88);
                box-shadow: none;
            }

            .block-container {
                max-width: 760px;
                padding: 1.1rem 1rem 3rem;
            }

            h1.app-title {
                margin: 0.45rem 0 1.2rem;
                text-align: center;
                font-size: 2.35rem;
                font-weight: 760;
                line-height: 1.1;
                letter-spacing: 0;
                color: var(--app-ink);
            }

            .section-title {
                margin: 2rem 0 0.9rem;
                text-align: center;
                font-size: 1.05rem;
                font-weight: 780;
                text-decoration: none;
                letter-spacing: 0;
                color: var(--app-ink);
            }

            .tracker-title {
                margin: 1.75rem 0 0.8rem;
                font-size: 1.28rem;
                font-weight: 760;
                letter-spacing: 0;
                color: var(--app-ink);
            }

            .period-heading {
                display: flex;
                align-items: center;
                gap: 0.7rem;
                margin: 1.25rem 0 0.35rem;
                color: var(--app-ink);
                font-size: 0.92rem;
                font-weight: 800;
            }

            .period-heading::before,
            .period-heading::after {
                content: "";
                height: 1px;
                flex: 1;
                background: linear-gradient(90deg, transparent, var(--app-line-strong));
            }

            .period-heading::after {
                background: linear-gradient(90deg, var(--app-line-strong), transparent);
            }

            .period-heading span {
                display: inline-flex;
                align-items: center;
                min-height: 2rem;
                padding: 0 1rem;
                border: 1px solid #c9d7e5;
                border-radius: 999px;
                background: rgba(255, 255, 255, 0.88);
                color: var(--app-accent-dark);
                box-shadow: 0 0.5rem 1rem rgba(20, 33, 61, 0.06);
            }

            button[data-testid="stBaseButton-primary"] {
                min-height: 3.15rem;
                border: 0;
                border-radius: 14px;
                background: linear-gradient(135deg, var(--app-accent), #24b8ca);
                color: #ffffff;
                font-size: 1rem;
                font-weight: 780;
                letter-spacing: 0;
                box-shadow: 0 0.65rem 1.4rem rgba(7, 152, 167, 0.28);
            }

            button[data-testid="stBaseButton-primary"]:hover,
            button[data-testid="stBaseButton-primary"]:focus {
                border: 0;
                background: linear-gradient(135deg, var(--app-accent-dark), #1098ab);
                color: #ffffff;
                box-shadow: 0 0.7rem 1.45rem rgba(7, 152, 167, 0.34);
            }

            div[data-testid="stForm"] {
                margin-top: 0.9rem;
                border: 1px solid var(--app-line);
                border-radius: 16px;
                padding: 1rem;
                background: rgba(255, 255, 255, 0.92);
                box-shadow: 0 0.8rem 2rem rgba(20, 33, 61, 0.07);
            }

            div[data-testid="stDateInput"] label,
            div[data-testid="stNumberInput"] label,
            div[data-testid="stTextArea"] label,
            div[data-testid="stSelectbox"] label {
                font-size: 0.86rem;
                font-weight: 720;
                color: var(--app-ink);
            }

            div[data-testid="stDataFrame"] {
                overflow: hidden;
                border: 1px solid var(--app-line);
                border-radius: 14px;
                box-shadow: 0 0.65rem 1.6rem rgba(20, 33, 61, 0.06);
            }

            div[data-baseweb="input"],
            div[data-baseweb="select"] > div,
            textarea {
                border-color: #cfd9e6;
                border-radius: 12px;
                background-color: #ffffff;
            }

            div[data-baseweb="input"]:focus-within,
            div[data-baseweb="select"] > div:focus-within,
            textarea:focus {
                border-color: var(--app-accent);
                box-shadow: 0 0 0 3px rgba(7, 152, 167, 0.12);
            }

            .mini-table-wrap {
                width: min(100%, 640px);
                margin: 0 auto 1rem;
                overflow: hidden;
                border: 1px solid var(--app-line);
                border-radius: 16px;
                background: var(--app-surface);
                box-shadow: 0 0.75rem 1.8rem rgba(20, 33, 61, 0.06);
            }

            table.mini-table {
                width: 100%;
                border-collapse: collapse;
                table-layout: fixed;
                font-size: 0.94rem;
            }

            table.mini-table th,
            table.mini-table td {
                padding: 0.48rem 0.62rem;
                border-bottom: 1px solid var(--app-line);
                text-align: right;
                line-height: 1.18;
            }

            table.mini-table th:first-child,
            table.mini-table td:first-child {
                text-align: left;
                font-weight: 740;
                text-decoration: none;
            }

            table.mini-table th {
                background: #f0f6fa;
                color: var(--app-muted);
                font-size: 0.78rem;
                font-weight: 780;
                text-decoration: none;
                text-transform: uppercase;
            }

            table.mini-table tr.gap-row td {
                height: 0.72rem;
                padding: 0;
                border-bottom: none;
                text-decoration: none;
                background: #ffffff;
            }

            table.mini-table tbody tr:last-child td {
                border-bottom: none;
            }

            .stPlotlyChart {
                box-sizing: border-box;
                max-width: 100%;
                overflow: hidden;
                margin-top: 0.45rem;
                border: 1px solid var(--app-line);
                border-radius: 16px;
                padding: 0.45rem;
                background: #ffffff;
                box-shadow: 0 0.75rem 1.8rem rgba(20, 33, 61, 0.06);
            }

            .stPlotlyChart > div {
                max-width: 100%;
                overflow: hidden;
            }

            div[data-testid="stAlert"] {
                border-radius: 14px;
            }

            hr {
                border-color: var(--app-line);
            }

            @media (max-width: 480px) {
                .block-container {
                    padding: 0.9rem 0.72rem 2.5rem;
                }

                h1.app-title {
                    font-size: 2.12rem;
                    margin-bottom: 1.1rem;
                }

                table.mini-table {
                    font-size: 0.88rem;
                }

                table.mini-table th,
                table.mini-table td {
                    padding: 0.42rem 0.5rem;
                }

                .stPlotlyChart {
                    padding: 0.25rem;
                }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_html_table(df: pd.DataFrame, spacer_after: str | None = None, decimals: bool = False) -> None:
    """Renderizza un DataFrame come una tabella HTML personalizzata, con opzioni per inserire uno spazio dopo una riga specifica e per formattare i numeri con o senza decimali."""
    headers = list(df.columns)
    html = ['<div class="mini-table-wrap"><table class="mini-table"><thead><tr>']
    for header in headers:
        html.append(f"<th>{escape(str(header))}</th>")
    html.append("</tr></thead><tbody>")

    for _, row in df.iterrows():
        first_value = str(row[headers[0]])
        html.append("<tr>")
        for header in headers:
            value = row[header]
            if header in ("Anno", "Periodo"):
                value = f"{float(value):.2f}" if decimals else f"{int(value)}"
            html.append(f"<td>{escape(str(value))}</td>")
        html.append("</tr>")
        if spacer_after and first_value == spacer_after:
            html.append(f'<tr class="gap-row"><td colspan="{len(headers)}"></td></tr>')

    html.append("</tbody></table></div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def build_bar_chart(period_df: pd.DataFrame):
    """Costruisce un grafico a barre impilate per visualizzare le attività settimanali nel periodo selezionato, con personalizzazione dei colori, del layout e dei tooltip."""
    chart_df = period_df.sort_values("data_da").copy()
    chart_df["Altro"] = chart_df[OTHER_COLS].sum(axis=1)
    chart_df["Settimana"] = chart_df.apply(
        lambda row: f"S{int(row['settimana_n'])}<br>{row['data_da'].strftime('%d/%m')}",
        axis=1,
    )
    chart_df["Settimana hover"] = chart_df.apply(
        lambda row: f"S{int(row['settimana_n'])} - {row['data_da'].strftime('%d/%m/%Y')}",
        axis=1,
    )

    fig = go.Figure()
    for label, column in [("Palestra", "palestra"), ("Corsa", "corsa"), ("Altro", "Altro")]:
        fig.add_trace(
            go.Bar(
                name=label,
                x=chart_df["Settimana"],
                y=chart_df[column],
                customdata=chart_df["Settimana hover"],
                marker={
                    "color": BAR_COLORS[label],
                    "line": {"width": 0},
                },
                hovertemplate="<b>%{customdata}</b><br>%{fullData.name}: %{y}<extra></extra>",
            )
        )

    fig.update_layout(
        barmode="stack",
        height=330,
        margin={"l": 24, "r": 10, "t": 40, "b": 62},
        bargap=0.28,
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
        font={"family": CHART_FONT, "color": "#536172", "size": 11},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.03,
            "xanchor": "left",
            "x": 0,
            "font": {"size": 11, "color": "#536172"},
        },
        hovermode="x unified",
        hoverlabel={
            "bgcolor": "#ffffff",
            "bordercolor": "#dce4ee",
            "font": {"family": CHART_FONT, "color": "#14213d", "size": 12},
        },
    )
    fig.update_xaxes(
        title=None,
        tickangle=0,
        tickfont={"size": 10, "color": "#536172"},
        automargin=True,
        fixedrange=True,
        showline=True,
        linewidth=1,
        linecolor="#dce4ee",
        showgrid=False,
    )
    fig.update_yaxes(
        title=None,
        tickfont={"size": 10, "color": "#536172"},
        automargin=True,
        fixedrange=True,
        rangemode="tozero",
        dtick=1,
        gridcolor="#e7edf3",
        zeroline=False,
    )
    return fig


def build_pie_chart(totals_df: pd.DataFrame, value_col: str, title: str):
    """Costruisce un grafico a torta per visualizzare la distribuzione delle attività per una colonna specifica (Anno o Periodo), con personalizzazione dei colori, del layout e dei tooltip."""
    chart_df = totals_df[["Sport", value_col, "_col"]].copy()
    chart_df = chart_df[chart_df[value_col] > 0]
    if chart_df.empty:
        return None

    chart_df["Ordine"] = chart_df["_col"].apply(lambda col: PIE_ORDER.index(col))
    chart_df = chart_df.sort_values("Ordine")
    chart_df["Percentuale"] = chart_df[value_col] / chart_df[value_col].sum()
    chart_df["Text"] = chart_df["Percentuale"].apply(lambda value: f"{value:.0%}" if value > 0.10 else "")

    fig = go.Figure(
        go.Pie(
            labels=chart_df["Sport"],
            values=chart_df[value_col],
            sort=False,
            direction="clockwise",
            hole=0.46,
            marker={
                "colors": [COLORS[col] for col in chart_df["_col"]],
                "line": {"color": "#ffffff", "width": 2},
            },
            text=chart_df["Text"],
            textinfo="text",
            textposition="inside",
            insidetextfont={"family": CHART_FONT, "size": 12, "color": "#14213d"},
            hovertemplate="<b>%{label}</b><br>Occorrenze: %{value}<br>Quota: %{percent}<extra></extra>",
        )
    )
    fig.update_layout(
        title={"text": title, "x": 0.5, "xanchor": "center", "font": {"size": 13, "color": "#14213d"}},
        height=350,
        margin={"l": 4, "r": 4, "t": 46, "b": 82},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"family": CHART_FONT, "color": "#536172", "size": 11},
        legend={
            "orientation": "h",
            "yanchor": "top",
            "y": -0.06,
            "xanchor": "center",
            "x": 0.5,
            "font": {"size": 10, "color": "#536172"},
        },
        hoverlabel={
            "bgcolor": "#ffffff",
            "bordercolor": "#dce4ee",
            "font": {"family": CHART_FONT, "color": "#14213d", "size": 12},
        },
    )
    return fig


def render_editor(df: pd.DataFrame) -> None:
    """Renderizza il form per aggiungere o modificare le settimane di allenamento, con selezione dell'anno, scelta della settimana, input per le attività e note, e pulsante per salvare la settimana selezionata."""
    year = form_year(df)
    options, week_map = annual_week_options(year)
    if st.session_state.get("selected_week") not in (None, *options):
        del st.session_state["selected_week"]

    selected_label = st.selectbox(
        "Settimana",
        options=options,
        index=default_week_index(options, week_map, df),
        key="selected_week",
    )
    settimana_n, data_da, data_a = week_map[selected_label]
    selected_id, defaults, note_default = week_defaults(df, data_da, data_a)
    scope = data_da.isoformat()

    with st.form("week_form", clear_on_submit=False):
        sport_values: dict[str, int] = {}
        left, right = st.columns(2)
        for index, col_name in enumerate(ACTIVITY_COLS):
            target = left if index % 2 == 0 else right
            with target:
                sport_values[col_name] = int(
                    st.number_input(
                        LABELS[col_name],
                        min_value=0,
                        max_value=99,
                        step=1,
                        value=int(defaults[col_name]),
                        key=f"{col_name}_{scope}",
                    )
                )

        note = st.text_area("Note", value=note_default, key=f"note_{scope}")
        save_col, delete_col = st.columns(2)
        with save_col:
            submitted = st.form_submit_button("Salva", type="primary", width="stretch")
        with delete_col:
            deleted = st.form_submit_button(
                "Elimina settimana selezionata",
                width="stretch",
                disabled=selected_id is None,
            )

    if submitted:
        save_week(selected_id, int(settimana_n), data_da, data_a, sport_values, note)
        flash("Settimana salvata.")
        rerun()

    if deleted and selected_id is not None:
        delete_week(selected_id)
        flash("Settimana eliminata.")
        rerun()


def render_tracker(period_df: pd.DataFrame) -> None:
    """Renderizza la tabella del tracker con tutte le settimane che rientrano nel periodo selezionato, mostrando le date, le attività e le note per ogni settimana, e gestendo il caso in cui non ci siano dati da mostrare."""
    st.markdown('<div class="tracker-title">Tracker</div>', unsafe_allow_html=True)
    if period_df.empty:
        st.info("Nessun dato nel periodo selezionato.")
        return

    tracker = period_df.sort_values("data_da").copy()
    tracker["Da"] = tracker["data_da"].dt.strftime("%d/%m/%Y")
    tracker["A"] = tracker["data_a"].dt.strftime("%d/%m/%Y")
    tracker = tracker.rename(
        columns={
            "settimana_n": "N",
            "palestra": "Palestra",
            "corsa": "Corsa",
            "sci": "Sci",
            "camminata": "Camminata",
            "kayak": "Kayak",
            "calcio": "Calcio",
            "arrampicata": "Arrampicata",
            "note": "Note",
        }
    )
    columns = ["N", "Da", "A", "Palestra", "Corsa", "Sci", "Camminata", "Kayak", "Calcio", "Arrampicata", "Note"]
    height = min(430, 38 * (len(tracker) + 1))
    st.dataframe(
        tracker[columns],
        hide_index=True,
        width="stretch",
        height=height,
        column_config={
            "N": st.column_config.NumberColumn("N", width="small"),
            "Da": st.column_config.TextColumn("Da", width="small"),
            "A": st.column_config.TextColumn("A", width="small"),
            "Note": st.column_config.TextColumn("Note", width="medium"),
        },
    )


def main() -> None:
    """Funzione principale dell'applicazione Streamlit, che gestisce l'inizializzazione del database, l'iniezione del CSS, la visualizzazione dei messaggi flash, il rendering del form di editor e dei grafici, e la visualizzazione del tracker con i dati filtrati per periodo."""
    st.set_page_config(page_title="⚡Allenamenti", page_icon=None, layout="wide")
    init_db()
    inject_css()

    st.markdown('<h1 class="app-title">⚡Tracker Allenamenti</h1>', unsafe_allow_html=True)
    show_flash()

    if "show_editor" not in st.session_state:
        st.session_state["show_editor"] = False

    if st.button("+ Aggiungi / Modifica allenamenti", type="primary", width="stretch"):
        st.session_state["show_editor"] = not st.session_state["show_editor"]

    all_df = load_all_data()
    if st.session_state["show_editor"]:
        render_editor(all_df)
        all_df = load_all_data()

    default_start, default_end = default_period(all_df)
    if st.session_state.get("period_start", default_start) < MIN_FILTER_DATE:
        st.session_state["period_start"] = MIN_FILTER_DATE
    if st.session_state.get("period_end", default_end) < MIN_FILTER_DATE:
        st.session_state["period_end"] = MIN_FILTER_DATE

    st.markdown('<div class="period-heading"><span>Filtra per periodo</span></div>', unsafe_allow_html=True)
    period_col_a, period_col_b = st.columns(2)
    with period_col_a:
        period_start = st.date_input(
            "Da",
            value=default_start,
            min_value=MIN_FILTER_DATE,
            format="DD/MM/YYYY",
            key="period_start",
        )
    with period_col_b:
        period_end = st.date_input(
            "A",
            value=default_end,
            min_value=MIN_FILTER_DATE,
            format="DD/MM/YYYY",
            key="period_end",
        )

    if period_end < period_start:
        st.warning("La data finale deve essere successiva alla data iniziale.")

    selected_year = period_start.year
    annual_df = year_slice(all_df, selected_year)
    period_df = filter_by_period(all_df, period_start, period_end)

    averages_df = calculate_weekly_averages(annual_df, period_df)
    totals_df = calculate_totals(annual_df, period_df)

    st.markdown('<div class="section-title">Medie Settimanali</div>', unsafe_allow_html=True)
    render_html_table(averages_df, decimals=True)

    if period_df.empty:
        st.info("Nessun dato nel periodo selezionato.")
    else:
        st.plotly_chart(
            build_bar_chart(period_df),
            width="stretch",
            config={"displayModeBar": False, "responsive": True},
        )

    st.markdown('<div class="section-title">Altre attività</div>', unsafe_allow_html=True)
    sport_table = totals_df.drop(columns=["_col"]).copy()
    sport_table = sport_table.iloc[[0, 1, 2, 3, 4, 5, 6]].reset_index(drop=True)
    render_html_table(sport_table, spacer_after="Arrampicata", decimals=False)

    pie_col_a, pie_col_b = st.columns(2)
    with pie_col_a:
        annual_pie = build_pie_chart(totals_df, "Anno", "Attività annuale")
        if annual_pie is None:
            st.info("Nessun dato annuale.")
        else:
            st.plotly_chart(annual_pie, width="stretch", config={"displayModeBar": False, "responsive": True})

    with pie_col_b:
        period_pie = build_pie_chart(totals_df, "Periodo", "Attività periodo")
        if period_pie is None:
            st.info("Nessun dato nel periodo.")
        else:
            st.plotly_chart(period_pie, width="stretch", config={"displayModeBar": False, "responsive": True})

    render_tracker(period_df)


if __name__ == "__main__":
    main()
