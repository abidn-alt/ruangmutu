PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('admin_kabupaten', 'kepala_dinas', 'kabid_smp', 'pengawas_sekolah')),
    district_scope TEXT NOT NULL DEFAULT '*',
    password_salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS schools (
    id INTEGER PRIMARY KEY,
    npsn TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    district TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('Negeri', 'Swasta')),
    address TEXT NOT NULL DEFAULT '',
    principal_name TEXT,
    principal_nip TEXT,
    accreditation_status TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dimensions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    weight REAL NOT NULL CHECK (weight >= 0 AND weight <= 1),
    indicators TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dimension_indicators (
    id TEXT PRIMARY KEY,
    dimension_id TEXT NOT NULL REFERENCES dimensions(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    UNIQUE (dimension_id, name)
);

CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY,
    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    teacher_attendance REAL NOT NULL CHECK (teacher_attendance BETWEEN 0 AND 100),
    student_attendance REAL NOT NULL CHECK (student_attendance BETWEEN 0 AND 100),
    bosp_absorption REAL NOT NULL CHECK (bosp_absorption BETWEEN 0 AND 100),
    literacy_score REAL NOT NULL CHECK (literacy_score BETWEEN 0 AND 100),
    numeracy_score REAL NOT NULL CHECK (numeracy_score BETWEEN 0 AND 100),
    dropout_rate REAL NOT NULL CHECK (dropout_rate >= 0),
    student_count INTEGER CHECK (student_count >= 0),
    rombel_count INTEGER CHECK (rombel_count >= 0),
    teacher_count INTEGER CHECK (teacher_count >= 0),
    education_staff_count INTEGER CHECK (education_staff_count >= 0),
    achievement_count INTEGER NOT NULL DEFAULT 0 CHECK (achievement_count >= 0),
    UNIQUE (school_id, year)
);

CREATE TABLE IF NOT EXISTS school_resource_snapshots (
    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    student_count INTEGER CHECK (student_count >= 0),
    rombel_count INTEGER CHECK (rombel_count >= 0),
    teacher_count INTEGER CHECK (teacher_count >= 0),
    education_staff_count INTEGER CHECK (education_staff_count >= 0),
    PRIMARY KEY (school_id, year)
);

CREATE TABLE IF NOT EXISTS dimension_scores (
    assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    dimension_id TEXT NOT NULL REFERENCES dimensions(id),
    score REAL NOT NULL CHECK (score BETWEEN 0 AND 100),
    PRIMARY KEY (assessment_id, dimension_id)
);

CREATE TABLE IF NOT EXISTS indicator_scores (
    assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    indicator_id TEXT NOT NULL REFERENCES dimension_indicators(id),
    score REAL NOT NULL CHECK (score BETWEEN 0 AND 100),
    PRIMARY KEY (assessment_id, indicator_id)
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY,
    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('tinggi', 'sedang', 'rendah')),
    message TEXT NOT NULL,
    acknowledged_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (school_id, year, type)
);

CREATE TABLE IF NOT EXISTS interventions (
    id INTEGER PRIMARY KEY,
    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    start_date TEXT NOT NULL,
    end_date TEXT,
    status TEXT NOT NULL DEFAULT 'direncanakan'
        CHECK (status IN ('direncanakan', 'berjalan', 'selesai')),
    baseline_score REAL,
    outcome_score REAL
);

CREATE INDEX IF NOT EXISTS idx_assessments_year ON assessments(year);
CREATE INDEX IF NOT EXISTS idx_assessments_school_year ON assessments(school_id, year);
CREATE INDEX IF NOT EXISTS idx_schools_district ON schools(district);
CREATE INDEX IF NOT EXISTS idx_alerts_year_severity ON alerts(year, severity);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_indicator_scores_indicator ON indicator_scores(indicator_id);
