const TOKEN_KEY = "ruangmutu-session";
const COLOR = { indigo: "#6263e6", mint: "#44c2a0", grid: "#eef0f5" };
const DISTRICT_POINTS = [
  ["Aikmel", 193, 91], ["Jerowaru", 121, 160], ["Keruak", 204, 139],
  ["Labuhan Haji", 184, 131], ["Masbagik", 174, 106], ["Montong Gading", 164, 90],
  ["Pringgabaya", 229, 89], ["Pringgasela", 154, 104], ["Sakra", 161, 143],
  ["Sakra Barat", 139, 137], ["Sakra Timur", 183, 151], ["Sambelia", 240, 40],
  ["Selong", 192, 119], ["Sembalun", 217, 63], ["Sikur", 145, 115],
  ["Sukamulia", 181, 115], ["Suralaga", 190, 102], ["Terara", 125, 113],
  ["Wanasaba", 211, 85], ["Suela", 207, 100], ["Lenek", 198, 83],
];
let sessionToken = localStorage.getItem(TOKEN_KEY);
let dashboardData = null;
let currentUser = null;
let indicatorCatalog = null;
let visibleSchoolCount = 8;
let toastTimer;

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

async function api(path, options = {}) {
  const headers = { ...(options.body ? { "Content-Type": "application/json" } : {}), ...(sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {}), ...options.headers };
  const response = await fetch(path, { ...options, headers });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && !path.includes("/auth/login")) logout(false);
    throw new Error(payload.error || `Permintaan gagal (${response.status}).`);
  }
  return payload;
}

function initials(name = "") {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase() || "RM";
}

function showToast(message, isError = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 3200);
}

function displayError(error) {
  showToast(error.message || "Terjadi kesalahan. Silakan coba kembali.", true);
}

async function login(email, password) {
  const response = await api("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  sessionToken = response.token;
  localStorage.setItem(TOKEN_KEY, sessionToken);
  setUser(response.user);
  $("#login-screen").classList.add("hidden");
  $("#app-screen").classList.remove("hidden");
  await loadDashboard();
}

function setUser(user) {
  currentUser = user;
  $("#user-name").textContent = user.name;
  $("#user-role").textContent = user.role_label;
  $("#user-avatar").textContent = initials(user.name);
  $("#top-avatar").textContent = initials(user.name);
  $("#greeting-name").textContent = user.role_label;
  const importButton = $("#import-data-button");
  const canImport = user.role === "admin_kabupaten";
  importButton.disabled = !canImport;
  importButton.title = canImport
    ? "Impor CSV profil sekolah"
    : "Hanya admin kabupaten yang dapat mengimpor data";
  $("#today-label").textContent = new Intl.DateTimeFormat("id-ID", {
    weekday: "long", day: "numeric", month: "long", year: "numeric",
  }).format(new Date()).toLocaleUpperCase("id-ID");
}

function logout(showMessage = true) {
  const token = sessionToken;
  sessionToken = null;
  localStorage.removeItem(TOKEN_KEY);
  $("#app-screen").classList.add("hidden");
  $("#login-screen").classList.remove("hidden");
  if (token) fetch("/api/auth/logout", { method: "DELETE", headers: { Authorization: `Bearer ${token}` } }).catch(() => {});
  if (showMessage) showToast("Anda telah keluar dari dashboard.");
}

async function restoreSession() {
  if (!sessionToken) return;
  try {
    const response = await api("/api/auth/me");
    setUser(response.user);
    $("#login-screen").classList.add("hidden");
    $("#app-screen").classList.remove("hidden");
    await loadDashboard();
  } catch (error) {
    if (error.message) showToast(error.message, true);
  }
}

async function loadDashboard() {
  const year = Number($("#year-filter").value);
  $("#refresh-button").classList.add("is-refreshing");
  try {
    dashboardData = await api(`/api/dashboard?year=${year}`);
    renderDashboard();
    $("#last-updated").textContent = new Intl.DateTimeFormat("id-ID", { hour: "2-digit", minute: "2-digit" }).format(new Date(dashboardData.updated_at));
  } catch (error) {
    displayError(error);
  } finally {
    $("#refresh-button").classList.remove("is-refreshing");
  }
}

function renderDashboard() {
  if (!dashboardData) return;
  const { summary, schools, districts, trend, alerts, insights } = dashboardData;
  $("#kpi-total").textContent = formatNumber(summary.total);
  $("#kpi-assessed").textContent = `${formatNumber(summary.assessed)} dinilai`;
  $("#kpi-districts").textContent = `${summary.districts} kecamatan`;
  $("#kpi-excellent").textContent = formatNumber(summary.excellent);
  $("#kpi-excellent-change").textContent = summary.assessed ? `↑ ${summary.average}/100` : "Belum ada skor";
  $("#kpi-growing").textContent = formatNumber(summary.growing);
  $("#kpi-stagnant").textContent = formatNumber(summary.stagnant);
  $("#kpi-declining").textContent = formatNumber(summary.declining);
  $("#kpi-priority").textContent = formatNumber(summary.priority);
  $("#nav-school-count").textContent = summary.total;
  $("#nav-alert-count").textContent = alerts.length;
  $("#district-data-year").textContent = `Tahun ${dashboardData.year}`;
  const districtFilter = $("#district-filter");
  const selectedDistrict = districtFilter.value;
  districtFilter.replaceChildren(new Option("Semua kecamatan", ""));
  [...districts].sort((a, b) => a.name.localeCompare(b.name, "id")).forEach((district) => {
    districtFilter.add(new Option(district.name, district.name));
  });
  districtFilter.value = selectedDistrict;
  $("#total-public-schools").textContent = formatNumber(summary.public_schools);
  $("#total-private-schools").textContent = formatNumber(summary.private_schools);
  $("#total-students").textContent = formatNumber(summary.students);
  $("#total-classrooms").textContent = formatNumber(summary.classrooms);
  $("#total-teachers").textContent = formatNumber(summary.teachers);
  $("#total-education-staff").textContent = formatNumber(summary.education_staff);
  $("#resource-coverage").textContent = `Jumlah sekolah terdaftar: ${formatNumber(summary.total)} (${formatNumber(summary.assessed)} memiliki penilaian). Data siswa tersedia dari ${formatNumber(summary.student_coverage)} sekolah; rombel ${formatNumber(summary.classroom_coverage)}; guru ${formatNumber(summary.teacher_coverage)}; tenaga kependidikan ${formatNumber(summary.staff_coverage)}. Nilai kosong tidak dihitung sebagai nol.`;
  $("#map-average").innerHTML = summary.assessed
    ? `${summary.average}<small>/100</small>`
    : '—<small>belum dinilai</small>';
  $("#map-best-district").textContent = summary.assessed ? districts.find((item) => item.average != null)?.name || "—" : "Belum dinilai";
  $("#trend-footnote").textContent = summary.assessed
    ? `${summary.change >= 0 ? "Indeks mutu meningkat" : "Indeks mutu menurun"} ${Math.abs(summary.change)} poin dibanding tahun sebelumnya. Prediksi rerata ${insights.forecast_average}/100.`
    : `Belum ada data penilaian untuk tahun ${dashboardData.year}.`;
  $(".chart-years").textContent = "Indeks per tahun";
  $("#insight-summary").textContent = insights.summary;
  renderTrend(trend);
  renderMap(districts);
  renderDistricts(districts);
  renderDistrictStats(districts);
  renderRecommendations(insights.recommendations);
  renderAlerts(alerts);
  renderSchools(schools);
  configureAssessmentButton();
}

function formatNumber(value) {
  return new Intl.NumberFormat("id-ID").format(value ?? 0);
}

function configureAssessmentButton() {
  const button = $("#open-assessment-button");
  const canAssess = ["admin_kabupaten", "kabid_smp", "pengawas_sekolah"].includes(currentUser?.role);
  button.classList.toggle("hidden", !canAssess);
  if (!canAssess || !dashboardData) return;
  const remaining = dashboardData.schools.filter((school) => !school.assessed).length;
  button.disabled = remaining === 0;
  button.textContent = remaining === 0 ? "Tahun ini lengkap" : `＋ Input penilaian (${formatNumber(remaining)})`;
  button.title = remaining === 0
    ? `Semua sekolah telah memiliki penilaian tahun ${dashboardData.year}.`
    : `Catat penilaian untuk salah satu dari ${remaining} sekolah yang belum dinilai.`;
}

async function openAssessmentDialog() {
  if (!dashboardData) return;
  try {
    if (!indicatorCatalog) indicatorCatalog = await api("/api/indicators");
    const schools = [...dashboardData.schools].sort((a, b) => a.name.localeCompare(b.name, "id"));
    const availableSchools = schools.filter((school) => !school.assessed);
    if (!availableSchools.length) {
      showToast(`Semua sekolah telah dinilai untuk tahun ${dashboardData.year}.`);
      return;
    }

    $("#assessment-school").innerHTML = schools.map((school) => `
      <option value="${school.id}" ${school.assessed ? "disabled" : ""}>
        ${escapeHTML(school.name)} · ${escapeHTML(school.district)}${school.assessed ? " · sudah dinilai" : ""}
      </option>`).join("");
    $("#assessment-year").textContent = dashboardData.year;
    $("#assessment-indicators").innerHTML = indicatorCatalog.dimensions.map((dimension, index) => {
      const indicators = indicatorCatalog.indicators.filter((item) => item.dimension_id === dimension.id);
      return `<details class="assessment-dimension" ${index === 0 ? "open" : ""}>
        <summary><span>${escapeHTML(dimension.name)} <small>${Math.round(dimension.weight * 100)}%</small></span><strong id="assessment-progress-${escapeHTML(dimension.id)}">0/${indicators.length}</strong></summary>
        <div class="assessment-indicator-grid">${indicators.map((indicator) => `
          <label for="assessment-${escapeHTML(indicator.id)}">
            <span>${escapeHTML(indicator.name)}</span>
            <input id="assessment-${escapeHTML(indicator.id)}" name="${escapeHTML(indicator.id)}" type="number" min="0" max="100" step="0.1" placeholder="0–100" required data-assessment-indicator data-dimension-id="${escapeHTML(dimension.id)}">
          </label>`).join("")}</div>
      </details>`;
    }).join("");
    $("#assessment-form").reset();
    $("#assessment-school").value = String(availableSchools[0].id);
    $("#assessment-year").textContent = dashboardData.year;
    $("#assessment-dialog").showModal();
  } catch (error) {
    displayError(error);
  }
}

function updateAssessmentProgress() {
  if (!indicatorCatalog) return;
  indicatorCatalog.dimensions.forEach((dimension) => {
    const fields = $$(`[data-assessment-indicator][data-dimension-id="${dimension.id}"]`, $("#assessment-form"));
    const entered = fields.filter((field) => field.value !== "").length;
    $(`#assessment-progress-${dimension.id}`).textContent = `${entered}/${fields.length}`;
  });
}

function renderTrend(points) {
  const element = $("#trend-chart");
  $("#trend-year-values").innerHTML = points.map((point) => `
    <div class="trend-year-value">
      <span>${point.year}</span>
      <strong>${point.quality == null ? "—" : `${point.quality}<small>/100</small>`}</strong>
    </div>`).join("");
  const width = 620;
  const height = 126;
  const padding = { top: 8, right: 12, bottom: 21, left: 3 };
  const x = (index) => padding.left + index * (width - padding.left - padding.right) / Math.max(points.length - 1, 1);
  const y = (value) => padding.top + (100 - value) * (height - padding.top - padding.bottom) / 100;
  const series = [
    { key: "quality", color: COLOR.indigo },
    { key: "learning", color: COLOR.mint },
  ];
  const gridLines = [100, 80, 60, 40, 20].map((value) =>
    `<line x1="${padding.left}" y1="${y(value)}" x2="${width - padding.right}" y2="${y(value)}" stroke="${COLOR.grid}" stroke-dasharray="3 4"/>`,
  ).join("");
  const labels = points.map((point, index) =>
    `<text x="${x(index)}" y="${height - 3}" text-anchor="middle" fill="#9ba4b3" font-size="9">${point.year}</text>`,
  ).join("");
  const paths = series.map(({ key, color }) => {
    const valid = points.map((point, index) => ({ index, value: point[key] })).filter((point) => point.value != null);
    const line = valid.map((point, index) => `${index ? "L" : "M"}${x(point.index)},${y(point.value)}`).join(" ");
    const circles = valid.map((point) => `<circle cx="${x(point.index)}" cy="${y(point.value)}" r="3" fill="#fff" stroke="${color}" stroke-width="2"><title>${point.value}</title></circle>`).join("");
    return `<path d="${line}" fill="none" stroke="${color}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>${circles}`;
  }).join("");
  element.innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">${gridLines}${paths}${labels}</svg>`;
}

function renderMap(districts) {
  const map = $("#district-map");
  $$(".map-dot", map).forEach((dot) => dot.remove());
  const ranked = new Map(districts.map((district) => [district.name, district]));
  DISTRICT_POINTS.forEach(([name, left, top]) => {
    const value = ranked.get(name);
    if (!value || value.average == null) return;
    const dot = document.createElement("button");
    dot.className = "map-dot";
    dot.style.left = `${left / 3.1}%`;
    dot.style.top = `${top / 2.04}%`;
    dot.style.backgroundColor = value.average >= 80 ? "#35b78e" : value.average >= 68 ? "#e8b254" : "#e77e76";
    dot.title = `${name}: ${value.average}/100 · ${value.count} sekolah`;
    dot.setAttribute("aria-label", dot.title);
    dot.addEventListener("click", () => {
      $("#school-search").value = "";
      $("#district-filter").value = name;
      visibleSchoolCount = 8;
      renderSchools(dashboardData.schools);
      $("#schools").scrollIntoView({ behavior: "smooth" });
    });
    map.append(dot);
  });
}

function renderDistricts(districts) {
  const rankedDistricts = districts.filter((item) => item.average != null);
  const maximum = Math.max(...rankedDistricts.map((item) => item.average), 1);
  $("#district-rankings").innerHTML = rankedDistricts.length ? rankedDistricts.slice(0, 5).map((item, index) => `
    <div class="ranking-row">
      <span class="rank-number ${index < 3 ? "top-rank" : ""}">${String(index + 1).padStart(2, "0")}</span>
      <span class="rank-name" title="${escapeHTML(item.name)}">${escapeHTML(item.name)}</span>
      <span class="rank-bar"><span class="rank-fill" style="display:block;width:${Math.max(3, item.average / maximum * 100)}%"></span></span>
      <span class="rank-score">${item.average}</span>
    </div>`).join("") : '<div class="alert-empty">Belum ada penilaian pada tahun ini.</div>';
  $(".rank-year").textContent = `Tahun ${dashboardData.year}`;
}

function renderDistrictStats(districts) {
  const ordered = [...districts].sort((a, b) => a.name.localeCompare(b.name, "id"));
  $("#district-stats-body").innerHTML = ordered.map((item) => `
    <tr>
      <td class="district-name-cell">${escapeHTML(item.name)}</td>
      <td class="district-count-cell">${formatNumber(item.school_count)}</td>
      <td>${formatNumber(item.public_schools)}</td>
      <td>${formatNumber(item.private_schools)}</td>
      <td>${item.student_coverage ? formatNumber(item.students) : "—"}</td>
      <td>${item.classroom_coverage ? formatNumber(item.classrooms) : "—"}</td>
      <td>${item.teacher_coverage ? formatNumber(item.teachers) : "—"}</td>
      <td>${item.staff_coverage ? formatNumber(item.education_staff) : "—"}</td>
      <td>${item.average == null ? "Belum dinilai" : `${item.average}/100`}</td>
    </tr>`).join("");
}

function renderRecommendations(recommendations) {
  $("#recommendations").innerHTML = recommendations.slice(0, 4).map((item) => `
    <div class="recommendation-item"><span class="recommendation-check">✓</span><span>${escapeHTML(item)}</span></div>`).join("");
}

function renderAlerts(alerts) {
  $("#alert-total").textContent = `${alerts.length} sinyal`;
  if (!alerts.length) {
    $("#alert-list").innerHTML = `<div class="alert-empty">Tidak ada sinyal peringatan untuk tahun ${dashboardData.year}. Lanjutkan pemantauan rutin.</div>`;
    return;
  }
  $("#alert-list").innerHTML = alerts.slice(0, 4).map((alert) => `
    <button class="alert-row" data-school-id="${alert.school_id}">
      <span class="alert-symbol ${alert.severity === "tinggi" ? "alert-symbol-high" : "alert-symbol-medium"}">${alert.severity === "tinggi" ? "!" : "↗"}</span>
      <span class="alert-copy"><strong>${escapeHTML(alert.title)}</strong><small>${escapeHTML(alert.school)} · ${escapeHTML(alert.district)}</small></span>
      <span class="alert-value">${escapeHTML(alert.value)}</span><span class="alert-chevron">›</span>
    </button>`).join("");
}

function filterSchools(schools) {
  const search = $("#school-search").value.trim().toLocaleLowerCase("id-ID");
  const district = $("#district-filter").value;
  const status = $("#status-filter").value;
  const trend = $("#trend-filter").value;
  return schools.filter((school) =>
    (!search || [school.name, school.npsn, school.district].some((value) => value.toLocaleLowerCase("id-ID").includes(search)))
    && (!district || school.district === district)
    && (!status || school.status === status)
    && (!trend || school.trend === trend),
  );
}

function renderSchools(schools) {
  const filtered = filterSchools(schools);
  const shown = filtered.slice(0, visibleSchoolCount);
  $("#school-count-label").textContent = `Menampilkan ${shown.length} dari ${filtered.length} sekolah`;
  $("#load-more-button").classList.toggle("hidden", filtered.length <= visibleSchoolCount);
  $("#schools-table-body").innerHTML = shown.length ? shown.map((school) => {
    const trendClass = !school.assessed ? "trend-unrated" : school.trend.includes("Menurun") ? "trend-negative" : school.trend === "Stabil" ? "trend-stable" : "trend-positive";
    const riskClass = !school.assessed ? "risk-unrated" : school.risk === "Tinggi" ? "risk-high" : school.risk === "Sedang" ? "risk-medium" : "risk-low";
    const changeClass = !school.assessed ? "" : school.change < 0 ? "change-down" : "change-up";
    const trendArrow = !school.assessed ? "—" : school.trend.includes("Menurun") ? "↘" : school.trend === "Stabil" ? "→" : "↗";
    return `<tr>
      <td><div class="school-cell"><span class="school-monogram">${escapeHTML(initials(school.name))}</span><span><span class="school-title">${escapeHTML(school.name)}</span><span class="school-code">${escapeHTML(school.npsn)}</span></span></div></td>
      <td>${escapeHTML(school.principal_name || "Belum diisi")}</td>
      <td>${escapeHTML(school.accreditation_status || "—")}</td>
      <td>${escapeHTML(school.district)}</td>
      <td><span class="status-pill status-${school.status.toLowerCase()}">${escapeHTML(school.status)}</span></td>
      <td>${school.student_count == null ? "—" : formatNumber(school.student_count)}</td>
      <td>${school.rombel_count == null ? "—" : formatNumber(school.rombel_count)}</td>
      <td>${school.teacher_count == null ? "—" : formatNumber(school.teacher_count)}</td>
      <td>${school.education_staff_count == null ? "—" : formatNumber(school.education_staff_count)}</td>
      <td class="score-cell">${school.quality_score == null ? "—" : `${school.quality_score}<span style="color:#a7afbd;font-weight:400"> /100</span>`}</td>
      <td class="${changeClass}">${school.change == null ? "—" : `${school.change > 0 ? "+" : ""}${school.change} poin`}</td>
      <td><span class="trend-pill ${trendClass}">${trendArrow} ${escapeHTML(school.trend)}</span></td>
      <td><span class="risk-pill ${riskClass}">${escapeHTML(school.risk)}</span></td>
      <td><button class="row-action" data-school-id="${school.id}" aria-label="Detail ${escapeHTML(school.name)}">›</button></td>
    </tr>`;
  }).join("") : `<tr><td colspan="14" class="table-empty">Tidak ada sekolah yang sesuai dengan filter.</td></tr>`;
}

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

async function openSchoolDetail(schoolId) {
  try {
    const result = await api(`/api/schools/${schoolId}?year=${dashboardData.year}`);
    const record = result.school;
    const years = result.years;
    const trend = record.trend;
    const dimensions = record.dimensions.map((item) => `
      <div class="dimension-row"><span>${escapeHTML(item.name)}</span><span class="dimension-bar"><span class="dimension-fill" style="display:block;width:${item.score}%"></span></span><span class="dimension-value">${item.score}</span></div>`).join("");
    const indicatorGroups = record.dimensions.map((dimension) => {
      const indicators = record.indicators.filter((item) => item.dimension_id === dimension.id);
      return `<details class="indicator-detail"><summary>${escapeHTML(dimension.name)} <span>${indicators.length} indikator</span></summary>${indicators.map((item) => `
        <div class="indicator-row"><span>${escapeHTML(item.name)}</span><strong>${item.score}</strong></div>`).join("")}</details>`;
    }).join("");
    const yearPills = years.map((item) => `<span class="dialog-year">${item.year}<strong>${item.quality_score}</strong></span>`).join("");
    const canEditProfile = ["admin_kabupaten", "kabid_smp"].includes(currentUser?.role);
    const profileContent = canEditProfile
      ? `<form class="school-profile-form" data-school-id="${record.id}">
          <label>Nama kepala sekolah<input name="principal_name" maxlength="160" value="${escapeHTML(record.principal_name || "")}" placeholder="Nama sesuai data resmi"></label>
          <label>NIP kepala sekolah<input name="principal_nip" inputmode="numeric" pattern="[0-9]{18}" maxlength="18" value="${escapeHTML(record.principal_nip || "")}" placeholder="18 digit; kosongkan jika tidak tersedia"></label>
          <label>Status akreditasi sekolah<input name="accreditation_status" maxlength="40" value="${escapeHTML(record.accreditation_status || "")}" placeholder="Contoh: A, B, C, Unggul, Baik"></label>
          <button class="button button-primary button-small" type="submit">Simpan profil sekolah</button>
        </form>`
      : `<div class="school-profile-grid"><div><span>Nama kepala sekolah</span><strong>${escapeHTML(record.principal_name || "Belum tersedia")}</strong></div><div><span>NIP kepala sekolah</span><strong>${escapeHTML(record.principal_nip || "Belum tersedia")}</strong></div><div><span>Status akreditasi</span><strong>${escapeHTML(record.accreditation_status || "Belum tersedia")}</strong></div></div>`;
    const assessmentContent = record.assessed
      ? `<div class="dialog-kpis"><div class="dialog-kpi"><span>Indeks mutu ${record.year}</span><strong>${record.quality_score}<small style="font-size:10px;color:#99a2b1"> /100</small></strong></div><div class="dialog-kpi"><span>Risiko sekolah</span><strong>${escapeHTML(record.risk)}</strong></div><div class="dialog-kpi"><span>Prediksi ${record.year + 1}</span><strong>${record.forecast}</strong></div></div>
        <div class="dialog-section-title">Analisis gap (poin indeks)</div><div class="dialog-note">Dari rerata kecamatan: ${record.gaps.district_average > 0 ? "+" : ""}${record.gaps.district_average} poin · Dari rerata kabupaten: ${record.gaps.county_average > 0 ? "+" : ""}${record.gaps.county_average} poin · Dari sekolah terbaik (${escapeHTML(record.gaps.best_school_name)}): ${record.gaps.best_school} poin.</div>
        <div class="dialog-section-title">Skor tujuh dimensi</div>${dimensions}<div class="indicator-groups">${indicatorGroups}</div>
        <div class="dialog-section-title">Tren indeks mutu · ${escapeHTML(trend)}</div><div class="dialog-trend">${yearPills}</div>
        <div class="dialog-section-title">Indikator peringatan</div><div class="dialog-note">${record.alerts.length ? record.alerts.map((item) => escapeHTML(item.title)).join("<br>") : "Tidak ada indikator yang melewati ambang peringatan pada tahun ini."}<br><br>Kehadiran guru ${record.teacher_attendance}% · Serapan BOSP ${record.bosp_absorption}% · Literasi ${record.literacy_score} · Numerasi ${record.numeracy_score} · Putus sekolah ${record.dropout_rate}%</div>`
      : '<div class="dialog-note">Belum ada data penilaian mutu untuk sekolah ini. Data profil dan sumber daya yang tersedia tetap dapat digunakan.</div>';
    $("#school-dialog-content").innerHTML = `
      <div class="dialog-header"><div><div class="section-kicker">PROFIL SEKOLAH</div><h2>${escapeHTML(record.name)}</h2><p>${escapeHTML(record.district)} · ${escapeHTML(record.status)} · NPSN ${escapeHTML(record.npsn)}</p></div><button class="dialog-close" aria-label="Tutup">×</button></div>
      <div class="dialog-body">
        <div class="dialog-section-title">Identitas kepala sekolah &amp; akreditasi</div>${profileContent}
        <div class="dialog-section-title">Jumlah siswa &amp; sumber daya sekolah · ${record.year}</div><div class="school-resource-grid"><div><span>Siswa</span><strong>${record.student_count == null ? "Belum tersedia" : formatNumber(record.student_count)}</strong></div><div><span>Rombel</span><strong>${record.rombel_count == null ? "Belum tersedia" : formatNumber(record.rombel_count)}</strong></div><div><span>Guru</span><strong>${record.teacher_count == null ? "Belum tersedia" : formatNumber(record.teacher_count)}</strong></div><div><span>Tenaga kependidikan</span><strong>${record.education_staff_count == null ? "Belum tersedia" : formatNumber(record.education_staff_count)}</strong></div></div>
        ${assessmentContent}
      </div>`;
    $("#school-dialog").showModal();
  } catch (error) {
    displayError(error);
  }
}

function downloadCSV(schools, filename = "ruang-mutu-sekolah.csv") {
  const headings = ["NPSN", "Nama sekolah", "Nama kepala sekolah", "NIP kepala sekolah", "Status akreditasi", "Kecamatan", "Status", "Tahun", "Jumlah siswa", "Jumlah rombel", "Jumlah guru", "Jumlah tenaga kependidikan", "Indeks mutu", "Perubahan", "Tren 5 tahun", "Risiko", "Prediksi tahun berikutnya"];
  const rows = schools.map((item) => [item.npsn, item.name, item.principal_name, item.principal_nip, item.accreditation_status, item.district, item.status, item.year, item.student_count, item.rombel_count, item.teacher_count, item.education_staff_count, item.quality_score, item.change, item.trend, item.risk, item.forecast]);
  const csv = [headings, ...rows].map((row) => row.map((field) => `"${String(field ?? "").replace(/"/g, '""')}"`).join(",")).join("\r\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" }));
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}

async function downloadXLSX(year) {
  const response = await fetch(`/api/exports/schools.xlsx?year=${year}`, {
    headers: sessionToken ? { Authorization: ["Bearer", sessionToken].join(" ") } : {},
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401) logout(false);
    throw new Error(payload.error || `Unduhan gagal (${response.status}).`);
  }
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `ruang-mutu-sekolah-${year}.xlsx`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function openSchoolPDF(schools, year) {
  const printWindow = window.open("", "_blank");
  if (!printWindow) throw new Error("Jendela PDF diblokir browser. Izinkan pop-up lalu coba lagi.");
  const headings = ["NPSN", "Nama sekolah", "Kepala sekolah", "NIP kepala sekolah", "Akreditasi", "Kecamatan", "Status", "Tahun", "Siswa", "Rombel", "Guru", "Tenaga kependidikan", "Indeks mutu", "Perubahan", "Tren", "Risiko", "Prediksi"];
  const columns = ["npsn", "name", "principal_name", "principal_nip", "accreditation_status", "district", "status", "year", "student_count", "rombel_count", "teacher_count", "education_staff_count", "quality_score", "change", "trend", "risk", "forecast"];
  const tableRows = schools.map((school) => `<tr>${columns.map((key) => `<td>${escapeHTML(school[key] == null ? "" : String(school[key]))}</td>`).join("")}</tr>`).join("");
  printWindow.document.write(`<!doctype html><html lang="id"><head><meta charset="utf-8"><title>Data SMP Lombok Timur ${year}</title><style>
    @page{size:landscape;margin:10mm}body{font:9px Arial,sans-serif;color:#17243a}h1{font-size:16px;margin:0 0 4px}p{margin:0 0 12px;color:#526078}table{width:100%;border-collapse:collapse}th,td{border:1px solid #cbd2df;padding:4px;text-align:left;overflow-wrap:anywhere}th{background:#28316e;color:#fff}tr:nth-child(even){background:#f3f5fa}
    </style></head><body><h1>Data SMP Kabupaten Lombok Timur</h1><p>Tahun ${year} · ${schools.length} sekolah · Indeks mutu dan indikator penilaian hanya terisi jika tersedia.</p><table><thead><tr>${headings.map((heading) => `<th>${escapeHTML(heading)}</th>`).join("")}</tr></thead><tbody>${tableRows}</tbody></table><script>window.onload=()=>window.print();</script></body></html>`);
  printWindow.document.close();
}

$("#download-data-button").addEventListener("click", () => {
  const options = $("#download-data-options");
  const isExpanded = $("#download-data-button").getAttribute("aria-expanded") === "true";
  $("#download-data-button").setAttribute("aria-expanded", String(!isExpanded));
  options.hidden = isExpanded;
});
$("#download-data-options").addEventListener("click", async (event) => {
  const option = event.target.closest("[data-export-format]");
  if (!option || !dashboardData) return;
  const format = option.dataset.exportFormat;
  const schools = dashboardData.schools;
  const year = dashboardData.year;
  $("#download-data-options").hidden = true;
  $("#download-data-button").setAttribute("aria-expanded", "false");
  try {
    if (format === "xlsx") await downloadXLSX(year);
    if (format === "csv") downloadCSV(schools, `ruang-mutu-sekolah-${year}.csv`);
    if (format === "pdf") openSchoolPDF(schools, year);
  } catch (error) {
    displayError(error);
  }
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".download-menu")) {
    $("#download-data-options").hidden = true;
    $("#download-data-button").setAttribute("aria-expanded", "false");
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    $("#download-data-options").hidden = true;
    $("#download-data-button").setAttribute("aria-expanded", "false");
  }
});

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const errorElement = $("#login-error");
  errorElement.textContent = "";
  const button = $(".login-button");
  button.disabled = true;
  button.textContent = "Memeriksa akses...";
  try {
    await login($("#login-email").value.trim(), $("#login-password").value);
  } catch (error) {
    errorElement.textContent = error.message;
  } finally {
    button.disabled = false;
    button.innerHTML = 'Masuk ke dashboard <span>→</span>';
  }
});

$("#fill-demo").addEventListener("click", () => {
  $("#login-email").value = "kepala@ruangmutu.id";
  $("#login-password").value = "Dikbud123";
});
$("#import-data-button").addEventListener("click", () => $("#import-data-file").click());
$("#import-data-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const button = $("#import-data-button");
  button.disabled = true;
  try {
    if (file.size > 250_000) throw new Error("Ukuran CSV maksimal 250 KB.");
    let csv;
    try {
      csv = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
    } catch {
      throw new Error("CSV harus menggunakan encoding UTF-8.");
    }
    const result = await api("/api/import/schools", {
      method: "POST",
      body: JSON.stringify({ csv }),
    });
    showToast(`Impor selesai: ${result.inserted} sekolah baru, ${result.updated} diperbarui, ${result.resource_snapshots} snapshot disimpan.`);
    await loadDashboard();
  } catch (error) {
    displayError(error);
  } finally {
    button.disabled = false;
    event.target.value = "";
  }
});
$("#logout-button").addEventListener("click", () => logout());
$("#refresh-button").addEventListener("click", loadDashboard);
$("#year-filter").addEventListener("change", () => {
  visibleSchoolCount = 8;
  loadDashboard();
});
$("#school-search").addEventListener("input", () => renderSchools(dashboardData?.schools || []));
["district-filter", "status-filter", "trend-filter"].forEach((selector) => {
  $(`#${selector}`).addEventListener("change", () => {
    visibleSchoolCount = 8;
    renderSchools(dashboardData?.schools || []);
  });
});
$("#load-more-button").addEventListener("click", () => {
  visibleSchoolCount = Number.MAX_SAFE_INTEGER;
  renderSchools(dashboardData?.schools || []);
});
$("#all-schools-export").addEventListener("click", () => downloadCSV(filterSchools(dashboardData?.schools || [])));
$("#export-button").addEventListener("click", () => downloadCSV(dashboardData?.schools || [], `ruang-mutu-ringkasan-${dashboardData?.year || ""}.csv`));
$("#show-priority-button").addEventListener("click", () => {
  $("#trend-filter").value = "";
  $("#school-search").value = "";
  $("#district-filter").value = "";
  $("#status-filter").value = "";
  visibleSchoolCount = Number.MAX_SAFE_INTEGER;
  renderSchools((dashboardData?.schools || []).filter((school) => school.risk === "Tinggi"));
  $("#schools").scrollIntoView({ behavior: "smooth" });
});
$("#schools-table-body").addEventListener("click", (event) => {
  const button = event.target.closest("[data-school-id]");
  if (button) openSchoolDetail(button.dataset.schoolId);
});
$("#alert-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-school-id]");
  if (button) openSchoolDetail(button.dataset.schoolId);
});
$("#school-dialog").addEventListener("click", (event) => {
  if (event.target === $("#school-dialog") || event.target.closest(".dialog-close")) $("#school-dialog").close();
});
$("#school-dialog-content").addEventListener("submit", async (event) => {
  const form = event.target.closest(".school-profile-form");
  if (!form) return;
  event.preventDefault();
  const submitButton = form.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  try {
    await api(`/api/schools/${form.dataset.schoolId}`, {
      method: "PATCH",
      body: JSON.stringify(Object.fromEntries(new FormData(form))),
    });
    const schoolId = form.dataset.schoolId;
    $("#school-dialog").close();
    showToast("Profil sekolah berhasil diperbarui.");
    await loadDashboard();
    await openSchoolDetail(schoolId);
  } catch (error) {
    displayError(error);
  } finally {
    submitButton.disabled = false;
  }
});
$("#open-assessment-button").addEventListener("click", openAssessmentDialog);
$("#assessment-dialog").addEventListener("click", (event) => {
  if (event.target === $("#assessment-dialog") || event.target.closest("[data-close-assessment]")) {
    $("#assessment-dialog").close();
  }
});
$("#assessment-form").addEventListener("input", updateAssessmentProgress);
$("#assessment-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const submitButton = form.querySelector('button[type="submit"]');
  const value = (name) => form.elements.namedItem(name).value;
  const optionalInteger = (name) => value(name) === "" ? null : Number(value(name));
  const indicators = Object.fromEntries(
    $$("[data-assessment-indicator]", form).map((field) => [field.name, Number(field.value)]),
  );
  const payload = {
    school_id: Number(value("school_id")),
    year: dashboardData.year,
    teacher_attendance: Number(value("teacher_attendance")),
    student_attendance: Number(value("student_attendance")),
    bosp_absorption: Number(value("bosp_absorption")),
    literacy_score: Number(value("literacy_score")),
    numeracy_score: Number(value("numeracy_score")),
    dropout_rate: Number(value("dropout_rate")),
    student_count: optionalInteger("student_count"),
    rombel_count: optionalInteger("rombel_count"),
    teacher_count: optionalInteger("teacher_count"),
    education_staff_count: optionalInteger("education_staff_count"),
    achievement_count: optionalInteger("achievement_count") ?? 0,
    indicators,
  };
  submitButton.disabled = true;
  submitButton.textContent = "Menyimpan penilaian...";
  try {
    await api("/api/assessments", { method: "POST", body: JSON.stringify(payload) });
    $("#assessment-dialog").close();
    showToast("Penilaian tersimpan. Analisis dan sinyal peringatan diperbarui.");
    await loadDashboard();
  } catch (error) {
    displayError(error);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "Simpan penilaian";
  }
});
function setSidebarOpen(isOpen) {
  $("#sidebar").classList.toggle("open", isOpen);
  $("#sidebar-backdrop").classList.toggle("visible", isOpen);
  $("#mobile-menu").setAttribute("aria-expanded", String(isOpen));
  $("#mobile-menu").setAttribute("aria-label", isOpen ? "Tutup navigasi" : "Buka navigasi");
}

$("#mobile-menu").addEventListener("click", () => {
  setSidebarOpen(!$("#sidebar").classList.contains("open"));
});
$("#sidebar-backdrop").addEventListener("click", () => setSidebarOpen(false));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && $("#sidebar").classList.contains("open")) {
    setSidebarOpen(false);
    $("#mobile-menu").focus();
  }
});
$$(".nav-link").forEach((link) => link.addEventListener("click", () => {
  $$(".nav-link").forEach((item) => item.classList.remove("active"));
  link.classList.add("active");
  setSidebarOpen(false);
}));

restoreSession();
