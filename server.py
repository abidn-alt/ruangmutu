#!/usr/bin/env python3
"""Ruang Mutu demo: standard-library HTTP API backed by SQLite."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import math
import os
import secrets
import sqlite3
import threading
import time
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from xml.sax.saxutils import escape
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "data.sqlite3"
HOST = os.environ.get("RUANG_MUTU_HOST", "127.0.0.1")
PORT = int(os.environ.get("RUANG_MUTU_PORT", "8000"))
SESSION_SECONDS = 8 * 60 * 60
DEFAULT_YEAR = 2026
TREND_CHART_YEARS = range(2025, 2031)
TEMPLATE_FILENAME = "Template_Data_Pendidikan_Lombok_Timur_Lengkap_Profil_Sekolah.xlsx"
DEMO_PASSWORD = "Dikbud123"
SCHEMA = (ROOT / "schema.sql").read_text(encoding="utf-8")
SEED_LOCK = threading.Lock()

DIMENSIONS = [
    ("manajemen", "Manajemen sekolah", .25, "Kepemimpinan kepala sekolah; Perencanaan berbasis data; Supervisi akademik; Disiplin guru; Kehadiran guru; Kehadiran siswa; Pengelolaan tenaga kependidikan; Pengelolaan sarana prasarana; Implementasi kurikulum; Pelaksanaan Projek P5; Budaya sekolah; Kemitraan sekolah"),
    ("pembelajaran", "Mutu pembelajaran", .25, "Observasi pembelajaran; Implementasi pembelajaran aktif; Pembelajaran berdiferensiasi; Pemanfaatan teknologi; Penggunaan asesmen formatif; Penggunaan hasil asesmen; Kualitas perangkat ajar; Kualitas modul ajar"),
    ("hasil_belajar", "Hasil belajar", .15, "Literasi; Numerasi; AKM; Nilai rapor pendidikan; Kenaikan kelas; Kelulusan siswa; Penurunan angka mengulang"),
    ("bosp", "Pengelolaan dana BOSP", .10, "Perencanaan RKAS; Kesesuaian penggunaan dana; Ketepatan pelaporan; Transparansi; Efektivitas penggunaan dana; Pemanfaatan untuk mutu pembelajaran"),
    ("gtk", "Kualitas guru dan tenaga kependidikan", .10, "Kualifikasi pendidikan guru; Sertifikasi guru; Pengembangan profesi; Pelatihan yang diikuti; Komunitas belajar; Kinerja guru"),
    ("prestasi", "Prestasi sekolah", .10, "Prestasi akademik; Prestasi non akademik; Tingkat kabupaten; Tingkat provinsi; Tingkat nasional; Tingkat internasional"),
    ("iklim", "Iklim dan lingkungan sekolah", .05, "Keamanan sekolah; Anti perundungan; Inklusivitas; Kebersihan sekolah; Sekolah sehat; Sekolah ramah anak; Ketangguhan iklim"),
]
INDICATOR_ROWS = [
    (f"{dimension[0]}_{index + 1:02d}", dimension[0], indicator.strip())
    for dimension in DIMENSIONS
    for index, indicator in enumerate(dimension[3].split(";"))
]

DISTRICTS = [
    "Aikmel", "Jerowaru", "Keruak", "Labuhan Haji", "Masbagik",
    "Montong Gading", "Pringgabaya", "Pringgasela", "Sakra",
    "Sakra Barat", "Sakra Timur", "Sambelia", "Selong", "Sembalun",
    "Sikur", "Sukamulia", "Suralaga", "Terara", "Wanasaba", "Suela", "Lenek",
]

DISTRICT_PROFILES = [
    (70, 2.7), (63, 1.0), (68, -1.8), (72, .5), (77, 2.8),
    (59, -2.8), (73, 1.5), (66, -.5), (69, -3.2), (64, 1.8),
    (71, -2.6), (61, .8), (78, 2.4), (67, 1.1), (74, 3.0),
    (65, -1.5), (72, 1.2), (76, 2.2), (62, -2.4), (69, .6), (71, 1.7),
]
SCHOOL_SEEDS = [
    (
        f"SIMULASI-LOTIM-{district_index * 2 + school_index + 1:03d}",
        f"SMP Contoh {district} {school_index + 1:02d} (Simulasi)",
        district_index,
        "Negeri" if school_index == 0 else "Swasta",
        round(baseline + (2 if school_index == 0 else -5), 1),
        slope if school_index == 0 else round(-slope * .65, 1),
    )
    for district_index, (district, (baseline, slope)) in enumerate(zip(DISTRICTS, DISTRICT_PROFILES))
    for school_index in range(2)
]

ROLE_LABELS = {
    "admin_kabupaten": "Admin Kabupaten",
    "kepala_dinas": "Kepala Dinas",
    "kabid_smp": "Kabid SMP",
    "pengawas_sekolah": "Pengawas Sekolah",
}


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


@contextmanager
def database_connection():
    connection = connect()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def password_digest(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 180_000)


def seed_database(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    migrate_assessment_resources(connection)
    migrate_school_profiles(connection)
    if connection.execute("SELECT COUNT(*) FROM dimensions").fetchone()[0] == 0:
        connection.executemany(
            "INSERT INTO dimensions (id, name, weight, indicators) VALUES (?, ?, ?, ?)",
            DIMENSIONS,
        )
    if connection.execute("SELECT COUNT(*) FROM dimension_indicators").fetchone()[0] == 0:
        connection.executemany(
            "INSERT INTO dimension_indicators (id, dimension_id, name) VALUES (?, ?, ?)",
            INDICATOR_ROWS,
        )
    if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        users = [
            ("Admin Kabupaten", "admin@ruangmutu.id", "admin_kabupaten"),
            ("Kepala Dinas", "kepala@ruangmutu.id", "kepala_dinas"),
            ("Kabid SMP", "kabid@ruangmutu.id", "kabid_smp"),
            ("Pengawas Sekolah", "pengawas@ruangmutu.id", "pengawas_sekolah"),
        ]
        for name, email, role in users:
            salt = secrets.token_bytes(16)
            connection.execute(
                """INSERT INTO users (name, email, role, district_scope, password_salt, password_hash)
                   VALUES (?, ?, ?, '*', ?, ?)""",
                (name, email, role, salt.hex(), password_digest(DEMO_PASSWORD, salt).hex()),
            )
    if connection.execute("SELECT COUNT(*) FROM schools").fetchone()[0] == 0:
        seed_schools_and_assessments(connection)
    connection.commit()


def migrate_school_profiles(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(schools)")}
    profile_columns = {
        "principal_name": "TEXT",
        "principal_nip": "TEXT",
        "accreditation_status": "TEXT",
    }
    for column, definition in profile_columns.items():
        if column not in columns:
            connection.execute(f"ALTER TABLE schools ADD COLUMN {column} {definition}")


def migrate_assessment_resources(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(assessments)")
    }
    resource_columns = {
        "student_count": "INTEGER CHECK (student_count >= 0)",
        "rombel_count": "INTEGER CHECK (rombel_count >= 0)",
        "teacher_count": "INTEGER CHECK (teacher_count >= 0)",
        "education_staff_count": "INTEGER CHECK (education_staff_count >= 0)",
    }
    for column, definition in resource_columns.items():
        if column not in columns:
            connection.execute(f"ALTER TABLE assessments ADD COLUMN {column} {definition}")

    seed_rows = connection.execute(
        """SELECT a.id, a.year, s.npsn, a.student_count
           FROM assessments a JOIN schools s ON s.id = a.school_id
           WHERE s.npsn LIKE 'SIMULASI-LOTIM-%' AND a.student_count IS NULL"""
    ).fetchall()
    for row in seed_rows:
        seed_number = int(row["npsn"].rsplit("-", 1)[-1])
        step = row["year"] - 2021
        student_count = 180 + (seed_number * 37 + step * 19) % 521
        rombel_count = max(6, round(student_count / (27 + seed_number % 5)))
        teacher_count = max(8, round(student_count / (18 + seed_number % 7)))
        education_staff_count = max(2, 2 + (seed_number + step) % 8)
        connection.execute(
            """UPDATE assessments
               SET student_count = ?, rombel_count = ?, teacher_count = ?, education_staff_count = ?
               WHERE id = ?""",
            (student_count, rombel_count, teacher_count, education_staff_count, row["id"]),
        )


def seed_schools_and_assessments(connection: sqlite3.Connection) -> None:
    indicators_by_dimension = {
        dimension_id: [(indicator_id, name) for indicator_id, grouped_dimension, name in INDICATOR_ROWS if grouped_dimension == dimension_id]
        for dimension_id, *_ in DIMENSIONS
    }
    for seed_index, (npsn, name, district_index, status, baseline, slope) in enumerate(SCHOOL_SEEDS):
        cursor = connection.execute(
            "INSERT INTO schools (npsn, name, district, status, address) VALUES (?, ?, ?, ?, ?)",
            (npsn, name, DISTRICTS[district_index], status, f"Kecamatan {DISTRICTS[district_index]}, Kabupaten Lombok Timur, Nusa Tenggara Barat"),
        )
        school_id = cursor.lastrowid
        for year in range(2021, 2026):
            step = year - 2021
            noise = math.sin((seed_index + 1) * (step + 1) * 1.7) * 1.15
            overall = clamp(baseline + slope * step + noise, 38, 94)
            differences = [
                2.5 * math.sin(seed_index + 1),
                3.2 * math.cos(seed_index * .7),
                (baseline - 70) * .22,
                (65 - baseline) * .13,
                1.4 * math.sin(seed_index * 1.4),
                1.8 * math.cos(seed_index * 1.3),
                1.3 * math.sin(seed_index * .8),
            ]
            dimension_scores = {}
            indicator_values = []
            for (dimension_id, _, _, _), difference in zip(DIMENSIONS, differences):
                base_score = clamp(overall + difference, 25, 98)
                indicators = indicators_by_dimension[dimension_id]
                variations = [math.sin((seed_index + 1) * (index + 2) * 1.37) * 1.7 for index in range(len(indicators))]
                average_variation = sum(variations) / len(variations)
                scores = [
                    (indicator_id, round(clamp(base_score + variation - average_variation, 0, 100), 1))
                    for (indicator_id, _), variation in zip(indicators, variations)
                ]
                indicator_values.extend(scores)
                dimension_scores[dimension_id] = round(sum(value for _, value in scores) / len(scores), 1)
            literacy = round(clamp(overall + math.sin(seed_index + step) * 2.1, 25, 98), 1)
            numeracy = round(clamp(overall - 3 + math.cos(seed_index * .6 + step) * 2.8, 20, 98), 1)
            attendance = round(clamp(93 + (overall - 70) * .16 + math.sin(seed_index + step) * 2.4, 68, 99), 1)
            student_attendance = round(clamp(95 + (overall - 70) * .08 + math.cos(seed_index + step) * 1.7, 75, 99), 1)
            absorption = round(clamp(82 + (overall - 70) * .48 + math.sin(seed_index * 1.3 + step) * 5, 48, 98), 1)
            dropout = round(clamp(.65 + (70 - overall) * .055 + (1.1 if slope < -2 else 0) - step * .025, .05, 4), 2)
            achievements = max(0, round((overall - 53) / 8 + (1 if status == "Negeri" else 0) + max(slope, 0) * .2))
            student_count = 180 + (seed_index * 37 + step * 19) % 521
            rombel_count = max(6, round(student_count / (27 + seed_index % 5)))
            teacher_count = max(8, round(student_count / (18 + seed_index % 7)))
            education_staff_count = max(2, 2 + (seed_index + step) % 8)
            cursor = connection.execute(
                """INSERT INTO assessments
                   (school_id, year, teacher_attendance, student_attendance, bosp_absorption,
                    literacy_score, numeracy_score, dropout_rate, student_count, rombel_count,
                    teacher_count, education_staff_count, achievement_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (school_id, year, attendance, student_attendance, absorption, literacy, numeracy,
                 dropout, student_count, rombel_count, teacher_count, education_staff_count, achievements),
            )
            connection.executemany(
                "INSERT INTO dimension_scores (assessment_id, dimension_id, score) VALUES (?, ?, ?)",
                [(cursor.lastrowid, key, score) for key, score in dimension_scores.items()],
            )
            connection.executemany(
                "INSERT INTO indicator_scores (assessment_id, indicator_id, score) VALUES (?, ?, ?)",
                [(cursor.lastrowid, indicator_id, score) for indicator_id, score in indicator_values],
            )


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def weighted_score(scores: list[dict]) -> float:
    return round(sum(item["score"] * item["weight"] for item in scores), 1)


def trend_label(scores: list[dict]) -> str:
    ordered = sorted(scores, key=lambda item: item["year"])
    if len(ordered) < 2:
        return "Stabil"
    change = ordered[-1]["score"] - ordered[0]["score"]
    if change >= 10:
        return "Sangat Meningkat"
    if change >= 3:
        return "Meningkat"
    if change <= -10:
        return "Sangat Menurun"
    if change <= -3:
        return "Menurun"
    return "Stabil"


def forecast(scores: list[dict]) -> float:
    ordered = sorted(scores, key=lambda item: item["year"])[-5:]
    if len(ordered) < 2:
        return ordered[-1]["score"] if ordered else 0
    x_mean = sum(item["year"] for item in ordered) / len(ordered)
    y_mean = sum(item["score"] for item in ordered) / len(ordered)
    denominator = sum((item["year"] - x_mean) ** 2 for item in ordered)
    slope = sum((item["year"] - x_mean) * (item["score"] - y_mean) for item in ordered) / denominator
    return round(clamp(ordered[-1]["score"] + clamp(slope, -5, 5), 0, 100), 1)


def risk_score(assessment: dict, quality: float, alert_count: int) -> float:
    score = (
        (100 - quality) * .55
        + max(0, 88 - assessment["teacher_attendance"]) * .45
        + max(0, 75 - assessment["bosp_absorption"]) * .25
        + max(0, assessment["dropout_rate"] - .5) * 4
        + alert_count * 2.5
    )
    return round(clamp(score, 0, 100), 1)


def risk_label(score: float) -> str:
    if score >= 35:
        return "Tinggi"
    if score >= 20:
        return "Sedang"
    return "Rendah"


def read_school_records(connection: sqlite3.Connection, year: int, district_scope: str = "*") -> list[dict]:
    parameters: list = [year]
    district_clause = ""
    if district_scope != "*":
        district_clause = " AND s.district = ?"
        parameters.append(district_scope)
    schools = connection.execute(
        f"""SELECT s.id, s.npsn, s.name, s.district, s.status,
                   s.principal_name, s.principal_nip, s.accreditation_status,
                   COALESCE(a.student_count, r.student_count) AS student_count,
                   COALESCE(a.rombel_count, r.rombel_count) AS rombel_count,
                   COALESCE(a.teacher_count, r.teacher_count) AS teacher_count,
                   COALESCE(a.education_staff_count, r.education_staff_count) AS education_staff_count,
                   a.id AS assessment_id, a.year, a.teacher_attendance, a.student_attendance,
                   a.bosp_absorption, a.literacy_score, a.numeracy_score, a.dropout_rate,
                   a.achievement_count
            FROM schools s JOIN assessments a ON a.school_id = s.id
            LEFT JOIN school_resource_snapshots r ON r.school_id = s.id AND r.year = a.year
            WHERE a.year = ?{district_clause}
            ORDER BY s.name""",
        parameters,
    ).fetchall()
    score_query = """SELECT a.school_id, a.year, d.id AS dimension_id, d.name AS dimension_name,
                  d.weight, ds.score
           FROM assessments a
           JOIN schools s ON s.id = a.school_id
           JOIN dimension_scores ds ON ds.assessment_id = a.id
           JOIN dimensions d ON d.id = ds.dimension_id
           WHERE a.year BETWEEN ? AND ?"""
    score_params: list = [max(2021, year - 4), year]
    if district_scope != "*":
        score_query += " AND s.district = ?"
        score_params.append(district_scope)
    all_scores = connection.execute(score_query + " ORDER BY a.school_id, a.year", score_params).fetchall()
    previous_metrics = {}
    if year > 2021:
        metrics_query = """SELECT a.school_id, a.literacy_score, a.numeracy_score, a.dropout_rate
                           FROM assessments a JOIN schools s ON s.id = a.school_id WHERE a.year = ?"""
        metric_params: list = [year - 1]
        if district_scope != "*":
            metrics_query += " AND s.district = ?"
            metric_params.append(district_scope)
        previous_metrics = {
            row["school_id"]: dict(row)
            for row in connection.execute(metrics_query, metric_params).fetchall()
        }
    history_by_school: dict[int, dict[int, list[dict]]] = {}
    for row in all_scores:
        history_by_school.setdefault(row["school_id"], {}).setdefault(row["year"], []).append(
            {"id": row["dimension_id"], "name": row["dimension_name"], "weight": row["weight"], "score": row["score"]}
        )
    records = []
    for row in schools:
        raw = dict(row)
        raw["previous_metrics"] = previous_metrics.get(row["id"])
        history = [
            {"year": item_year, "score": weighted_score(items)}
            for item_year, items in sorted(history_by_school.get(row["id"], {}).items())
        ]
        current_dimensions = history_by_school.get(row["id"], {}).get(year, [])
        current_quality = weighted_score(current_dimensions)
        previous = next((item["score"] for item in history if item["year"] == year - 1), None)
        change = round(current_quality - previous, 1) if previous is not None else 0
        alerts = compute_alerts(raw, current_quality, previous, history_by_school.get(row["id"], {}), year)
        current_risk = risk_score(raw, current_quality, len(alerts))
        records.append({
            **raw,
            "assessed": True,
            "quality_score": current_quality,
            "change": change,
            "trend": trend_label(history),
            "history": history,
            "forecast": forecast(history),
            "risk_score": current_risk,
            "risk": risk_label(current_risk),
            "alerts": alerts,
            "dimensions": current_dimensions,
        })
    county_average = round(sum(item["quality_score"] for item in records) / len(records), 1) if records else 0
    best_school = max(records, key=lambda item: item["quality_score"], default=None)
    district_averages = {}
    for district in {item["district"] for item in records}:
        district_items = [item for item in records if item["district"] == district]
        district_averages[district] = round(sum(item["quality_score"] for item in district_items) / len(district_items), 1)
    for record in records:
        record["gaps"] = {
            "district_average": round(record["quality_score"] - district_averages[record["district"]], 1),
            "county_average": round(record["quality_score"] - county_average, 1),
            "best_school": round(record["quality_score"] - best_school["quality_score"], 1) if best_school else 0,
            "best_school_name": best_school["name"] if best_school else "",
        }
    district_rank: dict[str, int] = {}
    status_rank: dict[str, int] = {}
    for district in {item["district"] for item in records}:
        for rank, record in enumerate(sorted((item for item in records if item["district"] == district), key=lambda item: item["quality_score"], reverse=True), 1):
            district_rank[record["id"]] = rank
    for status in {"Negeri", "Swasta"}:
        for rank, record in enumerate(sorted((item for item in records if item["status"] == status), key=lambda item: item["quality_score"], reverse=True), 1):
            status_rank[record["id"]] = rank
    for rank, record in enumerate(sorted(records, key=lambda item: item["quality_score"], reverse=True), 1):
        record["rank"] = rank
        record["district_rank"] = district_rank[record["id"]]
        record["status_rank"] = status_rank[record["id"]]
    return sorted(records, key=lambda item: item["quality_score"], reverse=True)


def compute_alerts(assessment: dict, quality: float, previous: float | None,
                   yearly_scores: dict[int, list[dict]], year: int) -> list[dict]:
    alerts = []
    if previous is not None and previous > 0 and (quality - previous) / previous < -.10:
        alerts.append({"type": "mutu_turun", "severity": "tinggi", "title": "Indeks mutu turun lebih dari 10%", "value": f"{quality - previous:.1f} poin"})
    if assessment["teacher_attendance"] < 85:
        alerts.append({"type": "kehadiran_guru", "severity": "tinggi", "title": "Kehadiran guru di bawah 85%", "value": f'{assessment["teacher_attendance"]:.1f}%'})
    if assessment["bosp_absorption"] < 70:
        alerts.append({"type": "serapan_bosp", "severity": "sedang", "title": "Serapan BOSP di bawah 70%", "value": f'{assessment["bosp_absorption"]:.1f}%'})
    previous_metrics = assessment.get("previous_metrics")
    if previous_metrics:
        if assessment["literacy_score"] < previous_metrics["literacy_score"] - 5:
            alerts.append({"type": "literasi_turun", "severity": "sedang", "title": "Capaian literasi turun lebih dari 5 poin", "value": f'{assessment["literacy_score"]:.1f}'})
        if assessment["numeracy_score"] < previous_metrics["numeracy_score"] - 5:
            alerts.append({"type": "numerasi_turun", "severity": "sedang", "title": "Capaian numerasi turun lebih dari 5 poin", "value": f'{assessment["numeracy_score"]:.1f}'})
        if assessment["dropout_rate"] > previous_metrics["dropout_rate"] + 1:
            alerts.append({"type": "putus_sekolah", "severity": "tinggi", "title": "Angka putus sekolah meningkat", "value": f'{assessment["dropout_rate"]:.2f}%'})
    return alerts


def collect_dashboard(connection: sqlite3.Connection, year: int, district_scope: str = "*") -> dict:
    records = read_school_records(connection, year, district_scope)
    if not records:
        district_stats = collect_district_stats(connection, year, district_scope, [])
        districts = sorted(district_stats, key=lambda item: item["name"])
        schools = read_school_registry(connection, year, district_scope)
        trend = [
            {"year": trend_year, "quality": None, "learning": None}
            for trend_year in TREND_CHART_YEARS
        ]
        return {
            "year": year,
            "summary": {
                "total": sum(item["school_count"] for item in districts),
                "assessed": 0,
                "districts": len(districts),
                "public_schools": sum(item["public_schools"] for item in districts),
                "private_schools": sum(item["private_schools"] for item in districts),
                "students": sum(item["students"] for item in districts),
                "classrooms": sum(item["classrooms"] for item in districts),
                "teachers": sum(item["teachers"] for item in districts),
                "education_staff": sum(item["education_staff"] for item in districts),
                "student_coverage": sum(item["student_coverage"] for item in districts),
                "classroom_coverage": sum(item["classroom_coverage"] for item in districts),
                "teacher_coverage": sum(item["teacher_coverage"] for item in districts),
                "staff_coverage": sum(item["staff_coverage"] for item in districts),
                "excellent": 0,
                "growing": 0,
                "stagnant": 0,
                "declining": 0,
                "priority": 0,
                "average": 0,
                "change": 0,
            },
            "trend": trend,
            "districts": districts,
            "alerts": [],
            "insights": {
                "summary": f"Belum ada penilaian sekolah untuk tahun {year}.",
                "recommendations": [],
                "forecast_average": 0,
            },
            "schools": schools,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    district_stats = collect_district_stats(connection, year, district_scope, records)
    average = round(sum(item["quality_score"] for item in records) / len(records), 1)
    previous_year_records = read_school_records(connection, year - 1, district_scope) if year > 2021 else []
    prev_avg = round(sum(item["quality_score"] for item in previous_year_records) / len(previous_year_records), 1) if previous_year_records else average
    trend = []
    for trend_year in TREND_CHART_YEARS:
        year_records = read_school_records(connection, trend_year, district_scope)
        trend.append({
            "year": trend_year,
            "quality": round(sum(item["quality_score"] for item in year_records) / len(year_records), 1) if year_records else None,
            "learning": round(sum((item["literacy_score"] + item["numeracy_score"]) / 2 for item in year_records) / len(year_records), 1) if year_records else None,
        })
    district_rankings = sorted(
        district_stats,
        key=lambda item: (item["average"] is None, -(item["average"] if item["average"] is not None else 0), item["name"]),
    )
    alerts = []
    for record in records:
        for alert in record["alerts"]:
            alerts.append({
                "school_id": record["id"], "school": record["name"], "district": record["district"],
                "quality_score": record["quality_score"], **alert,
            })
    alerts.sort(key=lambda item: (0 if item["severity"] == "tinggi" else 1, item["school"]))
    dimension_averages = []
    for dimension in DIMENSIONS:
        key, name, weight, _ = dimension
        values = [next(item["score"] for item in school["dimensions"] if item["id"] == key) for school in records]
        dimension_averages.append({"id": key, "name": name, "average": round(sum(values) / len(values), 1), "weight": weight})
    strongest = max(dimension_averages, key=lambda item: item["average"])
    weakest = min(dimension_averages, key=lambda item: item["average"])
    priority = sorted((item for item in records if item["risk"] == "Tinggi"), key=lambda item: item["risk_score"], reverse=True)
    declining = [item for item in records if item["trend"] in ("Menurun", "Sangat Menurun")]
    forecast_avg = round(sum(item["forecast"] for item in records) / len(records), 1)
    insights = {
        "summary": f"Rerata indeks mutu {average:.1f}/100 dari {len(records)} SMP pada {year}, {'naik' if average >= prev_avg else 'turun'} {abs(average - prev_avg):.1f} poin dibanding tahun sebelumnya. Dimensi relatif terkuat: {strongest['name']}; area dengan skor terendah: {weakest['name']}. {len(priority)} sekolah memerlukan prioritas pembinaan. Temuan dimensi menunjukkan sinyal untuk diverifikasi, bukan bukti sebab-akibat.",
        "strongest": strongest,
        "weakest": weakest,
        "recommendations": build_recommendations(weakest, alerts, priority),
        "budget_priority": {"dimension": weakest["name"], "average": weakest["average"], "rationale": "Validasi kebutuhan lapangan dan RKAS sebelum penetapan anggaran."},
        "supervision_priority": [{"id": item["id"], "name": item["name"], "district": item["district"], "risk_score": item["risk_score"]} for item in priority[:5]],
        "priority_schools": [{"id": item["id"], "name": item["name"], "district": item["district"], "risk_score": item["risk_score"]} for item in priority[:5]],
        "declining_count": len(declining),
        "forecast_average": forecast_avg,
        "forecast_note": "Prediksi sederhana menggunakan regresi linear atas skor indeks mutu 5 tahun; bukan jaminan capaian.",
    }
    assessed_ids = {item["id"] for item in records}
    unassessed_schools = [
        item for item in read_school_registry(connection, year, district_scope)
        if item["id"] not in assessed_ids
    ]
    return {
        "year": year,
        "summary": {
            "total": sum(item["school_count"] for item in district_stats),
            "assessed": len(records),
            "districts": len(district_stats),
            "public_schools": sum(item["public_schools"] for item in district_stats),
            "private_schools": sum(item["private_schools"] for item in district_stats),
            "students": sum(item["students"] for item in district_stats),
            "classrooms": sum(item["classrooms"] for item in district_stats),
            "teachers": sum(item["teachers"] for item in district_stats),
            "education_staff": sum(item["education_staff"] for item in district_stats),
            "student_coverage": sum(item["student_coverage"] for item in district_stats),
            "classroom_coverage": sum(item["classroom_coverage"] for item in district_stats),
            "teacher_coverage": sum(item["teacher_coverage"] for item in district_stats),
            "staff_coverage": sum(item["staff_coverage"] for item in district_stats),
            "excellent": sum(item["quality_score"] >= 80 for item in records),
            "growing": sum(item["trend"] in ("Meningkat", "Sangat Meningkat") for item in records),
            "stagnant": sum(item["trend"] == "Stabil" for item in records),
            "declining": len(declining),
            "priority": len(priority),
            "average": average,
            "change": round(average - prev_avg, 1),
        },
        "trend": trend,
        "districts": district_rankings,
        "alerts": alerts,
        "insights": insights,
        "schools": [*records, *unassessed_schools],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def read_school_registry(
    connection: sqlite3.Connection,
    year: int,
    district_scope: str = "*",
) -> list[dict]:
    query = """SELECT s.id, s.npsn, s.name, s.district, s.status, s.principal_name, s.principal_nip,
                      s.accreditation_status, r.student_count, r.rombel_count,
                      r.teacher_count, r.education_staff_count
               FROM schools s
               LEFT JOIN school_resource_snapshots r ON r.school_id = s.id AND r.year = ?"""
    params: list = [year]
    if district_scope != "*":
        query += " WHERE s.district = ?"
        params.append(district_scope)
    query += " ORDER BY s.name"
    return [
        {
            **dict(row),
            "year": year,
            "assessed": False,
            "quality_score": None,
            "change": None,
            "trend": "Belum dinilai",
            "forecast": None,
            "risk_score": None,
            "risk": "Belum dinilai",
            "alerts": [],
            "dimensions": [],
            "history": [],
        }
        for row in connection.execute(query, params)
    ]


def collect_district_stats(
    connection: sqlite3.Connection,
    year: int,
    district_scope: str,
    assessed_records: list[dict],
) -> list[dict]:
    query = """SELECT s.district, s.status, a.id AS assessment_id,
                      COALESCE(a.student_count, r.student_count) AS student_count,
                      COALESCE(a.rombel_count, r.rombel_count) AS rombel_count,
                      COALESCE(a.teacher_count, r.teacher_count) AS teacher_count,
                      COALESCE(a.education_staff_count, r.education_staff_count) AS education_staff_count
               FROM schools s LEFT JOIN assessments a
                 ON a.school_id = s.id AND a.year = ?
               LEFT JOIN school_resource_snapshots r
                 ON r.school_id = s.id AND r.year = ?"""
    params: list = [year, year]
    if district_scope != "*":
        query += " WHERE s.district = ?"
        params.append(district_scope)
    query += " ORDER BY s.district"
    groups: dict[str, dict] = {}
    for row in connection.execute(query, params):
        district = groups.setdefault(row["district"], {
            "name": row["district"], "school_count": 0, "public_schools": 0,
            "private_schools": 0, "students": 0, "classrooms": 0,
            "teachers": 0, "education_staff": 0, "assessed_schools": 0,
            "student_coverage": 0, "classroom_coverage": 0,
            "teacher_coverage": 0, "staff_coverage": 0, "average": None,
        })
        district["school_count"] += 1
        district["public_schools"] += row["status"] == "Negeri"
        district["private_schools"] += row["status"] == "Swasta"
        if row["assessment_id"] is not None:
            district["assessed_schools"] += 1
        for field, value_key, coverage_key in (
            ("student_count", "students", "student_coverage"),
            ("rombel_count", "classrooms", "classroom_coverage"),
            ("teacher_count", "teachers", "teacher_coverage"),
            ("education_staff_count", "education_staff", "staff_coverage"),
        ):
            if row[field] is not None:
                district[value_key] += row[field]
                district[coverage_key] += 1
    score_groups: dict[str, list[float]] = {}
    for record in assessed_records:
        score_groups.setdefault(record["district"], []).append(record["quality_score"])
    for name, values in score_groups.items():
        groups[name]["average"] = round(sum(values) / len(values), 1)
        groups[name]["count"] = len(values)
    for item in groups.values():
        item.setdefault("count", 0)
    return list(groups.values())


def build_recommendations(weakest: dict, alerts: list[dict], priority: list[dict]) -> list[str]:
    recommendations = [
        f"Prioritas anggaran: reviu kebutuhan dan RKAS untuk memperbaiki {weakest['name'].lower()} (rerata {weakest['average']:.0f}/100).",
    ]
    if priority:
        schools = ", ".join(item["name"] for item in priority[:3])
        recommendations.append(f"Prioritas supervisi: verifikasi lapangan dan dampingi {schools}.")
    if any(item["type"] == "kehadiran_guru" for item in alerts):
        recommendations.append("Verifikasi kehadiran guru di sekolah berisiko; susun pendampingan bersama pengawas.")
    if any(item["type"] == "serapan_bosp" for item in alerts):
        recommendations.append("Dampingi reviu RKAS dan realokasi BOSP untuk pembelajaran yang berdampak.")
    if any(item["type"] in ("literasi_turun", "numerasi_turun") for item in alerts):
        recommendations.append("Prioritaskan asesmen diagnostik dan intervensi literasi-numerasi terukur.")
    return recommendations[:4]


def safe_user(user: sqlite3.Row | dict) -> dict:
    return {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"], "role_label": ROLE_LABELS[user["role"]]}


SCHOOL_EXPORT_COLUMNS = [
    ("npsn", "NPSN"),
    ("name", "Nama sekolah"),
    ("principal_name", "Nama kepala sekolah"),
    ("principal_nip", "NIP kepala sekolah"),
    ("accreditation_status", "Status akreditasi"),
    ("district", "Kecamatan"),
    ("status", "Status sekolah"),
    ("year", "Tahun"),
    ("student_count", "Jumlah siswa"),
    ("rombel_count", "Jumlah rombel"),
    ("teacher_count", "Jumlah guru"),
    ("education_staff_count", "Jumlah tenaga kependidikan"),
    ("quality_score", "Indeks mutu"),
    ("change", "Perubahan"),
    ("trend", "Tren 5 tahun"),
    ("risk", "Risiko"),
    ("forecast", "Prediksi tahun berikutnya"),
]


def xlsx_column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def create_school_export_xlsx(schools: list[dict]) -> bytes:
    rows = [[label for _, label in SCHOOL_EXPORT_COLUMNS]]
    rows.extend([[school.get(key) for key, _ in SCHOOL_EXPORT_COLUMNS] for school in schools])
    worksheet_rows = []
    for row_index, row in enumerate(rows, 1):
        cells = []
        for column_index, value in enumerate(row, 1):
            reference = f"{xlsx_column_name(column_index)}{row_index}"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cell = f'<c r="{reference}"><v>{value}</v></c>'
            elif value is None:
                continue
            else:
                cell = (
                    f'<c r="{reference}" t="inlineStr"><is><t xml:space="preserve">'
                    f"{escape(str(value))}</t></is></c>"
                )
            cells.append(cell)
        worksheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="A1:{xlsx_column_name(len(SCHOOL_EXPORT_COLUMNS))}{len(rows)}"/>'
        f'<sheetData>{"".join(worksheet_rows)}</sheetData></worksheet>'
    )
    workbook = io.BytesIO()
    with zipfile.ZipFile(workbook, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>',
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Data Sekolah" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>',
        )
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
    return workbook.getvalue()


class APIHandler(BaseHTTPRequestHandler):
    server_version = "RuangMutu/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_attachment(self, body: bytes, filename: str, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Header Content-Length tidak valid.") from exc
        if size > 1_000_000:
            raise ValueError("Ukuran permintaan melebihi batas.")
        if size <= 0:
            raise ValueError("Body JSON diperlukan.")
        try:
            payload = json.loads(self.rfile.read(size))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("Body harus berupa JSON yang valid.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Body JSON harus berupa objek.")
        return payload

    def current_user(self, connection: sqlite3.Connection) -> sqlite3.Row | None:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        token = header[7:].strip()
        if not token or len(token) > 256:
            return None
        return connection.execute(
            """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash = ? AND s.expires_at > ?""",
            (hashlib.sha256(token.encode()).hexdigest(), int(time.time())),
        ).fetchone()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self.serve_static(parsed.path)
            return
        try:
            with database_connection() as connection:
                user = self.current_user(connection)
                if user is None:
                    self.send_json(401, {"error": "Sesi tidak valid atau telah berakhir."})
                    return
                scope = user["district_scope"]
                if parsed.path == "/api/auth/me":
                    self.send_json(200, {"user": safe_user(user)})
                    return
                if parsed.path == "/api/indicators":
                    dimensions = [
                        {"id": key, "name": name, "weight": weight}
                        for key, name, weight, _ in DIMENSIONS
                    ]
                    self.send_json(200, {
                        "dimensions": dimensions,
                        "indicators": [
                            {"id": indicator_id, "dimension_id": dimension_id, "name": name}
                            for indicator_id, dimension_id, name in INDICATOR_ROWS
                        ],
                    })
                    return
                if parsed.path == "/api/dashboard":
                    year = self.parse_year(parse_qs(parsed.query).get("year", [str(DEFAULT_YEAR)])[0])
                    self.send_json(200, collect_dashboard(connection, year, scope))
                    return
                if parsed.path == "/api/exports/schools.xlsx":
                    year = self.parse_year(parse_qs(parsed.query).get("year", [str(DEFAULT_YEAR)])[0])
                    schools = collect_dashboard(connection, year, scope)["schools"]
                    self.send_attachment(
                        create_school_export_xlsx(schools),
                        f"ruang-mutu-sekolah-{year}.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                    return
                if parsed.path == "/api/schools":
                    query = parse_qs(parsed.query)
                    year = self.parse_year(query.get("year", [str(DEFAULT_YEAR)])[0])
                    data = collect_dashboard(connection, year, scope)["schools"]
                    district = query.get("district", [""])[0].strip().lower()
                    status = query.get("status", [""])[0]
                    search = query.get("search", [""])[0].strip().lower()
                    data = [item for item in data if (not district or district in item["district"].lower()) and (not status or item["status"] == status) and (not search or search in item["name"].lower() or search in item["npsn"] or search in item["district"].lower())]
                    self.send_json(200, {"year": year, "count": len(data), "schools": data})
                    return
                if parsed.path.startswith("/api/schools/"):
                    school_id = self.parse_id(parsed.path.rsplit("/", 1)[-1])
                    year = self.parse_year(parse_qs(parsed.query).get("year", [str(DEFAULT_YEAR)])[0])
                    school = self.school_detail(connection, school_id, scope, year)
                    if school is None:
                        self.send_json(404, {"error": "Sekolah tidak ditemukan."})
                    else:
                        self.send_json(200, school)
                    return
                if parsed.path == "/api/alerts":
                    year = self.parse_year(parse_qs(parsed.query).get("year", [str(DEFAULT_YEAR)])[0])
                    data = collect_dashboard(connection, year, scope)["alerts"]
                    self.send_json(200, {"year": year, "count": len(data), "alerts": data})
                    return
                self.send_json(404, {"error": "Endpoint tidak ditemukan."})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except sqlite3.Error:
            self.log_error("Database error while handling GET")
            self.send_json(500, {"error": "Terjadi kesalahan saat membaca data."})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json()
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
            return
        try:
            with database_connection() as connection:
                if parsed.path == "/api/auth/login":
                    self.login(connection, payload)
                    return
                user = self.current_user(connection)
                if user is None:
                    self.send_json(401, {"error": "Sesi tidak valid atau telah berakhir."})
                    return
                if parsed.path == "/api/assessments":
                    self.create_assessment(connection, user, payload)
                    return
                if parsed.path == "/api/import/schools":
                    if user["role"] != "admin_kabupaten":
                        raise PermissionError("Hanya admin kabupaten yang dapat mengimpor data sekolah.")
                    import import_school_csv

                    inserted, updated, snapshots, backup_path = (
                        import_school_csv.import_uploaded_school_csv(
                            payload.get("csv"),
                            DB_PATH,
                        )
                    )
                    self.send_json(200, {
                        "message": "Data sekolah berhasil diperbarui.",
                        "inserted": inserted,
                        "updated": updated,
                        "resource_snapshots": snapshots,
                        "backup": backup_path.name,
                    })
                    return
                self.send_json(404, {"error": "Endpoint tidak ditemukan."})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except PermissionError as exc:
            self.send_json(403, {"error": str(exc)})
        except sqlite3.IntegrityError:
            self.send_json(409, {"error": "Penilaian sekolah untuk tahun tersebut sudah tersedia."})
        except sqlite3.Error:
            self.log_error("Database error while handling POST")
            self.send_json(500, {"error": "Terjadi kesalahan saat menyimpan data."})

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json()
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
            return
        try:
            with database_connection() as connection:
                user = self.current_user(connection)
                if user is None:
                    self.send_json(401, {"error": "Sesi tidak valid atau telah berakhir."})
                    return
                if not parsed.path.startswith("/api/schools/"):
                    self.send_json(404, {"error": "Endpoint tidak ditemukan."})
                    return
                school_id = self.parse_id(parsed.path.rsplit("/", 1)[-1])
                self.update_school_profile(connection, user, school_id, payload)
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except PermissionError as exc:
            self.send_json(403, {"error": str(exc)})
        except sqlite3.Error:
            self.log_error("Database error while updating school profile")
            self.send_json(500, {"error": "Terjadi kesalahan saat menyimpan profil sekolah."})

    def do_DELETE(self) -> None:
        if self.path != "/api/auth/logout":
            self.send_json(404, {"error": "Endpoint tidak ditemukan."})
            return
        with database_connection() as connection:
            header = self.headers.get("Authorization", "")
            token = header[7:].strip() if header.startswith("Bearer ") else ""
            if token:
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))
            self.send_json(200, {"message": "Anda telah keluar."})

    def login(self, connection: sqlite3.Connection, payload: dict) -> None:
        email = payload.get("email")
        password = payload.get("password")
        if not isinstance(email, str) or not isinstance(password, str) or len(email) > 254 or len(password) > 256:
            self.send_json(400, {"error": "Email dan kata sandi wajib diisi."})
            return
        user = connection.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        if user is None or not hmac.compare_digest(
            password_digest(password, bytes.fromhex(user["password_salt"])).hex(), user["password_hash"]
        ):
            self.send_json(401, {"error": "Email atau kata sandi tidak sesuai."})
            return
        token = secrets.token_urlsafe(36)
        connection.execute(
            "INSERT INTO sessions (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
            (user["id"], hashlib.sha256(token.encode()).hexdigest(), int(time.time()) + SESSION_SECONDS),
        )
        self.send_json(200, {"token": token, "expires_in": SESSION_SECONDS, "user": safe_user(user)})

    def update_school_profile(
        self,
        connection: sqlite3.Connection,
        user: sqlite3.Row,
        school_id: int,
        payload: dict,
    ) -> None:
        if user["role"] not in ("admin_kabupaten", "kabid_smp"):
            raise PermissionError("Hanya Admin Kabupaten atau Kabid SMP yang dapat memperbarui profil sekolah.")
        if not isinstance(payload, dict) or not payload:
            raise ValueError("Kirim sedikitnya satu data profil sekolah.")
        allowed = {
            "principal_name": ("Nama kepala sekolah", 160),
            "principal_nip": ("NIP kepala sekolah", 18),
            "accreditation_status": ("Status akreditasi", 40),
        }
        unknown = set(payload) - set(allowed)
        if unknown:
            raise ValueError(f"Kolom profil tidak dikenali: {', '.join(sorted(unknown))}.")
        school = connection.execute(
            "SELECT id, district FROM schools WHERE id = ?", (school_id,)
        ).fetchone()
        if school is None:
            raise ValueError("Sekolah tidak ditemukan.")
        if user["district_scope"] != "*" and school["district"] != user["district_scope"]:
            raise PermissionError("Anda tidak memiliki akses ke sekolah di kecamatan tersebut.")

        updates = {}
        for key, value in payload.items():
            label, maximum = allowed[key]
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{label} harus berupa teks atau kosong.")
            normalized = value.strip() if value is not None else None
            if normalized == "":
                normalized = None
            if normalized is not None and len(normalized) > maximum:
                raise ValueError(f"{label} maksimal {maximum} karakter.")
            if key == "principal_nip" and normalized is not None and (
                len(normalized) != 18 or not normalized.isdigit()
            ):
                raise ValueError("NIP kepala sekolah harus terdiri dari 18 angka.")
            updates[key] = normalized
        assignments = ", ".join(f"{key} = ?" for key in updates)
        connection.execute(
            f"UPDATE schools SET {assignments} WHERE id = ?",
            (*updates.values(), school_id),
        )
        self.send_json(200, {"message": "Profil sekolah berhasil diperbarui.", **updates})

    def create_assessment(self, connection: sqlite3.Connection, user: sqlite3.Row, payload: dict) -> None:
        if user["role"] not in ("admin_kabupaten", "kabid_smp", "pengawas_sekolah"):
            raise PermissionError("Peran Anda hanya memiliki akses baca.")
        school_id = self.parse_id(payload.get("school_id"))
        year = self.parse_year(payload.get("year"))
        school = connection.execute("SELECT * FROM schools WHERE id = ?", (school_id,)).fetchone()
        if school is None:
            raise ValueError("Sekolah tidak ditemukan.")
        if user["district_scope"] != "*" and school["district"] != user["district_scope"]:
            raise PermissionError("Anda tidak memiliki akses ke sekolah di kecamatan tersebut.")
        metric_fields = {
            "teacher_attendance": (0, 100), "student_attendance": (0, 100),
            "bosp_absorption": (0, 100), "literacy_score": (0, 100),
            "numeracy_score": (0, 100), "dropout_rate": (0, 100),
        }
        metrics = {}
        for key, (lower, upper) in metric_fields.items():
            value = payload.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lower <= value <= upper:
                raise ValueError(f"Nilai {key} wajib berupa angka antara {lower} dan {upper}.")
            metrics[key] = float(value)
        resource_fields = {
            "student_count": 100000,
            "rombel_count": 5000,
            "teacher_count": 20000,
            "education_staff_count": 20000,
        }
        for key, maximum in resource_fields.items():
            value = payload.get(key)
            if value is None:
                metrics[key] = None
            elif isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
                raise ValueError(f"{key} harus berupa bilangan bulat antara 0 dan {maximum}.")
            else:
                metrics[key] = value
        indicator_scores = payload.get("indicators")
        dimension_scores = payload.get("dimensions")
        if indicator_scores is not None:
            if dimension_scores is not None:
                raise ValueError("Kirim skor indikator atau skor dimensi, jangan keduanya.")
            if not isinstance(indicator_scores, dict) or set(indicator_scores) != {item[0] for item in INDICATOR_ROWS}:
                raise ValueError("Semua skor indikator wajib dikirim sesuai /api/indicators.")
            for key, value in indicator_scores.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
                    raise ValueError(f"Skor indikator {key} harus berada antara 0 dan 100.")
            grouped_scores: dict[str, list[float]] = {}
            for indicator_id, dimension_id, _ in INDICATOR_ROWS:
                grouped_scores.setdefault(dimension_id, []).append(float(indicator_scores[indicator_id]))
            scores = {key: round(sum(values) / len(values), 1) for key, values in grouped_scores.items()}
            indicator_values = [(key, float(value)) for key, value in indicator_scores.items()]
        else:
            scores = dimension_scores
            if not isinstance(scores, dict) or set(scores) != {item[0] for item in DIMENSIONS}:
                raise ValueError("Kirim semua skor indikator atau tujuh skor dimensi.")
            for key, value in scores.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
                    raise ValueError(f"Skor dimensi {key} harus berada antara 0 dan 100.")
            indicator_values = [(indicator_id, float(scores[dimension_id])) for indicator_id, dimension_id, _ in INDICATOR_ROWS]
        achievement_count = payload.get("achievement_count", 0)
        if isinstance(achievement_count, bool) or not isinstance(achievement_count, int) or not 0 <= achievement_count <= 10000:
            raise ValueError("achievement_count harus berupa bilangan bulat nonnegatif.")
        cursor = connection.execute(
            """INSERT INTO assessments
               (school_id, year, teacher_attendance, student_attendance, bosp_absorption,
                literacy_score, numeracy_score, dropout_rate, student_count, rombel_count,
                teacher_count, education_staff_count, achievement_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (school_id, year, metrics["teacher_attendance"], metrics["student_attendance"],
             metrics["bosp_absorption"], metrics["literacy_score"], metrics["numeracy_score"],
             metrics["dropout_rate"], metrics["student_count"], metrics["rombel_count"],
             metrics["teacher_count"], metrics["education_staff_count"], achievement_count),
        )
        connection.executemany(
            "INSERT INTO dimension_scores (assessment_id, dimension_id, score) VALUES (?, ?, ?)",
            [(cursor.lastrowid, key, value) for key, value in scores.items()],
        )
        connection.executemany(
            "INSERT INTO indicator_scores (assessment_id, indicator_id, score) VALUES (?, ?, ?)",
            [(cursor.lastrowid, key, value) for key, value in indicator_values],
        )
        self.send_json(201, {"message": "Penilaian berhasil disimpan.", "assessment_id": cursor.lastrowid, "dimensions": scores})

    def school_detail(self, connection: sqlite3.Connection, school_id: int, district_scope: str, year: int) -> dict | None:
        query = "SELECT * FROM schools WHERE id = ?"
        params: list = [school_id]
        if district_scope != "*":
            query += " AND district = ?"
            params.append(district_scope)
        school = connection.execute(query, params).fetchone()
        if school is None:
            return None
        record = next(
            (item for item in collect_dashboard(connection, year, district_scope)["schools"] if item["id"] == school_id),
            None,
        )
        if record is None:
            record = {
                **dict(school),
                "year": year,
                "assessed": False,
                "student_count": None,
                "rombel_count": None,
                "teacher_count": None,
                "education_staff_count": None,
                "quality_score": None,
                "change": None,
                "trend": "Belum dinilai",
                "forecast": None,
                "risk_score": None,
                "risk": "Belum dinilai",
                "alerts": [],
                "dimensions": [],
                "history": [],
                "gaps": None,
                "teacher_attendance": None,
                "bosp_absorption": None,
                "literacy_score": None,
                "numeracy_score": None,
                "dropout_rate": None,
            }
        years = self.school_years(connection, school_id)
        current_year = next((item for item in years if item["year"] == year), None)
        record["indicators"] = current_year["indicators"] if current_year else []
        return {"school": record, "years": years}

    @staticmethod
    def school_years(connection: sqlite3.Connection, school_id: int) -> list[dict]:
        years = connection.execute(
            """SELECT a.year, a.teacher_attendance, a.student_attendance, a.bosp_absorption,
                      a.literacy_score, a.numeracy_score, a.dropout_rate, a.student_count,
                      a.rombel_count, a.teacher_count, a.education_staff_count, a.achievement_count,
                      d.id AS dimension_id, d.name AS dimension_name, d.weight, ds.score
               FROM assessments a JOIN dimension_scores ds ON ds.assessment_id = a.id
               JOIN dimensions d ON d.id = ds.dimension_id
               WHERE a.school_id = ? ORDER BY a.year, d.id""",
            (school_id,),
        ).fetchall()
        results: dict[int, dict] = {}
        for row in years:
            year = results.setdefault(row["year"], {
                "year": row["year"], "teacher_attendance": row["teacher_attendance"],
                "student_attendance": row["student_attendance"], "bosp_absorption": row["bosp_absorption"],
                "literacy_score": row["literacy_score"], "numeracy_score": row["numeracy_score"],
                "dropout_rate": row["dropout_rate"], "student_count": row["student_count"],
                "rombel_count": row["rombel_count"], "teacher_count": row["teacher_count"],
                "education_staff_count": row["education_staff_count"],
                "achievement_count": row["achievement_count"],
                "indicators": [],
                "dimensions": [],
            })
            year["dimensions"].append({"id": row["dimension_id"], "name": row["dimension_name"], "weight": row["weight"], "score": row["score"]})
        for year in results.values():
            year["quality_score"] = weighted_score(year["dimensions"])
        indicator_rows = connection.execute(
            """SELECT a.year, i.id, i.dimension_id, i.name, score.score
               FROM assessments a
               JOIN indicator_scores score ON score.assessment_id = a.id
               JOIN dimension_indicators i ON i.id = score.indicator_id
               WHERE a.school_id = ? ORDER BY a.year, i.dimension_id, i.id""",
            (school_id,),
        ).fetchall()
        for row in indicator_rows:
            results[row["year"]]["indicators"].append({
                "id": row["id"], "dimension_id": row["dimension_id"],
                "name": row["name"], "score": row["score"],
            })
        return list(results.values())

    @staticmethod
    def parse_year(value: object) -> int:
        try:
            year = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Tahun harus berupa angka antara 2021 dan 2030.") from exc
        if not 2021 <= year <= 2030:
            raise ValueError("Tahun harus berada antara 2021 dan 2030.")
        return year

    @staticmethod
    def parse_id(value: object) -> int:
        try:
            identifier = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("ID sekolah tidak valid.") from exc
        if identifier <= 0:
            raise ValueError("ID sekolah tidak valid.")
        return identifier

    def serve_static(self, path: str) -> None:
        if path == "/download/template":
            template_path = ROOT / TEMPLATE_FILENAME
            if not template_path.is_file():
                self.send_error(404, "Template tidak ditemukan")
                return
            body = template_path.read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{TEMPLATE_FILENAME}"',
            )
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ("", "/"):
            path = "/index.html"
        allowed = {"/index.html": ("index.html", "text/html; charset=utf-8"),
                   "/styles.css": ("styles.css", "text/css; charset=utf-8"),
                   "/app.js": ("app.js", "text/javascript; charset=utf-8")}
        if path not in allowed:
            self.send_error(404, "Not found")
            return
        filename, content_type = allowed[path]
        body = (ROOT / filename).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_error(self, fmt: str, *args: object) -> None:
        message = fmt % args if args else fmt
        print(f"[{self.log_date_time_string()}] ERROR {message}")


def main() -> None:
    with SEED_LOCK, database_connection() as connection:
        seed_database(connection)
    server = ThreadingHTTPServer((HOST, PORT), APIHandler)
    print(f"Ruang Mutu berjalan di http://{HOST}:{PORT}")
    print(f"Akun demo: admin@ruangmutu.id, kepala@ruangmutu.id, kabid@ruangmutu.id, pengawas@ruangmutu.id (kata sandi: {DEMO_PASSWORD})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer dihentikan.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
